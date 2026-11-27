#!/usr/bin/env python3
"""cat-float.py — Nine, the cat, out on the desktop: a small see-through `kitten panel` (a
layer-shell overlay that never takes the keyboard) that holds the cat and its speech bubble, so the
cat can sit anywhere on the screen, next to kitty or away from it. Part of NineLives (stage 3).

    cat-float.py on | off       turn the floating cat on (and start it, from a NineLives kitty) or off
    cat-float.py status         is it on, is it running, where it sits
    cat-float.py start          the launcher: started by the main kitty (see HOOK below); it watches
                                the switches and the main kitty, and runs the panel while it should
    cat-float.py run            what runs inside the panel (the launcher starts it)
    cat-float.py run --demo N   a scripted visit for N seconds: fake tabs, no sounds, no kitty asked

How it works:
  - The panel is a kitty of its own (`kitten panel --edge=none --layer=overlay
    --focus-policy=not-allowed`, background_opacity 0), as big as the cat, or the cat and its bubble
    while it talks. The cat and the bubble are pictures (kitty's graphics protocol): the frames go in
    once, a new pose only moves a placement; the mouth is a placement of its own over the body (lip
    sync); the bubble's words appear left to right by cropping their picture (source rectangle).
  - It moves by moving the panel: remote control of the panel's own kitty (resize-os-window
    --action=os-panel --incremental margin-left=… margin-top=…) over its own socket in
    $XDG_RUNTIME_DIR (allow_remote_control socket-only; nothing else listens there).
  - A press on the cat or the bubble drags it (mouse reporting: SGR pixels, any motion); a click on
    the cat opens or closes the bubble; the bubble's buttons do what they say. Where you drop it is
    kept in $NINELIVES_STATE/cat-float.json.
  - The whole panel takes clicks (kitty sets no input region on a panel): it is kept as small as the
    cat while it doesn't talk.
  - What it says: cat-helper.py's suggestions() about the main kitty's tabs (read-only `kitten @
    --to <main socket> ls`), never twice in a row (a memory with cooldowns, cat-float-said.json).
  - Sounds: NineLives' own cat sounds (sounds/meow.oga …), with every sound switch: sounds-off,
    cat-sounds-off, sounds-classic (no cat sounds), sounds-volume; never with NINELIVES_QUIET or in a
    demo.
  - Off: the `cat-off` switch (the settings list's "The cat") hides it at once (the panel closes;
    the launcher keeps watching and brings it back when the switch goes); `cat-float.py off` (no
    `cat-float` file in the kitty config folder) ends it. It ends with the main kitty.
  - Never from the test kitty, the dev kitty or check.sh: `start` refuses without a Wayland display,
    with NINELIVES_QUIET or NL_TEST_DIR set (--force overrides).

HOOK (for tab_bar.py, once at startup; see the report that came with this file):
    _cat_float_start(boss) runs `python3 <config>/cat-float.py start --main-pid <kitty pid>
    --main-socket <boss.listening_on>` (detached), when the `cat-float` file exists.
"""
import base64
import datetime
import fcntl
import importlib.util
import json
import os
import random
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import termios
import time
import tty

HERE = os.path.dirname(os.path.abspath(__file__))
CAT_DIR = os.path.join(HERE, "cat")

# ---- settings ------------------------------------------------------------------------------------
CAT_PX = 128                 # the cat on the desktop (px, scaled from the 192 px frames with cairo)
DOCK = 72                    # what the bottom of each output keeps for the dock (COSMIC's: 72 px)
TOP_BAR = 36                 # and the top for the panel bar
FPS = 30.0                   # the panel moves and the words appear this often while anything moves
WALK_SPEED = 60.0            # px a second
WANDER_EVERY = (40.0, 110.0) # seconds between little walks along the floor
WALK_MOST = 360              # px at most in one walk
REVEAL_SPEED = 170.0         # px of words a second (about a word each quarter second)
SAY_HOLD = 7.0               # a line it said by itself stays this long after its last word
ASK_HOLD = 90.0              # a bubble you opened: until × or this long
UNPROMPTED_GAP = 180.0       # at most one line by itself every 3 minutes
TIP_EVERY = (1500.0, 2700.0) # and a tip every 25 to 45 minutes (kitty-cat talk on)
POLL = 2.0                   # seconds between looks at the main kitty's tabs
DRAG_SLOP = 4                # px a press may move and still be a click
SETTLE = 0.020               # after a move, motion this soon is still relative to the old place
BUBBLE_TEXT_W = 300          # px of words on a line at most
FONT = "DejaVu Sans"
# how long before the same thing may be said again (seconds), by kind; tabs: per tab and state
COOLDOWN = {"waiting": 600.0, "error": 600.0, "done": 600.0, "hello": 7200.0, "badge": 86400.0,
            "quest": 21600.0, "tip": 86400.0, "joke": 86400.0, "word": 86400.0}
SOUNDS = {"meow": ("meow.oga", 40000), "mrrp": ("mrrp.oga", 40000), "purr": ("purr.oga", 40000),
          "drop": ("drop.oga", 40000)}   # as tab_bar.py's SOUNDS (the cat's voice)


def conf_dir() -> str:
    return os.environ.get("KITTY_CONFIG_DIRECTORY") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "kitty")


def state_dir() -> str:
    return os.environ.get("NINELIVES_STATE") or os.path.expanduser("~/.local/state/ninelives")


def runtime_dir() -> str:
    return os.environ.get("XDG_RUNTIME_DIR") or state_dir()


_ch_mod = {}


