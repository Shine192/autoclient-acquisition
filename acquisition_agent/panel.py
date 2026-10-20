"""Loopback-only control panel. Does not expose credentials or send email."""
import fcntl
import json
import os
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from . import __version__
from .core import Store, assess, draft_prompt, read_json, validate_draft, clear_draft_repair, write_json, now
from . import delivery
from . import targeting
from . import campaigns
from . import review

ASSETS = Path(__file__).with_name('panel_assets')
TERMINAL = {'Sending','Sent','Replied','Interview','Won','Closed','Do Not Contact','Rejected'}


def open_store(state):
    store = Store(state)
    store.db.execute('CREATE TABLE IF NOT EXISTS panel_tasks(id TEXT PRIMARY KEY, kind TEXT, status TEXT, result TEXT, created_at TEXT)')
    store.db.commit()
    return store


def task_rows(store):
    return [{'id':r[0],'kind':r[1],'status':r[2],'result':json.loads(r[3]),'created_at':r[4]} for r in store.db.execute('SELECT * FROM panel_tasks ORDER BY created_at DESC LIMIT 30')]


def scheduled_worker_running(state):
    """Observe the combined runner's lifetime lock, without creating or starting it."""
    try:
        with (Path(state)/'agent.lock').open('r') as handle:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return True
            fcntl.flock(handle,fcntl.LOCK_UN)
    except OSError:return False
    return False


