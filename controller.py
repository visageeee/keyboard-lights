"""Non-shell adapter for the g810-led command line tool."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess


@dataclass(frozen=True)
class Device:
    name: str
    vendor: str
    product: str
    serial: str = ''

    @property
    def label(self):
        return f'{self.name} ({self.vendor}:{self.product})'


def default_controller():
    # Both the source checkout and installed app put the bundled build here.
    bundled = Path(__file__).resolve().parent / 'vendor/g810-led/bin/g810-led'
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    return shutil.which('g810-led') or 'g810-led'


def parse_devices(output):
    devices, current = [], None
    def finish():
        if current and re.fullmatch(r'[0-9a-fA-F]{4}', current.get('vendor', '')) and \
                re.fullmatch(r'[0-9a-fA-F]{4}', current.get('product', '')):
            devices.append(Device(current['name'], current['vendor'].lower(),
                                  current['product'].lower(), current.get('serial', '')))
    for line in output.splitlines():
        text = line.strip()
        if text.startswith('Device:'):
            finish()
            current = {'name': text.partition(':')[2].strip() or 'Keyboard'}
        elif current is not None:
            for label, field in [('Vendor ID:', 'vendor'), ('Product ID:', 'product'),
                                 ('Serial Number:', 'serial')]:
                if text.startswith(label):
                    current[field] = text[len(label):].strip()
    finish()
    return devices


class ControllerError(Exception):
    pass


class Controller:
    def __init__(self, executable):
        self.executable = executable
        self.notice = ""

    def run(self, args, *, input_text=None, timeout=15):
        try:
            result = subprocess.run([self.executable, *args], input=input_text, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=timeout, check=False, cwd='/tmp')
        except FileNotFoundError as error:
            raise ControllerError('Controller not found. Choose a g810-led executable.') from error
        except PermissionError as error:
            raise ControllerError('The controller executable is not accessible.') from error
        except subprocess.TimeoutExpired as error:
            raise ControllerError('The controller timed out. Check the device connection.') from error
        if result.returncode < 0:
            raise ControllerError(f'The controller crashed (signal {-result.returncode}). Check or rebuild the g810-led backend.')
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            if len(detail) > 350:
                detail = detail[:350] + '…'
            raise ControllerError(detail or f'Controller failed (exit {result.returncode}).')
        return result.stdout

    def devices(self):
        try:
            return parse_devices(self.run(['--list-keyboards'], timeout=10))
        except ControllerError as error:
            # Some development builds crash during libusb enumeration, even
            # though their G515-specific HID backend is available. Only use
            # the sysfs fallback if this executable explicitly advertises it.
            if 'crashed (signal ' not in str(error) or 'G515 TKL' not in self.run(['--help']):
                raise
            found = []
            for uevent in Path('/sys/class/hidraw').glob('hidraw*/device/uevent'):
                try:
                    fields = dict(line.split('=', 1) for line in uevent.read_text().splitlines() if '=' in line)
                except OSError:
                    continue
                if (fields.get('HID_ID') == '0003:0000046D:0000C358' and
                        fields.get('HID_PHYS', '').endswith('/input2')):
                    device = Device('Logitech G515 TKL', '046d', 'c358', fields.get('HID_UNIQ', ''))
                    if device not in found:
                        found.append(device)
            if not found:
                raise error
            self.notice = 'Detected G515 via Linux; controller listing crashed. Device access may still be required.'
            return found

    def apply(self, device, profile):
        args = ['-dv', device.vendor, '-dp', device.product]
        if device.serial:
            args += ['-ds', device.serial]
        self.run([*args, '-pp'], input_text=profile.controller_profile(), timeout=90)
