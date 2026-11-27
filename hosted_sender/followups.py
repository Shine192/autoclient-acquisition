"""Individually approved follow-ups; initial approval never authorizes these."""
import copy
import json
import re
from datetime import datetime, timezone
from email.utils import parseaddr, getaddresses
from acquisition_agent import delivery, review
from acquisition_agent.client_workflow import stopped, source_fingerprint, due_after, selected, text, parsed
from acquisition_agent.providers import rich
from .notion_import import read_lead
from .queue import digest


def enabled(worker):
    return worker.q.control().get('reviewed_followups_enabled') is True


def prepare(worker, parent, stage, expected=None):
    if not enabled(worker) or stage!=1:raise ValueError('Reviewed follow-ups are disabled')
    if parent.get('stage',0)!=0 or parent['state']!='sent' or parent.get('reply_reason') or parent.get('notion_sync_pending'):
        raise ValueError('A resolved initial receipt without replies is required')
    seed=worker.q.db.get('lead_'+parent['lead_id'])['data']
    page=worker.notion.request('pages/'+seed['notion_page_id'],'GET');p=page['properties']
    prefix='Follow-up '+str(stage)
    if page.get('archived') or page.get('in_trash') or stopped(p):raise ValueError('Reply, stop or unresolved delivery blocks follow-up')
    if (p.get('STATUS',{}).get('status') or {}).get('name')!='Sent':raise ValueError('Initial message must remain Sent')
    from acquisition_agent.simple_workflow import snapshot
    sequence=parent.get('sequence')
    body=text(p,prefix+' Draft')
    if sequence:
        if snapshot(p)!=sequence:raise ValueError('Approved sequence changed; renew review')
        if selected(p,prefix+' Review') in ('Held','Cancelled'):raise ValueError('Follow-up is held or cancelled')
        fingerprint=digest([sequence['hash'],stage])
    else:
        if selected(p,prefix+' Review')!='Approve':raise ValueError('Approve this follow-up separately')
        fingerprint=source_fingerprint(p,body,stage)
        approval=parsed(p,'Follow-up Review Log',{}).get(str(stage),{})
        if approval.get('state')!='Approve' or approval.get('sha256')!=fingerprint:raise ValueError('Follow-up changed; renew its approval')
    if text(p,prefix+' Receipt'):raise ValueError('Follow-up already has a receipt')
    if expected and expected['review_hash']!=fingerprint:raise ValueError('Follow-up approval changed after queueing')
    if text(p,'Gmail Message ID')!=parent['gmail_id'] or text(p,'Gmail Thread ID')!=parent['thread_id']:
        raise ValueError('Initial receipt or conversation changed')
    lead=read_lead(page,worker.s['preferences'])
    lead['application_route']=text(p,'Application Route')
    lead=review.sourced_candidate(lead)
    lead.update(approved=True,status='Ready',contact_review_notes=review.ATTESTATION,**{k:True for k in review.REVIEW_FLAGS})
    if lead['id']!=parent['lead_id'] or lead['email']!=parent['recipient']:raise ValueError('Follow-up identity changed')
    worker.target_matches(lead,None)
    with __import__('tempfile').TemporaryDirectory() as folder:
        store=worker.local(folder)
        try:
            original=delivery.gate(store,lead,worker.s['sending'],worker.s['profile'],worker.s['preferences'],worker.s['exclusions'],follow=True)
            if digest(original)!=parent['draft_hash']:raise ValueError('Original sent message changed; preserve its history')
            follow=copy.deepcopy(lead);follow['draft']['body']=body
            from acquisition_agent.commercial import OUTREACH_PORTFOLIO
            if OUTREACH_PORTFOLIO in body:follow['portfolio_url']=OUTREACH_PORTFOLIO
            draft=delivery.check_draft(follow,worker.s['profile'],worker.s['sending'])
            from acquisition_agent.approval_checks import pricing_issue
            issue=pricing_issue(follow,worker.s['preferences'])
            if issue:raise ValueError(issue)
        finally:store.db.close()
    previous=parent
    if stage==2:
        previous=worker.q.db.get('outbox_'+digest([parent['id'],'followup',1])[:32])
        if not previous or previous['state']!='sent' or previous.get('reply_reason') or previous.get('notion_sync_pending'):
            raise ValueError('First follow-up needs a verified saved receipt')
        if text(p,'Follow-up 1 Receipt')!=previous['gmail_id']:raise ValueError('First follow-up receipt changed')
    due=due_after(datetime.fromtimestamp(previous['attempted_at'],timezone.utc).isoformat(),2,lead['company_time_zone'])
    message=worker.gmail.message(previous['gmail_id'])
    headers={h['name'].lower():h['value'] for h in message.get('payload',{}).get('headers',[])}
    reference=headers.get('message-id','')
    if (message.get('id')!=previous['gmail_id'] or message.get('threadId')!=parent['thread_id'] or 'SENT' not in message.get('labelIds',[]) or
        parseaddr(headers.get('from',''))[1].lower()!=worker.s['sending']['sender'].lower() or
        {a.lower() for _,a in getaddresses([headers.get('to','')])}!={parent['recipient'].lower()} or not re.fullmatch(r'<[^<>\s]+@[^<>\s]+>',reference)):
        raise ValueError('Verify the original Gmail receipt and thread before follow-up')
    known={v.get('gmail_id') for v in worker.q.db.list('outbox') if v.get('state')=='sent'}
    messages=worker.gmail.thread(parent['thread_id'])+worker.gmail.related(parent['recipient'],parent['attempted_at'])
    for inbound in messages:
        reason=delivery.inbound_reason(inbound,worker.s['sending']['sender'],parent['recipient'],[parent['message_id'],reference],datetime.fromtimestamp(parent['attempted_at'],timezone.utc).isoformat())
        if reason:
            worker.q.suppress([parent['recipient'],parent['company']],reason)
            raise ValueError('Reply or delivery notice stops follow-ups')
        if ('SENT' in inbound.get('labelIds',[]) and inbound.get('id') not in known and
            int(inbound.get('internalDate','0'))>=int(parent['attempted_at']*1000)):
            raise ValueError('Unrecorded sent message; reconcile manual contact before follow-up')
    return lead,draft,fingerprint,datetime.fromisoformat(due).timestamp(),reference


