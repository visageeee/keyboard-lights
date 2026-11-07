import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import background_keeper
from controller import Device
from model import LightingProfile
import timer_chime
import timer_store


class TimerChimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.temp.name})
        self.env.start()
        self.process = None

    def tearDown(self):
        timer_store.cancel()
        if self.process:
            self.process.wait(timeout=5)
        self.env.stop()
        self.temp.cleanup()

    def test_play_uses_the_supplied_ogg_file(self):
        player = '/fake/paplay'
        with patch.object(timer_chime.shutil, 'which', side_effect=lambda name: player if name == 'paplay' else None), \
                patch.object(timer_chime.subprocess, 'run') as run:
            run.return_value.returncode = 0
            timer_chime._play()
        args = run.call_args.args[0]
        self.assertEqual(args[0], player)
        self.assertEqual(Path(args[1]), Path(timer_chime.__file__).resolve().with_name('chime.ogg'))
        self.assertTrue(Path(args[1]).read_bytes().startswith(b'OggS'))

    def test_each_timer_chimes_only_once_across_restarts(self):
        with patch.object(timer_chime.threading, 'Thread') as thread:
            self.assertTrue(timer_chime.notify_once('a' * 32))
            self.assertFalse(timer_chime.notify_once('a' * 32))
            self.assertTrue(timer_chime.notify_once('b' * 32))
        self.assertEqual(thread.call_count, 2)

    def test_background_timer_chimes_once_then_can_be_cancelled(self):
        directory = Path(self.temp.name)
        log = directory / 'audio-log'
        player = directory / 'paplay'
        player.write_text('#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\n'
                          f'p=Path({str(log)!r})\n'
                          'assert Path(sys.argv[1]).read_bytes().startswith(b"OggS")\n'
                          'with p.open("a") as f: f.write("play\\n")\n')
        player.chmod(0o755)
        controller = directory / 'controller'
        controller.write_text('#!/usr/bin/python3\nimport sys\nsys.stdin.read()\n')
        controller.chmod(0o755)
        with patch.dict(os.environ, {'PATH': str(directory)}):
            timer_store.start(str(controller), Device('Fake', '046d', 'c123'), LightingProfile(), 1)
            self.process = background_keeper.launch()
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline and not log.exists():
                time.sleep(.05)
            self.assertTrue(log.exists(), 'Timer never played the chime')
            time.sleep(.8)
            self.assertEqual(log.read_text().splitlines(), ['play'])
            timer_store.cancel()
            self.process.wait(timeout=5)
            self.process = None


if __name__ == '__main__':
    unittest.main()
