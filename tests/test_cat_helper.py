#!/usr/bin/env python3
"""Unit tests for config/cat-helper.py (the helper cat: Ctrl+Alt+C, a click on the sidebar's cat,
`ninelives cat`). A temp config and state folder, a pinned date and dice, no kitty, no terminal:
    python3 -m unittest discover -s tests          (or: python3 tests/test_cat_helper.py)"""
import base64
import datetime
import importlib.util
import io
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "..", "config")
HELPER = os.path.join(CONFIG, "cat-helper.py")
MAKE_CAT = os.path.join(HERE, "..", "scripts", "make-cat.py")
NOON = datetime.datetime(2026, 11, 26, 14, 0)          # a Thursday afternoon


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def plain(s: str) -> str:
    return re.sub("\x1b\\[[0-9;?]*[a-zA-Z]", "", s)


def tab(n, state="", name=None, active=False):
    return {"n": n, "id": 100 + n, "name": name or f"task {n}", "folder": "code/webapp", "state": state,
            "agent": "", "branch": "", "active": active}


class Dice:
    def __init__(self, *rolls):
        self.rolls = list(rolls)

    def random(self):
        return self.rolls.pop(0) if self.rolls else 0.99

    def choice(self, seq):
        return seq[0]


class HelperCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conf = os.path.join(self.tmp.name, "kitty")
        self.state = os.path.join(self.tmp.name, "state")
        os.makedirs(self.conf)
        os.makedirs(self.state)
        env = {k: v for k, v in os.environ.items() if k not in ("KITTY_LISTEN_ON", "NINELIVES_QUIET")}
        env.update(HOME=self.tmp.name, KITTY_CONFIG_DIRECTORY=self.conf, NINELIVES_STATE=self.state)
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()
        self.h = load(HELPER, "nl_cat_helper")
        self.pool = ["tip one", "tip two", "tip three", "tip four"]

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def say(self, tabs=(), now=NOON):
        return self.h.suggestions(list(tabs), now, self.state, self.conf, self.h.load_hidden(self.state), self.pool)

    def kinds(self, items):
        return [s["kind"] for s in items]


class WhatItSays(HelperCase):
    def test_a_waiting_tab_comes_first_and_enter_goes_there(self):
        tabs = [tab(1, active=True), tab(5, "working"), tab(6, "done", "Write release notes"),
                tab(7, "blocked", "Migrate database schema to v2"), tab(8, "error", "Deploy to staging")]
        items = self.say(tabs)
        self.assertEqual(self.kinds(items), ["waiting", "error", "done", "tip", "joke", "word"])
        self.assertEqual(items[0]["text"], "Tab 7 “Migrate database schema to v2” is waiting for you. Go there?")
        self.assertEqual(items[0]["action"], ("focus", 107))
        self.assertEqual(items[1]["text"], "Tab 8 “Deploy to staging” stopped with an error. Go there?")
        self.assertEqual(items[2]["text"], "Tab 6 “Write release notes” finished. Go there?")
        self.assertFalse(items[0]["hideable"])          # about your tabs: never hidden

    def test_several_tabs_are_counted_and_another_tab_goes_first(self):
        tabs = [tab(1, "blocked", "here", active=True), tab(3, "blocked", "API"), tab(9, "blocked")]
        first = self.say(tabs)[0]
        self.assertEqual(first["text"], "Three tabs are waiting for you. First: tab 3 “API”. Go there?")
        self.assertEqual(first["action"], ("focus", 103))
        alone = self.say([tab(1, "blocked", "here", active=True)])[0]
        self.assertEqual(alone["text"], "This tab “here” is waiting for you. Have a look?")

    def test_finished_tabs_are_named_then_numbered(self):
        tabs = [tab(1, active=True)] + [tab(n, "done", f"job {n}") for n in (5, 8, 9, 10, 11)]
        done = self.say(tabs)[0]
        self.assertEqual(done["text"], "Five tabs finished: tab 5 “job 5”, 8, 9 and 2 more. Go to tab 5?")
        two = self.say([tab(1, active=True), tab(2, "done", "a"), tab(4, "done", "b")])[0]
        self.assertEqual(two["text"], "Two tabs finished: tab 2 “a” and 4. Go to tab 2?")

    def test_nothing_pending_says_hello_and_how_things_stand(self):
        items = self.say([tab(1, active=True), tab(2, "working"), tab(3, "working")])
        self.assertEqual(items[0]["kind"], "hello")
        self.assertEqual(items[0]["text"], "Good afternoon! It's Thursday, November 26. Nothing needs you right now. "
                                           "Two tabs are working.")
        self.assertIsNone(items[0]["action"])
        night = self.say([], datetime.datetime(2026, 11, 26, 23, 30))[0]["text"]
        self.assertTrue(night.startswith("Good night!"), night)

    def test_the_days_lines_stay_all_day_and_change_the_next(self):
        morning = self.say(now=datetime.datetime(2026, 11, 26, 6, 1))
        evening = self.say(now=datetime.datetime(2026, 11, 26, 23, 59))
        pick = lambda items: [s["key"] for s in items if s["kind"] in ("tip", "joke", "word")]
        self.assertEqual(pick(morning), pick(evening))
        days = {tuple(pick(self.say(now=NOON + datetime.timedelta(days=d)))) for d in range(6)}
        self.assertGreater(len(days), 3)

    def test_dont_suggest_this_again(self):
        tip = next(s for s in self.say() if s["kind"] == "tip")
        self.assertTrue(tip["hideable"])
        self.h.hide(self.state, tip["key"])
        for d in range(30):                              # never again, whatever the day
            again = [s for s in self.say(now=NOON + datetime.timedelta(days=d)) if s["kind"] == "tip"]
            self.assertTrue(again)
            self.assertNotEqual(again[0]["key"], tip["key"])
        for t in self.pool:                              # all hidden: no tip at all
            self.h.hide(self.state, self.h.key_of("tip", t))
        self.assertNotIn("tip", self.kinds(self.say()))

    def test_every_joke_and_word_fits_the_bubble(self):
        for x in self.h.JOKES + tuple(f"{w}: {m}" for w, m in self.h.WORDS):
            self.assertLessEqual(len(self.h.wrap(x, 50 - 4, 99)), self.h.TEXT_LINES, x)
            self.assertNotIn("It looks like", x)      # (its own voice)


