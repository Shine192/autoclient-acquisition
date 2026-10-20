"""One explicit review decision; existing delivery gates remain authoritative."""
import copy
import re
from datetime import datetime, timedelta, timezone
from . import delivery, targeting
from .core import assess, hostname, normalize, PUBLIC_INBOXES, EMAIL_PATTERN
from .providers import rich, research_notes
from .scheduling import delivery_zone

REVIEW_FLAGS = ('targeting_reviewed', 'eligibility_reviewed', 'contact_purpose_reviewed', 'outreach_allowed')
NOTION_FLAGS = ('Targeting Reviewed', 'Eligibility Reviewed', 'Contact Purpose Reviewed', 'Outreach Allowed')
ATTESTATION = ('By approving, I confirm I reviewed the company fit, recipient, message, '
               'work/location restrictions where applicable, and whether this contact route permits this outreach.')
CITY_ZONES = {('United Arab Emirates','dubai'):'Asia/Dubai',
              ('United Kingdom','london'):'Europe/London',
              ('United States','new york'):'America/New_York',
              ('United States','california'):'America/Los_Angeles',
              ('Australia','sydney'):'Australia/Sydney',('Australia','melbourne'):'Australia/Melbourne',
              ('Australia','brisbane'):'Australia/Brisbane',('Australia','perth'):'Australia/Perth',
              ('Australia','adelaide'):'Australia/Adelaide',('New Zealand','auckland'):'Pacific/Auckland'}


def sourced_candidate(lead):
    """Reconcile deterministic facts only; never invent missing source content."""
    value=copy.deepcopy(lead)
    documents=[d for d in value.get('source_documents',[]) if hostname(d['url'])==hostname(value['url'])]
    # A published inbox is evidence of its address, not permission to pitch.
    # The single explicit review decision confirms the intended contact purpose.
    allowed=PUBLIC_INBOXES | {'office','business','collaborations'}
    if value.get('kind')=='Cold Outreach':
        allowed=allowed-{'help','support','booking','press','careers','jobs','hr','recruitment','talent'}
    addresses={}
    for doc in documents:
        for address in re.findall(EMAIL_PATTERN,doc['text'],re.I):
            address=address.lower()
            if address.split('@')[0] in allowed:addresses.setdefault(address,doc['url'])
    address=value.get('email','').lower().strip()
    if not address and len(addresses)==1:
        address=next(iter(addresses));value['email']=address
    if address in addresses:
        value['email_candidates']=sorted(set(value.get('email_candidates',[])+[address]))
        value['contact_source_url']=addresses[address]
    elif address:
        # Do not retain old verification when the selected address has no
        # suitable evidence in this review's official documents.
        value['email_candidates']=[x for x in value.get('email_candidates',[]) if x!=address]
        value['contact_source_url']=''
    # A paraphrased industry quote can be replaced with a literal, cited passage.
    if value.get('target_session'):
        evidence=value.setdefault('target_evidence',{})
        if value.get('industry') in targeting.INDUSTRIES:
            item=evidence.get('industry',{})
            valid=any(d['url'].rstrip('/')==item.get('url','').rstrip('/') and
                      12<=len(item.get('quote',''))<=400 and normalize(item['quote']) in normalize(d['text']) for d in documents)
            if not valid:
                terms=targeting.INDUSTRIES[value['industry']]['terms']
                for doc in documents:
                    match=re.search('|'.join(re.escape(t) for t in terms),doc['text'],re.I)
                    if match:
                        start=max(0,match.start()-80);quote=doc['text'][start:start+300]
                        if len(quote)>=12:
                            evidence['industry']={'url':doc['url'],'quote':quote};break
        # Infer a zone only for an explicitly supported, sourced office city.
        spec=value['target_session']['spec']
        zone=CITY_ZONES.get((value.get('country'),normalize(spec['city'])))
        location=evidence.get('location',{})
        location_valid=any(d['url'].rstrip('/')==location.get('url','').rstrip('/') and
                           12<=len(location.get('quote',''))<=400 and normalize(location['quote']) in normalize(d['text'])
                           for d in documents)
        if zone and location_valid and targeting.location_quote_matches(location.get('quote',''),spec) and targeting.city_matches(value.get('location_city',''),spec['city']):
            # The single review action explicitly confirms these displayed facts.
            value.update(company_time_zone=zone,company_time_zone_verified=True,
                         company_time_zone_source=location['url'])
        value['target_reasons']=targeting.target_check(value)
    return value


def next_window(config, lead, clock=None):
    clock=clock or datetime.now(timezone.utc)
    zone=delivery_zone(config,lead);local=clock.astimezone(zone)
    for day in range(8):
        date=local+timedelta(days=day)
        if date.weekday() not in config['send_weekdays']:continue
        start=date.replace(hour=config['send_hours'][0],minute=0,second=0,microsecond=0)
        end=start.replace(hour=config['send_hours'][1])
        if day==0 and local>=end:continue
        return max(local,start).astimezone(timezone.utc).isoformat()
    raise ValueError('No configured weekday delivery window')


