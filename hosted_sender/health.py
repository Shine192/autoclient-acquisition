"""Receipt-aware operational reports. Public output contains aggregate data only."""
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

KEY = 'delivery_health'
STAGES = {'starting', 'receipt_sync', 'notion_import', 'gmail_identity', 'reply_check',
          'preflight', 'source_and_history_check', 'durable_claim', 'gmail_dispatch',
          'receipt_persistence', 'receipt_reference', 'notion_receipt_sync', 'completed'}


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp is not None else None


def safe_error(exc):
    # Exception messages may contain provider bodies, private contacts or tokens.
    match = re.search(r'\bHTTP ([1-5][0-9]{2})\b', str(exc))
    known = {'ValueError', 'KeyError', 'TypeError', 'StateError', 'TimeoutError', 'OSError'}
    return {'category': type(exc).__name__ if type(exc).__name__ in known else 'UnexpectedError',
            'http_status': int(match.group(1)) if match else None}


def next_window(queue, settings, now):
    """Earliest remaining queue window, not a promise of eligibility or delivery."""
    cfg = settings['sending']; control = queue.control()
    plan = queue.db.get('campaign_' + control['active_campaign']) if control.get('active_campaign') else None
    if not plan or control.get('paused') or control.get('active_attempt') or plan['sent_attempts'] >= plan['maximum_sends']:
        return None
    from .worker import settings_hash
    if (os.getenv('SHINE_DELIVERY_ENABLED') != 'true' or cfg['mode'] != 'automatic'
            or not control.get('migration_complete') or control.get('approved_hash') != settings_hash(settings)):
        return None
    candidates = []
    for item in queue.db.list('outbox'):
        if item.get('state') != 'queued' or item.get('campaign') != plan['id']:continue
        zone = ZoneInfo(item['company_timezone'])
        for day in sorted(plan['dates']):
            date = datetime.fromisoformat(day)
            if date.weekday() not in cfg['send_weekdays']:continue
            start = date.replace(hour=cfg['send_hours'][0],tzinfo=zone).timestamp()
            end = date.replace(hour=cfg['send_hours'][1],tzinfo=zone).timestamp()
            candidate = max(now, start, item['due_at'], control.get('last_attempt',0) + cfg['minimum_interval_seconds'])
            counter_zone = ZoneInfo(cfg['timezone'])
            counter_day = datetime.fromtimestamp(candidate,timezone.utc).astimezone(counter_zone)
            if control.get('days',{}).get(counter_day.date().isoformat(),0) >= cfg['daily_limit']:
                candidate = max(candidate,(counter_day + timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
            if candidate < end:
                candidates.append(candidate);break
    return iso(min(candidates)) if candidates else None


def timer_status(queue, now):
    api = getattr(queue.db, 'api', None)
    if api is None:return {'state':'unavailable','last_event_at':None,'last_success_at':None}
    try:
        workflow = api('actions/workflows/delivery-timer.yml')
        if workflow.get('state') != 'active':return {'state':'disabled','last_event_at':None,'last_success_at':None}
        runs = api('actions/workflows/delivery-timer.yml/runs?event=schedule&per_page=5').get('workflow_runs',[])
        if not runs:return {'state':'never_observed','last_event_at':None,'last_success_at':None}
        latest = runs[0];created = latest['created_at']
        age = now - datetime.fromisoformat(created.replace('Z','+00:00')).timestamp()
        if age > 20*60:state = 'stale'
        elif latest.get('status') != 'completed':state = 'delayed' if age > 10*60 else latest['status']
        else:state = 'recent_success' if latest.get('conclusion') == 'success' else 'failed'
        success = next((r['created_at'] for r in runs if r.get('conclusion') == 'success'),None)
        return {'state':state,'last_event_at':created,'last_success_at':success}
    except Exception:
        return {'state':'unavailable','last_event_at':None,'last_success_at':None}


def snapshot(queue, settings, now=None, timer=None):
    from .worker import settings_hash
    now = time.time() if now is None else now
    items = [v for v in queue.db.list('outbox') if v.get('mode') != 'test']
    counts = Counter(v['state'] for v in items);control = queue.control()
    plan = queue.db.get('campaign_' + control['active_campaign']) if control.get('active_campaign') else None
    day = datetime.fromtimestamp(now,timezone.utc).astimezone(ZoneInfo(settings['sending']['timezone'])).date()
    accepted_today = sum(v['state']=='sent' and v.get('attempted_at') is not None and
        datetime.fromtimestamp(v['attempted_at'],timezone.utc).astimezone(ZoneInfo(settings['sending']['timezone'])).date()==day for v in items)
    report = {'checked_at':iso(now),'paused':bool(control.get('paused')),
        'delivery_enabled':os.getenv('SHINE_DELIVERY_ENABLED')=='true',
        'configuration_ready':bool(control.get('migration_complete') and control.get('test_verified')
            and control.get('approved_hash')==settings_hash(settings) and settings['sending']['mode']=='automatic'),
        'outstanding_attempt':bool(control.get('active_attempt')),
        'queued':counts['queued'],'held':counts['blocked'],
        'confirmed_sent':counts['sent'],'confirmed_sent_today':accepted_today,
        'uncertain':counts['sending']+counts['uncertain'],
        'notion_sync_pending':sum(bool(v.get('notion_sync_pending')) for v in items),
        'notion_sync_unverified':sum(v['state']=='sent' and not v.get('notion_receipt_synced') and not v.get('notion_sync_pending') for v in items),
        'next_queue_window_utc':next_window(queue,settings,now),
        'daily_limit':settings['sending']['daily_limit'],
        'campaign':({'maximum_attempts':plan['maximum_sends'],'attempts_used':plan['sent_attempts'],
                     'remaining_attempts':max(0,plan['maximum_sends']-plan['sent_attempts'])} if plan else None),
        'timer':timer if timer is not None else timer_status(queue,now),
        'last_worker_run':queue.db.get(KEY)}
    recent_success=report['timer'].get('last_success_at')
    timer_verified=bool(recent_success and now-datetime.fromisoformat(recent_success.replace('Z','+00:00')).timestamp()<20*60
                        and report['timer']['state'] in ('recent_success','queued','in_progress','running'))
    if report['outstanding_attempt'] or report['uncertain']:overall='blocked_unresolved_delivery'
    elif report['paused'] or not report['delivery_enabled']:overall='paused'
    elif not report['configuration_ready']:overall='blocked_configuration'
    elif report['notion_sync_pending'] or report['notion_sync_unverified']:overall='attention_notion_sync'
    elif not plan:overall='idle_no_campaign'
    elif plan['sent_attempts']>=plan['maximum_sends']:overall='idle_campaign_complete'
    elif not timer_verified:overall='attention_timer_unverified'
    else:overall='operational'
    report['overall_state']=overall
    return report


def emit(report):
    """A fixed field set keeps contacts, research and exception text out of logs."""
    print('SHINE_HEALTH '+json.dumps(report,sort_keys=True))
    path = os.getenv('GITHUB_STEP_SUMMARY')
    if not path:return
    run = report.get('last_worker_run') or {}
    rows = [('Overall state',report.get('overall_state','Unknown')),
            ('Worker outcome',run.get('outcome','Not recorded')),
            ('Worker stage',run.get('stage','Not recorded')),
            ('Last worker completion',run.get('completed_at') or 'Not recorded'),
            ('Last successful worker check',run.get('last_success_at') or 'Not recorded'),
            ('Automatic timer',report.get('timer',{}).get('state','unavailable')),
            ('Last timer event',report.get('timer',{}).get('last_event_at') or 'None observed'),
            ('Paused',report.get('paused','Unknown')),('Delivery enabled',report.get('delivery_enabled','Unknown')),
            ('Approved setup ready',report.get('configuration_ready','Unknown')),
            ('Queued',report.get('queued','Unknown')),('Held',report.get('held','Unknown')),
            ('Gmail accepted today',report.get('confirmed_sent_today','Unknown')),
            ('Notion sync pending',report.get('notion_sync_pending','Unknown')),
            ('Notion receipt checks unverified',report.get('notion_sync_unverified','Unknown')),
            ('Unresolved attempts',report.get('uncertain','Unknown')),
            ('Next queue window, UTC',report.get('next_queue_window_utc') or 'None currently available')]
    text = '# Outreach delivery health\n\n| Check | Result |\n|---|---|\n'
    text += ''.join('| '+k+' | '+str(v)+' |\n' for k,v in rows)
    text += '\nQueued times are conditional. A successful manual check does not verify the timer. '
    text += 'A saved Gmail receipt prevents redispatch even if Notion syncing fails.\n'
    try:
        with Path(path).open('a') as handle:handle.write(text)
    except OSError:print('Health summary file unavailable; see SHINE_HEALTH in the operation log.')


def monitored_run(queue, settings, operation, now=time.time):
    started = now();phase = {'stage':'starting'}
    def progress(stage):phase['stage'] = stage if stage in STAGES else 'starting'
    before = sum(v['state']=='sent' and v.get('mode')!='test' for v in queue.db.list('outbox'))
    error = None;result = None
    try:
        result = operation(progress)
        progress('completed')
        return result
    except Exception as exc:
        error = safe_error(exc)
        raise
    finally:
        completed = now()
        try:
            report = snapshot(queue,settings,completed)
            previous = report.pop('last_worker_run') or {}
            outcome = 'failed' if error else ('attention' if report['notion_sync_pending'] or report['outstanding_attempt'] else 'ok')
            event = os.getenv('GITHUB_EVENT_NAME','local')
            event = event if event in ('schedule','workflow_dispatch','workflow_call','local') else 'other'
            run_id = os.getenv('GITHUB_RUN_ID','')
            record = {'kind':'operational_health','started_at':iso(started),'completed_at':iso(completed),
                'event':event,'run_id':run_id if run_id.isdigit() else None,
                'outcome':outcome,'stage':phase['stage'],'error':error,
                'confirmed_sends_this_run':max(0,report['confirmed_sent']-before),
                'last_success_at':iso(completed) if outcome=='ok' else previous.get('last_success_at'),
                'last_scheduled_success_at':iso(completed) if outcome=='ok' and event=='schedule' else previous.get('last_scheduled_success_at')}
            queue.db.transaction(lambda tx:tx.put(KEY,record))
            report['last_worker_run']=record;emit(report)
            if outcome=='attention':print('::warning::Delivery health needs attention. Saved receipts must not be resent; pending Notion updates can be retried.')
        except Exception:
            # A state persistence error may make the last result unknowable.
            # Never replace the original error, or claim a healthy ledger.
            emit({'checked_at':iso(completed),'timer':{'state':'unavailable'},
                  'last_worker_run':{'outcome':'failed','stage':phase['stage'],
                    'error':error or {'category':'StateError','http_status':None},'completed_at':iso(completed)}})
            if error is None:raise
