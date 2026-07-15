import importlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


class HeartbeatTests(unittest.TestCase):
    def test_heartbeat_module_tracks_fresh_stale_and_throttled_updates(self):
        spec = importlib.util.find_spec("assistant_bot.health")
        self.assertIsNotNone(spec, "missing assistant_bot.health")
        health = importlib.import_module("assistant_bot.health")

        with tempfile.TemporaryDirectory() as tmp:
            now = [1_000.0]
            data_path = Path(tmp) / "assistant.sqlite3"
            heartbeat = health.Heartbeat(data_path, min_interval=10, clock=lambda: now[0])

            self.assertTrue(heartbeat.touch(force=True))
            self.assertTrue(health.heartbeat_is_fresh(data_path, max_age=120, now=now[0]))

            now[0] += 5
            self.assertFalse(heartbeat.touch())
            self.assertTrue(health.heartbeat_is_fresh(data_path, max_age=120, now=now[0]))

            now[0] += 126
            self.assertFalse(health.heartbeat_is_fresh(data_path, max_age=120, now=now[0]))
            self.assertTrue(heartbeat.touch())
            self.assertTrue(health.heartbeat_is_fresh(data_path, max_age=120, now=now[0]))
            heartbeat.clear()
            self.assertFalse(health.heartbeat_is_fresh(data_path, max_age=120, now=now[0]))

    def test_missing_heartbeat_is_unhealthy(self):
        spec = importlib.util.find_spec("assistant_bot.health")
        self.assertIsNotNone(spec, "missing assistant_bot.health")
        health = importlib.import_module("assistant_bot.health")

        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(health.heartbeat_is_fresh(Path(tmp) / "assistant.sqlite3", now=1_000.0))


if __name__ == "__main__":
    unittest.main()
