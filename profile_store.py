"""Locally managed lighting profiles, independent of the active keyboard."""
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from model import LightingProfile


def default_path():
    root = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return root / 'keyboard-lights' / 'profiles.json'


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
        raise ValueError('Profile names must be 1–80 characters.')
    return value.strip()


class ProfileStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_path()
        self.entries = []
        self.selected = None
        self.read_only = False
        self.load_error = None
        self._load()

    def _load(self):
        try:
            if self.path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('Profile library is too large.')
            with self.path.open(encoding='utf-8') as stream:
                data = json.load(stream)
            if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('profiles'), list):
                raise ValueError('Invalid profile library.')
            seen, names = set(), set()
            for item in data['profiles']:
                if not isinstance(item, dict):
                    raise ValueError('Invalid profile entry.')
                identifier, name = item.get('id'), _name(item.get('name'))
                if (not isinstance(identifier, str) or len(identifier) != 32 or
                        any(ch not in '0123456789abcdef' for ch in identifier) or
                        identifier in seen or name.casefold() in names):
                    raise ValueError('Invalid or duplicate profile.')
                if not isinstance(item.get('colors'), dict):
                    raise ValueError('Invalid profile colors.')
                profile = LightingProfile(item['colors'], item.get('brightness', 100))
                self.entries.append({'id': identifier, 'name': name, 'profile': profile})
                seen.add(identifier)
                names.add(name.casefold())
            self.selected = data.get('selected') if data.get('selected') in seen else None
            if not self.entries:
                raise ValueError('Profile library is empty.')
            self.selected = self.selected or self.entries[0]['id']
        except FileNotFoundError:
            self._make_default()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            # Never replace an unreadable or corrupt profile library with defaults.
            self.entries = []
            self._make_default()
            self.read_only = True
            self.load_error = str(error)

    def _make_default(self):
        entry = {'id': uuid4().hex, 'name': 'Default', 'profile': LightingProfile()}
        self.entries.append(entry)
        self.selected = entry['id']

    def current(self):
        return next(entry for entry in self.entries if entry['id'] == self.selected)

    def _unique_name(self, name, except_id=None):
        name = _name(name)
        if any(entry['name'].casefold() == name.casefold() and entry['id'] != except_id
               for entry in self.entries):
            raise ValueError('A profile with this name already exists.')
        return name

    def create(self, name, profile):
        name = self._unique_name(name)
        copy = LightingProfile(dict(profile.colors), profile.brightness)
        entry = {'id': uuid4().hex, 'name': name, 'profile': copy}
        self.entries.append(entry)
        self.selected = entry['id']
        return entry

    def rename(self, identifier, name):
        name = self._unique_name(name, identifier)
        entry = next(entry for entry in self.entries if entry['id'] == identifier)
        entry['name'] = name

    def delete(self, identifier):
        if len(self.entries) <= 1:
            raise ValueError('Keep at least one profile.')
        index = next(i for i, entry in enumerate(self.entries) if entry['id'] == identifier)
        del self.entries[index]
        if self.selected == identifier:
            self.selected = self.entries[min(index, len(self.entries) - 1)]['id']

    def save(self):
        if self.read_only:
            raise OSError('The existing profile library could not be read; it was left unchanged.')
        data = {'version': 1, 'selected': self.selected,
                'profiles': [{'id': e['id'], 'name': e['name'], 'colors': e['profile'].colors,
                              'brightness': e['profile'].brightness} for e in self.entries]}
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix='.profiles-', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
