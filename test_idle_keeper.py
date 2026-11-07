import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import background_keeper
from controller import Device
from g515_activity import G515ActivityMonitor
from model import LightingProfile


class IdleKeeperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.temp.name})
        self.env.start()
        self.device = Device('G515', '046d', 'c358')

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_idle_and_wake_notifications_are_distinct(self):
        wake, idle = Mock(), Mock()
        monitor = G515ActivityMonitor(self.device, wake, Mock(), idle, 30)
        monitor.feature = 9
        monitor.ignore_idle_until = 0
        monitor._handle(bytes([0x11, 0xff, 9, 0x10, 0]))
        monitor._handle(bytes([0x11, 0xff, 9, 0x10, 1]))
        monitor._handle(bytes([0x11, 0xff, 8, 0x10, 0]))
        idle.assert_called_once()
        wake.assert_called_once()

    def test_idle_timeout_is_configured_preserving_sleep_and_flags(self):
        monitor = G515ActivityMonitor(self.device, Mock(), Mock(), Mock(), 30)
        monitor.feature = 9
        monitor._request = Mock(side_effect=[bytes([0, 3, 4]),
                                            bytes([0, 0, 0, 0, 60, 1, 44]),
                                            bytes([1, 0, 0, 0, 30, 1, 44]),
                                            bytes([1, 3, 6])])
        monitor._enable()
        self.assertEqual(monitor._request.call_args_list[2].args, (9, 7, [1, 0, 0, 0, 30, 1, 44]))
        self.assertEqual(monitor._request.call_args_list[3].args, (9, 5, [1, 3, 6]))

    def test_idle_delay_survives_profile_updates(self):
        profile = LightingProfile()
        background_keeper.save_applied('/bin/true', self.device, profile, enabled=True, idle_off_after=60)
        background_keeper.save_applied('/bin/true', self.device, profile, enabled=True)
        self.assertEqual(background_keeper.idle_delay(), 60)
        background_keeper.save_applied('/bin/true', self.device, profile, enabled=True, idle_off_after=None)
        self.assertIsNone(background_keeper.idle_delay())

    def test_background_turns_off_on_idle_and_restores_custom_profile_on_wake(self):
        root = Path(self.temp.name)
        log, controller = root / 'calls', root / 'controller'
        controller.write_text('#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\n'
                              f'p=Path({str(log)!r})\n'
                              'with p.open("a") as f: f.write(sys.stdin.read().replace("\\n", "|") + "\\n")\n')
        controller.chmod(0o755)
        profile = LightingProfile()
        profile.set_key('a', 'abcdef')
        background_keeper.save_applied(str(controller), self.device, profile, enabled=True, idle_off_after=10)
        # Replace only the HID monitor; keep the real background loop and controller adapter.
        code = '''import pathlib, threading, time\nimport background_service\nroot = pathlib.Path(%r)\nclass Monitor:\n def __init__(self, device, wake, error, idle, seconds):\n  self.wake, self.idle, self.done = wake, idle, False\n  self.thread = None\n def start(self):\n  def loop():\n   while not self.done:\n    for name, callback in (("idle-event", self.idle), ("wake-event", self.wake)):\n     path = root / name\n     if path.exists():\n      path.unlink()\n      if callback: callback()\n    time.sleep(.02)\n  self.thread = threading.Thread(target=loop, daemon=True); self.thread.start()\n def rearm_notifications(self): pass\n def close(self): self.done = True\nbackground_service.G515ActivityMonitor = Monitor\nbackground_service.run()\n''' % str(root)
        process = subprocess.Popen([sys.executable, '-c', code], cwd=str(Path(__file__).parent))
        def wait_for(index, token):
            deadline = time.monotonic() + 7
            while time.monotonic() < deadline:
                if log.exists():
                    lines = log.read_text().splitlines()
                    if len(lines) > index and token in lines[index]:
                        return
                time.sleep(.05)
            self.fail(f'Profile update {index} not observed')
        try:
            wait_for(0, 'k a abcdef')
            (root / 'idle-event').touch()
            wait_for(1, 'k a 000000')
            (root / 'wake-event').touch()
            wait_for(2, 'k a abcdef')
            self.assertEqual(background_keeper.load()[2].colors['a'], 'abcdef')
        finally:
            background_keeper.disable()
            process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
