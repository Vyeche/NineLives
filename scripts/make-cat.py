#!/usr/bin/env python3
"""make-cat.py — draw NineLives' cat, Nine (config/cat/*.png), from scratch with cairo. The sidebar
(tab_bar.py) and the helper (cat-helper.py, Ctrl+Alt+C) show the pictures with kitty's graphics
protocol; they are built here, like the sounds, so nothing needs a drawing library at run time.
Needs pycairo (python3-cairo).

    python3 scripts/make-cat.py                  write config/cat/<size>/<frame>.png
    python3 scripts/make-cat.py --sheet FILE     also write a contact sheet of every frame (both themes)

Nine: a silver tabby sitting up, with a wide fluffy-cheeked head, rounded ears with pale tufts, big
green eyes with slit pupils, an M on the forehead, a white muzzle, bib and socks, a teal collar with a
gold tag shaped like a 9, and a tail curled round its front paws. A dark outline keeps it readable on
the light and the dark theme.

The sitting poses are drawn without a mouth: the mouth is a picture of its own (mouth-w, mouth-smile,
mouth-small, mouth-open, mouth-o), placed over the body, so the cat can talk (lip sync) in any of its
sitting poses without a frame per pose and mouth. Frames whose head moves (hops, the nod, walking,
asleep) have their mouth drawn in. cat-helper.py's FRAMES and MOUTH (which mouth each pose wears) list
them for the programs that show them.
"""
import collections
import math
import os
import struct
import sys
import zlib

FUR, FUR_DARK, WHITE = (0.66, 0.69, 0.75), (0.38, 0.40, 0.47), (0.97, 0.97, 0.98)
EAR_IN = (0.86, 0.86, 0.90)
LINE, NOSE = (0.13, 0.13, 0.18), (0.90, 0.52, 0.60)
IRIS, PUPIL = (0.47, 0.80, 0.38), (0.10, 0.11, 0.12)
COLLAR, TAG, TAG_INK = (0.05, 0.58, 0.62), (0.98, 0.77, 0.22), (0.45, 0.30, 0.02)
MOUTH_IN, TONGUE = (0.42, 0.16, 0.22), (0.94, 0.48, 0.56)
BLUSH = (0.96, 0.55, 0.62)
SLEEPY_Z = (0.60, 0.50, 0.76)            # lavender, like the sidebar cat asleep: reads on both themes
SIZES = (96, 192, 384)                   # px; the smallest at least as big as the cat on screen is shown
OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "cat"))
UNITS = 114                              # the drawing's square: the cat is 100 tall, room for a hop

# sitting poses: frame -> pose (only what differs from pose()); "mouth" None = drawn without one
FRAMES = {
    "idle": {},
    "blink": {"blink_l": 1.0, "blink_r": 1.0},
    "wink": {"blink_r": 1.0},
    "ear": {"ear": 1.0},
    "tail-left": {"tail": -1.0},
    "tail-right": {"tail": 1.0},
    "look-left": {"look": -1.0},
    "look-right": {"look": 1.0},
    "nod": {"hop": -0.25, "blink_l": 0.5, "blink_r": 0.5, "mouth": "w"},
    "hop-low": {"hop": 0.45, "mouth": "smile"},
    "hop": {"hop": 1.0, "mouth": "smile", "blush": True, "eyes": "happy"},
    "wave": {"paw": 1.0, "tail": 0.3},
    "surprised": {"ear": 1.0, "eyes": "wide"},
    "happy": {"blush": True, "eyes": "happy", "tail": 0.4},
    "sleepy": {"sleep": True, "mouth": "w"},
    "point-left": {"point": 1.0, "look": -1.0},
}
WALK_STEPS = 4                           # walk-right-1 … 4, walk-left-1 … 4 (the graphics can't mirror)
MOUTHS = ("w", "smile", "small", "open", "o")


def pose(**kw):
    p = {"blink_l": 0.0, "blink_r": 0.0, "mouth": None, "ear": 0.0, "tail": 0.0, "hop": 0.0,
         "paw": 0.0, "point": 0.0, "look": 0.0, "sleep": False, "blush": False, "eyes": "open"}
    p.update(kw)
    return p


