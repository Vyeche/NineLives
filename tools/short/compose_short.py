#!/usr/bin/env python3
"""compose_short.py — put the takes from capture.sh together into a vertical YouTube Short.

    python3 tools/short/compose_short.py WORK_DIR OUT.mp4 [--thumb THUMB.png] [--no-music] [--preview T ...]

Reads WORK_DIR/take*.meta.json and the takes' .mkv (see capture.sh) and writes a 1080x1920 H.264 +
AAC MP4 at 30 fps: captions on top, the test kitty's window in the middle (1:1, no scaling), and
below it a close-up of the sidebar, its pixels doubled, that follows what's happening (the search
box while it's open). The sounds are NineLives' own (config/sounds), mixed in at the times the test
kitty's stubs logged them, at the volume it asked for, over an original music bed (music.py, the
same synth as the sounds; --no-music leaves it out) that ducks under each sound. The mix is raised
with one static gain (and, only if the peaks need it, a light limiter) to about -14 LUFS with true
peak <= -1 dBTP.
--preview T writes WORK_DIR/preview-T.png (one composed frame at T seconds) and exits.
Needs ffmpeg, numpy and pycairo (python3-cairo)."""
import argparse
import json
import math
import os
import re
import subprocess
import sys

import cairo
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOUNDS = os.path.join(REPO, "config", "sounds")
FPS = 30
W, H = 1080, 1920
RATE = 48000
FONT = "DejaVu Sans"
MONO = "DejaVu Sans Mono"

# The cut: which part of each take to keep (seconds; "end" is the take's end event).
EDIT = [
    {"take": "take1", "start": 0.0, "end_before": 0.9},
    {"take": "take2", "start": 0.0, "end_before": 0.4},
]
END_CARD = 3.6           # seconds
MUSIC_UNDER = 6.0        # the music bed's loudness under the sounds' (dB)
DUCK = 8.0               # and how far it dips around each sound (dB)
GITHUB = "github.com/Vyeche/NineLives"

# Layout (px). YouTube draws its own buttons along the right edge and the title and channel over
# the bottom fifth, so nothing important goes right of x≈950 in the lower half or below y≈1536.
BRAND_Y = 168            # "NineLives" over the captions
CAPTION_TOP = 214
APP_Y = 416              # the window: 1080x480 at 1:1
ZOOM = 2
CLOSE_Y = 912    # the close-up: up to 400x300 doubled = 800x600, centred (ends at y 1512)

BG = (0x0d / 255, 0x0c / 255, 0x12 / 255)
ORANGE = (0xf0 / 255, 0x88 / 255, 0x1a / 255)
TEXT = (0.97, 0.96, 0.98)
SOFT = (0.72, 0.70, 0.78)
CHIP = (0x26 / 255, 0x23 / 255, 0x2f / 255)
EDGE = (0x3a / 255, 0x36 / 255, 0x46 / 255)


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def load_takes(work: str) -> list:
    """The cut as a list of segments: take meta, kept range, where it starts in the Short."""
    segs, at = [], 0.0
    for e in EDIT:
        path = os.path.join(work, e["take"] + ".meta.json")
        with open(path, encoding="utf-8") as f:
            meta = json.load(f)
        end = next(ev["t"] for ev in meta["events"] if ev["kind"] == "end")
        t0, t1 = e["start"], end - e["end_before"]
        segs.append({"meta": meta, "t0": t0, "t1": t1, "at": at, "path": os.path.join(work, meta["video"])})
        at += t1 - t0
    return segs


