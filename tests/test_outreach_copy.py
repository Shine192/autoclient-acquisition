import unittest
from acquisition_agent.outreach_copy import STRATEGY,PAID_TEST,PORTFOLIO_INTRO,observation,refreshed_intro,followup
from acquisition_agent.commercial import OUTREACH_PORTFOLIO
from acquisition_agent.core import draft_prompt
from acquisition_agent.targeting import build_prompt

class OutreachCopyTests(unittest.TestCase):
 def lead(self):
  quote='Klaviyo email marketing for e-commerce brands'
  return {'id':'x','url':'https://example.com','company':'Example','kind':'Cold Outreach','type':'Agency','design_quote':'USD 25–30/email','source_documents':[{'url':'https://example.com','text':quote}], 'draft':{'evidence':[{'url':'https://example.com','quote':quote}]}}
 def test_only_verifiable_relevant_observation_is_used(self):
  lead=self.lead();self.assertIn('website mentions',observation(lead));lead['source_documents'][0]['text']='Different page';self.assertIsNone(observation(lead))
 def test_no_observation_is_invented_when_source_is_missing(self):
  lead=self.lead();lead['draft']['evidence']=[]
  with self.assertRaisesRegex(ValueError,'verified'):refreshed_intro(lead,{})
 def test_work_enquiry_and_posted_application_are_preserved(self):
  for changes in ({'kind':'Posted Job'},{'application_route':'Unsolicited freelance work enquiry'}):
   with self.assertRaises(ValueError):refreshed_intro(dict(self.lead(),**changes),{})
 def test_selected_price_and_one_interest_question(self):
  for quote,range_text in [('USD 25–30/email','USD 25–30'),('USD 30–35/email','USD 30–35')]:
   result=refreshed_intro(dict(self.lead(),design_quote=quote),{'preferred_name':'Shine'})
   self.assertIn(range_text,result['body']);self.assertIn(OUTREACH_PORTFOLIO,result['body']);self.assertIn(PORTFOLIO_INTRO,result['body']);self.assertEqual(result['body'].count(PAID_TEST),1)
   self.assertNotIn('USD 20',result['body']);self.assertNotIn('overloaded',result['body'])
 def test_followup_adds_scope_without_a_date_or_revenue_promise(self):
  body=followup('Example','Shine',OUTREACH_PORTFOLIO)
  self.assertIn('supplied copy',body);self.assertIn('agreed before starting',body);self.assertIn(PORTFOLIO_INTRO,body);self.assertEqual(body.count(PAID_TEST),1);self.assertNotIn('revenue',body)
 def test_shared_strategy_reaches_manual_and_research_prompts(self):
  profile={'portfolio_url':OUTREACH_PORTFOLIO}
  self.assertIn(STRATEGY,draft_prompt(self.lead(),profile,{}))
  spec={'country':'Australia','city':'Sydney','company_type':'Agency','industries':[],'kind':'Cold Outreach','limit':2}
  self.assertIn(STRATEGY,build_prompt(spec,profile,{}, {})[1])

 def test_initial_cold_subject_cannot_fake_a_reply(self):
  from acquisition_agent.core import validate_draft
  lead=self.lead();draft=refreshed_intro(lead,{})
  for subject in ('Re: Your email','Fwd: Earlier discussion'):
   with self.assertRaisesRegex(ValueError,'existing conversation'):validate_draft(dict(draft,lead_id=lead['id'],subject=subject),lead)

 def test_product_observation_is_valid_without_inventing_email_activity(self):
  lead=self.lead();quote='Chocolate Hampers';lead['type']='Brand';lead['draft']['evidence'][0]['quote']=quote;lead['source_documents'][0]['text']=quote
  body=refreshed_intro(lead,{})['body'];self.assertIn(quote,body);self.assertNotIn('your client projects',body)
