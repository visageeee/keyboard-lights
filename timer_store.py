"""Countdown state and the temporary lighting overlay."""
import fcntl
import json
import math
import time
import uuid

from controller import Device
from model import KEYS, LightingProfile
import background_keeper

TOP_KEYS = tuple(key.name for key in KEYS if key.y == 0)
ALARM_SECONDS = 30
TIMER_BLUE = '0066ff'


def path():
    return background_keeper.config_root() / 'keyboard-lights' / 'timer.json'


def start(executable, device, profile, seconds, now=None):
    if not 1 <= seconds <= 24 * 3600:
        raise ValueError('Choose a duration between 1 second and 24 hours.')
    now = time.time() if now is None else now
    data = {'version': 1, 'id': uuid.uuid4().hex, 'start': now, 'end': now + seconds,
            'executable': executable, 'device': vars(device),
            'profile': {'colors': dict(profile.colors), 'brightness': profile.brightness}}
    background_keeper._write_atomic(path(), json.dumps(data) + '\n')
    return data


def load():
    try:
        if path().stat().st_size > 100000:
            return None
        data = json.loads(path().read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1:
            return None
        if (not isinstance(data.get('id'), str) or len(data['id']) != 32 or
                not isinstance(data.get('start'), (int, float)) or not isinstance(data.get('end'), (int, float)) or
                not math.isfinite(data['start']) or not math.isfinite(data['end']) or
                not 1 <= data['end'] - data['start'] <= 86400):
            return None
        raw = data['device']
        device = Device(raw['name'], raw['vendor'], raw['product'], raw.get('serial', ''))
        if not all(isinstance(v, str) and '\0' not in v and len(v) <= 1024 for v in vars(device).values()):
            return None
        if (len(device.vendor) != 4 or len(device.product) != 4 or
                any(c not in '0123456789abcdefABCDEF' for c in device.vendor + device.product)):
            return None
        executable = data['executable']
        if not isinstance(executable, str) or not executable or '\0' in executable or len(executable) > 4096:
            return None
        raw_profile = data['profile']
        profile = LightingProfile(raw_profile['colors'], raw_profile['brightness'])
        return data, executable, device, profile
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cancel(identifier=None):
    if identifier is not None:
        existing = load()
        if existing is None or existing[0]['id'] != identifier:
            return
    try:
        path().unlink()
    except FileNotFoundError:
        pass


def overlay(data, profile, now):
    """Return a frame and its discrete state, or None after the alarm."""
    left = data['end'] - now
    if left <= -ALARM_SECONDS:
        return None, ('finished',)
    result = LightingProfile(dict(profile.colors), profile.brightness)
    if left > 0:
        count = max(0, min(len(TOP_KEYS), math.ceil(left / (data['end'] - data['start']) * len(TOP_KEYS))))
        for index, key in enumerate(TOP_KEYS):
            result.set_key(key, TIMER_BLUE if index < count else '000000')
        return result, ('countdown', count)
    on = int(-left * 2) % 2 == 0
    for key in TOP_KEYS:
        result.set_key(key, 'ff0000' if on else '000000')
    return result, ('alarm', on)


def start_service(executable, device, profile, seconds):
    """Replace any older keeper process before handing it a timer overlay."""
    directory = background_keeper.config_path().parent
    directory.mkdir(parents=True, exist_ok=True)
    config = background_keeper.config_path()
    with (directory / 'keeper.lock').open('a') as lock:
        paused = None
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                try:
                    current_version = (directory / 'keeper.version').read_text(encoding='utf-8')
                except OSError:
                    current_version = ''
                if current_version == '7':
                    # The active helper understands timer files already.
                    start(executable, device, profile, seconds)
                    return
                # Older helper versions do not know about timer overlays. Ask them
                # to stop using their existing configuration protocol, then wait.
                try:
                    paused = config.read_text(encoding='utf-8')
                except FileNotFoundError:
                    paused = None
                if paused is not None:
                    background_keeper._write_atomic(config, '{"version": 1, "enabled": false}\n')
                # An older helper may be kept alive by a previous timer even
                # with the keeper disabled. End that timer before upgrading.
                cancel()
                deadline = time.monotonic() + 10
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise OSError('The lighting helper is busy; try again shortly.')
                        time.sleep(.1)
            if paused is not None:
                background_keeper._write_atomic(config, paused)
                paused = None
            data = start(executable, device, profile, seconds)
        finally:
            if paused is not None:
                background_keeper._write_atomic(config, paused)
            fcntl.flock(lock, fcntl.LOCK_UN)
    try:
        background_keeper.launch()
    except OSError:
        cancel(data['id'])
        raise
