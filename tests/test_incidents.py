import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from acquisition_agent import incidents,error_center
from acquisition_agent.core import Store
from acquisition_agent.providers import rich
from test_hosted_queue import Memory


class IncidentTests(unittest.TestCase):
 def event(self, errors=None,**kwargs):
  return incidents.observe([],'cloud','approval','lead',errors or ['Recipient does not match published evidence'],at=100,observation='run1',**kwargs)

 def test_contact_and_fit_have_different_recovery_guides(self):
  events=self.event(['Recipient does not match published evidence','Sourced fit 60/100; approved minimum 75'])
  self.assertEqual({x['code'] for x in events},{'contact','fit'})
  fit=next(x for x in events if x['code']=='fit');self.assertEqual(fit['technical'],{'fit_score':60,'minimum_fit':75})
  self.assertIn('recalculate',incidents.public_event(fit)['easiest_fix'])

 def test_specific_contact_explanation_survives_repeated_generic_blockers(self):
  event=self.event(['Selected inbox is for media enquiries.','Add an official source containing the selected shared business email address.','Recipient does not match published evidence'])[0]
  self.assertEqual(event['code'],'contact');self.assertEqual(event['technical']['contact_issue'],'press')
  self.assertIn('press or media',incidents.public_event(event)['what'])
  event=self.event(['Selected info@ address is not supported by the saved official evidence'])[0]
  self.assertEqual(event['code'],'contact')

 def test_local_logging_failure_does_not_change_the_original_task_outcome(self):
  import sqlite3
  with tempfile.TemporaryDirectory() as folder:
   store=Store(folder)
   with patch('acquisition_agent.incidents.mutate',side_effect=sqlite3.OperationalError('Disk unavailable')):
    self.assertFalse(incidents.record(store,'research','session',['HTTP 429']))
    self.assertFalse(incidents.LOCAL_LOGGING_AVAILABLE)
   self.assertTrue(incidents.record(store,'research','session',[]));store.db.close()

 def test_website_access_failure_is_not_an_api_key_failure(self):
  self.assertEqual(incidents.classify(ValueError('Research HTTP 403'),'research')[0],'source')
  self.assertEqual(incidents.classify(ValueError('API request failed with HTTP 403'),'notion_sync')[0],'auth')

 def test_unknown_provider_text_never_enters_the_journal_or_export(self):
  event=self.event([ValueError('PRIVATE_API_KEY sk-secret user@private.example RAW_EMAIL_BODY')])[0]
  raw=json.dumps([event,incidents.public_event(event)])
  for secret in ('PRIVATE_API_KEY','sk-secret','user@private.example','RAW_EMAIL_BODY'):self.assertNotIn(secret,raw)
  self.assertEqual(event['technical'],{'exception_type':'ValueError'})

 def test_safe_bug_location_has_no_local_variables_or_raw_message(self):
  namespace={'__name__':'acquisition_agent.fixture'}
  exec('def fail():\n secret="PRIVATE_TOKEN"\n raise ValueError(secret)',namespace)
  try:namespace['fail']()
  except ValueError as exc:event=self.event([exc])[0]
  self.assertEqual(event['technical']['locations'],[{'module':'acquisition_agent.fixture','function':'fail','line':3}])
  self.assertNotIn('PRIVATE_TOKEN',json.dumps(event));self.assertNotIn('secret',json.dumps(event))

 def test_known_message_does_not_capture_injected_private_suffix(self):
  event=self.event(['Recipient does not match published evidence PRIVATE_TOKEN private@example.com'])[0]
  self.assertNotIn('PRIVATE_TOKEN',json.dumps(event));self.assertNotIn('private@example.com',json.dumps(event))

 def test_dispatch_timeout_is_never_a_blind_retry(self):
  event=incidents.observe([],'cloud','sending','worker',[TimeoutError('timeout SECRET')],at=100)[0]
  detail=incidents.public_event(event)
  self.assertEqual(detail['severity'],'urgent');self.assertIn('reconcile',detail['easiest_fix'])
  self.assertIn('Do not blindly retry',detail['verify'])

 def test_polling_the_same_observation_does_not_inflate_counts(self):
  first=self.event();same=incidents.observe(first,'cloud','approval','lead',['Recipient does not match published evidence'],observation='run1',at=110)
  self.assertEqual(same[0]['occurrences'],1);self.assertEqual(same[0]['last_seen'],100)
  again=incidents.observe(same,'cloud','approval','lead',['Recipient does not match published evidence'],observation='run2',at=120)
  self.assertEqual(again[0]['occurrences'],2);self.assertEqual(again[0]['first_seen'],100)

 def test_success_resolves_only_the_scope_actually_checked(self):
  events=self.event();events=incidents.observe(events,'cloud','approval','other',['Personalization needs source evidence'],at=101)
  events=incidents.observe(events,'cloud','approval','lead',[],at=120)
  self.assertEqual(next(x for x in events if x['scope']=='lead')['status'],'resolved')
  self.assertEqual(next(x for x in events if x['scope']=='other')['status'],'open')
  reopened=incidents.observe(events,'cloud','approval','lead',['Recipient does not match published evidence'],observation='new',at=150)
  self.assertEqual(next(x for x in reopened if x['scope']=='lead')['first_seen'],100)

 def test_retention_keeps_open_incidents_ahead_of_old_resolved_entries(self):
  events=self.event()
  for i in range(220):
   events=incidents.observe(events,'local','research','session'+str(i),['HTTP 429'],at=200+i)
   events=incidents.observe(events,'local','research','session'+str(i),[],at=200+i)
  self.assertEqual(len(events),incidents.LIMIT)
  self.assertTrue(any(x['scope']=='lead' and x['status']=='open' for x in events))

 def test_only_validated_run_and_record_links_are_generated(self):
  e=self.event(run_id='12345',page_id='a'*32)[0]
  self.assertTrue(incidents.public_event(e)['run_url'].endswith('/12345'))
  e['run_id']='javascript:alert(1)';e['page_id']=None
  self.assertNotIn('run_url',incidents.public_event(e));self.assertNotIn('record_url',incidents.public_event(e))

 def test_cloud_history_does_not_change_controls_sends_or_receipts(self):
  db=Memory();db.records={'control':{'paused':False,'active_attempt':'existing'},'outbox_x':{'kind':'outbox','state':'sent','gmail_id':'receipt'}}
  before=copy.deepcopy(db.records)
  incidents.cloud_batch(db,[('approval','lead',['Recipient does not match published evidence'],{})],observation='123')
  for k,v in before.items():self.assertEqual(db.records[k],v)
  self.assertEqual(len(db.records['incident_history']['events']),1)

 def test_journal_survives_a_store_restart(self):
  with tempfile.TemporaryDirectory() as folder:
   store=Store(folder);incidents.record(store,'drafting','lead',['Draft contains unresolved placeholders'],observation='1');store.db.close()
   store=Store(folder)
   self.assertEqual(incidents.load(store)[0]['code'],'draft');store.db.close()

 def test_successful_retry_resolves_the_same_research_session(self):
  with tempfile.TemporaryDirectory() as folder:
   store=Store(folder)
   incidents.task_result(store,'automatic-research','task1',{'session_id':'session','errors':[{'error':'Provider HTTP 429'}]},observation='task1')
   incidents.task_result(store,'automatic-research','task2',{'session_id':'session','errors':[]},observation='task2')
   self.assertEqual(incidents.load(store)[0]['status'],'resolved');store.db.close()

 def test_slow_remote_refresh_cannot_erase_a_new_local_failure(self):
  with tempfile.TemporaryDirectory() as folder:
   store=Store(folder);old=incidents.load(store)
   incidents.record(store,'research','new-task',['HTTP 429'],at=110)
   stale=incidents.observe(old,'notion','approval','lead',['Recipient does not match published evidence'],at=100)
   incidents.merge_remote_observations(store,stale)
   self.assertEqual({x['scope'] for x in incidents.load(store)},{'new-task','lead'});store.db.close()


class ErrorCenterTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=Store(self.temp.name);self.addCleanup(self.store.db.close)
  self.prefs={'notion_leads_source_id':'source'}

 def page(self,error='',status='Needs Review'):
  return {'id':'a'*32,'last_edited_time':'2026-11-23T01:00:00Z','properties':{'Name':{'title':rich('Example company')},'Deduplication Key':{'type':'rich_text','rich_text':rich('lead')},'STATUS':{'status':{'name':status}},'Error':{'type':'rich_text','rich_text':rich(error)}}}

 def test_read_only_refresh_imports_notion_holds_and_resolves_after_fix(self):
  n=Mock();n.query.return_value=[self.page('Recipient does not match published evidence')]
  result=error_center.refresh(self.store,self.prefs,n,reader=lambda _:None,clock=lambda:100)
  self.assertEqual(result['counts']['open'],1);self.assertEqual(result['incidents'][0]['company'],'Example company')
  n.request.assert_not_called()
  n.query.return_value=[self.page()]
  result=error_center.refresh(self.store,self.prefs,n,reader=lambda _:None,clock=lambda:150)
  self.assertEqual(result['counts']['open'],0);self.assertEqual(result['counts']['resolved'],1)

 def test_failed_source_read_does_not_falsely_resolve_its_incidents(self):
  n=Mock();n.query.return_value=[self.page('Recipient does not match published evidence')]
  error_center.refresh(self.store,self.prefs,n,reader=lambda _:None,clock=lambda:100)
  n.query.side_effect=ValueError('HTTP 401 PRIVATE_SECRET')
  result=error_center.refresh(self.store,self.prefs,n,reader=lambda _:None,clock=lambda:150)
  self.assertEqual(result['sources']['notion']['state'],'unavailable')
  self.assertTrue(any(x['code']=='contact' and x['status']=='open' for x in result['incidents']))
  self.assertNotIn('PRIVATE_SECRET',json.dumps(result))

 def test_waiting_queue_is_information_not_an_error(self):
  records={'control':{'paused':False},'delivery_health':{'outcome':'ok'},'outbox_x':{'kind':'outbox','id':'x','state':'queued','lead_id':'lead','recipient':'PRIVATE_EMAIL','body':'PRIVATE_BODY'}}
  result=error_center.refresh(self.store,self.prefs,reader=lambda _:records,clock=lambda:100)
  self.assertEqual(result['sources']['cloud']['queued'],1);self.assertEqual(result['counts']['open'],0)
  self.assertNotIn('PRIVATE_EMAIL',json.dumps(result));self.assertNotIn('PRIVATE_BODY',json.dumps(result))

 def test_legacy_uncertain_send_is_visible_even_without_journal(self):
  records={'control':{},'outbox_x':{'kind':'outbox','id':'x','state':'uncertain','lead_id':'lead','recipient':'PRIVATE_EMAIL'}}
  result=error_center.refresh(self.store,self.prefs,reader=lambda _:records,clock=lambda:100)
  self.assertEqual(result['counts']['urgent'],1);self.assertFalse(result['sources']['cloud']['history_available'])

 def test_cloud_failures_preserve_the_previous_successful_cache(self):
  records={'control':{},'incident_history':{'events':incidents.observe([],'cloud','sending','lead',['Unresolved delivery'],at=90)},'delivery_health':{'outcome':'ok'}}
  error_center.refresh(self.store,self.prefs,reader=lambda _:records,clock=lambda:100)
  def fail(_):raise ValueError('Connection failed SECRET')
  result=error_center.refresh(self.store,self.prefs,reader=fail,clock=lambda:150)
  self.assertEqual(result['sources']['cloud']['checked_at'],100)
  self.assertEqual(result['sources']['cloud']['state'],'unavailable')
  self.assertEqual(result['counts']['urgent'],1);self.assertNotIn('SECRET',json.dumps(result))

 def test_missing_monitor_credentials_does_not_trigger_network_or_claim_connection(self):
  with patch('subprocess.run') as run:
   self.assertIsNone(error_center.cloud_read(self.temp.name));run.assert_not_called()

 def test_monitor_uses_only_a_read_command_and_keeps_key_out_of_arguments(self):
  path=Path(self.temp.name)/'credentials';path.mkdir();(path/'error-center-ledger.key').write_text('PRIVATE_KEY')
  response=Mock(returncode=0,stdout=json.dumps({'encoding':'base64','content':'eA=='}))
  with patch('shutil.which',return_value='/usr/bin/gh'),patch('subprocess.run',return_value=response) as run,patch('hosted_sender.github_state.Codec') as codec:
   codec.return_value.open.return_value={'control':{}}
   error_center.cloud_read(self.temp.name)
   args=run.call_args.args[0]
   self.assertEqual(args[:2],['gh','api']);self.assertNotIn('PRIVATE_KEY',json.dumps(args));self.assertNotIn('shell',run.call_args.kwargs)

 def test_normal_sent_or_opted_out_records_do_not_show_old_qualification_errors(self):
  for status in ('Sent','Replied','Closed','Do Not Contact'):
   n=Mock();n.query.return_value=[self.page('Recipient does not match published evidence',status)]
   result=error_center.refresh(self.store,self.prefs,n,reader=lambda _:None,clock=lambda:100)
   self.assertEqual(result['counts']['open'],0)

 def test_reply_stopping_a_followup_is_not_a_new_bug(self):
  page=self.page(status='Replied')
  page['properties']['Follow-up 1 Delivery']={'type':'rich_text','rich_text':rich('Held: Reply, stop or unresolved delivery blocks follow-up')}
  n=Mock();n.query.return_value=[page]
  result=error_center.refresh(self.store,self.prefs,n,reader=lambda _:None,clock=lambda:100)
  self.assertEqual(result['counts']['open'],0)

 def test_task_backfill_is_ordered_and_idempotent_after_a_successful_retry(self):
  from acquisition_agent.panel import open_store
  self.store.db.close();self.store=open_store(self.temp.name)
  self.store.db.executemany('INSERT INTO panel_tasks VALUES(?,?,?,?,?)',[
   ('a','automatic-research','Failed',json.dumps({'session_id':'session','error':'HTTP 429'}),'2026-11-23T01:00:00Z'),
   ('b','automatic-research','Completed',json.dumps({'session_id':'session','errors':[]}),'2026-11-23T02:00:00Z')])
  self.store.db.commit()
  first=error_center.snapshot(self.store);second=error_center.snapshot(self.store)
  self.assertEqual(first['counts']['open'],0);self.assertEqual(second['counts']['open'],0)
  self.assertEqual(first['incidents'][0]['occurrences'],second['incidents'][0]['occurrences'])
  self.store.db.close()

 def test_legacy_uncertain_event_keeps_its_first_seen_and_resolves_after_reconciliation(self):
  records={'control':{},'outbox_x':{'kind':'outbox','id':'x','state':'uncertain','lead_id':'lead'}}
  one=error_center.refresh(self.store,self.prefs,reader=lambda _:records,clock=lambda:100)
  two=error_center.refresh(self.store,self.prefs,reader=lambda _:records,clock=lambda:150)
  self.assertEqual(one['incidents'][0]['first_seen'],two['incidents'][0]['first_seen'])
  records['outbox_x']['state']='sent'
  fixed=error_center.refresh(self.store,self.prefs,reader=lambda _:records,clock=lambda:200)
  self.assertEqual(fixed['counts']['open'],0);self.assertEqual(fixed['counts']['resolved'],1)

 def test_new_resolution_wins_over_an_older_cloud_observation(self):
  cached_cloud={'control':{},'incident_history':{'events':incidents.observe([],'cloud','approval','lead',['Recipient does not match published evidence'],at=110)}}
  n=Mock();n.query.return_value=[self.page('Recipient does not match published evidence')]
  error_center.refresh(self.store,self.prefs,n,reader=lambda _:cached_cloud,clock=lambda:100)
  n.query.return_value=[self.page()]
  fixed=error_center.refresh(self.store,self.prefs,n,reader=lambda _:cached_cloud,clock=lambda:200)
  self.assertEqual(fixed['counts']['open'],0)
