"""nine.py — Nine, NineLives' cat: the parts that don't need kitty. Part of NineLives.

The sidebar's cat (tab_bar.py) uses them inside kitty; anything else that shows Nine (a panel of
its own, tests) can import them as they are:

    moves and poses   MOVES, FIDGETS, pick_frame(), lip()   what it does, which picture shows
    walking           route(), step()                        where it goes, a step at a time
    talking           Reveal                                 the words coming out, the mouth in step
    the bubble        Bubble (render())                      a speech bubble as an RGBA picture; the
                                                             text is drawn by a function you hand it
    memory            Memory                                 what it said lately, so it doesn't repeat

The pictures themselves are config/cat/ (scripts/make-cat.py); the lines it says come from
cat-helper.py's suggestions().
"""
import hashlib
import json
import os
import time

# ---- moves: (frame, ticks of 1/8 s) in a row, then back to resting ------------------------------------
MOVES = {
    "blink": (("blink", 1),), "wink": (("wink", 5),), "ear": (("ear", 2), ("idle", 2), ("ear", 2)),
    "tail": (("tail-left", 2), ("tail-right", 2), ("tail-left", 2), ("tail-right", 2)),
    "look-left": (("look-left", 8),), "look-right": (("look-right", 8),), "nod": (("nod", 2),),
    "hop": (("hop-low", 1), ("hop", 2), ("hop-low", 1), ("wave", 3), ("happy", 1), ("wave", 3)),
    "surprise": (("surprised", 10),), "cheer": (("hop-low", 1), ("hop", 3), ("hop-low", 1), ("happy", 4)),
    "flinch": (("ear", 1), ("surprised", 4)), "land": (("hop-low", 1), ("happy", 3)),
}
FIDGETS = ("wink", "ear", "tail", "look-left", "look-right", "walk")
BLINK, FIDGET = 0.22, 0.03          # chances at each roll of the dice (once a second)
WALK_STEPS = 4


def pick_frame(walking_to=None, pos=(0.0, 0.0), phase=0.0, facing=1, queue=(), spot="floor",
               pointing=False, asleep=False, carried=False) -> str:
    """The picture to show now. walking_to: the next waypoint while it walks (up or down: it
    bounds, hop frames; along: the walk cycle facing its way); carried: dangling, surprised; a move
    playing (queue: [[frame, ticks]]); sitting by a tab: pointing at it while it talks about it,
    else looking at it; asleep; else sitting."""
    if walking_to is not None:
        dx, dy = walking_to[0] - pos[0], walking_to[1] - pos[1]
        if abs(dy) > abs(dx):
            return "hop" if int(phase) % 2 else "hop-low"
        return f"walk-{'right' if facing > 0 else 'left'}-{int(phase) % WALK_STEPS + 1}"
    if carried:
        return "surprised"
    if queue:
        return queue[0][0]
    if spot == "visit":
        return "point-left" if pointing else "look-left"
    return "sleepy" if asleep else "idle"


def lip(ch: str) -> str:
    """The mouth for a letter it is saying: open on a, e; round on o, u; a little open on the other
    letters; shut between words and at punctuation."""
    c = ch.lower()
    if c in "ae":
        return "open"
    if c in "ou":
        return "o"
    if c.isalnum():
        return "small"
    return "w"


# ---- walking ---------------------------------------------------------------------------------------------
def route(pos, target, floor_y) -> list:
    """The way there, like a cat: down to the floor first (from up the sidebar), along the floor,
    then straight up. Waypoints, the target last."""
    (x, y), (tx, ty) = pos, target
    pts = []
    if abs(y - floor_y) > 1 and abs(tx - x) > 1:
        pts.append((x, floor_y))
        y = floor_y
    if abs(ty - y) > 1 and abs(tx - x) > 1:
        pts.append((tx, y))
    pts.append((tx, ty))
    return pts


def step(pos, target, dt, speed) -> tuple:
    """(x, y, arrived): pos moved toward target by speed × dt at most."""
    dx, dy = target[0] - pos[0], target[1] - pos[1]
    dist = (dx * dx + dy * dy) ** 0.5
    if dist <= max(speed * dt, 0.5):
        return target[0], target[1], True
    k = speed * dt / dist
    return pos[0] + dx * k, pos[1] + dy * k, False


