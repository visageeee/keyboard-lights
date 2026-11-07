"""Experimental wired G515 onboard solid color.

Protocol and layout adapted from logirgb, copyright 2026 Maurits van der
Schee, MIT license; see LICENSE-logirgb. Only c358 is supported.
"""
import fcntl
import json
import os
from pathlib import Path
import select
import time
import uuid
import zlib

import background_keeper
from g515_activity import find_g515_hidraw, ActivityError
from model import validate_color


class OnboardError(Exception):
    pass


class DeviceError(OnboardError):
    def __init__(self, code):
        self.code = code
        super().__init__(f'Keyboard rejected the request (HID++ error {code:#x}).')


class Transport:
    def __init__(self, device):
        self.device = device
        self.fd = None
        self.sequence = 0
        self.features = {0: 0}

    def __enter__(self):
        path = find_g515_hidraw(self.device)
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)

    def request(self, feature, function, params=()):
        if feature not in self.features:
            result = self.request(0, 0, (feature >> 8, feature & 255))
            if not result[0]:
                raise OnboardError(f'Keyboard does not support feature {feature:#x}.')
            self.features[feature] = result[0]
        self.sequence = self.sequence % 15 + 1
        index = self.features[feature]
        command = (function << 4) | self.sequence
        packet = bytes((0x11, 0xff, index, command, *params)).ljust(20, b'\0')
        if len(packet) != 20 or os.write(self.fd, packet) != 20:
            raise OnboardError('Could not send a complete keyboard request.')
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            readable, _, _ = select.select([self.fd], [], [], max(0, deadline - time.monotonic()))
            if not readable:
                break
            try:
                response = os.read(self.fd, 64)
            except BlockingIOError:
                continue
            if len(response) >= 6 and response[:2] in (b'\x10\xff', b'\x11\xff'):
                if response[2] == 0xff and response[3:5] == bytes((index, command)):
                    raise DeviceError(response[5])
                if response[2:4] == bytes((index, command)):
                    return response[4:]
        raise OnboardError('Keyboard did not respond. Check its connection and close other lighting apps.')


def _crc(data):
    return zlib.crc32(data).to_bytes(4, 'big')


def _valid_directory(directory):
    return (len(directory) == 16 and directory[4:10] == bytes.fromhex('010181014063')
            and directory[15] == 255 and directory[:4] == _crc(directory[4:]))


def _read_buffer(transport, size):
    data = bytearray()
    for offset in range(0, size, 16):
        result = transport.request(0x8101, 12, (offset >> 8, offset & 255))
        if len(result) < 16:
            raise OnboardError('Keyboard returned an incomplete profile.')
        data.extend(result[:16])
    return bytes(data[:size])


def _read_file(transport, address, size):
    try:
        transport.request(0x8101, 8, (address >> 8, address & 255, size >> 8, size & 255))
    except DeviceError as error:
        if address in (0, 8) and error.code == 4:
            return None
        raise
    return _read_buffer(transport, size)


def snapshot(transport):
    factory = _read_file(transport, 0x101, 99)
    factory_dir = _read_file(transport, 0x100, 16)
    user = _read_file(transport, 8, 99)
    user_dir = _read_file(transport, 0, 16)
    if not factory or factory[:2] != b'\x01\x01' or not _valid_directory(factory_dir or b''):
        raise OnboardError('Unrecognized factory profile; nothing was written.')
    if (user is None) != (user_dir is None):
        raise OnboardError('Existing user profile is incomplete; nothing was written.')
    if user is not None and (user[:2] != b'\x01\x01' or not _valid_directory(user_dir)
                             or user_dir[14] != 8 or user_dir[10:14] != _crc(user)):
        raise OnboardError('Existing user profile failed validation; nothing was written.')
    return {'factory': factory, 'factory_directory': factory_dir, 'user': user, 'user_directory': user_dir}


def build_profile(saved, color, idle_off_after=None):
    color = bytes.fromhex(validate_color(color))
    profile = bytearray(saved['user'] or saved['factory'])
    profile[30:74] = b'\0' * 44
    profile[41:52] = bytes((1, *color, 2)) + b'\0' * 6
    if idle_off_after is not None:
        if type(idle_off_after) is not int or not 1 <= idle_off_after <= 65534:
            raise OnboardError('Idle delay must be between 1 and 65534 seconds.')
        profile[2:4] = idle_off_after.to_bytes(2, 'big')
        # Use the already-supported static effect with black for the idle state.
        profile[63:74] = bytes.fromhex('0100000002000000000000')
    else:
        profile[63:74] = bytes((1, *(v // 2 for v in color), 2)) + b'\0' * 6
    profile[74] = 0
    directory = bytearray(saved['factory_directory'])
    directory[10:14] = _crc(profile)
    directory[14] = 8
    directory[0:4] = _crc(directory[4:])
    return bytes(profile), bytes(directory)


def _save_file(transport, address, data, checksum):
    if address not in (0, 8):
        raise OnboardError('Refusing to write a factory profile.')
    size = len(data)
    transport.request(0x8101, 2, (size >> 8, size & 255))
    for offset in range(0, size, 16):
        transport.request(0x8101, 3, data[offset:offset + 16])
    if _read_buffer(transport, size) != data:
        raise OnboardError('Staged data did not verify; flash was not written.')
    transport.request(0x8101, 7, bytes((address >> 8, address & 255, size >> 8, size & 255)) + checksum)
    if _read_file(transport, address, size) != data:
        raise OnboardError('Onboard profile did not verify after writing; backup was retained.')


def _backup(device, saved):
    directory = background_keeper.config_path().parent / 'onboard-backups'
    name = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.json'
    destination = directory / name
    data = {'version': 1, 'device': {'vendor': device.vendor, 'product': device.product, 'serial': device.serial},
            'files': {key: value.hex() if value is not None else None for key, value in saved.items()}}
    background_keeper._write_atomic(destination, json.dumps(data, indent=2) + '\n')
    return destination


def save_solid(device, color, transport_class=Transport, idle_off_after=None):
    if (device.vendor.lower(), device.product.lower()) != ('046d', 'c358'):
        raise OnboardError('Onboard saving is supported only for the wired G515 TKL (046d:c358).')
    validate_color(color)
    directory = background_keeper.config_path().parent
    directory.mkdir(parents=True, exist_ok=True)
    # Serialize against the background keeper, which can change HID++ state.
    with (directory / 'keeper.lock').open('a') as lock:
        deadline = time.monotonic() + 10
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OnboardError('The background lighting helper is busy; try again.')
                time.sleep(.1)
        try:
            with transport_class(device) as transport:
                transport.request(0, 0, (0x80, 0x71))
                saved = snapshot(transport)
                profile, user_dir = build_profile(saved, color, idle_off_after)
                backup = _backup(device, saved)
                try:
                    if saved['user'] != profile:
                        _save_file(transport, 8, profile, _crc(profile))
                    if saved['user_directory'] != user_dir:
                        _save_file(transport, 0, user_dir, user_dir[:4])
                    transport.request(0x8071, 5, (1, 0, 0))
                    transport.request(0x8101, 6, (0x0b,))
                    transport.request(0x8101, 9, bytes.fromhex('81010100010063') + _crc(profile))
                    state = transport.request(0x8101, 6, (0,))
                    if len(state) < 3 or not state[0] & 1 or state[1:3] != b'\0\x01':
                        raise OnboardError(f'Profile was written but activation was not verified. Backup: {backup}')
                except (OnboardError, OSError) as error:
                    raise OnboardError(f'{error} Backup: {backup}') from error
                return backup
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
