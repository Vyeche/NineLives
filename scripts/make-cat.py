#!/usr/bin/env python3
"""make-cat.py — draw the helper cat's frames (config/cat/*.png) from scratch with cairo. The helper
(config/cat-helper.py, Ctrl+Alt+C) shows them with kitty's graphics protocol; they are built here,
like the sounds, so the helper needs no drawing library at run time. Needs pycairo (python3-cairo).

    python3 scripts/make-cat.py                  write config/cat/<size>/<frame>.png
    python3 scripts/make-cat.py --sheet FILE     also write a contact sheet of every frame (both themes)

The cat: a ginger cat sitting up, big eyes, darker stripes on its head, a cream belly, pink ears and
nose, a dark outline. Each frame is one pose: a few 0..1 channels (each eye's blink, the ear twitch,
the tail's swing, a hop, a raised paw, where it looks) and a mouth. The helper plays moves by
swapping frames (a blink is blink → idle; a hop is hop-low, hop, hop-low, then a wave).
"""
import collections
import math
import os
import struct
import sys
import zlib

FUR, FUR_DARK, BELLY = (0.95, 0.63, 0.31), (0.80, 0.45, 0.18), (1.0, 0.89, 0.76)
LINE, PINK, EYE = (0.24, 0.22, 0.27), (0.96, 0.55, 0.62), (0.20, 0.18, 0.22)
SLEEPY_Z = (0.60, 0.50, 0.76)            # lavender, like the sidebar cat asleep: reads on both themes
SIZES = (96, 192)                        # px; the helper picks the one nearest its box, kitty scales
OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "cat"))
UNITS = 114                              # the drawing's square: the cat is 100 tall, room for a hop

# frame -> pose (only what differs from pose())
FRAMES = {
    "idle": {},
    "blink": {"blink_l": 1.0, "blink_r": 1.0},
    "wink": {"blink_r": 1.0, "mouth": "smile"},
    "ear": {"ear": 1.0},
    "tail-left": {"tail": -1.0},
    "tail-right": {"tail": 1.0},
    "look-left": {"look": -1.0},
    "look-right": {"look": 1.0},
    "nod": {"hop": -0.25, "blink_l": 0.5, "blink_r": 0.5},
    "hop-low": {"hop": 0.45, "mouth": "smile"},
    "hop": {"hop": 1.0, "mouth": "smile", "blush": True, "eyes": "happy"},
    "wave": {"paw": 1.0, "mouth": "smile", "tail": 0.3},
    "surprised": {"mouth": "o", "ear": 1.0, "eyes": "wide"},
    "happy": {"mouth": "smile", "blush": True, "eyes": "happy", "tail": 0.4},
    "sleepy": {"sleep": True},
}


def pose(**kw):
    p = {"blink_l": 0.0, "blink_r": 0.0, "mouth": "w", "ear": 0.0, "tail": 0.0, "hop": 0.0,
         "paw": 0.0, "look": 0.0, "sleep": False, "blush": False, "eyes": "open"}
    p.update(kw)
    return p