# ---- talking: the words come out at a steady pace ---------------------------------------------------------
class Reveal:
    """How much of a line is said at time t: `cps` characters a second, a short pause after . , ! ?
    and the mouth for the letter being said (lip())."""
    PAUSE = {".": 0.28, "!": 0.28, "?": 0.28, ",": 0.14, ":": 0.14, ";": 0.14, "—": 0.14}

    def __init__(self, text: str, start: float, cps: float = 50.0):
        self.text, self.start = text, start
        self.times, t = [], 0.0
        for c in text:
            t += 1.0 / cps
            self.times.append(t)
            t += self.PAUSE.get(c, 0.0)
        self.length = t

    def count(self, now: float) -> int:
        """Characters said by now."""
        el = now - self.start
        lo, hi = 0, len(self.times)
        while lo < hi:                                # (bisect: how many times are <= el)
            mid = (lo + hi) // 2
            if self.times[mid] <= el:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def done(self, now: float) -> bool:
        return self.count(now) >= len(self.text)

    def mouth(self, now: float) -> str:
        n = self.count(now)
        if n >= len(self.text) or n == 0:
            return "w"
        return lip(self.text[n - 1])


# ---- the bubble, as a picture ------------------------------------------------------------------------------
def _cov(px, py, x0, y0, x1, y1, r) -> float:
    """How much of pixel (px, py) a rounded rectangle covers (4×4 samples near the corners)."""
    if x0 + r <= px and px + 1 <= x1 - r and y0 <= py and py + 1 <= y1:
        return 1.0
    if y0 + r <= py and py + 1 <= y1 - r and x0 <= px and px + 1 <= x1:
        return 1.0
    if px + 1 <= x0 or px >= x1 or py + 1 <= y0 or py >= y1:
        return 0.0
    hit = 0
    for sy in range(4):
        for sx in range(4):
            x, y = px + (sx + 0.5) / 4, py + (sy + 0.5) / 4
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                continue
            qx, qy = min(max(x, x0 + r), x1 - r), min(max(y, y0 + r), y1 - r)
            if (x - qx) ** 2 + (y - qy) ** 2 <= r * r:
                hit += 1
    return hit / 16


class Canvas:
    """A small RGBA picture (straight alpha) to draw a bubble into."""
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.px = bytearray(w * h * 4)

    def blend(self, i: int, rgb, a: float) -> None:
        if a <= 0:
            return
        p = self.px
        da = p[i + 3] / 255
        oa = a + da * (1 - a)
        if oa <= 0:
            return
        for k in range(3):
            p[i + k] = min(255, round((rgb[k] * a + p[i + k] * da * (1 - a)) / oa))
        p[i + 3] = min(255, round(oa * 255))

    def rounded(self, x0, y0, x1, y1, r, rgb) -> None:
        """A filled rounded rectangle (x1, y1 exclusive), its edge antialiased."""
        row = bytes((*rgb, 255))
        for y in range(max(0, int(y0)), min(self.h, int(y1 + 0.999))):
            inner = y0 + r <= y and y + 1 <= y1 - r
            a, b = (int(x0 + 0.999), int(x1)) if inner else (int(x0 + r + 0.999), int(x1 - r))
            a, b = max(0, a), min(self.w, b)
            if b > a:
                self.px[(y * self.w + a) * 4:(y * self.w + b) * 4] = row * (b - a)
            for x in list(range(max(0, int(x0)), max(0, a))) + list(range(max(b, 0), min(self.w, int(x1 + 0.999)))):
                self.blend((y * self.w + x) * 4, rgb, _cov(x, y, x0, y0, x1, y1, r))

    def paste(self, src, sw: int, sh: int, x: int, y: int, premultiplied: bool = True) -> None:
        """Lay a picture (RGBA, premultiplied the way kitty's text renderer gives it) over this one."""
        for yy in range(sh):
            ty = y + yy
            if not 0 <= ty < self.h:
                continue
            for xx in range(sw):
                tx = x + xx
                if not 0 <= tx < self.w:
                    continue
                j = (yy * sw + xx) * 4
                a = src[j + 3]
                if not a:
                    continue
                k = a / 255
                rgb = tuple(min(255, round(src[j + c] / k)) for c in range(3)) if premultiplied else src[j:j + 3]
                self.blend((ty * self.w + tx) * 4, rgb, k)


