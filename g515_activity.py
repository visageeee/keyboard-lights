"""Listen for G515 HID++ activity transitions, never keyboard input reports."""
import os
from pathlib import Path
import select
import threading
import time


class ActivityError(Exception):
    pass


def find_g515_hidraw(device, root=Path('/sys/class/hidraw')):
    for uevent in root.glob('hidraw*/device/uevent'):
        try:
            fields = dict(line.split('=', 1) for line in uevent.read_text().splitlines() if '=' in line)
        except OSError:
            continue
        if (fields.get('HID_ID') == '0003:0000046D:0000C358' and
                fields.get('HID_PHYS', '').endswith('/input2') and
                (not device.serial or fields.get('HID_UNIQ', '') == device.serial)):
            return Path('/dev') / uevent.parts[-3]
    raise ActivityError('G515 activity interface not found')


def activity_report(packet, feature):
    """Match only the RGB feature's generic user-activity notification."""
    return (len(packet) >= 5 and packet[0] in (0x10, 0x11) and
            packet[1] == 0xff and packet[2] == feature and
            packet[3] == 0x10 and packet[4] == 0x01)


class G515ActivityMonitor:
    """Watch the vendor HID++ interface for idle-to-active transitions."""
    def __init__(self, device, on_activity, on_error):
        self.device, self.on_activity, self.on_error = device, on_activity, on_error
        self.stopping = threading.Event()
        self.rearm = threading.Event()
        self.thread = None
        self.sequence = 0
        self.feature = None
        self.fd = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='g515-activity', daemon=True)
        self.thread.start()

    def close(self):
        self.stopping.set()

    def rearm_notifications(self):
        # g810-led reclaims software control with its own event flags on each
        # apply; request activity notifications again afterwards.
        self.rearm.set()

    def _handle(self, packet):
        if self.feature is not None and activity_report(packet, self.feature):
            self.on_activity()

    def _request(self, feature, function, params):
        if self.stopping.is_set():
            raise ActivityError('G515 activity monitor stopped')
        self.sequence = self.sequence % 15 + 1
        command = (function << 4) | self.sequence
        packet = bytes([0x11, 0xff, feature, command, *params]).ljust(20, b'\0')
        if os.write(self.fd, packet) != len(packet):
            raise ActivityError('G515 activity request failed')
        deadline = time.monotonic() + 2
        while not self.stopping.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            readable, _, _ = select.select([self.fd], [], [], min(.25, remaining))
            if not readable:
                continue
            try:
                response = os.read(self.fd, 64)
            except BlockingIOError:
                continue
            if len(response) >= 6 and response[0] in (0x10, 0x11) and response[1] == 0xff:
                if response[2] == 0xff and response[3:5] == bytes([feature, command]):
                    raise ActivityError('G515 rejected the activity request')
                if response[2:4] == bytes([feature, command]):
                    return response[4:]
            self._handle(response)
        raise ActivityError('G515 activity request timed out')

    def _enable(self):
        current = self._request(self.feature, 5, [0, 0, 0])
        if len(current) < 3:
            raise ActivityError('Incomplete G515 control response')
        flags = current[2] | 0x02  # user-activity events; preserve existing flags
        if flags != current[2]:
            response = self._request(self.feature, 5, [1, current[1], flags])
            if len(response) < 3 or response[:3] != bytes([1, current[1], flags]):
                raise ActivityError('G515 did not confirm activity notifications')

    def _run(self):
        try:
            path = find_g515_hidraw(self.device)
            self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
            root = self._request(0, 0, [0x80, 0x71])
            if not root or not root[0]:
                raise ActivityError('G515 RGB activity notifications unavailable')
            self.feature = root[0]
            self._enable()
            while not self.stopping.is_set():
                if self.rearm.is_set():
                    self.rearm.clear()
                    self._enable()
                readable, _, _ = select.select([self.fd], [], [], .25)
                if readable:
                    try:
                        packet = os.read(self.fd, 64)
                        if not packet:
                            raise ActivityError('G515 activity interface disconnected')
                        self._handle(packet)
                    except BlockingIOError:
                        continue
        except (OSError, ValueError, ActivityError) as error:
            if not self.stopping.is_set():
                self.on_error(str(error))
        finally:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
