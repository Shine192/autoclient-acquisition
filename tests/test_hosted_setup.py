import copy,json,shutil,sqlite3,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch,Mock
from acquisition_agent.core import Store
from acquisition_agent.notion_compat import SOURCE
from acquisition_agent.providers import rich,research_notes
from hosted_sender.bootstrap import seed
from hosted_sender.cli import activate,campaign,close,run,self_test,verify_test
from hosted_sender.worker import settings_hash
from hosted_sender.notion_import import read_lead,refresh
from hosted_sender.queue import Queue
from test_hosted_queue import Memory
import test_review

ROOT=Path(__file__).resolve().parent.parent
class SetupTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  shutil.copytree(ROOT/'config',self.root/'config');p=json.loads((self.root/'config/preferences.json').read_text());p['notion_leads_source_id']=SOURCE;(self.root/'config/preferences.json').write_text(json.dumps(p))
  self.store=Store(self.root/'state');self.addCleanup(self.store.db.close)
  self.store.add({'id':'a'*16,'notion_page_id':'old-page','draft':{'body':'Keep this draft'}})
  self.store.db.executescript("CREATE TABLE outbox(id TEXT,lead_id TEXT,mode TEXT,state TEXT,recipient TEXT,company TEXT,attempted_at TEXT);INSERT INTO outbox VALUES('old','aaaaaaaaaaaaaaaa','automatic','sent','hello@example.com','example.com','2026-10-20T05:35:17+00:00');")
  self.store.db.commit()
 def test_seed_preserves_history_daily_count_and_links_without_credentials(self):
  before=(self.root/'state/agent.sqlite3').read_bytes()
  result=seed(self.root,{'records':[{'lead_id':'a'*16,'old_page_id':'old-page','new_page_id':'new-page'}]})
  self.assertEqual((self.root/'state/agent.sqlite3').read_bytes(),before)
  self.assertEqual(result['lead_'+'a'*16]['data']['notion_page_id'],'new-page')
  self.assertEqual(result['control']['days']['2026-10-20'],1)
  self.assertTrue(result['control']['paused']);self.assertFalse(result['control']['migration_complete'])
  self.assertEqual(result['settings']['data']['sending']['follow_up_days'],[])
  self.assertEqual(len([k for k in result if k.startswith('recipient_')]),1)
  self.assertNotIn('refresh_token',json.dumps(result))
 def test_uncertain_local_delivery_blocks_seed(self):
  self.store.db.execute("UPDATE outbox SET state='uncertain'");self.store.db.commit()
  with self.assertRaisesRegex(ValueError,'uncertain'):seed(self.root)
 def test_activate_requires_handover_and_verified_reply_and_exact_policy(self):
  state=seed(self.root);db=Memory();db.records=state;q=Queue(db);s=state['settings']['data'];h=settings_hash(s)
  with self.assertRaises(ValueError):activate(q,s,h)
  db.records['control'].update(mac_sender_disabled=True,test_verified=True,test_hash=h)
  with self.assertRaises(ValueError):activate(q,s,'wrong')
  self.assertTrue(activate(q,s,h)['activated']);self.assertFalse(q.control()['paused'])
 def test_campaign_dates_and_limits_and_close_preserve_history(self):
  state=seed(self.root);db=Memory();db.records=state;q=Queue(db);s=state['settings']['data']
  with self.assertRaises(ValueError):campaign(q,s,101,['2026-10-20'])
  with self.assertRaises(ValueError):campaign(q,s,20,['2026-10-24'])
  result=campaign(q,s,20,['2026-10-20','2026-10-21'])
  self.assertEqual(result['maximum_attempts'],20)
  with self.assertRaises(ValueError):campaign(q,s,30,['2026-10-22'])
  self.assertTrue(close(q)['history_preserved']);self.assertIn('legacy_old',db.records)
 def test_delivery_switch_off_never_calls_gmail_or_notion(self):
  state=seed(self.root);db=Memory();db.records=state;q=Queue(db);s=state['settings']['data'];gmail=Mock();notion=Mock()
  with patch.dict('os.environ',{'SHINE_DELIVERY_ENABLED':'false'}):self.assertEqual(run(q,s,gmail,notion)['state'],'delivery switch off')
  gmail.identity.assert_not_called();notion.query.assert_not_called()
 def test_hosted_self_test_only_to_owner_and_requires_actual_reply(self):
  db=Memory();db.records=seed(self.root);q=Queue(db);s=db.get('settings')['data'];g=Mock()
  g.identity.return_value=s['sending']['sender'];g.send.return_value={'id':'sent','threadId':'thread'}
  result=self_test(q,s,g);key=result['test_id'];item=db.get('outbox_'+key)
  self.assertEqual(g.send.call_args.args[1],s['sending']['sender'])
  g.thread.return_value=[]
  with self.assertRaises(ValueError):verify_test(q,s,g,key)
  g.thread.return_value=[{'id':'reply','internalDate':str(int((item['attempted_at']+1)*1000)),'labelIds':['INBOX'],'snippet':item['test_nonce'],'payload':{'headers':[{'name':'From','value':s['sending']['sender']}]}}]
  self.assertTrue(verify_test(q,s,g,key)['reply_verified']);self.assertEqual(q.control()['test_hash'],settings_hash(s))
 def test_readonly_github_login_stops_before_touching_mac(self):
  from hosted_sender.prepare import prepare
  before=(self.root/'config/sending.json').read_bytes()
  with patch('hosted_sender.prepare.gh',return_value=json.dumps({'permissions':{'push':False}})):
   with self.assertRaisesRegex(ValueError,'no write access'):prepare(self.root)
  self.assertEqual((self.root/'config/sending.json').read_bytes(),before)

