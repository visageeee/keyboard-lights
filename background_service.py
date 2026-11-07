#!/usr/bin/env python3
"""Reapply the last selected lighting in the user's desktop session."""
import fcntl
import os
import signal
import threading
import time

import background_keeper
import timer_store
from controller import Controller, ControllerError
from g515_activity import G515ActivityMonitor


def run():
    path = background_keeper.config_path().parent
    path.mkdir(parents=True, exist_ok=True)
    with (path / 'keeper.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        version_file = path / 'keeper.version'
        version_file.write_text('3', encoding='utf-8')
        stopping = threading.Event()
        wake = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stopping.set())
        signal.signal(signal.SIGINT, lambda *_: stopping.set())
        monitor = None
        identity = None
        next_apply = 0
        last_timer = None
        output_state = None
        attempted_state = None
        try:
            while not stopping.is_set():
                current = background_keeper.load()
                timer = timer_store.load()
                if timer:
                    data, executable, device, base = timer
                    frame, frame_state = timer_store.overlay(data, base, time.time())
                    if frame is None:
                        timer_store.cancel(data['id'])
                        timer = None
                    else:
                        last_timer = (executable, device, base)
                        current = (executable, device, frame)
                        frame_state = (data['id'], *frame_state)
                if not timer:
                    frame_state = None
                    if last_timer:
                        # Restore the design after cancel or the alarm.
                        current = current or last_timer
                    elif current is None:
                        break
                executable, device, profile = current
                fingerprint = (executable, device)
                if fingerprint != identity:
                    if monitor:
                        monitor.close()
                        if monitor.thread:
                            monitor.thread.join(timeout=3)
                        monitor = None
                    identity = fingerprint
                    wake.clear()
                    next_apply = 0
                    output_state = None
                    attempted_state = None
                state = (profile.brightness, tuple(sorted(profile.colors.items())), frame_state)
                if state != attempted_state:
                    next_apply = 0
                now = time.monotonic()
                if wake.is_set():
                    wake.clear()
                    # Give the firmware a moment to finish its wake transition.
                    stopping.wait(.1)
                    next_apply = 0
                if now >= next_apply:
                    attempted_state = state
                    try:
                        Controller(executable).apply(device, profile)
                    except (ControllerError, OSError):
                        # Devices can be disconnected at login; retry when they return.
                        if monitor:
                            monitor.close()
                            monitor = None
                    else:
                        output_state = state
                        if not timer and last_timer:
                            last_timer = None
                        if (device.vendor, device.product) == ('046d', 'c358'):
                            if monitor and monitor.thread and not monitor.thread.is_alive():
                                monitor.close()
                                monitor = None
                            if monitor is None:
                                monitor = G515ActivityMonitor(device, wake.set, lambda _error: None)
                                monitor.start()
                            else:
                                monitor.rearm_notifications()
                    next_apply = time.monotonic() + 15
                # Also pick up changed profiles and disable requests without a GUI.
                stopping.wait(.25)
        finally:
            if monitor:
                monitor.close()
            try:
                version_file.unlink()
            except FileNotFoundError:
                pass


if __name__ == '__main__':
    run()
