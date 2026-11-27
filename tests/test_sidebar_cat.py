#!/usr/bin/env python3
"""Unit tests for the drawn cat in tab_bar.py (Nine, in the sidebar), against the fake kitty of
test_tab_bar.py and a fake sidebar Screen that records what is fed to its parser: only quiet
graphics commands ever, every frame kept alive, the cat put back after a redraw, where it goes when
the tabs leave room (or don't), clicks, the night nap, the fall-backs, and saying each thing once.
    python3 -m unittest discover -s tests"""
import os
import sys
import time
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_tab_bar import LIGHT_THEME, FakeTab, FakeTabManager, FakeWindow, TabBarCase   # noqa: E402
from unittest import mock   # noqa: E402

R = types.SimpleNamespace


class FakeGrman:
    def __init__(self):
        self.ids = set()

    def image_for_client_id(self, iid):
        return {"id": iid} if iid in self.ids else None

    @property
    def image_count(self):
        return len(self.ids)


class FakeScreen:
    def __init__(self, lines=38, columns=31):
        self.lines, self.columns = lines, columns
        self.cursor = R(x=0, y=0, bg=0, fg=0, reset_display_attrs=lambda: None)
        self.grman = FakeGrman()
        self.fed = []

    def restore_scrollback(self, data):
        import re
        self.fed.append(data)
        for m in re.finditer(rb"a=t,[^;\x1b]*?i=(\d+)", data):
            self.grman.ids.add(int(m.group(1)))

    def erase_in_line(self, *a):
        pass


def ext(tab_id, start, end):
    return R(tab_id=tab_id, y=R(start=start, end=end))


def bar(extents, lines=38, columns=31, wid=1):
    return R(screen=FakeScreen(lines, columns), tab_extents=extents, cell_width=10, cell_height=20,
             window_geometry=R(left=0, top=0, right=columns * 10, bottom=lines * 20), os_window_id=wid,
             laid_out_once=True, tab_bar_align="start", max_tab_title_lines=2,
             draw_data=R(default_bg=0x110e18))


def sidebar(n_tabs=5, lines=38):
    """A search row, n tabs of 2 lines with a blank line between, "+ New tab" (2 lines)."""
    e, row = [ext(-2, 0, 0)], 2
    for i in range(n_tabs):
        e.append(ext(i + 1, row, row + 1))
        row += 3
    e.append(ext(-1, row, row + 1))
    return bar(e, lines)


class CatCase(TabBarCase):
    def setUp(self):
        super().setUp()
        tb = self.tb
        tb._internals["ok"] = True                    # (the fake kitty has no Screen: say it can)
        self.fdt = sys.modules["kitty.fast_data_types"]


class OnlyQuietGraphics(CatCase):
    """Nothing but our own quiet graphics commands may reach the sidebar's parser (a reply would be
    typed into the borrowed window's program; a BEL would ask the desktop for attention)."""
    def test_what_passes_and_what_doesnt(self):
        tb = self.tb
        ok = tb._gfx("a=p,i=4200,p=7,r=4,X=3,Y=5,z=1,C=1")
        self.assertTrue(tb._gfx_only(ok))
        big = tb._gfx("a=t,f=100,i=4200", os.urandom(9000))
        self.assertGreater(big.count(b"\x1b_G"), 2)                 # chunked
        self.assertTrue(tb._gfx_only(big))
        for bad in (b"\x07", b"\x1b[2J", b"\x1b]0;title\x07", ok + b"\x07", b"\x1b_Ga=p,i=1\x1b\\",
                    b"\x1b_Ga=p,i=1,q=1\x1b\\", big[:-40], ok.replace(b",q=2", b"") + ok, b"",
                    b"\x1b_Ga=t,i=1,q=2,m=1;AAAA\x1b\\\x1b_Ga=p,m=0;AAAA\x1b\\", b"\x1b_Gx\x1b\\"):
            self.assertFalse(tb._gfx_only(bad), bad[:40])
        s = FakeScreen()
        with self.assertRaises(ValueError):
            tb._cat_feed(s, ok + b"\x07")
        self.assertEqual(s.fed, [])


