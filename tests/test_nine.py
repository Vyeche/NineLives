#!/usr/bin/env python3
"""Unit tests for config/nine.py, the kitty-independent parts of the sidebar's cat: walking, which
picture shows, talking at a steady pace, the bubble picture, where the bubble goes, and the memory
that keeps it from repeating itself. No kitty, no display.
    python3 -m unittest discover -s tests"""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    spec = importlib.util.spec_from_file_location("nl_nine", os.path.join(HERE, "..", "config", "nine.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_text(s, rgb):
    """A stand-in for kitty's text renderer: 7 px a character, 18 px tall, every pixel ink."""
    w = 7 * len(s)
    return bytes((*rgb, 255)) * (w * 18), w, 18


class Walking(unittest.TestCase):
    def setUp(self):
        self.n = load()

    def test_a_route_goes_down_along_and_up(self):
        r = self.n.route
        self.assertEqual(r((10, 400), (200, 400), 400), [(200, 400)])                 # along the floor
        self.assertEqual(r((10, 400), (230, 100), 400), [(230, 400), (230, 100)])     # along, then up
        self.assertEqual(r((230, 100), (10, 400), 400), [(230, 400), (10, 400)])      # down, then along
        self.assertEqual(r((120, 150), (20, 400), 400), [(120, 400), (20, 400)])      # from a perch

    def test_a_step_never_overshoots(self):
        x, y, done = self.n.step((0, 0), (10, 0), 1.0, 45)
        self.assertEqual((x, y, done), (10, 0, True))
        x, y, done = self.n.step((0, 0), (100, 0), 0.1, 45)
        self.assertAlmostEqual(x, 4.5)
        self.assertFalse(done)

    def test_which_picture_shows(self):
        f = self.n.pick_frame
        self.assertEqual(f(), "idle")
        self.assertEqual(f(asleep=True), "sleepy")
        self.assertEqual(f((100, 0), (0, 0), 2.3, 1), "walk-right-3")
        self.assertEqual(f((0, 0), (100, 0), 0.0, -1), "walk-left-1")
        self.assertIn(f((0, 0), (0, 300), 1.0, 1), ("hop", "hop-low"))              # climbing: bounding
        self.assertEqual(f(queue=[["blink", 1]]), "blink")
        self.assertEqual(f(spot="visit"), "look-left")
        self.assertEqual(f(spot="visit", pointing=True), "point-left")
        self.assertEqual(f(carried=True, queue=[["blink", 1]]), "surprised")
        frames = set()
        for name, steps in self.n.MOVES.items():
            frames |= {fr for fr, ticks in steps}
            self.assertTrue(all(ticks > 0 for _, ticks in steps), name)
        ch = importlib.util.spec_from_file_location("ch", os.path.join(HERE, "..", "config", "cat-helper.py"))
        helper = importlib.util.module_from_spec(ch)
        ch.loader.exec_module(helper)
        self.assertLessEqual(frames | {"point-left", "look-left", "sleepy"}, set(helper.FRAMES))   # all drawn


class Talking(unittest.TestCase):
    def setUp(self):
        self.n = load()

    def test_the_words_come_at_a_steady_pace_with_pauses(self):
        r = self.n.Reveal("Hi, you. Ok", 100.0, cps=50)
        counts = [r.count(100.0 + t / 100) for t in range(0, 200)]
        self.assertEqual(counts, sorted(counts))                          # never backwards
        self.assertEqual(r.count(100.0), 0)
        self.assertEqual(r.count(100.0 + 0.021), 1)                       # a letter every 1/50 s
        self.assertTrue(r.done(100.0 + r.length))
        # a comma and a full stop hold it a moment: longer than the letters alone
        self.assertGreater(r.length, len("Hi, you. Ok") / 50 + 0.3)

    def test_the_mouth_follows_the_letters(self):
        lip = self.n.lip
        self.assertEqual([lip(c) for c in "ao xy ,."], ["open", "o", "w", "small", "small", "w", "w", "w"])
        r = self.n.Reveal("ab", 0.0, cps=10)
        self.assertEqual(r.mouth(0.0), "w")                                # not started: shut
        self.assertEqual(r.mouth(0.1), "open")                             # "a"
        self.assertEqual(r.mouth(5.0), "w")                                # said: shut


class BubblePicture(unittest.TestCase):
    def setUp(self):
        self.n = load()
        self.colours = {"bg": (23, 20, 31), "fg": (235, 231, 242), "muted": (200, 195, 210), "close": (235, 231, 242),
                        "border": (120, 115, 130), "do": ((230, 126, 0), (23, 20, 31)),
                        "next": ((74, 63, 95), (242, 239, 247))}

    def render(self, text="Tab 7 “Migrate” is waiting for you. Go there?", buttons=None, width=300):
        b = self.n.Bubble(fake_text)
        buttons = buttons if buttons is not None else [("Go there ↵", "do", "do"), ("Next tip ›", "next", "next")]
        return b.render(width, "Needs you", (207, 174, 124), "1/5", text, buttons, self.colours)

    def test_its_parts_and_where_a_click_lands(self):
        spec = self.render()
        self.assertEqual(len(spec["px"]), spec["w"] * spec["h"] * 4)
        tw, th, tpx = spec["text"]
        self.assertEqual(len(tpx), tw * th * 4)
        self.assertEqual(th, len(spec["lines"]) * spec["lh"])
        self.assertTrue(all(w <= tw for _, w in spec["lines"]))            # the words fit inside
        regions = {r[4]: r for r in spec["regions"]}
        self.assertEqual(set(regions), {"quit", "do", "next"})
        x0, y0, x1, y1, _ = regions["quit"]
        self.assertEqual(x1, spec["w"])                                    # × in the top right corner
        self.assertEqual(y0, 0)
        do, nxt = regions["do"], regions["next"]
        self.assertLess(do[2], nxt[0])                                     # side by side, a gap between
        self.assertGreaterEqual(nxt[0] - do[2], 8)
        self.assertLess(do[3], spec["h"])
        self.assertGreater(do[1], spec["ty"] + th - 1)                     # under the words
        # the corners are rounded (see-through), the middle is the bubble's colour
        self.assertEqual(spec["px"][3], 0)
        mid = (spec["h"] // 2 * spec["w"] + 3) * 4
        self.assertEqual(tuple(spec["px"][mid:mid + 3]), self.colours["bg"])
        self.assertEqual(spec["chars"], "Tab 7 “Migrate” is waiting for you. Go there?")

    def test_buttons_fit_a_narrow_card(self):
        one = self.render(width=300)
        spec = self.render(width=150)                             # two 86 px chips don't fit side by side
        chips = [r for r in spec["regions"] if r[4] in ("do", "next")]
        self.assertEqual(len(chips), 2)
        for x0, y0, x1, y1, cmd in spec["regions"]:
            self.assertTrue(0 <= x0 < x1 <= spec["w"] and 0 <= y0 < y1 <= spec["h"], cmd)
        (a, b) = sorted(chips, key=lambda r: r[1])
        self.assertGreaterEqual(b[1], a[3])                       # Next on a row of its own
        self.assertGreater(spec["h"], self.render("x", width=150, buttons=[("Go ↵", "do", "do")])["h"])
        self.assertEqual(len([r for r in one["regions"] if r[4] in ("do", "next")]), 2)
        tiny = self.render(width=80, buttons=[("Go there, it is waiting ↵", "do", "do")])
        x0, y0, x1, y1, _ = [r for r in tiny["regions"] if r[4] == "do"][0]
        self.assertLessEqual(x1, 80 - 9)                          # shortened with … to fit inside

    def test_a_long_line_wraps_and_is_cut_at_the_last_line(self):
        spec = self.render("word " * 200, buttons=[], width=200)
        self.assertEqual(len(spec["lines"]), 5)
        self.assertTrue(spec["chars"].endswith("…"))
        self.assertEqual({r[4] for r in spec["regions"]}, {"quit"})       # no buttons: just ×

    def test_the_tail(self):
        b = self.n.Bubble(fake_text)
        for down in (True, False):
            w, h, px = b.tail(self.colours, down)
            self.assertEqual(len(px), w * h * 4)
            alpha = [px[(y * w + w // 2) * 4 + 3] for y in range(h)]
            self.assertTrue(all(a > 0 for a in alpha[3:-3]), alpha)       # solid down its middle

    def test_the_bubble_stays_inside_and_points_at_the_cat(self):
        place = self.n.place_bubble
        for cx in range(0, 231, 23):
            for cy in range(0, 681, 40):
                x, y, tx, ty, down = place(cx, cy, 80, 300, 120, 310, 760, 11)
                self.assertTrue(0 <= x and x + 300 <= 310, (cx, cy, x))
                self.assertTrue(0 <= y and y + 120 <= 760, (cx, cy, y))
                self.assertTrue(x <= tx <= x + 300 - 16, (cx, cy, tx))
                if down:
                    self.assertLessEqual(ty + 11, cy + 80 * 0.12 + 3)        # above the cat's head
        x, y, tx, ty, down = place(20, 680, 80, 300, 120, 310, 760, 11)
        self.assertTrue(down)                                              # on the floor: above it
        x, y, tx, ty, down = place(20, 0, 80, 300, 120, 310, 760, 11)
        self.assertFalse(down)                                             # at the top: below it
        self.assertGreater(y, 80 * 0.9)


class Memory(unittest.TestCase):
    """It says each thing once: a tab's news not again for 30 minutes (a new event is a new key), a
    tip or joke not again the same day, none of its last 20 lines again."""
    def setUp(self):
        self.n = load()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "cat-said")

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_repeats_across_many_polls(self):
        m = self.n.Memory(self.path)
        item = {"kind": "waiting", "key": "waiting:7@123.0", "text": "Tab 7 is waiting for you."}
        said = 0
        for i in range(200):                       # a poll every second for 200 s: said once
            if m.fresh(item, now=1000.0 + i):
                m.note(item, now=1000.0 + i)
                said += 1
        self.assertEqual(said, 1)
        again = dict(item, key="waiting:7@999.0", text="Psst: tab 7 is waiting on you.")
        self.assertTrue(m.fresh(again, now=1300.0))                       # it started waiting again: news
        self.assertTrue(m.fresh(dict(item, text="other words"), now=1000.0 + 30 * 60))   # 30 min on

    def test_a_daily_line_once_a_day(self):
        import time
        m = self.n.Memory(self.path)
        tip = {"kind": "tip", "key": "tip:abc", "text": "Ctrl+Alt+Z zooms."}
        noon = time.mktime((2026, 11, 27, 12, 0, 0, 0, 0, -1))
        m.note(tip, now=noon)
        self.assertFalse(m.fresh(dict(tip, text="x"), now=noon + 6 * 3600))   # the same day: no
        self.assertTrue(m.fresh(dict(tip, text="x"), now=noon + 24 * 3600))   # tomorrow: yes
        self.assertFalse(m.fresh(dict(tip, key="tip:other"), now=noon + 24 * 3600))   # (its words: recent)

    def test_none_of_the_last_twenty(self):
        m = self.n.Memory(self.path)
        for i in range(25):
            m.note({"kind": "joke", "key": f"joke:{i}", "text": f"joke {i}"}, now=float(i))
        self.assertEqual(len(m.recent), 20)
        self.assertFalse(m.fresh({"kind": "joke", "key": "new", "text": "joke 24"}, now=99.0))
        self.assertTrue(m.fresh({"kind": "joke", "key": "new", "text": "joke 2"}, now=99.0))   # long ago

    def test_the_file_keeps_no_words(self):
        # with kitty-commands full a tab's name is its command line: never written to cat-said
        m = self.n.Memory(self.path)
        m.note({"kind": "waiting", "key": "waiting:7@1.0", "text": "Tab 7 “deploy --token=s3cret” is waiting."})
        m.note({"kind": "tip", "key": "tip:x", "text": "a secret tip"})
        with open(self.path, encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn("s3cret", raw)
        self.assertNotIn("secret tip", raw)
        self.assertFalse(self.n.Memory(self.path).fresh({"kind": "joke", "key": "j", "text": "a secret tip"}))
        with open(self.path, "w", encoding="utf-8") as f:     # a file from before kept the words
            f.write('{"said": {}, "recent": ["Tab 3 \u201cssh admin@host\u201d is waiting."]}')
        old = self.n.Memory(self.path)
        self.assertFalse(old.fresh({"kind": "joke", "key": "j", "text": "Tab 3 “ssh admin@host” is waiting."}))
        old.note({"kind": "tip", "key": "tip:y", "text": "y"})
        with open(self.path, encoding="utf-8") as f:
            self.assertNotIn("admin", f.read())                   # gone with the next write

    def test_it_remembers_over_a_restart(self):
        m = self.n.Memory(self.path)
        m.note({"kind": "tip", "key": "tip:x", "text": "a tip"})
        m2 = self.n.Memory(self.path)
        self.assertFalse(m2.fresh({"kind": "tip", "key": "tip:x", "text": "other"}))
        self.n.Memory(os.path.join(self.tmp.name, "missing", "file"))      # nothing there: no error

    def test_next_walks_forward_and_never_loops(self):
        items = [{"key": k} for k in ("waiting:7", "done:6", "quest:x", "tip:a", "joke:b")]
        shown, sel, seen = {"waiting:7"}, 0, ["waiting:7"]
        for _ in range(20):                           # many presses of Next
            nxt = self.n.next_line(items, sel, shown)
            if nxt < 0:
                break
            sel = nxt
            shown.add(items[sel]["key"])
            seen.append(items[sel]["key"])
        self.assertEqual(seen, [i["key"] for i in items])               # each once, in order
        self.assertEqual(self.n.next_line(items, sel, shown), -1)       # then "That's all"
        self.assertIn("That's all", self.n.ALL_SAID["text"])


if __name__ == "__main__":
    unittest.main()