def _ellipse(cr, x, y, rx, ry):
    cr.save(); cr.translate(x, y); cr.scale(rx, ry); cr.arc(0, 0, 1, 0, 2 * math.pi); cr.restore()


def _fill_stroke(cr, fill, lw=2.6):
    cr.set_source_rgb(*fill); cr.fill_preserve()
    cr.set_source_rgb(*LINE); cr.set_line_width(lw); cr.stroke()


def mouth(cr, kind, x=50.0, y=50.5):
    """One of the mouths, under the nose at (x, y) in head units."""
    cr.set_line_cap(1); cr.set_line_join(1)
    cr.set_source_rgb(*LINE); cr.set_line_width(1.8)
    if kind == "w":                                   # a small closed ω
        cr.arc(x - 2.3, y, 2.3, 0.1 * math.pi, 0.9 * math.pi); cr.stroke()
        cr.arc(x + 2.3, y, 2.3, 0.1 * math.pi, 0.9 * math.pi); cr.stroke()
    elif kind == "smile":
        cr.move_to(x - 5, y - 0.5); cr.curve_to(x - 3, y + 3.5, x + 3, y + 3.5, x + 5, y - 0.5); cr.stroke()
    elif kind == "small":                             # a syllable: just open
        _ellipse(cr, x, y + 1.2, 2.4, 1.6); cr.set_source_rgb(*MOUTH_IN); cr.fill_preserve()
        cr.set_source_rgb(*LINE); cr.set_line_width(1.4); cr.stroke()
    elif kind == "open":                              # a vowel: open wide, a pink tongue
        cr.move_to(x - 4, y); cr.curve_to(x - 4, y + 6.5, x + 4, y + 6.5, x + 4, y); cr.close_path()
        cr.set_source_rgb(*MOUTH_IN); cr.fill_preserve(); cr.set_source_rgb(*LINE); cr.set_line_width(1.5); cr.stroke()
        _ellipse(cr, x, y + 3.6, 2.4, 1.3); cr.set_source_rgb(*TONGUE); cr.fill()
    elif kind == "o":                                 # surprised, or an "oo"
        _ellipse(cr, x, y + 2, 2.3, 2.9); cr.set_source_rgb(*MOUTH_IN); cr.fill_preserve()
        cr.set_source_rgb(*LINE); cr.set_line_width(1.5); cr.stroke()