def enqueue(worker):
    if not enabled(worker):return
    for parent in worker.q.db.list('outbox'):
        if parent.get('stage',0) or parent['state']!='sent' or parent.get('mode')=='test':continue
        for stage in (1,):
            key=digest([parent['id'],'followup',stage])[:32]
            if worker.q.db.get('outbox_'+key):continue
            try:lead,draft,fp,due,reference=prepare(worker,parent,stage)
            except (ValueError,KeyError,TypeError) as exc:
                seed=worker.q.db.get('lead_'+parent['lead_id'])
                if not seed:continue
                page=worker.notion.request('pages/'+seed['data']['notion_page_id'],'GET')
                prefix='Follow-up '+str(stage)
                if parent.get('sequence') or selected(page['properties'],prefix+' Review')=='Approve':
                    from acquisition_agent.incidents import cloud_record
                    import os,time
                    # Reply/stop outcomes are expected safeguards, not bugs.
                    if not re.search(r'without replies is required|Reply, stop|held or cancelled|Approve this follow-up separately',str(exc),re.I):
                        cloud_record(worker.q.db,'followup',parent['lead_id'],[exc],observation=os.getenv('GITHUB_RUN_ID') or str(time.time()),run_id=os.getenv('GITHUB_RUN_ID'),page_id=page['id'])
                    worker.notion.request('pages/'+page['id'],'PATCH',{'properties':{
                        prefix+' Review':{'select':{'name':'Held'}},prefix+' Delivery':{'rich_text':rich('Held: '+str(exc)[:400])}}})
                continue
            body=draft['body']
            if lead['kind']=='Cold Outreach':
                from acquisition_agent.signature import with_footer
                body=with_footer(body,worker.s['profile'],worker.s['sending']['cold_outreach_footer']+'\n'+worker.s['sending']['business_postal_address'])
            item=dict(id=key,kind='outbox',state='queued',attempted_at=None,stage=stage,parent_id=parent['id'],campaign=None,
                      lead_id=parent['lead_id'],recipient=parent['recipient'],company=parent['company'],company_timezone=lead['company_time_zone'],
                      due_at=due,review_hash=fp,subject=parent['subject'],body=body,draft_hash=digest(draft),thread_id=parent['thread_id'],reply_to=reference,
                      message_id='<shine-github-'+key+'@'+worker.s['sending']['sender'].split('@')[1]+'>')
            def save(tx):
                if tx.get('outbox_'+key):return
                tx.put('outbox_'+key,item)
            worker.q.db.transaction(save)
            worker.notion.request('pages/'+lead['notion_page_id'],'PATCH',{'properties':{'Follow-up '+str(stage)+' Delivery':{'rich_text':rich('Approved and queued; separate approval, company-local window and final reply checks apply')}}})


def preflight(worker,item):
    parent=worker.q.db.get('outbox_'+item['parent_id'])
    lead,draft,fp,due,reference=prepare(worker,parent,item['stage'],item)
    if digest(draft)!=item['draft_hash'] or lead['company_time_zone']!=item['company_timezone'] or reference!=item['reply_to'] or due!=item['due_at']:
        raise ValueError('Follow-up contents or timing changed')
    return lead


def sync(worker,item):
    page=worker.q.db.get('lead_'+item['lead_id'])['data']['notion_page_id'];prefix='Follow-up '+str(item['stage'])
    current=worker.notion.request('pages/'+page,'GET')
    if current.get('archived') or current.get('in_trash'):return False
    props={prefix+' Review':{'select':{'name':'Sent'}},prefix+' Receipt':{'rich_text':rich(item['gmail_id'])},
           prefix+' Sent Time':{'date':{'start':datetime.fromtimestamp(item['attempted_at'],timezone.utc).isoformat()}},
           prefix+' Delivery':{'rich_text':rich('Sent in original conversation; provider receipt saved')}}
    if item.get('reply_reason'):props['Reply Status']={'rich_text':rich(item['reply_reason'])}
    worker.notion.request('pages/'+page,'PATCH',{'properties':props});return True
