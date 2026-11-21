import copy,json,unittest
from unittest.mock import patch
from datetime import datetime,timezone
import test_approval_delivery as fixture
from acquisition_agent.simple_workflow import properties,snapshot,automatic_quote,apply_quote,MODE
from acquisition_agent.providers import rich
from hosted_sender.followups import enqueue

class SimpleWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.base=fixture.ApprovalDeliveryTests();self.base.setUp();self.addCleanup(self.base.doCleanups);self.base.enable()
  self.f=self.base.f;self.q=self.f.q;self.page=self.f.page();self.page['properties'].update({k:dict(v,**({'type':'rich_text'} if 'rich_text' in v else {})) for k,v in properties(self.f.lead,self.f.s['profile']).items()})
  def notion(path,method='POST',data=None):
   if method=='PATCH':
    for k,v in data['properties'].items():self.page['properties'][k]=dict(v,**({'type':'rich_text'} if 'rich_text' in v else {}))
   return copy.deepcopy(self.page)
  self.f.notion.request.side_effect=notion
  self.q.db.records['control']['reviewed_followups_enabled']=True
 def send_initial(self):
  item=self.f.w.enqueue(self.f.lead['id']);self.q.db.records['outbox_'+item['id']]['due_at']=self.f.t
  self.f.w.tick(self.f.t)
  self.f.gmail.message.return_value={'id':'gmail1','threadId':'thread1','labelIds':['SENT'],'payload':{'headers':[
   {'name':'Message-ID','value':'<provider@sender.example>'},{'name':'From','value':self.f.s['sending']['sender']},{'name':'To','value':self.f.lead['email']}]}}
  self.f.gmail.send.reset_mock();return item
 def test_one_notion_approval_sends_only_one_followup_after_two_business_days(self):
  item=self.send_initial();enqueue(self.f.w)
  follow=next(i for i in self.q.db.list('outbox') if i.get('stage'))
  self.assertEqual(datetime.fromtimestamp(follow['due_at'],timezone.utc).date().isoformat(),'2026-10-21')
  self.assertEqual(self.page['properties']['Follow-up 1 Review']['select']['name'],'Draft')
  self.f.gmail.send.return_value={'id':'follow1','threadId':'thread1'}
  self.assertEqual(self.f.w.tick(follow['due_at'])['state'],'sent')
  self.assertEqual(self.f.gmail.send.call_count,1);enqueue(self.f.w)
  self.assertEqual(len([i for i in self.q.db.list('outbox') if i.get('stage')]),1)
  self.assertEqual(self.page['properties']['Gmail Message ID']['rich_text'][0]['text']['content'],'gmail1')
 def test_editing_followup_after_approval_holds_initial(self):
  item=self.f.w.enqueue(self.f.lead['id']);self.q.db.records['outbox_'+item['id']]['due_at']=self.f.t
  self.page['properties']['Follow-up 1 Draft']={'type':'rich_text','rich_text':rich('Changed '+self.page['properties']['Follow-up 1 Draft']['rich_text'][0]['text']['content'])}
  self.f.w.tick(self.f.t);self.f.gmail.send.assert_not_called()
 def test_editing_followup_after_initial_send_prevents_followup(self):
  self.send_initial();self.page['properties']['Follow-up 1 Draft']={'type':'rich_text','rich_text':rich('Changed draft')};enqueue(self.f.w)
  self.assertFalse(any(i.get('stage') for i in self.q.db.list('outbox')))
 def test_reply_stops_followup_and_prepares_review_only_reply(self):
  self.send_initial();self.f.gmail.thread.return_value=[{'id':'reply','internalDate':str(int((self.f.t+1)*1000)),'payload':{'headers':[{'name':'From','value':self.f.lead['email']}],'body':{'data':''}}}]
  self.f.w.tick(self.f.t+86400*3);self.f.gmail.send.assert_not_called()
  self.assertEqual(self.page['properties']['Reply Draft Status']['select']['name'],'Needs your review')
  self.assertEqual(self.page['properties']['STATUS']['status']['name'],'Replied')
 def test_holding_sequence_withdraws_followup_permission(self):
  self.send_initial();self.page['properties']['Sequence Mode']={'select':{'name':'Hold'}};enqueue(self.f.w)
  self.assertFalse(any(i.get('stage') for i in self.q.db.list('outbox')))
 def test_unknown_size_never_invents_employee_or_budget(self):
  quote,reason=automatic_quote([{'url':'https://example.com','text':'We serve 100 clients.'}]);self.assertEqual(quote,'USD 25–30/email');self.assertIn('unknown',reason)
  for wording,expected in [('team of 10','USD 25–30/email'),('51-200 employees','USD 30–35/email'),('team of 50','USD 25–30/email')]:
   quote,reason=automatic_quote([{'url':'https://example.com','text':wording}]);self.assertEqual(quote,expected);self.assertIn('Not a confirmed client budget',reason)
 def test_quote_replacement_does_not_change_hourly_compensation(self):
  body='Client budget USD 100 per hour. Figma USD 30–35 per email.'
  result=apply_quote(body,'USD 25–30/email');self.assertIn('USD 100 per hour',result);self.assertIn('USD 25–30 per email',result)
 def test_receipts_and_status_do_not_change_approved_content_snapshot(self):
  p=self.page['properties'];before=snapshot(p);p['STATUS']={'status':{'name':'Sent'}};p['Gmail Message ID']={'rich_text':rich('receipt')};self.assertEqual(snapshot(p),before)

 def test_two_business_days_skip_weekend_and_follow_company_dst(self):
  from acquisition_agent.client_workflow import due_after
  self.assertEqual(due_after('2026-10-30T09:00:00-04:00',2,'America/New_York'),'2026-11-03T08:00:00-05:00')
