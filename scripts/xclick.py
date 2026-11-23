#!/usr/bin/env python3
"""xclick.py — click at X,Y on a hidden X display (the test kitty's Xvfb) with XTest. Never the
real desktop: refuses to run without an explicit DISPLAY argument.
    python3 scripts/xclick.py :97 X Y [button]"""
import ctypes
import sys
import time

disp, x, y = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
button = int(sys.argv[4]) if len(sys.argv) > 4 else 1
x11 = ctypes.CDLL("libX11.so.6")
xtst = ctypes.CDLL("libXtst.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
d = x11.XOpenDisplay(disp.encode())
if not d:
    sys.exit(f"cannot open display {disp}")
d = ctypes.c_void_p(d)
xtst.XTestFakeMotionEvent(d, -1, x, y, 0)
x11.XFlush(d)
time.sleep(0.15)
xtst.XTestFakeButtonEvent(d, button, True, 0)
x11.XFlush(d)
time.sleep(0.05)
xtst.XTestFakeButtonEvent(d, button, False, 0)
x11.XFlush(d)
x11.XCloseDisplay(d)
