"""Keyboard layout and portable, validated lighting profiles."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

COLOR = re.compile(r'^[0-9a-fA-F]{6}$')


@dataclass(frozen=True)
class Key:
    name: str
    label: str
    x: float
    y: float
    width: float = 1.0
    height: float = 1.0


def _row(y, specs, x=0):
    result = []
    for name, label, width in specs:
        if name:
            result.append(Key(name, label, x, y, width))
        x += width
    return result


def keyboard_layout():
    # Nordic ISO TKL. Identifiers are physical HID keys understood by g810-led.
    one = lambda values: [(key, label, 1.) for key, label in values]
    keys = _row(0, [('esc', 'Esc', 1), ('', '', .5)] +
                one([(f'f{i}', f'F{i}') for i in range(1, 13)]) +
                [('', '', .25)] + one([('print_screen', 'Prt'), ('scroll_lock', 'Scr'), ('pause_break', 'Pause')]))
    keys += _row(1.35, one([('tilde', '§'), *[(str(i), str(i)) for i in range(1, 10)],
                             ('0', '0'), ('minus', '+'), ('equal', '´')]) + [('backspace', 'Backspace', 2)] +
                 [('', '', .25)] + one([('insert', 'Ins'), ('home', 'Home'), ('page_up', 'PgUp')]))
    keys += _row(2.35, [('tab', 'Tab', 1.5)] + one([(x, x.upper()) for x in 'qwertyuiop']) +
                 one([('open_bracket', 'Å'), ('close_bracket', '¨')]) + [('', '', 1.5)] +
                 [('', '', .25)] + one([('delete', 'Del'), ('end', 'End'), ('page_down', 'PgDn')]))
    keys += _row(3.35, [('caps_lock', 'Caps', 1.75)] + one([(x, x.upper()) for x in 'asdfghjkl']) +
                 one([('semicolon', 'Ö'), ('quote', 'Ä'), ('dollar', "'")]))
    keys.append(Key('enter', 'Enter', 13.75, 2.35, 1.25, 2.0))
    keys += _row(4.35, [('shift_left', 'Shift', 1.25), ('intl_backslash', '<', 1.0)] + one([(x, x.upper()) for x in 'zxcvbnm']) +
                 one([('comma', ','), ('period', '.'), ('slash', '/')]) + [('shift_right', 'Shift', 2.75)] +
                 [('', '', 1.25), ('arrow_top', 'Up', 1)])
    keys += _row(5.35, [('ctrl_left', 'Ctrl', 1.25), ('win_left', 'Super', 1.25), ('alt_left', 'Alt', 1.25),
                         ('space', 'Space', 6.25), ('alt_right', 'Alt', 1.25), ('win_right', 'Super', 1.25),
                         ('menu', 'Menu', 1.25), ('ctrl_right', 'Ctrl', 1.25), ('', '', .25)] +
                 one([('arrow_left', 'Left'), ('arrow_bottom', 'Down'), ('arrow_right', 'Right')]))
    return tuple(keys)


KEYS = keyboard_layout()
KEY_NAMES = frozenset(key.name for key in KEYS)
LEGACY_KEY_NAMES = (KEY_NAMES - {'intl_backslash', 'dollar'}) | {'backslash'}


def validate_color(value):
    if not isinstance(value, str) or not COLOR.fullmatch(value):
        raise ValueError('Colors must be six hexadecimal digits.')
    return value.lower()


class LightingProfile:
    def __init__(self, colors=None, brightness=100):
        self.set_brightness(brightness)
        self.colors = {name: '232d40' for name in KEY_NAMES}
        if colors is not None:
            if not isinstance(colors, dict):
                raise ValueError('This profile does not match the TKL keyboard layout.')
            if set(colors) == LEGACY_KEY_NAMES:
                # Preserve the earlier ANSI preview when opening existing files.
                colors = dict(colors)
                colors['dollar'] = colors.pop('backslash')
                colors['intl_backslash'] = colors['shift_left']
            if set(colors) != KEY_NAMES:
                raise ValueError('This profile does not match the TKL keyboard layout.')
            self.colors = {name: validate_color(color) for name, color in colors.items()}

    def set_key(self, name, color):
        if name not in KEY_NAMES:
            raise ValueError('Unknown keyboard key.')
        self.colors[name] = validate_color(color)

    def set_all(self, color):
        color = validate_color(color)
        self.colors = {name: color for name in KEY_NAMES}

    def set_brightness(self, brightness):
        if type(brightness) is not int or not 0 <= brightness <= 100:
            raise ValueError('Brightness must be between 0 and 100.')
        self.brightness = brightness

    def effective_color(self, name):
        color = self.colors[name]
        return ''.join(f'{(int(color[i:i + 2], 16) * self.brightness + 50) // 100:02x}'
                       for i in (0, 2, 4))

    def controller_profile(self):
        # Scale output without destroying the saved, full-brightness colors.
        return ''.join(f'k {key.name} {self.effective_color(key.name)}\n' for key in KEYS) + 'c\n'

    def save(self, path):
        data = {'version': 1, 'layout': 'tkl', 'colors': self.colors, 'brightness': self.brightness}
        Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    @classmethod
    def load(cls, path):
        with Path(path).open(encoding='utf-8') as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or data.get('version') != 1 or data.get('layout') != 'tkl':
            raise ValueError('Unsupported lighting profile.')
        return cls(data.get('colors'), data.get('brightness', 100))
