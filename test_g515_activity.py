import socket
import threading
import unittest
from unittest.mock import Mock

from controller import Device
from g515_activity import G515ActivityMonitor, activity_report


class ActivityTests(unittest.TestCase):
    def test_accepts_only_g515_generic_activity_notification(self):
        self.assertTrue(activity_report(bytes([0x11, 0xff, 9, 0x10, 1]), 9))
        for packet in (bytes([0x11, 0xff, 9, 0x10, 0]),  # idle, not wake
                       bytes([0x11, 0xff, 9, 0x20, 1]),  # different notification
                       bytes([0x11, 0xff, 8, 0x10, 1]),  # other feature
                       bytes([0x11, 0xff, 9, 0x11, 1]),  # response, not event
                       b'\x11'):
            self.assertFalse(activity_report(packet, 9))

    def test_subscribe_preserves_existing_control_and_event_flags(self):
        client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        seen, failure = [], []
        monitor = G515ActivityMonitor(Device('G515', '046d', 'c358'), Mock(), Mock())
        monitor.fd = client.fileno()
        monitor.feature = 9
        def keyboard():
            try:
                get = server.recv(64)
                seen.append(get)
                server.send(get[:4] + bytes([0, 3, 4]).ljust(16, b'\0'))
                set_request = server.recv(64)
                seen.append(set_request)
                server.send(set_request)
            except Exception as error:
                failure.append(error)
        thread = threading.Thread(target=keyboard)
        thread.start()
        try:
            monitor._enable()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertFalse(failure)
            self.assertEqual(seen[0][4:7], bytes([0, 0, 0]))
            self.assertEqual(seen[1][4:7], bytes([1, 3, 6]))
        finally:
            client.close()
            server.close()


if __name__ == '__main__':
    unittest.main()
