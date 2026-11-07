# Keyboard Lights

A GTK 3 Linux desktop application for Logitech keyboard lighting, with a bundled, modified [g810-led](https://github.com/MatMoul/g810-led) controller. Paint a tenkeyless keyboard preview, save or load designs, and apply the result to a selected keyboard using the installed controller. The preview starts with a default color: g810-led does not provide a way for this app to read back the keyboard's current per-key colors.

## Run

Install Python 3, PyGObject, pycairo and GTK 3. On Ubuntu:

```bash
sudo apt install python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-3.0 make g++ libusb-1.0-0-dev
```

Install for your user (no root required):

```bash
git clone https://github.com/visageeee/keyboard-lights.git
cd keyboard-lights
/usr/bin/python3 install.py
```

Launch **Keyboard Lights** from the applications menu or run `keyboard-lights`. The app is copied into `~/.local/share/keyboard-lights`; re-run the installer after updating the source. Its command launchers are installed into `~/.local/bin`, which should be on your `PATH`. Existing profiles and background-lighting settings are kept. You can also run the source directly with `/usr/bin/python3 main.py`.

The installer builds the bundled controller from source using libusb and installs it alongside the app. You can use **Browse** to select a different build and **Refresh** to detect keyboards. For running from a source checkout, first run `make -C vendor/g810-led bin LIB=libusb`.

Click or drag across the preview to paint keys; click a key in the selected color again to turn it off. Drag from a painted key to erase a group. **Fill all keys** colors the entire layout. Use the **Brightness** slider to scale the preview and the output from 0–100%; full colors are preserved in saved profiles. The preview is not sent to the device until **Apply to keyboard** is pressed. With **Keep applied lighting active after closing (start at login)** enabled, applying a design starts a small per-user helper. It reapplies the last successfully applied design on keyboard wake and periodically, even after the window closes, and starts again when you log in. On the G515 it listens only for generic activity notifications, not individual keys. The keyboard can still briefly show its built-in lighting during wake. Uncheck the option to stop the helper and remove its login autostart. This uses a background process, not permanent onboard storage; it only works while your desktop user is logged in. If background setup fails, the app reports the error and keeps the lighting active only while its window is open. Unapplied preview edits are never sent by the helper. The helper configuration is stored in `$XDG_CONFIG_HOME/keyboard-lights/keeper.json` and its login entry in `$XDG_CONFIG_HOME/autostart/keyboard-lights-keeper.desktop` (normally under `~/.config`). The **Profiles** sidebar keeps named profiles locally and saves edits automatically. Use **+** to copy the current design into a new profile, select a profile to edit it, or use **Rename** and **Delete** to manage it. Selecting a profile changes only the preview; press **Apply to keyboard** to send it. Existing JSON profiles can be brought in using **Import old profile**. The profile library is stored in `$XDG_CONFIG_HOME/keyboard-lights/profiles.json` (normally `~/.config/keyboard-lights/profiles.json`). The app passes a validated `g810-led -pp` profile to the controller without invoking a shell.


## Timer

Apply a design, set a duration in minutes and seconds, and press **Start timer**. The top row turns blue and empties from right to left. At zero it flashes red for 30 seconds, then restores the applied design. **Cancel timer** restores it early. The timer continues after the window closes while you remain logged in. Cancel it before applying a different design.

To control the same timer from a terminal or desktop keyboard shortcut, apply a design in the GUI once, then use:

```bash
keyboard-lights-timer start 25m
keyboard-lights-timer status
keyboard-lights-timer cancel
```

A bare number means minutes; suffixes support seconds, minutes and hours, such as `90s` or `1h30m` (maximum 24 hours). Starting another timer replaces the current one. The last applied design is used even when the background-lighting option is off. The command starts the timer asynchronously; as with the GUI, device access and a working controller are required.

## G515 TKL notes

The bundled controller includes experimental G515 TKL per-key support. This interface uses ordinary keyboard keys only; it does not enable unsupported G515 native effects or onboard storage. The preview uses a Nordic ISO TKL layout, including the extra key next to left Shift and the key beside Enter. Other models with per-key control may work, but the preview does not represent numpads, logos, media keys, white-only keyboards or zone-only models.

The controller needs access to the keyboard. If it reports **Permission denied**, configure device access as described by your controller's installation instructions and reconnect the device. This GUI does not run the controller as root or change udev rules. The included `69-g515-led.rules` grants the active local desktop user access to G515 HID interfaces; installing it requires administrator privileges and a udev reload. The bundled controller may crash in `--list-keyboards` on some systems; when it advertises G515 support, the GUI falls back to read-only Linux sysfs discovery and reports the crash. Applying still requires a working controller and device permissions.

## Tests

```bash
/usr/bin/python3 -m unittest -v
```

The tests use a fake controller and do not change keyboard lighting.

## License and attribution

Keyboard Lights and the bundled modified controller are distributed under the GNU General Public License, version 3; see [LICENSE](LICENSE). The controller is based on [g810-led](https://github.com/MatMoul/g810-led) at upstream commit `efa3c35`. Its original copyright and contributor notices are retained in [vendor/g810-led](vendor/g810-led), and the local changes are documented in [LOCAL-MODIFICATIONS.md](vendor/g810-led/LOCAL-MODIFICATIONS.md).