def timeline(segs: list) -> dict:
    """Captions, key presses, close-up targets and sounds on the Short's clock."""
    caps, keys, focus, sounds = [], [], [], []
    for s in segs:
        m, off = s["meta"], s["at"] - s["t0"]
        for ev in m["events"]:
            t = ev["t"] + off
            if not (s["at"] - 0.01 <= t <= s["at"] + (s["t1"] - s["t0"])):
                continue
            if ev["kind"] == "beat":
                if t - s["at"] < 0.5:              # a take's first caption is there from its first frame
                    t = s["at"] - (0.3 if s is segs[0] else 0)    # (the Short's very first, without a fade)
                caps.append({"t": t, "text": ev["text"], "keys": ev.get("keys", "")})
            elif ev["kind"] == "key":
                keys.append({"t": t, "key": ev["args"]})
            elif ev["kind"] == "focus":
                focus.append({"t": t, "x": ev["x"], "y": ev["y"], "w": ev.get("w", m["crop"][0]), "seg": s})
        for snd in m["sounds"]:
            t = snd["t"] + off
            if s["at"] <= t <= s["at"] + (s["t1"] - s["t0"]):
                sounds.append({"t": t, "file": snd["file"], "volume": snd["volume"]})
    total = segs[-1]["at"] + segs[-1]["t1"] - segs[-1]["t0"]
    caps.append({"t": total, "text": "", "keys": "", "end": True})
    return {"caps": caps, "keys": keys, "focus": focus, "sounds": sounds, "total": total,
            "duration": total + END_CARD}


# ---------- drawing ----------

