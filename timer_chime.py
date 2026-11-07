"""Play one short desktop chime when a keyboard timer finishes."""
from pathlib import Path
import shutil
import subprocess
import threading

import background_keeper


def _play():
    sound = Path(__file__).resolve().with_name('chime.ogg')
    if not sound.is_file():
        return
    # These players decode Ogg Vorbis and output through the desktop session.
    for name, arguments in (('paplay', ()), ('pw-play', ()),
                            ('ogg123', ('-q',)),
                            ('ffplay', ('-nodisp', '-autoexit', '-loglevel', 'quiet'))):
        program = shutil.which(name)
        if not program:
            continue
        try:
            result = subprocess.run([program, *arguments, str(sound)], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=60, check=False)
            if result.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass


def notify_once(timer_id):
    """Remember the timer ID across helper restarts and play without blocking."""
    marker = background_keeper.config_path().parent / 'last-chimed-timer'
    try:
        if marker.read_text(encoding='utf-8').strip() == timer_id:
            return False
    except OSError:
        pass
    try:
        background_keeper._write_atomic(marker, timer_id + '\n')
    except OSError:
        # The caller still suppresses repeats in the current process.
        pass
    threading.Thread(target=_play, name='timer-chime', daemon=True).start()
    return True
