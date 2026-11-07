import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from model import LightingProfile
from profile_store import ProfileStore


class ProfileStoreTests(unittest.TestCase):
    def test_create_select_edit_restart_rename_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings' / 'profiles.json'
            store = ProfileStore(path)
            self.assertEqual(store.current()['name'], 'Default')
            source = store.current()['profile']
            source.set_key('w', 'ff0000')
            source.set_brightness(37)
            copy = store.create('  Gaming  ', source)
            copy['profile'].set_key('w', '00ff00')
            self.assertEqual(source.colors['w'], 'ff0000')
            store.save()
            reloaded = ProfileStore(path)
            self.assertEqual(reloaded.current()['name'], 'Gaming')
            self.assertEqual(reloaded.current()['profile'].colors['w'], '00ff00')
            self.assertEqual(reloaded.current()['profile'].brightness, 37)
            reloaded.rename(reloaded.selected, 'Gaming 2')
            reloaded.save()
            reloaded = ProfileStore(path)
            self.assertEqual(reloaded.current()['name'], 'Gaming 2')
            reloaded.delete(reloaded.selected)
            self.assertEqual(reloaded.current()['name'], 'Default')
            with self.assertRaises(ValueError):
                reloaded.delete(reloaded.selected)

    def test_duplicate_names_and_invalid_profiles_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / 'profiles.json')
            with self.assertRaises(ValueError):
                store.create('default', LightingProfile())
            with self.assertRaises(ValueError):
                store.create(' ', LightingProfile())
            with self.assertRaises(ValueError):
                store.create('x' * 81, LightingProfile())

    def test_corrupt_library_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            path.write_text('{not json')
            store = ProfileStore(path)
            self.assertTrue(store.read_only)
            self.assertTrue(store.load_error)
            with self.assertRaises(OSError):
                store.save()
            self.assertEqual(path.read_text(), '{not json')

    def test_save_failure_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            store = ProfileStore(path)
            store.save()
            original = path.read_bytes()
            store.current()['profile'].set_key('w', 'ff0000')
            with patch('profile_store.os.replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    store.save()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob('.profiles-*')), [])

    def test_imported_old_profile_remains_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.json'
            source = LightingProfile()
            source.set_brightness(22)
            source.save(path)
            store = ProfileStore(Path(directory) / 'profiles.json')
            store.create('Imported', LightingProfile.load(path))
            store.save()
            self.assertEqual(ProfileStore(store.path).current()['profile'].brightness, 22)


if __name__ == '__main__':
    unittest.main()
