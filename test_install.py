import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import background_keeper
from controller import Device
import install
from model import LightingProfile


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='keyboard install ')
        root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'XDG_DATA_HOME': str(root / 'data'),
                                            'XDG_CONFIG_HOME': str(root / 'config'),
                                            'XDG_BIN_HOME': str(root / 'bin')})
        self.env.start()
        self.root = root

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_installs_launchers_icon_and_is_repeatable(self):
        install.install()
        install.install()
        desktop = (self.root / 'data/applications/keyboard-lights.desktop').read_text()
        self.assertIn('StartupWMClass=keyboard-lights', desktop)
        self.assertIn('Icon=keyboard-lights', desktop)
        self.assertTrue((self.root / 'data/icons/hicolor/scalable/apps/keyboard-lights.svg').exists())
        command = self.root / 'bin/keyboard-lights-timer'
        result = subprocess.run([str(command), '--help'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('start', result.stdout)

    def test_preserves_existing_unrelated_launcher(self):
        command = self.root / 'bin/keyboard-lights'
        command.parent.mkdir(parents=True)
        command.write_text('mine')
        with self.assertRaises(OSError):
            install.install()
        self.assertEqual(command.read_text(), 'mine')

    def test_existing_autostart_is_migrated_without_changing_profile(self):
        device = Device('Test', '046d', 'c123')
        profile = LightingProfile()
        with patch('background_keeper.launch'):
            background_keeper.enable('/bin/true', device, profile)
        install.install()
        entry = background_keeper.autostart_path().read_text()
        self.assertIn(str(self.root / 'data/keyboard-lights/background_service.py'), entry)
        self.assertEqual(background_keeper.load()[1], device)


if __name__ == '__main__':
    unittest.main()
