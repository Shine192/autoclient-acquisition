import unittest
import copy
from unittest.mock import Mock, patch
from acquisition_agent.approval_checks import blockers, message, pricing_issue, offered_design_range, published_work_enquiry
from acquisition_agent.review import sourced_candidate


class ApprovalChecksTests(unittest.TestCase):
    def ir_solutions(self):
        return {'id':'1d9e845f82760645', 'notion_page_id':'3ff35189-9d8d-81c0-85bb-ce1b726db471',
                'url':'https://irsolutions.tech/hire-klaviyo-expert', 'website':'https://irsolutions.tech/',
                'email':'hr@irsolutions.tech', 'kind':'Cold Outreach', 'remote_eligibility':'Unknown',
                'application_route':'Unsolicited freelance work enquiry',
                'draft':{'subject':'Freelance email design and Klaviyo work enquiry',
                         'body':"I'm writing to ask whether you consider remote freelancers. My Figma design rate is USD 25–30 per email."},
                'source_documents':[{'url':'https://irsolutions.tech/contact-us',
                    'text':'For Jobs\n\n[hr@irsolutions.tech](mailto:hr@irsolutions.tech)'}]}

    def test_ir_work_enquiry_keeps_unknown_terms_and_needs_final_approval(self):
        lead=self.ir_solutions();before=copy.deepcopy(lead)
        candidate=sourced_candidate(lead)
        self.assertEqual(candidate['contact_source_url'],'https://irsolutions.tech/contact-us')
        self.assertIn('hr@irsolutions.tech',candidate['email_candidates'])
        self.assertEqual(candidate['kind'],'Cold Outreach')
        self.assertEqual(candidate['remote_eligibility'],'Unknown')
        self.assertFalse(candidate.get('approved'))
        self.assertEqual(pricing_issue(candidate,{'design_rate_usd':[20,30]}),'')
        self.assertEqual(lead,before)

    def test_ir_route_and_price_authorization_cannot_apply_to_another_record(self):
        for key,value in [('id','other'),('notion_page_id','another-page'),('website','https://other.example'),
                          ('email','hr@other.example'),('kind','Posted Job')]:
            with self.subTest(key=key):
                lead=self.ir_solutions();lead[key]=value
                self.assertFalse(published_work_enquiry(lead,lead['source_documents'][0]))
                if value != 'Posted Job':
                    self.assertFalse(sourced_candidate(lead).get('contact_source_url'))
                self.assertTrue(pricing_issue(lead,{'design_rate_usd':[20,30]}))

    def test_hr_is_not_a_general_cold_pitch_route_or_an_unlabelled_contact(self):
        for route,text,url in [('', 'For Jobs\nhr@irsolutions.tech', 'https://irsolutions.tech/contact-us'),
                               ('Business introduction', 'For Jobs\nhr@irsolutions.tech', 'https://irsolutions.tech/contact-us'),
                               ('Unsolicited freelance work enquiry', 'Sales\nhr@irsolutions.tech', 'https://irsolutions.tech/contact-us'),
                               ('Unsolicited freelance work enquiry', 'For Jobs\nhr@irsolutions.tech', 'https://other.example/contact-us')]:
            lead=self.ir_solutions();lead['application_route']=route
            lead['source_documents']=[{'url':url,'text':text}]
            lead.update(contact_source_url='old',email_candidates=['hr@irsolutions.tech'])
            self.assertFalse(sourced_candidate(lead)['contact_source_url'])
            self.assertNotIn('hr@irsolutions.tech',sourced_candidate(lead)['email_candidates'])

    def test_ir_old_and_unselected_higher_quotes_need_review(self):
        for body in ['USD 20–30 per email', 'USD 30–35 per email']:
            lead=self.ir_solutions();lead['draft']['body']=body
            self.assertTrue(pricing_issue(lead,{'design_rate_usd':[20,30]}))

    def test_business_pitch_cannot_reuse_hr_permission_by_keeping_the_route_label(self):
        lead=self.ir_solutions();lead['draft']['body']='I sell marketing services to businesses.'
        self.assertFalse(sourced_candidate(lead)['contact_source_url'])
        lead=self.ir_solutions();lead['draft']['subject']='Applying for your advertised vacancy'
        self.assertFalse(sourced_candidate(lead)['contact_source_url'])

    def test_collects_independent_failures(self):
        lead={'email':'support@example.com','url':'https://example.com','kind':'Posted Job','country':'UAE',
              'draft':{'body':'My Figma design rate is $30-$35 per email.'}}
        config={'mode':'automatic','minimum_fit_score':75,'allowed_kinds':['Posted Job'],
                'require_row_approval':True,'require_confirmed_job_eligibility':True}
        prefs={'design_rate_usd':[20,30],'countries':['UAE']}
        store=Mock();store.paused.return_value=False
        store.db.execute.return_value=[]
        with patch('acquisition_agent.delivery.assess', return_value={'score':65,'status':'Needs Review'}), patch('acquisition_agent.delivery.delivery_zone', side_effect=ValueError('Timezone unverified')), patch('acquisition_agent.delivery.check_draft', side_effect=ValueError('Evidence missing')), patch('acquisition_agent.delivery.suppressed',return_value=False):
            issues=blockers(store,lead,config,{},prefs, {'confirmed':True})
            from acquisition_agent.delivery import gate
            with self.assertRaises(ValueError) as failure:gate(store,lead,config,{},prefs,{'confirmed':True})
        self.assertIn('Approved but blocked:',message(issues))
        self.assertEqual(issues.count('Evidence missing'),1)
        for problem in ('Timezone unverified','Recipient does not match published evidence',
                        'Worldwide/Thailand applicant eligibility unconfirmed',
                        'Job compensation requires review; hourly rates cannot be assumed per-email',
                        'Draft per-email price differs from configured Figma design range; confirm pricing before approval'):
            self.assertIn(problem,issues)
            self.assertIn(problem,str(failure.exception))

    def test_configured_price_and_no_quote_are_allowed(self):
        for body in ['USD 20–30 per email', 'USD 20-30/email','Quote after reviewing scope']:
            self.assertEqual(pricing_issue({'draft':{'body':body}},{'design_rate_usd':[20,30]}),'')

    def test_mismatch_does_not_rewrite_message(self):
        lead={'draft':{'body':'My Figma design rate is $30-$35 per email.'}}
        self.assertTrue(pricing_issue(lead,{'design_rate_usd':[20,30]}))
        self.assertIn('$30-$35',lead['draft']['body'])

    def prism(self):
        return {'id':'fc403920dc3d81fa','notion_page_id':'3ff35189-9d8d-81ac-aa4a-fcb9067b3d56',
                'website':'https://www.prism-me.com/', 'email':'sales@prism-me.com','kind':'Cold Outreach',
                'draft':{'body':'My Figma design rate is $30-$35 per email. Klaviyo building quoted separately.'}}

    def test_explicit_prism_offer_does_not_change_default_or_approve_a_row(self):
        lead=self.prism();before=copy.deepcopy(lead);prefs={'design_rate_usd':[20,30]}
        self.assertEqual(pricing_issue(lead,prefs),'')
        self.assertEqual(offered_design_range(lead,prefs),[30,35])
        self.assertEqual(offered_design_range({},prefs),[20,30])
        self.assertEqual(lead,before);self.assertEqual(prefs,{'design_rate_usd':[20,30]})

    def test_prism_authorization_is_bound_to_opportunity_page_company_and_recipient(self):
        for key,value in [('id','other'),('notion_page_id','another-page'),('website','https://other.example'),
                          ('email','other@prism-me.com'),('kind','Posted Job')]:
            with self.subTest(key=key):
                lead=self.prism();lead[key]=value
                self.assertTrue(pricing_issue(lead,{'design_rate_usd':[20,30]}))

    def test_imported_price_confirmation_cannot_authorize_an_exception(self):
        lead={'draft':{'body':'USD 30–35 per email'},'pricing_approval':{'confirmed':True,'design_rate_usd':[30,35]}}
        self.assertTrue(pricing_issue(lead,{'design_rate_usd':[20,30]}))

    def test_changed_prism_rate_or_a_second_conflicting_quote_stays_blocked(self):
        for body in ['USD 35–40 per email', 'USD 30–35 per email. Or USD 40–50 per email.']:
            lead=self.prism();lead['draft']['body']=body
            self.assertTrue(pricing_issue(lead,{'design_rate_usd':[20,30]}))
