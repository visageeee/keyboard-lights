import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from controller import Device
import g515_onboard as onboard


def factory_files():
    profile = bytearray([255] * 99)
    profile[:6] = bytes.fromhex('0101003c012c')
    profile[75:91] = bytes(range(16))
    directory = bytearray(16)
    directory[4:10] = bytes.fromhex('010181014063')
    directory[10:14] = onboard._crc(profile)
    directory[14:16] = b'\x01\xff'
    directory[:4] = onboard._crc(directory[4:])
    return {0x101: bytes(profile), 0x100: bytes(directory)}


class FakeTransport:
    files = None
    calls = None
    corrupt_stage = False
    supports_breathe = True
    def __init__(self, device):
        self.buffer = b''
        self.expected = 0
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def request(self, feature, function, params=()):
        self.calls.append((feature, function, bytes(params)))
        if feature == 0:
            return b'\x01' + b'\0' * 15
        if feature == 0x8071:
            if function == 0 and tuple(params) == (255, 255, 0):
                return b'\0\0\x01' + b'\0' * 13
            if function == 0 and tuple(params) == (0, 255, 0):
                return b'\0\0\0\0\x01' + b'\0' * 11
            if function == 0 and tuple(params) == (0, 0, 0):
                return b'\0\0\0' + (b'\x0a' if self.supports_breathe else b'\x01') + b'\0' * 12
            return b'\0' * 16
        if function == 8:
            addr = int.from_bytes(params[:2], 'big')
            if addr not in self.files:
                raise onboard.DeviceError(4)
            self.buffer = self.files[addr]
        elif function == 12:
            offset = int.from_bytes(params[:2], 'big')
            value = self.buffer[offset:offset + 16].ljust(16, b'\0')
            if self.corrupt_stage and self.expected:
                return bytes([value[0] ^ 1]) + value[1:]
            return value
        elif function == 2:
            self.expected = int.from_bytes(params[:2], 'big')
            self.buffer = b''
        elif function == 3:
            self.buffer += bytes(params)
        elif function == 7:
            addr = int.from_bytes(params[:2], 'big')
            self.files[addr] = self.buffer[:self.expected]
            self.expected = 0
        elif function == 6 and bytes(params) == b'\0':
            return b'\x01\x00\x01' + b'\0' * 13
        return b'\0' * 16


class OnboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.temp.name})
        self.env.start()
        FakeTransport.files = factory_files()
        FakeTransport.calls = []
        FakeTransport.corrupt_stage = False
        FakeTransport.supports_breathe = True
        self.device = Device('G515 TKL', '046d', 'c358', '')

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_backups_writes_verifies_and_preserves_other_fields(self):
        original = FakeTransport.files[0x101]
        backup = onboard.save_solid(self.device, '123456', FakeTransport)
        saved = json.loads(Path(backup).read_text())
        self.assertEqual(saved['files']['factory'], original.hex())
        self.assertIsNone(saved['files']['user'])
        result = FakeTransport.files[8]
        self.assertEqual(result[:30], original[:30])
        self.assertEqual(result[75:], original[75:])
        self.assertEqual(result[41:46], bytes.fromhex('0112345602'))
        self.assertEqual(result[63:68], bytes.fromhex('01091a2b02'))
        self.assertEqual(FakeTransport.files[0][10:14], onboard._crc(result))
        self.assertEqual(Path(backup).stat().st_mode & 0o777, 0o600)
        writes = [int.from_bytes(p[:2], 'big') for f, fn, p in FakeTransport.calls if f == 0x8101 and fn == 7]
        self.assertEqual(writes, [8, 0])

    def test_idle_backlight_off_preserves_sleep_and_active_color(self):
        onboard.save_solid(self.device, '123456', FakeTransport, idle_off_after=45)
        profile = FakeTransport.files[8]
        self.assertEqual(profile[2:6], bytes.fromhex('002d012c'))
        self.assertEqual(profile[41:46], bytes.fromhex('0112345602'))
        self.assertEqual(profile[63:74], bytes.fromhex('0100000002000000000000'))
        self.assertEqual(FakeTransport.files[0][10:14], onboard._crc(profile))

    def test_invalid_idle_delay_is_rejected_without_writing(self):
        for delay in (0, 65535, -1, True):
            with self.assertRaises(onboard.OnboardError):
                onboard.save_solid(self.device, '123456', FakeTransport, idle_off_after=delay)
        self.assertFalse(any(f == 0x8101 and fn == 7 for f, fn, _ in FakeTransport.calls))

    def test_refuses_wrong_model_and_invalid_profile_without_writing(self):
        with self.assertRaises(onboard.OnboardError):
            onboard.save_solid(Device('Other', '046d', 'c355'), 'abcdef', FakeTransport)
        FakeTransport.files[0] = b'invalid directory'
        with self.assertRaises(onboard.OnboardError):
            onboard.save_solid(self.device, 'abcdef', FakeTransport)
        self.assertFalse(any(f == 0x8101 and fn == 7 for f, fn, _ in FakeTransport.calls))

    def test_corrupt_staging_aborts_before_flash_and_keeps_backup(self):
        FakeTransport.corrupt_stage = True
        with self.assertRaisesRegex(onboard.OnboardError, 'Backup:'):
            onboard.save_solid(self.device, 'abcdef', FakeTransport)
        self.assertNotIn(8, FakeTransport.files)
        self.assertFalse(any(f == 0x8101 and fn == 7 for f, fn, _ in FakeTransport.calls))
        self.assertEqual(len(list((Path(self.temp.name) / 'keyboard-lights/onboard-backups').glob('*.json'))), 1)


if __name__ == '__main__':
    unittest.main()
