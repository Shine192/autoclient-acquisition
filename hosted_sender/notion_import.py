"""Read Notion research as data; only the actual STATUS property can approve."""
import json,re
from acquisition_agent import notion_compat,delivery
from acquisition_agent.providers import text_value,rich
from .queue import digest

def value(p,name):return text_value(p.get(name,{}))
def read_lead(page,preferences):
    if page.get('archived') or page.get('in_trash'):raise ValueError('Archived record')
    p=page['properties'];key=value(p,'Deduplication Key')
    if not re.fullmatch(r'[0-9a-f]{16}',key):raise ValueError('No owned opportunity ID')
    notes=json.loads(value(p,'Research Notes'))
    if not isinstance(notes,dict) or not notes.get('source_documents'):raise ValueError('Complete structured research missing')
    observed_country=value(p,'COUNTRY')
    countries=[c for c in preferences['countries'] if notion_compat.country(c)==observed_country or c==observed_country]
    if len(countries)!=1:raise ValueError('Country missing or outside configured markets')
    doc=notes['source_documents'][0]
    lead={'id':key,'notion_page_id':page['id'],'company':''.join(t.get('plain_text',t.get('text',{}).get('content','')) for t in p.get('Name',{}).get('title',[])),
          'title':value(p,'Role'),'url':p.get('Job URL',{}).get('url') or notes.get('job_url'),
          'website':p.get('WEBSITE',{}).get('url') or '', 'country':countries[0],
          'kind':(p.get('Opportunity Type',{}).get('select') or {}).get('name'),
          'type':(p.get('Type',{}).get('select') or {}).get('name'),
          'status':(p.get('STATUS',{}).get('status') or {}).get('name','Needs Review'),
          'email':p.get('EMAIL',{}).get('email') or '',
          'contact_source_url':p.get('Contact Source URL',{}).get('url') or '',
          'remote_eligibility':(p.get('Remote Eligibility',{}).get('select') or {}).get('name','Unknown'),
          'rate_per_email':p.get('Rate Per Email',{}).get('number'),
          'currency':value(p,'Budget Currency'),
          'weekly_hours':p.get('Hours Per Week',{}).get('number'),
          'posted_at':(p.get('Posting Date',{}).get('date') or {}).get('start'),
          'discovered_at':notes.get('collected',''),'source_text':doc['text'],'source_documents':notes['source_documents'],
          'research_source_url':notes.get('source',doc['url']),'research_level':notes.get('research_level','Supplied research'),
          'research_warning':notes.get('research_warning',''),'checked_at':notes.get('checked_at',''),
          'email_candidates':notes.get('email_candidates',[]),'target_session':notes.get('target_session'),
          'location_city':notes.get('location_city',''),'industry':notes.get('industry',''),
          'target_evidence':notes.get('target_evidence',{}),'target_reasons':notes.get('target_reasons',[]),
          'country_source_url':notes.get('country_source_url',''),'country_evidence':notes.get('country_evidence',''),
          'is_demo':bool(notes.get('demo')),'score':p.get('Match Score',{}).get('number') or 0,
          'draft':{'subject':value(p,'email SUBJECT'),'body':value(p,'email body'),'evidence':notes.get('personalization_evidence',[])}}
    if lead['type']=='Startup':lead['type']='Start-up'
    return lead

def refresh(queue,notion,settings,campaign_id=None):
    pages=list(notion.query(settings['preferences']['notion_leads_source_id']))
    keys={};contacts={};output={'imported':0,'held':0,'queued':0}
    for p in pages:
        key=value(p['properties'],'Deduplication Key')
        if key:
            if key in keys:raise ValueError('Duplicate opportunity IDs in Notion; no dispatch')
            keys[key]=p
    # Finish a failed review-reset write before any old approval can be reused.
    for item in queue.db.list('outbox'):
        if item['state']!='blocked' or item.get('approval_reset_done') or item.get('attempted_at'):continue
        lead=queue.db.get('lead_'+item['lead_id'])
        page=keys.get(item['lead_id'])
        if not lead or not page:continue
        status=(page['properties'].get('STATUS',{}).get('status') or {}).get('name')
        if status=='Approve':
            notion.request('pages/'+page['id'],'PATCH',{'properties':{'STATUS':{'status':{'name':'Needs Review'}}}})
            page['properties']['STATUS']={'status':{'name':'Needs Review'}}
        def reset(tx):
            held=tx.get('outbox_'+item['id']);held['approval_reset_done']=True;tx.put('outbox_'+item['id'],held)
        queue.db.transaction(reset)
    for key,page in keys.items():
        props=page['properties'];status=(props.get('STATUS',{}).get('status') or {}).get('name')
        known=queue.db.get('lead_'+key)
        if known and known['data'].get('notion_page_id')!=page['id']:
            def relink(tx):
                saved=tx.get('lead_'+key);saved['data']['notion_page_id']=page['id'];tx.put('lead_'+key,saved)
            queue.db.transaction(relink)
        if status in ('Sent','Replied','Interview','Won','Rejected','Closed','Do Not Contact'):
            email=(props.get('EMAIL',{}).get('email') or '').lower()
            website=props.get('WEBSITE',{}).get('url') or ''
            if email and status!='Closed':
                def remember(tx):
                    for ref in ('recipient_'+digest(email),'company_'+digest(notion_compat.host(website))):
                        if not tx.get(ref):tx.put(ref,{'kind':'dedup','outbox_id':'notion-history-'+key})
                queue.db.transaction(remember)
            continue
        if status!='Approve':continue
        existing=queue.db.get('lead_'+key)
        try:
            lead=read_lead(page,settings['preferences'])
        except (ValueError,KeyError,TypeError):
            if not existing:
                output['held']+=1
                notion.request('pages/'+page['id'],'PATCH',{'properties':{'Delivery State':{'rich_text':rich('Held: complete structured research is missing. Repair and sync from the Mac dashboard.')}}})
                continue
            lead=dict(existing['data']);lead['notion_page_id']=page['id']
        # A complete local seed is kept if Notion's stored excerpts are shorter.
        if existing and sum(len(d.get('text','')) for d in existing['data'].get('source_documents',[]))>sum(len(d.get('text','')) for d in lead.get('source_documents',[])):
            prior=dict(existing['data']);prior['notion_page_id']=page['id'];lead=prior
        def save(tx):tx.put('lead_'+key,{'kind':'lead','data':lead})
        queue.db.transaction(save);output['imported']+=1
    if campaign_id or queue.control().get('delivery_model')=='notion-approval':
        from .worker import Worker
        worker=Worker(queue,settings,None,notion)
        for key,page in keys.items():
            if (page['properties'].get('STATUS',{}).get('status') or {}).get('name')!='Approve':continue
            if not queue.db.get('lead_'+key):continue
            try:
                item=worker.enqueue(key,campaign_id)
                if item['state']=='queued':output['queued']+=1
            except (ValueError,KeyError,TypeError) as exc:
                output['held']+=1
                notion.request('pages/'+page['id'],'PATCH',{'properties':{'Delivery State':{'rich_text':rich('Held: '+str(exc)[:400])}}})
    return output
