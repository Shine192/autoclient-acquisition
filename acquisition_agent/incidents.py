"""Private, bounded incident history. Never stores raw exceptions, drafts or keys."""
import copy
import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime, timezone

LIMIT = 200
LOCAL_LOGGING_AVAILABLE = True
STEPS = {'research':'Finding prospects', 'drafting':'Writing emails', 'notion_sync':'Saving to Notion',
         'approval':'Checking approval and evidence', 'queue':'Queueing and scheduling',
         'preflight':'Final checks before sending', 'sending':'Sending the email',
         'replies':'Checking replies', 'followup':'Preparing the follow-up',
         'receipts':'Saving delivery confirmation', 'setup':'Connections and setup', 'monitoring':'Reading the error log'}
# Each explanation describes a check, rather than claiming an unverified cause.
# (title, what happened, likely cause, impact, easiest action, alternative, verification, severity)
GUIDES = {
 'auth':('A connection rejected its credentials','A service rejected the saved account or API credentials.','The credential may have expired, been revoked, or belong to another account.','This step cannot continue.','Reconnect the affected account in setup, then retry the failed read or research task.','Check account access and the service status before replacing a credential.','A new connection check succeeds. Never paste API keys into an email or bug report.','error'),
 'credits':('Provider credit is unavailable','A paid research provider refused the request.','Its balance or billing access may be unavailable.','Further paid research is held; saved results remain available.','Check the provider balance and account status.','Use the existing manual research prompt while billing is reviewed.','A deliberately retried research request succeeds within the configured allowance.','blocked'),
 'rate_limit':('A service rate limit was reached','The provider refused requests temporarily.','Too many requests or an account usage limit may have been reached.','The affected operation stopped.','Wait for the provider limit to reset, then retry research or sync once.','Reduce the research batch size or inspect the provider allowance.','The next request completes without HTTP 429.','warning'),
 'network':('A connection could not finish','The step could not complete a network request.','Internet access, DNS, the remote service, or a timeout may be responsible.','Results may be incomplete. A send timeout never proves that no email was sent.','Check the connection and the affected run. Retry a read or sync only.','If the failure happened during sending, reconcile its delivery receipt before doing anything else.','A read succeeds, or an uncertain send is explicitly reconciled.','error'),
 'source':('An official source could not be checked','A source page could not be retrieved or re-identified.','The page may have moved, restricted automated access, or changed.','The prospect stays held until its evidence can be checked.','Open the official page and replace the source with its current published URL and exact excerpt.','Keep the prospect on hold if a reliable source is unavailable.','The same record passes source verification; no address or vacancy is guessed.','blocked'),
 'structured_research':('Research information is incomplete','The record lacks usable structured research.','An older entry, incomplete import, or manual edit may have removed required source information.','Approval cannot produce a sendable record.','Repair the existing record with official source documents and exact evidence quotes.','Use a new research session to refresh evidence while preserving the original record and sending history.','Research validation passes on the existing record.','blocked'),
 'location':('The location does not match the search','The saved location evidence does not establish the requested city or region.','The prospect may be linked to the wrong discovery session, or its quote may be incomplete.','The match score or scheduling cannot be trusted yet.','Compare the company address with the search country and city; correct the record using the official address.','Hold companies outside the intended market.','Location evidence matches the corrected session and the exact source.','blocked'),
 'company_type':('The company type does not match','The company does not match the saved agency or brand search.','A record may have inherited another session’s company type.','Qualification is held.','Check whether this is an agency, brand, or advertised job and repair the saved search context.','Keep it out of the approval list if its type cannot be established.','The company type and its cited evidence pass validation.','blocked'),
 'industry':('Industry evidence is missing or mismatched','The industry quote does not establish the selected industry.','A wrong category, paraphrased quote, or incorrect source URL may be saved.','Qualification remains blocked.','Select the evidenced industry and save an exact official quote at the correct URL.','For an agency search, leave an optional client industry blank when it is unknown.','Industry validation passes without inventing a client need.','blocked'),
 'contact':('The recipient needs verification','The selected email is not verified as an appropriate published contact route.','The address may be absent from evidence, restricted to press/support, or unrecognized by the inbox rules.','No outreach is queued for this recipient.','Open the official contact source and check the exact address and its stated purpose.','Find a suitable general business or freelance route; keep press, customer care and webmaster routes held.','The recipient and contact-purpose checks pass. A public address alone is not permission.','blocked'),
 'fit':('The qualification score is below the minimum','The current sourced score is lower than the sending threshold.','Required facts may be missing, the search context may be wrong, or the prospect may not fit.','The record stays out of the approval-ready list.','Repair missing evidence and the saved search context, then recalculate.','Reject a poor-fit prospect rather than increasing its score or lowering all checks.','The recalculated score passes with source support; buying intent remains unconfirmed.','blocked'),
 'timezone':('The company’s sending timezone is unverified','The sender cannot establish a verified company-local sending window.','The office city, timezone or public location source may be missing.','The email cannot be scheduled.','Save the official office location and its correct region/city timezone.','Keep the record held when the company location is uncertain.','A company-local weekday sending window can be calculated.','blocked'),
 'price':('The email price and selected quote differ','The message does not match its selected Figma design quote.','An old draft or changed quote may have left inconsistent pricing.','Sending is held to prevent an unintended offer.','Make the email and selected USD 25–30 or USD 30–35 range agree, then review again.','Keep Klaviyo implementation separately quoted.','The price check passes for the exact revised message.','blocked'),
 'draft':('The email draft needs correction','The draft failed a writing or evidence check.','It may contain missing evidence, placeholders, an unsupported claim, an invalid subject, or an unapproved offer.','The company can remain saved while its draft is held.','Open the affected record and repair the named draft requirement using verified facts.','Use its drafting prompt with the existing research; avoid repeating paid research unnecessarily.','The main email and its follow-up pass validation before approval.','blocked'),
 'changed':('The approved content changed','The current recipient, message, evidence, quote or sequence differs from the reviewed version.','Someone edited the record after approval or queueing.','The earlier approval cannot authorize the revised sequence.','Review the complete updated main email and follow-up in Notion, then approve the revised version.','Leave the record held if the edit was not intended.','A new approval matches the exact current sequence.','blocked'),
 'approval':('The record still needs your approval','The sender has no current explicit approval for this exact sequence.','The entry may still be in review, or an earlier approval was withdrawn.','No email is sent.','Use Ready for your approval in Notion and approve only after checking the recipient and both messages.','Leave incomplete records in Research to repair.','The approved record enters the guarded queue.','blocked'),
 'sync':('Notion could not be updated','The system could not save or retrieve the required Notion information.','Connection access, a changed field, API limits or a temporary Notion failure may be responsible.','The dashboard and Notion may temporarily disagree.','Check Notion access and retry the sync of the existing record.','If an email was already sent, retry only its receipt sync; do not resend it.','Notion shows the existing saved result or delivery receipt.','error'),
 'history':('Sending history prevents another message','A previous send, suppression, reply or duplicate contact conflicts with this action.','The company may already have been contacted or asked not to receive further messages.','The conflicting send or follow-up is stopped.','Inspect the existing record, conversation and sending receipt.','Keep opt-outs suppressed; do not delete history to make a message send.','The history is reconciled without contacting a suppressed recipient or duplicating a message.','blocked'),
 'uncertain':('Delivery outcome needs reconciliation','A send was attempted but its final outcome is not safely confirmed.','A timeout, interruption or receipt-persistence failure may have occurred after the provider accepted it.','Further sending may be stopped to prevent duplicates.','Check the sent folder and the existing message ID; reconcile the original attempt.','Ask for technical help with the affected run if its receipt cannot be established.','The original attempt is recorded as sent or conclusively not sent. Do not blindly retry.','urgent'),
 'state':('The saved delivery state could not be verified','The encrypted state or a durable write failed its consistency check.','A persistence failure, concurrent update, missing key or invalid state may be responsible.','Sending stops because history cannot be trusted safely.','Inspect the affected run and restore access to the existing encrypted history.','Get technical help; never reset the ledger, reservations or receipts.','The original history can be read and updated consistently.','urgent'),
 'allowance':('A research allowance was reached','The configured research budget or request allowance stopped the task.','The session or monthly limit has been used, or billing usage needs review.','No additional paid research is started automatically.','Review saved results and the allowance before starting more paid research.','Continue with the existing manual research prompt.','Research resumes only within an explicitly available allowance.','warning'),
 'busy':('Another task is already running','A worker lock prevented an overlapping operation.','The dashboard, agent or another task is still using the same state.','The new task waits or stops without duplicating work.','Wait for the active task to finish, then retry once.','If it is stuck, inspect that task before restarting the app.','Only one worker owns the operation and its result is saved.','warning'),
 'paused':('The agent or sequence is on hold','The configured pause or sequence hold prevents new work.','The operator paused the agent or withdrew this sequence.','New work remains stopped.','Check the pause or hold setting and the reason before resuming.','Keep it paused while other unresolved incidents are investigated.','The intended task resumes through the existing controls.','info'),
 'setup':('A connection or sending setup is incomplete','A required account, sender identity or approved configuration is unavailable.','An account may not be connected, or the configured policy may have changed.','The dependent step cannot continue.','Open Setup and preferences and check the affected connection and policy.','Keep the Mac sender in draft-only mode when GitHub owns production delivery.','The existing connection and policy checks pass without changing approval rules.','blocked'),
 'unknown':('An unexpected error needs inspection','The operation stopped without a recognized explanation.','The cause is not established from the safe information available.','This step did not complete; other records may be unaffected.','Open the affected session or run and copy this incident’s safe diagnostic details for investigation.','Do not repeat a sending action until its delivery outcome is known.','The underlying problem is identified and the affected step completes safely.','error'),
}