class Panel:
    def __init__(self, root, state):
        self.root, self.state = Path(root), Path(state)
        self.key, self.csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='agent-panel')
        self.busy = threading.Lock()
        self.stopping = threading.Event()
        store = open_store(state)
        store.db.execute("UPDATE panel_tasks SET status='Interrupted',result=? WHERE status IN ('Running','Queued')", (json.dumps({'error':'Panel stopped before completion. Inspect state before retrying.'}),))
        store.db.commit()
        store.db.close()

    def settings(self):
        from .discovery import source_config
        prefs,profile,exclusions,sending = tuple(read_json(self.root / ('config/' + name + '.json')) for name in ('preferences','profile','exclusions','sending'))
        return source_config(prefs,self.root),profile,exclusions,sending

    def snapshot(self):
        store = open_store(self.state)
        try:
            prefs, profile, exclusions, sending = self.settings()
            # Capture task progress before its data. A task finishing midway
            # must not report Completed with a pre-completion lead snapshot.
            task_snapshot=task_rows(store)
            busy_snapshot=self.busy.locked() or any(t['status'] in ('Queued','Running') for t in task_snapshot)
            leads = store.leads()
            for lead in leads:
                if lead.get('status') not in TERMINAL:
                    candidate=review.sourced_candidate(lead)
                    lead['score']=assess(candidate,prefs,exclusions)['score']
            outbox = delivery.rows(store)
            from .readiness import report
            readiness=report(store,sending,profile,prefs,exclusions)
            return {'notion_database_url':('https://www.notion.so/30d351899d8d819baac0ce09ca716b32?v=3ff351899d8d819a9141000c112e565b' if prefs.get('notion_leads_source_id')=='30d35189-9d8d-810b-ab15-000b34956275' else None), 'worker_running':scheduled_worker_running(self.state),'readiness':readiness,'version':__version__, 'paused':store.paused(), 'csrf':self.csrf,
                    'target_sessions':targeting.sessions(store)[:5], 'automatic':__import__(__package__+'.automatic',fromlist=['usage']).usage(store), 'industries':targeting.INDUSTRIES,
                    'setup':{'gmail_token_present':(self.state/'credentials/gmail-token.json').exists(), 'notion_key_present':bool(os.getenv('NOTION_TOKEN')), 'openai_key_present':bool(os.getenv('OPENAI_API_KEY')), 'search_key_present':bool(os.getenv('FIRECRAWL_API_KEY')), 'ai_key_present':bool(os.getenv('OPENAI_API_KEY') or (os.getenv('AI_MODEL') and os.getenv('ANTHROPIC_API_KEY')))},
                    'profile':{k:profile.get(k) for k in ('preferred_name','sender_email','portfolio_url','location','availability','email_signature')},
                    'preferences':{k:prefs.get(k) for k in ('title_keywords','required_skills_any','countries','weekly_capacity_hours','max_post_age_days','design_rate_usd')},
                    'sending':{k:sending.get(k) for k in ('mode','daily_limit','minimum_fit_score','timezone','send_hours','follow_ups_enabled','schedule_basis','send_weekdays','minimum_interval_seconds','campaign_required')},
                    'leads':[{k:lead.get(k) for k in ('id','company','title','kind','status','country','score','email','url','website','discovered_at','notion_page_id','reasons','is_demo','location_city','industry','type')} | {'has_draft':bool(lead.get('draft')),'session_id':(lead.get('target_session') or {}).get('id')} for lead in leads],
                    'campaign':campaigns.active(store),
                    'outbox':[{k:item[k] for k in ('id','lead_id','stage','mode','state','recipient','error','due_at','sent_at')} for item in outbox],
                    'tasks':task_snapshot, 'busy':busy_snapshot,
                    'suppressions':[{'value':v,'reason':r,'created_at':a} for v,r,a in store.db.execute('SELECT * FROM suppressions ORDER BY created_at DESC')]}
        finally:
            store.db.close()

    def detail(self, lead_id):
        store = open_store(self.state)
        try:
            lead = store.get(lead_id)
            prefs, profile, exclusions, sending = self.settings()
            setup_issue=None
            if os.getenv('NOTION_TOKEN') and lead.get('notion_page_id') and not lead.get('draft_dirty'):
                from .providers import Notion
                try:lead=delivery.remote_lead(store,Notion(),lead,persist=False)
                except Exception:setup_issue='Could not refresh this Notion record. Reopen the review after checking the connection.'
            _, readiness=review.evaluate(store,lead,sending,profile,prefs,exclusions)
            if lead.get('draft_dirty'):readiness['blockers'].append('Sync your saved draft to Notion before approving.')
            if not os.getenv('NOTION_TOKEN'):readiness['blockers'].append('Connect Notion in this local app before approving.')
            if setup_issue:readiness['blockers'].append(setup_issue)
            readiness['can_approve']=not readiness['blockers']
            return {k:lead.get(k) for k in ('id','company','title','kind','status','country','url','email','reasons','source_documents','source_text','draft','draft_error','research_warning','remote_eligibility','notion_page_id','rate_per_email','currency','hours_per_week')} | {'prompt':draft_prompt(lead,profile,prefs), 'offer':delivery.recommend(lead,sending), 'review':readiness}
        finally:
            store.db.close()

    def approve_review(self, payload):
        if not os.getenv('NOTION_TOKEN'):raise ValueError('Connect Notion before approving.')
        from .providers import Notion
        store=open_store(self.state)
        try:
            lead=store.get(payload['lead_id'])
            if lead.get('draft_dirty'):raise ValueError('Sync your saved draft to Notion before approving.')
            prefs,profile,exclusions,sending=self.settings()
            return review.approve(store,Notion(),lead,sending,profile,prefs,exclusions,
                                  payload.get('token'),payload.get('reviewed'))
        finally:store.db.close()

    def save_draft(self, payload):
        store = open_store(self.state)
        try:
            lead = store.get(payload['lead_id'])
            if lead.get('status') in TERMINAL or any(item['lead_id']==lead['id'] and item['state'] in ('sending','sent','uncertain') for item in delivery.rows(store)):
                raise ValueError('Closed, suppressed or contacted opportunities cannot be edited')
            prefs, profile, exclusions, _ = self.settings()
            if assess(lead,prefs,exclusions)['status'] in ('Closed','Do Not Contact'):
                raise ValueError('Current targeting or exclusions block this opportunity')
            draft = validate_draft(payload,lead,profile)
            clear_draft_repair(lead)
            lead.update(draft=draft, draft_dirty=True, status='Draft')
            lead.pop('starter_seed',None)
            store.save(lead)
            if os.getenv('NOTION_TOKEN'):
                from .providers import Notion
                try:
                    Notion().save_lead(prefs['notion_leads_source_id'],lead)
                    store.save(lead)
                    from .notion_review import prepare
                    prepare(store,Notion(),lead,self.settings()[3],profile,prefs,exclusions)
                    return {'saved':True,'message':'Draft saved and synced. Finish your review in Notion and set STATUS to Approve.'}
                except Exception:
                    return {'saved':True,'message':'Draft saved locally; Notion sync failed. Use Sync to Notion, then reopen the review.'}
            return {'saved':True,'message':'Draft saved locally. Connect Notion to finish review.'}
        finally:
            store.db.close()

    def preferences(self, payload):
        allowed = {'title_keywords','required_skills_any','countries','weekly_capacity_hours','max_post_age_days','design_rate_usd'}
        if not isinstance(payload,dict) or not set(payload)<=allowed:
            raise ValueError('Unsupported preference field')
        prefs, profile, exclusions, sending = self.settings()
        for name,value in payload.items():
            if name in ('title_keywords','required_skills_any','countries'):
                if not isinstance(value,list) or not 1<=len(value)<=100 or any(not isinstance(v,str) or not 1<=len(v.strip())<=100 for v in value):
                    raise ValueError(name+' must be a nonempty list of short strings')
                prefs[name]=list(dict.fromkeys(v.strip() for v in value))
            elif name in ('weekly_capacity_hours','max_post_age_days'):
                maximum=40 if name=='weekly_capacity_hours' else 365
                if type(value) is not int or not 1<=value<=maximum:
                    raise ValueError(name+' is outside allowed range')
                prefs[name]=value
            else:
                if not isinstance(value,list) or len(value)!=2 or any(type(v) not in (int,float) for v in value) or not 1<=value[0]<=value[1]<=1000:
                    raise ValueError('Design price must be [minimum, maximum] in USD/email')
                # Drafting and offer text use the agreed 20–30 rate. Price edits must be consistent throughout before enabling.
                if value != [20,30]:
                    raise ValueError('Pricing remains USD 20–30/email. Update profile, drafting and offer configuration together before changing it.')
                prefs[name]=value
        write_json(self.root/'config/preferences.json',prefs)
        return {'saved':True,'message':'Targeting saved. Any existing sending-policy approval is invalidated by this change.'}

    def campaign(self,payload):
        store=open_store(self.state)
        try:return campaigns.configure(store,payload.get('action'),payload.get('target'))
        finally:store.db.close()

    def target_session(self, payload):
        store=open_store(self.state)
        try:
            prefs,profile,exclusions,_=self.settings()
            targeting.validate_spec(payload,prefs)
            target=payload.get('campaign_target')
            if target is not None:
                campaigns.configure(store,'update' if campaigns.active(store) else 'start',target)
            return targeting.create_session(store,payload,prefs,profile,exclusions)
        finally:store.db.close()

    def run_task(self, task_id, kind, payload):
        from .__main__ import check_exclusions, ingest, run_discovery, starter, sync
        from .providers import Notion
        from argparse import Namespace
        store = open_store(self.state)
        try:
            with (self.state/'worker.lock').open('a') as handle:
                try:
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError('The worker is finishing a discovery or sync cycle. Wait briefly and retry; older workers must be stopped before updating.') from None
                store.db.execute("UPDATE panel_tasks SET status='Running' WHERE id=?",(task_id,));store.db.commit()
                prefs,profile,exclusions,_=self.settings()
                check_exclusions(store,prefs,exclusions)
                if self.stopping.is_set() or store.paused():
                    raise ValueError('Agent paused or panel stopping; no task started')
                if kind=='starter':
                    result=starter(store,prefs,profile,exclusions)
                elif kind=='import':
                    items=payload.get('leads')
                    if not isinstance(items,list) or not 1<=len(items)<=20 or any(not isinstance(item,dict) for item in items):
                        raise ValueError('Import 1–20 lead objects with source text')
                    result=ingest(store,items,prefs,profile,exclusions,'manual',20,lambda: not self.stopping.is_set() and not store.paused())
                elif kind=='automatic-research':
                    from .automatic import run
                    session=targeting.get_session(store,payload.get('session_id',''))
                    def progress(value):
                        store.db.execute('UPDATE panel_tasks SET result=? WHERE id=?',(json.dumps(dict(value,session_id=session['id'])),task_id));store.db.commit()
                    result=run(store,session,prefs,profile,exclusions,progress,
                        lambda: not self.stopping.is_set() and not store.paused())
                elif kind=='target-import':
                    session=targeting.get_session(store,payload.get('session_id',''))
                    result=targeting.import_batch(store,session,payload.get('leads'),prefs,profile,exclusions)
                    if os.getenv('NOTION_TOKEN'):
                        delivery.setup_schema(Notion(),prefs['notion_leads_source_id'])
                        result['notion_sync']=sync(store,Notion(),prefs['notion_leads_source_id'])
                elif kind=='discover':
                    args=Namespace(search=False,kind='both',ai='manual',limit=20,query=None,keep_running=lambda: not self.stopping.is_set() and not store.paused())
                    result=run_discovery(store,prefs,profile,exclusions,args)
                elif kind=='sync':
                    result=sync(store,Notion(),prefs['notion_leads_source_id'])
                else:
                    raise ValueError('Unknown task')
                if kind in ('automatic-research','target-import'):result['session_id']=session['id']
                status='Needs attention' if result.get('errors') or result.get('notion_sync',{}).get('errors') else 'Paused' if result.get('paused') else 'Completed'
                store.db.execute('UPDATE panel_tasks SET status=?,result=? WHERE id=?',(status,json.dumps(result),task_id));store.db.commit()
        except Exception as exc:
            store.db.execute("UPDATE panel_tasks SET status='Failed',result=? WHERE id=?",(json.dumps({'error':str(exc)[:300]}),task_id));store.db.commit()
        finally:
            store.db.close()
            self.busy.release()

    def submit(self, kind, payload):
        if kind not in ('starter','discover','sync','import','target-import','automatic-research'):
            raise ValueError('Only research, import and sync tasks are available; no sending endpoint')
        if not self.busy.acquire(blocking=False):
            raise ValueError('A panel task is already active')
        store = open_store(self.state)
        task_id=uuid.uuid4().hex
        try:
            store.db.execute('INSERT INTO panel_tasks VALUES(?,?,?,?,?)',(task_id,kind,'Queued','{}',now()));store.db.commit()
            self.executor.submit(self.run_task,task_id,kind,payload)
        except Exception:
            self.busy.release();raise
        finally:
            store.db.close()
        return {'id':task_id,'status':'Queued'}


