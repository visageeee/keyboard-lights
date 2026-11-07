"""Persistence and desktop autostart for the optional lighting keeper."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from controller import Device
from model import LightingProfile


def config_root():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')


def config_path():
    return config_root() / 'keyboard-lights' / 'keeper.json'


def autostart_path():
    return config_root() / 'autostart' / 'keyboard-lights-keeper.desktop'


def _write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.keyboard-lights-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read():
    try:
        path = config_path()
        if path.stat().st_size > 100000:
            return None
        with path.open(encoding='utf-8') as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) and value.get('version') == 1 else None
    except (OSError, ValueError):
        return None


def enabled():
    data = _read()
    return data.get('enabled') is True if data is not None else not config_path().exists()


def load(include_disabled=False):
    data = _read()
    if not data or (not include_disabled and data.get('enabled') is not True):
        return None
    try:
        executable, raw, profile = data['executable'], data['device'], data['profile']
        if not isinstance(executable, str) or not executable or '\0' in executable or len(executable) > 4096:
            return None
        if not isinstance(raw, dict) or any(not isinstance(raw.get(k, ''), str) or '\0' in raw.get(k, '') or len(raw.get(k, '')) > 1024 for k in ('name', 'vendor', 'product', 'serial')):
            return None
        if not all(re.fullmatch('[0-9a-fA-F]{4}', raw.get(k, '')) for k in ('vendor', 'product')):
            return None
        device = Device(raw.get('name', 'Keyboard'), raw['vendor'].lower(), raw['product'].lower(), raw.get('serial', ''))
        return executable, device, LightingProfile(profile['colors'], profile['brightness'])
    except (KeyError, TypeError, ValueError):
        return None


def _desktop_arg(value):
    if any(c in value for c in '\n\r\0'):
        raise ValueError('Invalid autostart path')
    for old, new in (('\\', '\\\\'), ('"', '\\"'), ('`', '\\`'), ('$', '\\$'), ('%', '%%')):
        value = value.replace(old, new)
    return '"' + value + '"'


def save_applied(executable, device, profile, enabled=False):
    # Keep the last applied snapshot even when the optional keeper is disabled.
    data = {'version': 1, 'enabled': enabled, 'executable': executable,
            'device': vars(device), 'profile': {'colors': dict(profile.colors), 'brightness': profile.brightness}}
    _write_atomic(config_path(), json.dumps(data, sort_keys=True) + '\n')


def enable(executable, device, profile):
    script = str(Path(__file__).resolve().with_name('background_service.py'))
    desktop = ('[Desktop Entry]\nType=Application\nName=Keyboard Lights background service\n'
               f'Exec={_desktop_arg(sys.executable)} {_desktop_arg(script)}\n'
               'Terminal=false\nX-GNOME-Autostart-enabled=true\n')
    save_applied(executable, device, profile, enabled=True)
    _write_atomic(autostart_path(), desktop)
    return launch()


def launch():
    script = str(Path(__file__).resolve().with_name('background_service.py'))
    return subprocess.Popen([sys.executable, script], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            close_fds=True, start_new_session=True)


def disable():
    # The running helper observes this file and exits; no PID or process name guessing.
    data = _read() or {'version': 1}
    data['enabled'] = False
    _write_atomic(config_path(), json.dumps(data, sort_keys=True) + '\n')
    try:
        autostart_path().unlink()
    except FileNotFoundError:
        pass
