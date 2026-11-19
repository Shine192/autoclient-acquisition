import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock
from acquisition_agent.core import Store, prepare_lead, draft_prompt, validate_draft
from acquisition_agent.providers import rich, lead_properties
from acquisition_agent.commercial import DEFAULT_QUOTE, CURATED_PORTFOLIO, quote_instruction, region_for, audience_instruction, agency_context, agency_issue, profile_for_lead
from acquisition_agent.approval_checks import pricing_issue, offered_design_range
from acquisition_agent.client_workflow import ClientWorkflow, record, summary, due_after, schema
from acquisition_agent.targeting import build_prompt


def prop(value):return {'type':'rich_text','rich_text':rich(value)}


def page():
    notes={'source_documents':[{'url':'https://studio.example','text':'Sample studio offers email marketing for e-commerce clients.'}],
           'personalization_evidence':[{'url':'https://studio.example','quote':'studio offers email marketing'}]}
    return {'id':'owned-page','properties':{'Name':{'title':rich('Sample studio')},
        'Deduplication Key':prop('abcdabcdabcdabcd'),'STATUS':{'status':{'name':'Needs Review'}},
        'COUNTRY':prop('AUSTRALIA'),'Target City':prop('Sydney'),'Type':{'select':{'name':'Agency'}},
        'Opportunity Type':{'select':{'name':'Cold Outreach'}},'Match Score':{'number':75},
        'Research Check':{'select':{'name':'Ready for review'}},'EMAIL':{'email':'hello@studio.example'},
        'WEBSITE':{'url':'https://studio.example'},'Job URL':{'url':'https://studio.example'},
        'Contact Source URL':{'url':'https://studio.example/contact'},'Research Notes':prop(json.dumps(notes)),
        'email SUBJECT':prop('Email design support'),'email body':prop('Initial reviewed body'),
        'Company Time Zone':{'select':{'name':'Australia/Sydney'}}}}


class FakeNotion:
    def __init__(self):self.page=page();self.writes=[]
    def query(self,source):return [copy.deepcopy(self.page)]
    def request(self,path,method='GET',data=None):
        if method=='GET':return copy.deepcopy(self.page)
        if method!='PATCH':raise AssertionError('Unexpected operation')
        self.writes.append(copy.deepcopy(data))
        for key,value in data['properties'].items():
            if 'rich_text' in value:value={'type':'rich_text',**value}
            self.page['properties'][key]=value
        return copy.deepcopy(self.page)