RULES = [
 ('uncertain',r'uncertain|unresolved (?:send|delivery)|outcome unknown|active.attempt|receipt.*persist'),
 ('state',r'encrypted|ledger|state cannot|state persistence|durable|StateError'),
 ('auth',r'HTTP 40[13]|invalid.grant|credential.*reject|token.*expir'),
 ('credits',r'HTTP 402|credit.*unavailable'),('rate_limit',r'HTTP 429|rate.limit'),
 ('price',r'price.*differ|pricing|design quote|Figma design range'),
 ('changed',r'changed after|sequence changed|approval.*changed|draft or timezone changed'),
 ('location',r'location.*(?:evidence|match|quote)|requested city|country.*(?:missing|outside)'),
 ('company_type',r'company type'),('industry',r'industry'),
 ('timezone',r'timezone|time.zone|company.local.*verif'),
 ('contact',r'recipient.*(?:evidence|source|match)|published.*(?:address|inbox|email)|address.*(?:supported|published)|contact URL|selected inbox|contact.purpose|press|media enquiries|webmaster|shared business email|no valid.*address'),
 ('fit',r'qualification|(?:sourced|research) fit|minimum.*score'),
 ('structured_research',r'structured research|Research Notes.*invalid|source documents.*missing'),
 ('draft',r'personalization|placeholder|draft|subject|unsupported|unapproved.*(?:offer|free)|exact.*portfolio'),
 ('history',r'duplicate|suppression|suppressed|opt.out|bounce|already.*(?:sent|contacted|attempted)|inbound reply'),
 ('approval',r'STATUS.*Approve|review the message|review eligibility|approval.*withdrawn|notion approval'),
 ('allowance',r'allowance|billing.hold|billing usage|safe input limit'),
 ('busy',r'lock|worker.*(?:active|running|finishing)|task.*already'),
 ('paused',r'paused|panel stopping|sequence.*hold|held or cancelled|follow.ups are disabled'),
 ('source',r'research HTTP|source.*(?:check|unavailable)|page.*(?:HTTP|moved)|re.identify'),
 ('network',r'timeout|timed.out|connection failed|network|DNS|URLError'),
 ('sync',r'Notion.*(?:sync|save|access|update|failed)|sync.*Notion'),
 ('setup',r'policy hash|not configured|missing.*(?:key|token)|required.*(?:key|token)|sender|authentication|connect.*(?:Notion|Gmail)'),
]

