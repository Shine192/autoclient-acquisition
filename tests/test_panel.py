"""Loopback HTTP integration tests, no external requests or messages."""
import copy
import http.client
import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from acquisition_agent.panel import Panel, make_server, open_store
from acquisition_agent.core import read_json
from acquisition_agent.__main__ import starter

ROOT=Path(__file__).resolve().parent.parent

class PanelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);shutil.copytree(ROOT/'config',self.root/'config')
        self.state=self.root/'state';self.panel=Panel(self.root,self.state)
        self.server=make_server(self.panel,0)
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.cookie='shine_panel='+self.panel.key
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.panel.stopping.set();self.server.shutdown();self.server.server_close();self.panel.executor.shutdown(wait=True);self.thread.join()

    def request(self,path,body=None,headers=None,authorized=True):
        h={'Cookie':self.cookie} if authorized else {}
        if body is not None:h.update({'Content-Type':'application/json','Origin':self.origin,'X-CSRF-Token':self.panel.csrf})
        h.update(headers or {})
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,h)
        r=c.getresponse();raw=r.read().decode();result=(r.status,dict(r.getheaders()),raw);c.close();return result

    def seed(self):
        store=open_store(self.state)
        prefs,profile,exclusions,_=self.panel.settings()
        starter(store,prefs,profile,exclusions);store.db.close()

    def test_audience_form_can_set_campaign_total_without_another_screen(self):
        payload={'country':'United Arab Emirates','city':'Dubai','company_type':'Brand',
                 'kind':'Cold Outreach','industries':['chocolate_snacks_nuts'],'limit':5,'campaign_target':20}
        code,_,raw=self.request('/api/target-session',payload)
        self.assertEqual(code,200,raw)
        state=json.loads(self.request('/api/state')[2])
        self.assertEqual(state['campaign']['target'],20)
        payload['campaign_target']=None
        self.assertEqual(self.request('/api/target-session',payload)[0],200)
        self.assertEqual(json.loads(self.request('/api/state')[2])['campaign']['target'],20)

    def test_anonymous_state_is_not_readable(self):
        self.assertEqual(self.request('/api/state',authorized=False)[0],401)

    def test_bootstrap_sets_private_cookie_redirects_without_key(self):
        code,headers,_=self.request('/?key='+self.panel.key,authorized=False)
        self.assertEqual(code,303);self.assertEqual(headers['Location'],'/')
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertEqual(headers['Referrer-Policy'],'no-referrer')

    def test_wrong_bootstrap_key_never_authenticates(self):
        self.assertEqual(self.request('/?key=wrong',authorized=False)[0],401)

    def test_host_rebinding_is_rejected(self):
        self.assertEqual(self.request('/api/state',headers={'Host':'attacker.example'})[0],403)

    def test_cross_origin_action_rejected(self):
        self.assertEqual(self.request('/api/pause',{'paused':True},{'Origin':'https://attacker.example'})[0],403)

    def test_missing_or_bad_csrf_rejected(self):
        self.assertEqual(self.request('/api/pause',{'paused':True},{'X-CSRF-Token':'wrong'})[0],403)

    def test_anonymous_post_rejected(self):
        self.assertEqual(self.request('/api/pause',{'paused':True},authorized=False)[0],403)

    def test_pause_persists_and_resume_works(self):
        self.assertEqual(self.request('/api/pause',{'paused':True})[0],200)
        self.assertTrue(self.panel.snapshot()['paused'])
        self.request('/api/pause',{'paused':False});self.assertFalse(self.panel.snapshot()['paused'])

    def test_no_send_or_auto_enable_endpoint(self):
        self.assertEqual(self.request('/api/send',{'send':True})[0],404)
        self.assertEqual(self.request('/api/task',{'kind':'send'})[0],400)
        self.assertEqual(self.request('/api/preferences',{'mode':'automatic'})[0],400)
        self.assertEqual(self.panel.settings()[3]['mode'],'draft-only')

    def test_campaign_http_presets_custom_and_close_keep_draft_only_mode(self):
        for target in (20,30,50,73):
            action='start' if target==20 else 'update'
            code,_,body=self.request('/api/campaign',{'action':action,'target':target})
            self.assertEqual(code,200);self.assertEqual(json.loads(body)['campaign']['target'],target)
        snapshot=self.panel.snapshot();self.assertEqual(snapshot['sending']['mode'],'draft-only')
        self.assertEqual(snapshot['campaign']['remaining'],73)
        self.assertEqual(snapshot['sending']['send_hours'],[8,11]);self.assertEqual(snapshot['sending']['daily_limit'],50)
        self.assertEqual(self.request('/api/campaign',{'action':'update','target':True})[0],400)
        self.assertEqual(self.request('/api/campaign',{'action':'close'})[0],200)
        self.assertIsNone(self.panel.snapshot()['campaign'])

    def test_automatic_research_http_runs_to_completion_without_send(self):
        from unittest.mock import patch
        import test_targeting
        fixture=test_targeting.TargetSessionTests();fixture.setUp()
        raw=copy.deepcopy(fixture.raw)
        raw['identity_evidence']={'url':raw['url'],'quote':'Paper Cocoa sells chocolate gifts online'}
        response={'status':'completed','usage':{'input_tokens':1000,'output_tokens':800},'output':[{'content':[{'type':'output_text','text':json.dumps({'leads':[raw]})}]}]}
        try:
            code,_,body=self.request('/api/target-session',fixture.spec)
            session=json.loads(body);self.assertEqual(code,200)
            with patch.dict('os.environ',{'OPENAI_API_KEY':'fixture','FIRECRAWL_API_KEY':'fixture','NOTION_TOKEN':''},clear=True),patch('acquisition_agent.automatic.search',return_value=[{'url':raw['url']}]),patch('acquisition_agent.automatic.research',return_value=fixture.text),patch('acquisition_agent.automatic.api_json',return_value=response),patch('acquisition_agent.__main__.sending_command') as send:
                code,_,_=self.request('/api/task',{'kind':'automatic-research','session_id':session['id']})
                self.assertEqual(code,202)
                for _ in range(100):
                    state=self.panel.snapshot()
                    if not state['busy']:break
                    time.sleep(.01)
                self.assertFalse(state['busy'])
                self.assertEqual(state['tasks'][0]['status'],'Completed')
                self.assertEqual(state['tasks'][0]['result']['drafts'],1)
                self.assertEqual(state['leads'][0]['session_id'],session['id'])
                self.assertEqual(state['tasks'][0]['result']['session_id'],session['id'])
                self.assertTrue(state['setup']['openai_key_present'])
                self.assertEqual(state['automatic']['input_tokens'],1000)
                send.assert_not_called()
        finally:fixture.doCleanups()

    def test_target_session_http_and_batch_import_preserve_review_gates(self):
        from unittest.mock import patch
        from test_targeting import TargetSessionTests
        fixture=TargetSessionTests();fixture.setUp()
        try:
            payload=fixture.spec
            code,_,body=self.request('/api/target-session',payload)
            self.assertEqual(code,200);session=json.loads(body)
            self.assertIn('New York',session['prompt'])
            with patch.dict('os.environ',{'NOTION_TOKEN':''}):
                code,_,body=self.request('/api/task',{'kind':'target-import','session_id':session['id'],'leads':[fixture.raw]})
                self.assertEqual(code,202)
                for _ in range(50):
                    if not self.panel.busy.locked():break
                    time.sleep(.02)
            snapshot=self.panel.snapshot()
            self.assertEqual(snapshot['tasks'][0]['status'],'Completed')
            self.assertEqual(snapshot['leads'][0]['status'],'Draft')
            self.assertEqual(snapshot['outbox'],[])
            self.assertEqual(snapshot['sending']['mode'],'draft-only')
            self.assertEqual(snapshot['target_sessions'][0]['result']['drafts'],1)
            self.assertEqual(self.request('/api/target-session',dict(payload,country='Not approved'))[0],400)
        finally:fixture.doCleanups()

    def test_snapshot_never_includes_credential_values(self):
        credential=self.state/'credentials';credential.mkdir()
        (credential/'gmail-token.json').write_text('{"refresh_token":"DONT_EXPOSE_THIS"}')
        text=self.request('/api/state')[2]
        self.assertNotIn('DONT_EXPOSE_THIS',text);self.assertNotIn('refresh_token',text)
        self.assertTrue(json.loads(text)['setup']['gmail_token_present'])

    def test_only_exact_asset_routes_are_served(self):
        self.assertEqual(self.request('/style.css')[0],200)
        self.assertEqual(self.request('/app.js')[0],200)
        self.assertEqual(self.request('/')[0],200)
        self.assertEqual(self.request('/../state/credentials/gmail-token.json')[0],404)
        self.assertEqual(self.request('/.env')[0],404)

    def test_security_headers_prevent_inline_scripts_and_framing(self):
        _,h,_=self.request('/')
        self.assertIn("frame-ancestors 'none'",h['Content-Security-Policy'])
        self.assertIn("script-src 'self'",h['Content-Security-Policy'])
        self.assertEqual(h['X-Content-Type-Options'],'nosniff')

    def test_starter_task_uses_existing_ingest_and_drafts(self):
        code,_,body=self.request('/api/task',{'kind':'starter'})
        self.assertEqual(code,202)
        deadline=time.monotonic()+3
        while self.panel.busy.locked() and time.monotonic()<deadline:time.sleep(.01)
        state=self.panel.snapshot();self.assertEqual(len(state['leads']),3)
        self.assertTrue(all(l['has_draft'] for l in state['leads']))
        self.assertEqual(state['tasks'][0]['status'],'Completed')
        self.assertEqual(state['outbox'],[])

    def test_review_details_include_real_evidence_and_prompt(self):
        self.seed();lead=self.panel.snapshot()['leads'][0]
        code,_,raw=self.request('/api/lead?id='+lead['id'])
        self.assertEqual(code,200);detail=json.loads(raw)
        self.assertIn('UNTRUSTED DATA',detail['prompt'])
        self.assertTrue(detail['source_documents']);self.assertTrue(detail['draft']['evidence'])
        self.assertEqual(detail['offer']['offer'],'paid_test')

    def test_edited_draft_marks_dirty_and_preserves_evidence(self):
        self.seed();item=self.panel.snapshot()['leads'][0]
        detail=self.panel.detail(item['id']);draft={'lead_id':item['id'],**detail['draft']}
        draft['subject']='Reviewed design introduction'
        self.assertEqual(self.request('/api/draft',draft)[0],200)
        store=open_store(self.state);saved=store.get(item['id']);store.db.close()
        self.assertTrue(saved['draft_dirty']);self.assertEqual(saved['draft']['subject'],draft['subject'])
        self.assertNotIn('starter_seed',saved)

    def test_missing_portfolio_is_rejected_on_draft_save(self):
        self.seed();item=self.panel.snapshot()['leads'][0];detail=self.panel.detail(item['id'])
        draft={'lead_id':item['id'],**detail['draft']};draft['body']='Hello company. This is a long application message without the required portfolio URL. '*3
        self.assertEqual(self.request('/api/draft',draft)[0],400)

    def test_contacted_record_cannot_be_edited(self):
        self.seed();item=self.panel.snapshot()['leads'][0];detail=self.panel.detail(item['id'])
        store=open_store(self.state);lead=store.get(item['id']);lead['status']='Sent';store.save(lead);store.db.close()
        self.assertEqual(self.request('/api/draft',{'lead_id':item['id'],**detail['draft']})[0],400)

    def test_preferences_do_not_change_sender_or_offers(self):
        original=self.panel.settings()[3]
        self.assertEqual(self.request('/api/preferences',{'weekly_capacity_hours':15,'title_keywords':['Klaviyo designer']})[0],200)
        self.assertEqual(self.panel.settings()[0]['weekly_capacity_hours'],15)
        self.assertEqual(self.panel.settings()[3],original)

    def test_invalid_preferences_rejected(self):
        for value in [0,99,True,'20']:
            self.assertEqual(self.request('/api/preferences',{'weekly_capacity_hours':value})[0],400)
        self.assertEqual(self.request('/api/preferences',{'countries':[]})[0],400)
        self.assertEqual(self.request('/api/preferences',{'design_rate_usd':[1,5]})[0],400)

    def test_unknown_opportunity_returns_useful_error(self):
        self.assertEqual(self.request('/api/lead?id=not-a-lead')[0],400)