def head(cr, p):
    """The head, centred on (50, 38): ears, the wide cheeky face, eyes, muzzle, nose (no mouth)."""
    for side, twitch in ((-1, p["ear"]), (1, 0.0)):  # rounded ears, the left one twitches
        cr.save(); cr.translate(50 + side * 17, 21); cr.rotate(side * 0.38 - twitch * 0.42)
        cr.move_to(-10, 9); cr.curve_to(-8, -2, -4, -13, 0, -14); cr.curve_to(4, -13, 8, -2, 10, 9)
        cr.close_path(); _fill_stroke(cr, FUR)
        cr.move_to(-5.5, 7); cr.curve_to(-4, 0, -2, -7, 0, -8); cr.curve_to(2, -7, 4, 0, 5.5, 7); cr.close_path()
        cr.set_source_rgb(*EAR_IN); cr.fill()
        cr.set_source_rgb(*FUR_DARK); cr.set_line_width(1.1)
        for dx in (-2, 0, 2):                         # tufts
            cr.move_to(dx, 7); cr.line_to(dx * 1.4, 1); cr.stroke()
        cr.restore()
    # the face: round on top, wide fluffy cheeks with a tuft each side, a soft chin
    cr.move_to(24, 38)
    cr.curve_to(24, 22, 36, 15, 50, 15); cr.curve_to(64, 15, 76, 22, 76, 38)
    cr.curve_to(80, 42, 83, 45, 84, 49); cr.curve_to(80, 49, 78, 50, 77, 52)
    cr.curve_to(73, 58, 62, 61, 50, 61); cr.curve_to(38, 61, 27, 58, 23, 52)
    cr.curve_to(22, 50, 20, 49, 16, 49); cr.curve_to(17, 45, 20, 42, 24, 38); cr.close_path()
    _fill_stroke(cr, FUR)
    cr.set_source_rgb(*FUR_DARK); cr.set_line_width(2.2); cr.set_line_cap(1); cr.set_line_join(1)
    cr.move_to(42, 25); cr.line_to(45, 19); cr.line_to(50, 24); cr.line_to(55, 19); cr.line_to(58, 25); cr.stroke()   # the M
    for side in (-1, 1):                              # cheek stripes
        for dy in (0, 4.5):
            cr.move_to(50 + side * 26, 41 + dy); cr.line_to(50 + side * 20, 42 + dy); cr.stroke()
    _ellipse(cr, 45.5, 50, 7.5, 5.5); cr.set_source_rgb(*WHITE); cr.fill()           # the muzzle
    _ellipse(cr, 54.5, 50, 7.5, 5.5); cr.fill()
    _ellipse(cr, 50, 56, 6, 3.5); cr.fill()
    look = p["look"] * 2.2
    for x, blink in ((39, p["blink_l"]), (61, p["blink_r"])):
        if p["sleep"] or blink >= 0.85:               # shut: a soft smiling curve
            cr.arc(x, 35.5, 5.2, 0.15 * math.pi, 0.85 * math.pi)
            cr.set_source_rgb(*LINE); cr.set_line_width(2.2); cr.stroke()
        elif p["eyes"] == "happy":                    # ^ ^
            cr.arc(x, 39.5, 5.0, 1.15 * math.pi, 1.85 * math.pi)
            cr.set_source_rgb(*LINE); cr.set_line_width(2.4); cr.stroke()
        else:
            wide = p["eyes"] == "wide"
            big = 1.15 if wide else 1.0
            _ellipse(cr, x, 36, 6.8 * big, 7.0 * big * (1 - blink)); cr.set_source_rgb(*IRIS); cr.fill_preserve()
            cr.set_source_rgb(*LINE); cr.set_line_width(1.5); cr.stroke()
            if blink < 0.6:
                r = 2.6 if wide else 4.4              # big round pupils (small ones when startled)
                _ellipse(cr, x + look, 36.6, r, r * (1 - blink)); cr.set_source_rgb(*PUPIL); cr.fill()
                _ellipse(cr, x + look + 2.0, 33.8, 1.9, 1.9); cr.set_source_rgb(1, 1, 1); cr.fill()   # two highlights
                _ellipse(cr, x + look - 1.6, 38.9, 0.9, 0.9); cr.fill()
    if p["blush"]:
        for x in (32, 68):
            _ellipse(cr, x, 47, 4, 2.2); cr.set_source_rgba(*BLUSH, 0.65); cr.fill()
    cr.move_to(47.2, 45.5); cr.line_to(52.8, 45.5); cr.line_to(50, 48.6); cr.close_path()   # the nose
    cr.set_source_rgb(*NOSE); cr.fill_preserve(); cr.set_source_rgb(*LINE); cr.set_line_width(0.9); cr.stroke()
    cr.move_to(50, 48.6); cr.line_to(50, 50.2); cr.set_line_width(1.2); cr.stroke()
    cr.set_line_width(1.0)                            # whiskers: three a side, long
    up = -1.5 if p["eyes"] == "wide" else 0.0
    for side in (-1, 1):
        for i, dy in enumerate((-2.5, 0.5, 3.5)):
            cr.move_to(50 + side * 9, 51 + dy * 0.5); cr.line_to(50 + side * 31, 47 + dy * 2.0 + up + i * 0.4)
            cr.stroke()


def collar(cr, cx=50.0, y=62.0, w=13.0):
    """The teal collar and its gold 9 tag."""
    cr.move_to(cx - w, y - 1); cr.curve_to(cx - w * 0.5, y + 3.5, cx + w * 0.5, y + 3.5, cx + w, y - 1)
    cr.set_source_rgb(*LINE); cr.set_line_width(5.6); cr.stroke_preserve()
    cr.set_source_rgb(*COLLAR); cr.set_line_width(3.2); cr.stroke()
    _ellipse(cr, cx, y + 6.5, 4.6, 4.6); _fill_stroke(cr, TAG, 1.4)
    cr.select_font_face("DejaVu Sans", 0, 1); cr.set_font_size(7.0)
    ext = cr.text_extents("9")
    cr.move_to(cx - ext.x_advance / 2 - 0.2, y + 9.1); cr.set_source_rgb(*TAG_INK); cr.show_text("9")


