#!/usr/bin/env python3
"""Control the keyboard countdown without opening the GUI."""
import argparse
import math
import re
import sys
import time

import background_keeper
import timer_store


def duration(value):
    text = value.strip().lower()
    if re.fullmatch(r'\d+', text):
        seconds = int(text) * 60
    else:
        match = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', text)
        if not match or not any(match.groups()):
            raise argparse.ArgumentTypeError('Use minutes (25) or a duration such as 25m, 90s or 1h30m.')
        hours, minutes, secs = (int(part or 0) for part in match.groups())
        seconds = hours * 3600 + minutes * 60 + secs
    if not 1 <= seconds <= 86400:
        raise argparse.ArgumentTypeError('Duration must be between 1 second and 24 hours.')
    return seconds


def main(argv=None):
    parser = argparse.ArgumentParser(description='Start or control the Keyboard Lights timer.')
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('start', help='Start or replace a countdown')
    start.add_argument('duration', type=duration, help='Minutes, or e.g. 25m, 90s, 1h30m')
    commands.add_parser('cancel', help='Cancel the countdown and restore the lighting')
    commands.add_parser('status', help='Show the remaining time')
    args = parser.parse_args(argv)
    try:
        if args.command == 'start':
            # When replacing a timer, its snapshot is the actual design currently
            # controlled by the helper, even if the background keeper is disabled.
            active = timer_store.load()
            current = active[1:] if active else background_keeper.load(include_disabled=True)
            if not current:
                print('No applied lighting found. Apply a design to the keyboard in the GUI first.', file=sys.stderr)
                return 1
            timer_store.start_service(*current, args.duration)
            print(f'Timer started for {args.duration} seconds.')
        elif args.command == 'cancel':
            if timer_store.load():
                timer_store.cancel()
                print('Timer cancelled; restoring lighting.')
            else:
                print('No timer is running.')
        else:
            active = timer_store.load()
            if not active:
                print('No timer is running.')
                return 1
            remaining = math.ceil(active[0]['end'] - time.time())
            if remaining <= 0:
                print('Time is up; alarm is flashing.')
            else:
                print(f'{remaining // 3600:02d}:{remaining // 60 % 60:02d}:{remaining % 60:02d} remaining')
    except (OSError, ValueError) as error:
        print(f'Timer: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