class Quests(HelperCase):
    """Badges and the next quest come from what tab_bar.py writes (quests.txt), by its own code."""
    def write_quests(self, earned):
        ttb = sys.modules.get("test_tab_bar") or load(os.path.join(HERE, "test_tab_bar.py"), "test_tab_bar")
        case = ttb.TabBarCase("run")
        case.setUp()
        try:
            for qid, day in earned.items():
                case.tb._earned[qid] = day
            case.tb._write_quest_files()
            with open(os.path.join(os.environ["NINELIVES_STATE"], "quests.txt"), encoding="utf-8") as f:
                text = f.read()
            nxt = case.tb._next_quest()
        finally:
            case.tearDown()
        with open(os.path.join(self.state, "quests.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        return nxt

    def test_a_badge_earned_today_and_the_next_quest(self):
        nxt = self.write_quests({"zoom": "2026-11-26", "split": "2026-11-20"})
        items = self.say()
        badge = [s for s in items if s["kind"] == "badge"]
        self.assertEqual(len(badge), 1)                   # today's only
        self.assertEqual(badge[0]["text"], "You earned the Zoom Lens badge today: ★ 2 of 16, rank Kitten.")
        quest = next(s for s in items if s["kind"] == "quest")
        self.assertEqual(quest["text"], f"{nxt[3].rstrip('.')}. Use it once to earn the {nxt[1]} badge.")
        self.assertEqual(quest["action"], ("help",))
        self.assertEqual(self.kinds(items)[:3], ["hello", "badge", "quest"])
        # don't suggest the quest again: hidden until the next quest comes round
        self.h.hide(self.state, quest["key"])
        self.assertNotIn("quest", self.kinds(self.say()))

    def test_quests_off_hides_them(self):
        self.write_quests({"zoom": "2026-11-26"})
        open(os.path.join(self.conf, "quests-off"), "w").close()
        self.assertEqual(self.kinds(self.say()), ["hello", "tip", "joke", "word"])


class TheTips(HelperCase):
    def test_the_tip_pool_is_tips_sh_s(self):
        out = subprocess.run(["bash", "-c", 'eval "$(sed -n "/^_kitty_tips=(/,/^)/p" "$1")"; '
                              'printf "%s\\n" "${_kitty_tips[@]}"', "-", os.path.join(CONFIG, "tips.sh")],
                             capture_output=True, text=True, check=True).stdout.splitlines()
        self.assertGreater(len(out), 20)
        self.assertEqual(self.h.tips(os.path.join(CONFIG, "tips.sh")), out)
        self.assertTrue(any('"' in t for t in out))     # an escaped quote, read as bash reads it

    def test_one_of_them_tells_you_about_the_helper(self):
        self.assertTrue(any("Ctrl+Alt+C" in t for t in self.h.tips(os.path.join(CONFIG, "tips.sh"))))


class Pictures(HelperCase):
    def test_the_graphics_protocol_chunks(self):
        data = bytes(range(256)) * 40                      # 10240 bytes: 13656 base64, four chunks
        s = self.h.graphics("a=t,f=100,i=3", data)
        parts = re.findall("\x1b_G([^;]*);([^\x1b]*)\x1b\\\\", s)
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0][0], "a=t,f=100,i=3,q=2,m=1")
        self.assertEqual([p[0] for p in parts[1:]], ["m=1", "m=1", "m=0"])
        self.assertTrue(all(len(p[1]) <= 4096 for p in parts))
        self.assertTrue(all(len(p[1]) % 4 == 0 for p in parts[:-1]))
        self.assertEqual(base64.b64decode("".join(p[1] for p in parts)), data)
        self.assertEqual(self.h.graphics("a=d,d=A"), "\x1b_Ga=d,d=A,q=2\x1b\\")
        one = self.h.graphics("a=t,i=1", b"x" * 30)
        self.assertEqual(one.count("\x1b_G"), 1)
        self.assertIn("m=0;", one)

    def test_every_frame_is_shipped_small(self):
        mk = load(MAKE_CAT, "nl_make_cat")                 # (no cairo needed to read its lists)
        self.assertEqual(tuple(mk.FRAMES), self.h.FRAMES)
        self.assertEqual(tuple(mk.SIZES), self.h.SIZES)
        for size in self.h.SIZES:
            for name in self.h.FRAMES:
                path = os.path.join(CONFIG, "cat", str(size), name + ".png")
                with open(path, "rb") as f:
                    head = f.read(32)
                self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n", path)
                self.assertEqual(struct.unpack(">II", head[16:24]), (size, size), path)
                self.assertLess(os.path.getsize(path), 8000, path)
        ids = {self.h.image_id(f, s) for f in self.h.FRAMES for s in self.h.SIZES}
        self.assertEqual(len(ids), len(self.h.FRAMES) * len(self.h.SIZES))

    def helper(self, *rolls):
        out = io.StringIO()
        h = self.h.Helper(out, self.conf, self.state, now=lambda: NOON, rng=Dice(*rolls))
        h.size = (77, 37, 10, 20)
        return h, out

    def test_frames_go_once_and_swap_in_place(self):
        h, out = self.helper()
        h.refresh([tab(1, active=True)])
        h.queue = []
        h.draw()
        first = out.getvalue()
        self.assertNotIn("\x1b[2J", first)               # it would free the frames kitty keeps
        self.assertIn(f"a=t,f=100,i={self.h.image_id('idle', 192)},q=2", first)
        self.assertIn(f"a=p,i={self.h.image_id('idle', 192)},p=7,r=10,C=1,q=2", first)
        out.truncate(0); out.seek(0)
        h.draw_cat()
        self.assertEqual(out.getvalue(), "")             # nothing changed: nothing written
        h.play("blink")
        h.draw_cat()
        blink = out.getvalue()
        self.assertLess(blink.index("a=p,i=" + str(self.h.image_id("blink", 192))),
                        blink.index(f"a=d,d=i,i={self.h.image_id('idle', 192)}"))   # new, then old off
        h.step()
        out.truncate(0); out.seek(0)
        h.draw_cat()
        back = out.getvalue()
        self.assertNotIn("a=t", back)                    # idle was sent before: only placed again
        self.assertIn(f"a=p,i={self.h.image_id('idle', 192)}", back)

    def test_without_its_frames_the_bubble_shows_alone(self):
        out = io.StringIO()
        h = self.h.Helper(out, self.conf, self.state, now=lambda: NOON, rng=Dice(),
                          cat_dir=os.path.join(self.tmp.name, "nowhere"))
        h.size = (77, 37, 10, 20)
        h.refresh([tab(1, active=True)])
        h.draw()
        self.assertEqual(h.lay["mode"], "alone")
        self.assertNotIn("\x1b_G", out.getvalue())
        self.assertIn("Hello", plain(out.getvalue()))

    def test_the_dice(self):
        h, _ = self.helper(0.1, 0.23, 0.5)
        h.refresh([])
        h.queue = []
        h.roll()
        self.assertEqual(h.frame(), "blink")
        h.queue = []
        h.roll()
        self.assertEqual(h.frame(), "wink")              # a fidget (Dice picks the first)
        h.queue = []
        h.roll()
        self.assertEqual(h.frame(), "idle")
        h.now = lambda: datetime.datetime(2026, 11, 26, 2, 0)
        self.assertEqual(h.frame(), "sleepy")            # at night, nothing waiting: it naps
        h.refresh([tab(2, "blocked")])
        h.queue = []
        self.assertEqual(h.frame(), "idle")              # ... but not while a tab needs you

    def test_it_reacts_to_your_tabs(self):
        h, _ = self.helper()
        h.refresh([tab(1, active=True), tab(2, "working")])
        h.queue = []
        h.sel = 2
        h.refresh([tab(1, active=True), tab(2, "working"), tab(3, "blocked", "API")])
        self.assertEqual(h.frame(), "surprised")
        self.assertEqual(h.items[h.sel]["kind"], "waiting")
        h.queue = []
        h.refresh([tab(1, active=True), tab(2, "done"), tab(3, "blocked", "API")])
        self.assertEqual(h.frame(), "hop-low")
        self.assertEqual(h.items[h.sel]["kind"], "waiting")   # still on what it was showing
        # on the word of the day when a tab finishes (a new line in front of it): still the word
        h.sel = next(i for i, s in enumerate(h.items) if s["kind"] == "word")
        h.queue = []
        h.refresh([tab(1, active=True), tab(2, "done"), tab(3, "blocked", "API"), tab(4, "done")])
        self.assertEqual(h.frame(), "hop-low")
        self.assertEqual(h.items[h.sel]["kind"], "word")
        h.refresh([tab(1, active=True), tab(2, "error"), tab(3, "blocked", "API"), tab(4, "done")])
        self.assertEqual(h.items[h.sel]["kind"], "word")      # an error: a flinch, the bubble stays


