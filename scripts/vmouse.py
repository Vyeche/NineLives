#!/usr/bin/env python3
# vmouse.py — temporary virtual mouse for testing a kitty window. Steers by reading the pointer
# position from that kitty's --debug-input log, so pointer acceleration and monitor layout don't
# matter. Presses only when the log's latest event shows the pointer inside that kitty window.
#   python3 -I vmouse.py LOG step [step ...]
#   steps: wiggle | goto:X,Y | down | up | mdown | mup | sleep:S | shot:DIR | key:ctrl+alt+z
# key: types a shortcut, only while the log says that kitty window has keyboard focus.
import re
import subprocess
import sys
import time

import evdev
from evdev import ecodes as e

LOG = sys.argv[1]
POS_RE = re.compile(r"(?:Move\S* x: ([\d.]+) y: ([\d.]+))|(?:entered window: \d+ at ([\d.]+)x([\d.]+))|(left window)")
FOCUS_RE = re.compile(r"on_focus_change\S* window id: \S+ focused: (\d)")

state = {"off": 0, "pos": None, "inside": False, "focused": False}


def poll():
    with open(LOG, "rb") as f:
        f.seek(state["off"])
        data = f.read()
        state["off"] += len(data)
    for m in POS_RE.finditer(data.decode("utf-8", "replace")):
        if m.group(5):
            state["inside"] = False
        else:
            x, y = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            state["pos"], state["inside"] = (float(x), float(y)), True
    for m in FOCUS_RE.finditer(data.decode("utf-8", "replace")):
        state["focused"] = m.group(1) == "1"
    return state["pos"]


def rel(ui, dx, dy):
    ui.write(e.EV_REL, e.REL_X, int(dx))
    ui.write(e.EV_REL, e.REL_Y, int(dy))
    ui.syn()


def button(ui, code, value):
    if not state["inside"]:
        sys.exit(f"refusing to press: pointer not inside the test window (last {state['pos']})")
    ui.write(e.EV_KEY, code, value)
    ui.syn()
    time.sleep(0.05)


def goto(ui, tx, ty, tol=3.0):
    for _ in range(600):
        time.sleep(0.02)
        pos = poll()
        if pos is None:
            rel(ui, 1, 0)
            continue
        dx, dy = tx - pos[0], ty - pos[1]
        if abs(dx) <= tol and abs(dy) <= tol:
            return pos
        sx = max(-6, min(6, round(dx * 0.4))) or (1 if dx > tol else -1 if dx < -tol else 0)
        sy = max(-6, min(6, round(dy * 0.4))) or (1 if dy > tol else -1 if dy < -tol else 0)
        rel(ui, sx, sy)
    sys.exit(f"could not reach {tx},{ty}; last {state['pos']}")


MODS = {"ctrl": e.KEY_LEFTCTRL, "alt": e.KEY_LEFTALT, "shift": e.KEY_LEFTSHIFT}
KEYS = [getattr(e, n) for n in dir(e) if n.startswith("KEY_") and isinstance(getattr(e, n), int)
        and getattr(e, n) < 0x100]


def key_code(name):
    name = {"pageup": "PAGEUP", "pagedown": "PAGEDOWN", "page_up": "PAGEUP", "page_down": "PAGEDOWN", "=": "EQUAL", "-": "MINUS", "/": "SLASH"}.get(
        name, name.upper())
    return MODS.get(name.lower()) or getattr(e, "KEY_" + name)


def press_keys(ui, combo):
    poll()
    if not state["focused"]:
        sys.exit(f"refusing to type {combo}: the test window doesn't have keyboard focus")
    codes = [key_code(k) for k in combo.split("+")]
    for c in codes:
        ui.write(e.EV_KEY, c, 1); ui.syn(); time.sleep(0.03)
    for c in reversed(codes):
        ui.write(e.EV_KEY, c, 0); ui.syn(); time.sleep(0.03)


ui = evdev.UInput({e.EV_REL: [e.REL_X, e.REL_Y],
                   e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE] + KEYS},
                  name="claude-test-vmouse")
try:
    time.sleep(1.0)  # let the compositor pick the device up
    with open(LOG, "rb") as f:
        state["off"] = 0
    poll()
    for step in sys.argv[2:]:
        name, _, arg = step.partition(":")
        if name == "wiggle":
            rel(ui, 2, 0); time.sleep(0.05); rel(ui, -2, 0); time.sleep(0.1); poll()
        elif name == "goto":
            x, y = map(float, arg.split(","))
            print("at", goto(ui, x, y), flush=True)
        elif name == "down":
            poll(); button(ui, e.BTN_LEFT, 1)
        elif name == "up":
            ui.write(e.EV_KEY, e.BTN_LEFT, 0); ui.syn(); time.sleep(0.05)
        elif name == "mdown":
            poll(); button(ui, e.BTN_MIDDLE, 1)
        elif name == "mup":
            ui.write(e.EV_KEY, e.BTN_MIDDLE, 0); ui.syn(); time.sleep(0.05)
        elif name == "key":
            press_keys(ui, arg)
        elif name == "sleep":
            time.sleep(float(arg))
        elif name == "shot":
            subprocess.run(["cosmic-screenshot", "--interactive=false", "--modal=false", "--notify=false",
                            "--save-dir", arg], timeout=15)
        print("done", step, "pos", state["pos"], "inside", state["inside"], flush=True)
finally:
    # never leave a button held
    for code in (e.BTN_LEFT, e.BTN_MIDDLE, e.BTN_RIGHT, *MODS.values()):
        ui.write(e.EV_KEY, code, 0)
    ui.syn()
    ui.close()