def font(cr, size, bold=True, mono=False):
    cr.select_font_face(MONO if mono else FONT, cairo.FONT_SLANT_NORMAL,
                        cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(size)


def wrap(cr, text, width):
    """Lines no wider than width, as even as possible (no lone last word); "|" forces a break."""
    if "|" in text:
        return [line for part in text.split("|") for line in wrap(cr, part, width)]
    words = text.split()
    for n in range(1, len(words) + 1):
        best = None
        # try every way to cut into n lines (captions are short), keep the most even
        def cuts(i, k):
            if k == 1:
                yield [" ".join(words[i:])]
                return
            for j in range(i + 1, len(words) - k + 2):
                for rest in cuts(j, k - 1):
                    yield [" ".join(words[i:j])] + rest
        for lines in cuts(0, n):
            widest = max(cr.text_extents(l).x_advance for l in lines)
            if widest <= width and (best is None or widest < best[0]):
                best = (widest, lines)
        if best:
            return best[1]
    return [text]


def centered(cr, text, y, colour=TEXT, alpha=1.0, shadow=True):
    ext = cr.text_extents(text)
    x = (W - ext.x_advance) / 2
    if shadow:
        cr.set_source_rgba(0, 0, 0, 0.55 * alpha)
        cr.move_to(x + 2, y + 3)
        cr.show_text(text)
    cr.set_source_rgba(*colour, alpha)
    cr.move_to(x, y)
    cr.show_text(text)


def rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def draw_chips(cr, keys: str, y: float, alpha: float, pressed: float):
    """Keycaps for e.g. "Ctrl+Shift+Space", centred; pressed (0..1) lights them up."""
    font(cr, 40)
    parts = keys.split("+")
    pad, gap, h = 22, 18, 66
    widths = [cr.text_extents(p).x_advance + 2 * pad for p in parts]
    plus = cr.text_extents("+").x_advance
    total = sum(widths) + (len(parts) - 1) * (2 * gap + plus)
    x = (W - total) / 2
    sink = 4 * pressed
    for i, (p, w) in enumerate(zip(parts, widths)):
        cr.set_source_rgba(0, 0, 0, 0.5 * alpha)
        rounded(cr, x, y + 6, w, h, 14)
        cr.fill()
        mix = [CHIP[j] + (ORANGE[j] - CHIP[j]) * pressed for j in range(3)]
        cr.set_source_rgba(*mix, alpha)
        rounded(cr, x, y + sink, w, h, 14)
        cr.fill()
        cr.set_line_width(2.5)
        cr.set_source_rgba(*ORANGE, alpha * (0.55 + 0.45 * pressed))
        rounded(cr, x, y + sink, w, h, 14)
        cr.stroke()
        tc = [TEXT[j] + (0.08 - TEXT[j]) * pressed for j in range(3)]
        cr.set_source_rgba(*tc, alpha)
        cr.move_to(x + pad, y + sink + 46)
        cr.show_text(p)
        x += w
        if i < len(parts) - 1:
            cr.set_source_rgba(*SOFT, alpha)
            cr.move_to(x + gap, y + 46)
            cr.show_text("+")
            x += 2 * gap + plus


def draw_caption(cr, tl: dict, t: float):
    caps = tl["caps"]
    i = max((k for k, c in enumerate(caps) if c["t"] <= t + 1e-6), default=-1)
    if i < 0 or caps[i].get("end"):
        return
    c = caps[i]
    nxt = caps[i + 1]["t"] if i + 1 < len(caps) else tl["total"]
    a = ease((t - c["t"]) / 0.28) * ease((nxt - t) / 0.18) if not caps[i + 1].get("end") else ease((t - c["t"]) / 0.28)
    rise = (1 - ease((t - c["t"]) / 0.35)) * 18
    for size in (66, 62, 58, 54, 50):          # two lines at most: a long one gets a smaller font
        font(cr, size)
        lines = wrap(cr, c["text"], W - 2 * 70)
        if len(lines) <= 2:
            break
    y = CAPTION_TOP + 62 + rise + (0 if len(lines) > 1 or c["keys"] else 34)
    for line in lines:
        centered(cr, line, y, alpha=a)
        y += 80
    if c["keys"]:
        pressed = 0.0
        for k in tl["keys"]:
            if c["t"] <= k["t"] <= nxt and k["key"].replace(" ", "").lower() == c["keys"].replace(" ", "").lower():
                pressed = max(pressed, ease((t - k["t"] + 0.08) / 0.08) * (1 - ease((t - k["t"] - 0.35) / 0.4)))
        draw_chips(cr, c["keys"], y - 50 + (0 if len(lines) > 1 else 6), a, pressed)


def draw_brand(cr, alpha=1.0):
    font(cr, 34)
    label = "NineLives"
    ext = cr.text_extents(label)
    sub = "  ·  for the kitty terminal"
    font(cr, 30, bold=False)
    ext2 = cr.text_extents(sub)
    x = (W - ext.x_advance - ext2.x_advance) / 2
    font(cr, 34)
    cr.set_source_rgba(*ORANGE, alpha)
    cr.move_to(x, BRAND_Y)
    cr.show_text(label)
    font(cr, 30, bold=False)
    cr.set_source_rgba(*SOFT, alpha)
    cr.move_to(x + ext.x_advance, BRAND_Y)
    cr.show_text(sub)


def focus_at(tl: dict, t: float, seg) -> tuple:
    """The close-up's source box (x, y, width) at time t: eases 0.45 s to each new one in this take."""
    full = tl["crop"][0]
    fs = [(f["t"], f["x"], f["y"], f.get("w", full)) for f in tl["focus"] if f["seg"] is seg]
    if not fs:
        return 0.0, 0.0, float(full)
    cur = fs[0][1:]
    for prev, f in zip([None] + fs[:-1], fs):
        if f[0] > t:
            break
        if prev is None:
            cur = f[1:]
            continue
        k = ease((t - f[0]) / 0.45)
        cur = tuple(p + (q - p) * k for p, q in zip(prev[1:], f[1:]))
    return cur


def segment_at(segs, t):
    for s in segs:
        if s["at"] <= t < s["at"] + s["t1"] - s["t0"]:
            return s
    return segs[-1]


class Frames:
    """Raw RGB frames of one take's kept range, resampled to FPS by their timestamps."""

    def __init__(self, seg):
        m = seg["meta"]
        self.w, self.h = m["size"]
        self.p = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-ss", f"{seg['t0']:.3f}", "-i", seg["path"],
             "-t", f"{seg['t1'] - seg['t0']:.3f}", "-vf", f"fps={FPS}", "-pix_fmt", "rgb24",
             "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
        self.last = np.zeros((self.h, self.w, 3), np.uint8)

    def next(self):
        buf = self.p.stdout.read(self.w * self.h * 3)
        if len(buf) == self.w * self.h * 3:
            self.last = np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3)
        return self.last

    def close(self):
        self.p.stdout.close()
        self.p.wait()