def draw(cr, size, p):
    """The cat in a size × size square (UNITS units across)."""
    def ellipse(x, y, rx, ry):
        cr.save(); cr.translate(x, y); cr.scale(rx, ry); cr.arc(0, 0, 1, 0, 2 * math.pi); cr.restore()

    def fill_stroke(fill, lw=2.8):
        cr.set_source_rgb(*fill); cr.fill_preserve()
        cr.set_source_rgb(*LINE); cr.set_line_width(lw); cr.stroke()

    cr.save()
    cr.scale(size / UNITS, size / UNITS)
    cr.translate(7, 13 - p["hop"] * 12)
    cr.set_line_join(1); cr.set_line_cap(1)
    t = p["tail"]                                     # the tail, swinging
    cr.move_to(66, 84)
    cr.curve_to(86, 86, 92 + 4 * t, 70, 84 + 10 * t, 56 - 4 * abs(t))
    cr.set_source_rgb(*LINE); cr.set_line_width(11.5); cr.stroke_preserve()
    cr.set_source_rgb(*FUR); cr.set_line_width(6); cr.stroke()
    cr.move_to(28, 92)                                # body
    cr.curve_to(24, 70, 34, 56, 50, 56); cr.curve_to(66, 56, 76, 70, 72, 92); cr.close_path()
    fill_stroke(FUR)
    ellipse(50, 80, 11, 11); cr.set_source_rgb(*BELLY); cr.fill()
    ellipse(40, 92, 6, 4); fill_stroke(FUR)           # paws; the right one waves
    if p["paw"] > 0:
        a = p["paw"]
        cr.save(); cr.translate(70 + 4 * a, 80 - 26 * a); cr.rotate(-0.6 * a)
        ellipse(0, 0, 5.5, 6.5); fill_stroke(FUR); cr.restore()
    else:
        ellipse(60, 92, 6, 4); fill_stroke(FUR)
    for side, twitch in ((-1, p["ear"]), (1, 0.0)):  # ears; the left one twitches
        cr.save(); cr.translate(50 + side * 15, 22); cr.rotate(side * 0.25 - twitch * 0.35)
        cr.move_to(-9, 8); cr.line_to(0, -12); cr.line_to(9, 8); cr.close_path(); fill_stroke(FUR)
        cr.move_to(-4.5, 5); cr.line_to(0, -5); cr.line_to(4.5, 5); cr.close_path()
        cr.set_source_rgb(*PINK); cr.fill(); cr.restore()
    ellipse(50, 38, 26, 21); fill_stroke(FUR)        # head
    cr.set_source_rgb(*FUR_DARK); cr.set_line_width(2.4)   # stripes
    for x in (44, 50, 56):
        cr.move_to(x, 18.5); cr.line_to(x, 24.5); cr.stroke()
    for side in (-1, 1):                              # and on the cheeks
        cr.move_to(50 + side * 25, 35); cr.line_to(50 + side * 20, 36); cr.stroke()
    look = p["look"] * 3.2
    for x, blink in ((40, p["blink_l"]), (60, p["blink_r"])):
        if p["sleep"] or blink >= 0.85:               # shut: a soft arc
            cr.arc(x, 37, 4.5, 0.15 * math.pi, 0.85 * math.pi)
            cr.set_source_rgb(*LINE); cr.set_line_width(2.4); cr.stroke()
        elif p["eyes"] == "happy":                    # ∩: smiling eyes
            cr.arc(x, 39, 4.2, 1.15 * math.pi, 1.85 * math.pi)
            cr.set_source_rgb(*LINE); cr.set_line_width(2.6); cr.stroke()
        else:
            big = 1.2 if p["eyes"] == "wide" else 1.0
            ellipse(x + look, 37, 4.2 * big, 5.4 * big * (1 - blink)); cr.set_source_rgb(*EYE); cr.fill()
            ellipse(x + look + 1.4, 35, 1.5 * big, max(0.1, 1.5 * big * (1 - blink)))
            cr.set_source_rgb(1, 1, 1); cr.fill()
    if p["blush"]:
        for x in (34, 66):
            ellipse(x, 45, 4, 2.2); cr.set_source_rgba(*PINK, 0.6); cr.fill()
    cr.move_to(48, 43); cr.line_to(52, 43); cr.line_to(50, 45.5); cr.close_path()
    cr.set_source_rgb(*PINK); cr.fill()
    cr.set_source_rgb(*LINE); cr.set_line_width(1.9)
    if p["mouth"] == "w":                             # ω
        cr.arc(47.5, 46, 2.5, 0.05 * math.pi, 0.95 * math.pi); cr.stroke()
        cr.arc(52.5, 46, 2.5, 0.05 * math.pi, 0.95 * math.pi); cr.stroke()
    elif p["mouth"] == "o":
        ellipse(50, 49, 2.4, 3); cr.fill()
    else:                                             # a smile
        cr.arc(50, 45, 5, 0.15 * math.pi, 0.85 * math.pi); cr.stroke()
    cr.set_line_width(1.2)                            # whiskers
    up = -1.5 if p["eyes"] == "wide" else 0.0
    for side in (-1, 1):
        for dy in (-1.5, 2):
            cr.move_to(50 + side * 12, 45 + dy * 0.6); cr.line_to(50 + side * 27, 43 + dy * 2.2 + up); cr.stroke()
    if p["sleep"]:
        cr.select_font_face("DejaVu Sans", 0, 1)
        for x, y, s in ((78, 16, 11), (87, 7, 9), (94, 0, 7)):
            cr.set_font_size(s); cr.move_to(x, y); cr.set_source_rgb(*SLEEPY_Z); cr.show_text("z")
    cr.restore()


def render(cairo, name: str, size: int):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(s)
    cr.set_antialias(cairo.ANTIALIAS_GOOD)
    draw(cr, size, pose(**FRAMES[name]))
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
    pal = [p for p, _ in count.most_common(256)]
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


def sheet(cairo, path: str) -> None:
    """Every frame at its large size, on the dark theme's background and on the light one's."""
    size, pad, label = SIZES[-1], 12, 18
    cols = len(FRAMES)
    w, h = cols * (size + pad) + pad, 2 * (size + label + pad) + pad
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(out)
    for row, (bg, fg) in enumerate((((0x17, 0x14, 0x1f), (0xeb, 0xe7, 0xf2)), ((0xf7, 0xf6, 0xf9), (0x1c, 0x1a, 0x21)))):
        y = pad + row * (size + label + pad)
        cr.set_source_rgb(*(c / 255 for c in bg)); cr.rectangle(0, y - pad / 2, w, size + label + pad); cr.fill()
        for i, name in enumerate(FRAMES):
            x = pad + i * (size + pad)
            # the shipped file, read back: the sheet shows what the helper shows
            frame = cairo.ImageSurface.create_from_png(os.path.join(OUT_DIR, str(size), name + ".png"))
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
    out_dir = OUT_DIR
    for size in SIZES:
        d = os.path.join(out_dir, str(size))
        os.makedirs(d, exist_ok=True)
        for name in FRAMES:
            with open(os.path.join(d, name + ".png"), "wb") as f:
                f.write(png(render(cairo, name, size)))
    print(f"{len(FRAMES)} frames × {len(SIZES)} sizes in {os.path.normpath(out_dir)}")
    if args[:1] == ["--sheet"] and len(args) > 1:
        sheet(cairo, args[1])
        print(args[1])
    elif args:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
