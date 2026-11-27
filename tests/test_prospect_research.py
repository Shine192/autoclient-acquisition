"""Research planning stays bounded, official and evidence-only; no live requests."""
import unittest
from unittest.mock import patch
from acquisition_agent.prospect_research import official_links, supporting_pages, ResearchText, RESEARCH_STRATEGY
from acquisition_agent.discovery import research


class ProspectResearchTests(unittest.TestCase):
    def test_links_exclude_external_private_routes_scripts_and_query_actions(self):
        html = '''<a href="/contact-us#team">Contact</a><a href="/services/email-design">Email</a>
        <a href="https://elsewhere.example/contact">External</a><a href="http://studio.example/about">HTTP</a>
        <a href="https://user:pass@studio.example/contact">Credentials</a><a href="/contact?delete=1">Query</a>
        <a href="mailto:person@studio.example">Personal</a><a href="/cdn-cgi/l/email-protection">Protected</a>
        <script><a href="/contact-hidden">Hidden</a></script><a href="/about.pdf">File</a>'''
        self.assertEqual(official_links(html, 'https://studio.example/'),
                         ['https://studio.example/contact-us', 'https://studio.example/services/email-design'])

    def test_actual_contact_and_service_paths_win_with_two_extra_pages(self):
        links = ['https://studio.example/about-us', 'https://studio.example/contact-us',
                 'https://studio.example/services/klaviyo', 'https://studio.example/contact-sales']
        self.assertEqual(supporting_pages('https://studio.example/', links),
                         [links[1], links[2]])

    def test_fallback_is_bounded_and_does_not_repeat_original_page(self):
        self.assertEqual(supporting_pages('https://studio.example/', []),
                         ['https://studio.example/contact', 'https://studio.example/about'])
        self.assertEqual(supporting_pages('https://studio.example/contact', []),
                         ['https://studio.example/about'])

    def test_real_fetch_preserves_visible_text_and_navigation_without_extra_requests(self):
        with patch('acquisition_agent.discovery.fetch_text', side_effect=['', '<p>Published service</p><a href="/contact-us">Contact</a>']) as fetch:
            value = research('https://studio.example/')
        self.assertIsInstance(value, str)
        self.assertIn('Published service', value)
        self.assertEqual(value.links, ('https://studio.example/contact-us',))
        self.assertEqual(fetch.call_count, 2)  # robots + one document

    def test_shared_research_guidance_reaches_manual_and_automatic_paths(self):
        from acquisition_agent.targeting import build_prompt
        from acquisition_agent.automatic import prompt_for
        spec = {'country':'Australia', 'city':'Sydney', 'company_type':'Agency', 'industries':[], 'kind':'Cold Outreach', 'limit':1}
        profile={'portfolio_url':'https://portfolio.example/'}
        self.assertIn(RESEARCH_STRATEGY, build_prompt(spec, profile, {}, {})[1])
        self.assertIn(RESEARCH_STRATEGY, prompt_for(spec, profile, []))
