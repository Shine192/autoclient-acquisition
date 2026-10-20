"""Offline integration tests: no provider requests, credit purchases or emails."""
import copy
import fcntl
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import test_targeting
from acquisition_agent import automatic as auto
from acquisition_agent.core import Store, prepare_lead
from acquisition_agent.automatic_setup import save_keys
from acquisition_agent.targeting import create_session

ROOT=Path(__file__).resolve().parent.parent

class AutomaticTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_targeting.TargetSessionTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store=self.fixture.store;self.session=self.fixture.session
        self.profile=self.fixture.profile;self.prefs=self.fixture.prefs;self.exclusions=self.fixture.exclusions
        self.raw=copy.deepcopy(self.fixture.raw)
        self.raw['identity_evidence']={'url':self.raw['url'],'quote':'Paper Cocoa sells chocolate gifts online'}
        self.env=patch.dict(os.environ,{'OPENAI_API_KEY':'test-fixture','FIRECRAWL_API_KEY':'test-fixture'},clear=True)
        self.env.start();self.addCleanup(self.env.stop)

    def response(self,raw=None):
        return {'status':'completed','usage':{'input_tokens':1234,'output_tokens':800},'output':[{'content':[{'type':'output_text','text':json.dumps({'leads':[raw or self.raw]})}]}]}

    def pipeline(self,**kwargs):
        with patch.object(auto,'search',return_value=[{'url':self.raw['url']}]) as search, patch.object(auto,'research',return_value=self.fixture.text) as research, patch.object(auto,'api_json',return_value=self.response()) as api:
            result=auto.run(self.store,self.session,self.prefs,self.profile,self.exclusions,**kwargs)
        return result,search,research,api

    def test_full_pipeline_saves_valid_draft_without_approval_or_queue(self):
        result,search,research,api=self.pipeline()
        self.assertEqual(result['new'],1);self.assertEqual(result['drafts'],1)
        lead=self.store.leads()[0]
        self.assertEqual(lead['email'],'hello@paper.example')
        self.assertIn(self.profile['portfolio_url'],lead['draft']['body'])
        self.assertEqual(lead['status'],'Draft');self.assertFalse(lead.get('approved'))
        self.assertEqual(result['usage']['input_tokens'],1234)
        self.assertEqual(result['usage']['search_credits_reserved'],2)
        self.assertGreater(result['usage']['reserved_usd'],result['usage']['reported_usd_estimate'])
        self.assertEqual(api.call_args.kwargs['payload']['model'],auto.MODEL)
        self.assertNotIn('tools',api.call_args.kwargs['payload'])
        self.assertFalse(self.store.db.execute("SELECT 1 FROM sqlite_master WHERE name='outbox'").fetchone())

    def test_same_session_cannot_restart_or_pay_again(self):
        self.pipeline()
        with patch.object(auto,'search') as search, self.assertRaisesRegex(ValueError,'already started'):
            auto.run(self.store,self.session,self.prefs,self.profile,self.exclusions)
        search.assert_not_called()

    def test_fresh_session_skips_existing_company_and_uses_search_cache(self):
        self.pipeline()
        other=create_session(self.store,self.fixture.spec,self.prefs,self.profile,self.exclusions)
        with patch.object(auto,'search') as search,patch.object(auto,'generate') as generate:
            result=auto.run(self.store,other,self.prefs,self.profile,self.exclusions)
        self.assertEqual(result['duplicates'],1);generate.assert_not_called();search.assert_not_called()

    def test_missing_keys_and_more_than_ten_candidates_fail_before_network(self):
        with patch.dict(os.environ,{},clear=True), patch.object(auto,'search') as search, self.assertRaisesRegex(ValueError,'OPENAI_API_KEY'):
            auto.run(self.store,self.session,self.prefs,self.profile,self.exclusions)
        search.assert_not_called()
        self.session['spec']['limit']=11
        with self.assertRaisesRegex(ValueError,'up to 10'):auto.run(self.store,self.session,self.prefs,self.profile,self.exclusions)

    def test_timeout_keeps_reservation_and_stops_without_retry(self):
        with patch.object(auto,'api_json',side_effect=TimeoutError):
            with self.assertRaises(auto.Stopped):auto.generate(self.store,self.session['id'],'Return JSON only')
        self.assertGreater(auto.usage(self.store)['reserved_usd'],0)
        self.assertEqual(self.store.db.execute('SELECT status FROM automatic_usage').fetchone()[0],'reserved')

    def test_unknown_usage_sets_persistent_billing_hold(self):
        with patch.object(auto,'api_json',return_value={'status':'completed'}), self.assertRaises(auto.Stopped):
            auto.generate(self.store,self.session['id'],'JSON')
        with self.assertRaisesRegex(auto.Stopped,'held'):auto.reserve(self.store,'other','openai',.01)

    def test_incomplete_or_invalid_json_never_creates_a_draft(self):
        for response in ({'status':'incomplete','usage':{'input_tokens':10,'output_tokens':20}}, {'status':'completed','usage':{'input_tokens':10,'output_tokens':20},'output':[]}):
            with patch.object(auto,'api_json',return_value=response),self.assertRaises(ValueError):
                auto.generate(self.store,self.session['id'],'JSON')
        self.assertEqual(self.store.leads(),[])

    def test_app_allowance_is_reserved_atomically_and_not_refunded(self):
        auto.reserve(self.store,'a','openai',.49)
        with self.assertRaises(auto.Stopped):auto.reserve(self.store,'a','openai',.02)
        auto.reserve(self.store,'b','openai',.49)
        auto.reserve(self.store,'c','openai',.49)
        auto.reserve(self.store,'d','openai',.49)
        with self.assertRaises(auto.Stopped):auto.reserve(self.store,'e','openai',.05)
        self.assertAlmostEqual(auto.usage(self.store)['reserved_usd'],1.96)

    def test_search_credit_cap_precedes_request(self):
        auto.reserve(self.store,'a','firecrawl_search',credits=50)
        with patch.object(auto,'search') as search:
            result=auto.run(self.store,self.session,self.prefs,self.profile,self.exclusions)
        search.assert_not_called();self.assertEqual(result['stage'],'Stopped')

    def test_exclusions_block_fetch_and_ai(self):
        with patch.object(auto,'search',return_value=[{'url':'https://growth-horizon.nl/'}]),patch.object(auto,'research') as research:
            result=auto.run(self.store,self.session,self.prefs,self.profile,self.exclusions)
        research.assert_not_called();self.assertEqual(result['new'],0)

    def test_runtime_domain_suppression_blocks_fetch(self):
        from acquisition_agent.delivery import suppress
        suppress(self.store,'paper.example','Opted out')
        result,_,research,api=self.pipeline()
        research.assert_not_called();api.assert_not_called();self.assertEqual(result['new'],0)

    def test_pause_stops_new_calls(self):
        self.store.pause(True)
        result,search,research,api=self.pipeline()
        search.assert_not_called();research.assert_not_called();api.assert_not_called()
        self.assertTrue(result['paused'])

    def test_robots_or_fetch_failure_never_falls_back_to_paid_scraping(self):
        with patch.object(auto,'search',return_value=[{'url':self.raw['url']}]),patch.object(auto,'research',side_effect=ValueError('Source disallows this research fetch')),patch.object(auto,'generate') as gen:
            result=auto.run(self.store,self.session,self.prefs,self.profile,self.exclusions)
        gen.assert_not_called();self.assertEqual(result['new'],0)

    def test_ai_fabricated_source_text_cannot_validate_evidence(self):
        raw=copy.deepcopy(self.raw);raw['source_text']='Imaginary audit reveals lost sales'
        raw['source_documents']=[{'url':raw['url'],'text':raw['source_text']}]
        raw['draft']['evidence'][0]['quote']=raw['source_text']
        with patch.object(auto,'search',return_value=[{'url':raw['url']}]),patch.object(auto,'research',return_value=self.fixture.text),patch.object(auto,'api_json',return_value=self.response(raw)):
            result=auto.run(self.store,self.session,self.prefs,self.profile,self.exclusions)
        self.assertEqual(result['drafts_rejected'],1)
        self.assertNotIn('draft',self.store.leads()[0]);self.assertEqual(self.store.leads()[0]['status'],'Needs Review')

    def test_ai_email_and_approval_fields_are_ignored(self):
        raw=dict(self.raw,email='invented@paper.example',selected_email='invented@paper.example',approved=True,status='Ready')
        docs=[{'url':raw['url'],'text':self.fixture.text}]
        trusted=auto.trusted_candidate(raw,docs,raw['url'],self.session['spec'])
        for key in ('email','selected_email','approved','status'):self.assertNotIn(key,trusted)
        self.assertEqual(prepare_lead(trusted)['email'],'hello@paper.example')

    def test_mismatched_official_host_is_rejected(self):
        raw=dict(self.raw,website='https://other.example/')
        with self.assertRaisesRegex(ValueError,'host'):
            auto.trusted_candidate(raw,[{'url':self.raw['url'],'text':self.fixture.text}],self.raw['url'],self.session['spec'])

    def test_notion_failure_keeps_research_and_draft_locally(self):
        with patch.dict(os.environ,{'NOTION_TOKEN':'test'}),patch('acquisition_agent.delivery.setup_schema'),patch('acquisition_agent.providers.Notion.save_lead',side_effect=ValueError('offline')):
            result,_,_,_=self.pipeline()
        self.assertEqual(result['new'],1);self.assertEqual(result['drafts'],1)
        self.assertTrue(result['notion_sync']['errors']);self.assertTrue(self.store.leads()[0]['draft_dirty'])

    def test_prompt_bound_prevents_billable_request(self):
        with patch.object(auto,'api_json') as api,self.assertRaisesRegex(ValueError,'input limit'):
            auto.generate(self.store,self.session['id'],'x'*(auto.PROMPT_BYTES+1))
        api.assert_not_called();self.assertEqual(auto.usage(self.store)['reserved_usd'],0)

    def test_stale_cache_is_not_used(self):
        auto.init(self.store);auto.cache_put(self.store,'key',{'value':1})
        self.assertEqual(auto.cache_get(self.store,'key',24),{'value':1})
        self.store.db.execute("UPDATE research_cache SET fetched_at='2020-01-01T00:00:00+00:00'");self.store.db.commit()
        self.assertIsNone(auto.cache_get(self.store,'key',24))

    def test_atomic_reservations_across_connections(self):
        auto.init(self.store);errors=[];success=[]
        def call():
            store=Store(self.store.root)
            try:auto.reserve(store,'same','openai',.3);success.append(True)
            except auto.Stopped:errors.append(True)
            finally:store.db.close()
        threads=[threading.Thread(target=call) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(len(success),1);self.assertEqual(len(errors),1)

    def test_private_setup_preserves_existing_credentials_and_model(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'.env';path.write_text('NOTION_TOKEN=old-secret\nAI_MODEL=keep-model\nOPENAI_API_KEY=old\n')
            save_keys(root,{'OPENAI_API_KEY':'new-test','FIRECRAWL_API_KEY':'search-test'})
            self.assertIn('NOTION_TOKEN=old-secret',path.read_text());self.assertIn('AI_MODEL=keep-model',path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with self.assertRaises(ValueError):save_keys(root,{'OPENAI_API_KEY':'bad\nvalue'})

class WorkerCoordinationTests(unittest.TestCase):
    def test_scheduled_worker_releases_research_lock_while_idle(self):
        from acquisition_agent.runner import run
        from acquisition_agent.core import read_json
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            prefs,profile,exclusions=[read_json(ROOT/'config'/name) for name in ('preferences.json','profile.json','exclusions.json')]
            checked=[]
            def idle(seconds):
                with (store.root/'worker.lock').open('a') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    checked.append(True)
                with (store.root/'agent.lock').open('a') as lock:
                    with self.assertRaises(BlockingIOError):fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                raise KeyboardInterrupt
            with patch('acquisition_agent.__main__.settings',return_value=(prefs,profile,exclusions)),patch('acquisition_agent.__main__.run_discovery',return_value={'new':0}),patch('acquisition_agent.runner.time.sleep',side_effect=idle),patch.dict(os.environ,{},clear=True),self.assertRaises(KeyboardInterrupt):
                run(store,ROOT)
            self.assertTrue(checked);store.db.close()

    def test_research_lock_blocks_scheduled_worker_mutations(self):
        from acquisition_agent.runner import run
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with (store.root/'worker.lock').open('a') as lock,patch('acquisition_agent.__main__.run_discovery') as discover,patch('acquisition_agent.__main__.sending_command') as send:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                run(store,ROOT,once=True)
            discover.assert_not_called();send.assert_not_called();store.db.close()