def ch():
    """cat-helper.py (suggestions, frames, the words), loaded once; None if it can't be."""
    if "m" not in _ch_mod:
        try:
            spec = importlib.util.spec_from_file_location("ninelives_cat_helper", os.path.join(HERE, "cat-helper.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _ch_mod["m"] = mod
        except Exception:
            _ch_mod["m"] = None
    return _ch_mod["m"]


# ---- where things go (pure) ----------------------------------------------------------------------
def floor_y(out_h: int, cat: int = CAT_PX, dock: int = DOCK) -> int:
    """The y of the cat's top edge when it sits on the floor: right above the dock."""
    return max(0, out_h - dock - cat)


def home(out_w: int, out_h: int, cat: int = CAT_PX, dock: int = DOCK) -> tuple:
    """Where it first sits: the bottom-right corner, on the floor, a little in from the edge."""
    return max(0, out_w - cat - 48), floor_y(out_h, cat, dock)


def clamp(x: float, y: float, w: int, h: int, out_w: int, out_h: int, top: int = 0) -> tuple:
    """A w×h box at x,y moved the least so it is all on the output (and below `top`)."""
    x = min(max(0, int(round(x))), max(0, out_w - w))
    y = min(max(top, int(round(y))), max(top, out_h - h))
    return x, y


def restore(saved: dict, out_w: int, out_h: int, cat: int = CAT_PX, dock: int = DOCK) -> tuple:
    """Where it sits after a restart: where it was dropped (the output's size may have changed:
    clamped onto it, and kept on the floor if it was on the floor), or home."""
    try:
        x, y = float(saved["x"]), float(saved["y"])
    except (KeyError, TypeError, ValueError):
        return home(out_w, out_h, cat, dock)
    if saved.get("floor"):
        y = floor_y(out_h, cat, dock)
    return clamp(x, y, cat, cat, out_w, out_h)


def on_floor(y: float, out_h: int, cat: int = CAT_PX, dock: int = DOCK) -> bool:
    return abs(y - floor_y(out_h, cat, dock)) <= 6


def cells_for(px: int, cell: int) -> int:
    return max(1, -(-int(px) // max(1, cell)))


def layout(cat_xy, bubble_wh, cell_wh, out_wh, cat: int = CAT_PX, side=None, top: int = TOP_BAR) -> dict:
    """The panel around the cat (at cat_xy on the output) and, if bubble_wh, its bubble beside the
    cat's head: on `side` ("left"/"right") or the side with room (left first: the cat lives at the
    right). The panel is whole cells; the cat never moves on the screen because of the bubble.
    Returns cols, rows, margin (x, y: the panel's top-left on the output), cat (x, y in the panel),
    bubble (x, y in the panel, or None), side, and mouth (the cat's mouth, in the bubble's own px,
    for the bubble's tail)."""
    cw, chh = cell_wh
    out_w, out_h = out_wh
    cx, cy = int(cat_xy[0]), int(cat_xy[1])
    if not bubble_wh:
        return {"cols": cells_for(cat, cw), "rows": cells_for(cat, chh), "margin": (cx, cy),
                "cat": (0, 0), "bubble": None, "side": None, "mouth": None}
    bw, bh = bubble_wh
    tuck = int(cat * 0.12)                       # the frames' empty edge: the bubble's tail gets close
    room_left, room_right = cx + tuck, out_w - (cx + cat - tuck)
    if side not in ("left", "right"):
        side = "left" if room_left >= bw or room_left >= room_right else "right"
    bx = cx + tuck - bw if side == "left" else cx + cat - tuck
    mouth_y = cy + int(cat * 0.42)
    by = mouth_y + 14 - bh                       # the bubble's bottom just below the cat's mouth
    by = max(top, by)                            # no room above: it slides down beside the cat
    bx = min(max(0, bx), max(0, out_w - bw))
    by = min(by, max(top, out_h - bh))
    left, up = min(cx, bx), min(cy, by)
    right, down = max(cx + cat, bx + bw), max(cy + cat, by + bh)
    mouth = (cx + cat // 2 - bx, mouth_y - by)
    return {"cols": cells_for(right - left, cw), "rows": cells_for(down - up, chh), "margin": (left, up),
            "cat": (cx - left, cy - up), "bubble": (bx - left, by - up), "side": side, "mouth": mouth}


def cell_pos(px: int, py: int, cw: int, chh: int) -> tuple:
    """A pixel in the panel as (column, row, x offset, y offset), 0-based: where a placement goes."""
    px, py = max(0, int(px)), max(0, int(py))
    col, row = px // max(1, cw), py // max(1, chh)
    return col, row, px - col * cw, py - row * chh


def drag_to(margin, grab, local) -> tuple:
    """Dragging: the panel's new top-left so the point grabbed (grab: panel px at the press) is under
    the pointer again (local: the pointer in panel px, as the last motion reported it, relative to
    where the panel was when the compositor sent it: `margin`)."""
    return margin[0] + local[0] - grab[0], margin[1] + local[1] - grab[1]


def walk_target(x: float, out_w: int, cat: int, rng, lo: int = 0, hi=None) -> int:
    """Somewhere else on the floor, at most WALK_MOST px away, in [lo, hi]."""
    hi = out_w - cat if hi is None else hi
    lo, hi = max(0, lo), max(max(0, lo), hi)
    a, b = max(lo, int(x) - WALK_MOST), min(hi, int(x) + WALK_MOST)
    t = rng.randint(a, b) if b > a else a
    return t if abs(t - x) >= 40 or b - a < 40 else (a if x - a > b - x else b)


# ---- what it remembers (pure apart from the file) ------------------------------------------------
def load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_json(path: str, d: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, sort_keys=True)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def said_key(item: dict) -> str:
    """What makes a line the same line: its key (tab lines: the tab and its state's kind)."""
    return item.get("key") or f"{item.get('kind')}:{item.get('text', '')[:40]}"


def fresh(items, said: dict, now: float) -> list:
    """The lines not said within their kind's cooldown, in order. (A memory of its own until
    cat-helper.py has a shared one; see the report.)"""
    out = []
    for it in items:
        last = said.get(said_key(it))
        if last is None or now - float(last) >= COOLDOWN.get(it.get("kind"), 3600.0):
            out.append(it)
    return out


def remember(said: dict, item: dict, now: float, keep: int = 200) -> dict:
    said = dict(said)
    said[said_key(item)] = now
    if len(said) > keep:                          # the oldest go
        for k, _ in sorted(said.items(), key=lambda kv: kv[1])[:len(said) - keep]:
            del said[k]
    return said


# ---- sounds (pure: which command, if any) --------------------------------------------------------
def sound_argv(kind: str, conf: str, env=None, demo: bool = False):
    """paplay's command for one of the cat's sounds, or None when it must stay quiet: a demo,
    NINELIVES_QUIET (the dev and test kitties), sounds-off (all sounds), cat-sounds-off (the
    cat's), sounds-classic (the desktop's set has no cat), or no such file. The volume as
    tab_bar.py's: the sound's own level times kitty-sounds volume."""
    env = os.environ if env is None else env
    if demo or env.get("NINELIVES_QUIET") or kind not in SOUNDS:
        return None
    if any(os.path.exists(os.path.join(conf, f)) for f in ("sounds-off", "cat-sounds-off", "sounds-classic")):
        return None
    name, level = SOUNDS[kind]
    path = os.path.join(conf, "sounds", name)
    if not os.path.isfile(path):
        return None
    try:
        with open(os.path.join(conf, "sounds-volume"), encoding="utf-8") as f:
            pct = max(5, min(100, int(f.read().strip())))
    except (OSError, ValueError):
        pct = 100
    return ["paplay", f"--volume={level * pct // 100}", path]


# ---- the mouse (pure) ------------------------------------------------------------------------------
MOUSE_RE = re.compile(r"\x1b\[<(\d+);(-?\d+);(-?\d+)([Mm])")
FOCUS_RE = re.compile(r"\x1b\[([IO])")


def mouse_events(chunk: str) -> list:
    """SGR mouse reports (pixels with mode 1016) and focus reports in what the panel's kitty sent:
    [("press"|"release"|"move"|"drag"|"leave"|"scroll", button, x, y) or ("focus", in?, 0, 0)]"""
    out = []
    for m in re.finditer(r"\x1b\[<(\d+);(-?\d+);(-?\d+)([Mm])|\x1b\[([IO])", chunk):
        if m.group(5):
            out.append(("focus", m.group(5) == "I", 0, 0))
            continue
        cb, x, y, end = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
        button = cb & 3
        if cb & 64:
            out.append(("scroll", button, x, y))
        elif cb & 128 and cb & 32:
            out.append(("leave", 0, x, y))
        elif cb & 32:
            out.append(("move" if button == 3 else "drag", button, x, y))
        else:
            out.append(("release" if end == "m" else "press", button, x, y))
    return out


def hit(regions, x: int, y: int):
    """The thing at panel px (x, y): a button's command, "bubble", "cat", or None. regions:
    [(x0, y0, x1, y1, what)], the first that holds the point wins."""
    for x0, y0, x1, y1, what in regions:
        if x0 <= x < x1 and y0 <= y < y1:
            return what
    return None


# ---- the bubble: a picture (pycairo) or cells --------------------------------------------------------
THEMES = {   # text ≥ 4.5:1 on the fill, the border ≥ 3:1 (tests/test_cat_float.py checks)
    "light": {"fill": "#ffffff", "border": "#6e7781", "text": "#1f2328", "muted": "#57606a",
              "kinds": {"waiting": "#9a6700", "error": "#cf222e", "done": "#1a7f37", "badge": "#9a6700",
                        "quest": "#9a6700", "hello": "#0969da", "tip": "#0969da", "joke": "#8250df",
                        "word": "#8250df"},
              "do": ("#0969da", "#ffffff"), "next": ("#eaeef2", "#1f2328")},
    "dark": {"fill": "#24292f", "border": "#8c959f", "text": "#e6edf3", "muted": "#b1bac4",
             "kinds": {"waiting": "#d29922", "error": "#ff7b72", "done": "#3fb950", "badge": "#d29922",
                       "quest": "#d29922", "hello": "#58a6ff", "tip": "#58a6ff", "joke": "#d2a8ff",
                       "word": "#d2a8ff"},
             "do": ("#58a6ff", "#0d1117"), "next": ("#424a53", "#f0f6fc")},
}


def rgb(hexcol: str) -> tuple:
    h = hexcol.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def contrast(a: str, b: str) -> float:
    def lum(c):
        return sum(w * (x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4)
                   for w, x in zip((0.2126, 0.7152, 0.0722), rgb(c)))
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def buttons_for(item, n: int) -> list:
    """[(words, command)]: the action when the line offers one, Next › when there is more to say."""
    out = []
    if item.get("action"):
        out.append((f"{item.get('button', 'Go there')} ↵", "do"))
    if n > 1:
        out.append(("Next ›", "next"))
    return out


def wrap_px(words, width: float, measure) -> list:
    """Words in lines no wider than `width` (measure(text) -> px); a word too long sits alone."""
    lines, line = [], ""
    for w in words:
        trial = f"{line} {w}" if line else w
        if line and measure(trial) > width:
            lines.append(line)
            line = w
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


TAIL = 16                    # px the bubble's tail reaches out


def render_bubble(item, n: int, theme: str, side: str, mouth, prompted: bool, measure_only: bool = False):
    """The bubble as two PNGs (cairo): `bg` (shape, title, buttons, ×) and `text` (the words alone,
    on nothing), the same size, so the words can be shown a bit at a time by cropping `text`. The
    tail is drawn toward `mouth` (the cat's mouth in the bubble's px) on the cat's `side`. Returns
    {w, h, bg, text, lines: [(x, y, w, h, [word end x …])], regions: [(x0, y0, x1, y1, cmd)]}."""
    import cairo
    t = THEMES.get(theme, THEMES["light"])
    pad, title_h, line_h, btn_h, gap = 12, 20, 20, 24, 8
    probe = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))

    def setfont(cr, size, bold=False):
        cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(size)

    def width(text, size=14, bold=False):
        setfont(probe, size, bold)
        return probe.text_extents(text).x_advance
    lines = wrap_px(item["text"].split(), BUBBLE_TEXT_W, width)[:6]
    btns = buttons_for(item, n) if prompted else []
    btn_ws = [width(w, 13, True) + 20 for w, _ in btns]
    title = item.get("title", "")
    inner = max([width(x) for x in lines] + [width(title, 13, True) + 28, sum(btn_ws) + gap * max(0, len(btns) - 1), 120])
    bw = int(inner + 2 * pad)
    bh = int(pad + title_h + line_h * len(lines) + (btn_h + 10 if btns else 0) + pad - 4)
    w, h = bw + TAIL, bh
    ox = TAIL if side == "right" else 0           # the body's left edge in the picture
    if measure_only:
        return {"w": w, "h": h}
    mx, my = mouth if mouth else ((-TAIL * 2, bh - 20) if side == "right" else (w + TAIL * 2, bh - 20))
    surfaces = {}
    out_lines, regions = [], []
    for layer in ("bg", "text"):
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(s)
        cr.set_antialias(cairo.ANTIALIAS_GRAY)
        if layer == "bg":
            r = 12
            x0, y0, x1, y1 = ox + 1.5, 1.5, ox + bw - 1.5, bh - 1.5
            ty = min(max(y0 + r + 10, my), y1 - r - 4)          # where the tail leaves the body
            cr.new_path()
            cr.arc(x0 + r, y0 + r, r, 3.1416, 1.5 * 3.1416)
            cr.arc(x1 - r, y0 + r, r, 1.5 * 3.1416, 0)
            if side == "left":                                   # the cat is right of the bubble
                cr.line_to(x1, ty - 9)
                cr.line_to(min(w - 1.5, x1 + TAIL - 2), min(max(ty + 2, my), ty + 10))
                cr.line_to(x1, ty + 3)
            cr.arc(x1 - r, y1 - r, r, 0, 0.5 * 3.1416)
            cr.arc(x0 + r, y1 - r, r, 0.5 * 3.1416, 3.1416)
            if side == "right":
                cr.line_to(x0, ty + 3)
                cr.line_to(max(1.5, x0 - TAIL + 2), min(max(ty + 2, my), ty + 10))
                cr.line_to(x0, ty - 9)
            cr.close_path()
            cr.set_source_rgba(*rgb(t["fill"]), 0.97)
            cr.fill_preserve()
            cr.set_source_rgb(*rgb(t["border"]))
            cr.set_line_width(1.6)
            cr.stroke()
            setfont(cr, 13, True)
            cr.set_source_rgb(*rgb(t["kinds"].get(item.get("kind"), t["kinds"]["tip"])))
            cr.move_to(ox + pad, pad + 13)
            cr.show_text(title)
            if prompted:                                         # × closes
                setfont(cr, 15, True)
                cr.set_source_rgb(*rgb(t["muted"]))
                cr.move_to(ox + bw - pad - 10, pad + 13)
                cr.show_text("×")
                regions.append((ox + bw - pad - 16, 0, ox + bw, pad + title_h, "quit"))
            bx, by = ox + pad, pad + title_h + line_h * len(lines) + 6
            for (words, cmd), bwid in zip(btns, btn_ws):
                fill, fg = t[cmd]
                cr.new_path()
                rr = 6
                cr.arc(bx + rr, by + rr, rr, 3.1416, 1.5 * 3.1416)
                cr.arc(bx + bwid - rr, by + rr, rr, 1.5 * 3.1416, 0)
                cr.arc(bx + bwid - rr, by + btn_h - rr, rr, 0, 0.5 * 3.1416)
                cr.arc(bx + rr, by + btn_h - rr, rr, 0.5 * 3.1416, 3.1416)
                cr.close_path()
                cr.set_source_rgb(*rgb(fill))
                cr.fill()
                setfont(cr, 13, True)
                cr.set_source_rgb(*rgb(fg))
                cr.move_to(bx + 10, by + 17)
                cr.show_text(words)
                regions.append((int(bx), int(by), int(bx + bwid), int(by + btn_h), cmd))
                bx += bwid + gap
        else:
            setfont(cr, 14)
            cr.set_source_rgb(*rgb(t["text"]))
            for i, line in enumerate(lines):
                y = pad + title_h + line_h * i
                cr.move_to(ox + pad, y + 15)
                cr.show_text(line)
                ends, acc = [], ""
                for word in line.split(" "):
                    acc = f"{acc} {word}" if acc else word
                    ends.append(int(width(acc)) + 1)
                out_lines.append((ox + pad, y, int(width(line)) + 2, line_h, ends))
        s.flush()
        import io
        buf = io.BytesIO()
        s.write_to_png(buf)
        surfaces[layer] = buf.getvalue()
    return {"w": w, "h": h, "bg": surfaces["bg"], "text": surfaces["text"], "lines": out_lines,
            "regions": regions}


def have_cairo() -> bool:
    try:
        import cairo  # noqa: F401
        return True
    except ImportError:
        return False


def cell_bubble(item, n: int, theme: str, cols: int, prompted: bool) -> tuple:
    """Without pycairo: the bubble in cells (rounded box drawing) with its own background colour (the
    panel's default background is see-through). (lines, regions as (col0, row, col1, cmd))."""
    t = THEMES.get(theme, THEMES["light"])
    bg = "\x1b[48;2;%d;%d;%dm" % tuple(int(c * 255) for c in rgb(t["fill"]))
    fg = "\x1b[38;2;%d;%d;%dm" % tuple(int(c * 255) for c in rgb(t["text"]))
    bd = "\x1b[38;2;%d;%d;%dm" % tuple(int(c * 255) for c in rgb(t["border"]))
    kc = "\x1b[38;2;%d;%d;%dm" % tuple(int(c * 255) for c in rgb(t["kinds"].get(item.get("kind"), t["kinds"]["tip"])))
    inner = max(10, cols - 4)
    text = wrap_px(item["text"].split(), inner, len)[:5]
    title = item.get("title", "")[:inner - 4]
    out = [f"{bg}{bd}╭─ {kc}\x1b[1m{title}\x1b[22m{bd} " + "─" * max(0, inner - len(title) - 3)
           + ("×" if prompted else "─") + "─╮\x1b[0m"]
    for line in text:
        out.append(f"{bg}{bd}│ {fg}{line}{' ' * (inner - len(line))} {bd}│\x1b[0m")
    regions = [(cols - 3, 0, cols - 2, "quit")] if prompted else []
    if prompted:
        row, plain = "", ""
        for words, cmd in buttons_for(item, n):
            fill, f2 = t[cmd]
            c0 = 2 + len(plain)
            row += "\x1b[48;2;%d;%d;%dm\x1b[38;2;%d;%d;%dm" % (tuple(int(c * 255) for c in rgb(fill)) + tuple(int(c * 255) for c in rgb(f2)))
            row += f" {words} {bg} "
            regions.append((c0, len(out), c0 + len(words) + 2, cmd))
            plain += f" {words}  "
        out.append(f"{bg}{bd}│ {row}{' ' * max(0, inner - len(plain))} {bd}│\x1b[0m")
    out.append(f"{bg}{bd}╰" + "─" * (inner + 2) + "╯\x1b[0m")
    return out, regions


# ---- kitty: pictures and remote control ------------------------------------------------------------
CHUNK = 4096


def gfx(control: str, data: bytes = b"") -> str:
    control = f"{control},q=2"
    if not data:
        return f"\x1b_G{control}\x1b\\"
    b64 = base64.standard_b64encode(data).decode("ascii")
    parts = [b64[i:i + CHUNK] for i in range(0, len(b64), CHUNK)] or [""]
    return "".join(f"\x1b_G{control + ',' if i == 0 else ''}m={1 if i < len(parts) - 1 else 0};{p}\x1b\\"
                   for i, p in enumerate(parts))


def scaled_png(path: str, px: int) -> bytes:
    """A frame at px×px (cairo, smooth), or the file as it is without cairo."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        import io
        import cairo
        src = cairo.ImageSurface.create_from_png(io.BytesIO(raw))
        out = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
        cr = cairo.Context(out)
        cr.scale(px / src.get_width(), px / src.get_height())
        cr.set_source_surface(src, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_BEST)
        cr.paint()
        buf = io.BytesIO()
        out.write_to_png(buf)
        return buf.getvalue()
    except Exception:
        return raw


def rc_send(addr: str, cmd: str, payload: dict, timeout: float = 2.0) -> dict:
    """One remote-control command to a kitty that listens on a unix socket (unix:/path or unix:@name),
    without kitten: the panel moves many times a second. Returns kitty's answer ({} if none)."""
    if not addr.startswith("unix:"):
        raise OSError(f"not a unix socket: {addr!r}")
    path = addr[5:]
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect("\0" + path[1:] if path.startswith("@") else path)
        msg = {"cmd": cmd, "version": [0, 51, 1], "payload": payload}
        s.sendall(b"\x1bP@kitty-cmd" + json.dumps(msg).encode() + b"\x1b\\")
        out = b""
        while not out.endswith(b"\x1b\\"):
            d = s.recv(65536)
            if not d:
                break
            out += d
    finally:
        s.close()
    m = re.search(rb"\x1bP@kitty-cmd(.*)\x1b\\", out, re.S)
    return json.loads(m.group(1)) if m else {}


def main_kitty(socket_addr: str, *args) -> str:
    """kitten @ to the main kitty, always with --to (never the kitty this runs in)."""
    if not socket_addr:
        raise OSError("no main kitty socket")
    return subprocess.run(["kitten", "@", "--to", socket_addr, *args], capture_output=True, text=True,
                          check=True, timeout=5).stdout


def winsize(fd: int = 1) -> tuple:
    """(rows, cols, width px, height px) of the panel's terminal."""
    r, c, w, h = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
    return r, c, w, h


# ---- outputs ---------------------------------------------------------------------------------------
def outputs() -> list:
    """[{name, x, y, w, h, scale}] from cosmic-randr (COSMIC), or [] elsewhere."""
    try:
        raw = subprocess.run(["cosmic-randr", "list"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_randr(raw)


def parse_randr(raw: str) -> list:
    raw = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    found, cur = [], None
    for line in raw.splitlines():
        m = re.match(r"^(\S+) \((enabled|disabled)\)", line)
        if m:
            cur = {"name": m.group(1), "on": m.group(2) == "enabled", "x": 0, "y": 0, "scale": 1.0}
            found.append(cur)
        elif cur is not None:
            p = re.match(r"\s+Position:\s*(-?\d+),(-?\d+)", line)
            if p:
                cur["x"], cur["y"] = int(p.group(1)), int(p.group(2))
            c = re.match(r"\s+(\d+)x(\d+) @ .*\(current\)", line)
            if c:
                cur["w"], cur["h"] = int(c.group(1)), int(c.group(2))
            s = re.match(r"\s+Scale:\s*(\d+)%", line)
            if s:
                cur["scale"] = int(s.group(1)) / 100
    out = []
    for o in found:
        if o["on"] and "w" in o:
            sc = o["scale"] or 1.0
            out.append({"name": o["name"], "x": o["x"], "y": o["y"], "w": int(o["w"] / sc),
                        "h": int(o["h"] / sc), "scale": sc})
    return out


def output_size(probe_px, cell_wh, known) -> tuple:
    """The output's logical size from the probe (a panel that filled it: its grid, whole cells, so up
    to a cell short) matched to a known output (cosmic-randr), else the probe plus half a cell."""
    pw, ph = probe_px
    cw, chh = cell_wh
    for o in known:
        if 0 <= o["w"] - pw < cw + 2 and 0 <= o["h"] - ph < chh + 2:
            return o["w"], o["h"]
    return pw + cw // 2, ph + chh // 2


# ---- the cat, in the panel ---------------------------------------------------------------------------
FRAME_IDS = {}
MOUTH_IDS = {}
BODY_P, MOUTH_P, BG_P, TEXT_P0 = 1, 2, 3, 10
BUBBLE_IDS = (900, 901, 902, 903)       # two pairs (bg, text): a new bubble goes in while the old shows


class FloatCat:
    def __init__(self, args, out=None):
        self.args = args
        self.out = out or sys.stdout
        self.conf, self.state = conf_dir(), state_dir()
        self.demo = args.demo
        self.log_path = os.path.join(self.state, "cat-float.log")
        self.rng = random.Random(args.seed) if args.seed is not None else random.Random()
        self.panel_addr = os.environ.get("KITTY_LISTEN_ON", "")
        self.main_addr = args.main_socket or ""
        self.saved = load_json(os.path.join(self.state, "cat-float.json"))
        self.said = load_json(os.path.join(self.state, "cat-float-said.json"))
        self.cairo = have_cairo() and not args.cells
        self.theme = args.theme or "light"
        self.frame = "idle"
        self.mouth = None
        self.bubble = None        # {"item", "items", "sel", "art", "prompted", "until", "revealed", ...}
        self.bubble_pair = 0
        self.lay = None
        self.walking = None       # (target x, direction)
        self.drag = None
        self.press = None
        self.regions = []
        self.tabs_seen = {}
        self.last_talk = -1e9
        self.next_tip = None
        self.events = 0

    # -- the log: what happened, for the owner's one-click tests and the demo's screenshots --
    def log(self, *words) -> None:
        try:
            os.makedirs(self.state, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]} " + " ".join(str(w) for w in words) + "\n")
        except OSError:
            pass

    def w(self, s: str) -> None:
        self.out.write(s)

    def flush(self) -> None:
        try:
            self.out.flush()
        except OSError:
            pass

    # -- the panel --
    def rc(self, payload: dict) -> bool:
        try:
            ans = rc_send(self.panel_addr, "resize-os-window", payload)
            if not ans.get("ok", False):
                self.log("rc refused:", ans.get("error", ans))
                return False
            return True
        except (OSError, ValueError) as e:
            self.log("rc failed:", e)
            return False

    def set_panel(self, lay: dict, force: bool = False) -> None:
        """Move (and size) the panel to lay; only what changed is sent."""
        old = self.lay
        opts = []
        if force or not old or (old["cols"], old["rows"]) != (lay["cols"], lay["rows"]):
            opts += [f"columns={lay['cols']}", f"lines={lay['rows']}"]
        if force or not old or old["margin"] != lay["margin"]:
            opts += [f"margin-left={lay['margin'][0]}", f"margin-top={lay['margin'][1]}"]
        if force:
            opts += ["edge=none"]
        resized = bool(old) and (old["cols"], old["rows"]) != (lay["cols"], lay["rows"])
        self.lay = lay
        if opts:
            self.rc({"action": "os-panel", "incremental": True, "os_panel": opts})
            self.moved_at = time.monotonic()
        if resized or force or (old and old["cat"] != lay["cat"]):
            self.pending_place = True             # (after the resize lands: SIGWINCH)
        if not resized:
            self.place_all()

    # -- pictures --
    def transmit_frames(self) -> None:
        h = ch()
        frames = list(getattr(h, "FRAMES", ("idle",))) if h else ["idle"]
        mouths = list(getattr(h, "MOUTHS", ())) if h else []
        src = os.path.join(CAT_DIR, "192")
        n = 1
        for f in frames:
            p = os.path.join(src, f + ".png")
            if os.path.isfile(p):
                FRAME_IDS[f] = n
                self.w(gfx(f"a=t,f=100,i={n}", scaled_png(p, CAT_PX) if self.cairo else open(p, "rb").read()))
                n += 1
        n = 100
        for m in mouths:
            p = os.path.join(src, f"mouth-{m}.png")
            if os.path.isfile(p):
                MOUTH_IDS[m] = n
                self.w(gfx(f"a=t,f=100,i={n}", scaled_png(p, CAT_PX) if self.cairo else open(p, "rb").read()))
                n += 1
        self.flush()

    def at(self, px: int, py: int) -> str:
        col, row, xo, yo = cell_pos(px, py, self.cw, self.chh)
        return f"\x1b[{row + 1};{col + 1}H", xo, yo

    def size_spec(self) -> str:
        return "" if self.cairo else f",c={cells_for(CAT_PX, self.cw)},r={cells_for(CAT_PX, self.chh)}"

    def place_cat(self) -> None:
        if not self.lay:
            return
        cx, cy = self.lay["cat"]
        move, xo, yo = self.at(cx, cy)
        fid = FRAME_IDS.get(self.frame) or FRAME_IDS.get("idle")
        if fid is None:
            return
        s = ""
        if getattr(self, "placed_frame", None) not in (None, fid):
            s += gfx(f"a=d,d=i,i={self.placed_frame},p={BODY_P}")
        s += move + gfx(f"a=p,i={fid},p={BODY_P},X={xo},Y={yo},z=1,C=1{self.size_spec()}")
        self.placed_frame = fid
        h = ch()
        mouth = self.mouth or (getattr(h, "MOUTH", {}).get(self.frame) if h else None)
        mid = MOUTH_IDS.get(mouth) if mouth and self.frame in (getattr(h, "MOUTH", {}) if h else {}) else None
        if getattr(self, "placed_mouth", None) not in (None, mid):
            s += gfx(f"a=d,d=i,i={self.placed_mouth},p={MOUTH_P}")
        if mid:
            s += move + gfx(f"a=p,i={mid},p={MOUTH_P},X={xo},Y={yo},z=2,C=1{self.size_spec()}")
        self.placed_mouth = mid
        self.w(s)

    def set_frame(self, frame: str, mouth=None) -> None:
        if frame not in FRAME_IDS:
            frame = "idle"
        if (frame, mouth) != (self.frame, self.mouth):
            self.frame, self.mouth = frame, mouth
            self.place_cat()
            self.flush()

    def place_all(self) -> None:
        self.w("\x1b[2J")                         # (cells only: pictures stay)
        self.place_cat()
        self.place_bubble()
        self.flush()

    # -- the bubble --
    def measure(self, item, n, prompted, side) -> tuple:
        if self.cairo:
            m = render_bubble(item, n, self.theme, side or "left", None, prompted, measure_only=True)
            return m["w"], m["h"]
        lines, _ = cell_bubble(item, n, self.theme, 40, prompted)
        return 42 * self.cw, len(lines) * self.chh

    def open_bubble(self, items, sel: int = 0, prompted: bool = False, sound: str = "") -> None:
        if not items:
            return
        item = items[sel]
        side = None
        wh = self.measure(item, len(items), prompted, "left")
        lay = layout(self.cat_xy, wh, (self.cw, self.chh), self.out_wh, CAT_PX, side)
        wh = self.measure(item, len(items), prompted, lay["side"])
        lay = layout(self.cat_xy, wh, (self.cw, self.chh), self.out_wh, CAT_PX, lay["side"])
        art = None
        if self.cairo:
            art = render_bubble(item, len(items), self.theme, lay["side"], lay["mouth"], prompted)
            self.bubble_pair ^= 1
            bg_id, tx_id = BUBBLE_IDS[self.bubble_pair * 2], BUBBLE_IDS[self.bubble_pair * 2 + 1]
            self.w(gfx(f"a=t,f=100,i={bg_id}", art["bg"]) + gfx(f"a=t,f=100,i={tx_id}", art["text"]))
            art["ids"] = (bg_id, tx_id)
        old = self.bubble
        self.bubble = {"item": item, "items": items, "sel": sel, "art": art, "prompted": prompted,
                       "revealed": 0.0, "done": False, "until": None, "shown_lines": 0}
        if old and old.get("art"):
            self.drop_bubble_pictures(old)
        self.remember(item)
        self.log("say", item.get("kind"), repr(item.get("text", "")[:60]), "prompted" if prompted else "by itself")
        self.set_panel(lay)
        if sound:
            self.play(sound)

    def drop_bubble_pictures(self, b) -> None:
        if b and b.get("art") and b["art"].get("ids"):
            for i in b["art"]["ids"]:
                self.w(gfx(f"a=d,d=I,i={i}"))      # upper-case: its data goes too

    def close_bubble(self) -> None:
        if not self.bubble:
            return
        self.drop_bubble_pictures(self.bubble)
        self.bubble = None
        self.mouth = None
        self.set_panel(layout(self.cat_xy, None, (self.cw, self.chh), self.out_wh, CAT_PX))
        self.place_cat()
        self.flush()

    def place_bubble(self) -> None:
        b = self.bubble
        self.regions = []
        if not self.lay:
            return
        cx, cy = self.lay["cat"]
        if not b or not self.lay.get("bubble"):
            self.regions.append((cx, cy, cx + CAT_PX, cy + CAT_PX, "cat"))
            return
        bx, by = self.lay["bubble"]
        if b["art"]:
            art = b["art"]
            move, xo, yo = self.at(bx, by)
            self.w(move + gfx(f"a=p,i={art['ids'][0]},p={BG_P},X={xo},Y={yo},z=0,C=1"))
            for x0, y0, x1, y1, cmd in art["regions"]:
                self.regions.append((bx + x0, by + y0, bx + x1, by + y1, cmd))
            self.regions.append((cx, cy, cx + CAT_PX, cy + CAT_PX, "cat"))
            self.regions.append((bx, by, bx + art["w"], by + art["h"], "bubble"))
            self.place_words(full_redraw=True)
        else:
            cols = max(12, (self.lay["cols"] * self.cw - (CAT_PX if True else 0)) // self.cw - 1)
            lines, regs = cell_bubble(b["item"], len(b["items"]), self.theme, min(40, cols), b["prompted"])
            col0, row0 = bx // self.cw, by // self.chh
            shown = lines if b["done"] else lines[:1 + int(b["revealed"] // 60)]
            for i, line in enumerate(shown):
                self.w(f"\x1b[{row0 + i + 1};{col0 + 1}H{line}")
            for c0, r, c1, cmd in regs:
                self.regions.append(((col0 + c0) * self.cw, (row0 + r) * self.chh, (col0 + c1 + 1) * self.cw,
                                     (row0 + r + 1) * self.chh, cmd))
            self.regions.append((cx, cy, cx + CAT_PX, cy + CAT_PX, "cat"))
            self.regions.append((col0 * self.cw, row0 * self.chh, (col0 + 42) * self.cw,
                                 (row0 + len(lines)) * self.chh, "bubble"))

    def place_words(self, full_redraw: bool = False) -> None:
        """The words said so far: each line a crop of the words' picture, as wide as said."""
        b = self.bubble
        if not b or not b["art"] or not self.lay or not self.lay.get("bubble"):
            return
        art = b["art"]
        bx, by = self.lay["bubble"]
        left = b["revealed"]
        s = ""
        for i, (x, y, w, h, _ends) in enumerate(art["lines"]):
            show = int(min(w, max(0, left)))
            left -= w
            if show <= 0:
                if full_redraw or i < b.get("shown_lines", 0):
                    s += gfx(f"a=d,d=i,i={art['ids'][1]},p={TEXT_P0 + i}")
                continue
            move, xo, yo = self.at(bx + x, by + y)
            s += move + gfx(f"a=p,i={art['ids'][1]},p={TEXT_P0 + i},x={x},y={y},w={show},h={h},X={xo},Y={yo},z=3,C=1")
            b["shown_lines"] = max(b.get("shown_lines", 0), i + 1)
        self.w(s)

    def talking_mouth(self) -> str:
        """While the words come: open on a word, closed between words (lip sync with the reveal)."""
        b = self.bubble
        if not b or b["done"]:
            return None
        if not b["art"]:
            return ("open", "small", "o", "w")[int(time.monotonic() * 8) % 4]
        left = b["revealed"]
        for (_x, _y, w, _h, ends) in b["art"]["lines"]:
            if left > w:
                left -= w
                continue
            prev = 0
            for e in ends:
                if left <= e:
                    into = (left - prev) / max(1, e - prev)
                    if into > 0.85:
                        return "w"                             # the gap after a word
                    return ("open", "o", "small", "open")[int(into * 4) % 4]
                prev = e
            return "w"
        return "w"

    def reveal_tick(self, dt: float) -> None:
        b = self.bubble
        if not b or b["done"]:
            return
        total = sum(l[2] for l in b["art"]["lines"]) if b["art"] else 60 * 6
        b["revealed"] += REVEAL_SPEED * dt
        if b["revealed"] >= total:
            b["revealed"] = total
            b["done"] = True
            b["until"] = time.monotonic() + (ASK_HOLD if b["prompted"] else SAY_HOLD)
            self.mouth = None
        if b["art"]:
            self.place_words()
        else:
            self.place_bubble()
        if not b["done"]:
            m = self.talking_mouth()
            if m != self.mouth:
                self.mouth = m
                self.place_cat()
        else:
            self.place_cat()
        self.flush()

    # -- memory, sounds --
    def remember(self, item) -> None:
        self.said = remember(self.said, item, time.time())
        save_json(os.path.join(self.state, "cat-float-said.json"), self.said)

    def play(self, kind: str) -> None:
        argv = sound_argv(kind, self.conf, demo=self.demo)
        if argv is None:
            self.log("sound (quiet):", kind)
            return
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass

    # -- what it has to say --
    def tabs(self):
        if self.demo:
            return self.demo_tabs
        h = ch()
        finder = getattr(h, "_finder", None) if h else None
        if not self.main_addr or finder is None:
            return []
        try:
            return finder.rows(json.loads(main_kitty(self.main_addr, "ls")))
        except Exception as e:
            self.log("ls failed:", e)
            return []

    def suggestions(self, tabs) -> list:
        h = ch()
        if not h:
            return [{"kind": "hello", "key": "hello", "title": "Hello", "text": "Meow.", "action": None}]
        hidden = h.load_hidden(self.state) if hasattr(h, "load_hidden") else set()
        return h.suggestions(tabs, datetime.datetime.now(), self.state, self.conf, hidden)

    def talk_mode(self) -> str:
        try:
            with open(os.path.join(self.conf, "cat-talk"), encoding="utf-8") as f:
                return f.read().strip() or "on"
        except OSError:
            return "on"

    def look(self) -> None:
        """The tabs again: one that starts waiting, fails or finishes is news (said once)."""
        tabs = self.tabs()
        news = None
        for t in tabs:
            before = self.tabs_seen.get(t["id"])
            st = t.get("state")
            if before is not None and st != before and st in ("blocked", "error", "done"):
                news = news or st
        self.tabs_seen = {t["id"]: t.get("state") for t in tabs}
        if not news or self.talk_mode() == "off" or self.drag or (self.bubble and self.bubble["prompted"]):
            return
        items = [s for s in self.suggestions(tabs) if s["kind"] in ("waiting", "error", "done")]
        items = fresh(items, self.said, time.time())
        if items:
            self.last_talk = time.monotonic()
            self.walking = None
            self.set_frame("surprised" if items[0]["kind"] in ("waiting", "error") else "happy")
            self.open_bubble(items[:1], prompted=False, sound="meow" if items[0]["kind"] == "waiting" else "mrrp")

    def maybe_tip(self, now: float) -> None:
        if self.talk_mode() != "on" or self.bubble or self.drag:
            return
        if self.next_tip is None:
            self.next_tip = now + self.rng.uniform(*TIP_EVERY)
        if now < self.next_tip or now - self.last_talk < UNPROMPTED_GAP:
            return
        self.next_tip = now + self.rng.uniform(*TIP_EVERY)
        items = [s for s in self.suggestions(self.tabs()) if s["kind"] in ("tip", "joke", "word", "quest")]
        items = fresh(items, self.said, time.time())
        if items:
            self.last_talk = now
            self.set_frame("idle")
            self.open_bubble([self.rng.choice(items)], prompted=False, sound="mrrp")

    # -- clicks and drags --
    def on_mouse(self, ev) -> None:
        kind, button, x, y = ev
        self.events += 1
        if kind in ("press", "release", "focus") or self.events <= 3:
            self.log("mouse", kind, button, x, y)
        if kind == "focus":
            self.log("FOCUS", "in" if button else "out", "(the panel got the keyboard: it shouldn't)" if button else "")
            return
        if kind == "move":
            what = hit(self.regions, x, y)
            shape = "grab" if what in ("cat", "bubble") else "pointer" if what in ("do", "next", "quit") else "default"
            if shape != getattr(self, "shape", None):
                self.shape = shape
                self.w(f"\x1b]22;{shape}\x1b\\")
                self.flush()
            return
        if kind == "press" and button == 0:
            self.press = {"at": (x, y), "what": hit(self.regions, x, y), "margin": self.lay["margin"],
                          "cat": tuple(self.cat_xy)}
            return
        if kind == "drag" and self.press:
            if not self.drag and max(abs(x - self.press["at"][0]), abs(y - self.press["at"][1])) <= DRAG_SLOP:
                return
            if not self.drag:
                if self.press["what"] not in ("cat", "bubble"):
                    return
                self.drag = {"grab": self.press["at"]}
                self.walking = None
                self.set_frame("surprised")
                self.w("\x1b]22;grabbing\x1b\\")
                self.log("drag start")
            if time.monotonic() - getattr(self, "moved_at", 0) < SETTLE:
                self.drag["pending"] = (x, y)
                return
            self.drag_move(x, y)
            return
        if kind == "release" and button in (0, 3):
            p, self.press = self.press, None
            if self.drag:
                if self.drag.get("pending"):
                    self.drag_move(*self.drag["pending"])
                self.drag = None
                self.drop()
                return
            if p:
                self.click(p["what"])

    def drag_move(self, x, y) -> None:
        mx, my = drag_to(self.lay["margin"], self.drag["grab"], (x, y))
        cx, cy = mx + self.lay["cat"][0], my + self.lay["cat"][1]
        cx, cy = clamp(cx, cy, CAT_PX, CAT_PX, *self.out_wh)
        self.drag["pending"] = None
        self.move_cat(cx, cy)

    def drop(self) -> None:
        self.set_frame("hop-low")
        self.anim = [("happy", 0.35), ("idle", 0)]
        x, y = self.cat_xy
        fl = on_floor(y, self.out_wh[1])
        if fl:
            y = floor_y(self.out_wh[1])
            self.move_cat(x, y)
        self.saved = {"x": x, "y": y, "floor": fl, "out": list(self.out_wh)}
        save_json(os.path.join(self.state, "cat-float.json"), self.saved)
        self.log("drop at", x, y, "floor" if fl else "perched")
        self.play("drop")

    def click(self, what) -> None:
        self.log("click", what)
        if what == "cat":
            if self.bubble and self.bubble["prompted"]:
                self.close_bubble()
                return
            items = self.suggestions(self.tabs())
            if self.demo and getattr(self.args, "click_test", False):
                items = [{"kind": "hello", "key": "click-test", "title": "Click test",
                          "text": "You clicked me! Now type a letter: did it go where you were typing?",
                          "action": None}] + items
            self.walking = None
            self.set_frame("wave")
            self.open_bubble(items, 0, prompted=True, sound="mrrp")
        elif what == "quit":
            self.close_bubble()
        elif what == "next" and self.bubble:
            b = self.bubble
            self.open_bubble(b["items"], (b["sel"] + 1) % len(b["items"]), prompted=True)
        elif what == "do" and self.bubble:
            act = self.bubble["item"].get("action")
            if act and act[0] == "focus" and self.main_addr and not self.demo:
                try:
                    main_kitty(self.main_addr, "focus-tab", "--match", f"id:{act[1]}")
                except Exception as e:
                    self.log("focus-tab failed:", e)
            elif act and act[0] == "help" and self.main_addr and not self.demo:
                try:
                    main_kitty(self.main_addr, "action", "kitten", "show_key")   # (F1's sheet: see report)
                except Exception:
                    pass
            self.close_bubble()

    # -- moving --
    def move_cat(self, x, y) -> None:
        self.cat_xy = [int(x), int(y)]
        if self.bubble:
            wh = (self.bubble["art"]["w"], self.bubble["art"]["h"]) if self.bubble["art"] else \
                self.measure(self.bubble["item"], len(self.bubble["items"]), self.bubble["prompted"], "left")
            lay = layout(self.cat_xy, wh, (self.cw, self.chh), self.out_wh, CAT_PX, self.lay.get("side"))
            if lay["mouth"] != self.lay.get("mouth") and self.bubble["art"]:
                # the bubble slid against an edge: its tail must point at the cat again
                self.open_bubble(self.bubble["items"], self.bubble["sel"], self.bubble["prompted"])
                return
            self.set_panel(lay)
        else:
            self.set_panel(layout(self.cat_xy, None, (self.cw, self.chh), self.out_wh, CAT_PX))

    def walk_tick(self, dt: float) -> None:
        if not self.walking:
            return
        target, way = self.walking
        x, y = self.cat_xy
        step = WALK_SPEED * dt
        nx = min(target, x + step) if way > 0 else max(target, x - step)
        if self.bubble and self.lay.get("side"):        # walking with the bubble: it stays on the screen
            bw = self.bubble["art"]["w"] if self.bubble["art"] else 42 * self.cw
            tuck = int(CAT_PX * 0.12)
            lo = bw - tuck if self.lay["side"] == "left" else 0
            hi = self.out_wh[0] - CAT_PX - (bw - tuck if self.lay["side"] == "right" else 0)
            nx = min(max(lo, nx), hi)
            if nx in (lo, hi):
                target = nx
        self.walk_phase = getattr(self, "walk_phase", 0.0) + dt
        f = 1 + int(self.walk_phase * 8) % 4
        self.set_frame(f"walk-{'right' if way > 0 else 'left'}-{f}")
        self.move_cat(nx, y)
        if int(nx) == int(target):
            self.walking = None
            self.set_frame("idle")
            self.log("walked to", int(nx), y)

    def start_walk(self, target: int) -> None:
        x = self.cat_xy[0]
        if int(target) == int(x):
            return
        self.walking = (int(target), 1 if target > x else -1)
        self.log("walk from", x, "to", target)

    # -- running --
    def setup(self) -> None:
        r, c, wpx, hpx = winsize()
        self.cw, self.chh = max(1, wpx // max(1, c)), max(1, hpx // max(1, r))
        if self.args.probe:
            self.out_wh = output_size((wpx, hpx), (self.cw, self.chh), outputs())
        else:
            self.out_wh = (self.args.out_w, self.args.out_h)
        self.log("start: cell", self.cw, self.chh, "output", self.out_wh, "cairo" if self.cairo else "cells",
                 "demo" if self.demo else "", "panel", self.panel_addr)
        self.w("\x1b[?25l\x1b[?7l")                             # no cursor, no wrapping
        self.w("\x1b[?1003h\x1b[?1006h\x1b[?1016h\x1b[?1004h")   # any motion, SGR pixels, focus reports
        self.transmit_frames()
        if self.args.at:
            x, y = self.args.at
            self.cat_xy = list(clamp(x, y, CAT_PX, CAT_PX, *self.out_wh))
        else:
            self.cat_xy = list(restore(self.saved, *self.out_wh))
        self.set_panel(layout(self.cat_xy, None, (self.cw, self.chh), self.out_wh, CAT_PX), force=True)
        self.pending_place = True

    def teardown(self) -> None:
        self.w("\x1b[?1003l\x1b[?1006l\x1b[?1016l\x1b[?1004l\x1b[?25h")
        self.w(gfx("a=d,d=A"))
        self.flush()

    def alive(self) -> bool:
        for pid in (self.args.supervisor, self.args.main_pid):
            if pid:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return False
                except PermissionError:
                    pass
        return not os.path.exists(os.path.join(self.conf, "cat-off")) or self.demo

    def run(self) -> int:
        fd = sys.stdin.fileno()
        old = None
        try:
            old = termios.tcgetattr(fd)
            tty.setraw(fd)
        except termios.error:
            pass
        winch = {"got": False}
        signal.signal(signal.SIGWINCH, lambda *_: winch.update(got=True))
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(0)))
        self.setup()
        self.demo_tabs = []
        script = demo_script(self) if self.demo else None
        start = last = time.monotonic()
        next_look, next_alive = start + 1.0, start + 1.0
        next_wander = start + self.rng.uniform(*WANDER_EVERY)
        self.anim = []
        anim_at = start
        blink_at = start + self.rng.uniform(2, 6)
        buf = ""
        try:
            while True:
                now = time.monotonic()
                dt, last = min(0.1, now - last), now
                if self.demo and now - start >= self.demo:
                    self.log("demo over")
                    return 0
                if winch["got"]:
                    winch["got"] = False
                    r, c, wpx, hpx = winsize()
                    self.log("resized", (r, c, wpx, hpx))
                    self.pending_place = True
                if self.pending_place and self.lay:
                    r, c, wpx, hpx = winsize()
                    if c >= self.lay["cols"] - 1 and r >= self.lay["rows"] - 1 or now - getattr(self, "moved_at", 0) > 0.3:
                        self.pending_place = False
                        self.place_all()
                if now >= next_alive:
                    next_alive = now + 1.0
                    if not self.alive():
                        self.log("leaving (main kitty gone, launcher gone, or cat-off)")
                        return 0
                if script:
                    script(now - start)
                elif now >= next_look:
                    next_look = now + POLL
                    self.look()
                    self.maybe_tip(now)
                if self.drag and self.drag.get("pending") and now - getattr(self, "moved_at", 0) >= SETTLE:
                    self.drag_move(*self.drag["pending"])
                if self.bubble:
                    self.reveal_tick(dt)
                    b = self.bubble
                    if b and b["done"] and b["until"] and now >= b["until"] and not self.drag:
                        self.close_bubble()
                if self.walking:
                    self.walk_tick(dt)
                elif not script and not self.drag and not self.bubble and now >= next_wander:
                    next_wander = now + self.rng.uniform(*WANDER_EVERY)
                    if on_floor(self.cat_xy[1], self.out_wh[1]):
                        self.start_walk(walk_target(self.cat_xy[0], self.out_wh[0], CAT_PX, self.rng))
                if self.anim and now >= anim_at:
                    f, hold = self.anim.pop(0)
                    self.set_frame(f)
                    anim_at = now + hold
                if not self.walking and not self.drag and not self.anim and now >= blink_at \
                        and self.frame in ("idle", "look-left", "look-right"):
                    self.anim = [("blink", 0.15), (self.frame, 0)]
                    blink_at = now + self.rng.uniform(2.5, 7)
                busy = self.walking or self.drag or (self.bubble and not self.bubble["done"]) or self.anim or script
                r, _, _ = select.select([fd], [], [], 1 / FPS if busy else 0.25)
                if r:
                    try:
                        data = os.read(fd, 65536).decode("utf-8", "replace")
                    except OSError:
                        return 0
                    if not data:
                        return 0
                    buf += data
                    for ev in mouse_events(buf):
                        self.on_mouse(ev)
                    buf = buf[buf.rfind("\x1b"):] if re.search(r"\x1b(\[[<0-9;]*)?\Z", buf) else ""
        finally:
            self.teardown()
            if old is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                except termios.error:
                    pass


DEMO_TABS = [{"n": 3, "id": 103, "name": "Write notes", "folder": "code/webapp", "state": "working",
              "agent": "claude", "branch": "", "active": False},
             {"n": 5, "id": 105, "name": "Fix the build", "folder": "code/webapp", "state": "working",
              "agent": "claude", "branch": "", "active": False}]


def demo_script(cat: FloatCat):
    """The demo's visit, by the clock (seconds since it started): sit, say something, walk with the
    bubble, a tab starts waiting, the bubble you'd get from a click. Each step logged with where the
    cat is, to compare with screenshots."""
    steps = [
        (1.0, "blink", lambda: cat.set_frame("blink")),
        (1.2, "idle", lambda: cat.set_frame("idle")),
        (2.0, "say", lambda: cat.open_bubble([{"kind": "hello", "key": "demo-hello", "title": "Hello",
                                               "text": "Hi, I'm Nine! I can sit out here on the desktop now, next to kitty or anywhere you put me.",
                                               "action": None}], prompted=False, sound="mrrp")),
        (9.0, "walk", lambda: cat.start_walk(cat.cat_xy[0] - 240)),
        (16.0, "close", cat.close_bubble),
        (16.5, "walk back", lambda: cat.start_walk(cat.cat_xy[0] + 160)),
        (21.0, "tab waits", lambda: cat.demo_tabs.__setitem__(0, dict(cat.demo_tabs[0], state="blocked"))),
        (21.1, "news", cat.look),
        (30.0, "close", cat.close_bubble),
        (30.5, "asked", lambda: cat.click("cat")),
    ]
    if cat.args.click_test:
        steps = steps[:3] + [(10.0, "close", cat.close_bubble)]
    cat.demo_tabs = [dict(t) for t in DEMO_TABS]
    cat.tabs_seen = {t["id"]: t["state"] for t in cat.demo_tabs}
    done = set()

    def tick(t):
        for i, (at, name, fn) in enumerate(steps):
            if i not in done and t >= at:
                done.add(i)
                fn()
                cat.log(f"demo t={t:.2f} {name} cat at", tuple(cat.cat_xy), "panel", cat.lay["margin"] if cat.lay else None,
                        f"{cat.lay['cols']}x{cat.lay['rows']} cells" if cat.lay else "")
    return tick


# ---- the launcher -------------------------------------------------------------------------------------
def refuse_reason(env, force: bool = False) -> str:
    """Why the floating cat must not start here ("" when it may): not on Wayland (a panel needs the
    layer shell), the dev or test kitty (NINELIVES_QUIET, NL_TEST_DIR), or switched off."""
    if force:
        return ""
    if not env.get("WAYLAND_DISPLAY"):
        return "no Wayland display (the floating cat needs a layer-shell desktop)"
    if env.get("NINELIVES_QUIET"):
        return "NINELIVES_QUIET is set (a dev or test kitty)"
    if env.get("NL_TEST_DIR"):
        return "NL_TEST_DIR is set (check.sh or the test kitty)"
    return ""


def kitten_path() -> str:
    for p in (os.environ.get("NL_KITTEN"), os.path.expanduser("~/.local/kitty.app/bin/kitten"), "/usr/bin/kitten"):
        if p and os.access(p, os.X_OK):
            return p
    return "kitten"


def panel_argv(sock: str, inner: list, output: str = "", at=None, cells=(15, 8)) -> list:
    """The `kitten panel` command for the floating cat: never takes the keyboard, see-through, its
    own config (none of kitty.conf: NineLives' sidebar must not load in it), remote control only on
    its own socket. With no output: a probe panel that fills the output the desktop chooses (the one
    in use), which the cat measures and then shrinks to itself."""
    argv = [kitten_path(), "panel", "--config", "NONE", "--focus-policy=not-allowed", "--layer=overlay",
            "--app-id", "ninelives-cat", "--listen-on", f"unix:{sock}",
            "-o", "background_opacity=0", "-o", "allow_remote_control=socket-only",
            "-o", "cursor_blink_interval=0", "-o", "mouse_hide_wait=0", "-o", "enable_audio_bell=no",
            "-o", "window_alert_on_bell=no", "-o", "visual_bell_duration=0", "-o", "scrollback_lines=0",
            "-o", "resize_debounce_time=0 0", "-o", "confirm_os_window_close=0", "-o", "clipboard_control=no-append"]
    if output:
        argv.append(f"--output-name={output}")
    if at:
        argv += ["--edge=none", f"--margin-left={at[0]}", f"--margin-top={at[1]}",
                 f"--columns={cells[0]}", f"--lines={cells[1]}"]
    else:
        argv += ["--edge=center"]
    return argv + inner


def lock(path: str):
    """A single-instance lock (flock), or None when another holds it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def is_running(state: str = "") -> bool:
    """True while a launcher runs (its lock is held). For tab_bar.py: the sidebar cat can step aside."""
    f = lock(os.path.join(state or state_dir(), "cat-float.lock"))
    if f is None:
        return True
    f.close()
    return False


def clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KITTY_") or k == "KITTY_CONFIG_DIRECTORY"}
    env.pop("KITTY_LISTEN_ON", None)
    return env


def supervise(args) -> int:
    """The launcher's loop: while the switches say so and the main kitty lives, a panel runs."""
    conf, state = conf_dir(), state_dir()
    held = lock(os.path.join(state, "cat-float.lock"))
    if held is None:
        return 0                                     # one is running already
    sock = os.path.join(runtime_dir(), f"ninelives-catfloat-{os.getpid()}.sock")
    proc, restarts = None, []
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))

    def end_panel():
        nonlocal proc
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(3)
            except (OSError, subprocess.SubprocessError):
                pass
        proc = None
    try:
        while not stop["now"]:
            if args.main_pid:
                try:
                    os.kill(args.main_pid, 0)
                except ProcessLookupError:
                    break
                except PermissionError:
                    pass
            if not os.path.exists(os.path.join(conf, "cat-float")) and not args.force:
                break
            show = not os.path.exists(os.path.join(conf, "cat-off"))
            if show and (proc is None or proc.poll() is not None):
                now = time.monotonic()
                restarts = [t for t in restarts if now - t < 300]
                if len(restarts) >= 3:
                    time.sleep(5)
                    continue
                restarts.append(now)
                inner = [sys.executable or "python3", os.path.abspath(__file__), "run", "--supervisor", str(os.getpid())]
                if args.main_pid:
                    inner += ["--main-pid", str(args.main_pid)]
                if args.main_socket:
                    inner += ["--main-socket", args.main_socket]
                if args.output:
                    known = {o["name"]: o for o in outputs()}
                    o = known.get(args.output)
                    if o:
                        inner += ["--out", f"{o['w']}x{o['h']}"]
                        saved = load_json(os.path.join(state, "cat-float.json"))
                        x, y = restore(saved, o["w"], o["h"])
                        argv = panel_argv(sock, inner + ["--at", f"{x},{y}"], args.output, (x, y))
                    else:
                        argv = panel_argv(sock, inner + ["--probe"], args.output)
                else:
                    argv = panel_argv(sock, inner + ["--probe"])
                try:
                    os.unlink(sock)
                except OSError:
                    pass
                proc = subprocess.Popen(argv, env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, start_new_session=True)
            elif not show and proc is not None:
                end_panel()
            time.sleep(1.0)
    finally:
        end_panel()
        try:
            os.unlink(sock)
        except OSError:
            pass
        held.close()
    return 0


def start(args) -> int:
    why = refuse_reason(os.environ, args.force)
    if why:
        print(f"cat-float: not starting: {why}", file=sys.stderr)
        return 1
    if not args.force and not os.path.exists(os.path.join(conf_dir(), "cat-float")):
        print("cat-float: off (cat-float.py on turns it on)", file=sys.stderr)
        return 1
    if is_running():
        return 0
    if not args.foreground:                        # detach: the launcher outlives the shell that asked
        argv = [sys.executable or "python3", os.path.abspath(__file__), "start", "--foreground"] + \
            (["--force"] if args.force else []) + \
            (["--main-pid", str(args.main_pid)] if args.main_pid else []) + \
            (["--main-socket", args.main_socket] if args.main_socket else []) + \
            (["--output", args.output] if args.output else [])
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, env=clean_env() | {"KITTY_CONFIG_DIRECTORY": conf_dir()})
        return 0
    return supervise(args)


def parse(argv) -> "object":
    import argparse
    p = argparse.ArgumentParser(prog="cat-float.py", description="Nine, the cat, out on the desktop.")
    p.add_argument("cmd", nargs="?", default="status", choices=("on", "off", "status", "start", "run"))
    p.add_argument("--demo", type=float, default=0.0, help="run: a scripted visit for this many seconds")
    p.add_argument("--click-test", action="store_true", help="run --demo: the one-click test (see the report)")
    p.add_argument("--probe", action="store_true", help="run: the panel starts filling its output; measure it")
    p.add_argument("--out", default="", help="run: the output's size, WxH (instead of --probe)")
    p.add_argument("--at", default="", help="run: where the cat sits first, X,Y on its output")
    p.add_argument("--supervisor", type=int, default=0)
    p.add_argument("--main-pid", type=int, default=0)
    p.add_argument("--main-socket", default="")
    p.add_argument("--output", default="", help="start: the output's name (default: the one in use)")
    p.add_argument("--theme", choices=("light", "dark"), default="")
    p.add_argument("--cells", action="store_true", help="run: the bubble in cells even with pycairo")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--force", action="store_true", help="start even here (the dev or test kitty, no switch)")
    p.add_argument("--foreground", action="store_true")
    a = p.parse_args(argv)
    a.out_w, a.out_h = (int(v) for v in a.out.split("x")) if a.out else (1920, 1080)
    a.at = tuple(int(v) for v in a.at.split(",")) if a.at else None
    return a


def main(argv=None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    conf, state = conf_dir(), state_dir()
    flag = os.path.join(conf, "cat-float")
    if args.cmd == "on":
        open(flag, "a").close()
        print("=^.^=  the cat can leave the sidebar now: it sits on your desktop (cat-float.py off: back inside)")
        if os.environ.get("KITTY_PID") and os.environ.get("KITTY_LISTEN_ON", "").startswith("unix:"):
            args.main_pid = int(os.environ["KITTY_PID"])
            args.main_socket = os.environ["KITTY_LISTEN_ON"]
            return start(args)
        return 0
    if args.cmd == "off":
        try:
            os.unlink(flag)
        except FileNotFoundError:
            pass
        print("the cat stays in the sidebar (the floating one leaves within a second)")
        return 0
    if args.cmd == "status":
        saved = load_json(os.path.join(state, "cat-float.json"))
        print(f"floating cat: {'on' if os.path.exists(flag) else 'off'}, "
              f"{'running' if is_running() else 'not running'}"
              + (", hidden (cat-off)" if os.path.exists(os.path.join(conf, "cat-off")) else "")
              + (f", sits at {saved.get('x')},{saved.get('y')}" if saved else ""))
        return 0
    if args.cmd == "start":
        return start(args)
    return FloatCat(args).run()


if __name__ == "__main__":
    sys.exit(main())
