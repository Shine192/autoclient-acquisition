"""Campaign bounds and actual delivery integration using fake provider boundaries."""
import copy
import json
import tempfile
import threading
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import test_delivery
from acquisition_agent import campaigns as c, delivery as d
from acquisition_agent.core import Store,prepare_lead,read_json,write_json,validate_draft
from acquisition_agent.signature import SIGNATURE,with_signature,with_footer
from acquisition_agent.scheduling import permitted_time

ROOT=Path(__file__).resolve().parent.parent

class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name);self.addCleanup(self.store.db.close);d.init(self.store)

    def seed(self,key,campaign=''):
        self.store.db.execute('INSERT INTO outbox(id,lead_id,stage,mode,state,recipient,company,payload,message_id,created_at,due_at,campaign_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (key,key,0,'automatic','queued',key+'@example.org','example.org','{}','<'+key+'@example.org>', '2026-10-19T00:00:00+00:00','2026-10-19T00:00:00+00:00',campaign))
        self.store.db.commit();return next(r for r in d.rows(self.store) if r['id']==key)

    def test_presets_and_custom_target_are_durable(self):
        for n in (20,30,50,73):
            value=c.configure(self.store,'start',n)['campaign'];self.assertEqual(value['remaining'],n)
            second=Store(self.store.root)
            try:self.assertEqual(c.active(second)['target'],n)
            finally:second.db.close()
            c.configure(self.store,'close')

    def test_only_one_campaign_and_valid_integer_target(self):
        for n in (0,-1,1001,True,20.5,'20',None):
            with self.assertRaises(ValueError):c.configure(self.store,'start',n)
        c.configure(self.store,'start',20)
        with self.assertRaises(ValueError):c.configure(self.store,'start',30)

    def test_atomic_target_counter_precedes_send_and_survives_restart(self):
        current=c.configure(self.store,'start',1)['campaign']
        item=self.seed('one',current['id']);extra=self.seed('two',current['id'])
        c.claim(self.store,item,'2026-10-19T07:00:00+00:00')
        self.assertEqual(c.active(self.store)['remaining'],0)
        with self.assertRaises(ValueError):c.claim(self.store,extra,'2026-10-20T07:00:00+00:00')
        self.assertEqual(d.rows(self.store)[0]['state'],'sending')
        second=Store(self.store.root)
        try:self.assertEqual(c.active(second)['attempted'],1)
        finally:second.db.close()

    def test_simultaneous_claims_cannot_exceed_target(self):
        current=c.configure(self.store,'start',1)['campaign'];items=[self.seed(str(i),current['id']) for i in range(2)];outcomes=[]
        def call(item):
            store=Store(self.store.root)
            try:c.claim(store,item,'2026-10-19T07:00:00+00:00');outcomes.append('reserved')
            except ValueError:outcomes.append('held')
            finally:store.db.close()
        threads=[threading.Thread(target=call,args=(item,)) for item in items]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(sorted(outcomes),['held','reserved'])

    def test_unknown_outcome_consumes_slot_and_prevents_close(self):
        current=c.configure(self.store,'start',20)['campaign'];item=self.seed('one',current['id'])
        c.claim(self.store,item,'2026-10-19T07:00:00+00:00');d.change(self.store,'one','uncertain')
        self.assertEqual(c.active(self.store)['remaining'],19)
        with self.assertRaisesRegex(ValueError,'Reconcile'):c.configure(self.store,'close')
        with self.assertRaises(ValueError):c.configure(self.store,'update',0)

    def test_close_cancels_only_unsent_and_preserves_old_campaign_history(self):
        current=c.configure(self.store,'start',20)['campaign'];one=self.seed('one',current['id']);self.seed('two',current['id'])
        c.claim(self.store,one,'2026-10-19T07:00:00+00:00');d.change(self.store,'one','sent')
        c.configure(self.store,'close');self.assertIsNone(c.active(self.store))
        states={r['id']:r['state'] for r in d.rows(self.store)}
        self.assertEqual(states,{'one':'sent','two':'cancelled'})
        new=c.configure(self.store,'start',30)['campaign'];self.assertNotEqual(new['id'],current['id']);self.assertEqual(new['remaining'],30)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM campaign_attempts').fetchone()[0],1)

    def test_target_can_change_without_resetting_attempts(self):
        current=c.configure(self.store,'start',20)['campaign'];item=self.seed('one',current['id'])
        c.claim(self.store,item,'2026-10-19T07:00:00+00:00');d.change(self.store,'one','sent')
        self.assertEqual(c.configure(self.store,'update',30)['campaign']['remaining'],29)
        self.assertEqual(c.configure(self.store,'update',1)['campaign']['remaining'],0)

    def test_legacy_unassigned_queue_is_not_adopted(self):
        item=self.seed('legacy');c.configure(self.store,'start',20)
        self.assertFalse(c.permitted(self.store,item))
        with self.assertRaises(ValueError):c.claim(self.store,item,'2026-10-19T07:00:00+00:00')

class CampaignDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.f=test_delivery.DeliveryTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;f.config.update(mode='automatic',schedule_basis='company',campaign_required=True,daily_limit=50,minimum_interval_seconds=180,send_hours=[8,11],send_weekdays=[0,1,2,3,4])
        d.init(f.store)
        write_json(f.store.root/'sending-approval.json',{'sha256':d.fingerprint(d.policy(f.config,f.profile,f.prefs,f.exclusions))})
        write_json(f.store.root/'test-evidence.json',{'reply_verified':True})
        self.clock=datetime(2026,10,19,7,tzinfo=timezone.utc);self.sources={}
        remote=patch.object(d,'remote_lead',side_effect=lambda store,notion,lead,persist=True:lead);remote.start();self.addCleanup(remote.stop)
        f.research.side_effect=lambda url:self.sources[url]

    def seed(self,index):
        f=self.f;old='studio.example';host='studio'+str(index)+'.example'
        raw={k:v.replace(old,host) if isinstance(v,str) else v for k,v in f.raw.items()}
        lead=prepare_lead(raw);lead.update({k:v for k,v in f.lead.items() if k in ('status','approved','notion_page_id','eligibility_reviewed','contact_purpose_reviewed','outreach_allowed','application_route','contact_review_notes','selected_offer')})
        lead.update(company_time_zone='Europe/London',company_time_zone_verified=True,company_time_zone_source=lead['url'])
        lead['draft']=copy.deepcopy(f.lead['draft']);lead['draft']['evidence'][0]['url']=lead['url']
        f.store.add(lead);self.sources[lead['url']]=raw['source_text'];self.sources[lead['contact_source_url']]=raw['source_text']
        return d.queue(f.store,lead,f.config,f.profile,f.prefs,f.exclusions,due='2026-10-19T00:00:00+00:00')

    def tick(self,clock=None):
        f=self.f
        return d.tick(f.store,f.gmail,f.notion,f.config,f.profile,f.prefs,f.exclusions,f.research,clock or self.clock)

    def test_no_active_campaign_prevents_automatic_queue(self):
        with self.assertRaisesRegex(ValueError,'campaign target'):self.seed(1)
        self.f.gmail.send.assert_not_called()

    def test_target_twenty_stops_at_twenty_and_does_not_reset_next_day(self):
        c.configure(self.f.store,'start',20)
        for i in range(21):self.seed(i)
        for i in range(20):self.assertEqual(self.tick(self.clock+timedelta(seconds=180*i))['state'],'sent')
        self.assertEqual(self.tick(self.clock+timedelta(days=1))['state'],'campaign target reached')
        self.assertEqual(self.f.gmail.send.call_count,20)
        c.configure(self.f.store,'update',30)
        self.assertEqual(self.tick(self.clock+timedelta(days=1))['state'],'sent')
        self.assertEqual(c.active(self.f.store)['attempted'],21)

    def test_daily_ceiling_fifty_even_when_campaign_target_is_higher(self):
        c.configure(self.f.store,'start',100)
        for i in range(51):self.seed(i)
        for i in range(50):self.assertEqual(self.tick(self.clock+timedelta(seconds=180*i))['state'],'sent')
        self.assertEqual(self.tick(self.clock+timedelta(seconds=180*50))['state'],'daily limit reached')
        self.assertEqual(self.f.gmail.send.call_count,50)
        self.assertEqual(self.tick(self.clock+timedelta(days=1))['state'],'sent')

    def test_uncertain_gmail_result_never_retries_or_frees_campaign_slot(self):
        c.configure(self.f.store,'start',20);self.seed(1);self.f.gmail.send.side_effect=TimeoutError
        self.assertEqual(self.tick()['state'],'uncertain')
        self.assertEqual(c.active(self.f.store)['attempted'],1)
        with self.assertRaisesRegex(ValueError,'Uncertain'):self.tick(self.clock+timedelta(minutes=4))
        self.assertEqual(self.f.gmail.send.call_count,1)

    def test_earlier_than_eight_or_at_eleven_and_weekends_are_held(self):
        c.configure(self.f.store,'start',20);self.seed(1)
        for clock in (self.clock-timedelta(minutes=1),self.clock+timedelta(hours=3),self.clock+timedelta(days=5)):
            self.assertIn('window',self.tick(clock)['state'])
        self.f.gmail.send.assert_not_called()
        self.assertEqual(self.tick()['state'],'sent')

    def test_exact_signature_is_present_once_in_sent_email(self):
        c.configure(self.f.store,'start',20);self.seed(1);self.tick()
        body=self.f.gmail.send.call_args[0][3]
        self.assertTrue(body.endswith(SIGNATURE));self.assertEqual(body.count('Whatsapp:'),1)

    def test_daily_limit_validation_rejects_above_fifty_and_bool(self):
        for value in (51,True,0):
            with self.assertRaises(ValueError):d.validate_config(dict(self.f.config,daily_limit=value),self.f.profile)
        d.validate_config(dict(self.f.config,daily_limit=50),self.f.profile)

class SignatureTests(unittest.TestCase):
    def test_existing_closing_is_replaced_not_duplicated(self):
        profile={'email_signature':SIGNATURE}
        for ending in ('\n\nShine','\n\nThank you,\nShine','\n\nBest regards,\nShine'):
            body=with_signature('My portfolio and application text.'+ending,profile)
            self.assertTrue(body.endswith(SIGNATURE));self.assertEqual(body.count('Shine'),1)
            self.assertEqual(with_signature(body,profile),body)

    def test_postal_and_optout_footer_preserved_before_exact_closing(self):
        body=with_footer('Application text.\n\nShine',{'email_signature':SIGNATURE},'Reply to opt out.\nTest postal address')
        self.assertIn('Reply to opt out.\nTest postal address',body)
        self.assertTrue(body.endswith(SIGNATURE))

    def test_new_company_window_uses_local_time_for_dubai_and_us(self):
        config=read_json(ROOT/'config/sending.json')
        for zone,utc_hour in (('Asia/Dubai',4),('America/New_York',12)):
            lead={'company_time_zone':zone,'company_time_zone_verified':True,'company_time_zone_source':'https://example.org/contact'}
            clock=datetime(2026,10,19,utc_hour,tzinfo=timezone.utc)
            self.assertTrue(permitted_time(config,clock,lead))
            self.assertFalse(permitted_time(config,clock-timedelta(minutes=1),lead))
            self.assertFalse(permitted_time(config,clock+timedelta(hours=3),lead))
