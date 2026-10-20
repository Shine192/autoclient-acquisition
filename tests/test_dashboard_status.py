"""The UI observes worker state; inspecting it must not start or alter a worker."""
import fcntl
import tempfile
import unittest
from pathlib import Path
from acquisition_agent.panel import scheduled_worker_running

class WorkerStatusTests(unittest.TestCase):
    def test_missing_lock_does_not_create_one(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(scheduled_worker_running(folder))
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_old_lock_file_is_not_a_running_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'agent.lock';path.write_text('unchanged')
            self.assertFalse(scheduled_worker_running(folder))
            self.assertEqual(path.read_text(),'unchanged')
            with path.open('a') as handle:
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def test_held_lifetime_lock_is_running_and_remains_held(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'agent.lock'
            with path.open('a') as handle:
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.assertTrue(scheduled_worker_running(folder))
                with path.open('r') as other:
                    with self.assertRaises(BlockingIOError):fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertFalse(scheduled_worker_running(folder))
