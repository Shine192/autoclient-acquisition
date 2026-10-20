import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from acquisition_agent.core import Store,read_json
from acquisition_agent.readiness import report
from acquisition_agent.runner import due

ROOT=Path(__file__).resolve().parent.parent
class ReadinessTests(unittest.TestCase):
    def test_no_credentials_and_no_queue_created(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            cfg,profile,prefs,exclusions=[read_json(ROOT/'config'/name) for name in ('sending.json','profile.json','preferences.json','exclusions.json')]
            result=report(store,cfg,profile,prefs,exclusions)
            self.assertFalse(result['checks']['gmail_token_present'])
            self.assertFalse(result['checks']['exact_policy_approved'])
            self.assertIn('Local Gmail authorization is missing',result['production_blockers'])
            self.assertFalse((store.root/'sending-approval.json').exists())
            store.db.close()

    def test_discovery_attempt_interval_survives_restart(self):
        clock=datetime.now(timezone.utc)
        self.assertTrue(due(None,6,clock))
        self.assertFalse(due(clock.isoformat(),6,clock))
        self.assertTrue(due((clock-timedelta(hours=7)).isoformat(),6,clock))

    def test_combined_agent_once_never_sends_in_draft_mode(self):
        from unittest.mock import patch
        from acquisition_agent.runner import run
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            cfg,profile,prefs,exclusions=[read_json(ROOT/'config'/name) for name in ('sending.json','profile.json','preferences.json','exclusions.json')]
            with patch('acquisition_agent.__main__.settings',return_value=(prefs,profile,exclusions)), patch('acquisition_agent.__main__.run_discovery',return_value={'new':0,'errors':[]}) as discover, patch('acquisition_agent.__main__.sending_command') as send, patch.dict('os.environ',{},clear=True):
                run(store,ROOT,6,True)
                run(store,ROOT,6,True)
            discover.assert_not_called()
            send.assert_not_called()
            self.assertFalse((store.root/'agent-events.jsonl').exists())
            store.db.close()
