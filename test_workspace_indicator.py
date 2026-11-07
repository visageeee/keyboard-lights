import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import background_keeper
from controller import Device
from model import LightingProfile
import workspace_indicator as workspace
import timer_store


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.temp.name})
        self.env.start()
        self.process = None

    def tearDown(self):
        if self.process:
            timer_store.cancel()
            background_keeper.disable()
            self.process.wait(timeout=5)
        self.env.stop()
        self.temp.cleanup()

    def test_workspace_number_parsing_and_bounds(self):
        self.assertEqual(workspace.parse_workspace('_NET_CURRENT_DESKTOP(CARDINAL) = 0\n'), 1)
        self.assertEqual(workspace.parse_workspace('_NET_CURRENT_DESKTOP(CARDINAL) = 11'), 12)
        self.assertIsNone(workspace.parse_workspace('_NET_CURRENT_DESKTOP(CARDINAL) = 12'))
        self.assertIsNone(workspace.parse_workspace('something else'))

    def test_overlay_preserves_profile_and_other_keys(self):
        profile = LightingProfile()
        profile.set_key('f1', '123456')
        profile.set_key('f2', 'abcdef')
        first = workspace.overlay(profile, 1, 'ff0000')
        second = workspace.overlay(profile, 2, 'ff0000')
        self.assertEqual((first.colors['f1'], first.colors['f2']), ('ff0000', 'abcdef'))
        self.assertEqual((second.colors['f1'], second.colors['f2']), ('123456', 'ff0000'))
        self.assertEqual(profile.colors['f1'], '123456')
        self.assertEqual(workspace.overlay(profile, None, 'ff0000').colors, profile.colors)

    def test_settings_persist_and_validate(self):
        self.assertEqual(workspace.load(), (False, '57cdc5'))
        workspace.save(True, 'ABCDEF')
        self.assertEqual(workspace.load(), (True, 'abcdef'))
        with self.assertRaises(ValueError):
            workspace.save(True, 'ff0000\n')

    def test_real_helper_updates_f_keys_from_workspace_changes(self):
        root = Path(self.temp.name)
        log = root / 'calls'
        controller = root / 'controller'
        controller.write_text('#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\n'
                              f'p=Path({str(log)!r})\n'
                              'with p.open("a") as f: f.write(sys.stdin.read().replace("\\n", "|") + "\\n")\n')
        controller.chmod(0o755)
        xprop = root / 'xprop'
        xprop.write_text('#!/usr/bin/python3\nimport time\nfrom pathlib import Path\n'
                         f'flag=Path({str(root / "switch")!r})\n'
                         'print("_NET_CURRENT_DESKTOP(CARDINAL) = 0", flush=True)\n'
                         'while not flag.exists(): time.sleep(.05)\n'
                         'print("_NET_CURRENT_DESKTOP(CARDINAL) = 1", flush=True)\n'
                         'while True: time.sleep(.1)\n')
        xprop.chmod(0o755)
        profile = LightingProfile()
        profile.set_key('f1', '111111')
        profile.set_key('f2', '222222')
        background_keeper.save_applied(str(controller), Device('fake', '046d', 'c123'), profile, enabled=True)
        workspace.save(True, 'ff0000')
        with patch.dict(os.environ, {'PATH': str(root), 'DISPLAY': ':test', 'XDG_SESSION_TYPE': 'x11'}):
            self.process = background_keeper.launch()
            def wait_for(first, second):
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    if log.exists():
                        for line in log.read_text().splitlines():
                            if first in line and second in line:
                                return
                    time.sleep(.05)
                self.fail('Workspace update was not applied')
            wait_for('k f1 ff0000', 'k f2 222222')
            (root / 'switch').touch()
            wait_for('k f1 111111', 'k f2 ff0000')
            timer_store.start(str(controller), Device('fake', '046d', 'c123'), profile, 30)
            wait_for('k f1 0066ff', 'k f2 0066ff')
            timer_store.cancel()
            self.assertEqual(background_keeper.load()[2].colors['f1'], '111111')


if __name__ == '__main__':
    unittest.main()