class Keys(HelperCase):
    def test_keys(self):
        c = self.h.command
        for k, want in (("\r", "do"), ("n", "next"), (" ", "next"), ("\x1b[C", "next"), ("p", "prev"),
                        ("\x1b[D", "prev"), ("d", "hide"), ("\x1b", "quit"), ("q", "quit"), ("x", None)):
            self.assertEqual(c(k), want, repr(k))
        got = list(self.h.keys("\x1b_Gi=1;OK\x1b\\n\x1b[C\x1b[<0;30;12M"))
        self.assertEqual(got[:2], ["n", "\x1b[C"])       # a graphics answer is never a key (nor Esc)
        self.assertEqual(got[2], ("mouse", 0, 30, 12, True))

    def test_clicks_hit_the_bubbles_buttons_and_the_cat(self):
        h = self.h
        items = h.suggestions([tab(1, active=True), tab(7, "blocked", "API")], NOON, self.state, self.conf,
                              set(), ["a tip"])
        lay = h.layout(77, 37, 10, 20)
        canvas, cat, regions = h.screen(items, 0, 77, 37, lay)
        found = {r[3]: r for r in regions if r[0] != "cat"}
        self.assertEqual(set(found), {"do", "next", "quit"})
        for cmd, (row, c0, c1, _) in found.items():
            line = plain(canvas[row])
            self.assertEqual(h.hit(regions, c0, row), cmd)
            self.assertEqual(h.hit(regions, c1, row), cmd)
            word = {"do": "Go there", "next": "Next", "quit": "Close"}[cmd]
            self.assertEqual(line[c0 - 1:c0 - 1 + len(word) + 1].strip(), word)
        self.assertEqual(h.hit(regions, cat[0] + 2, cat[1] + 2), "pet")
        self.assertIsNone(h.hit(regions, 1, 1))

    def test_what_a_command_does(self):
        out = io.StringIO()
        h = self.h.Helper(out, self.conf, self.state, now=lambda: NOON, rng=Dice())
        h.refresh([tab(1, active=True), tab(4, "blocked", "API")])
        self.assertEqual(h.act("do"), "focus:104")
        self.assertEqual(h.act("hide"), "")              # about a tab: stays, and says why
        self.assertIn("stays", h.notice)
        self.assertFalse(os.path.exists(os.path.join(self.state, "cat-helper-hidden")))
        h.act("next")
        tip = h.items[h.sel]
        self.assertEqual(h.act("do"), "")                # nothing to do: the next one
        self.assertEqual(h.sel, 2)
        h.act("prev")
        self.assertEqual(h.items[h.sel], tip)
        h.act("hide")
        self.assertIn(tip["key"], self.h.load_hidden(self.state))
        self.assertNotIn(tip["key"], [s["key"] for s in h.items])
        self.assertEqual(h.act("quit"), "quit")


