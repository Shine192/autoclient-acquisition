"""Read-only monitoring of local tasks, Notion holds and encrypted hosted history."""
import base64
import copy
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from . import incidents
from .providers import text_value

REPOSITORY='Shine192/autoclient-acquisition'

def cached(store):
    incidents.load(store)
    row=store.db.execute("SELECT data FROM incident_data WHERE name='monitor_cache'").fetchone()
    return json.loads(row[0]) if row else {'notion':{},'cloud':{},'cloud_events':[],'names':{}}

def cache(store,value):
    store.db.execute('INSERT OR REPLACE INTO incident_data VALUES(?,?)',('monitor_cache',json.dumps(value)));store.db.commit()

def cloud_read(state):
    """Existing gh authentication is read-only here. The key stays on this Mac."""
    key=Path(state)/'credentials/error-center-ledger.key'
    if not key.is_file():return None
    if not shutil.which('gh'):raise ValueError('Cloud monitoring connection failed: GitHub CLI is unavailable')
    result=subprocess.run(['gh','api','--hostname','github.com','repos/'+REPOSITORY+'/contents/ledger.enc?ref=shine-delivery-state'],capture_output=True,text=True,timeout=40)
    if result.returncode:raise ValueError('Cloud monitoring connection failed')
    data=json.loads(result.stdout)
    if data.get('encoding')!='base64' or len(data.get('content',''))>1300000:raise ValueError('Encrypted monitoring state is invalid')
    from hosted_sender.github_state import Codec
    return Codec(key.read_text().strip(),REPOSITORY).open(base64.b64decode(data['content']).decode())

def step_for_stage(stage):
    return {'notion_import':'approval','receipt_sync':'receipts','gmail_identity':'setup','reply_check':'replies',
            'preflight':'preflight','source_and_history_check':'preflight','durable_claim':'queue',
            'gmail_dispatch':'sending','receipt_persistence':'receipts','receipt_reference':'receipts',
            'notion_receipt_sync':'notion_sync','completed':'setup'}.get(stage,'setup')

def import_tasks(store):
    incidents.load(store)
    exists=store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='panel_tasks'").fetchone()
    if not exists:return
    rows=store.db.execute('SELECT id,kind,status,result FROM panel_tasks ORDER BY created_at DESC LIMIT 30').fetchall()
    marker=store.db.execute("SELECT data FROM incident_data WHERE name='task_imports'").fetchone()
    imported=json.loads(marker[0]) if marker else {}
    for key,kind,status,result in reversed(rows):
        if status in ('Queued','Running'):continue
        if imported.get(key)==status:continue
        value=json.loads(result)
        if status=='Interrupted' and not value.get('error'):value['error']='Panel stopped before completion'
        incidents.task_result(store,kind,key,value,observation=key+'-'+status)
        imported[key]=status
    imported=dict(list(imported.items())[-200:])
    store.db.execute('INSERT OR REPLACE INTO incident_data VALUES(?,?)',('task_imports',json.dumps(imported)));store.db.commit()

