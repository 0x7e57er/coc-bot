# Background BlueStacks support: implementation notes

The current device backend is foreground/desktop automation, not an emulator automation backend:

- `ImageGrab.grab()` reads the physical desktop.
- `pyautogui` sends mouse input to the desktop.
- `pynput` sends keyboard input to the focused application.
- `prepare()` deliberately activates the BlueStacks window before every capture and input.

Removing the activation call is unsafe: a click could reach another application and screenshots could
show the wrong window. Windows window messages are not a drop-in replacement for actual game input,
and minimized/occluded GPU-rendered windows are not guaranteed to produce usable captures.

A real background implementation should be a separate device backend with all three parts:

1. **Capture:** obtain a frame from the BlueStacks render surface (for example, a tested Windows
   Graphics Capture / Desktop Duplication path, or an emulator-supported screenshot interface) and
   normalize it to the exact game-space calibration used by `bot/space.py`.
2. **Touch:** send taps and swipes through ADB (`input tap`, `input swipe`) in Android display
   coordinates. Do not use desktop-global mouse events.
3. **Keyboard/zoom:** map the BlueStacks zoom gesture to a verified Android-side gesture or
   emulator input command. Do not send global key events.

The backend must be validated with a running and minimized BlueStacks instance and with another
desktop application in the foreground. Before enabling automation, a preflight should verify the
captured image dimensions, locate known UI templates, and confirm a harmless test touch. Until those
tests pass, foreground mode remains the supported mode.

The current bot's full-screen pixel calibration and extensive screen-reading flow mean that a
background backend should not be enabled by a settings toggle alone.