def classify(error, step):
    text=str(error)
    code=next((code for code,pattern in RULES if re.search(pattern,text,re.I)), 'unknown')
    if re.search(r'research HTTP [1-5][0-9]{2}',text,re.I):code='source'
    elif re.search(r'HTTP 5[0-9]{2}',text) and code=='unknown':code='network'
    # A timeout while dispatching is always an uncertain outcome, not retryable.
    if step in ('sending','receipts') and code in ('network','unknown'):code='uncertain'
    technical={}
    m=re.search(r'\bHTTP ([1-5][0-9]{2})\b',text)
    if m:technical['http_status']=int(m[1])
    m=re.search(r'(?:fit (?:is )?|score[=: ]+)(\d{1,3})/100',text,re.I)
    if m:technical['fit_score']=int(m[1])
    m=re.search(r'(?:minimum|needs)\s+(\d{1,3})',text,re.I)
    if m:technical['minimum_fit']=int(m[1])
    if code=='contact':
        if re.search(r'nonstandard|unrecognized|does not recognize',text,re.I):technical['contact_issue']='inbox_rule'
        elif re.search(r'press|media enquiries',text,re.I):technical['contact_issue']='press'
        elif re.search(r'webmaster|technical route',text,re.I):technical['contact_issue']='technical'
        elif re.search(r'support inbox|customer care',text,re.I):technical['contact_issue']='support'
    if isinstance(error,BaseException):
        technical['exception_type']=type(error).__name__ if type(error).__name__ in ('ValueError','KeyError','TypeError','TimeoutError','OSError','StateError') else 'UnexpectedError'
        frames=[];tb=error.__traceback__
        while tb:
            module=tb.tb_frame.f_globals.get('__name__','');function=tb.tb_frame.f_code.co_name
            if re.fullmatch(r'(?:acquisition_agent|hosted_sender)(?:\.[A-Za-z_][A-Za-z_0-9]*)+',module) and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',function):
                frames.append({'module':module,'function':function,'line':tb.tb_lineno})
            tb=tb.tb_next
        if frames:technical['locations']=frames[-4:]
    return code,technical

