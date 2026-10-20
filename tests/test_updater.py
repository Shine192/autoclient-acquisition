import json
import tempfile
import unittest
import shutil
from pathlib import Path
from acquisition_agent.updater import install

ROOT=Path(__file__).resolve().parent.parent
class UpdaterTests(unittest.TestCase):
    def test_preserves_state_keys_and_targeting(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'existing';target.mkdir()
            shutil.copytree(ROOT/'config',target/'config')
            shutil.copytree(ROOT/'acquisition_agent',target/'acquisition_agent')
            (target/'.env').write_text('PRIVATE_TEST_KEY=not-a-real-key')
            (target/'state/credentials').mkdir(parents=True)
            (target/'state/credentials/gmail-token.json').write_text('private-token-fixture')
            preferences={'countries':['United Kingdom'],'search_markets':['United Kingdom'],'weekly_capacity_hours':13,'custom':'keep'}
            (target/'config/preferences.json').write_text(json.dumps(preferences))
            old_config=json.loads((target/'config/sending.json').read_text());old_config.update(daily_limit=10,minimum_interval_seconds=300,send_hours=[9,11],campaign_required=False,custom_setting='keep')
            (target/'config/sending.json').write_text(json.dumps(old_config))
            original=(target/'config/sending.json').read_bytes()
            (target/'state/agent.sqlite3').write_bytes(b'preserved-sending-history-fixture')
            backup=install(ROOT,target)
            updated_config=json.loads((target/'config/sending.json').read_text())
            self.assertEqual(updated_config,dict(old_config,daily_limit=50,minimum_interval_seconds=180,send_hours=[8,11],send_weekdays=[0,1,2,3,4],schedule_basis='company',campaign_required=True))
            self.assertEqual((backup/'config/sending.json').read_bytes(),original)
            self.assertEqual(json.loads((target/'config/profile.json').read_text())['email_signature'],'Thank you,\nShine\nWhatsapp: (+0) 000-000-0000')
            self.assertEqual((target/'state/agent.sqlite3').read_bytes(),b'preserved-sending-history-fixture')
            self.assertTrue((target/'Configure-Automatic-Research.command').exists())
            self.assertTrue((target/'docs/AUTOMATIC-RESEARCH.md').exists())
            self.assertEqual((target/'.env').read_text(),'PRIVATE_TEST_KEY=not-a-real-key')
            self.assertEqual((target/'state/credentials/gmail-token.json').read_text(),'private-token-fixture')
            updated=json.loads((target/'config/preferences.json').read_text())
            self.assertEqual(updated,dict(preferences,countries=['United Kingdom','United Arab Emirates'],search_markets=['United Kingdom','United Arab Emirates']))
            self.assertEqual(json.loads((backup/'config/preferences.json').read_text()),preferences)
            install(ROOT,target)
            self.assertEqual(json.loads((target/'config/preferences.json').read_text()),updated)
            self.assertFalse((backup/'state').exists())
            self.assertFalse((backup/'.env').exists())

    def test_valid_live_tested_approval_carries_only_the_explicit_policy_update(self):
        from acquisition_agent.updater import manifest
        from acquisition_agent.delivery import fingerprint
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'existing';target.mkdir()
            shutil.copytree(ROOT/'config',target/'config');shutil.copytree(ROOT/'acquisition_agent',target/'acquisition_agent')
            (target/'state').mkdir()
            old=json.loads((target/'config/sending.json').read_text());old.update(mode='automatic',daily_limit=10,send_hours=[9,11],minimum_interval_seconds=300,campaign_required=False)
            (target/'config/sending.json').write_text(json.dumps(old))
            profile=json.loads((target/'config/profile.json').read_text());profile.pop('email_signature',None);(target/'config/profile.json').write_text(json.dumps(profile))
            (target/'state/test-evidence.json').write_text(json.dumps({'reply_verified':True}))
            old_hash=fingerprint(manifest(target));(target/'state/sending-approval.json').write_text(json.dumps({'sha256':old_hash}))
            backup=install(ROOT,target)
            approval=json.loads((target/'state/sending-approval.json').read_text())
            self.assertEqual(approval['sha256'],fingerprint(manifest(target)));self.assertNotEqual(approval['sha256'],old_hash)
            self.assertEqual(json.loads((backup/'state/sending-approval.json').read_text())['sha256'],old_hash)
            self.assertFalse((target/'state/agent.sqlite3').exists()) # Installer neither resets nor creates sending history.
            self.assertEqual(json.loads((target/'config/sending.json').read_text())['mode'],'automatic')

    def test_stale_approval_is_not_reauthorized(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'existing';target.mkdir()
            shutil.copytree(ROOT/'config',target/'config');shutil.copytree(ROOT/'acquisition_agent',target/'acquisition_agent')
            (target/'state').mkdir();(target/'state/test-evidence.json').write_text('{"reply_verified":true}')
            (target/'state/sending-approval.json').write_text('{"sha256":"stale"}')
            install(ROOT,target)
            self.assertEqual(json.loads((target/'state/sending-approval.json').read_text())['sha256'],'stale')

    def test_active_panel_stops_install_before_copy(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'existing';target.mkdir()
            shutil.copytree(ROOT/'config',target/'config')
            shutil.copytree(ROOT/'acquisition_agent',target/'acquisition_agent')
            (target/'state').mkdir()
            with (target/'state/panel.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(ValueError):install(ROOT,target)
            self.assertFalse((target/'update-backups').exists())

    def test_ui_update_after_policy_migration_preserves_policy_and_approval_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'existing';target.mkdir()
            shutil.copytree(ROOT/'config',target/'config')
            shutil.copytree(ROOT/'acquisition_agent',target/'acquisition_agent')
            (target/'state/migrations').mkdir(parents=True)
            (target/'state/migrations/v0.13-policy.json').write_text('{"version":"0.13.0"}')
            sending=json.loads((target/'config/sending.json').read_text());sending.update(mode='automatic',daily_limit=32,send_hours=[8,11])
            (target/'config/sending.json').write_text(json.dumps(sending))
            (target/'state/sending-approval.json').write_text('{"sha256":"preserve-exact-bytes"}')
            (target/'state/agent.sqlite3').write_bytes(b'queue-and-delivery-history')
            before={name:(target/name).read_bytes() for name in ('config/sending.json','config/profile.json','state/sending-approval.json','state/agent.sqlite3')}
            install(ROOT,target)
            for name,value in before.items():self.assertEqual((target/name).read_bytes(),value,name)
