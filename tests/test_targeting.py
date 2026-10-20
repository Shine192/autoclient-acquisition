import copy
import tempfile
import unittest
from pathlib import Path
from acquisition_agent.core import Store, read_json, assess, validate_draft, clear_draft_repair
from acquisition_agent.targeting import create_session, import_batch, validate_spec, get_session, INDUSTRIES
from acquisition_agent.providers import lead_properties
from acquisition_agent import delivery

ROOT=Path(__file__).resolve().parent.parent


class TargetSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name);self.addCleanup(self.store.db.close)
        self.prefs=read_json(ROOT/'config/preferences.json');self.profile=read_json(ROOT/'config/profile.json')
        self.exclusions={'confirmed':True,'domains':['growth-horizon.nl'],'emails':[],'companies':['Growth Horizon']}
        self.spec={'country':'United States','city':'New York','company_type':'Brand','industries':['chocolate_snacks_nuts'],'kind':'Cold Outreach','limit':5}
        self.session=create_session(self.store,self.spec,self.prefs,self.profile,self.exclusions)
        self.text='Paper Cocoa sells chocolate gifts online from New York, United States. We are an independent chocolate brand. Contact hello@paper.example.'
        self.raw={'company':'Paper Cocoa','url':'https://paper.example/','website':'https://paper.example/','country':'United States',
                  'location_city':'New York','type':'Brand','industry':'chocolate_snacks_nuts','kind':'Cold Outreach',
                  'title':'Freelance email design introduction','source_text':self.text,
                  'target_evidence':{k:{'url':'https://paper.example/','quote':q} for k,q in [('location','New York, United States'),('company_type','independent chocolate brand'),('industry','chocolate gifts online')]}}
        self.raw['draft']={'subject':'Email designs for Paper Cocoa gifts',
          'body':'Hi Paper Cocoa team, your chocolate gifts could be featured in clear seasonal email designs. I create Figma email layouts and quote Klaviyo building separately. A small paid test could help us explore working together without an ongoing commitment. My portfolio: '+self.profile['portfolio_url'],
          'evidence':[{'url':'https://paper.example/','quote':'Paper Cocoa sells chocolate gifts online'}]}

    def run_import(self, raw=None):
        return import_batch(self.store,self.session,[raw or self.raw],self.prefs,self.profile,self.exclusions)

    def test_session_prompt_contains_exact_profile_and_all_guidance(self):
        self.assertIn(self.profile['portfolio_url'],self.session['prompt'])
        self.assertIn('New York',self.session['queries'][0])
        self.assertIn('Appetizing',self.session['prompt'])
        self.assertIn('not permission to invent',self.session['prompt'])
        self.assertEqual(get_session(self.store,self.session['id'])['spec'],self.spec)
        self.assertTrue(set(['education','fashion','beauty_skincare','saas_software']).issubset(INDUSTRIES))

    def test_dubai_and_expanded_industries_reach_research_prompt(self):
        spec=dict(self.spec,country='United Arab Emirates',city='Dubai',industries=list(INDUSTRIES))
        session=create_session(self.store,spec,self.prefs,self.profile,self.exclusions)
        self.assertEqual(session['spec']['city'],'Dubai')
        self.assertIn('"Dubai" "United Arab Emirates"',session['queries'][0])
        for key in ('beauty_skincare','saas_software','hotels_resorts'):
            self.assertIn(INDUSTRIES[key]['focus'],session['prompt'])
        with self.assertRaises(ValueError):
            validate_spec(dict(spec,industries=['unknown_industry']),self.prefs)

    def test_rejects_unapproved_markets_and_missing_brand_industry(self):
        for changes in ({'country':'Unapproved country'},{'industries':[]},{'city':''},{'limit':21},{'company_type':'Anything'}):
            with self.assertRaises(ValueError):validate_spec(dict(self.spec,**changes),self.prefs)

    def test_uae_city_country_mismatch_is_rejected_before_session_creation(self):
        for city in ('Dubai','Abu Dhabi','Sharjah'):
            with self.assertRaisesRegex(ValueError,'United Arab Emirates'):
                create_session(self.store,dict(self.spec,city=city,country='Australia'),self.prefs,self.profile,self.exclusions)
        spec=validate_spec(dict(self.spec,city='Dubai',country='United Arab Emirates'),self.prefs)
        self.assertEqual(spec['country'],'United Arab Emirates')

    def test_import_brand_without_klaviyo_retains_draft_and_requires_review(self):
        result=self.run_import();self.assertEqual(result['new'],1);self.assertEqual(result['drafts'],1)
        lead=self.store.leads()[0]
        self.assertEqual(lead['status'],'Draft');self.assertEqual(lead['score'],75)
        self.assertEqual(lead['email'],'hello@paper.example');self.assertEqual(lead['target_reasons'],[])
        self.assertIn(self.profile['portfolio_url'],lead['draft']['body'])
        props=lead_properties(lead)
        self.assertFalse(props['Approved']['checkbox']);self.assertFalse(props['Targeting Reviewed']['checkbox'])
        config=read_json(ROOT/'config/sending.json');config['mode']='automatic'
        with self.assertRaisesRegex(ValueError,'Review Summary'):
            delivery.gate(self.store,lead,config,self.profile,self.prefs,self.exclusions)

    def test_city_and_quote_mismatch_stay_held(self):
        raw=copy.deepcopy(self.raw);raw['location_city']='Los Angeles';raw['target_evidence']['industry']['quote']='Invented description never published'
        self.run_import(raw);lead=self.store.leads()[0]
        self.assertEqual(lead['score'],0);self.assertTrue(lead['target_reasons'])
        self.assertIn('Observed company location',str(lead['target_reasons']))

    def test_sourced_eatery_wording_matches_restaurant_industry_without_relaxing_evidence(self):
        from acquisition_agent.targeting import target_check
        lead=copy.deepcopy(self.raw)
        lead.update(industry='restaurants_cafes',target_session={'spec':dict(self.spec,industries=['restaurants_cafes'])})
        text='An independent eatery brand in New York, United States. We operate three eateries.'
        lead['source_documents']=[{'url':lead['url'],'text':text}]
        lead['target_evidence']={k:{'url':lead['url'],'quote':q} for k,q in
            [('location','New York, United States'),('company_type','independent eatery brand'),('industry','operate three eateries')]}
        self.assertEqual(target_check(lead),[])
        lead['target_evidence']['industry']['quote']='Invented eatery text'
        self.assertIn('Missing exact industry evidence',target_check(lead))
        lead['target_evidence']['industry']['quote']='operate three eateries'
        lead['target_session']['spec']['industries']=['chocolate_snacks_nuts']
        self.assertIn('Observed industry does not match session',target_check(lead))

    def test_exact_us_state_postal_quote_matches_full_state_request(self):
        from acquisition_agent.targeting import target_check
        lead=copy.deepcopy(self.raw)
        lead['target_session']={'spec':dict(self.spec,city='California')}
        lead['location_city']='San Diego, California'
        text=self.text+' Office: San Diego, CA.'
        lead['source_documents']=[{'url':lead['url'],'text':text}]
        lead['target_evidence']['location']['quote']='San Diego, CA.'
        self.assertEqual(target_check(lead),[])
        lead['source_documents'][0]['text']=self.text
        self.assertIn('Missing exact location evidence',target_check(lead))

    def test_postal_alias_does_not_expand_other_countries_or_substrings(self):
        from acquisition_agent.targeting import location_quote_matches
        self.assertTrue(location_quote_matches('Office: Albany, NY.',{'country':'United States','city':'New York'}))
        self.assertFalse(location_quote_matches('Office: San Diego, CA.',{'country':'Canada','city':'California'}))
        self.assertFalse(location_quote_matches('CAMERA services office',{'country':'United States','city':'California'}))
        self.assertFalse(location_quote_matches('Office: San Diego, ca.',{'country':'United States','city':'California'}))

    def test_wrong_session_kind_and_exclusion_do_not_import(self):
        raw=dict(self.raw,kind='Posted Job');self.assertTrue(self.run_import(raw)['errors'])
        raw=dict(self.raw,url='https://growth-horizon.nl/',website='https://growth-horizon.nl/')
        self.assertTrue(self.run_import(raw)['errors']);self.assertEqual(self.store.leads(),[])

    def test_invalid_draft_keeps_company_without_unsafe_message(self):
        raw=copy.deepcopy(self.raw)
        raw['draft']['evidence'][0]['quote']='This company has a broken welcome flow'
        result=self.run_import(raw)
        self.assertEqual(result['new'],1)
        self.assertEqual(result['drafts'],0)
        self.assertEqual(result['drafts_rejected'],1)
        self.assertTrue(result['errors'][0]['company_saved'])
        lead=self.store.leads()[0]
        self.assertEqual(lead['status'],'Needs Review')
        self.assertNotIn('draft',lead)
        self.assertTrue(lead['draft_error'])
        self.assertTrue(Path(lead['prompt_file']).is_file())
        props=lead_properties(lead)
        self.assertFalse(props['Approved']['checkbox'])
        self.assertNotIn('email body',props)
        self.assertIn('Draft needs repair',str(props['Error']))
        self.assertEqual(self.run_import(raw)['duplicates'],1)
        self.assertEqual(len(self.store.leads()),1)

    def test_corrected_draft_clears_only_import_diagnostics(self):
        raw=copy.deepcopy(self.raw)
        raw['draft']['evidence'][0]['quote']='This company has a broken welcome flow'
        self.run_import(raw)
        lead=self.store.leads()[0]
        corrected=validate_draft(dict(self.raw['draft'],lead_id=lead['id']),lead,self.profile)
        clear_draft_repair(lead)
        lead.update(draft=corrected,status='Draft',draft_dirty=True)
        self.assertNotIn('draft_error',lead)
        self.assertNotIn('error',lead)
        self.assertTrue(lead['draft_repaired'])
        self.assertFalse(any(r.startswith('Draft withheld: ') for r in lead['reasons']))
        self.assertIn(self.profile['portfolio_url'],lead['draft']['body'])

    def test_missing_portfolio_keeps_only_company_research(self):
        raw=copy.deepcopy(self.raw)
        raw['draft']['body']='This body is long enough but has no required portfolio link. Please contact me for design support.'
        result=self.run_import(raw)
        self.assertEqual(result['new'],1)
        self.assertEqual(result['drafts_rejected'],1)
        self.assertNotIn('draft',self.store.leads()[0])

    def test_missing_evidence_page_has_specific_error(self):
        raw=copy.deepcopy(self.raw)
        raw['draft']['evidence'][0]['url']='https://paper.example/missing-page'
        result=self.run_import(raw)
        self.assertEqual(result['new'],1)
        self.assertIn('Evidence URL is outside',result['errors'][0]['error'])

    def test_batch_preserves_valid_and_repairable_companies(self):
        raw=copy.deepcopy(self.raw)
        raw['url']=raw['website']='https://second.example/'
        raw['draft']['evidence'][0]['quote']='Unsupported company observation'
        result=import_batch(self.store,self.session,[self.raw,raw],self.prefs,self.profile,self.exclusions)
        self.assertEqual(result['new'],2)
        self.assertEqual(result['drafts'],1)
        self.assertEqual(result['drafts_rejected'],1)
        self.assertEqual(len(self.store.leads()),2)

    def test_duplicates_preserve_prior_sent_record(self):
        self.run_import();lead=self.store.leads()[0];lead['status']='Sent';self.store.save(lead)
        result=self.run_import();self.assertEqual(result['duplicates'],1)
        self.assertEqual(self.store.leads()[0]['status'],'Sent')

    def test_nonofficial_documents_and_malformed_evidence_rejected(self):
        raw=dict(self.raw,source_documents=[{'url':'https://directory.example/','text':self.text}])
        self.assertTrue(self.run_import(raw)['errors'])
        raw=dict(self.raw,target_evidence={'location':[]})
        self.assertTrue(self.run_import(raw)['errors']);self.assertEqual(self.store.leads(),[])

    def test_no_matches_is_a_valid_completed_research_result(self):
        result=import_batch(self.store,self.session,[],self.prefs,self.profile,self.exclusions)
        self.assertEqual(result['new'],0);self.assertEqual(result['errors'],[])
        self.assertEqual(self.store.leads(),[])
