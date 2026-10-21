"""Campaign-free handoff: real qualification/state logic with isolated fake providers."""
import copy
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from hosted_sender.cli import enable_approvals, run
from hosted_sender.health import snapshot
from hosted_sender.notion_import import refresh
from hosted_sender.queue import Queue
from hosted_sender.worker import settings_hash
from acquisition_agent.providers import rich, research_notes
import test_hosted_worker


class ApprovalDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.f=test_hosted_worker.WorkerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.q,self.s=self.f.q,self.f.s
        self.f.lead['id']='a'*16
        self.f.db.records['lead_'+self.f.lead['id']]=self.f.db.records.pop('lead_lead')
        self.f.db.records['lead_'+self.f.lead['id']]['data']['id']=self.f.lead['id']
        original_page=self.f.page
        def complete_page():
            page=original_page();lead=self.f.lead
            page['properties'].update({'Name':{'title':rich(lead['company'])},
                'Deduplication Key':{'type':'rich_text','rich_text':rich(lead['id'])},
                'Research Notes':{'type':'rich_text','rich_text':rich(research_notes(lead))},
                'COUNTRY':{'type':'rich_text','rich_text':rich('UAE')},
                'Role':{'type':'rich_text','rich_text':rich(lead['title'])},
                'Job URL':{'url':lead['url']},'WEBSITE':{'url':lead['website']},
                'Contact Source URL':{'url':lead['contact_source_url']},
                'Type':{'select':{'name':'Brand'}},'Opportunity Type':{'select':{'name':'Cold Outreach'}}})
            return page
        self.f.page=complete_page
        self.q.db.records['control'].update(mac_sender_disabled=True,test_hash=settings_hash(self.s))
        self.addCleanup(patch.stopall)
        patch.dict(os.environ,{'SHINE_DELIVERY_ENABLED':'true'}).start()

    def enable(self):return enable_approvals(self.q,self.s,settings_hash(self.s))

    def test_enable_preserves_receipts_daily_counts_and_test(self):
        before=copy.deepcopy(self.q.control())
        self.q.db.records['outbox_old']={'kind':'outbox','id':'old','state':'sent','gmail_id':'saved','campaign':'a'}
        result=self.enable()
        self.assertFalse(result['campaign_required'])
        self.assertEqual(self.q.db.get('outbox_old')['gmail_id'],'saved')
        self.assertEqual(self.q.control()['days'],before['days'])
        self.assertTrue(self.q.control()['test_verified'])
        self.assertIsNone(self.q.control()['active_campaign'])

    def test_mode_change_requires_current_tested_policy(self):
        with self.assertRaises(ValueError):enable_approvals(self.q,self.s,'wrong')
        self.q.db.records['control']['test_verified']=False
        with self.assertRaises(ValueError):self.enable()

    def test_three_drafts_to_approval_to_receipts_on_different_weeks(self):
        self.enable();f=self.f;pages={};base=copy.deepcopy(f.lead)
        for n in range(3):
            key=f'{n+1:016x}';lead=copy.deepcopy(base)
            lead=json.loads(json.dumps(lead).replace('paper.example',f'paper{n}.example'))
            lead.update(id=key,notion_page_id=f'page{n}')
            f.q.db.records['lead_'+key]={'kind':'lead','data':lead}
            f.lead=lead;page=f.page()
            page=json.loads(json.dumps(page).replace('office@paper.example',lead['email']))
            page['id']=lead['notion_page_id']
            page['properties'].update({'Name':{'type':'title','title':rich('Paper Cocoa')},
                'Deduplication Key':{'type':'rich_text','rich_text':rich(key)},
                'Research Notes':{'type':'rich_text','rich_text':rich(research_notes(lead))},
                'Job URL':{'url':lead['url']},'WEBSITE':{'url':lead['website']},
                'Opportunity Type':{'select':{'name':'Cold Outreach'}},'Type':{'select':{'name':'Brand'}},
                'Role':{'type':'rich_text','rich_text':rich(lead['title'])},
                'COUNTRY':{'type':'rich_text','rich_text':rich('UAE')},
                'STATUS':{'status':{'name':'Draft'}}})
            pages[page['id']]=page
        def notion(path,method='POST',data=None):
            page=pages[path.split('/')[1]]
            if method=='PATCH':page['properties'].update(copy.deepcopy(data['properties']))
            return copy.deepcopy(page)
        f.notion.request.side_effect=notion
        f.notion.query.side_effect=lambda source:list(copy.deepcopy(pages).values())
        self.assertEqual(refresh(self.q,f.notion,self.s)['queued'],0)
        f.gmail.send.assert_not_called()
        for n,day in enumerate((19,20,28)):
            key=f'{n+1:016x}';page=pages[f'page{n}'];page['properties']['STATUS']={'status':{'name':'Approve'}}
            t=datetime(2026,10,day,6,tzinfo=timezone.utc).timestamp()
            refresh(self.q,f.notion,self.s)
            queued=[x for x in self.q.db.list('outbox') if x['state']=='queued']
            self.assertEqual(len(queued),1,str(page['properties'].get('Delivery State')))
            self.q.db.records['outbox_'+queued[0]['id']]['due_at']=t
            self.q=Queue(f.db);f.w.q=self.q  # A fresh process reuses durable history.
            f.gmail.send.return_value={'id':f'gmail{n}','threadId':f'thread{n}'}
            f.w.research=lambda url:pages[f'page{n}']['properties']['Research Notes']['rich_text'][0]['text']['content']
            result=f.w.tick(t)
            self.assertEqual(result['state'],'sent')
            self.assertEqual(page['properties']['STATUS']['status']['name'],'Sent')
            self.assertEqual(page['properties']['Gmail Message ID']['rich_text'][0]['text']['content'],f'gmail{n}')
            self.assertIn(self.s['profile']['portfolio_url'],f.gmail.send.call_args.args[3])
            self.assertIn(self.s['profile']['email_signature'],f.gmail.send.call_args.args[3])
            refresh(self.q,f.notion,self.s);f.w.tick(t+600)
            self.assertEqual(f.gmail.send.call_count,n+1)

    def test_next_week_approval_needs_no_campaign_date(self):
        self.enable();item=self.f.w.enqueue(self.f.lead['id'])
        t=datetime(2026,10,28,6,tzinfo=timezone.utc).timestamp()
        self.q.db.records['outbox_'+item['id']]['due_at']=t
        self.assertEqual(self.f.w.tick(t)['state'],'sent')
        self.assertEqual(self.q.control()['days']['2026-10-28'],1)

    def test_withdrawn_approval_or_dnc_stops_dispatch(self):
        self.enable();item=self.f.w.enqueue(self.f.lead['id'])
        self.q.db.records['outbox_'+item['id']]['due_at']=self.f.t
        page=self.f.page();page['properties']['STATUS']={'status':{'name':'Do Not Contact'}}
        self.f.notion.request.side_effect=lambda *args:copy.deepcopy(page)
        self.assertEqual(self.f.w.tick(self.f.t)['state'],'no-due-send')
        self.f.gmail.send.assert_not_called()

    def test_atomic_claim_enforces_local_window_and_new_policy(self):
        self.enable();item=self.f.w.enqueue(self.f.lead['id'])
        self.q.db.records['outbox_'+item['id']]['due_at']=self.f.t
        with self.assertRaisesRegex(ValueError,'Outside company-local'):
            self.q.claim(item['id'],self.f.t+7200,settings_hash(self.s),50,180,'Asia/Bangkok')
        self.q.db.records['control']['approval_policy_hash']='old'
        with self.assertRaisesRegex(ValueError,'policy'):
            self.q.claim(item['id'],self.f.t,settings_hash(self.s),50,180,'Asia/Bangkok')

    def test_health_shows_next_weekday_without_campaign(self):
        self.enable();item=self.f.w.enqueue(self.f.lead['id'])
        self.q.db.records['outbox_'+item['id']]['due_at']=0
        friday=datetime(2026,10,23,8,tzinfo=timezone.utc).timestamp()
        report=snapshot(self.q,self.s,friday,timer={'state':'never_observed'})
        self.assertEqual(report['delivery_model'],'notion-approval')
        self.assertIsNone(report['campaign'])
        self.assertEqual(report['next_queue_window_utc'],'2026-10-26T04:00:00+00:00')
        self.assertEqual(report['overall_state'],'attention_timer_unverified')

    def test_run_imports_approvals_without_active_campaign(self):
        self.enable()
        with patch('hosted_sender.cli.refresh',return_value={'imported':0,'queued':0,'held':0}) as importer,patch('hosted_sender.cli.Worker') as worker:
            worker.return_value.tick.return_value={'state':'no-due-send'}
            result=run(self.q,self.s,self.f.gmail,self.f.notion)
        importer.assert_called_once();worker.return_value.tick.assert_called_once()
        self.assertEqual(result['sent_this_run'],0)

    def test_new_notion_evidence_overrides_longer_historical_seed(self):
        self.enable();key=self.f.lead['id'];page=self.f.page()
        self.q.db.records['lead_'+key]['data']['source_documents'][0]['text']+=' historical padding'*200
        page['properties']['COUNTRY']={'type':'rich_text','rich_text':rich('Outside approved markets')}
        self.f.notion.request.side_effect=lambda *args:copy.deepcopy(page)
        with self.assertRaisesRegex(ValueError,'Country'):self.f.w.enqueue(key)
        self.f.gmail.send.assert_not_called()

    def test_invalid_research_after_queueing_blocks_dispatch(self):
        self.enable();item=self.f.w.enqueue(self.f.lead['id'])
        self.q.db.records['outbox_'+item['id']]['due_at']=self.f.t
        page=self.f.page();page['properties']['Research Notes']['rich_text']=rich('{truncated')
        self.f.notion.request.side_effect=lambda *args:copy.deepcopy(page)
        self.assertEqual(self.f.w.tick(self.f.t)['state'],'no-due-send')
        self.assertEqual(self.q.db.get('outbox_'+item['id'])['state'],'blocked')
        self.f.gmail.send.assert_not_called()