class WhereItGoes(CatCase):
    def test_floor_when_the_tabs_leave_room(self):
        tb = self.tb
        b = sidebar(5)                                              # rows 0..19 used of 38
        self.assertEqual(tb._cat_choose(b, tb._cat_state(b), 0), ("floor", 0))

    def test_the_blank_lines_go_before_the_floor(self):
        tb = self.tb
        b = sidebar(11)                                             # 25 rows and 12 blank lines: 37 of 38
        mode, pad = tb._cat_choose(b, tb._cat_state(b), 0)
        self.assertEqual((mode, pad), ("floor", 4))                 # without the blank lines: room for 4
        pads = tb._pad_entries(b, (R(tab_id=-1, title="x", _replace=lambda **k: R(**k)),), 4)
        self.assertEqual(sum(p.title.count("\n") + 1 for p in pads), 4)
        self.assertTrue(all(p.tab_id <= tb.PAD_ID for p in pads))

    def test_small_or_the_face_when_full(self):
        tb = self.tb
        b = sidebar(16)                                             # no room for 4 rows even without gaps
        self.assertEqual(tb._cat_choose(b, tb._cat_state(b), 0), ("small", 0))
        self.assertEqual(tb._cat_choose(b, tb._cat_state(b), 3), ("small", 0))     # tabs hidden
        b.tab_extents[-1] = ext(-1, 50, 50)                         # "+ New tab" one line (quests off)
        self.assertEqual(tb._cat_choose(b, tb._cat_state(b), 3), ("text", 0))

    def test_off_and_the_fall_backs(self):
        tb = self.tb
        b = sidebar(5)
        open(self.kitty_path("cat-off"), "w").close()
        self.assertEqual(tb._cat_choose(b, tb._cat_state(b), 0), ("off", 0))
        os.remove(self.kitty_path("cat-off"))
        tb._internals["ok"] = None                                  # the fake kitty has no Screen
        self.assertFalse(tb._cat_possible())
        self.assertEqual(tb._cat_choose(b, tb._cat_state(b), 0), ("text", 0))
        tb._internals["ok"] = True
        tb._cat_state(b)["failed"] = True                           # kitty took no pictures
        self.assertEqual(tb._cat_choose(b, tb._cat_state(b), 0), ("text", 0))

    def test_the_frame_size_is_never_scaled_up(self):
        tb = self.tb
        for ch in range(10, 120):
            rows = tb._cat_rows(ch)
            self.assertLessEqual(rows * ch, 384)
            self.assertGreaterEqual(tb._cat_size(rows * ch), rows * ch)
        self.assertEqual(tb._cat_size(80), 96)
        self.assertEqual(tb._cat_size(160), 192)