def background() -> np.ndarray:
    """BGRA background: near-black with a faint warm glow behind the window."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    glow = np.exp(-(((xx - W / 2) / 700) ** 2 + ((yy - 900) / 650) ** 2)) * 0.06
    rgb = np.stack([BG[0] + glow * ORANGE[0], BG[1] + glow * ORANGE[1], BG[2] + glow * ORANGE[2]], -1)
    out = np.empty((H, W, 4), np.uint8)
    out[..., :3] = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)[..., ::-1]
    out[..., 3] = 255
    return out


def compose(canvas: np.ndarray, surf, frame: np.ndarray, box: tuple, tl, t, extra=None):
    """One output frame into canvas (BGRA, the cairo surface's memory)."""
    fh, fw = frame.shape[:2]
    canvas[APP_Y:APP_Y + fh, 0:fw, :3] = frame[..., ::-1]
    fx, fy, fw_ = box
    ch = tl["crop"][1]
    cw = int(round(fw_))
    close_x = W // 2 - cw                         # centred, so its right edge stays clear of YouTube's buttons
    x0, y0 = int(round(fx)), int(round(fy))
    x0, y0 = max(0, min(fw - cw, x0)), max(0, min(fh - ch, y0))
    crop = frame[y0:y0 + ch, x0:x0 + cw]
    big = crop.repeat(ZOOM, 0).repeat(ZOOM, 1)
    canvas[CLOSE_Y:CLOSE_Y + ch * ZOOM, close_x:close_x + cw * ZOOM, :3] = big[..., ::-1]
    surf.mark_dirty()
    cr = cairo.Context(surf)
    # the window's edges, and where the close-up comes from
    cr.set_line_width(2)
    cr.set_source_rgba(*EDGE, 1)
    cr.move_to(0, APP_Y - 1)
    cr.line_to(W, APP_Y - 1)
    cr.move_to(0, APP_Y + fh + 1)
    cr.line_to(W, APP_Y + fh + 1)
    cr.stroke()
    cr.set_source_rgba(*ORANGE, 0.9)
    cr.set_line_width(2.5)
    cr.rectangle(x0 + 1.5, APP_Y + y0 + 1.5, cw - 3, ch - 3)
    cr.stroke()
    # the close-up's frame (drawn over the doubled pixels' edge, rounded corners masked)
    cr.set_source_rgba(*BG, 1)
    cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    cr.rectangle(close_x - 8, CLOSE_Y - 8, cw * ZOOM + 16, ch * ZOOM + 16)
    rounded(cr, close_x, CLOSE_Y, cw * ZOOM, ch * ZOOM, 18)
    cr.fill()
    cr.set_fill_rule(cairo.FILL_RULE_WINDING)
    cr.set_source_rgba(*ORANGE, 0.95)
    cr.set_line_width(3)
    rounded(cr, close_x, CLOSE_Y, cw * ZOOM, ch * ZOOM, 18)
    cr.stroke()
    # thin guides from the source box to the close-up
    cr.set_source_rgba(*ORANGE, 0.28)
    cr.set_line_width(1.5)
    cr.move_to(x0, APP_Y + y0 + ch)
    cr.line_to(close_x, CLOSE_Y)
    cr.move_to(x0 + cw, APP_Y + y0 + ch)
    cr.line_to(close_x + cw * ZOOM, CLOSE_Y)
    cr.stroke()
    draw_brand(cr)
    if extra:
        extra(cr)
    else:
        draw_caption(cr, tl, t)
    surf.flush()


def end_card(surf, canvas, bg, k: float, t_in: float):
    """The last frames: the cat, the name and where to get it."""
    canvas[:] = bg
    surf.mark_dirty()
    cr = cairo.Context(surf)
    a = ease(t_in / 0.4)
    font(cr, 150, mono=True)
    notes = "♪" * min(3, 1 + int(t_in / 0.7))
    cat = "=^ω^="
    ext = cr.text_extents(cat)
    font(cr, 110, mono=True)
    ext_n = cr.text_extents(" ♪♪♪")
    x = (W - ext.x_advance - ext_n.x_advance) / 2
    font(cr, 150, mono=True)
    cr.set_source_rgba(*TEXT, a)
    cr.move_to(x, 700)
    cr.show_text(cat)
    font(cr, 110, mono=True)
    cr.set_source_rgba(0x8f / 255, 0xd6 / 255, 0x8a / 255, a)
    cr.move_to(x + ext.x_advance, 690)
    cr.show_text(" " + notes)
    font(cr, 118)
    centered(cr, "NineLives", 900, colour=ORANGE, alpha=a)
    font(cr, 52, bold=False)
    centered(cr, "free & open source", 1000, colour=TEXT, alpha=a)
    centered(cr, "for the kitty terminal", 1070, colour=SOFT, alpha=a)
    font(cr, 46, mono=True)
    centered(cr, GITHUB, 1220, colour=TEXT, alpha=ease((t_in - 0.3) / 0.4))
    surf.flush()


# ---------- audio ----------

def decode(path: str) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "f32le", "-ac", "2",
                          "-ar", str(RATE), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2)