def scope_id(value):
    value=str(value or 'system')
    return value if re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',value) else hashlib.sha256(value.encode()).hexdigest()[:24]

def observe(events, source, step, scope, errors, observation=None, run_id=None, page_id=None, at=None):
    """Replace one scope's current conditions; resolve only after a full check."""
    at=time.time() if at is None else at
    source=source if source in ('local','cloud','notion','monitor') else 'local'
    step=step if step in STEPS else 'setup';scope=scope_id(scope)
    events=copy.deepcopy(events);active=set();batch_technical={};observation=scope_id(observation) if observation is not None else str(at)
    for error in errors:
        code,technical=classify(error,step)
        key=hashlib.sha256(json.dumps([source,step,scope,code],separators=(',',':')).encode()).hexdigest()[:24]
        active.add(key);current=next((e for e in events if e['id']==key),None)
        technical=dict(batch_technical.get(key,{}),**technical);batch_technical[key]=technical
        if current is None:
            current={'id':key,'source':source,'step':step,'scope':scope,'code':code,'first_seen':at,'last_seen':at,'occurrences':0,'observations':[]};events.append(current)
        if observation not in current['observations']:
            current['occurrences']+=1;current['observations']=(current['observations']+[observation])[-10:]
            current['last_seen']=max(current['last_seen'],at)
        current.update(status='open',technical=technical,resolved_at=None)
        if str(run_id or '').isdigit():current['run_id']=str(run_id)
        if re.fullmatch(r'[0-9a-fA-F-]{32,36}',str(page_id or '')):current['page_id']=page_id
    for event in events:
        if (event['source'],event['step'],event['scope'])==(source,step,scope) and event['id'] not in active and event['status']=='open':
            event.update(status='resolved',resolved_at=at)
    # Keep unresolved incidents first; old resolved history expires first.
    return sorted(events,key=lambda e:(e['status']=='open',e['last_seen']),reverse=True)[:LIMIT]

