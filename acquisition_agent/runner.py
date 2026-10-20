"""Foreground local agent. Manual AI drafts wait for human import and review."""
import fcntl
import json
import os
import time
from argparse import Namespace
from datetime import datetime, timezone
from .core import now, read_json, write_json


def due(last, hours, clock=None):
    try:
        return ((clock or datetime.now(timezone.utc))-datetime.fromisoformat(last)).total_seconds()>=hours*3600
    except (TypeError,ValueError):return True


def run(store, root, hours=6, once=False):
    from .__main__ import settings, run_discovery, sync, sending_command
    from .providers import Notion
    if not 6<=hours<=168:raise ValueError('Discovery interval must be 6–168 hours')
    def log(kind,result):
        record={'at':now(),'kind':kind,'result':result}
        with (store.root/'agent-events.jsonl').open('a') as handle:handle.write(json.dumps(record,ensure_ascii=False)+'\n')
        print(json.dumps(record,ensure_ascii=False),flush=True)
    with (store.root/'agent.lock').open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another combined agent is already running') from None
        last_sync=0
        try:
            while True:
                with (store.root/'worker.lock').open('a') as cycle_lock:
                    try:fcntl.flock(cycle_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:
                        if once:return
                        time.sleep(1)
                        continue
                    prefs,profile,exclusions=settings()
                    if store.paused():
                        log('paused',{'message':'No new discovery or sending'})
                    else:
                        # Research starts only from the dashboard, never on a timer.
                        if os.getenv('NOTION_TOKEN') and (once or time.monotonic()-last_sync>=300):
                            last_sync=time.monotonic()
                            try:log('notion',sync(store,Notion(),prefs['notion_leads_source_id']))
                            except Exception as exc:log('notion error',{'error':str(exc)[:300]})
                        sending=read_json(root/'config/sending.json')
                        if sending['mode']=='automatic':
                            try:sending_command(Namespace(command='send-once'),store,prefs,profile,exclusions)
                            except Exception as exc:log('delivery held',{'error':str(exc)[:300]})
                if once:return
                time.sleep(30)
        finally:fcntl.flock(handle,fcntl.LOCK_UN)
