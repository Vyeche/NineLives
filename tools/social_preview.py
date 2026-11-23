#!/usr/bin/env python3
"""social_preview.py — build the GitHub social preview image (1280x640, shown when the repo link is
shared) from a real sidebar still recorded on the hidden test kitty.

    python3 tools/social_preview.py [OUT.png]        default: docs/images/social-preview.png

Upload it under the repository's Settings → General → Social preview → Edit."""
import os
import sys

import cairo

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
STILL = os.path.join(REPO, "docs", "images", "steps", "4-needs-you.png")   # amber block, ⚠1, =O.O= !
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "docs", "images", "social-preview.png")

W, H = 1280, 640
BG = (0x17 / 255, 0x14 / 255, 0x1F / 255)          # COSMIC dark background
FG = (0xEB / 255, 0xE7 / 255, 0xF2 / 255)          # foreground
MUTED = (0xC8 / 255, 0xC3 / 255, 0xD2 / 255)       # palette colour 7
ACCENT = (0xE6 / 255, 0x7E / 255, 0x00 / 255)      # COSMIC orange (the active tab)
AMBER = (0xCF / 255, 0xAE / 255, 0x7C / 255)       # "needs you"


def text(cr, x, y, s, size, colour, bold=False, mono=False):
    cr.select_font_face("DejaVu Sans Mono" if mono else "DejaVu Sans", cairo.FONT_SLANT_NORMAL,
                        cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(size)
    cr.set_source_rgb(*colour)
    cr.move_to(x, y)
    cr.show_text(s)


def main():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    cr = cairo.Context(surface)
    cr.set_source_rgb(*BG)
    cr.paint()

    # the real sidebar, scaled with nearest-neighbour so the terminal text stays crisp, in a frame
    still = cairo.ImageSurface.create_from_png(STILL)
    sw, sh = still.get_width(), still.get_height()
    scale = 540 / sh
    x0, y0 = 60, (H - sh * scale) / 2
    cr.save()
    cr.translate(x0, y0)
    cr.scale(scale, scale)
    pattern = cairo.SurfacePattern(still)
    pattern.set_filter(cairo.FILTER_NEAREST)
    cr.set_source(pattern)
    cr.paint()
    cr.restore()
    cr.set_source_rgb(*ACCENT)
    cr.set_line_width(3)
    cr.rectangle(x0 - 1.5, y0 - 1.5, sw * scale + 3, sh * scale + 3)
    cr.stroke()

    # the words
    tx = x0 + sw * scale + 70
    text(cr, tx, 200, "NineLives", 92, ACCENT, bold=True)
    text(cr, tx, 262, "Every AI coding session.", 36, FG, bold=True)
    text(cr, tx, 308, "One kitty window.", 36, FG, bold=True)
    lines = ["Live tab status · quiet sounds · a cat",
             "Tab search · jump to the tab that needs you",
             "Restarts keep every tab and split",
             "Quests that teach kitty as you go"]
    for i, s in enumerate(lines):
        text(cr, tx, 372 + i * 38, s, 23, MUTED)
    text(cr, tx, 560, "=O.O= !", 30, AMBER, bold=True, mono=True)
    text(cr, tx + 165, 560, "github.com/Vyeche/NineLives", 24, FG, mono=True)

    surface.write_to_png(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
