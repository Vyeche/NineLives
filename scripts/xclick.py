#!/usr/bin/env python3
"""xclick.py — click at X,Y on a hidden X display (the test kitty's Xvfb) with XTest. Never the
real desktop: refuses to run without an explicit DISPLAY argument.
    python3 scripts/xclick.py :97 X Y [button]
    python3 scripts/xclick.py :97 X Y drag X2 Y2     press at X,Y, move to X2,Y2 in small steps, release"""
import ctypes
import sys
import time

disp, x, y = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
drag = sys.argv[5:7] if len(sys.argv) > 6 and sys.argv[4] == "drag" else None
button = 1 if drag else int(sys.argv[4]) if len(sys.argv) > 4 else 1
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
if drag:
    x2, y2 = int(drag[0]), int(drag[1])
    for i in range(1, 21):
        xtst.XTestFakeMotionEvent(d, -1, x + (x2 - x) * i // 20, y + (y2 - y) * i // 20, 0)
        x11.XFlush(d)
        time.sleep(0.03)
xtst.XTestFakeButtonEvent(d, button, False, 0)
x11.XFlush(d)
x11.XCloseDisplay(d)