def sitting(cr, p):
    t = p["tail"]
    # the tail, curled round the front paws, its tip flicking
    cr.move_to(70, 88)
    cr.curve_to(90, 90, 90, 101, 66, 101)
    cr.curve_to(48, 101, 32, 100, 24 + 4 * t, 96 - 6 * abs(t) - 3 * (t > 0))
    cr.set_source_rgb(*LINE); cr.set_line_width(10.5); cr.stroke_preserve()
    cr.set_source_rgb(*FUR); cr.set_line_width(5.4); cr.stroke()
    cr.move_to(81, 95); cr.line_to(84, 99); cr.set_source_rgb(*FUR_DARK); cr.set_line_width(2.0); cr.stroke()   # rings
    cr.move_to(58, 98); cr.line_to(58, 103); cr.stroke()
    # the body: a soft pear, a white bib
    cr.move_to(29, 96)
    cr.curve_to(25, 78, 31, 62, 50, 60); cr.curve_to(69, 62, 75, 78, 71, 96); cr.close_path()
    _fill_stroke(cr, FUR)
    cr.move_to(50, 61); cr.curve_to(40, 66, 40, 84, 50, 92); cr.curve_to(60, 84, 60, 66, 50, 61)
    cr.set_source_rgb(*WHITE); cr.fill()
    cr.set_source_rgb(*FUR_DARK); cr.set_line_width(2.2)
    for y in (72, 80):                                # flank stripes
        cr.move_to(29, y); cr.line_to(35, y + 1); cr.stroke()
        cr.move_to(71, y); cr.line_to(65, y + 1); cr.stroke()
    _ellipse(cr, 42, 96, 6, 4); _fill_stroke(cr, WHITE)     # white socks; the right paw waves
    if p["paw"] > 0:
        a = p["paw"]
        cr.save(); cr.translate(71 + 5 * a, 82 - 28 * a); cr.rotate(-0.5 * a)
        _ellipse(cr, 0, 0, 5.5, 6.5); _fill_stroke(cr, WHITE); cr.restore()
    else:
        _ellipse(cr, 58, 96, 6, 4); _fill_stroke(cr, WHITE)
    if p["point"] > 0:                                # the left paw stretched out, pointing left
        cr.move_to(36, 70); cr.curve_to(28, 70, 20, 69, 10, 66)
        cr.set_source_rgb(*LINE); cr.set_line_width(9.5); cr.stroke_preserve()
        cr.set_source_rgb(*FUR); cr.set_line_width(5.0); cr.stroke()
        _ellipse(cr, 8, 65.5, 5.5, 4.5); _fill_stroke(cr, WHITE)
    collar(cr)
    head(cr, p)
    if p["mouth"]:
        mouth(cr, p["mouth"])


