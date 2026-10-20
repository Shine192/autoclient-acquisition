import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from acquisition_agent.discovery import source_config, discover

class SourcesTests(unittest.TestCase):
    def config(self,root,value):
        (Path(root)/'config').mkdir(exist_ok=True)
        (Path(root)/'config/discovery.json').write_text(json.dumps(value))

    def test_additive_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            original={'rss_feeds':['https://a.test/feed'],'weekly_capacity_hours':20}
            self.config(root,{'rss_feeds':['https://a.test/feed','https://b.test/feed']})
            result=source_config(original,root)
            self.assertEqual(len(result['rss_feeds']),2)
            self.assertEqual(result['weekly_capacity_hours'],20)
            self.assertEqual(len(original['rss_feeds']),1)

    def test_invalid_kind_and_cross_host(self):
        with tempfile.TemporaryDirectory() as root:
            for entry in ({'url':'https://a.test','kind':'Guess'}, {'url':'https://a.test','kind':'Cold Outreach','research_urls':['https://b.test']}):
                self.config(root,{'watchlist':[entry]})
                with self.assertRaises(ValueError): source_config({},root)

    def test_cold_discovery_separate_evidence_and_pause(self):
        entry={'url':'https://studio.test','company':'Studio','title':'Email design support','kind':'Cold Outreach','research_urls':['https://studio.test/contact']}
        cfg={'watchlist':[entry],'rss_feeds':[],'max_candidates_per_session':20,'countries':['Australia']}
        with patch('acquisition_agent.discovery.research',side_effect=['Klaviyo email design agency based in Australia','Published contact: hello@studio.test']):
            items,errors=discover(cfg,kind='cold')
        self.assertFalse(errors)
        self.assertEqual(items[0]['kind'],'Cold Outreach')
        self.assertEqual(len(items[0]['source_documents']),2)
        self.assertIn('no vacancy',items[0]['research_warning'])
        with patch('acquisition_agent.discovery.research') as fetch:
            self.assertEqual(discover(cfg,kind='cold',keep_running=lambda:False)[0],[])
            fetch.assert_not_called()

    def test_watchlist_failure_never_becomes_fake_lead(self):
        cfg={'watchlist':[{'url':'https://a.test','kind':'Cold Outreach'}],'rss_feeds':[],'max_candidates_per_session':20}
        with patch('acquisition_agent.discovery.research',side_effect=ValueError('blocked')):
            items,errors=discover(cfg,kind='cold')
        self.assertEqual(items,[])
        self.assertEqual(errors[0]['error'],'blocked')

    def test_excluded_company_not_fetched(self):
        cfg={'watchlist':[{'url':'https://growth-horizon.nl','company':'Growth Horizon','kind':'Cold Outreach'}],'rss_feeds':[], 'max_candidates_per_session':20, '_exclusions':{'companies':[],'domains':['growth-horizon.nl'],'emails':[]}}
        with patch('acquisition_agent.discovery.research') as fetch:
            self.assertEqual(discover(cfg,kind='cold')[0],[])
            fetch.assert_not_called()