def make_server(panel, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass  # Bootstrap URL/cookies must never be logged.
        def reply(self,code,body,media='application/json',headers=None):
            raw=(json.dumps(body,ensure_ascii=False) if media=='application/json' else body).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type',media+'; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            for k,v in (headers or {}).items():self.send_header(k,v)
            self.end_headers();self.wfile.write(raw)
        def authorized(self):
            cookies=SimpleCookie()
            try:cookies.load(self.headers.get('Cookie',''))
            except Exception:return False
            value=cookies.get('shine_panel')
            return bool(value and secrets.compare_digest(value.value,panel.key))
        def valid_host(self):
            return self.headers.get('Host')=='127.0.0.1:'+str(self.server.server_port)
        def do_GET(self):
            if not self.valid_host():return self.reply(403,{'error':'Invalid Host'})
            parts=urlsplit(self.path)
            if parts.path=='/' and parse_qs(parts.query).get('key')==[panel.key]:
                return self.reply(303,'','text/plain',{'Location':'/','Set-Cookie':'shine_panel='+panel.key+'; HttpOnly; SameSite=Strict; Path=/'})
            if not self.authorized():return self.reply(401,{'error':'Open the private URL printed by the dashboard command'})
            try:
                if parts.path=='/api/state':return self.reply(200,panel.snapshot())
                if parts.path=='/api/lead':return self.reply(200,panel.detail(parse_qs(parts.query).get('id',[''])[0]))
                assets={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
                if parts.path in assets:
                    name,media=assets[parts.path];return self.reply(200,(ASSETS/name).read_text(),media)
                return self.reply(404,{'error':'Not found'})
            except (ValueError,KeyError):return self.reply(400,{'error':'Unknown opportunity or invalid request'})
            except Exception:return self.reply(500,{'error':'Could not load local state. Check the agent files.'})
        def do_POST(self):
            origin='http://127.0.0.1:'+str(self.server.server_port)
            if not self.valid_host() or not self.authorized() or self.headers.get('Origin')!=origin or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),panel.csrf):
                return self.reply(403,{'error':'Invalid local session, origin or request token'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=250000:raise ValueError('Request must be at most 250 KB')
                payload=json.loads(self.rfile.read(length))
                if not isinstance(payload,dict):raise ValueError('Expected JSON object')
                path=urlsplit(self.path).path
                if path=='/api/pause':
                    if type(payload.get('paused')) is not bool:raise ValueError('paused must be true or false')
                    store=open_store(panel.state)
                    try:store.pause(payload['paused'])
                    finally:store.db.close()
                    return self.reply(200,{'paused':payload['paused']})
                if path=='/api/task':return self.reply(202,panel.submit(payload.get('kind'),payload))
                if path=='/api/campaign':return self.reply(200,panel.campaign(payload))
                if path=='/api/target-session':return self.reply(200,panel.target_session(payload))
                if path=='/api/review-approve':return self.reply(200,panel.approve_review(payload))
                if path=='/api/draft':return self.reply(200,panel.save_draft(payload))
                if path=='/api/preferences':return self.reply(200,panel.preferences(payload))
                return self.reply(404,{'error':'Not found; sending and authorization changes are unavailable here'})
            except (ValueError,KeyError,TypeError) as exc:return self.reply(400,{'error':str(exc)[:300]})
            except Exception:return self.reply(500,{'error':'Local action failed. Check the task list.'})
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def serve(root,state,port=8765):
    state=Path(state);state.mkdir(parents=True,exist_ok=True)
    with (state/'panel.lock').open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another control panel is already using this state directory') from None
        panel=Panel(root,state)
        try:
            server=make_server(panel,port)
        except Exception:
            panel.executor.shutdown(wait=False);raise
        print('Shine control panel v'+__version__+' — private local URL:',flush=True)
        print('http://127.0.0.1:'+str(server.server_port)+'/?key='+panel.key,flush=True)
        print('Open this URL on your Mac. No sending controls. Ctrl+C stops the panel.',flush=True)
        try:server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:print('Panel stopping; waiting for active research to finish.',flush=True)
        finally:
            panel.stopping.set();server.server_close();panel.executor.shutdown(wait=True)