class Layout(HelperCase):
    def test_it_fits_every_window(self):
        h = self.h
        items = h.suggestions([tab(1, active=True), tab(7, "blocked", "A tab with a rather long name indeed")],
                              NOON, self.state, self.conf, set(), ["a tip"])
        modes = set()
        for cols in (20, 30, 40, 50, 77, 120, 200):
            for lines in (6, 10, 16, 24, 37, 60):
                for cw, ch in ((10, 20), (8, 17), (20, 40)):
                    lay = h.layout(cols, lines, cw, ch)
                    modes.add(lay["mode"])
                    for sel in range(len(items)):
                        canvas, cat, _ = h.screen(items, sel, cols, lines, lay, "Got it.")
                        self.assertTrue(all(1 <= y <= lines for y in canvas), (cols, lines))
                        for y, text in canvas.items():
                            self.assertLessEqual(h.cells(plain(text)), cols, (cols, lines, y, plain(text)))
                        if cat:
                            left, top, rows, ccols = cat
                            self.assertLessEqual(left + ccols - 1, cols)
                            self.assertLess(top + rows - 1, lines)   # above the footer
        self.assertEqual(modes, {"side", "stacked", "alone"})


class Toggle(HelperCase):
    def test_which_windows_are_helpers(self):
        conf_dir = os.path.join(self.tmp.name, "kc")
        os.makedirs(conf_dir)
        open(os.path.join(conf_dir, "kitty.conf"), "w").close()
        h = self.h
        self.assertTrue(h._is_helper(["python3", os.path.join(conf_dir, "cat-helper.py")]))
        self.assertTrue(h._is_helper(["sh", "-c", 'exec python3 "${KITTY_CONFIG_DIRECTORY:-x}/cat-helper.py"']))
        self.assertFalse(h._is_helper(["python3", os.path.join(conf_dir, "cat-helper.py"), "say"]))
        self.assertFalse(h._is_helper(["vim", "cat-helper.py"]))
        self.assertFalse(h._is_helper(["bash"]))
        data = [{"tabs": [
            {"windows": [{"id": 1, "cmdline": ["bash"]},
                         {"id": 2, "cmdline": ["sh", "-c", 'exec python3 "${KITTY_CONFIG_DIRECTORY:-x}/cat-helper.py"'],
                          "is_self": True}]},
            {"windows": [{"id": 3, "cmdline": ["sh", "-c", 'exec python3 "${KITTY_CONFIG_DIRECTORY:-x}/cat-helper.py"']}]}]}]
        self.assertEqual(h.other_helpers(data), [3])
        self.assertEqual(h.other_helpers(data, here_only=True), [])
        data[0]["tabs"][0]["windows"].insert(1, dict(data[0]["tabs"][1]["windows"][0], id=4))
        self.assertEqual(h.other_helpers(data, here_only=True), [4])
        with mock.patch.object(h, "kitty") as k:
            self.assertTrue(h.toggle_off_others(data))
            self.assertEqual(sorted(c.args[2] for c in k.call_args_list), ["id:3", "id:4"])

    def test_run_from_a_shell_its_own_tab_isnt_working(self):
        h = self.h
        me = {"id": 2, "is_self": True, "is_active": True, "title": "~", "cwd": "/w/proj", "cmdline": ["bash"],
              "foreground_processes": [{"cmdline": ["python3", "/k/cat-helper.py"]}], "program_status": []}
        busy = {"id": 3, "is_active": True, "title": "npm run build", "cwd": "/w/proj", "cmdline": ["bash"],
                "foreground_processes": [{"cmdline": ["npm", "run", "build"]}], "program_status": []}
        data = [{"is_focused": True, "tabs": [
            {"id": 1, "is_active": True, "title": "~", "windows": [me]},
            {"id": 5, "is_active": False, "title": "npm run build", "windows": [busy]}]}]
        rows = h.own_tab_state(h._finder.rows(data), data)
        self.assertEqual([r["state"] for r in rows], ["", "working"])
        hello = h.suggestions(rows, NOON, self.state, self.conf, set(), [])[0]["text"]
        self.assertTrue(hello.endswith("Nothing needs you right now. One tab is working."), hello)

    def test_without_a_terminal_it_prints(self):
        r = subprocess.run([sys.executable, HELPER], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env=os.environ, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"^Hello: Good (morning|afternoon|evening|night)!")
        self.assertIn("Tip of the day: ", r.stdout)


if __name__ == "__main__":
    unittest.main()
