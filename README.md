# Keyboard Lights

A Linux app made specifically for the **Logitech G515 TKL**. Paint and save per-key lighting profiles, adjust brightness, and use the top row as a countdown timer. The preview uses a Nordic ISO layout. Other keyboards may work, but are not the focus of this app.

## Install

On Ubuntu or Debian, install the dependencies, then clone and install the app:

```bash
sudo apt install git python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-3.0 make g++ libusb-1.0-0-dev
git clone https://github.com/visageeee/keyboard-lights.git
cd keyboard-lights
/usr/bin/python3 install.py
```

Open **Keyboard Lights** from your applications menu. The installer builds the bundled controller and installs the app for your user. To update it, pull the latest changes and run the installer again.

If applying a design reports **Permission denied**, install the included device rule and reconnect the keyboard:

```bash
sudo install -m 644 69-g515-led.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

## Use

Paint the keys and press **Apply to keyboard**. Enable **Keep applied lighting active after closing** to restore the design when the keyboard wakes and after login. This uses a background helper while you are logged in; the design is not saved to the keyboard's onboard memory.

Set a timer in the app, or use these commands in a terminal or keyboard shortcut:

```bash
keyboard-lights-timer start 25m
keyboard-lights-timer status
keyboard-lights-timer cancel
```

The top row counts down in blue, then flashes red before restoring your design. Durations such as `90s` and `1h30m` are supported.

## License

GPL-3.0. The bundled controller is based on [g810-led](https://github.com/MatMoul/g810-led); its attribution and [local modifications](vendor/g810-led/LOCAL-MODIFICATIONS.md) are included in the repository.