class Bubble:
    """A speech bubble as a picture: a rounded card in the theme's colours with a title (in the
    line's colour), a count and a × in the top right corner, the text, and the buttons as filled
    chips (the action in the accent pair, Next in the selection pair). The text goes in a picture
    of its own (text_px), so it can be revealed bit by bit by cropping it; tail() is the little
    pointer to the cat, also its own picture so it can follow the cat along the bubble's edge.

    text(s, rgb) -> (premultiplied RGBA bytes, width, height): draws one line of text (kitty's own
    renderer in kitty; anything that returns the same will do). Colours are (r, g, b)."""
    def __init__(self, text, scale: float = 1.0):
        self.text = text
        self.s = max(1.0, scale)
        self._w = {}

    def width_of(self, s: str) -> int:
        if s not in self._w:
            self._w[s] = self.text(s, (255, 255, 255))[1] if s else 0
        return self._w[s]

    def fit(self, s: str, width: int) -> str:
        """s as it is if it's at most `width` px wide, else cut short with … to fit."""
        if self.width_of(s) <= width:
            return s
        while s and self.width_of(s + "…") > width:
            s = s[:-1]
        return s.rstrip() + "…"

    def wrap(self, s: str, width: int, most: int) -> list:
        """The words in lines at most `width` px wide, at most `most` lines (the last cut with …)."""
        out, line = [], ""
        for word in s.split():
            trial = f"{line} {word}" if line else word
            if line and self.width_of(trial) > width:
                out.append(line)
                line = word
            else:
                line = trial
        if line:
            out.append(line)
        if len(out) > most:
            last = " ".join(out[most - 1:])
            while last and self.width_of(last + "…") > width:
                last = last[:-1]
            out = out[:most - 1] + [last.rstrip() + "…"]
        return out

    def render(self, width: int, title: str, title_rgb, count: str, body: str, buttons, colours,
               most_lines: int = 5) -> dict:
        """Everything about one bubble `width` px wide: {"w", "h", "px" (RGBA bytes), "text": (w, h,
        RGBA bytes) and where it goes ("tx", "ty"), "lines": [(chars, px wide)], "lh" (a line's
        height), "regions": [(x0, y0, x1, y1, command)], "chars": the text as said}. buttons:
        [(words, command, "do" or "next")]; colours: bg, border, fg, muted, close, do (fill, text),
        next (fill, text)."""
        s = self.s
        pad, radius = round(9 * s), round(9 * s)
        inner = width - 2 * pad
        lh = self.text("Ag", colours["fg"])[2]
        lines = self.wrap(body, inner, most_lines)
        x_w = self.width_of("×")
        head = lh
        top = round(5 * s)
        text_y = top + head + round(1 * s)
        chip_h = lh + round(4 * s)
        chip_pad = round(8 * s)
        gap = round(8 * s)
        # the buttons in a row, the next one on a row of its own when it doesn't fit beside, and words
        # too long for any row shortened (…): every chip, and so every click region, inside the card
        chips, x, row = [], pad, 0
        for words, cmd, style in buttons:
            words = self.fit(words, inner - 2 * chip_pad)
            w = self.width_of(words) + 2 * chip_pad
            if x > pad and x + w > width - pad:
                row, x = row + 1, pad
            chips.append((x, row, words, cmd, style, w))
            x += w + gap
        rows = chips[-1][1] + 1 if chips else 0
        row_h = chip_h + round(5 * s)
        buttons_y = text_y + len(lines) * lh + round(6 * s)
        h = buttons_y + (rows * row_h - round(5 * s) + round(9 * s) if chips else round(3 * s))
        c = Canvas(width, h)
        bw = max(1, round(1.5 * s))
        c.rounded(0, 0, width, h, radius, colours["border"])
        c.rounded(bw, bw, width - bw, h - bw, max(1, radius - bw), colours["bg"])
        px, w, hh = self.text(title, title_rgb)
        c.paste(px, w, hh, pad, top)
        regions = []
        # the × in the corner, and the count left of it
        close_w = x_w + round(12 * s)
        cx = width - pad - x_w
        px, w, hh = self.text("×", colours["close"])
        c.paste(px, w, hh, cx, top)
        regions.append((width - close_w - round(4 * s), 0, width, top + head + round(2 * s), "quit"))
        if count:
            px, w, hh = self.text(count, colours["muted"])
            c.paste(px, w, hh, cx - round(10 * s) - w, top)
        for x0, row, words, cmd, style, w in chips:
            fill, ink = colours[style]
            y0 = buttons_y + row * row_h
            c.rounded(x0, y0, x0 + w, y0 + chip_h, round(5 * s), fill)
            px, tw, hh = self.text(words, ink)
            c.paste(px, tw, hh, x0 + chip_pad, y0 + (chip_h - hh) // 2)
            regions.append((x0, y0, x0 + w, y0 + chip_h, cmd))
        # the text, a picture of its own
        tw, th = max(1, inner), max(1, len(lines) * lh)
        t = Canvas(tw, th)
        widths = []
        for i, line in enumerate(lines):
            px, w, hh = self.text(line, colours["fg"])
            t.paste(px, w, hh, 0, i * lh)
            widths.append((len(line), min(w, tw)))
        return {"w": width, "h": h, "px": bytes(c.px), "text": (tw, th, bytes(t.px)), "tx": pad, "ty": text_y,
                "lines": widths, "lh": lh, "regions": regions, "chars": " ".join(lines)}

    def tail(self, colours, down: bool = True) -> tuple:
        """(w, h, RGBA bytes): the pointer under the bubble (down) or over it (up), its open side
        covering the bubble's border so they join."""
        s = self.s
        w, h = round(16 * s), round(10 * s)
        bw = max(1, round(1.5 * s))
        c = Canvas(w, h + bw)
        for y in range(h + bw):
            yy = y - bw if down else h - 1 - y + bw
            for x in range(w):
                d = (x + 0.5) - w / 2
                half = (w / 2) * (1 - max(0, yy) / h)
                if yy < 0:
                    c.blend((y * w + x) * 4, colours["bg"], 1.0 if abs(d) < w / 2 - bw * 1.5 else 0.0)
                    continue
                inside = half - abs(d)
                if inside > bw:
                    c.blend((y * w + x) * 4, colours["bg"], 1.0)
                elif inside > -0.5:
                    c.blend((y * w + x) * 4, colours["border"], min(1.0, inside + 0.5))
        return w, h + bw, bytes(c.px)


def place_bubble(cat_x, cat_y, cat_px, bw, bh, area_w, area_h, tail_h) -> tuple:
    """Where a bubble bw × bh goes for a cat at (cat_x, cat_y), cat_px tall, in an area_w × area_h
    box it must stay inside: above the cat, its tail pointing down at its head; below it when
    there's no room above. (x, y, tail x, tail y, tail points down)."""
    mid = cat_x + cat_px * 0.5
    x = min(max(0.0, mid - bw / 2), max(0.0, area_w - bw))
    head = cat_y + cat_px * 0.12
    y = head - tail_h - bh + 2
    down = True
    if y < 0:
        y, down = cat_y + cat_px * 0.98 + tail_h - 2, False
        if y + bh > area_h:                            # no room either way: over the cat's top
            y, down = max(0.0, min(area_h - bh, head - bh)), True
    tx = min(max(x + 12, mid - 8), x + bw - 28)
    ty = y + bh - 2 if down else y - tail_h + 2
    return x, y, tx, ty, down


# ---- memory: what it said lately ------------------------------------------------------------------------------
STATUS = ("waiting", "error", "done", "hello", "badge")
DAILY = ("tip", "joke", "word", "quest")
STATUS_COOLDOWN = 30 * 60.0         # a line about the same thing: not again for 30 minutes
RECENT = 20                         # and none of the last 20 lines again


def fingerprint(text: str) -> str:
    """A line's words as Memory keeps them: a short hash, never the words (a tab's name can be a
    whole command line with kitty-commands full, and the cat-said file is no place for that)."""
    return "#" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def _is_fingerprint(x: str) -> bool:
    return len(x) == 17 and x[0] == "#" and all(c in "0123456789abcdef" for c in x[1:])


class Memory:
    """The lines said lately (kept in a small file, so a restart doesn't make it repeat itself):
    the last RECENT of them (as fingerprints), and when each key was said. fresh() says whether a line may be said
    now: never one of the last RECENT texts (news about tabs aside: see below); a tip, joke, word or quest not again the same day; a
    line about a tab or a badge not again for STATUS_COOLDOWN (its key names the event, so a new
    event is a new key)."""
    def __init__(self, path: str = ""):
        self.path = path
        self.said, self.recent = {}, []
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                self.said = {k: float(v) for k, v in d.get("said", {}).items()}
                # (a file from before kept the words themselves: hashed now, so the next write drops them)
                self.recent = [x if _is_fingerprint(x) else fingerprint(x)
                               for x in (str(x) for x in d.get("recent", []))][-RECENT:]
            except (OSError, ValueError, AttributeError):
                pass

    def fresh(self, item: dict, now=None) -> bool:
        now = time.time() if now is None else now
        if item.get("kind") not in STATUS and fingerprint(item.get("text", "")) in self.recent:
            return False                              # (news about a tab is its event's: a new one is news)
        at = self.said.get(item.get("key", ""))
        if at is None:
            return True
        if item.get("kind") in DAILY:
            return time.strftime("%Y-%m-%d", time.localtime(at)) != time.strftime("%Y-%m-%d", time.localtime(now))
        return now - at >= STATUS_COOLDOWN

    def note(self, item: dict, now=None) -> None:
        now = time.time() if now is None else now
        self.said[item.get("key", "")] = now
        self.recent = (self.recent + [fingerprint(item.get("text", ""))])[-RECENT:]
        if len(self.said) > 400:                         # old keys go (a day is the longest cooldown)
            self.said = {k: v for k, v in self.said.items() if now - v < 2 * 86400}
        if self.path:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump({"said": self.said, "recent": self.recent}, f)
                os.replace(self.path + ".tmp", self.path)
            except OSError:
                pass


ALL_SAID = {"kind": "hello", "key": "all-said", "title": "That's all", "action": None,
            "text": "That's all I've got for now. I'll keep an eye on your tabs."}


def next_line(items, sel: int, shown) -> int:
    """After line `sel`, the next one not shown yet in this bubble (never back to one just
    shown); -1 when every line was shown (then say ALL_SAID)."""
    for i in range(sel + 1, len(items)):
        if items[i].get("key") not in shown:
            return i
    return -1
