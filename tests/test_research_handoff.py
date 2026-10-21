import json
import unittest
from acquisition_agent.providers import rich, text_value
from acquisition_agent.automatic import provider_error


class ResearchHandoffTests(unittest.TestCase):
    def test_long_research_json_roundtrips_without_truncation(self):
        note=json.dumps({'source_documents':[{'url':'https://example.com/','text':'a'*27000}],
                         'personalization_evidence':[{'url':'https://example.com/','quote':'Exact evidence at the end'}]})
        prop={'type':'rich_text','rich_text':rich(note)}
        restored=json.loads(text_value(prop))
        self.assertEqual(len(restored['source_documents'][0]['text']),27000)
        self.assertEqual(restored['personalization_evidence'][0]['quote'],'Exact evidence at the end')

    def test_oversized_research_fails_before_truncating(self):
        with self.assertRaises(ValueError):rich('x'*190001)

    def test_authentication_error_is_actionable_without_provider_body(self):
        message=provider_error(ValueError('HTTP 401 PRIVATE_SECRET_BODY'))
        self.assertIn('401',message);self.assertIn('Replace',message)
        self.assertNotIn('PRIVATE_SECRET_BODY',message)
