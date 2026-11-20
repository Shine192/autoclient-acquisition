import copy,json,unittest
from datetime import datetime,timezone
import test_approval_delivery as fixture
from acquisition_agent.client_workflow import source_fingerprint
from acquisition_agent.providers import rich
from hosted_sender.followups import enqueue, prepare

class ReviewedFollowupsTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.ApprovalDeliveryTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.base.enable();self.f=self.base.f;self.q=self.f.q
        self.page=self.f.page()
        def notion(path,method='POST',data=None):
            if method=='PATCH':
                for k,v in data['properties'].items():
                    if 'rich_text' in v:v=dict(v,type='rich_text')
                    self.page['properties'][k]=copy.deepcopy(v)
            return copy.deepcopy(self.page)
        self.f.notion.request.side_effect=notion
        self.item=self.f.w.enqueue(self.f.lead['id'])
        self.q.db.records['outbox_'+self.item['id']]['due_at']=self.f.t
        self.f.w.tick(self.f.t)
        self.parent=self.q.db.get('outbox_'+self.item['id'])
        self.q.db.records['control']['reviewed_followups_enabled']=True
        self.f.gmail.message.return_value={'id':'gmail1','threadId':'thread1','labelIds':['SENT'],'payload':{'headers':[
            {'name':'Message-ID','value':'<provider@sender.example>'},{'name':'From','value':self.f.s['sending']['sender']},
            {'name':'To','value':self.parent['recipient']}]}}
        self.f.gmail.send.reset_mock()
        self.approve()
    def approve(self):
        p=self.page['properties'];body=self.f.lead['draft']['body']
        p['Follow-up 1 Draft']={'type':'rich_text','rich_text':rich(body)}
        p['Follow-up 1 Review']={'select':{'name':'Approve'}}
        p['Follow-up Review Log']={'type':'rich_text','rich_text':rich(json.dumps({'1':{'state':'Approve','sha256':source_fingerprint(p,body,1)}}))}
    def test_separate_approval_threading_due_and_no_duplicate(self):
        enqueue(self.f.w);items=[i for i in self.q.db.list('outbox') if i.get('stage')]
        self.assertEqual(len(items),1);item=items[0]
        due=datetime.fromtimestamp(item['due_at'],timezone.utc)
        self.assertEqual(due.date().isoformat(),'2026-10-26')
        self.f.gmail.send.return_value={'id':'follow1','threadId':'thread1'}
        self.assertEqual(self.f.w.tick(item['due_at'])['state'],'sent')
        self.assertEqual(self.f.gmail.send.call_args.kwargs,{'thread_id':'thread1','reply_to':'<provider@sender.example>'})
        self.assertEqual(self.page['properties']['Gmail Message ID']['rich_text'][0]['text']['content'],'gmail1')
        self.assertEqual(self.page['properties']['Follow-up 1 Receipt']['rich_text'][0]['text']['content'],'follow1')
        self.f.w.tick(item['due_at']+600);self.assertEqual(self.f.gmail.send.call_count,1)
    def test_initial_approval_or_reviewed_never_approves_followup(self):
        for value in ('Draft','Reviewed','Held','Cancelled'):
            self.page['properties']['Follow-up 1 Review']={'select':{'name':value}}
            enqueue(self.f.w)
        self.assertFalse(any(i.get('stage') for i in self.q.db.list('outbox')))
    def test_changed_draft_recipient_source_or_approval_stops_queued_followup(self):
        for field,value in [('Follow-up 1 Draft',{'type':'rich_text','rich_text':rich('Changed wording '+self.f.lead['draft']['body'])}),
                            ('EMAIL',{'email':'other@paper.example'}),('Research Notes',{'type':'rich_text','rich_text':rich('{}')}),
                            ('Follow-up 1 Review',{'select':{'name':'Reviewed'}})]:
            before=copy.deepcopy(self.page['properties']);self.page['properties'][field]=value
            with self.assertRaises((ValueError,KeyError)):prepare(self.f.w,self.parent,1)
            self.page['properties']=before
    def test_reply_and_bounce_suppress_and_hold(self):
        self.f.gmail.thread.return_value=[{'id':'inbound','internalDate':str(int((self.f.t+1)*1000)),
            'payload':{'headers':[{'name':'From','value':self.parent['recipient']}],'body':{'data':''}}}]
        with self.assertRaisesRegex(ValueError,'Reply'):prepare(self.f.w,self.parent,1)
        self.assertTrue(self.q.db.list('suppression'))
    def test_missing_receipt_second_stage_and_disabled_activation(self):
        with self.assertRaises(ValueError):prepare(self.f.w,self.parent,2)
        self.q.db.records['control']['reviewed_followups_enabled']=False
        with self.assertRaisesRegex(ValueError,'disabled'):prepare(self.f.w,self.parent,1)
    def test_inbox_failure_stops_delivery(self):
        self.f.gmail.thread.side_effect=ValueError('Inbox unavailable')
        with self.assertRaises(ValueError):self.f.w.tick(self.f.t+86400*7)
        self.f.gmail.send.assert_not_called()
    def test_unknown_manual_send_requires_reconciliation(self):
        self.f.gmail.thread.return_value=[{'id':'manual','labelIds':['SENT'],'internalDate':str(int((self.f.t+1)*1000))}]
        with self.assertRaisesRegex(ValueError,'Unrecorded sent'):prepare(self.f.w,self.parent,1)
    def test_timeout_uses_existing_uncertainty_lock(self):
        enqueue(self.f.w);item=next(i for i in self.q.db.list('outbox') if i.get('stage'))
        self.f.gmail.send.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):self.f.w.tick(item['due_at'])
        self.assertEqual(self.q.db.get('outbox_'+item['id'])['state'],'uncertain')
        with self.assertRaises(ValueError):self.f.w.tick(item['due_at']+600)
        self.assertEqual(self.f.gmail.send.call_count,1)

    def test_activation_requires_verified_policy_and_does_not_send(self):
        from hosted_sender.cli import enable_reviewed_followups
        from hosted_sender.worker import settings_hash
        self.q.db.records['control']['reviewed_followups_enabled']=False
        with self.assertRaises(ValueError):enable_reviewed_followups(self.q,self.f.s,'wrong')
        result=enable_reviewed_followups(self.q,self.f.s,settings_hash(self.f.s))
        self.assertTrue(result['individual_followup_approval_required'])
        self.f.gmail.send.assert_not_called()
        self.q.db.records['control']['active_attempt']='uncertain'
        with self.assertRaises(ValueError):enable_reviewed_followups(self.q,self.f.s,settings_hash(self.f.s))

    def test_second_followup_requires_actual_first_receipt_and_waits_seven_business_days(self):
        from hosted_sender.queue import digest
        from acquisition_agent.client_workflow import due_after
        key=digest([self.parent['id'],'followup',1])[:32]
        first=dict(self.parent,id=key,stage=1,gmail_id='first',attempted_at=datetime(2026,10,26,4,tzinfo=timezone.utc).timestamp())
        self.q.db.records['outbox_'+key]=first
        p=self.page['properties'];p['Follow-up 1 Receipt']={'type':'rich_text','rich_text':rich('first')}
        p['Follow-up 1 Sent Time']={'date':{'start':'2026-10-26T04:00:00+00:00'}}
        p['Follow-up 2 Draft']=copy.deepcopy(p['Follow-up 1 Draft']);p['Follow-up 2 Review']={'select':{'name':'Approve'}}
        p['Follow-up Review Log']={'type':'rich_text','rich_text':rich(json.dumps({'2':{'state':'Approve','sha256':source_fingerprint(p,self.f.lead['draft']['body'],2)}}))}
        self.f.gmail.message.return_value['id']='first'
        _,_,_,due,_=prepare(self.f.w,self.parent,2)
        self.assertEqual(datetime.fromtimestamp(due,timezone.utc).date().isoformat(),'2026-11-04')
        self.q.db.records['outbox_'+key]['notion_sync_pending']=True
        with self.assertRaises(ValueError):prepare(self.f.w,self.parent,2)

    def test_new_followup_uses_website_without_rewriting_initial_figma_link(self):
        from acquisition_agent.commercial import OUTREACH_PORTFOLIO
        before=copy.deepcopy(self.page['properties']['email body'])
        body=self.f.lead['draft']['body'].replace(self.f.s['profile']['portfolio_url'],OUTREACH_PORTFOLIO)
        p=self.page['properties'];p['Follow-up 1 Draft']={'type':'rich_text','rich_text':rich(body)}
        p['Follow-up Review Log']={'type':'rich_text','rich_text':rich(json.dumps({'1':{'state':'Approve','sha256':source_fingerprint(p,body,1)}}))}
        _,draft,_,_,_=prepare(self.f.w,self.parent,1)
        self.assertIn(OUTREACH_PORTFOLIO,draft['body'])
        self.assertEqual(self.page['properties']['email body'],before)
