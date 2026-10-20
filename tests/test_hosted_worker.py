import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from test_hosted_queue import Memory
from hosted_sender.queue import Queue
from hosted_sender.worker import Worker, settings_hash
from acquisition_agent.core import prepare_lead
from acquisition_agent.providers import rich

ROOT=Path(__file__).resolve().parent.parent
class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.db=Memory();self.q=Queue(self.db);self.q.init()
        self.s={k:json.loads((ROOT/'config'/(k+'.json')).read_text()) for k in ('profile','preferences','sending','exclusions')}
        self.s['exclusions']={'confirmed':True,'domains':['growth-horizon.nl'],'companies':['Growth Horizon'],'emails':[]}
        self.s['sending']['business_postal_address']='Test fixture address only'
        self.s['sending'].update(mode='automatic',schedule_basis='company',follow_up_days=[],minimum_fit_score=0,send_hours=[8,11],minimum_interval_seconds=180,send_weekdays=[0,1,2,3,4])
        self.s['preferences']['countries'].append('United Arab Emirates') if 'United Arab Emirates' not in self.s['preferences']['countries'] else None
        self.t=datetime(2026,10,19,6,tzinfo=timezone.utc).timestamp()
        self.target={'country':'United Arab Emirates','city':'Dubai','company_type':'Brand','industries':['chocolate_snacks_nuts'],'kind':'Cold Outreach','limit':5}
        text='We are an independent chocolate brand located in Dubai, United Arab Emirates. Contact our studio: office@paper.example.'
        lead=prepare_lead({'url':'https://paper.example/','website':'https://paper.example/','company':'Paper Cocoa','title':'Freelance email design support','kind':'Cold Outreach','country':'United Arab Emirates','type':'Brand','source_text':text})
        lead.update(email='office@paper.example',email_candidates=['office@paper.example'],contact_source_url='https://paper.example/',id='lead',notion_page_id='page',location_city='Dubai',industry='chocolate_snacks_nuts',target_session={'id':'s','spec':self.target},target_evidence={k:{'url':lead['url'],'quote':v} for k,v in [('location','located in Dubai, United Arab Emirates'),('company_type','independent chocolate brand'),('industry','chocolate brand')]},company_time_zone='Asia/Dubai',company_time_zone_verified=True,company_time_zone_source=lead['url'])
        lead['draft']={'subject':'Figma design support for Paper Cocoa','body':'Hi Paper Cocoa team, I create Figma email designs for e-commerce brands. Your chocolate could feature in clear product campaigns. Klaviyo building is quoted separately. Would a small paid test help? Portfolio: '+self.s['profile']['portfolio_url'],'evidence':[{'url':lead['url'],'quote':'independent chocolate brand'}]}
        self.lead=lead;self.db.records['lead_lead']={'kind':'lead','data':lead}
        self.q.campaign('a',{'dates':['2026-10-19'],'start_date':'2026-10-19','end_date':'2026-10-19','maximum_sends':5,'settings_hash':settings_hash(self.s),'target':self.target})
        self.db.records['control'].update(paused=False,migration_complete=True,test_verified=True,approved_hash=settings_hash(self.s))
        self.gmail=Mock();self.gmail.identity.return_value=self.s['sending']['sender'];self.gmail.send.return_value={'id':'gmail1','threadId':'thread1'}
        self.gmail.prior_contact.return_value=False;self.gmail.prior_company_contact.return_value=False;self.gmail.thread.return_value=[];self.gmail.related.return_value=[]
        self.notion=Mock();self.notion.request.side_effect=lambda path,method='POST',data=None:self.page() if method=='GET' else {}
        self.w=Worker(self.q,self.s,self.gmail,self.notion,lambda url:text)
    def page(self):
        props={k:{'checkbox':True} for k in ['Approved','Eligibility Reviewed','Contact Purpose Reviewed','Outreach Allowed','Targeting Reviewed','Company Time Zone Verified']}
        props.update({'STATUS':{'status':{'name':'Approve'}},'EMAIL':{'email':'office@paper.example'},'Company Time Zone':{'select':{'name':'Asia/Dubai'}},'Company Time Zone Source':{'url':'https://paper.example/'}})
        for name,value in [('email SUBJECT',self.lead['draft']['subject']),('email body',self.lead['draft']['body']),('Selected Offer','paid_test'),('Contact Source Notes','Official shared studio inbox; relevant business introduction'),('Application Route','Business introduction')]:props[name]={'type':'rich_text','rich_text':rich(value)}
        return {'id':'page','properties':props}
    def enqueue(self):
        item=self.w.enqueue('lead','a');self.db.records['outbox_'+item['id']]['due_at']=self.t;return item
    def test_real_preflight_send_and_notion_receipt(self):
        item=self.enqueue();result=self.w.tick(self.t)
        self.assertEqual(result['state'],'sent');self.assertEqual(self.db.get('outbox_'+item['id'])['state'],'sent');self.assertEqual(self.gmail.send.call_count,1)
        self.assertIn(self.s['profile']['portfolio_url'],self.gmail.send.call_args.args[3])
    def test_gmail_timeout_never_retry(self):
        item=self.enqueue();self.gmail.send.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):self.w.tick(self.t)
        self.assertEqual(self.db.get('outbox_'+item['id'])['state'],'uncertain')
        with self.assertRaises(ValueError):self.w.tick(self.t+600)
        self.assertEqual(self.gmail.send.call_count,1)
    def test_notion_failure_after_send_does_not_resend(self):
        item=self.enqueue();original=self.notion.request.side_effect
        self.notion.request.side_effect=lambda p,m='POST',d=None:(_ for _ in ()).throw(ValueError('notion offline')) if m=='PATCH' else original(p,m,d)
        with self.assertRaises(ValueError):self.w.tick(self.t)
        self.assertEqual(self.db.get('outbox_'+item['id'])['state'],'sent')
        self.notion.request.side_effect=original;self.w.tick(self.t+600)
        self.assertEqual(self.gmail.send.call_count,1)
    def test_changed_draft_stops_send(self):
        self.enqueue();self.lead['draft']['body']+=' Changed.'
        self.assertEqual(self.w.tick(self.t)['state'],'no-due-send')
        self.gmail.send.assert_not_called()
    def test_reply_stops_and_not_reverted_to_sent(self):
        item=self.enqueue();self.w.tick(self.t)
        self.gmail.thread.return_value=[{'id':'reply','internalDate':str(int((self.t+1)*1000)),'labelIds':['INBOX'],'snippet':'Please remove me','payload':{'headers':[{'name':'From','value':'office@paper.example'}]}}]
        self.w.tick(self.t+600)
        self.assertIn('Opt-out',self.db.get('outbox_'+item['id'])['reply_reason'])
        patches=[x.args[2]['properties'] for x in self.notion.request.call_args_list if len(x.args)>2 and x.args[1]=='PATCH']
        self.assertEqual(patches[-1]['STATUS']['status']['name'],'Do Not Contact')
    def test_outside_company_window(self):
        self.enqueue();self.assertEqual(self.w.tick(self.t+7200)['state'],'no-due-send');self.gmail.send.assert_not_called()
    def test_suppression_between_preflight_and_claim(self):
        self.enqueue()
        self.gmail.prior_contact.side_effect=lambda email:(self.q.suppress([email],'Opt-out') or False)
        self.assertEqual(self.w.tick(self.t)['state'],'no-due-send')
        self.gmail.send.assert_not_called()
    def test_campaign_mismatch(self):
        self.db.records['campaign_a']['target']['city']='London'
        with self.assertRaises(ValueError):self.enqueue()
    def test_wrong_sender(self):
        self.enqueue();self.gmail.identity.return_value='wrong@example.com'
        with self.assertRaises(ValueError):self.w.tick(self.t)
        self.gmail.send.assert_not_called()
    def test_prior_company_contact_is_held_without_sending(self):
        item=self.enqueue();self.gmail.prior_company_contact.return_value=True
        self.assertEqual(self.w.tick(self.t)['state'],'no-due-send')
        self.assertEqual(self.db.get('outbox_'+item['id'])['state'],'blocked');self.gmail.send.assert_not_called()
    def test_weekend_does_not_send(self):
        self.enqueue();self.assertEqual(self.w.tick(self.t+5*86400)['state'],'no-due-send');self.gmail.send.assert_not_called()
    def test_legacy_ready_is_not_new_hosted_approval(self):
        original=self.notion.request.side_effect
        def legacy(path,method='POST',data=None):
            page=original(path,method,data)
            if method=='GET':page['properties']['STATUS']={'status':{'name':'Ready'}}
            return page
        self.notion.request.side_effect=legacy
        with self.assertRaisesRegex(ValueError,'Approve'):self.w.enqueue('lead','a')
        self.gmail.send.assert_not_called()
    def test_reconcile_requires_matching_positive_receipt(self):
        item=self.enqueue();self.q.claim(item['id'],self.t,settings_hash(self.s),10,300,'Asia/Bangkok');self.q.outcome(item['id'],error='timeout')
        self.gmail.find_sent.return_value=None
        with self.assertRaises(ValueError):self.w.reconcile(item['id'])
        self.assertTrue(self.q.control()['active_attempt'])
        self.gmail.find_sent.return_value={'id':'gmail1'}
        self.gmail.message.return_value={'id':'gmail1','threadId':'thread1','labelIds':['SENT'],'payload':{'headers':[{'name':'Message-ID','value':item['message_id']},{'name':'From','value':self.s['sending']['sender']},{'name':'To','value':item['recipient']}]}}
        self.w.reconcile(item['id']);self.assertEqual(self.q.control()['active_attempt'],'');self.gmail.send.assert_not_called()