class PicturesStay(CatCase):
    """Every frame is sent once with a placement that's never drawn (so a redraw's erase can't free
    it); after each redraw the cat (and its mouth) is put back; it stays inside the sidebar."""
    def ready(self):
        tb = self.tb
        b = sidebar(5)
        tm = FakeTabManager([FakeTab()])
        tm.tab_bar = b
        self.boss.all_tab_managers = [tm]
        self.boss.active_tab_manager = tm
        st = tb._cat_state(b)
        st["mode"] = "floor"
        tb._cat_settle(b, st)
        b._vye_cat_wid, b._vye_cat_screen = tm.tabs[0].windows[0].id, b.screen      # (adopted)
        self.boss.window_id_map = {b._vye_cat_wid: R(os_window_id=1)}
        self.assertTrue(tb._cat_ready(tm, b, st))
        return tm, b, st

    def test_upload_keep_alive_and_put_back(self):
        tb = self.tb
        tm, b, st = self.ready()
        sent = b"".join(b.screen.fed)
        ch = tb._ch()
        for name in ch.FRAMES + tuple(f"mouth-{m}" for m in ch.MOUTHS):
            iid = tb._cat_iid(name)
            self.assertIn(f"a=t,f=100,i={iid},q=2".encode(), sent)
            self.assertIn(f"a=p,U=1,i={iid},p={tb.KEEP_P},c=1,r=1,q=2".encode(), sent)   # kept alive
        b.screen.fed.clear()
        tb._cat_settle(b, st)                                       # a redraw: put back at once
        placed = b"".join(b.screen.fed)
        self.assertIn(f"a=p,i={tb._cat_iid('idle')},p={tb.BODY_P},r=4".encode(), placed)
        self.assertIn(f"a=p,i={tb._cat_iid('mouth-w')},p={tb.MOUTH_P},r=4".encode(), placed)   # its mouth over it
        b.screen.fed.clear()
        self.assertFalse(tb._cat_place(b, st))                      # nothing changed: nothing sent
        self.assertEqual(b.screen.fed, [])
        st["queue"] = [["blink", 1]]
        self.assertTrue(tb._cat_place(b, st))
        swap = b"".join(b.screen.fed)
        self.assertLess(swap.index(f"a=p,i={tb._cat_iid('blink')}".encode()),
                        swap.index(f"a=d,d=i,i={tb._cat_iid('idle')}".encode()))       # new, then old off

    def test_it_stays_inside_the_sidebar(self):
        tb = self.tb
        tm, b, st = self.ready()
        g = st["geom"]
        self.assertEqual(st["y"], g["floor_y"])
        self.assertEqual(g["floor_y"] + g["px"], b.screen.lines * 20)    # its feet on the sidebar's bottom
        spot = tb._visit_spot(b, st, 3)
        self.assertIsNotNone(spot)
        self.assertLessEqual(spot[0] + g["px"], g["width"])          # all of it inside (no peeking)
        st["x"] = 10 ** 6
        tb._cat_settle(b, st)
        self.assertLessEqual(st["x"] + g["px"], g["width"])

    def test_asleep_at_night_awake_to_talk(self):
        tb = self.tb
        tm, b, st = self.ready()
        tb._night = lambda: True
        tb._cat["quiet_since"] = time.monotonic()
        self.assertEqual(tb._cat_frame(st, time.monotonic()), "sleepy")
        st["bubble"] = {"items": [{"key": "x", "action": None}], "sel": 0}
        self.assertEqual(tb._cat_frame(st, time.monotonic()), "idle")   # talking: awake
        tb._night = lambda: False
        st["bubble"] = None
        self.assertEqual(tb._cat_frame(st, time.monotonic()), "idle")


class Clicks(CatCase):
    """The bubble is on top of everything, then the current tab's ×, then the cat, then the rest."""
    def test_what_a_click_lands_on(self):
        tb = self.tb
        b = sidebar(5)
        a = FakeTab()
        tm = FakeTabManager([a])
        tm.tab_bar, tm.active_tab = b, a
        b.tab_extents[1] = ext(a.id, 2, 3)
        st = tb._cat_state(b)
        st.update(mode="floor", geom={"px": 80, "width": 310, "cw": 10, "ch": 20, "floor_y": 680, "rows": 4,
                                      "height": 760, "size": 96, "lines": 38, "cols": 31},
                  x=200.0, y=20.0, shown=("s", "idle", "", 0, 0, 4))
        tb._buttons.setdefault("close_cols", {})[a.id] = 28
        tb._buttons.setdefault("close_row", {})[1] = 2
        self.assertEqual(tb._region(tm, 285, 45), ("close",))       # × beats the cat over it
        self.assertEqual(tb._region(tm, 240, 75), ("cat",))
        st["bubble"] = {"image": True, "placed": (0,), "at": (0.0, 30.0), "items": [{}], "sel": 0,
                        "spec": {"w": 300, "h": 100, "regions": [(270, 0, 300, 25, "quit"), (9, 60, 100, 85, "do")]}}
        self.assertEqual(tb._region(tm, 285, 40), ("bubble", "quit"))   # the bubble's × beats everything
        self.assertEqual(tb._region(tm, 50, 100), ("bubble", "do"))
        self.assertEqual(tb._region(tm, 150, 50), ("bubble", None))     # on it, between buttons: nothing
        self.assertIsNone(tb._region(tm, 50, 300))


