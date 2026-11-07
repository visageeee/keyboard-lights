"""Optional X11 workspace indicator for the F1–F12 keys."""
import json
import os
from pathlib import Path
import re
import subprocess
import threading

import background_keeper
from model import LightingProfile, validate_color


def path():
    return background_keeper.config_root() / 'keyboard-lights' / 'workspace.json'


def load():
    try:
        if path().stat().st_size > 4096:
            return False, '57cdc5'
        data = json.loads(path().read_text(encoding='utf-8'))
        if data.get('version') != 1 or type(data.get('enabled')) is not bool:
            return False, '57cdc5'
        return data['enabled'], validate_color(data.get('color'))
    except (OSError, ValueError, TypeError, AttributeError):
        return False, '57cdc5'


def save(enabled, color):
    if type(enabled) is not bool:
        raise ValueError('Invalid workspace indicator setting.')
    data = {'version': 1, 'enabled': enabled, 'color': validate_color(color)}
    background_keeper._write_atomic(path(), json.dumps(data) + '\n')


def parse_workspace(line):
    match = re.fullmatch(r'\s*_NET_CURRENT_DESKTOP\(CARDINAL\)\s*=\s*(\d+)\s*', line)
    if not match:
        return None
    index = int(match.group(1))
    return index + 1 if 0 <= index < 12 else None


def overlay(profile, workspace, color):
    copy = LightingProfile(dict(profile.colors), profile.brightness)
    if type(workspace) is int and 1 <= workspace <= 12:
        copy.set_key(f'f{workspace}', color)
    return copy


def supported_session():
    return os.environ.get('XDG_SESSION_TYPE', '').lower() != 'wayland' and bool(os.environ.get('DISPLAY'))


class WorkspaceMonitor:
    """Watch EWMH workspace changes without recording keyboard input."""
    def __init__(self, on_change):
        self.on_change = on_change
        self.process = None
        self.closed = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name='workspace-indicator')
        self.thread.start()

    def close(self):
        self.closed.set()
        if self.process is not None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass

    def _run(self):
        if not supported_session():
            self.on_change(None)
            return
        try:
            self.process = subprocess.Popen(['xprop', '-spy', '-root', '_NET_CURRENT_DESKTOP'],
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            text=True, bufsize=1)
            if self.closed.is_set():
                self.process.terminate()
            for line in self.process.stdout:
                if self.closed.is_set():
                    break
                self.on_change(parse_workspace(line))
        except OSError:
            self.on_change(None)
        finally:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.terminate()
                self.process.wait()
                if not self.closed.is_set():
                    self.on_change(None)
