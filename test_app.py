import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from concurrent.futures import Future

from controller import Controller, ControllerError, Device, parse_devices
from model import KEYS, KEY_NAMES, LEGACY_KEY_NAMES, LightingProfile


class LightingTests(unittest.TestCase):
    def test_all_preview_keys_are_unique_and_supported_by_profile(self):
        self.assertEqual(len(KEY_NAMES), len(KEYS))
        profile = LightingProfile()
        self.assertEqual(set(profile.colors), KEY_NAMES)
        profile.set_all('AABBCC')
        profile.set_key('w', 'FF00aa')
        lines = profile.controller_profile().splitlines()
        self.assertEqual(lines[-1], 'c')
        self.assertIn('k w ff00aa', lines)
        self.assertEqual(len(lines), len(KEYS) + 1)
        with self.assertRaises(ValueError):
            profile.set_key('w\nc', 'ffffff')
        with self.assertRaises(ValueError):
            profile.set_key('w', 'ffffff\nc')

    def test_nordic_iso_keys_and_controller_commands(self):
        keys = {key.name: key for key in KEYS}
        self.assertEqual(keys['intl_backslash'].label, '<')
        self.assertEqual(keys['dollar'].label, "'")
        self.assertEqual(keys['quote'].label, 'Ä')
        self.assertEqual(keys['semicolon'].label, 'Ö')
        self.assertEqual(keys['open_bracket'].label, 'Å')
        self.assertEqual(keys['enter'].height, 2)
        self.assertEqual(keys['shift_left'].x + keys['shift_left'].width,
                         keys['intl_backslash'].x)
        self.assertEqual(keys['quote'].x + keys['quote'].width, keys['dollar'].x)
        self.assertEqual(keys['dollar'].x + keys['dollar'].width, keys['enter'].x)
        profile = LightingProfile()
        profile.set_key('intl_backslash', '123456')
        profile.set_key('dollar', 'abcdef')
        profile.set_key('quote', '987654')
        output = profile.controller_profile()
        self.assertIn('k intl_backslash 123456\n', output)
        self.assertIn('k dollar abcdef\n', output)
        self.assertIn('k quote 987654\n', output)

    def test_old_ansi_profile_migrates_without_losing_colors(self):
        old = {name: '102030' for name in LEGACY_KEY_NAMES}
        old['backslash'] = 'aabbcc'
        old['shift_left'] = '123456'
        old['quote'] = '778899'
        profile = LightingProfile(old)
        self.assertEqual(profile.colors['dollar'], 'aabbcc')
        self.assertEqual(profile.colors['intl_backslash'], '123456')
        self.assertEqual(profile.colors['quote'], '778899')
        self.assertEqual(set(profile.colors), KEY_NAMES)

    def test_brightness_scales_output_without_changing_saved_colors(self):
        profile = LightingProfile()
        profile.set_key('w', 'ff8040')
        profile.set_brightness(50)
        self.assertEqual(profile.effective_color('w'), '804020')
        self.assertIn('k w 804020\n', profile.controller_profile())
        self.assertEqual(profile.colors['w'], 'ff8040')
        profile.set_brightness(0)
        self.assertEqual(profile.effective_color('w'), '000000')
        profile.set_brightness(100)
        self.assertEqual(profile.effective_color('w'), 'ff8040')
        for invalid in (-1, 101, True, 2.5):
            with self.assertRaises(ValueError):
                profile.set_brightness(invalid)

    def test_click_toggles_and_drag_uses_a_single_paint_or_erase_stroke(self):
        from main import KeyboardPreview, Gdk
        profile = LightingProfile()
        keys = {key.name: key for key in KEYS}
        preview = SimpleNamespace(profile=profile, get_color=lambda: 'ff0000',
                                  key_at=lambda x, _y: keys.get(x), queue_draw=Mock(),
                                  changed=Mock(), painting=False, stroke_color=None,
                                  stroke_keys=set())
        preview.paint = lambda key: KeyboardPreview.paint(preview, key)
        press = lambda key: KeyboardPreview.press(preview, None, SimpleNamespace(button=1, x=key, y=0))
        release = lambda: KeyboardPreview.release(preview, None, SimpleNamespace(button=1))
        drag = lambda key: KeyboardPreview.motion(preview, None,
                         SimpleNamespace(x=key, y=0, state=Gdk.ModifierType.BUTTON1_MASK))
        press('w')
        drag('a')
        drag('w')
        release()
        self.assertEqual((profile.colors['w'], profile.colors['a']), ('ff0000', 'ff0000'))
        press('w')
        drag('a')
        drag('w')
        release()
        self.assertEqual((profile.colors['w'], profile.colors['a']), ('000000', '000000'))
        press('w')
        release()
        self.assertEqual(profile.colors['w'], 'ff0000')
        doubled = SimpleNamespace(button=1, x='w', y=0, type=Gdk.EventType.DOUBLE_BUTTON_PRESS)
        self.assertFalse(KeyboardPreview.press(preview, None, doubled))
        self.assertEqual(profile.colors['w'], 'ff0000')

    def test_refresh_uses_last_applied_snapshot_and_stops_when_disabled(self):
        from main import LightingWindow
        snapshot = LightingProfile()
        snapshot.set_key('w', 'ff0000')
        device = Device('G515', '046d', 'c358')
        jobs, callbacks = [], []
        def submit(work):
            future = Future()
            jobs.append((work, future))
            return future
        window = SimpleNamespace(closed=False, busy=False, applied_lighting=('/controller', device, snapshot),
                                 keepalive_source=0, keepalive_generation=0, keepalive_future=None,
                                 activity_monitor=None, activity_restore_source=0,
                                 on_g515_activity=Mock(), on_g515_activity_error=Mock(),
                                 keepalive_toggle=SimpleNamespace(get_active=lambda: True),
                                 executor=SimpleNamespace(submit=submit), set_status=Mock())
        window.stop_keepalive = lambda: LightingWindow.stop_keepalive(window)
        window.refresh_applied_lighting = lambda: LightingWindow.refresh_applied_lighting(window)
        fake_controller = Mock()
        with patch('main.GLib.timeout_add_seconds', return_value=77) as schedule, \
                patch('main.GLib.source_remove') as remove, \
                patch('main.GLib.idle_add', side_effect=lambda fn, *args: callbacks.append((fn, args))), \
                patch('main.Controller', return_value=fake_controller), \
                patch('main.G515ActivityMonitor') as monitor_factory:
            LightingWindow.start_keepalive(window)
            schedule.assert_called_once_with(15, window.refresh_applied_lighting)
            self.assertTrue(LightingWindow.refresh_applied_lighting(window))
            self.assertEqual(len(jobs), 1)
            self.assertTrue(LightingWindow.refresh_applied_lighting(window))
            self.assertEqual(len(jobs), 1)  # no overlapping refreshes
            work, future = jobs.pop()
            work()
            fake_controller.apply.assert_called_once_with(device, snapshot)
            future.set_result(None)
            callback, args = callbacks.pop()
            self.assertFalse(callback(*args))
            monitor_factory.return_value.rearm_notifications.assert_called_once()
            LightingWindow.stop_keepalive(window)
            monitor_factory.return_value.close.assert_called_once()
            remove.assert_called_once_with(77)
            self.assertEqual(window.keepalive_source, 0)

    def test_queued_refresh_cannot_reapply_after_stop(self):
        from main import LightingWindow
        future = Future()
        jobs = []
        window = SimpleNamespace(closed=False, busy=False,
                                 applied_lighting=('/controller', Device('G515', '046d', 'c358'), LightingProfile()),
                                 keepalive_source=1, keepalive_generation=0, keepalive_future=None,
                                 activity_monitor=None, activity_restore_source=0,
                                 keepalive_toggle=SimpleNamespace(get_active=lambda: True),
                                 executor=SimpleNamespace(submit=lambda work: (jobs.append(work), future)[1]),
                                 set_status=Mock())
        with patch('main.GLib.source_remove'), patch('main.Controller') as controller:
            self.assertTrue(LightingWindow.refresh_applied_lighting(window))
            LightingWindow.stop_keepalive(window)
            jobs[0]()
            controller.assert_not_called()

    def test_wake_event_schedules_one_restoration_and_waits_for_busy_work(self):
        from main import LightingWindow
        window = SimpleNamespace(closed=False, keepalive_generation=4, keepalive_source=12,
                                 activity_restore_source=0, busy=True, keepalive_future=None,
                                 refresh_applied_lighting=Mock())
        window.restore_after_g515_wake = lambda generation: LightingWindow.restore_after_g515_wake(window, generation)
        with patch('main.GLib.timeout_add', return_value=88) as schedule:
            self.assertFalse(LightingWindow.on_g515_activity(window, 4))
            self.assertEqual(window.activity_restore_source, 88)
            self.assertFalse(LightingWindow.on_g515_activity(window, 4))
            schedule.assert_called_once_with(100, window.restore_after_g515_wake, 4)
            self.assertTrue(LightingWindow.restore_after_g515_wake(window, 4))
            window.busy = False
            self.assertFalse(LightingWindow.restore_after_g515_wake(window, 4))
            self.assertEqual(window.activity_restore_source, 0)
            window.refresh_applied_lighting.assert_called_once()
            self.assertFalse(LightingWindow.on_g515_activity(window, 3))
            self.assertEqual(schedule.call_count, 1)

    def test_profile_roundtrip_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'
            original = LightingProfile()
            original.set_key('space', '112233')
            original.set_brightness(37)
            original.save(path)
            restored = LightingProfile.load(path)
            self.assertEqual(restored.colors, original.colors)
            self.assertEqual(restored.brightness, 37)
            legacy = json.loads(path.read_text())
            del legacy['brightness']
            path.write_text(json.dumps(legacy))
            self.assertEqual(LightingProfile.load(path).brightness, 100)
            original.save(path)
            invalid = json.loads(path.read_text())
            invalid['colors']['space'] = 'ffffff\nc'
            path.write_text(json.dumps(invalid))
            with self.assertRaises(ValueError):
                LightingProfile.load(path)

    def test_parse_devices_and_target_selected_keyboard(self):
        output = ('Device: Logitech - G515 TKL\n\tVendor ID: 046d\n'
                  '\tProduct ID: c358\n\tSerial Number: ABC123\n')
        self.assertEqual(parse_devices(output), [Device('Logitech - G515 TKL', '046d', 'c358', 'ABC123')])
        result = SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch('controller.subprocess.run', return_value=result) as run:
            Controller('/tmp/fake-controller').apply(Device('G515', '046d', 'c358', 'ABC123'), LightingProfile())
        args = run.call_args.args[0]
        self.assertEqual(args, ['/tmp/fake-controller', '-dv', '046d', '-dp', 'c358', '-ds', 'ABC123', '-pp'])
        self.assertTrue(run.call_args.kwargs['input'].endswith('c\n'))
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_failures_are_reported_without_running_as_root(self):
        result = SimpleNamespace(returncode=-11, stdout='', stderr='')
        with patch('controller.subprocess.run', return_value=result):
            with self.assertRaisesRegex(ControllerError, 'crashed.*signal 11'):
                Controller('/tmp/fake-controller').devices()
        denied = SimpleNamespace(returncode=2, stdout='Access denied', stderr='Cannot open device: Permission denied')
        with patch('controller.subprocess.run', return_value=denied):
            with self.assertRaisesRegex(ControllerError, 'Permission denied'):
                Controller('/tmp/fake-controller').apply(Device('G515', '046d', 'c358'), LightingProfile())

    def test_controller_profiles_reach_a_real_child_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / 'g810-led'
            capture = root / 'capture'
            fake.write_text('#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\n'
                            f'Path({str(capture)!r}).write_text(sys.stdin.read())\n')
            fake.chmod(0o700)
            Controller(str(fake)).apply(Device('Keyboard', '046d', 'c358'), LightingProfile())
            text = capture.read_text()
            self.assertIn('k space ', text)
            self.assertTrue(text.endswith('c\n'))


if __name__ == '__main__':
    unittest.main()