def refresh(store,prefs,notion=None,reader=cloud_read,clock=time.time):
    """Network reads only. A missing source never resolves its saved incidents."""
    now=clock();value=cached(store);events=incidents.load(store);names=value.get('names',{})
    if notion is not None:
        try:
            pages=[]
            for page in notion.query(prefs['notion_leads_source_id']):
                pages.append(page)
                if len(pages)>1000:raise ValueError('Monitoring read limit reached; records are preserved')
            for page in pages:
                p=page['properties'];key=text_value(p.get('Deduplication Key',{})) or page['id']
                name=''.join(x.get('plain_text',x.get('text',{}).get('content','')) for x in p.get('Name',{}).get('title',[]))
                names[incidents.scope_id(key)]=name[:160]
                status=(p.get('STATUS',{}).get('status') or p.get('STATUS',{}).get('select') or {}).get('name')
                errors=text_value(p.get('Error',{})).strip()
                if status in ('Sent','Replied','Interview','Won','Closed','Rejected','Do Not Contact'):errors=''
                if status is None:continue
                conditions=[x.strip().lstrip('- ').strip() for x in errors.splitlines() if x.strip()]
                if not conditions and status=='Approve' and text_value(p.get('Delivery State',{})).startswith('Approved but blocked:'):
                    conditions=[text_value(p['Delivery State'])]
                observed=page.get('last_edited_time') or 'current-'+hashlib.sha256(errors.encode()).hexdigest()[:16]
                events=incidents.observe(events,'notion','approval',key,conditions,observation=observed,page_id=page['id'],at=now)
                for stage in (1,2):
                    note=text_value(p.get('Follow-up '+str(stage)+' Delivery',{}))
                    normal_stop=status in ('Closed','Do Not Contact','Rejected','Replied','Interview','Won') or bool(text_value(p.get('Reply Status',{})).strip())
                    problem=[note] if note.startswith(('Held:','Failed:')) and not normal_stop else []
                    events=incidents.observe(events,'notion','followup',key+'-'+str(stage),problem,observation=observed,page_id=page['id'],at=now)
            value['notion']={'state':'connected','checked_at':now,'records_checked':len(pages)}
            events=incidents.observe(events,'monitor','monitoring','notion',[],at=now)
        except Exception as exc:
            value['notion']={**value.get('notion',{}),'state':'unavailable','attempted_at':now}
            events=incidents.observe(events,'monitor','monitoring','notion',[exc],at=now)
    else:value['notion']={**value.get('notion',{}),'state':'not_connected'}
    try:
        records=reader(store.root)
        if records is None:value['cloud']={**value.get('cloud',{}),'state':'not_connected'}
        else:
            incoming=(records.get('incident_history') or {}).get('events',[])
            overlay=value.get('state_events',[]);active=set()
            for item in records.values():
                if item.get('kind')!='outbox' or item.get('mode')=='test':continue
                scope=item.get('lead_id') or item['id']
                if item.get('state') in ('sending','uncertain'):
                    overlay=incidents.observe(overlay,'cloud','sending',scope,['Unresolved delivery outcome; reconcile the original attempt'],observation=item['id'],at=now)
                    active.add(('sending',incidents.scope_id(scope)))
                if item.get('notion_sync_pending'):
                    overlay=incidents.observe(overlay,'cloud','notion_sync',scope,['Notion receipt sync failed'],observation=item['id'],at=now)
                    active.add(('notion_sync',incidents.scope_id(scope)))
            # The last pre-upgrade failed run is useful; earlier failures cannot
            # be reconstructed. Its exception message is never available here.
            health=records.get('delivery_health') or {}
            if health.get('outcome')=='failed':
                error=health.get('error') or {};message='HTTP '+str(error['http_status']) if error.get('http_status') else error.get('category','UnexpectedError')
                step=step_for_stage(health.get('stage'))
                overlay=incidents.observe(overlay,'cloud',step,'legacy-worker',[message],observation=health.get('run_id') or health.get('completed_at'),run_id=health.get('run_id'),at=now)
                active.add((step,'legacy-worker'))
            for event in list(overlay):
                if (event['step'],event['scope']) not in active:
                    overlay=incidents.observe(overlay,'cloud',event['step'],event['scope'],[],at=now)
            value['state_events']=overlay
            value['cloud_events']=incoming+overlay
            for record in records.values():
                if record.get('kind')=='lead':
                    lead=record['data'];names[incidents.scope_id(lead['id'])]=str(lead.get('company',''))[:160]
            control=records.get('control',{})
            value['cloud']={'state':'connected','checked_at':now,'last_run_at':health.get('completed_at'),
                            'last_run_outcome':health.get('outcome'),'paused':bool(control.get('paused')),
                            'queued':sum(r.get('kind')=='outbox' and r.get('mode')!='test' and r.get('state')=='queued' for r in records.values()),
                            'approval_check':records.get('notion_approval_health',{}),
                            'history_available':bool(records.get('incident_history'))}
            events=incidents.observe(events,'monitor','monitoring','cloud',[],at=now)
    except Exception as exc:
        value['cloud']={**value.get('cloud',{}),'state':'unavailable','attempted_at':now}
        events=incidents.observe(events,'monitor','monitoring','cloud',[exc],at=now)
    value.update(names=names,last_refreshed=now)
    incidents.merge_remote_observations(store,events);cache(store,value)
    return snapshot(store)

def snapshot(store):
    import_tasks(store);value=cached(store)
    value.setdefault('names',{}).update({incidents.scope_id(l['id']):str(l.get('company',''))[:160] for l in store.leads()})
    events=incidents.load(store)+value.get('cloud_events',[])
    # The same failed gate may be visible in both Notion and the sender journal.
    # Keep one readable card, retaining both source names without double counts.
    combined={}
    for event in events:
        item=incidents.public_event(event,value.get('names'))
        key=(item['step'],item['scope'],item['code'])
        prior=combined.get(key)
        if prior is None:item['sources']=[item['source']];combined[key]=item
        else:
            sources=sorted(set(prior['sources']+[item['source']]))
            effective=lambda e:max(e['last_seen'],e.get('resolved_at') or 0)
            newest=item if effective(item)>effective(prior) else prior
            merged=copy.deepcopy(newest);merged['sources']=sources
            merged['first_seen']=min(prior['first_seen'],item['first_seen']);merged['occurrences']=max(prior['occurrences'],item['occurrences'])
            combined[key]=merged
    items=sorted(combined.values(),key=lambda e:(e['status']=='open',e['severity']=='urgent',e['last_seen']),reverse=True)
    return {'incidents':items,'steps':incidents.STEPS,'sources':{k:value.get(k,{}) for k in ('notion','cloud')},
            'local_logging_available':incidents.LOCAL_LOGGING_AVAILABLE,
            'last_refreshed':value.get('last_refreshed'),'retention':incidents.LIMIT,
            'history_note':'History starts with this update. Existing visible failures are imported; unavailable older errors cannot be reconstructed.',
            'waiting_note':'Queued messages waiting for company-local hours, spacing or the daily limit are normal waiting, not errors.',
            'counts':{'open':sum(x['status']=='open' for x in items),'resolved':sum(x['status']=='resolved' for x in items),'urgent':sum(x['status']=='open' and x['severity']=='urgent' for x in items)}}