class NotionImportTests(unittest.TestCase):
 def setUp(self):
  self.fixture=test_review.SingleReviewTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
  f=self.fixture;self.prefs=copy.deepcopy(f.prefs)
  if 'United Arab Emirates' not in self.prefs['countries']:self.prefs['countries'].append('United Arab Emirates')
  self.lead=f.lead
  notes=json.loads(research_notes(self.lead));notes['approved']=True;notes['status']='Approve'
  self.page={'id':'new-page','properties':{'Name':{'title':rich('Paper Cocoa')},'Deduplication Key':{'type':'rich_text','rich_text':rich(self.lead['id'])},'Research Notes':{'type':'rich_text','rich_text':rich(json.dumps(notes))},'COUNTRY':{'type':'rich_text','rich_text':rich('UAE')},'Role':{'type':'rich_text','rich_text':rich(self.lead['title'])},'Job URL':{'url':self.lead['url']},'Opportunity Type':{'select':{'name':'Cold Outreach'}},'Type':{'select':{'name':'Brand'}},'STATUS':{'status':{'name':'Draft'}},'email SUBJECT':{'type':'rich_text','rich_text':rich(self.lead['draft']['subject'])},'email body':{'type':'rich_text','rich_text':rich(self.lead['draft']['body'])}}}
 def test_only_actual_status_property_controls_approval(self):
  lead=read_lead(self.page,self.prefs);self.assertEqual(lead['status'],'Draft');self.assertNotIn('approved',lead);self.assertEqual(lead['country'],'United Arab Emirates')
 def test_incomplete_structured_research_is_not_fabricated(self):
  self.page['properties']['Research Notes']['rich_text']=rich('{truncated')
  with self.assertRaises(ValueError):read_lead(self.page,self.prefs)
 def test_duplicate_notion_ids_stop_before_queue_or_send(self):
  n=Mock();n.query.return_value=[self.page,copy.deepcopy(self.page)];q=Queue(Memory());q.init()
  with self.assertRaisesRegex(ValueError,'Duplicate'):refresh(q,n,{'preferences':self.prefs})
  self.assertEqual(q.db.list('outbox'),[])
 def test_source_text_cannot_approve_or_import_draft_rows(self):
  n=Mock();n.query.return_value=[self.page];q=Queue(Memory());q.init()
  self.assertEqual(refresh(q,n,{'preferences':self.prefs})['imported'],0)

class WorkflowTests(unittest.TestCase):
 def test_workflow_has_no_push_sends_and_has_serialization_and_no_artifact_state(self):
  import yaml
  w=yaml.load((ROOT/'.github/workflows/outreach.yml').read_text(),Loader=yaml.BaseLoader)
  self.assertNotIn('push',w['on']);self.assertEqual(w['concurrency']['cancel-in-progress'],'false')
  self.assertEqual(w['jobs']['outreach']['runs-on'],'ubuntu-latest')
  self.assertNotIn('upload-artifact',(ROOT/'.github/workflows/outreach.yml').read_text())
  for step in w['jobs']['outreach']['steps']:
   if 'uses' in step:self.assertRegex(step['uses'],r'@[0-9a-f]{40}$')