def walking(cr, step: int):
    """Walking to the right, chibi style: the same big round head as sitting, a small bean of a body
    on little paddle paws, bobbing along; the tail a soft curl, swaying. step: 0..WALK_STEPS-1."""
    ph = step * 2 * math.pi / WALK_STEPS
    swing = math.sin(ph)
    cr.translate(0, -1.8 * abs(math.sin(ph)))         # a gentle bob

    def paw(x, a, near):
        _ellipse(cr, x + 3.5 * a, 97 - 2.2 * max(0.0, a), 6.2, 4.0)
        _fill_stroke(cr, WHITE if near else EAR_IN, 2.0)
    paw(64, -swing, False); paw(34, swing, False)      # far paws, behind the body
    # the tail: up from the back, a curl at its tip, swaying
    cr.move_to(28, 80); cr.curve_to(14, 78, 10, 62, 16 + 2 * swing, 54)
    cr.curve_to(20 + 2 * swing, 48, 28 + 2 * swing, 52, 24 + 2 * swing, 58)
    cr.set_source_rgb(*LINE); cr.set_line_width(10.0); cr.stroke_preserve()
    cr.set_source_rgb(*FUR); cr.set_line_width(5.2); cr.stroke()
    cr.move_to(26, 92); cr.curve_to(22, 76, 34, 68, 52, 68)          # the body: a short round bean
    cr.curve_to(70, 68, 80, 76, 76, 90); cr.curve_to(74, 97, 30, 98, 26, 92); cr.close_path()
    _fill_stroke(cr, FUR)
    cr.move_to(42, 92); cr.curve_to(46, 84, 62, 84, 68, 92); cr.close_path()
    cr.set_source_rgb(*WHITE); cr.fill()
    cr.set_source_rgb(*FUR_DARK); cr.set_line_width(2.2)
    for x in (36, 44):                                # back stripes
        cr.move_to(x, 70); cr.line_to(x + 1, 76); cr.stroke()
    paw(60, swing, True); paw(38, -swing, True)        # near paws
    cr.save(); cr.translate(57, 33); cr.rotate(0.05 * swing); cr.scale(0.86, 0.86); cr.translate(-50, -38)
    collar(cr, 50, 63, 13)                            # the big head, as sitting, looking ahead, smiling
    head(cr, pose(look=0.8, blush=True))
    mouth(cr, "w")
    cr.restore()


def draw(cr, size, name):
    cr.save()
    cr.scale(size / UNITS, size / UNITS)
    cr.set_line_join(1); cr.set_line_cap(1)
    if name.startswith("walk-"):
        _, way, n = name.split("-")
        if way == "left":                             # the graphics protocol can't mirror: draw it
            cr.translate(UNITS, 0); cr.scale(-1, 1)
        cr.translate(7, 13)
        walking(cr, int(n) - 1)
    elif name.startswith("mouth-"):
        cr.translate(7, 13)
        mouth(cr, name[6:])
    else:
        p = pose(**FRAMES[name])
        cr.translate(7, 13 - p["hop"] * 12)
        sitting(cr, p)
        if p["sleep"]:
            cr.select_font_face("DejaVu Sans", 0, 1)
            for x, y, s in ((80, 16, 11), (89, 7, 9), (96, 0, 7)):
                cr.set_font_size(s); cr.move_to(x, y); cr.set_source_rgb(*SLEEPY_Z); cr.show_text("z")
    cr.restore()


def names() -> list:
    return list(FRAMES) + [f"walk-{w}-{i}" for w in ("right", "left") for i in range(1, WALK_STEPS + 1)] \
        + [f"mouth-{m}" for m in MOUTHS]


def render(cairo, name: str, size: int):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(s)
    cr.set_antialias(cairo.ANTIALIAS_GOOD)
    draw(cr, size, name)
    return s


def png(surface) -> bytes:
    """The frame as an 8-bit palette PNG (with alpha): about a third of cairo's RGBA file. The 255
    most used colours are kept exactly, the rest (a few antialiased edge pixels) take the nearest.
    (cairo's pixels are premultiplied B, G, R, A on a little-endian machine.)"""
    surface.flush()
    w, h, stride = surface.get_width(), surface.get_height(), surface.get_stride()
    d = bytes(surface.get_data())
    if sys.byteorder != "little":
        raise SystemExit("make-cat.py reads cairo's pixels as little-endian")
    rows = [[d[y * stride + 4 * x:y * stride + 4 * x + 4] for x in range(w)] for y in range(h)]
    count = collections.Counter(p for r in rows for p in r)
    # the drawing's own colours first (a small patch like the gold tag mustn't lose its slot to edge
    # pixels), then the most used
    keep = []
    for c in (FUR, FUR_DARK, WHITE, EAR_IN, LINE, NOSE, IRIS, PUPIL, COLLAR, TAG, TAG_INK, MOUTH_IN, TONGUE, SLEEPY_Z):
        want = (round(c[2] * 255), round(c[1] * 255), round(c[0] * 255), 255)
        near = [p for p in count if p[3] == 255 and max(abs(a - b) for a, b in zip(p, want)) <= 2]
        if near:
            keep.append(max(near, key=count.__getitem__))
    pal = keep + [p for p, _ in count.most_common(300) if p not in keep][:256 - len(keep)]
    index = {p: i for i, p in enumerate(pal)}
    for p in count:
        if p not in index:
            index[p] = min(range(len(pal)), key=lambda i: sum((a - b) ** 2 for a, b in zip(p, pal[i])))
    raw = b"".join(b"\0" + bytes(index[p] for p in r) for r in rows)

    def straight(c, a):
        return min(255, round(c * 255 / a)) if a else 0
    plte = b"".join(bytes((straight(r, a), straight(g, a), straight(b, a))) for b, g, r, a in pal)
    trns = bytes(p[3] for p in pal).rstrip(b"\xff") or b"\xff"

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", plte) + chunk(b"tRNS", trns) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# which mouth each sitting pose wears (the frames with a mouth drawn in have none here); as in cat-helper.py
MOUTH_OF = {"idle": "w", "blink": "w", "wink": "smile", "ear": "w", "tail-left": "w", "tail-right": "w",
            "look-left": "w", "look-right": "w", "wave": "smile", "surprised": "o", "happy": "smile",
            "point-left": "small"}


