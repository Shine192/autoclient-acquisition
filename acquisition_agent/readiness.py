"""Explain configuration and per-opportunity holds without queueing or sending."""
import os
import ssl
from . import delivery
from .core import read_json


def report(store, config, profile, prefs, exclusions, gmail=None, notion=None):
    blockers=[]
    checks={'mode':config['mode'],'paused':store.paused(),
            'schedule_basis':config.get('schedule_basis','sender'),
            'send_hours':config['send_hours'],'daily_limit_timezone':config['timezone'],
            'gmail_token_present':(store.root/'credentials/gmail-token.json').exists(),
            'notion_key_present':bool(os.getenv('NOTION_TOKEN')),
            'tls_library':ssl.OPENSSL_VERSION,'tls13_available':ssl.HAS_TLSv1_3}
    try:
        checks['self_test_reply_verified']=bool(read_json(store.root/'test-evidence.json').get('reply_verified'))
    except (OSError,ValueError):
        checks['self_test_reply_verified']=False
    if not checks['gmail_token_present']:blockers.append('Local Gmail authorization is missing')
    if not checks['notion_key_present']:blockers.append('Local Notion token is missing')
    if not checks['self_test_reply_verified']:blockers.append('Live self-inbox reply verification is missing')
    if store.paused():blockers.append('Agent is paused')
    if not exclusions.get('confirmed'):blockers.append('Exclusion list is not confirmed')
    if 'Cold Outreach' in config['allowed_kinds'] and not config.get('business_postal_address','').strip():
        blockers.append('Cold outreach requires your business mailing address and contact-purpose review')
    if config.get('campaign_required'):
        delivery.init(store)
        from . import campaigns
        campaign=campaigns.active(store)
        checks['campaign']=campaign
        if not campaign:blockers.append('Choose an on-demand campaign target in Delivery queue')
        elif not campaign['remaining']:blockers.append('Campaign target reached; further sending is held')
    manifest=delivery.policy(config,profile,prefs,exclusions)
    try:
        checks['exact_policy_approved']=read_json(store.root/'sending-approval.json').get('sha256')==delivery.fingerprint(manifest) and config['mode']=='automatic'
    except (OSError,ValueError):checks['exact_policy_approved']=False
    if not checks['exact_policy_approved']:blockers.append('Exact production policy has not been approved')
    if gmail:
        try:
            checks['gmail_account_verified']=gmail.identity()==profile['sender_email'].lower()
            if not checks['gmail_account_verified']:blockers.append('Gmail account does not match sender')
        except Exception as exc:
            checks['gmail_account_verified']=False;blockers.append('Gmail check failed: '+str(exc)[:160])
    candidates=[]
    preview=dict(config,mode='automatic')
    for lead in store.leads():
        if lead.get('is_demo') or lead.get('status') in delivery.STOP:continue
        try:
            if notion and lead.get('notion_page_id'):lead=delivery.remote_lead(store,notion,lead)
            delivery.gate(store,lead,preview,profile,prefs,exclusions)
            held=''
        except Exception as exc:held=str(exc)[:200]
        candidates.append({'id':lead['id'],'company':lead.get('company',''),'status':lead.get('status',''),
                           'eligible_at_review_gates':not bool(held),'hold':held})
    return {'checks':checks,'production_blockers':blockers,'opportunities':candidates,
            'message':'Readiness only. No queue entries created and no email sent. Source freshness is checked again at dispatch.'}
