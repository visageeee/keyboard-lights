# Local modifications

This is the source of [g810-led](https://github.com/MatMoul/g810-led), based on upstream commit `efa3c35` (version 0.4.3). The changes add experimental Logitech G515 TKL (USB ID 046d:c358) per-key lighting through the HID++ vendor interface, and update help output. See `src/classes/G515.cpp` and the G515 additions to `Keyboard.cpp` and `Keyboard.h`. Native G515 effects and saving per-key designs to onboard memory are not implemented. The upstream project and these changes are distributed under GPL-3.0-only; see `LICENSE` and `CONTRIBUTORS.md` in this directory.
