"""Build an encrypted seed from a read-only Mac snapshot. Never send email."""
import json,sqlite3,time
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .queue import digest

def seed(root,links=None):
    root=Path(root)
    source=sqlite3.connect((root/'state/agent.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    db=sqlite3.connect(':memory:')
    try:source.backup(db)
    finally:source.close()
    db.row_factory=sqlite3.Row
    settings={name:json.loads((root/'config'/(name+'.json')).read_text()) for name in ('sending','profile','preferences','exclusions')}
    cfg=settings['sending'];cfg.update(mode='automatic',schedule_basis='company',follow_up_days=[],follow_ups_enabled=False,daily_limit=50,minimum_interval_seconds=180,send_hours=[8,11],send_weekdays=[0,1,2,3,4])
    from acquisition_agent.notion_compat import SOURCE
    if settings['preferences']['notion_leads_source_id']!=SOURCE:raise ValueError('Connect the original Outreach database before handover')
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    outbox=[dict(r) for r in db.execute('SELECT * FROM outbox')] if 'outbox' in tables else []
    if any(r['state'] in ('sending','uncertain') for r in outbox):raise ValueError('Resolve uncertain Mac sends before handover')
    records={'settings':{'kind':'settings','data':settings},'control':{'kind':'control','paused':True,'migration_complete':False,'active_attempt':'','last_attempt':0,'days':{},'migration_imported':True,'followups':'disabled'}}
    mapping={r['lead_id']:r for r in (links or {}).get('records',[])}
    for r in db.execute('SELECT data FROM leads'):
        lead=json.loads(r[0]);key=lead['id']
        if key in mapping and lead.get('notion_page_id')==mapping[key]['old_page_id']:lead['notion_page_id']=mapping[key]['new_page_id']
        lead.pop('prompt_file',None);lead['draft_dirty']=False
        records['lead_'+key]={'kind':'lead','data':lead}
    for item in outbox:
        records['legacy_'+item['id']]={'kind':'legacy_outbox','data':item}
        if item.get('mode')!='automatic' or not item.get('attempted_at'):continue
        for v,prefix in ((item['recipient'],'recipient_'),(item['company'],'company_')):
            records[prefix+digest(v.lower())]={'kind':'dedup','outbox_id':'legacy_'+item['id']}
        timestamp=datetime.fromisoformat(item['attempted_at']).timestamp()
        if item['state']=='sent' and item.get('gmail_id') and item.get('thread_id'):
            records['outbox_'+item['id']]={'kind':'outbox','id':item['id'],'lead_id':item['lead_id'],
                'mode':'legacy','state':'sent','recipient':item['recipient'],'company':item['company'],
                'attempted_at':timestamp,'message_id':item['message_id'],'provider_message_id':item.get('provider_message_id',''),
                'gmail_id':item['gmail_id'],'thread_id':item['thread_id']}
        day=datetime.fromtimestamp(timestamp,timezone.utc).astimezone(ZoneInfo(cfg['timezone'])).date().isoformat()
        control=records['control'];control['days'][day]=control['days'].get(day,0)+1;control['last_attempt']=max(control['last_attempt'],timestamp)
    if 'suppressions' in tables:
        for r in db.execute('SELECT * FROM suppressions'):
            record=dict(r);records['suppress_'+digest(record['value'].lower())]=dict(record,kind='suppression')
    db.close()
    records['control']['seed_at']=time.time()
    return records
