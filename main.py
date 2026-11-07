#!/usr/bin/env python3
"""A small GTK interface for g810-led keyboard lighting."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import time

import timer_store
import g515_onboard
import workspace_indicator
from g515_activity import ActivityError

import cairo
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk, Pango

import background_keeper
from controller import Controller, ControllerError, default_controller
from g515_activity import G515ActivityMonitor
from model import KEYS, LightingProfile
from profile_store import ProfileStore


STYLE = b'''
window { background: #10141d; color: #eef2fa; }
label { color: #eef2fa; }
#eyebrow { color: #65d9d3; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
#title { color: #f5f7fc; font-size: 27px; font-weight: 700; }
#subtitle, #hint { color: #9daabd; font-size: 12px; }
#section { color: #c7d2e3; font-size: 12px; font-weight: 700; }
#panel { background: #191f2b; border: 1px solid #2b3444; border-radius: 12px; }
#status { color: #afbdd0; font-size: 12px; }
#status.error { color: #ff9997; }
button, combobox button, entry { background: #263142; border: 1px solid #3a485e; border-radius: 7px; color: #eef2fa; text-shadow: none; box-shadow: none; padding: 7px 12px; }
button:hover { background: #344359; }
button:disabled { color: #788496; background: #202938; }
button#primary { background: #57cdc5; color: #102427; border: 0; font-weight: 700; }
button#primary:hover { background: #79e0d8; }
button#primary:disabled { background: #304b50; color: #a1b4b3; }
colorbutton button { padding: 4px; }
#profiles-sidebar { background: #191f2b; border: 1px solid #2b3444; border-radius: 12px; padding: 14px; }
#profiles-list, #profiles-list viewport { background: transparent; }
#profiles-list row { border-radius: 7px; padding: 8px; }
#profiles-list row:hover { background: #293748; }
#profiles-list row:selected { background: #315255; }
#profiles-list row:selected label { color: #e6fffd; }
#profile-warning { color: #ff9997; font-size: 11px; }
'''


def rounded(context, x, y, width, height, radius):
    radius = min(radius, width / 2, height / 2)
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -1.5708, 0)
    context.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
    context.arc(x + radius, y + height - radius, radius, 1.5708, 3.14159)
    context.arc(x + radius, y + radius, radius, 3.14159, 4.71239)
    context.close_path()


class KeyboardPreview(Gtk.DrawingArea):
    UNIT = 46
    HEIGHT = 6.35
    WIDTH = 18.25

    def __init__(self, profile, get_color, changed):
        super().__init__()
        self.profile = profile
        self.get_color = get_color
        self.changed = changed
        self.painting = False
        self.stroke_color = None
        self.stroke_keys = set()
        self.set_size_request(540, 235)
        self.set_hexpand(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect('draw', self.draw_keyboard)
        self.connect('button-press-event', self.press)
        self.connect('button-release-event', self.release)
        self.connect('motion-notify-event', self.motion)
        self.get_accessible().set_name('Keyboard lighting preview')

    def geometry(self):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        unit = max(1., min((width - 24) / self.WIDTH, (height - 24) / self.HEIGHT, self.UNIT))
        return unit, (width - self.WIDTH * unit) / 2, (height - self.HEIGHT * unit) / 2

    def draw_keyboard(self, _widget, context):
        unit, left, top = self.geometry()
        context.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        context.set_font_size(max(8, min(11, unit * .23)))
        for key in KEYS:
            x, y = left + key.x * unit, top + key.y * unit
            width, height = key.width * unit - 4, key.height * unit - 5
            color = self.profile.effective_color(key.name)
            rgb = [int(color[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            rounded(context, x, y, width, height, 5)
            context.set_source_rgb(*(0.10 + c * .45 for c in rgb))
            context.fill_preserve()
            context.set_source_rgba(*(0.20 + c * .75 for c in rgb), .95)
            context.set_line_width(1.2)
            context.stroke()
            text = context.text_extents(key.label)
            context.move_to(x + (width - text.width) / 2 - text.x_bearing,
                            y + (height - text.height) / 2 - text.y_bearing)
            context.set_source_rgb(.90, .94, .97)
            context.show_text(key.label)
        return False

    def key_at(self, x, y):
        unit, left, top = self.geometry()
        x, y = (x - left) / unit, (y - top) / unit
        return next((key for key in KEYS if key.x <= x < key.x + key.width - 4 / unit and
                     key.y <= y < key.y + key.height - 5 / unit), None)

    def paint(self, key):
        if key is not None and key.name not in self.stroke_keys:
            self.stroke_keys.add(key.name)
            self.profile.set_key(key.name, self.stroke_color)
            self.queue_draw()
            action = 'cleared' if self.stroke_color == '000000' else 'painted'
            self.changed(f'Preview {action}: {key.label}')

    def press(self, _widget, event):
        if (event.button != 1 or
                getattr(event, 'type', Gdk.EventType.BUTTON_PRESS) != Gdk.EventType.BUTTON_PRESS):
            return False
        key = self.key_at(event.x, event.y)
        if key is None:
            return False
        selected = self.get_color()
        self.stroke_color = ('000000' if selected != '000000' and
                             self.profile.colors[key.name] == selected else selected)
        self.stroke_keys = set()
        self.painting = True
        self.paint(key)
        return True

    def release(self, _widget, event):
        if event.button == 1 and self.painting:
            self.painting = False
            self.stroke_color = None
            self.stroke_keys.clear()
            return True
        return False

    def motion(self, _widget, event):
        if self.painting and event.state & Gdk.ModifierType.BUTTON1_MASK:
            self.paint(self.key_at(event.x, event.y))
            return True
        return False


class LightingWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title='Keyboard Lights')
        self.set_default_size(1200, 700)
        self.set_border_width(24)
        self.profile_store = ProfileStore()
        self.profile = self.profile_store.current()['profile']
        self.profile_save_source = 0
        self._updating_profiles = False
        self._switching_profile = False
        self.devices = []
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='keyboard-controller')
        self.closed = False
        self.busy = False
        self.applied_lighting = None
        self.keepalive_source = 0
        self.keepalive_generation = 0
        self.keepalive_future = None
        self.activity_monitor = None
        self.activity_restore_source = 0
        self.connect('destroy', self.close)
        provider = Gtk.CssProvider()
        provider.load_from_data(STYLE)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.add(root)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar.set_name('profiles-sidebar')
        sidebar.set_size_request(205, -1)
        root.pack_start(sidebar, False, False, 0)
        header = Gtk.Box(spacing=8)
        label = Gtk.Label(label='Profiles', xalign=0)
        label.set_name('section')
        label.set_hexpand(True)
        header.pack_start(label, True, True, 0)
        add = self.button('+', self.new_profile)
        add.set_tooltip_text('Create a profile from the current design')
        add.get_accessible().set_name('Create profile')
        header.pack_start(add, False, False, 0)
        sidebar.pack_start(header, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.profile_list = Gtk.ListBox()
        self.profile_list.set_name('profiles-list')
        self.profile_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.profile_list.connect('row-selected', self.profile_selected)
        scroll.add(self.profile_list)
        sidebar.pack_start(scroll, True, True, 0)
        self.profile_warning = Gtk.Label(xalign=0)
        self.profile_warning.set_name('profile-warning')
        self.profile_warning.set_line_wrap(True)
        if self.profile_store.load_error:
            self.profile_warning.set_text('Saved profiles could not be read; the file was left unchanged.')
        sidebar.pack_start(self.profile_warning, False, False, 0)
        actions = Gtk.Box(spacing=6)
        self.rename_profile_button = self.button('Rename', self.rename_profile)
        self.delete_profile_button = self.button('Delete', self.delete_profile)
        actions.pack_start(self.rename_profile_button, True, True, 0)
        actions.pack_start(self.delete_profile_button, True, True, 0)
        sidebar.pack_start(actions, False, False, 0)
        sidebar.pack_start(self.button('Import old profile…', self.import_profile), False, False, 0)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        outer.set_hexpand(True)
        root.pack_start(outer, True, True, 0)
        eyebrow = Gtk.Label(label='LOGITECH LIGHTING', xalign=0)
        eyebrow.set_name('eyebrow')
        outer.pack_start(eyebrow, False, False, 0)
        title = Gtk.Label(label='Keyboard Lights', xalign=0)
        title.set_name('title')
        outer.pack_start(title, False, False, 0)
        subtitle = Gtk.Label(label='Paint your keys, then apply the design to your keyboard.', xalign=0)
        subtitle.set_name('subtitle')
        outer.pack_start(subtitle, False, False, 0)
        device_row = Gtk.Box(spacing=10)
        outer.pack_start(device_row, False, False, 0)
        device_row.pack_start(Gtk.Label(label='Keyboard', xalign=0), False, False, 0)
        self.device_combo = Gtk.ComboBoxText()
        self.device_combo.set_hexpand(True)
        self.device_combo.connect('changed', self.device_changed)
        device_row.pack_start(self.device_combo, True, True, 0)
        self.refresh_button = Gtk.Button(label='Refresh')
        self.refresh_button.connect('clicked', self.refresh_devices)
        device_row.pack_start(self.refresh_button, False, False, 0)
        self.path_entry = Gtk.Entry()
        self.path_entry.set_text(default_controller())
        self.path_entry.set_tooltip_text('Path to the g810-led controller executable')
        self.path_entry.connect('changed', self.controller_changed)
        path_row = Gtk.Box(spacing=10)
        path_row.pack_start(Gtk.Label(label='Controller', xalign=0), False, False, 0)
        path_row.pack_start(self.path_entry, True, True, 0)
        self.browse_button = self.button('Browse…', self.choose_controller)
        path_row.pack_start(self.browse_button, False, False, 0)
        outer.pack_start(path_row, False, False, 0)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        panel.set_name('panel')
        panel.set_border_width(16)
        outer.pack_start(panel, True, True, 0)
        tools = Gtk.Box(spacing=10)
        tools.pack_start(Gtk.Label(label='PAINT COLOR', xalign=0), False, False, 0)
        self.color_button = Gtk.ColorButton()
        rgba = Gdk.RGBA()
        rgba.parse('#57cdc5')
        self.color_button.set_rgba(rgba)
        self.color_button.set_title('Choose key color')
        tools.pack_start(self.color_button, False, False, 0)
        tools.pack_start(self.button('Fill all keys', self.fill_all), False, False, 0)
        tools.pack_start(self.button('Turn all off', self.clear_all), False, False, 0)
        hint = Gtk.Label(label='Click a painted key again to turn it off', xalign=1)
        hint.set_name('hint')
        hint.set_hexpand(True)
        tools.pack_end(hint, True, True, 0)
        panel.pack_start(tools, False, False, 0)
        brightness_row = Gtk.Box(spacing=10)
        brightness_row.pack_start(Gtk.Label(label='Brightness', xalign=0), False, False, 0)
        self.brightness_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.brightness_scale.set_draw_value(False)
        self.brightness_scale.set_hexpand(True)
        self.brightness_scale.set_value(self.profile.brightness)
        self.brightness_scale.get_accessible().set_name('Keyboard brightness')
        brightness_row.pack_start(self.brightness_scale, True, True, 0)
        self.brightness_label = Gtk.Label(label=f'{self.profile.brightness}%', xalign=1)
        self.brightness_label.set_width_chars(4)
        brightness_row.pack_start(self.brightness_label, False, False, 0)
        panel.pack_start(brightness_row, False, False, 0)
        self.preview = KeyboardPreview(self.profile, self.paint_color, self.profile_modified)
        self.brightness_scale.connect('value-changed', self.brightness_changed)
        panel.pack_start(self.preview, True, True, 0)
        info = Gtk.Label(label='Preview only — current keyboard colors cannot be read.', xalign=0)
        info.set_name('hint')
        panel.pack_start(info, False, False, 0)
        timer_row = Gtk.Box(spacing=8)
        timer_row.pack_start(Gtk.Label(label='Timer', xalign=0), False, False, 0)
        self.timer_minutes = Gtk.SpinButton.new_with_range(0, 1440, 1)
        self.timer_minutes.set_value(25)
        self.timer_minutes.set_tooltip_text('Minutes')
        timer_row.pack_start(self.timer_minutes, False, False, 0)
        timer_row.pack_start(Gtk.Label(label='min'), False, False, 0)
        self.timer_seconds = Gtk.SpinButton.new_with_range(0, 59, 1)
        self.timer_seconds.set_tooltip_text('Seconds')
        timer_row.pack_start(self.timer_seconds, False, False, 0)
        timer_row.pack_start(Gtk.Label(label='sec'), False, False, 0)
        self.timer_start_button = self.button('Start timer', self.start_timer)
        timer_row.pack_start(self.timer_start_button, False, False, 0)
        self.timer_cancel_button = self.button('Cancel timer', self.cancel_timer)
        timer_row.pack_start(self.timer_cancel_button, False, False, 0)
        self.timer_label = Gtk.Label(xalign=0)
        timer_row.pack_start(self.timer_label, True, True, 0)
        outer.pack_start(timer_row, False, False, 0)
        self.timer_ui_source = GLib.timeout_add(500, self.update_timer_display)
        self.update_timer_display()
        bottom = Gtk.Box(spacing=10)
        outer.pack_start(bottom, False, False, 0)
        self.apply_button = self.button('Apply to keyboard', self.apply_profile)
        self.apply_button.set_name('primary')
        self.onboard_button = self.button('Save default color…', self.save_onboard_color)
        bottom.pack_start(self.onboard_button, False, False, 0)
        bottom.pack_end(self.apply_button, False, False, 0)
        self.keepalive_toggle = Gtk.CheckButton(label='Keep applied lighting active after closing (start at login)')
        self.keepalive_toggle.set_active(background_keeper.enabled())
        self.keepalive_toggle.connect('toggled', self.keepalive_changed)
        outer.pack_start(self.keepalive_toggle, False, False, 0)
        workspace_row = Gtk.Box(spacing=8)
        workspace_enabled, workspace_color = workspace_indicator.load()
        self.workspace_toggle = Gtk.CheckButton(label='Show workspace on F1–F12')
        self.workspace_toggle.set_active(workspace_enabled)
        self.workspace_toggle.set_tooltip_text('Uses the active X11 workspace; requires background lighting.')
        workspace_row.pack_start(self.workspace_toggle, False, False, 0)
        self.workspace_color = Gtk.ColorButton()
        workspace_rgba = Gdk.RGBA()
        workspace_rgba.parse('#' + workspace_color)
        self.workspace_color.set_rgba(workspace_rgba)
        self.workspace_color.set_title('Workspace indicator color')
        workspace_row.pack_start(self.workspace_color, False, False, 0)
        workspace_row.pack_start(Gtk.Label(label='Indicator color', xalign=0), False, False, 0)
        self.workspace_toggle.connect('toggled', self.workspace_changed)
        self.workspace_color.connect('color-set', self.workspace_changed)
        outer.pack_start(workspace_row, False, False, 0)
        self.status = Gtk.Label(label='Looking for keyboards…', xalign=0)
        self.status.set_name('status')
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_selectable(True)
        outer.pack_start(self.status, False, False, 0)
        self.refresh_profile_list()
        self.update_controls()
        GLib.idle_add(self.refresh_devices)

    @staticmethod
    def button(label, callback):
        button = Gtk.Button(label=label)
        button.connect('clicked', callback)
        return button

    def set_status(self, message, error=False):
        self.status.set_text(message)
        context = self.status.get_style_context()
        context.add_class('error') if error else context.remove_class('error')

    def update_controls(self):
        if hasattr(self, 'apply_button'):
            self.apply_button.set_sensitive(not self.busy and 0 <= self.device_combo.get_active() < len(self.devices))
        if hasattr(self, 'onboard_button'):
            index = self.device_combo.get_active()
            device = self.devices[index] if 0 <= index < len(self.devices) else None
            self.onboard_button.set_sensitive(not self.busy and device is not None and
                                              (device.vendor.lower(), device.product.lower()) == ('046d', 'c358'))
        if hasattr(self, 'keepalive_toggle'):
            self.keepalive_toggle.set_sensitive(not self.busy)
        if hasattr(self, 'workspace_toggle'):
            self.workspace_toggle.set_sensitive(not self.busy)
            self.workspace_color.set_sensitive(not self.busy)
        self.refresh_button.set_sensitive(not self.busy)
        if hasattr(self, 'path_entry'):
            self.path_entry.set_sensitive(not self.busy)
        if hasattr(self, 'browse_button'):
            self.browse_button.set_sensitive(not self.busy)

    def device_changed(self, *_):
        active = self.device_combo.get_active()
        selected = self.devices[active] if 0 <= active < len(self.devices) else None
        if self.applied_lighting is not None and selected != self.applied_lighting[1]:
            self.stop_keepalive()
            self.applied_lighting = None
        self.update_controls()

    def stop_keepalive(self):
        self.keepalive_generation += 1
        if self.keepalive_source:
            GLib.source_remove(self.keepalive_source)
            self.keepalive_source = 0
        if self.activity_restore_source:
            GLib.source_remove(self.activity_restore_source)
            self.activity_restore_source = 0
        if self.activity_monitor is not None:
            self.activity_monitor.close()
            self.activity_monitor = None

    def start_keepalive(self):
        self.stop_keepalive()
        if not self.closed and self.applied_lighting is not None and self.keepalive_toggle.get_active():
            self.keepalive_source = GLib.timeout_add_seconds(15, self.refresh_applied_lighting)
            _executable, device, _profile = self.applied_lighting
            if (device.vendor, device.product) == ('046d', 'c358'):
                generation = self.keepalive_generation
                self.activity_monitor = G515ActivityMonitor(
                    device,
                    lambda: GLib.idle_add(self.on_g515_activity, generation),
                    lambda error: GLib.idle_add(self.on_g515_activity_error, generation, error))
                self.activity_monitor.start()

    def on_g515_activity(self, generation):
        if (not self.closed and generation == self.keepalive_generation and
                self.keepalive_source and not self.activity_restore_source):
            # Let the keyboard finish its firmware wake transition first.
            self.activity_restore_source = GLib.timeout_add(100, self.restore_after_g515_wake, generation)
        return False

    def restore_after_g515_wake(self, generation):
        if self.closed or generation != self.keepalive_generation or not self.keepalive_source:
            self.activity_restore_source = 0
            return False
        if self.busy or (self.keepalive_future is not None and not self.keepalive_future.done()):
            return True
        self.activity_restore_source = 0
        self.refresh_applied_lighting()
        return False

    def on_g515_activity_error(self, generation, _error):
        if not self.closed and generation == self.keepalive_generation:
            self.set_status('Wake detection unavailable; periodic lighting refresh remains active.', error=True)
        return False

    def enable_background_keeper(self):
        if self.applied_lighting is None:
            self.set_status('Apply a design to enable background lighting.')
            return
        try:
            background_keeper.enable(*self.applied_lighting)
        except (OSError, ValueError) as error:
            try:
                background_keeper.disable()
            except OSError:
                pass
            self.start_keepalive()
            self.set_status(f'Background lighting unavailable; keeping it active while open: {error}', error=True)
        else:
            self.stop_keepalive()
            self.set_status('Lighting applied. Background lighting will also start at login.')

    def keepalive_changed(self, toggle):
        if getattr(self, '_updating_keepalive', False):
            return
        if toggle.get_active():
            self.enable_background_keeper()
        else:
            self.stop_keepalive()
            try:
                background_keeper.disable()
            except OSError as error:
                self.set_status(f'Could not turn off background lighting: {error}', error=True)
            else:
                self.set_status('Background lighting turned off.')

    def workspace_changed(self, *_):
        rgba = self.workspace_color.get_rgba()
        color = ''.join(f'{round(max(0, min(1, value)) * 255):02x}'
                        for value in (rgba.red, rgba.green, rgba.blue))
        active = self.workspace_toggle.get_active()
        try:
            workspace_indicator.save(active, color)
        except (OSError, ValueError) as error:
            self.set_status(f'Could not save workspace indicator: {error}', error=True)
            return
        if active and not workspace_indicator.supported_session():
            self.set_status('The workspace indicator currently requires an X11 session.', error=True)
            return
        if background_keeper.load() is None:
            self.set_status('Apply a design with background lighting enabled to show the workspace.')
            return
        if timer_store.load():
            self.set_status('Workspace setting saved. It takes effect after restarting the helper.')
            return
        self.set_status('Updating workspace indicator…')
        self.run_task(background_keeper.restart_helper,
                      lambda _result: self.set_status('Workspace indicator updated.'))

    def refresh_applied_lighting(self):
        if self.closed or self.applied_lighting is None or not self.keepalive_toggle.get_active():
            self.keepalive_source = 0
            return False
        if self.busy or (self.keepalive_future is not None and not self.keepalive_future.done()):
            return True
        generation = self.keepalive_generation
        executable, device, profile = self.applied_lighting
        def refresh():
            if self.closed or generation != self.keepalive_generation:
                return
            Controller(executable).apply(device, profile)
        def finished(future):
            if self.closed or generation != self.keepalive_generation:
                return False
            try:
                future.result()
            except Exception as error:
                self.stop_keepalive()
                self.set_status(f'Could not keep lighting active: {error}', error=True)
            else:
                # The CLI restores its own event flags while reclaiming the LEDs.
                if self.activity_monitor is not None:
                    self.activity_monitor.rearm_notifications()
            return False
        try:
            self.keepalive_future = self.executor.submit(refresh)
            self.keepalive_future.add_done_callback(lambda future: GLib.idle_add(finished, future))
        except RuntimeError:
            self.keepalive_source = 0
            return False
        return True

    def controller_changed(self, *_):
        self.stop_keepalive()
        self.applied_lighting = None
        self.devices = []
        self.device_combo.remove_all()
        self.update_controls()
        if hasattr(self, 'status'):
            self.set_status('Controller changed. Select Refresh to find keyboards.')

    def run_task(self, work, done):
        if self.busy:
            return
        self.busy = True
        self.update_controls()
        future = self.executor.submit(work)
        def finished():
            if self.closed:
                return False
            self.busy = False
            try:
                result = future.result()
            except (ControllerError, OSError, ValueError) as error:
                self.set_status(str(error), error=True)
            except Exception:
                self.set_status('The controller request failed unexpectedly.', error=True)
            else:
                done(result)
            self.update_controls()
            return False
        future.add_done_callback(lambda _: GLib.idle_add(finished))

    def refresh_devices(self, *_):
        executable = self.path_entry.get_text().strip()
        self.devices = []
        self.device_combo.remove_all()
        self.set_status('Looking for keyboards…')
        def found(result):
            devices, notice = result
            self.devices = devices
            for device in devices:
                self.device_combo.append_text(device.label)
            if devices:
                self.device_combo.set_active(0)
                self.set_status(notice or f'{len(devices)} compatible keyboard(s) found.', error=bool(notice))
            else:
                self.set_status('No compatible keyboards found. Check the controller and device access.', error=True)
        def detect():
            controller = Controller(executable)
            devices = controller.devices()
            return devices, controller.notice
        self.run_task(detect, found)
        return False

    def paint_color(self):
        rgba = self.color_button.get_rgba()
        return ''.join(f'{round(max(0, min(1, value)) * 255):02x}' for value in (rgba.red, rgba.green, rgba.blue))

    def brightness_changed(self, scale):
        value = round(scale.get_value())
        self.profile.set_brightness(value)
        self.brightness_label.set_text(f'{value}%')
        self.preview.queue_draw()
        if not self._switching_profile:
            self.profile_modified('Brightness updated. Apply to send it to the keyboard.')

    def fill_all(self, *_):
        self.profile.set_all(self.paint_color())
        self.preview.queue_draw()
        self.profile_modified('Preview updated. Apply to send it to the keyboard.')

    def clear_all(self, *_):
        self.profile.set_all('000000')
        self.preview.queue_draw()
        self.profile_modified('Preview updated. Apply to send it to the keyboard.')

    def start_timer(self, *_):
        if self.busy:
            return
        seconds = int(self.timer_minutes.get_value()) * 60 + int(self.timer_seconds.get_value())
        index = self.device_combo.get_active()
        current = self.applied_lighting or background_keeper.load()
        if not current or not 0 <= index < len(self.devices) or current[1] != self.devices[index]:
            self.set_status('Apply a design to the selected keyboard before starting the timer.', error=True)
            return
        if not 1 <= seconds <= 86400:
            self.set_status('Choose a duration between 1 second and 24 hours.', error=True)
            return
        self.stop_keepalive()
        self.set_status('Starting timer…')
        def started(_result):
            self.set_status('Timer started. The top row will count down and flash red.')
            self.update_timer_display()
        self.run_task(lambda: timer_store.start_service(*current, seconds), started)

    def cancel_timer(self, *_):
        try:
            timer_store.cancel()
        except OSError as error:
            self.set_status(f'Could not cancel timer: {error}', error=True)
            return
        self.set_status('Timer cancelled. Restoring the applied lighting.')
        self.update_timer_display()

    def update_timer_display(self):
        active = timer_store.load()
        self.timer_cancel_button.set_sensitive(active is not None)
        if active:
            remaining = max(0, int(active[0]['end'] - time.time() + .999))
            if remaining:
                self.timer_label.set_text(f'{remaining // 60}:{remaining % 60:02d} remaining')
            else:
                self.timer_label.set_text('Time is up!')
        else:
            self.timer_label.set_text('')
        return True

    def save_onboard_color(self, *_):
        index = self.device_combo.get_active()
        if self.busy or not 0 <= index < len(self.devices):
            return
        device = self.devices[index]
        if (device.vendor.lower(), device.product.lower()) != ('046d', 'c358'):
            self.set_status('Default color is supported only on the wired G515 TKL.', error=True)
            return
        if timer_store.load():
            self.set_status('Cancel the timer before saving the default color.', error=True)
            return
        color = self.paint_color()
        brightness = self.profile.brightness
        color = ''.join(f'{(int(color[i:i+2], 16) * brightness + 50) // 100:02x}' for i in (0, 2, 4))
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE, text='Save a default keyboard color?')
        dialog.format_secondary_text(
            'This writes the selected paint color and brightness as a solid color to the wired G515. '
            'Per-key designs cannot be stored this way. The existing onboard profile will be backed up. '
            'The background helper will restore your per-key design when the keyboard wakes. '
            'Close other lighting apps first.')
        idle_row = Gtk.Box(spacing=8)
        idle_row.set_margin_start(12)
        idle_row.set_margin_end(12)
        idle_row.set_margin_bottom(12)
        idle_off = Gtk.CheckButton(label='Turn off backlight after idle')
        idle_off.set_active(True)
        idle_seconds = Gtk.SpinButton.new_with_range(3, 65534, 1)
        idle_seconds.set_value(60)
        idle_off.connect('toggled', lambda toggle: idle_seconds.set_sensitive(toggle.get_active()))
        idle_row.pack_start(idle_off, False, False, 0)
        idle_row.pack_start(idle_seconds, False, False, 0)
        idle_row.pack_start(Gtk.Label(label='seconds'), False, False, 0)
        dialog.get_content_area().pack_start(idle_row, False, False, 0)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Save color', Gtk.ResponseType.OK)
        dialog.show_all()
        try:
            confirmed = dialog.run() == Gtk.ResponseType.OK
            idle_off_after = int(idle_seconds.get_value()) if idle_off.get_active() else None
        finally:
            dialog.destroy()
        if not confirmed:
            return
        previous = self.applied_lighting or background_keeper.load(include_disabled=True)
        if previous is None or previous[1] != device:
            previous = (self.path_entry.get_text().strip(), device,
                        LightingProfile(dict(self.profile.colors), self.profile.brightness))
        restart_keeper = idle_off_after is not None or self.keepalive_toggle.get_active()
        self.stop_keepalive()
        self.keepalive_toggle.set_active(False)
        self.set_status('Backing up and saving the keyboard profile…')
        def work():
            try:
                background_keeper.disable()
                backup = g515_onboard.save_solid(device, color, idle_off_after=idle_off_after)
                if restart_keeper:
                    background_keeper.enable(*previous, idle_off_after=idle_off_after)
                return backup
            except (g515_onboard.OnboardError, ActivityError) as error:
                raise ControllerError(str(error)) from error
        def done(backup):
            self.applied_lighting = previous if restart_keeper else None
            if restart_keeper:
                self._updating_keepalive = True
                try:
                    self.keepalive_toggle.set_active(True)
                finally:
                    self._updating_keepalive = False
            self.set_status(f'Default color saved; custom lighting restores on wake. Backup: {backup}'
                            if restart_keeper else f'Default color saved. Backup: {backup}')
        self.run_task(work, done)

    def apply_profile(self, *_):
        if timer_store.load():
            self.set_status('Cancel the timer before applying another design.', error=True)
            return
        index = self.device_combo.get_active()
        if not 0 <= index < len(self.devices):
            return
        device = self.devices[index]
        executable = self.path_entry.get_text().strip()
        snapshot = LightingProfile(dict(self.profile.colors), self.profile.brightness)
        self.stop_keepalive()
        self.applied_lighting = None
        self.set_status('Applying lighting…')
        def applied(_result):
            self.applied_lighting = (executable, device, snapshot)
            if self.keepalive_toggle.get_active():
                self.enable_background_keeper()
            else:
                try:
                    background_keeper.save_applied(executable, device, snapshot)
                except OSError as error:
                    self.set_status(f'Lighting applied, but could not save it for terminal timers: {error}', error=True)
                else:
                    self.set_status(f'Lighting applied to {device.name}.')
        self.run_task(lambda: Controller(executable).apply(device, snapshot), applied)

    def choose_controller(self, *_):
        dialog = Gtk.FileChooserDialog(title='Choose g810-led', transient_for=self,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Choose', Gtk.ResponseType.OK)
        try:
            if dialog.run() == Gtk.ResponseType.OK:
                self.path_entry.set_text(dialog.get_filename())
        finally:
            dialog.destroy()

    def profile_modified(self, message):
        self.set_status(message)
        self.queue_profile_save()

    def queue_profile_save(self):
        if self.profile_save_source:
            GLib.source_remove(self.profile_save_source)
        self.profile_save_source = GLib.timeout_add(350, self.flush_profile_save)

    def flush_profile_save(self):
        self.profile_save_source = 0
        try:
            self.profile_store.save()
        except OSError as error:
            self.set_status(f'Could not save profiles: {error}', error=True)
        return False

    def refresh_profile_list(self):
        self._updating_profiles = True
        try:
            for row in self.profile_list.get_children():
                row.destroy()
            selected = None
            for entry in self.profile_store.entries:
                row = Gtk.ListBoxRow()
                row.profile_id = entry['id']
                label = Gtk.Label(label=entry['name'], xalign=0)
                label.set_ellipsize(Pango.EllipsizeMode.END)
                row.add(label)
                self.profile_list.add(row)
                if entry['id'] == self.profile_store.selected:
                    selected = row
            self.profile_list.show_all()
            if selected is not None:
                self.profile_list.select_row(selected)
            self.rename_profile_button.set_sensitive(not self.profile_store.read_only)
            self.delete_profile_button.set_sensitive(not self.profile_store.read_only and len(self.profile_store.entries) > 1)
        finally:
            self._updating_profiles = False

    def profile_selected(self, _list, row):
        if self._updating_profiles or row is None:
            return
        if row.profile_id == self.profile_store.selected:
            return
        self.profile_store.selected = row.profile_id
        self.show_current_profile()
        self.queue_profile_save()
        self.set_status('Profile selected. Apply to send it to the keyboard.')

    def show_current_profile(self):
        self._switching_profile = True
        try:
            self.profile = self.preview.profile = self.profile_store.current()['profile']
            self.brightness_scale.set_value(self.profile.brightness)
            self.brightness_label.set_text(f'{self.profile.brightness}%')
            self.preview.queue_draw()
        finally:
            self._switching_profile = False

    def ask_profile_name(self, title, initial=''):
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Save', Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_border_width(16)
        entry = Gtk.Entry()
        entry.set_max_length(80)
        entry.set_text(initial)
        entry.set_activates_default(True)
        content.pack_start(entry, False, False, 0)
        error = Gtk.Label(xalign=0)
        error.set_name('profile-warning')
        content.pack_start(error, False, False, 0)
        dialog.show_all()
        try:
            while dialog.run() == Gtk.ResponseType.OK:
                name = entry.get_text().strip()
                try:
                    self.profile_store._unique_name(name, self.profile_store.selected if title == 'Rename profile' else None)
                    return name
                except ValueError as problem:
                    error.set_text(str(problem))
        finally:
            dialog.destroy()
        return None

    def new_profile(self, *_):
        if self.profile_store.read_only:
            self.set_status('The existing profile library could not be read; it was left unchanged.', error=True)
            return
        name = self.ask_profile_name('New profile')
        if name is not None:
            self.profile_store.create(name, self.profile)
            self.show_current_profile()
            self.refresh_profile_list()
            self.queue_profile_save()
            self.set_status('Profile created from the current design.')

    def rename_profile(self, *_):
        name = self.ask_profile_name('Rename profile', self.profile_store.current()['name'])
        if name is not None:
            self.profile_store.rename(self.profile_store.selected, name)
            self.refresh_profile_list()
            self.queue_profile_save()
            self.set_status('Profile renamed.')

    def delete_profile(self, *_):
        if len(self.profile_store.entries) <= 1:
            return
        entry = self.profile_store.current()
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.NONE, text=f'Delete “{entry["name"]}”?')
        dialog.format_secondary_text('This removes the saved profile from this app.')
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Delete', Gtk.ResponseType.OK)
        try:
            confirmed = dialog.run() == Gtk.ResponseType.OK
        finally:
            dialog.destroy()
        if confirmed:
            self.profile_store.delete(entry['id'])
            self.show_current_profile()
            self.refresh_profile_list()
            self.queue_profile_save()
            self.set_status('Profile deleted.')

    def import_profile(self, *_):
        if self.profile_store.read_only:
            self.set_status('The existing profile library could not be read; it was left unchanged.', error=True)
            return
        dialog = Gtk.FileChooserDialog(title='Import old lighting profile', transient_for=self,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Import', Gtk.ResponseType.OK)
        try:
            path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        finally:
            dialog.destroy()
        if path:
            try:
                profile = LightingProfile.load(path)
                base = Path(path).stem[:70] or 'Imported profile'
                name, number = base, 2
                while any(e['name'].casefold() == name.casefold() for e in self.profile_store.entries):
                    name, number = f'{base} {number}', number + 1
                self.profile_store.create(name, profile)
            except (OSError, ValueError) as error:
                self.set_status(f'Could not import profile: {error}', error=True)
                return
            self.show_current_profile()
            self.refresh_profile_list()
            self.queue_profile_save()
            self.set_status('Profile imported. Apply to send it to the keyboard.')

    def close(self, *_):
        if self.timer_ui_source:
            GLib.source_remove(self.timer_ui_source)
            self.timer_ui_source = 0
        if self.profile_save_source:
            GLib.source_remove(self.profile_save_source)
            self.flush_profile_save()
        self.closed = True
        self.stop_keepalive()
        self.executor.shutdown(wait=False, cancel_futures=True)
        Gtk.main_quit()


def main():
    GLib.set_prgname('keyboard-lights')
    GLib.set_application_name('Keyboard Lights')
    Gtk.Window.set_default_icon_name('keyboard-lights')
    window = LightingWindow()
    window.set_wmclass('keyboard-lights', 'keyboard-lights')
    window.show_all()
    Gtk.main()


if __name__ == '__main__':
    main()
