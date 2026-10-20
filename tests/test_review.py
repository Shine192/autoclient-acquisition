import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from acquisition_agent.core import Store, read_json, prepare_lead, assess
from acquisition_agent.targeting import city_matches, target_check
from acquisition_agent import review, delivery
from acquisition_agent.providers import rich

ROOT=Path(__file__).resolve().parent.parent


class SingleReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name);self.addCleanup(self.store.db.close)
        self.profile=read_json(ROOT/'config/profile.json')
        self.prefs=read_json(ROOT/'config/preferences.json')
        self.exclusions={'confirmed':True,'companies':[],'domains':[],'emails':[]}
        self.config=read_json(ROOT/'config/sending.json')
        self.config.update(mode='automatic',schedule_basis='company',business_postal_address='Test business address',send_hours=[9,11],send_weekdays=[0,1,2,3,4],allow_unknown_cold_budget=True)
        text='Paper Cocoa is an independent chocolate brand, located in Dubai, United Arab Emirates. Contact office@paper.example for business enquiries.'
        self.lead=prepare_lead({'url':'https://paper.example/','website':'https://paper.example/','company':'Paper Cocoa','kind':'Cold Outreach','type':'Brand','country':'United Arab Emirates','source_text':text})
        self.lead.update(notion_page_id='page',status='Draft',location_city='Al Quoz 3, Dubai',industry='chocolate_snacks_nuts',target_session={'id':'session','spec':{'country':'United Arab Emirates','city':'Dubai','company_type':'Brand','industries':['chocolate_snacks_nuts'],'kind':'Cold Outreach','limit':5}},target_evidence={k:{'url':'https://paper.example/','quote':q} for k,q in [('location','located in Dubai, United Arab Emirates'),('company_type','independent chocolate brand'),('industry','chocolate brand')]})
        self.lead['draft']={'subject':'Email design for Paper Cocoa','body':'Hi Paper Cocoa team, I create Figma email designs for e-commerce brands. Your chocolate could feature in clear product campaigns. Klaviyo building is quoted separately. Would a small paid test help? Portfolio: '+self.profile['portfolio_url'],'evidence':[{'url':'https://paper.example/','quote':'independent chocolate brand'}]}
        self.store.add(self.lead)

    def evaluate(self, lead=None):
        return review.evaluate(self.store,lead or self.lead,self.config,self.profile,self.prefs,self.exclusions)

    def notion(self, lead=None):
        lead=lead or self.lead
        n=Mock();n.request.return_value={'id':'page','properties':{
            'STATUS':{'status':{'name':lead['status']}},'EMAIL':{'email':lead.get('email','')},
            'email SUBJECT':{'type':'rich_text','rich_text':rich(lead['draft']['subject'])},
            'email body':{'type':'rich_text','rich_text':rich(lead['draft']['body'])}}}
        return n

    def approve(self, notion, token, confirmed=True):
        return review.approve(self.store,notion,self.lead,self.config,self.profile,self.prefs,self.exclusions,token,confirmed)

    def test_address_components_match_without_substring_false_positives(self):
        for city in ('Dubai','Al Quoz 3, Dubai','Dubai — Alserkal Avenue','Dubai Design District, Dubai'):
            self.assertTrue(city_matches(city,'Dubai'))
        for city,query in [('New York','York'),('Dubai Hills','Dubai'),('Yorkshire','York'),('Dubai','London')]:
            self.assertFalse(city_matches(city,query))
        self.assertEqual(target_check(self.lead),[])

    def test_stale_cached_target_error_does_not_keep_score_zero(self):
        self.lead['target_reasons']=['Observed company location does not match session']
        self.assertEqual(assess(self.lead,self.prefs,self.exclusions)['score'],70)

    def test_review_derives_published_inbox_and_sourced_timezone_without_mutating(self):
        before=copy.deepcopy(self.lead)
        candidate,r=self.evaluate()
        self.assertTrue(r['can_approve'],r['blockers'])
        self.assertEqual(candidate['email'],'office@paper.example')
        self.assertEqual(candidate['company_time_zone'],'Asia/Dubai')
        self.assertTrue(candidate['company_time_zone_verified'])
        self.assertTrue(r['setup_blockers'])  # No policy silently authorized.
        self.assertEqual(before,self.lead)
        self.assertEqual(self.store.get(self.lead['id'])['status'],'Draft')

    def test_agency_without_brand_industry_derives_sourced_california_zone(self):
        lead=copy.deepcopy(self.lead)
        text='Sample agency offers email creative and Klaviyo services in San Diego, CA. Contact hello@paper.example.'
        lead.update(country='United States',type='Agency',industry='',location_city='San Diego, California',source_text=text,
                    source_documents=[{'url':lead['url'],'text':text}],
                    target_session={'id':'session','spec':{'country':'United States','city':'California','company_type':'Agency','industries':[],'kind':'Cold Outreach','limit':5}},
                    target_evidence={'location':{'url':lead['url'],'quote':'San Diego, CA.'},'company_type':{'url':lead['url'],'quote':'agency offers email creative'}})
        before=copy.deepcopy(lead);candidate=review.sourced_candidate(lead)
        self.assertEqual(candidate['company_time_zone'],'America/Los_Angeles')
        self.assertTrue(candidate['company_time_zone_verified'])
        self.assertEqual(candidate['target_reasons'],[])
        self.assertEqual(lead,before)

    def test_one_decision_updates_all_review_fields_without_queueing_or_sending(self):
        n=self.notion();current=delivery.remote_lead(self.store,n,copy.deepcopy(self.lead),persist=False)
        _,r=self.evaluate(current)
        result=self.approve(n,r['token'])
        self.assertTrue(result['approved'])
        props=n.request.call_args.args[2]['properties']
        self.assertEqual(props['STATUS']['status']['name'],'Ready')
        self.assertTrue(props['Approved']['checkbox'])
        for key in review.NOTION_FLAGS:self.assertTrue(props[key]['checkbox'])
        self.assertEqual(props['EMAIL']['email'],'office@paper.example')
        self.assertEqual(delivery.rows(self.store),[])
        self.assertEqual(self.store.get(self.lead['id'])['status'],'Ready')

    def test_confirmation_and_stale_message_are_rejected_before_patch(self):
        n=self.notion();current=delivery.remote_lead(self.store,n,copy.deepcopy(self.lead),persist=False)
        _,r=self.evaluate(current)
        with self.assertRaisesRegex(ValueError,'Review the recipient'):self.approve(n,r['token'],False)
        n.request.return_value['properties']['email body']={'type':'rich_text','rich_text':rich(self.lead['draft']['body']+' Changed.')}
        with self.assertRaisesRegex(ValueError,'changed'):self.approve(n,r['token'])
        self.assertFalse(any(c.args[1:2]==('PATCH',) for c in n.request.call_args_list))

    def test_missing_research_and_support_only_inbox_stay_held(self):
        lead=copy.deepcopy(self.lead);lead['target_evidence']['location']['quote']='Unpublished office location in Dubai'
        _,r=self.evaluate(lead);self.assertFalse(r['can_approve'])
        lead=copy.deepcopy(self.lead)
        lead['source_documents'][0]['text']=lead['source_documents'][0]['text'].replace('office@paper.example','support@paper.example')
        lead['email']='support@paper.example';lead['email_candidates']=['support@paper.example']
        _,r=self.evaluate(lead);self.assertFalse(r['can_approve'])
        self.assertIn('official source',' '.join(r['blockers']))

    def test_excluded_company_or_uncertain_delivery_cannot_be_approved(self):
        self.exclusions['domains']=['paper.example'];_,r=self.evaluate();self.assertFalse(r['can_approve'])
        self.exclusions['domains']=[];delivery.init(self.store)
        self.store.db.execute("INSERT INTO outbox(id,lead_id,stage,mode,state,recipient,company,payload,message_id,created_at,due_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",('uncertain',self.lead['id'],0,'automatic','uncertain','office@paper.example','paper.example','{}','message','2026-10-18','2026-10-19'));self.store.db.commit()
        _,r=self.evaluate();self.assertFalse(r['can_approve'])

    def test_notion_write_failure_leaves_local_record_unapproved(self):
        n=self.notion();current=delivery.remote_lead(self.store,n,copy.deepcopy(self.lead),persist=False)
        _,r=self.evaluate(current)
        n.request.side_effect=lambda path,method,*args: (_ for _ in ()).throw(ValueError('network failed')) if method=='PATCH' else n.request.return_value
        with self.assertRaisesRegex(ValueError,'network failed'):self.approve(n,r['token'])
        self.assertFalse(self.store.get(self.lead['id'])['approved'])
        self.assertEqual(delivery.rows(self.store),[])

    def test_remote_sent_status_stops_approval(self):
        n=self.notion();n.request.return_value['properties']['STATUS']={'status':{'name':'Sent'}}
        current=delivery.remote_lead(self.store,n,copy.deepcopy(self.lead),persist=False)
        _,r=self.evaluate(current)
        self.assertFalse(r['can_approve'])
        with self.assertRaisesRegex(ValueError,'Approval held'):self.approve(n,r['token'])
        self.assertFalse(any(c.args[1:2]==('PATCH',) for c in n.request.call_args_list))

    def test_approved_row_does_not_need_repeated_confirmation(self):
        candidate,_=self.evaluate()
        _,r=self.evaluate(candidate)
        self.assertTrue(r['already_approved'])
        self.assertFalse(r['can_approve'])

    def test_literal_industry_evidence_can_be_recovered_without_inventing_text(self):
        lead=copy.deepcopy(self.lead)
        lead['target_evidence']['industry']['quote']='Unsupplied and unsupported chocolate claim'
        candidate,r=self.evaluate(lead)
        self.assertTrue(r['can_approve'],r['blockers'])
        item=candidate['target_evidence']['industry']
        self.assertIn(item['quote'],lead['source_text'])
        self.assertEqual(item['url'],lead['url'])

    def test_dubai_window_rolls_weekend_to_monday(self):
        candidate,_=self.evaluate()
        due=review.next_window(self.config,candidate,datetime(2026,10,18,16,tzinfo=timezone.utc))
        self.assertEqual(due,'2026-10-19T05:00:00+00:00')


if __name__=='__main__':unittest.main()
