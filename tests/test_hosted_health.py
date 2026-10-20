import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from hosted_sender import health
from hosted_sender.queue import Queue
from hosted_sender.worker import settings_hash
from hosted_sender.cli import run
from hosted_sender.github_state import StateError
from test_hosted_queue import Memory

ROOT=Path(__file__).resolve().parent.parent


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.s={k:json.loads((ROOT/'config'/(k+'.json')).read_text()) for k in ('profile','preferences','sending','exclusions')}
        self.s['sending'].update(mode='automatic',send_hours=[8,11],send_weekdays=[0,1,2,3,4],minimum_interval_seconds=180,timezone='Asia/Bangkok',schedule_basis='company',follow_up_days=[])
        self.db=Memory();self.q=Queue(self.db);self.q.init()
        self.q.campaign('a',{'dates':['2026-10-20','2026-10-21'],'start_date':'2026-10-20','end_date':'2026-10-21','maximum_sends':20,'settings_hash':settings_hash(self.s)})
        self.db.records['control'].update(paused=False,migration_complete=True,test_verified=True,active_campaign='a',approved_hash=settings_hash(self.s))
        self.now=datetime(2026,10,20,15,22,tzinfo=timezone.utc).timestamp()
        self.db.records['outbox_a']={'kind':'outbox','id':'a','state':'queued','campaign':'a','company_timezone':'Asia/Dubai',
            'due_at':datetime(2026,10,21,4,tzinfo=timezone.utc).timestamp(),'recipient':'PRIVATE_CONTACT@example.com','body':'PRIVATE_BODY'}
        self.addCleanup(patch.stopall)
        patch.dict(os.environ,{'SHINE_DELIVERY_ENABLED':'true','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ID':'123'}).start()

    def report(self):return health.snapshot(self.q,self.s,self.now,timer={'state':'never_observed','last_event_at':None,'last_success_at':None})

    def test_next_window_uses_company_zone_and_campaign_dates(self):
        self.assertEqual(self.report()['next_queue_window_utc'],'2026-10-21T04:00:00+00:00')
        self.db.records['campaign_a']['dates']=['2026-10-20']
        self.assertIsNone(self.report()['next_queue_window_utc'])

    def test_pause_delivery_switch_and_exhausted_campaign_remove_next_window(self):
        self.q.pause();self.assertIsNone(self.report()['next_queue_window_utc'])
        self.q.pause(False)
        with patch.dict(os.environ,{'SHINE_DELIVERY_ENABLED':'false'}):self.assertIsNone(self.report()['next_queue_window_utc'])
        self.db.records['campaign_a']['sent_attempts']=20
        self.assertIsNone(self.report()['next_queue_window_utc'])

    def test_stale_due_time_is_not_reported_as_an_available_past_window(self):
        self.db.records['outbox_a']['due_at']=self.now-86400
        self.assertEqual(self.report()['next_queue_window_utc'],'2026-10-21T04:00:00+00:00')

    def test_daily_cap_does_not_advertise_a_window_that_cannot_be_used(self):
        self.db.records['control']['days']={'2026-10-21':self.s['sending']['daily_limit']}
        self.assertIsNone(self.report()['next_queue_window_utc'])

    def test_company_window_respects_daylight_saving_transition(self):
        self.db.records['outbox_a'].update(company_timezone='America/New_York',due_at=0)
        plan=self.db.records['campaign_a'];plan['dates']=['2026-11-02']
        self.assertEqual(self.report()['next_queue_window_utc'],'2026-11-02T13:00:00+00:00')

    def test_working_timer_does_not_hide_an_unapproved_configuration(self):
        self.db.records['control']['approved_hash']='old-policy'
        timer={'state':'recent_success','last_event_at':health.iso(self.now),'last_success_at':health.iso(self.now)}
        report=health.snapshot(self.q,self.s,self.now,timer=timer)
        self.assertFalse(report['configuration_ready']);self.assertEqual(report['overall_state'],'blocked_configuration')

    def test_no_timer_is_not_presented_as_operational_after_manual_check(self):
        self.assertEqual(self.report()['overall_state'],'attention_timer_unverified')

    def test_sent_counts_exclude_test_and_keep_pending_sync_separate(self):
        self.db.records['outbox_a'].update(state='sent',attempted_at=self.now,notion_sync_pending=True)
        self.db.records['outbox_test']={'kind':'outbox','mode':'test','state':'sent','attempted_at':self.now}
        report=self.report()
        self.assertEqual(report['confirmed_sent_today'],1);self.assertEqual(report['notion_sync_pending'],1)
        self.assertEqual(report['queued'],0)

    def test_no_schedule_event_remains_unverified_after_manual_success(self):
        self.db.api=Mock(side_effect=[{'state':'active'},{'workflow_runs':[]}])
        self.assertEqual(health.timer_status(self.q,self.now)['state'],'never_observed')

    def test_old_success_is_stale_and_api_failure_is_unknown(self):
        old={'created_at':'2026-05-01T20:02:04Z','status':'completed','conclusion':'success'}
        self.db.api=Mock(side_effect=[{'state':'active'},{'workflow_runs':[old]}])
        self.assertEqual(health.timer_status(self.q,self.now)['state'],'stale')
        self.db.api=Mock(side_effect=ValueError('PRIVATE_TOKEN'))
        self.assertEqual(health.timer_status(self.q,self.now)['state'],'unavailable')

    def test_manual_health_check_cannot_claim_scheduled_success(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result=health.monitored_run(self.q,self.s,lambda progress:{'state':'no-due-send'},now=lambda:self.now)
        self.assertEqual(result['state'],'no-due-send')
        self.assertIsNone(self.db.get(health.KEY)['last_scheduled_success_at'])
        self.assertNotIn('PRIVATE_CONTACT',output.getvalue());self.assertNotIn('PRIVATE_BODY',output.getvalue())

    def test_genuine_schedule_operation_records_separate_success(self):
        with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'schedule'}),contextlib.redirect_stdout(io.StringIO()):
            health.monitored_run(self.q,self.s,lambda progress:{'state':'no-due-send'},now=lambda:self.now)
        self.assertEqual(self.db.get(health.KEY)['last_scheduled_success_at'],health.iso(self.now))

    def test_failure_after_receipt_reports_saved_delivery_without_exposing_error_body(self):
        def operation(progress):
            self.db.records['outbox_a'].update(state='sent',attempted_at=self.now,notion_sync_pending=True)
            progress('notion_receipt_sync')
            raise ValueError('API request failed with HTTP 429 PRIVATE_TOKEN_BODY')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(ValueError):health.monitored_run(self.q,self.s,operation,now=lambda:self.now)
        saved=self.db.get(health.KEY)
        self.assertEqual(saved['outcome'],'failed');self.assertEqual(saved['confirmed_sends_this_run'],1)
        self.assertEqual(saved['stage'],'notion_receipt_sync');self.assertEqual(saved['error']['http_status'],429)
        self.assertEqual(self.db.get('outbox_a')['state'],'sent')
        self.assertNotIn('PRIVATE_TOKEN',output.getvalue())

    def test_pending_notion_sync_is_attention_not_a_failed_email(self):
        self.db.records['outbox_a'].update(state='sent',attempted_at=self.now,notion_sync_pending=True)
        with contextlib.redirect_stdout(io.StringIO()):health.monitored_run(self.q,self.s,lambda progress:{},now=lambda:self.now)
        self.assertEqual(self.db.get(health.KEY)['outcome'],'attention')
        self.assertEqual(self.db.get('outbox_a')['state'],'sent')

    def test_unresolved_dispatch_never_gets_a_new_send_attempt(self):
        self.db.records['control']['active_attempt']='a'
        self.db.records['outbox_a']['state']='uncertain'
        gmail=Mock();notion=Mock()
        result=run(self.q,self.s,gmail,notion)
        self.assertIn('uncertain',result['state']);gmail.send.assert_not_called()
        self.assertEqual(self.report()['overall_state'],'blocked_unresolved_delivery')

    def test_unreadable_state_cannot_produce_a_healthy_report(self):
        def operation(progress):
            progress('receipt_persistence')
            self.db.get=Mock(side_effect=StateError('PRIVATE_STATE_BODY'))
            raise StateError('PRIVATE_STATE_BODY')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(StateError):health.monitored_run(self.q,self.s,operation,now=lambda:self.now)
        text=output.getvalue()
        self.assertIn('"outcome": "failed"',text);self.assertNotIn('PRIVATE_STATE_BODY',text)
        self.assertNotIn('"outcome": "ok"',text)

    def test_pending_saved_receipt_blocks_new_dispatch_until_sync_recovers(self):
        self.db.records['outbox_a'].update(state='sent',attempted_at=self.now,notion_sync_pending=True)
        gmail=Mock();notion=Mock()
        with patch('hosted_sender.cli.Worker') as worker:
            worker.return_value.sync_one.return_value=False
            result=run(self.q,self.s,gmail,notion)
        self.assertEqual(result['sent_this_run'],0);self.assertEqual(result['notion_sync_pending'],1)
        worker.return_value.tick.assert_not_called();gmail.send.assert_not_called()

    def test_github_summary_uses_only_aggregate_health(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'summary.md'
            with patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':str(path)}),contextlib.redirect_stdout(io.StringIO()):health.emit(self.report())
            text=path.read_text()
        self.assertIn('never_observed',text);self.assertIn('2026-10-21T04:00:00',text)
        self.assertNotIn('PRIVATE_CONTACT',text);self.assertNotIn('PRIVATE_BODY',text)
