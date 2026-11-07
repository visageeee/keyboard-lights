import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import background_keeper as keeper
from controller import Device
from model import LightingProfile


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.temp.name})
        self.env.start()
        self.device = Device('Test keyboard', '046d', 'c123', 'serial')
        self.profile = LightingProfile()
        self.process = None

    def tearDown(self):
        try:
            keeper.disable()
            if self.process:
                self.process.wait(timeout=5)
        finally:
            self.env.stop()
            self.temp.cleanup()

    def wait_for_lines(self, path, count):
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            if path.exists():
                lines = path.read_text().splitlines()
                if len(lines) >= count:
                    return lines
            time.sleep(.05)
        self.fail('Background helper did not apply the expected design')

    def test_enable_stores_snapshot_autostart_and_disable(self):
        with patch('background_keeper.subprocess.Popen') as spawn:
            keeper.enable('/tmp/controller', self.device, self.profile)
        self.profile.set_key('a', '123456')
        executable, device, snapshot = keeper.load()
        self.assertEqual((executable, device), ('/tmp/controller', self.device))
        self.assertNotEqual(snapshot.colors['a'], '123456')
        self.assertTrue(keeper.enabled())
        self.assertEqual(keeper.config_path().stat().st_mode & 0o777, 0o600)
        self.assertIn('background_service.py', keeper.autostart_path().read_text())
        self.assertTrue(spawn.called)
        keeper.disable()
        self.assertFalse(keeper.enabled())
        self.assertIsNone(keeper.load())
        self.assertFalse(keeper.autostart_path().exists())

    def test_invalid_config_is_not_applied(self):
        keeper.config_path().parent.mkdir(parents=True)
        keeper.config_path().write_text('{"version":1,"enabled":true,"device":{}}')
        self.assertIsNone(keeper.load())
        keeper.config_path().write_text('not json')
        self.assertIsNone(keeper.load())

    def test_helper_survives_caller_updates_and_stops(self):
        base = Path(self.temp.name)
        log = base / 'calls'
        fake = base / 'fake-controller'
        fake.write_text('#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\n'
                        f'p=Path({str(log)!r})\n'
                        'with p.open("a") as f: f.write(sys.stdin.read().replace("\\n", "|") + "\\n")\n')
        fake.chmod(0o755)
        self.profile.set_key('a', 'abcdef')
        self.process = keeper.enable(str(fake), self.device, self.profile)
        self.assertIn('k a abcdef', self.wait_for_lines(log, 1)[0])
        # Updating the saved applied profile is observed by the existing helper.
        self.profile.set_key('a', '123456')
        extra = keeper.enable(str(fake), self.device, self.profile)
        extra.wait(timeout=5)
        self.assertIn('k a 123456', self.wait_for_lines(log, 2)[1])
        keeper.disable()
        self.process.wait(timeout=5)
        self.assertEqual(self.process.returncode, 0)
        self.process = None


if __name__ == '__main__':
    unittest.main()