class Readable(CatCase):
    """The bubble's words and buttons read in both themes (text 4.5:1), here and in the overlay."""
    def test_both_themes(self):
        tb = self.tb
        for theme in (tb.THEME_FALLBACK, LIGHT_THEME):
            with mock.patch.object(tb, "_theme", lambda t=theme: dict(t)):
                c = tb._bubble_colours()
            for fg in ("fg", "muted", "close"):
                self.assertGreaterEqual(tb._contrast(c[fg], c["bg"]), 4.5, (fg, theme is LIGHT_THEME))
            for chip in ("do", "next"):
                fill, ink = c[chip]
                self.assertGreaterEqual(tb._contrast(ink, fill), 4.5, (chip, theme is LIGHT_THEME))
            self.assertNotEqual(c["do"][0], c["next"][0])          # two kinds of button, two fills
        ch = tb._ch()
        for colors in ({"foreground": "#ebe7f2", "background": "#17141f", "active_tab_background": "#e67e00",
                        "active_tab_foreground": "#17141f", "selection_background": "#4a3f5f",
                        "selection_foreground": "#f2eff7"},
                       {"foreground": "#1c1a21", "background": "#f7f6f9", "active_tab_background": "#00525a",
                        "active_tab_foreground": "#ffffff", "selection_background": "#a9d0d4",
                        "selection_foreground": "#888888"}):          # (a pair too faint: swapped)
            chips = ch.theme_chips(colors)
            import re
            for name in ("do", "next"):
                nums = [int(x) for x in re.findall(r"\d+", chips[name])]
                fill, ink = tuple(nums[2:5]), tuple(nums[7:10])
                self.assertGreaterEqual(tb._contrast(ink, fill), 4.5, (name, colors["background"]))


class SaysItOnce(CatCase):
    """A tab that starts waiting is announced once: not again on the next polls, nor after the
    bubble closes; a new wait is news again."""
    def test_once_per_event(self):
        tb = self.tb
        b = sidebar(3)
        w = FakeWindow("blocked")
        t = FakeTab(w)
        tm = FakeTabManager([FakeTab(), t])
        tm.tab_bar = b
        self.boss.all_tab_managers = [tm]
        tb._prev_state[w.id] = "blocked"
        st = tb._cat_state(b)
        st["mode"] = "text"
        tb._cat["waiting_tab"] = t.id
        tb._blocked_since[t.id] = 100.0
        opened = 0
        for i in range(50):
            tb._cat_talk["last"] = -1e9                             # (no 3-minute gap in the way)
            tb._cat_speak_up(tm, b, st, ["waiting"], 1000.0 + i)
            if st["bubble"] is not None:
                opened += 1
                self.assertIn("waiting", st["bubble"]["items"][0]["key"])
                st["bubble"] = None
        self.assertEqual(opened, 1)
        tb._blocked_since[t.id] = 5000.0                            # it waits again later: news
        tb._cat_talk["last"] = -1e9
        tb._cat_speak_up(tm, b, st, ["waiting"], 6000.0)
        self.assertIsNotNone(st["bubble"])

    def test_quiet_when_told_or_typing(self):
        tb = self.tb
        b = sidebar(3)
        tm = FakeTabManager([FakeTab(FakeWindow("blocked"))])
        tm.tab_bar = b
        self.boss.all_tab_managers = [tm]
        st = tb._cat_state(b)
        st["mode"] = "text"
        with open(self.kitty_path("cat-talk"), "w") as f:
            f.write("off\n")
        tb._cat_speak_up(tm, b, st, ["waiting"], 1000.0)
        self.assertIsNone(st["bubble"])
        os.remove(self.kitty_path("cat-talk"))
        tb._cat_talk["typing"]["at"] = time.monotonic()             # you're typing
        tb._cat_speak_up(tm, b, st, ["waiting"], time.monotonic())
        self.assertIsNone(st["bubble"])

    def test_next_walks_forward_then_says_thats_all(self):
        tb = self.tb
        b = sidebar(3)
        tm = FakeTabManager([FakeTab()])
        tm.tab_bar = b
        self.boss.all_tab_managers = [tm]
        st = tb._cat_state(b)
        st["mode"] = "text"
        tb._cat_clicked(tm)
        self.assertIsNotNone(st["bubble"])
        keys = [tb._bubble_item(st["bubble"])["key"]]
        for _ in range(30):
            tb._bubble_do(tm, "next")
            keys.append(tb._bubble_item(st["bubble"])["key"])
            if keys[-1] == "all-said":
                break
        self.assertEqual(keys[-1], "all-said")
        self.assertEqual(len(keys[:-1]), len(set(keys[:-1])))         # nothing twice
        tb._bubble_close(tm, st)
        tb._cat_clicked(tm)                                         # again: today's lines were said
        again = [s["kind"] for s in st["bubble"]["items"]]
        self.assertTrue(all(k in ("hello", "waiting", "done", "error", "badge") for k in again), again)


if __name__ == "__main__":
    unittest.main()
