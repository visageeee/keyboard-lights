#!/usr/bin/env python3
"""Install Keyboard Lights into the current user's XDG directories."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import background_keeper

APP_FILES = ('main.py', 'controller.py', 'model.py', 'profile_store.py',
             'background_keeper.py', 'background_service.py', 'g515_activity.py',
             'timer.py', 'timer_store.py', 'timer_chime.py', 'g515_onboard.py', 'workspace_indicator.py')
MARKER = '# Installed by Keyboard Lights\n'
SOURCE = Path(__file__).resolve().parent


def write_owned(path, content, marker, executable=False):
    if path.exists() and marker not in path.read_text(encoding='utf-8'):
        raise OSError(f'Refusing to overwrite an existing file: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    background_keeper._write_atomic(path, content)
    path.chmod(0o755 if executable else 0o644)


def install():
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    binary = Path(os.environ.get('XDG_BIN_HOME') or Path.home() / '.local/bin')
    destination = data / 'keyboard-lights'
    desktop = data / 'applications/keyboard-lights.desktop'
    icon = data / 'icons/hicolor/scalable/apps/keyboard-lights.svg'
    python = Path('/usr/bin/python3')
    if not python.exists():
        raise OSError('/usr/bin/python3 is required for GTK on this installation')
    if destination.exists() and not (destination / '.keyboard-lights-install').is_file():
        raise OSError(f'Refusing to overwrite an existing directory: {destination}')
    for file in (desktop, binary / 'keyboard-lights', binary / 'keyboard-lights-timer'):
        if file.exists() and MARKER.strip() not in file.read_text(encoding='utf-8'):
            raise OSError(f'Refusing to overwrite an existing file: {file}')
    if icon.exists() and '<!-- Keyboard Lights icon -->' not in icon.read_text(encoding='utf-8'):
        raise OSError(f'Refusing to overwrite an existing file: {icon}')
    build = subprocess.run(['make', '-C', str(SOURCE / 'vendor/g810-led'), 'bin', 'LIB=libusb'], check=False)
    if build.returncode:
        raise OSError('Could not build the bundled controller. Install make, g++ and libusb development headers.')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / '.keyboard-lights-install').write_text('Keyboard Lights user installation\n', encoding='utf-8')
    for name in APP_FILES:
        shutil.copy2(SOURCE / name, destination / name)
    shutil.copy2(SOURCE / 'chime.ogg', destination / 'chime.ogg')
    shutil.copy2(SOURCE / 'LICENSE-logirgb', destination / 'LICENSE-logirgb')
    bundled_bin = destination / 'vendor/g810-led/bin'
    bundled_bin.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE / 'vendor/g810-led/bin/g810-led', bundled_bin / 'g810-led')
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_text('<!-- Keyboard Lights icon -->\n' + (SOURCE / 'keyboard-lights.svg').read_text(encoding='utf-8'), encoding='utf-8')
    for name, module in (('keyboard-lights', 'main.py'), ('keyboard-lights-timer', 'timer.py')):
        script = '#!/bin/sh\n' + MARKER + f'exec {shlex.quote(str(python))} {shlex.quote(str(destination / module))} "$@"\n'
        write_owned(binary / name, script, MARKER.strip(), executable=True)
    # Desktop Entry Exec has its own quoting rules, not shell quoting.
    exec_line = ' '.join(background_keeper._desktop_arg(str(value)) for value in (python, destination / 'main.py'))
    entry = ('[Desktop Entry]\n' + MARKER + 'Type=Application\nName=Keyboard Lights\n'
             'Comment=Control keyboard lighting and timers\n'
             f'Exec={exec_line}\nIcon=keyboard-lights\nTerminal=false\n'
             'Categories=Settings;HardwareSettings;\nStartupNotify=true\nStartupWMClass=keyboard-lights\n')
    write_owned(desktop, entry, MARKER.strip())
    # Point an already-enabled autostart at the installed copy without starting
    # or stopping the user's existing helper, or changing its configuration.
    auto = background_keeper.autostart_path()
    if background_keeper.load() and auto.exists():
        old = auto.read_text(encoding='utf-8')
        if 'Name=Keyboard Lights background service' in old:
            command = ' '.join(background_keeper._desktop_arg(str(v)) for v in (python, destination / 'background_service.py'))
            lines = [('Exec=' + command) if line.startswith('Exec=') else line for line in old.splitlines()]
            background_keeper._write_atomic(auto, '\n'.join(lines) + '\n')
    print(f'Installed Keyboard Lights in {destination}')
    print('Open “Keyboard Lights” from your applications menu.')
    print(f'Timer command: {binary / "keyboard-lights-timer"} start 25m')
    if str(binary) not in os.environ.get('PATH', '').split(os.pathsep):
        print(f'Add {binary} to PATH to use the timer command without its full path.')


if __name__ == '__main__':
    try:
        install()
    except (OSError, ValueError) as error:
        print(f'Install failed: {error}', file=sys.stderr)
        sys.exit(1)
