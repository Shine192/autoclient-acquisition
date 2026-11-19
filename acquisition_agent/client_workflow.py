"""Notion-backed commercial review and outcome recording. No mail transport or send operation."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .commercial import DEFAULT_QUOTE, QUOTES, EXPERIMENT, PAID_TEST_SCOPE, quote_range, region_for, portfolio_name_issue
from .providers import rich, text_value

OUTCOMES=('Not started','Positive reply','Paid test agreed','Paid test completed','Repeat client')
STOP={'Replied','Interview','Won','Rejected','Closed','Do Not Contact','Sending'}


def select(options):return {'select':{'options':[{'name':x} for x in options]}}


def schema():
    fields={'Design Quote':select(QUOTES),'Portfolio Link':{'url':{}},'Agency Experiment':{'checkbox':{}},
        'Agency Segment':select(EXPERIMENT['regions']), 'Agency Fit':{'rich_text':{}},
        'Business Signal':{'rich_text':{}}, 'Experiment Joined':{'date':{}},
        'Reply Classification':select(['Unclassified','Positive','Not interested','Automated','Other']),
        'Client Outcome':select(OUTCOMES), 'Acquisition Events':{'rich_text':{}},
        'Acquisition Minutes':{'number':{'format':'number'}}, 'Follow-up Review Log':{'rich_text':{}}}
    for stage in (1,2):
        prefix='Follow-up '+str(stage)
        fields.update({prefix+' Draft':{'rich_text':{}},
            prefix+' Review':select(['Draft','Reviewed','Held','Cancelled','Sent manually']),
            prefix+' Due':{'date':{}}, prefix+' Delivery':{'rich_text':{}},
            prefix+' Sent Time':{'date':{}}, prefix+' Receipt':{'rich_text':{}}})
    return fields


def selected(p,name):return (p.get(name,{}).get('select') or {}).get('name','')
def date(p,name):return (p.get(name,{}).get('date') or {}).get('start')
def text(p,name):return text_value(p.get(name,{}))
def timestamp():return datetime.now(timezone.utc).isoformat()


def parsed(p,name,default):
    raw=text(p,name)
    if not raw:return default
    try:value=json.loads(raw)
    except (ValueError,TypeError):raise ValueError(name+' contains invalid data; preserve and repair it before editing') from None
    if not isinstance(value,type(default)):raise ValueError(name+' has an unexpected format')
    return value


def stopped(p):
    status=(p.get('STATUS',{}).get('status') or p.get('STATUS',{}).get('select') or {}).get('name','')
    delivery=text(p,'Delivery State').lower()
    reply=text(p,'Reply Status').strip()
    return bool(status in STOP or p.get('Do Not Contact',{}).get('checkbox') or
                reply or any(word in delivery for word in ('uncertain','unresolved','suppressed','bounce')))


def due_after(value,days,zone):
    if not value:return None
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:raise ValueError('A send timestamp must include its timezone')
    dt=dt.astimezone(ZoneInfo(zone))
    while days:
        dt+=timedelta(days=1)
        if dt.weekday()<5:days-=1
    return dt.replace(hour=8,minute=0,second=0,microsecond=0).isoformat()


def source_fingerprint(p,body,stage):
    value={'recipient':p.get('EMAIL',{}).get('email'),'subject':text(p,'email SUBJECT'),
        'initial_body':text(p,'email body'),'initial_receipt':text(p,'Gmail Message ID'),
        'thread':text(p,'Gmail Thread ID'),'initial_sent':date(p,'sent time'),
        'portfolio_url':p.get('Portfolio Link',{}).get('url'),'quote':selected(p,'Design Quote'),'route':text(p,'Application Route'),
        'evidence':text(p,'Research Notes'),'contact_source':p.get('Contact Source URL',{}).get('url'),
        'timezone':selected(p,'Company Time Zone'),'body':body,'stage':stage,
        'first_followup_receipt':text(p,'Follow-up 1 Receipt') if stage==2 else None,
        'first_followup_sent':date(p,'Follow-up 1 Sent Time') if stage==2 else None}
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def record(page):
    p=page['properties'];key=text(p,'Deduplication Key')
    # Older records can contain human notes. Keep them visible without treating
    # unstructured text as verified evidence or rewriting the owner's notes.
    try:notes=parsed(p,'Research Notes',{})
    except ValueError:notes={}
    from .commercial import agency_context
    facts=agency_context({'url':p.get('Job URL',{}).get('url') or p.get('WEBSITE',{}).get('url') or '',
                          'source_documents':notes.get('source_documents',[])})
    service_fit=bool(facts['agency_fit_evidence'] and facts['ecommerce_fit_verified'] and not notes.get('demo'))
    name=''.join(t.get('plain_text',t.get('text',{}).get('content','')) for t in p.get('Name',{}).get('title',[]))
    country=text(p,'COUNTRY');city=text(p,'Target City');region=region_for(country,city)
    status=(p.get('STATUS',{}).get('status') or {}).get('name','')
    score=p.get('Match Score',{}).get('number') or 0
    reviews=parsed(p,'Follow-up Review Log',{})
    followups=[]
    for stage in (1,2):
        prefix='Follow-up '+str(stage);body=text(p,prefix+' Draft');review=selected(p,prefix+' Review') or 'Draft'
        if stopped(p) and review!='Sent manually':review='Cancelled'
        elif review=='Reviewed' and reviews.get(str(stage),{}).get('sha256')!=source_fingerprint(p,body,stage):review='Needs review'
        followups.append({'stage':stage,'body':body,'review':review,'due':date(p,prefix+' Due'),
                          'delivery':'Automatic delivery disabled; review does not send mail',
                          'sent_time':date(p,prefix+' Sent Time'),'receipt':text(p,prefix+' Receipt')})
    kind=selected(p,'Opportunity Type');company_type=selected(p,'Type')
    return {'id':key,'page_id':page['id'],'company':name,'status':status,'region':region,
        'quote':selected(p,'Design Quote'),'segment':selected(p,'Agency Segment'),
        'enrolled':bool(p.get('Agency Experiment',{}).get('checkbox')),'joined':date(p,'Experiment Joined'),
        'qualified':bool(company_type=='Agency' and kind=='Cold Outreach' and region in EXPERIMENT['regions'] and
                         service_fit and score>=75 and selected(p,'Research Check')=='Ready for review' and
                         p.get('Contact Source URL',{}).get('url') and p.get('EMAIL',{}).get('email') and not stopped(p)),
        'kind':kind,'company_type':company_type,'score':score,'service_fit_verified':service_fit,'agency_fit':text(p,'Agency Fit'),
        'business_signal':text(p,'Business Signal'),'outcome':selected(p,'Client Outcome') or 'Not started',
        'reply_classification':selected(p,'Reply Classification') or 'Unclassified',
        'events':parsed(p,'Acquisition Events',[]),'minutes':p.get('Acquisition Minutes',{}).get('number') or 0,
        'initial_sent':bool(text(p,'Gmail Message ID') and date(p,'sent time')),
        'followups':followups,'stopped':stopped(p)}


def summary(rows):
    cohort=[r for r in rows if r['enrolled']]
    sent=[r for r in cohort if r['initial_sent']]
    def reached(r,outcome):return any(e.get('outcome')==outcome for e in r['events'])
    counts={name:sum(reached(r,name) for r in sent) for name in OUTCOMES[1:]}
    counts['Positive reply']=sum(r['reply_classification']!='Automated' and
        (r['reply_classification']=='Positive' or reached(r,'Positive reply')) for r in sent)
    def ratio(n,d):return round(100*n/d,1) if d else None
    regions={name:sum(r['region']==name for r in cohort) for name in EXPERIMENT['regions']}
    minutes=sum(r['minutes'] for r in cohort)
    paid=counts['Paid test agreed'];completed=counts['Paid test completed']
    def group(items):
        initial=[r for r in items if r['initial_sent']]
        return {'enrolled':len(items),'sent':len(initial),
                'positive':sum(r['reply_classification']!='Automated' and
                    (r['reply_classification']=='Positive' or reached(r,'Positive reply')) for r in initial),
                'paid_tests':sum(reached(r,'Paid test agreed') for r in initial),
                'repeat_clients':sum(reached(r,'Repeat client') for r in initial)}
    first=min((r['joined'] for r in cohort if r['joined']),default=None)
    return {'qualified_enrolled':len(cohort),'initial_messages_sent':len(sent),**counts,
        'positive_reply_rate_percent':ratio(counts['Positive reply'],len(sent)),
        'paid_test_agreement_rate_percent':ratio(paid,len(sent)),
        'paid_test_completion_rate_percent':ratio(completed,paid),
        'repeat_client_rate_percent':ratio(counts['Repeat client'],completed),
        'acquisition_minutes':minutes,'minutes_per_paid_test':round(minutes/paid,1) if paid else None,
        'regions':regions,'first_enrolled_at':first,
        'four_week_review_at':(datetime.fromisoformat(first.replace('Z','+00:00'))+timedelta(weeks=4)).isoformat() if first else None,
        'results_by_region':{name:group([r for r in cohort if r['region']==name]) for name in EXPERIMENT['regions']},
        'results_by_quote':{label:group([r for r in cohort if r['quote']==label]) for label in list(QUOTES)+['']},
        'definitions':{'positive_reply_rate':'Unique initial recipients with a manually classified positive reply / unique initial recipients with a saved receipt.',
            'paid_test_agreement_rate':'Manually recorded paid-test agreements / unique initial recipients with a saved receipt.',
            'paid_test_completion_rate':'Manually recorded paid-test completions / manually recorded agreements.',
            'repeat_client_rate':'Manually recorded repeat clients / manually recorded paid-test completions.',
            'acquisition_minutes':'Manually logged research, review and conversation time; production time is separate.'}}


class ClientWorkflow:
    def __init__(self,store,notion,source,profile,sending=None):
        self.store,self.notion,self.source,self.profile=store,notion,source,profile
        self.sending=sending or {'offers':{'paid_test':{'enabled':True,'scope':PAID_TEST_SCOPE}}}
        store.db.execute('CREATE TABLE IF NOT EXISTS client_workflow_cache(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        store.db.commit()

    def cached(self):
        rows=[json.loads(r[0]) for r in self.store.db.execute('SELECT data FROM client_workflow_cache ORDER BY rowid')]
        return {'rows':rows,'summary':summary(rows),'experiment':EXPERIMENT,'quotes':list(QUOTES),
                'paid_test_scope':PAID_TEST_SCOPE,'automatic_followups_enabled':False}

    def refresh(self):
        pages=list(self.notion.query(self.source));rows=[]
        for page in pages:
            if page.get('archived') or page.get('in_trash') or not text(page['properties'],'Deduplication Key'):continue
            rows.append(record(page))
        if len({r['id'] for r in rows})!=len(rows):raise ValueError('Duplicate opportunity IDs; repair them before using the workflow')
        with self.store.db:
            self.store.db.execute('DELETE FROM client_workflow_cache')
            self.store.db.executemany('INSERT INTO client_workflow_cache VALUES(?,?)',[(r['id'],json.dumps(r)) for r in rows])
        return self.cached()

    def action(self,payload):
        action=payload.get('action')
        if action=='refresh':return self.refresh()
        page_id=payload.get('page_id','')
        if not isinstance(page_id,str) or len(page_id)>50:raise ValueError('Choose an existing Notion record')
        page=self.notion.request('pages/'+page_id,'GET');p=page['properties'];r=record(page)
        if page.get('archived') or page.get('in_trash') or not r['id']:raise ValueError('Record unavailable')
        # A URL supplied to the local app cannot write another Notion database.
        members={x['id'] for x in self.notion.query(self.source)}
        if page['id'] not in members:raise ValueError('Record is outside the acquisition tracker')
        props={}
        if action=='quote':
            if r['status'] in {'Approve','Ready','Scheduled','Sending','Sent','Replied','Interview','Won','Closed','Rejected','Do Not Contact'}:
                raise ValueError('Preserve approved or contacted quotes. Put an unsent record in Needs Review before selecting a new quote.')
            label=payload.get('quote');quote_range(label)
            props={'Design Quote':{'select':{'name':label}},'STATUS':{'status':{'name':'Needs Review'}}}
        elif action=='enroll':
            if not r['qualified']:raise ValueError('Complete agency, source, contact, fit and region checks before enrolling')
            rows=self.refresh()['rows'];cohort=[x for x in rows if x['enrolled'] and x['id']!=r['id']]
            if len(cohort)>=40 or sum(x['region']==r['region'] for x in cohort)>=10:raise ValueError('Experiment or regional target reached; retain this prospect for later')
            website=p.get('WEBSITE',{}).get('url') or ''
            from .core import hostname
            if not hostname(website):raise ValueError('A sourced company website is required')
            for other in self.notion.query(self.source):
                if other['id']!=page['id'] and other['properties'].get('Agency Experiment',{}).get('checkbox') and hostname(other['properties'].get('WEBSITE',{}).get('url') or '')==hostname(website):
                    raise ValueError('This company is already enrolled')
            props={'Agency Experiment':{'checkbox':True},'Agency Segment':{'select':{'name':r['region']}},
                   'Experiment Joined':{'date':{'start':r['joined'] or timestamp()}}}
        elif action=='result':
            classification=payload.get('reply_classification',r['reply_classification'])
            if classification not in ('Unclassified','Positive','Not interested','Automated','Other'):raise ValueError('Choose a reply classification')
            outcome=payload.get('outcome',r['outcome'])
            if outcome not in OUTCOMES:raise ValueError('Choose a supported client outcome')
            minutes=payload.get('minutes',0)
            if type(minutes) is not int or not 0<=minutes<=600:raise ValueError('Log 0–600 additional acquisition minutes')
            events=r['events'];request_id=payload.get('request_id','')
            if not isinstance(request_id,str) or not 8<=len(request_id)<=80:raise ValueError('A unique save identifier is required')
            if any(e.get('id')==request_id for e in events):return self.refresh()
            if outcome!=r['outcome']:
                current=OUTCOMES.index(r['outcome']);nxt=OUTCOMES.index(outcome)
                if nxt!=current+1:raise ValueError('Record each confirmed outcome in sequence; preserve previous milestones')
                if not r['initial_sent']:raise ValueError('A saved initial-send receipt and timestamp are required for this outreach funnel')
                if outcome=='Positive reply' and classification!='Positive':raise ValueError('Classify a genuine positive reply; automated responses do not qualify')
            happened=payload.get('outcome_at') or timestamp()
            dt=datetime.fromisoformat(happened.replace('Z','+00:00'))
            if dt.tzinfo is None or dt>datetime.now(timezone.utc):raise ValueError('Use an actual outcome time with timezone, not a future date')
            if outcome!=r['outcome'] and dt<datetime.fromisoformat(date(p,'sent time').replace('Z','+00:00')):
                raise ValueError('An outreach outcome cannot precede the initial send')
            previous=[e for e in events if e.get('outcome')!='Not started']
            if outcome!=r['outcome'] and previous and dt<datetime.fromisoformat(previous[-1]['at'].replace('Z','+00:00')):
                raise ValueError('Outcome dates must follow the recorded milestone sequence')
            events=events+[{'id':request_id,'at':dt.isoformat(),'recorded_at':timestamp(),'outcome':outcome,'reply_classification':classification,
                            'minutes':minutes,'source':'manually confirmed by owner'}]
            if len(json.dumps(events))>90000:raise ValueError('Outcome history is too large; preserve and archive with assistance')
            props={'Reply Classification':{'select':{'name':classification}},'Client Outcome':{'select':{'name':outcome}},
                   'Acquisition Events':{'rich_text':rich(json.dumps(events))},'Acquisition Minutes':{'number':r['minutes']+minutes}}
        elif action in ('followup_draft','followup_review','followup_hold','followup_record_sent'):
            stage=payload.get('stage')
            if type(stage) is not int or stage not in (1,2):raise ValueError('Choose follow-up 1 or 2')
            prefix='Follow-up '+str(stage);f=r['followups'][stage-1]
            if stopped(p):raise ValueError('A reply, stop state or unresolved delivery holds follow-ups')
            if f['receipt'] or f['review']=='Sent manually':raise ValueError('Preserve this recorded follow-up; never prepare it as a new send')
            body=payload.get('body',f['body'])
            portfolio=p.get('Portfolio Link',{}).get('url') or self.profile['portfolio_url']
            from .commercial import profile_for_lead
            checked_profile=profile_for_lead({'portfolio_url':portfolio},self.profile)
            if action=='followup_draft' and not body:
                body=('Hi '+r['company']+' team,\n\n'+
                    ('Following up on my freelance email design enquiry. I can support Figma layouts and Klaviyo production using your client guidelines.' if stage==1 else
                     'One final follow-up on freelance email design support. If you use freelance production support, I would be happy to discuss a small paid test. If the timing is not suitable, no problem.')+
                    '\n\nPortfolio: '+portfolio+'\n\nWould discussing a small paid test be useful?\n\n'+self.profile.get('email_signature','Shine'))
            if not isinstance(body,str) or not 80<=len(body)<=5000:raise ValueError('Follow-up draft must be 80–5000 characters')
            if portfolio_name_issue(body):raise ValueError(portfolio_name_issue(body))
            if portfolio not in body:raise ValueError('Keep the exact portfolio URL in the follow-up')
            from .delivery import check_draft
            from .approval_checks import pricing_issue
            notes=parsed(p,'Research Notes',{})
            lead={'id':r['id'],'url':p.get('Job URL',{}).get('url') or '',
                  'source_documents':notes.get('source_documents',[]),'source_text':notes.get('source_excerpt',''),
                  'selected_offer':'paid_test','design_quote':r['quote'] or None,'portfolio_url':portfolio,
                  'draft':{'subject':text(p,'email SUBJECT'),'body':body,'evidence':notes.get('personalization_evidence',[])}}
            check_draft(lead,checked_profile,self.sending)
            price=pricing_issue(lead,{'design_rate_usd':[25,30]})
            if price:raise ValueError(price)
            if action=='followup_review' and (not r['initial_sent'] or not text(p,'Gmail Thread ID')):raise ValueError('Wait for the initial saved receipt and conversation thread before reviewing a follow-up')
            if stage==2 and action in ('followup_review','followup_record_sent') and not r['followups'][0]['receipt']:raise ValueError('Record the first follow-up receipt before reviewing the second')
            if action=='followup_record_sent':
                receipt=payload.get('receipt','').strip();sent=payload.get('sent_time','')
                if f['review']!='Reviewed':raise ValueError('Review the exact draft and current source first')
                if body!=f['body']:raise ValueError('Record the exact reviewed draft; changed wording needs a new review')
                if not 8<=len(receipt)<=300 or not sent:raise ValueError('Supply the existing Gmail receipt and actual sent timestamp; this operation never sends mail')
                dt=datetime.fromisoformat(sent.replace('Z','+00:00'))
                if dt.tzinfo is None or dt>datetime.now(timezone.utc):raise ValueError('Use an actual past send time with timezone')
                initial=datetime.fromisoformat((date(p,'sent time') or '').replace('Z','+00:00'))
                if dt<initial:raise ValueError('Follow-up cannot precede the original message')
                previous=date(p,'Follow-up 1 Sent Time') if stage==2 else None
                if previous and dt<datetime.fromisoformat(previous.replace('Z','+00:00')):
                    raise ValueError('Second follow-up cannot precede the first follow-up')
                if receipt in (text(p,'Gmail Message ID'),text(p,'Follow-up 1 Receipt'),text(p,'Follow-up 2 Receipt')):
                    raise ValueError('This receipt already belongs to a recorded message')
                props.update({prefix+' Receipt':{'rich_text':rich(receipt)},prefix+' Sent Time':{'date':{'start':dt.isoformat()}}})
                state='Sent manually'
            else:state={'followup_draft':'Draft','followup_review':'Reviewed','followup_hold':'Held'}[action]
            zone=selected(p,'Company Time Zone')
            base=date(p,'sent time') if stage==1 else date(p,'Follow-up 1 Sent Time')
            due=due_after(base,5 if stage==1 else 7,zone) if base and zone else None
            props.update({prefix+' Draft':{'rich_text':rich(body)},prefix+' Review':{'select':{'name':state}},
                          prefix+' Due':{'date':{'start':due}} if due else {'date':None},
                          prefix+' Delivery':{'rich_text':rich('Manually reported sent; no automatic send performed' if state=='Sent manually' else 'Automatic sending disabled. '+('Awaiting initial/previous receipt.' if not due else 'Review date only; not a scheduled send.'))}})
            reviews=parsed(p,'Follow-up Review Log',{})
            reviews[str(stage)]={'state':state,'at':timestamp(),'sha256':source_fingerprint(p,body,stage)}
            props['Follow-up Review Log']={'rich_text':rich(json.dumps(reviews))}
        else:raise ValueError('Unknown workflow action; no sending operation exists')
        self.notion.request('pages/'+page['id'],'PATCH',{'properties':props})
        return self.refresh()