def sheet(cairo, path: str, size: int = 192) -> None:
    """Every frame (the sitting ones with their mouth on), on the dark theme's sidebar and on the
    light one's, a row of mouths at the end."""
    pad, label = 10, 18
    shown = [n for n in names() if not n.startswith("mouth-")] + [f"mouth-{m}" for m in MOUTHS]
    cols = 8
    rows_per = -(-len(shown) // cols)
    w = cols * (size + pad) + pad
    h = 2 * rows_per * (size + label + pad) + 2 * pad
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(out)
    for theme, (bg, fg) in enumerate((((0x11, 0x0e, 0x18), (0xeb, 0xe7, 0xf2)), ((0xd4, 0xd3, 0xda), (0x1c, 0x1a, 0x21)))):
        y0 = pad + theme * rows_per * (size + label + pad)
        cr.set_source_rgb(*(c / 255 for c in bg))
        cr.rectangle(0, y0 - pad / 2, w, rows_per * (size + label + pad)); cr.fill()
        for i, name in enumerate(shown):
            x, y = pad + (i % cols) * (size + pad), y0 + (i // cols) * (size + label + pad)
            frame = cairo.ImageSurface.create_from_png(os.path.join(OUT_DIR, str(size), name + ".png"))
            cr.set_source_surface(frame, x, y); cr.paint()
            if name in MOUTH_OF:
                m = cairo.ImageSurface.create_from_png(os.path.join(OUT_DIR, str(size), f"mouth-{MOUTH_OF[name]}.png"))
                cr.set_source_surface(m, x, y); cr.paint()
            elif name.startswith("mouth-"):
                body = cairo.ImageSurface.create_from_png(os.path.join(OUT_DIR, str(size), "blink.png"))
                cr.set_source_surface(body, x, y); cr.paint()
                cr.set_source_surface(frame, x, y); cr.paint()
            cr.set_source_rgb(*(c / 255 for c in fg)); cr.select_font_face("DejaVu Sans Mono", 0, 0)
            cr.set_font_size(13); cr.move_to(x + 4, y + size + 13); cr.show_text(name)
    out.write_to_png(path)


def main() -> int:
    try:
        import cairo
    except ImportError:
        print("make-cat.py needs pycairo (python3-cairo, or pip install pycairo)", file=sys.stderr)
        return 1
    args = sys.argv[1:]
    for size in SIZES:
        d = os.path.join(OUT_DIR, str(size))
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):                       # frames that are gone from the list
            if f.endswith(".png") and f[:-4] not in names():
                os.remove(os.path.join(d, f))
        for name in names():
            with open(os.path.join(d, name + ".png"), "wb") as f:
                f.write(png(render(cairo, name, size)))
    print(f"{len(names())} frames × {len(SIZES)} sizes in {os.path.normpath(OUT_DIR)}")
    if args[:1] == ["--sheet"] and len(args) > 1:
        sheet(cairo, args[1])
        print(args[1])
    elif args:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
