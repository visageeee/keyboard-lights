import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import background_keeper
from controller import Device
from model import LightingProfile
import timer
import timer_store


class TimerCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.temp.name})
        self.env.start()
        self.device = Device('Keyboard', '046d', 'c123')
        self.profile = LightingProfile()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = timer.main(list(args))
        return result, out.getvalue(), err.getvalue()

    def test_duration_inputs(self):
        for value, seconds in [('25', 1500), ('25m', 1500), ('90s', 90), ('1h30m', 5400), ('24h', 86400)]:
            self.assertEqual(timer.duration(value), seconds)
        for value in ('0', '25x', '25m30h', '25h', ''):
            with self.assertRaises(Exception):
                timer.duration(value)

    def test_requires_applied_design(self):
        code, _, error = self.invoke('start', '25m')
        self.assertEqual(code, 1)
        self.assertIn('Apply a design', error)

    def test_disabled_keeper_preserves_applied_snapshot_for_command(self):
        background_keeper.save_applied('/bin/true', self.device, self.profile, enabled=True)
        background_keeper.disable()
        self.assertIsNone(background_keeper.load())
        self.assertEqual(background_keeper.load(include_disabled=True)[1], self.device)
        with patch('timer_store.start_service') as start:
            code, output, _ = self.invoke('start', '90s')
        self.assertEqual(code, 0)
        self.assertIn('90 seconds', output)
        self.assertEqual(start.call_args.args[1], self.device)
        self.assertEqual(start.call_args.args[3], 90)

    def test_status_cancel_and_replace_active_timer(self):
        timer_store.start('/bin/true', self.device, self.profile, 60)
        self.assertIn('remaining', self.invoke('status')[1])
        with patch('timer_store.start_service') as start:
            self.assertEqual(self.invoke('start', '1m')[0], 0)
            self.assertEqual(start.call_args.args[1], self.device)
        self.assertEqual(self.invoke('cancel')[0], 0)
        self.assertIsNone(timer_store.load())
        self.assertEqual(self.invoke('status')[0], 1)


if __name__ == '__main__':
    unittest.main()
