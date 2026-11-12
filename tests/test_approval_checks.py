import unittest
import copy
from unittest.mock import Mock, patch
from acquisition_agent.approval_checks import blockers, message, pricing_issue, offered_design_range


class ApprovalChecksTests(unittest.TestCase):
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