def write_wav(path: str, x: np.ndarray):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "f32le", "-ac", "2", "-ar", str(RATE),
                    "-i", "-", "-c:a", "pcm_f32le", path], input=x.astype(np.float32).tobytes(), check=True)


def loudness(path: str, af: str = "") -> tuple:
    """(integrated LUFS, true peak dBTP) of a file, after an optional filter."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                          (af + "," if af else "") + "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summ = out[out.rfind("Summary:"):]
    i = float(re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summ).group(1))
    tp = float(re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summ).group(1))
    return i, tp


def duck_envelope(n: int, times: list, depth_db: float) -> np.ndarray:
    """Gain (1 = untouched) that dips depth_db around each sound: down in 60 ms starting 80 ms
    before it, held 0.7 s, back up over 0.45 s (a sidechain compressor, from the known times)."""
    t = np.arange(n) / RATE
    d = np.zeros(n)
    for at in times:
        a0, a1, h1, r1 = at - 0.08, at - 0.02, at + 0.7, at + 1.15
        shape = np.clip((t - a0) / (a1 - a0), 0, 1) * np.clip((r1 - t) / (r1 - h1), 0, 1)
        d = np.maximum(d, shape * shape * (3 - 2 * shape))
    return 1 - (1 - 10 ** (-depth_db / 20)) * d


def rms_db(x: np.ndarray) -> float:
    return 20 * math.log10(max(1e-9, float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))))


def mix(tl: dict, work: str, music: bool = True) -> str:
    n = int(math.ceil(tl["duration"] * RATE)) + RATE
    snd = np.zeros((n, 2), np.float64)
    cache = {}
    for s in tl["sounds"]:
        if s["file"] not in cache:
            cache[s["file"]] = decode(os.path.join(SOUNDS, s["file"]))
        x = cache[s["file"]] * s["volume"]
        i = int(round(s["t"] * RATE))
        snd[i:i + len(x)] += x[: n - i]
    n = int(round(tl["duration"] * RATE))
    snd = snd[:n]
    stem_s = os.path.join(work, "stem-sounds.wav")
    write_wav(stem_s, snd)
    i_snd, tp_snd = loudness(stem_s)
    print(f"audio: {len(tl['sounds'])} sounds alone {i_snd:.1f} LUFS, true peak {tp_snd:.1f} dBTP")
    bed = np.zeros_like(snd)
    if music:
        import music as bedmusic                # tools/short/music.py
        m = bedmusic.render(tl["duration"], tl["total"])[:n]
        stem_m = os.path.join(work, "stem-music.wav")
        write_wav(stem_m, m)
        i_m, _ = loudness(stem_m)
        # the bed sits MUSIC_UNDER dB under the chimes, and dips DUCK dB more around each one
        bed = m * 10 ** ((i_snd - MUSIC_UNDER - i_m) / 20)
        bed *= duck_envelope(n, [s["t"] for s in tl["sounds"]], DUCK)[:, None]
        write_wav(stem_m, bed)
        print(f"audio: music {bedmusic.describe(tl['duration'], tl['total'])}; "
              f"{MUSIC_UNDER:.0f} dB under the sounds, ducked {DUCK:.0f} dB around each")
    raw = os.path.join(work, "mix-raw.wav")
    write_wav(raw, snd + bed)
    i0, tp0 = loudness(raw)
    print(f"audio: raw mix {i0:.1f} LUFS, true peak {tp0:.1f} dBTP")
    # one static gain to -14 LUFS; if that pushes the true peak over -1.5 dBTP, a fast lookahead
    # limiter takes the tips off the chimes' attacks (their levels against each other stay put)
    gain, target, ceiling = -14.0 - i0, -14.0, -1.5
    af = f"volume={gain:.2f}dB"
    if tp0 + gain > ceiling:
        lim = 10 ** ((ceiling - 1.0) / 20)
        for _ in range(8):
            af = (f"volume={gain:.2f}dB,aresample=192000,alimiter=limit={lim:.4f}:attack=2:release=60:"
                  f"level=disabled:asc=0,aresample={RATE}")
            i1, tp1 = loudness(raw, af)
            if abs(i1 - target) < 0.1:
                break
            gain += target - i1
        print(f"audio: gain {gain:+.1f} dB with a limiter at {ceiling - 1.0:.1f} dBFS → {i1:.1f} LUFS, {tp1:.1f} dBTP"
              f" (the limiter takes up to {tp0 + gain - (ceiling - 1.0):.1f} dB off the loudest attack)")
    out = os.path.join(work, "mix.wav")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", raw, "-af", af, "-c:a", "pcm_f32le", out], check=True)
    if music:
        final = decode(out)
        print("audio: each sound against the bed (RMS dB; 'before' = 1.0-0.2 s before it, unducked bed;"
              " 'at' = the 0.4 s from the sound, in the final mix; 'over bed' = the sound alone vs the ducked bed then)")
        for s in tl["sounds"]:
            i = int(s["t"] * RATE)
            before = rms_db(final[i - RATE: i - int(0.2 * RATE)])
            at = rms_db(final[i: i + int(0.4 * RATE)])
            over = rms_db(snd[i: i + int(0.4 * RATE)]) - rms_db(bed[i: i + int(0.4 * RATE)])
            print(f"  {s['t']:6.2f}  {s['file']:<14} before {before:6.1f}  at {at:6.1f}  (+{at - before:4.1f} dB)"
                  f"   sound over bed {over:+5.1f} dB")
    return out


# ---------- main ----------

def render(work: str, out: str, thumb: str = "", preview=None, music: bool = True):
    segs = load_takes(work)
    tl = timeline(segs)
    tl["crop"] = segs[0]["meta"]["crop"]
    bg = background()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    canvas = np.ndarray((H, W, 4), np.uint8, surf.get_data())
    if preview is not None:
        for t in preview:
            if t >= tl["total"]:
                end_card(surf, canvas, bg, 1, t - tl["total"])
                surf.write_to_png(os.path.join(work, f"preview-{t:05.2f}.png"))
                continue
            s = segment_at(segs, t)
            local = s["t0"] + t - s["at"]
            png = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{local:.3f}", "-i", s["path"],
                                  "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                                 capture_output=True, check=True).stdout
            w, h = s["meta"]["size"]
            frame = np.frombuffer(png, np.uint8).reshape(h, w, 3)
            canvas[:] = bg
            compose(canvas, surf, frame, focus_at(tl, t, s), tl, t)
            surf.write_to_png(os.path.join(work, f"preview-{t:05.2f}.png"))
        return
    if thumb:
        make_thumb(segs, tl, bg, surf, canvas, thumb)
    audio = mix(tl, work, music)
    n_frames = int(round(tl["duration"] * FPS))
    enc = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", audio, "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-tune", "animation", "-pix_fmt", "yuv420p",
         "-profile:v", "high", "-level", "4.2", "-r", str(FPS), "-g", str(FPS * 2),
         "-c:a", "aac", "-b:a", "192k", "-ar", str(RATE), "-movflags", "+faststart",
         "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-shortest", out],
        stdin=subprocess.PIPE)
    readers = {}
    for f in range(n_frames):
        t = f / FPS
        if t < tl["total"]:
            s = segment_at(segs, t)
            r = readers.get(id(s))
            if r is None:
                for old in readers.values():
                    old.close()
                readers.clear()
                r = readers[id(s)] = Frames(s)
            frame = r.next()
            canvas[:] = bg
            compose(canvas, surf, frame, focus_at(tl, t, s), tl, t)
        else:
            end_card(surf, canvas, bg, 1, t - tl["total"])
        enc.stdin.write(canvas.tobytes())
    for r in readers.values():
        r.close()
    enc.stdin.close()
    enc.wait()
    i, tp = loudness(out)
    print(f"wrote {out}: {n_frames / FPS:.2f} s, {os.path.getsize(out) / 1e6:.1f} MB, "
          f"{i:.1f} LUFS integrated, {tp:.1f} dBTP true peak")
    print("beats:")
    for c in tl["caps"][:-1]:
        print(f"  {max(0.0, c['t']):6.2f}  {c['text']}" + (f"  [{c['keys']}]" if c["keys"] else ""))
    print(f"  {tl['total']:6.2f}  end card")
    for s in tl["sounds"]:
        print(f"  sound {s['t']:6.2f}  {s['file']}")


def make_thumb(segs, tl, bg, surf, canvas, path):
    """A still for the video's cover: the moment a tab needs you, with a bigger headline."""
    s = segs[0]
    m = s["meta"]
    blocked = next(ev["t"] for ev in m["events"] if ev["kind"] == "state" and ev["args"].endswith("blocked"))
    w, h = m["size"]
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{blocked:.3f}", "-i", s["path"], "-t", "3",
                          "-vf", f"fps={FPS}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
    # a frame with the waiting tab's pulse on: most amber in the status column and the cat's "!"
    # (the active tab's orange row, which never changes, is left out)
    side = frames.astype(np.int16)
    col = side[:, 80:270, 30:60]               # tabs 2… (tab 1, on screen, is orange throughout)
    cat = side[:, 270:300, 200:310]
    def amberish(px):
        return ((px[..., 0] > 150) & (px[..., 0] - px[..., 2] > 60)).sum(axis=(1, 2))
    amber = amberish(col) + amberish(cat)
    best = int(np.argmax(amber))
    frame = frames[best]
    local = blocked + best / FPS
    canvas[:] = bg

    def headline(cr):
        font(cr, 84)
        y = CAPTION_TOP + 70
        for line in ("Every AI agent.", "One kitty window."):
            centered(cr, line, y)
            y += 100
    compose(canvas, surf, frame, focus_at(tl, s["at"] + local - s["t0"], s), tl, 0, extra=headline)
    surf.write_to_png(path)
    print(f"wrote {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("work")
    ap.add_argument("out", nargs="?", default="")
    ap.add_argument("--thumb", default="")
    ap.add_argument("--preview", type=float, nargs="+")
    ap.add_argument("--no-music", action="store_true", help="only NineLives' sounds, no music bed")
    a = ap.parse_args()
    if not a.out and a.preview is None:
        ap.error("OUT.mp4 (or --preview T)")
    render(a.work, a.out, a.thumb, a.preview, music=not a.no_music)


if __name__ == "__main__":
    sys.exit(main())