def evaluate(store, lead, config, profile, prefs, exclusions):
    candidate=sourced_candidate(lead)
    assessment=assess(candidate,prefs,exclusions)
    candidate['score']=assessment['score'];candidate['reasons']=assessment['reasons']
    issues=[]
    if candidate.get('target_session'):
        issues.extend(targeting.target_check(candidate))
    if candidate['score']<config['minimum_fit_score']:
        issues.append('Research fit is '+str(candidate['score'])+'/100; needs '+str(config['minimum_fit_score'])+'. Complete the supporting research.')
    if lead.get('status') in {'Sending','Sent','Replied','Interview','Won','Rejected','Closed','Do Not Contact'}:
        issues.append('This opportunity is contacted, closed or suppressed.')
    if any(r['lead_id']==lead['id'] and r['state'] in ('sending','sent','uncertain') for r in delivery.rows(store)):
        issues.append('A delivery was already attempted. Review its delivery state first.')
    if not candidate.get('notion_page_id'):issues.append('Sync this company to Notion first.')
    candidate.update(status='Ready',approved=True,**{key:True for key in REVIEW_FLAGS})
    # This records the meaning of the user's explicit decision, never a scraped instruction.
    candidate['contact_review_notes']=candidate.get('contact_review_notes','').strip()
    if ATTESTATION not in candidate['contact_review_notes']:
        candidate['contact_review_notes']=(candidate['contact_review_notes']+'\nSingle review: '+ATTESTATION).strip()
    if not candidate.get('draft'):issues.append('Save a valid email draft first.')
    if candidate.get('email','') not in candidate.get('email_candidates',[]) or not candidate.get('contact_source_url'):issues.append('Add an official source containing the selected shared business email address.')
    try:delivery.gate(store,candidate,config,profile,prefs,exclusions)
    except (ValueError,TypeError) as exc:
        if 'check Targeting Reviewed' not in str(exc):issues.append(str(exc))
    except KeyError:issues.append('Complete the required research and draft fields before approval.')
    due=None
    try:due=next_window(config,candidate)
    except (ValueError,KeyError,TypeError) as exc:issues.append(str(exc))
    setup=[]
    try:delivery.require_approval(store,delivery.policy(config,profile,prefs,exclusions))
    except ValueError as exc:setup.append(str(exc))
    if config['mode']!='automatic':setup.append('Automatic delivery is not enabled. Review the sending plan before enabling it.')
    already=lead.get('status')=='Ready' and lead.get('approved') and all(lead.get(k) for k in REVIEW_FLAGS)
    token=delivery.fingerprint({'lead':lead,'policy':delivery.policy(config,profile,prefs,exclusions)})
    return candidate,{'can_approve':not issues and not already,'already_approved':bool(already),'blockers':list(dict.fromkeys(issues)),
        'setup_blockers':setup,'token':token,'score':candidate['score'],
        'recipient':candidate.get('email',''),'time_zone':candidate.get('company_time_zone',''),
        'timezone_source':candidate.get('company_time_zone_source',''),
        'contact_source':candidate.get('contact_source_url',''),'next_window':due,
        'attestation':ATTESTATION,'schedule':'Weekdays '+str(config['send_hours'][0])+':00–'+str(config['send_hours'][1])+':00 in the company timezone; daily limits still apply.'}


def approve(store, notion, lead, config, profile, prefs, exclusions, token, confirmed):
    if confirmed is not True:raise ValueError('Review the recipient, message and outreach purpose before approving.')
    with delivery.lock(store):
        current=delivery.remote_lead(store,notion,copy.deepcopy(lead),persist=False)
        candidate,result=evaluate(store,current,config,profile,prefs,exclusions)
        if token!=result['token']:raise ValueError('Company, draft or settings changed. Reopen the review before approving.')
        if result['already_approved']:raise ValueError('This company is already approved. Check the delivery queue or sender setup.')
        if result['blockers']:raise ValueError('Approval held: '+'; '.join(result['blockers']))
        props={'EMAIL':{'email':candidate['email']},'STATUS':{'status':{'name':'Ready'}},'Approved':{'checkbox':True},
               **{key:{'checkbox':True} for key in NOTION_FLAGS},
               'Contact Source URL':{'url':candidate['contact_source_url']},
               'Contact Source Notes':{'rich_text':rich(candidate['contact_review_notes'])},
               'Match Score':{'number':candidate['score']},
               'Research Notes':{'rich_text':rich(research_notes(candidate))},
               'Fit Reasons':{'rich_text':rich('\n'.join(candidate['reasons']))},
               'Scheduled Time':{'date':{'start':result['next_window']}}}
        if candidate.get('company_time_zone') and candidate.get('company_time_zone_source'):
            props.update({'Company Time Zone':{'select':{'name':candidate['company_time_zone']}},
                          'Company Time Zone Verified':{'checkbox':True},
                          'Company Time Zone Source':{'url':candidate['company_time_zone_source']}})
        # Persist reconciled evidence before Notion becomes Ready. A failed PATCH
        # leaves the local record unapproved and creates no outbox item.
        candidate.update(status=current['status'],approved=False,draft_dirty=False)
        store.save(candidate)
        notion.request('pages/'+candidate['notion_page_id'],'PATCH',{'properties':props})
        candidate.update(status='Ready',approved=True,scheduled_time=result['next_window'],reviewed_at=delivery.now())
        store.save(candidate)
        return {'approved':True,'setup_blockers':result['setup_blockers'],
                'message':'Approved for the next eligible delivery window. '+('Finish the sender setup shown in this review before delivery.' if result['setup_blockers'] else 'The running agent will queue it; daily limits and stop conditions still apply.')}