class CommercialTests(unittest.TestCase):
    def test_new_portfolio_is_per_prospect_and_old_profile_is_not_rewritten(self):
        profile={'portfolio_url':'https://old-portfolio.example'}
        self.assertEqual(profile_for_lead({},profile),profile)
        self.assertEqual(profile_for_lead({'portfolio_url':CURATED_PORTFOLIO},profile)['portfolio_url'],CURATED_PORTFOLIO)
        self.assertEqual(profile['portfolio_url'],'https://old-portfolio.example')
        with self.assertRaisesRegex(ValueError,'owner-confirmed'):profile_for_lead({'portfolio_url':'https://unapproved.example'},profile)

    def test_focused_agencies_need_official_service_fit_not_invented_hiring_intent(self):
        lead={'url':'https://studio.example','source_documents':[{'url':'https://studio.example/services',
            'text':'Our agency offers Klaviyo email marketing for Shopify e-commerce clients.'}],
            'target_session':{'spec':{'agency_focus':True}}}
        facts=agency_context(lead,{'business_signal':{'url':'https://studio.example/services','quote':'We are hiring now','published_at':'2026-11-01'},'employees':15})
        self.assertTrue(facts['ecommerce_fit_verified']);self.assertIsNone(facts['employees'])
        self.assertIn('No dated hiring',facts['business_signal']['interpretation'])
        self.assertEqual(agency_issue(lead),'')
        lead['source_documents'][0]['url']='https://unrelated.example'
        self.assertTrue(agency_issue(lead))

    def test_observed_business_context_is_not_a_fabricated_published_date(self):
        lead={'url':'https://studio.example','source_documents':[{'url':'https://studio.example','text':'We offer email marketing for e-commerce brands.'}]}
        facts=agency_context(lead,{'business_signal':{'url':lead['url'],'quote':'We offer email marketing for e-commerce brands.','published_at':'2026-11-01'}})
        self.assertIsNone(facts['business_signal']['published_at'])
        self.assertIn('unconfirmed',facts['business_signal']['interpretation'])
    def test_quote_selection_is_separate_from_client_budget_and_legacy_quotes(self):
        lead={'design_quote':DEFAULT_QUOTE,'rate_per_email':99,'currency':'USD','draft':{'body':'USD 25–30 per email'}}
        self.assertEqual(offered_design_range(lead,{'design_rate_usd':[20,30]}),[25,30])
        self.assertEqual(lead['rate_per_email'],99)
        self.assertFalse(pricing_issue(lead,{'design_rate_usd':[20,30]}))
        lead['design_quote']='USD 30–35/email'
        self.assertTrue(pricing_issue(lead,{'design_rate_usd':[20,30]}))
        self.assertEqual(offered_design_range({}, {'design_rate_usd':[20,30]}),[20,30])

    def test_missing_new_quote_and_unsupported_quotes_fail_closed(self):
        self.assertTrue(pricing_issue({'quote_schema_version':1,'draft':{'body':'USD 20–30/email'}},{'design_rate_usd':[20,30]}))
        self.assertTrue(pricing_issue({'design_quote':'USD 1–2/email'}, {'design_rate_usd':[20,30]}))

    def test_drafting_prompts_replace_stale_profile_prices_and_agency_intent_is_explicit(self):
        profile={'portfolio_url':'https://portfolio.example','design_pricing':'USD 20–30/email'}
        spec={'country':'Australia','city':'Sydney','company_type':'Agency','industries':[],'kind':'Cold Outreach','limit':5,'agency_focus':True,'design_quote':'USD 30–35/email'}
        prompt=build_prompt(spec,profile,{}, {})[1]
        self.assertIn('USD 30–35 per email',prompt);self.assertNotIn('USD 20–30',prompt)
        self.assertIn('2–50 employees is a preference',prompt);self.assertIn('not a current need',prompt)
        lead=prepare_lead({'url':'https://studio.example','source_text':'Studio sells email marketing'})
        lead['design_quote']=DEFAULT_QUOTE
        prompt=draft_prompt(lead,profile,{})
        self.assertIn('USD 25–30 per email',prompt);self.assertNotIn('USD 20–30',prompt)
        self.assertEqual(profile['design_pricing'],'USD 20–30/email')

    def test_client_names_are_allowed_in_portfolio_but_blocked_in_email(self):
        lead={'id':'a','url':'https://studio.example','source_documents':[{'url':'https://studio.example','text':'A sample studio offers email design.'}]}
        draft={'lead_id':'a','subject':'Freelance support','body':'I worked on Happy Dog designs. '+'Sample text '*10,
               'evidence':[{'url':lead['url'],'quote':'sample studio offers email design'}]}
        with self.assertRaisesRegex(ValueError,'portfolio client names'):validate_draft(draft,lead)

    def test_regions_use_actual_country_and_dubai_city(self):
        for country,city,expected in [('AUSTRALIA','Sydney','Australia'),('UNITED_KINGDOM','London','UK'),
                ('UAE','Al Mankhool, Dubai','Dubai'),('UAE','Abu Dhabi','Other markets'),
                ('NETHERLANDS','Amsterdam','EU'),('Norway','Oslo','Other markets')]:
            self.assertEqual(region_for(country,city),expected)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name);self.addCleanup(self.store.db.close)
        self.n=FakeNotion();self.profile={'portfolio_url':'https://portfolio.example','email_signature':'Shine'}
        self.w=ClientWorkflow(self.store,self.n,'owned-source',self.profile)

    def action(self,action,**values):return self.w.action({'action':action,'page_id':'owned-page',**values})
    def sent(self):
        p=self.n.page['properties'];p.update({'STATUS':{'status':{'name':'Sent'}},'Gmail Message ID':prop('gmail-receipt-123'),
            'Gmail Thread ID':prop('thread-123'),'sent time':{'date':{'start':'2026-11-05T09:00:00+11:00'}}})

    def test_quote_changes_preserve_body_and_do_not_approve_or_send(self):
        before=copy.deepcopy(self.n.page['properties']['email body'])
        result=self.action('quote',quote='USD 30–35/email')
        self.assertEqual(self.n.page['properties']['email body'],before)
        self.assertEqual(result['rows'][0]['status'],'Needs Review')
        self.assertFalse(result['automatic_followups_enabled'])
        for status in ('Approve','Scheduled','Sent','Sending','Replied'):
            self.n.page['properties']['STATUS']={'status':{'name':status}}
            with self.assertRaisesRegex(ValueError,'Preserve'):self.action('quote',quote=DEFAULT_QUOTE)

    def test_enrollment_requires_evidence_and_is_idempotent(self):
        result=self.action('enroll');self.assertEqual(result['summary']['qualified_enrolled'],1)
        result=self.action('enroll');self.assertEqual(result['summary']['qualified_enrolled'],1)
        self.n.page['properties']['Match Score']={'number':65}
        with self.assertRaisesRegex(ValueError,'Complete agency'):self.action('enroll')

    def test_enrollment_requires_email_and_ecommerce_service_fit_not_only_agency_type(self):
        p=self.n.page['properties']
        for source in ('We offer website design.', 'We offer email marketing.', 'We offer Shopify website design.'):
            p['Research Notes']=prop(json.dumps({'source_documents':[{'url':'https://studio.example','text':source}]}))
            self.assertFalse(record(self.n.page)['qualified'])
            with self.assertRaisesRegex(ValueError,'Complete agency'):self.action('enroll')
        p['Research Notes']=prop(json.dumps({'source_documents':[{'url':'https://unrelated.example','text':'Email marketing for e-commerce.'}]}))
        self.assertFalse(record(self.n.page)['qualified'])

    def test_legacy_human_notes_remain_visible_without_qualifying_as_source_evidence(self):
        self.n.page['properties']['Research Notes']=prop('Historical research note written by the owner.')
        before=copy.deepcopy(self.n.page)
        result=self.w.refresh()
        self.assertEqual(len(result['rows']),1)
        self.assertFalse(result['rows'][0]['qualified'])
        self.assertEqual(self.n.page,before)
        self.assertFalse(self.n.writes)

    def test_followup_review_waits_for_receipt_and_never_creates_an_outbox(self):
        self.action('followup_draft',stage=1)
        with self.assertRaisesRegex(ValueError,'initial saved receipt'):self.action('followup_review',stage=1)
        self.sent();result=self.action('followup_review',stage=1)
        self.assertEqual(result['rows'][0]['followups'][0]['review'],'Reviewed')
        tables={r[0] for r in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('outbox',tables)

    def test_review_is_invalidated_by_body_source_quote_or_timezone_change(self):
        self.sent();self.action('followup_draft',stage=1);self.action('followup_review',stage=1)
        p=self.n.page['properties'];snapshot=copy.deepcopy(p)
        for key,value in [('Follow-up 1 Draft',prop('Changed draft')),('email body',prop('Changed initial message')),
                         ('Design Quote',{'select':{'name':'USD 30–35/email'}}),('Company Time Zone',{'select':{'name':'Europe/London'}})]:
            self.n.page['properties']=copy.deepcopy(snapshot);self.n.page['properties'][key]=value
            self.assertEqual(record(self.n.page)['followups'][0]['review'],'Needs review')

    def test_reply_suppression_and_uncertain_delivery_cancel_reviews(self):
        self.sent();self.action('followup_draft',stage=1)
        before=copy.deepcopy(self.n.page['properties'])
        for key,value in [('Reply Status',prop('Relevant reply')),('Do Not Contact',{'checkbox':True}),('Delivery State',prop('Uncertain delivery'))]:
            self.n.page['properties']=copy.deepcopy(before);self.n.page['properties'][key]=value
            self.assertEqual(record(self.n.page)['followups'][0]['review'],'Cancelled')
            with self.assertRaisesRegex(ValueError,'holds follow-ups'):self.action('followup_review',stage=1)

    def test_second_followup_waits_for_first_actual_receipt(self):
        self.sent();self.action('followup_draft',stage=2)
        with self.assertRaisesRegex(ValueError,'first follow-up receipt'):self.action('followup_review',stage=2)

    def test_new_outcomes_require_order_receipt_and_nonautomated_reply(self):
        with self.assertRaisesRegex(ValueError,'receipt'):self.action('result',outcome='Positive reply',reply_classification='Positive',request_id='request-1')
        self.sent()
        with self.assertRaisesRegex(ValueError,'sequence'):self.action('result',outcome='Paid test completed',request_id='request-2')
        with self.assertRaisesRegex(ValueError,'genuine positive'):self.action('result',outcome='Positive reply',reply_classification='Automated',request_id='request-3')
        self.action('result',outcome='Positive reply',reply_classification='Positive',minutes=10,request_id='request-4')
        self.action('result',outcome='Positive reply',reply_classification='Positive',minutes=10,request_id='request-4')
        self.assertEqual(record(self.n.page)['minutes'],10)
        self.action('result',outcome='Paid test agreed',request_id='request-5')
        self.action('result',outcome='Paid test completed',request_id='request-6')
        self.action('result',outcome='Repeat client',request_id='request-7')
        r=record(self.n.page);r['enrolled']=True;metrics=summary([r])
        self.assertEqual(metrics['repeat_client_rate_percent'],100)
        self.assertEqual(metrics['Paid test agreed'],1)

    def test_future_outcomes_and_changed_manual_followup_receipts_are_rejected(self):
        self.sent()
        with self.assertRaisesRegex(ValueError,'actual outcome'):self.action('result',outcome='Positive reply',reply_classification='Positive',outcome_at='2099-01-01T00:00:00+00:00',request_id='future-date')
        self.action('followup_draft',stage=1);self.action('followup_review',stage=1)
        with self.assertRaisesRegex(ValueError,'exact reviewed'):self.action('followup_record_sent',stage=1,body='Changed message https://portfolio.example '+'words '*25,receipt='manual-receipt',sent_time='2026-11-12T00:00:00+00:00')

    def test_outcomes_cannot_precede_the_original_outreach(self):
        self.sent()
        with self.assertRaisesRegex(ValueError,'precede the initial'):
            self.action('result',outcome='Positive reply',reply_classification='Positive',outcome_at='2026-01-01T00:00:00+00:00',request_id='past-date')

    def test_manual_followup_receipts_are_unique_and_ordered(self):
        self.sent();self.action('followup_draft',stage=1);self.action('followup_review',stage=1)
        with self.assertRaisesRegex(ValueError,'already belongs'):
            self.action('followup_record_sent',stage=1,receipt='gmail-receipt-123',sent_time='2026-11-10T00:00:00+00:00')
        self.action('followup_record_sent',stage=1,receipt='first-followup-receipt',sent_time='2026-11-10T00:00:00+00:00')
        self.action('followup_draft',stage=2);self.action('followup_review',stage=2)
        with self.assertRaisesRegex(ValueError,'precede the first'):
            self.action('followup_record_sent',stage=2,receipt='second-followup-receipt',sent_time='2026-11-09T00:00:00+00:00')
        with self.assertRaisesRegex(ValueError,'already belongs'):
            self.action('followup_record_sent',stage=2,receipt='first-followup-receipt',sent_time='2026-11-17T00:00:00+00:00')
        result=self.action('followup_record_sent',stage=2,receipt='second-followup-receipt',sent_time='2026-11-17T00:00:00+00:00')
        self.assertEqual(result['rows'][0]['followups'][1]['review'],'Sent manually')

    def test_automated_responses_and_missing_denominators_do_not_inflate_results(self):
        r=record(self.n.page);r.update(enrolled=True,initial_sent=True,reply_classification='Automated',events=[])
        self.assertEqual(summary([r])['Positive reply'],0)
        self.assertIsNone(summary([])['paid_test_agreement_rate_percent'])

    def test_no_send_action_or_writes_outside_tracker(self):
        with self.assertRaisesRegex(ValueError,'no sending'):self.action('send')
        self.n.query=lambda source:[]
        with self.assertRaisesRegex(ValueError,'outside'):self.action('quote',quote=DEFAULT_QUOTE)
        self.assertEqual(self.n.writes,[])

    def test_business_day_dates_skip_weekends_and_respect_dst(self):
        self.assertEqual(due_after('2026-10-30T09:00:00-04:00',5,'America/New_York'),'2026-11-06T08:00:00-05:00')
        self.assertIsNone(due_after(None,5,'Europe/London'))
        with self.assertRaisesRegex(ValueError,'timezone'):due_after('2026-11-01T09:00:00',5,'Europe/London')
