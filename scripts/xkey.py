#!/usr/bin/env python3
"""xkey.py — press keys on a hidden X display (the test kitty's Xvfb) with XTest, the way
xclick.py clicks. Never the real desktop: refuses to run without an explicit DISPLAY argument.
    python3 scripts/xkey.py :97 ctrl+alt+u            a shortcut (X keysym names joined by +)
    python3 scripts/xkey.py :97 ctrl+shift+space Tab Return
    python3 scripts/xkey.py :97 --type "api"          type text (letters, digits, space)
Keys go to the window X gives the focus to: on Xvfb with no window manager that's the one under
the pointer, so the test kitty, which fills the display."""
import ctypes
import sys
import time

if len(sys.argv) < 3 or not sys.argv[1].startswith(":"):
    sys.exit(__doc__)
disp = sys.argv[1]
x11 = ctypes.CDLL("libX11.so.6")
xtst = ctypes.CDLL("libXtst.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XStringToKeysym.restype = ctypes.c_ulong
x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
d = x11.XOpenDisplay(disp.encode())
if not d:
    sys.exit(f"cannot open display {disp}")
d = ctypes.c_void_p(d)
ALIAS = {"ctrl": "Control_L", "alt": "Alt_L", "shift": "Shift_L", "super": "Super_L",
         "enter": "Return", "esc": "Escape", "tab": "Tab", "backspace": "BackSpace", " ": "space"}


def code(name: str) -> int:
    sym = x11.XStringToKeysym(ALIAS.get(name.lower(), ALIAS.get(name, name)).encode())
    kc = x11.XKeysymToKeycode(d, sym) if sym else 0
    if not kc:
        sys.exit(f"unknown key: {name}")
    return kc


def press(combo: str) -> None:
    parts = [code(p) for p in (combo.split("+") if combo != "+" else ["plus"])]
    for kc in parts:
        xtst.XTestFakeKeyEvent(d, kc, True, 0)
        x11.XFlush(d)
        time.sleep(0.02)
    for kc in reversed(parts):
        xtst.XTestFakeKeyEvent(d, kc, False, 0)
        x11.XFlush(d)
        time.sleep(0.02)


args = sys.argv[2:]
if args[0] == "--type":
    for ch in " ".join(args[1:]):
        if ch.isupper():
            press("shift+" + ch.lower())
        else:
            press(ch)
        time.sleep(0.03)
else:
    for combo in args:
        press(combo)
        time.sleep(0.05)
x11.XCloseDisplay(d)
