import unittest
from datetime import datetime, timezone
from acquisition_agent.scheduling import delivery_zone, permitted_time, notion_timezone, TIMEZONE_OPTIONS


class SchedulingTests(unittest.TestCase):
    def test_dropdown_and_legacy_text(self):
        self.assertEqual(notion_timezone({'type':'select','select':{'name':'Europe/London'}}),'Europe/London')
        self.assertEqual(notion_timezone({'type':'select','select':None}),'')
        self.assertEqual(notion_timezone({'rich_text':[{'plain_text':'Europe/London'}]}),'Europe/London')
        for name in TIMEZONE_OPTIONS:
            from zoneinfo import ZoneInfo
            ZoneInfo(name)
    def setUp(self):
        self.config = {'schedule_basis': 'company', 'timezone': 'Asia/Bangkok',
                       'send_hours': [9, 11], 'send_weekdays': [0, 1, 2, 3, 4]}

    def lead(self, zone):
        return {'company_time_zone': zone, 'company_time_zone_verified': True,
                'company_time_zone_source': 'https://company.example/contact'}

    def clock(self, month, day, hour):
        return datetime(2026, month, day, hour, tzinfo=timezone.utc)

    def test_uk_summer_and_winter(self):
        lead = self.lead('Europe/London')
        self.assertTrue(permitted_time(self.config, self.clock(7, 6, 8), lead))
        self.assertFalse(permitted_time(self.config, self.clock(7, 6, 10), lead))
        self.assertFalse(permitted_time(self.config, self.clock(12, 7, 8), lead))
        self.assertTrue(permitted_time(self.config, self.clock(12, 7, 9), lead))

    def test_us_coasts_differ(self):
        clock = self.clock(10, 19, 14)
        self.assertTrue(permitted_time(self.config, clock, self.lead('America/New_York')))
        self.assertFalse(permitted_time(self.config, clock, self.lead('America/Los_Angeles')))

    def test_weekend_and_end_excluded(self):
        self.assertFalse(permitted_time(self.config, self.clock(10, 18, 9), self.lead('Europe/London')))
        self.assertFalse(permitted_time(self.config, self.clock(10, 19, 10), self.lead('Europe/London')))

    def test_no_country_or_sender_fallback(self):
        for lead in ({'country': 'United States'}, self.lead('USA'), self.lead('America/Invalid')):
            with self.assertRaises(ValueError):
                delivery_zone(self.config, lead)

    def test_evidence_and_review_required(self):
        lead = self.lead('Europe/London')
        lead['company_time_zone_verified'] = False
        with self.assertRaises(ValueError): delivery_zone(self.config, lead)
        lead['company_time_zone_verified'] = True
        lead['company_time_zone_source'] = ''
        with self.assertRaises(ValueError): delivery_zone(self.config, lead)