def public_event(event, names=None, repository='Shine192/autoclient-acquisition'):
    guide=GUIDES.get(event['code'],GUIDES['unknown'])
    title,what,cause,impact,fix,alternative,verify,severity=guide
    if event['step']=='monitoring':
        impact='This view cannot read fresh information from that source. Previously saved history remains visible; this read does not change the sender.'
    if event['code']=='unknown' and event.get('technical',{}).get('exception_type'):
        what+=' Recorded error type: '+event['technical']['exception_type']+'.'
    technical=event.get('technical',{})
    if event['code']=='fit' and 'fit_score' in technical:
        what='The sourced score is '+str(technical['fit_score'])+'/100.'+(' The required minimum is '+str(technical['minimum_fit'])+'.' if 'minimum_fit' in technical else '')
    if event['code']=='contact':
        what={'press':'The selected route is for press or media enquiries, rather than freelance service introductions.',
              'technical':'The selected route is a webmaster or technical inbox, rather than freelance service introductions.',
              'support':'The selected route is a support or customer-care inbox, rather than freelance service introductions.',
              'inbox_rule':'The address is published, but the current inbox rules do not recognize this route. Contact-purpose review is still needed.'}.get(technical.get('contact_issue'),what)
    value={k:copy.deepcopy(event.get(k)) for k in ('id','source','step','scope','code','status','first_seen','last_seen','resolved_at','occurrences','technical','run_id','page_id')}
    value.update(title=title,what=what,likely_cause=cause,impact=impact,easiest_fix=fix,other_option=alternative,verify=verify,severity=severity,step_label=STEPS.get(event['step'],'Setup'),company=(names or {}).get(event['scope']))
    if value.get('page_id'):value['record_url']='https://www.notion.so/'+value['page_id'].replace('-','')
    if str(value.get('run_id') or '').isdigit() and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*',repository):
        value['run_url']='https://github.com/'+repository+'/actions/runs/'+value['run_id']
    return value

def load(store):
    store.db.execute('CREATE TABLE IF NOT EXISTS incident_data (name TEXT PRIMARY KEY, data TEXT)');store.db.commit()
    row=store.db.execute("SELECT data FROM incident_data WHERE name='events'").fetchone()
    return json.loads(row[0]) if row else []

def save(store, events):
    store.db.execute('INSERT OR REPLACE INTO incident_data VALUES(?,?)',('events',json.dumps(events)));store.db.commit()

def record(store, step, scope, errors, **kwargs):
    global LOCAL_LOGGING_AVAILABLE
    try:
        mutate(store,lambda events:observe(events,'local',step,scope,errors,**kwargs))
        LOCAL_LOGGING_AVAILABLE=True
        return True
    except (sqlite3.Error,OSError):
        LOCAL_LOGGING_AVAILABLE=False
        return False  # Logging must not turn completed research into a failed task.

def mutate(store, operation):
    load(store)  # Initialize before acquiring the write transaction.
    try:
        store.db.execute('BEGIN IMMEDIATE')
        row=store.db.execute("SELECT data FROM incident_data WHERE name='events'").fetchone()
        events=operation(json.loads(row[0]) if row else [])
        store.db.execute('INSERT OR REPLACE INTO incident_data VALUES(?,?)',('events',json.dumps(events)))
        store.db.commit()
    except Exception:
        store.db.rollback();raise

def merge_remote_observations(store, observed):
    def merge(current):
        result={e['id']:e for e in current}
        for event in observed:
            if event['source']=='local':continue
            old=result.get(event['id'])
            effective=lambda e:max(e['last_seen'],e.get('resolved_at') or 0)
            if old is None or effective(event)>=effective(old):result[event['id']]=event
        return sorted(result.values(),key=lambda e:(e['status']=='open',e['last_seen']),reverse=True)[:LIMIT]
    mutate(store,merge)

def task_result(store, kind, scope, result, observation=None):
    scope=result.get('session_id') or kind
    step='notion_sync' if kind=='sync' else ('drafting' if kind in ('import','target-import') else 'research')
    errors=[x.get('error','Unexpected error') for x in result.get('errors',[]) if isinstance(x,dict)]
    if result.get('error'):errors.append(result['error'])
    if result.get('paused') and result.get('message'):errors.append(result['message'])
    record(store,step,scope,errors,observation=observation)
    sync=result.get('notion_sync')
    if isinstance(sync,dict):record(store,'notion_sync',scope,[x.get('error','Notion sync failed') for x in sync.get('errors',[]) if isinstance(x,dict)],observation=observation)

def cloud_record(db, step, scope, errors, **kwargs):
    """One encrypted document; no new public-log output or message side effects."""
    def op(tx):
        prior=tx.get('incident_history') or {'events':[]}
        tx.put('incident_history',{'kind':'incident_history','events':observe(prior['events'],'cloud',step,scope,errors,**kwargs)})
    db.transaction(op)

def cloud_batch(db, checks, **kwargs):
    def op(tx):
        events=(tx.get('incident_history') or {}).get('events',[])
        for step,scope,errors,context in checks:
            events=observe(events,'cloud',step,scope,errors,**dict(kwargs,**context))
        tx.put('incident_history',{'kind':'incident_history','events':events})
    db.transaction(op)
