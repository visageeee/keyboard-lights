#!/usr/bin/env python3
"""Reapply the last selected lighting in the user's desktop session."""
import fcntl
import os
import signal
import threading
import time

import background_keeper
import timer_store
import timer_chime
import workspace_indicator
from controller import Controller, ControllerError
from g515_activity import G515ActivityMonitor
from model import LightingProfile


def run():
    path = background_keeper.config_path().parent
    path.mkdir(parents=True, exist_ok=True)
    with (path / 'keeper.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        version_file = path / 'keeper.version'
        version_file.write_text('7', encoding='utf-8')
        stopping = threading.Event()
        wake = threading.Event()
        idle = threading.Event()
        is_idle = False
        signal.signal(signal.SIGTERM, lambda *_: stopping.set())
        signal.signal(signal.SIGINT, lambda *_: stopping.set())
        monitor = None
        workspace_monitor = None
        workspace = [None]
        identity = None
        next_apply = 0
        last_timer = None
        output_state = None
        attempted_state = None
        chimed = set()
        try:
            while not stopping.is_set():
                current = background_keeper.load()
                idle_seconds = background_keeper.idle_delay() if current else None
                timer = timer_store.load()
                workspace_enabled, workspace_color = workspace_indicator.load()
                if current and workspace_enabled and workspace_monitor is None:
                    workspace_monitor = workspace_indicator.WorkspaceMonitor(lambda index: workspace.__setitem__(0, index))
                    workspace_monitor.start()
                elif (not current or not workspace_enabled) and workspace_monitor is not None:
                    workspace_monitor.close()
                    workspace_monitor = None
                    workspace[0] = None
                if timer:
                    data, executable, device, base = timer
                    frame, frame_state = timer_store.overlay(data, base, time.time())
                    if frame is None:
                        timer_store.cancel(data['id'])
                        timer = None
                    else:
                        if frame_state[0] == 'alarm' and data['id'] not in chimed:
                            chimed.add(data['id'])
                            timer_chime.notify_once(data['id'])
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
                fingerprint = (executable, device, idle_seconds)
                if fingerprint != identity:
                    if monitor:
                        monitor.close()
                        if monitor.thread:
                            monitor.thread.join(timeout=3)
                        monitor = None
                    identity = fingerprint
                    wake.clear()
                    idle.clear()
                    is_idle = False
                    next_apply = 0
                    output_state = None
                    attempted_state = None
                if idle.is_set():
                    idle.clear()
                    if idle_seconds and not timer:
                        is_idle = True
                if wake.is_set():
                    wake.clear()
                    is_idle = False
                    # Let the firmware finish its transition before restoring.
                    stopping.wait(.1)
                    next_apply = 0
                if timer:
                    is_idle = False
                if is_idle and not timer:
                    profile = LightingProfile(dict(profile.colors), profile.brightness)
                    profile.set_all('000000')
                if workspace_enabled and current and not is_idle and not timer:
                    profile = workspace_indicator.overlay(profile, workspace[0], workspace_color)
                state = (profile.brightness, tuple(sorted(profile.colors.items())), frame_state)
                if state != attempted_state:
                    next_apply = 0
                now = time.monotonic()
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
                                monitor = G515ActivityMonitor(device, wake.set, lambda _error: None,
                                                              idle.set if idle_seconds else None, idle_seconds)
                                monitor.start()
                            else:
                                monitor.rearm_notifications()
                    next_apply = time.monotonic() + 15
                # Also pick up changed profiles and disable requests without a GUI.
                stopping.wait(.25)
        finally:
            if monitor:
                monitor.close()
            if workspace_monitor:
                workspace_monitor.close()
            try:
                version_file.unlink()
            except FileNotFoundError:
                pass


if __name__ == '__main__':
    run()
