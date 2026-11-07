import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import background_keeper
from controller import Device
from model import LightingProfile
import timer_store


class TimerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.tmp.name})
        self.env.start()
        self.profile = LightingProfile()
        self.device = Device('Keyboard', '046d', 'c123')
        self.process = None

    def tearDown(self):
        timer_store.cancel()
        if self.process:
            self.process.wait(timeout=5)
        self.env.stop()
        self.tmp.cleanup()

    def test_progress_alarm_and_restoration_frame(self):
        data = timer_store.start('/bin/true', self.device, self.profile, 160, now=1000)
        frame, state = timer_store.overlay(data, self.profile, 1000)
        self.assertEqual(state, ('countdown', len(timer_store.TOP_KEYS)))
        self.assertTrue(all(frame.colors[k] == '0066ff' for k in timer_store.TOP_KEYS))
        frame, state = timer_store.overlay(data, self.profile, 1080)
        self.assertEqual(state, ('countdown', len(timer_store.TOP_KEYS) // 2))
        self.assertEqual(frame.colors[timer_store.TOP_KEYS[-1]], '000000')
        self.assertEqual(frame.colors[timer_store.TOP_KEYS[0]], '0066ff')
        self.assertEqual(frame.colors['a'], self.profile.colors['a'])
        frame, _ = timer_store.overlay(data, self.profile, 1160)
        self.assertTrue(all(frame.colors[k] == 'ff0000' for k in timer_store.TOP_KEYS))
        frame, _ = timer_store.overlay(data, self.profile, 1160.6)
        self.assertTrue(all(frame.colors[k] == '000000' for k in timer_store.TOP_KEYS))
        self.assertIsNotNone(timer_store.overlay(data, self.profile, 1189.9)[0])
        self.assertIsNone(timer_store.overlay(data, self.profile, 1190)[0])
        self.assertNotEqual(self.profile.colors[timer_store.TOP_KEYS[-1]], '000000')

    def test_validation_and_snapshot(self):
        for seconds in (0, -1, 86401):
            with self.assertRaises(ValueError):
                timer_store.start('/bin/true', self.device, self.profile, seconds)
        timer_store.start('/bin/true', self.device, self.profile, 20)
        self.profile.set_key('a', 'ffffff')
        self.assertNotEqual(timer_store.load()[3].colors['a'], 'ffffff')
        timer_store.path().write_text('{"version":1}')
        self.assertIsNone(timer_store.load())

    def test_background_timer_reapplies_and_restores_without_keeper(self):
        base = Path(self.tmp.name)
        log = base / 'calls'
        fake = base / 'controller'
        fake.write_text('#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\n'
                        f'p=Path({str(log)!r})\n'
                        'with p.open("a") as f: f.write(sys.stdin.read().replace("\\n", "|") + "\\n")\n')
        fake.chmod(0o755)
        self.profile.set_key(timer_store.TOP_KEYS[-1], 'abcdef')
        timer_store.start(str(fake), self.device, self.profile, 4)
        self.process = background_keeper.launch()
        deadline = time.monotonic() + 5
        target = 'k ' + timer_store.TOP_KEYS[-1] + ' 000000'
        while time.monotonic() < deadline:
            if log.exists() and target in log.read_text():
                break
            time.sleep(.05)
        else:
            self.fail('Countdown did not update the top row')
        timer_store.cancel()
        self.process.wait(timeout=5)
        self.process = None
        self.assertIn('k ' + timer_store.TOP_KEYS[-1] + ' abcdef', log.read_text().splitlines()[-1])


if __name__ == '__main__':
    unittest.main()
