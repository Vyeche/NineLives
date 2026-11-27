#!/usr/bin/env python3
"""Unit tests for config/tab_bar.py that need no kitty, no display and no sound.

tab_bar.py is loaded against small fake kitty modules (below), with HOME and NINELIVES_STATE in a
temp folder, so nothing touches your real config, badges or speakers. Run:
    python3 -m unittest discover -s tests -v          (or: python3 tests/test_tab_bar.py)
The fake kitty leaves out the internals tab_bar.py patches (TabManager, TabBar, …), which also checks
the promise that it degrades safely when a kitty update renames them.
"""
import importlib.util
import os
import random
import sys
import tempfile
import time
import types
import unicodedata
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TAB_BAR = os.path.join(HERE, "..", "config", "tab_bar.py")


# ---- a fake kitty ---------------------------------------------------------------------------
def _wcswidth(s: str) -> int:
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


class FakeStatus:
    def __init__(self, state=None):
        self.state = state

    def as_list(self):
        return [{"state": self.state}] if self.state else []


class FakeWindow:
    _ids = iter(range(1000, 10**6))

    def __init__(self, state=None):
        self.id = next(self._ids)
        self.program_status = FakeStatus(state)
        self.child = types.SimpleNamespace(child_fd=-1, pid=-1)   # tcgetpgrp fails: no plain command


class FakeTab:
    _ids = iter(range(1, 10**6))

    def __init__(self, *windows):
        self.id = next(self._ids)
        self.windows = list(windows) or [FakeWindow()]
        self.active_window = self.windows[0]

    def __iter__(self):
        return iter(self.windows)


class FakeTabManager:
    def __init__(self, tabs, os_window_id=1):
        self.tabs = tabs
        self.os_window_id = os_window_id
        self.active_tab = tabs[0] if tabs else None
        self.dirty = 0

    def __iter__(self):
        return iter(self.tabs)

    def mark_tab_bar_dirty(self):
        self.dirty += 1


class FakeBoss:
    def __init__(self):
        self.all_tab_managers = []


def fake_kitty(boss, focused=lambda: 1):
    k = types.ModuleType("kitty")
    k.__path__ = []
    mods = {"kitty": k}
    for name in ("boss", "fast_data_types", "tab_bar", "tabs", "constants", "utils"):
        m = types.ModuleType("kitty." + name)
        setattr(k, name, m)
        mods["kitty." + name] = m
    for mod, attrs in {
        "kitty.boss": {"get_boss": lambda: boss},
        "kitty.fast_data_types": {"add_timer": lambda fn, interval, repeat: 1,
                                  "remove_timer": lambda tid: None, "wcswidth": _wcswidth,
                                  "current_focused_os_window_id": focused,
                                  "wakeup_main_loop": lambda: None},
        "kitty.constants": {"is_wayland": lambda: True},
    }.items():
        for name, value in attrs.items():
            setattr(mods[mod], name, value)
    return mods


class Fmt:
    """Stand-in for kitty's tab-bar formatter: colours print as markers, e.g. <fg3>."""
    class _Colours:
        def __init__(self, kind):
            self.kind = kind

        def __getattr__(self, name):
            return f"<{self.kind}{name.replace('color', '')}>"
    fg = _Colours("fg")
    bg = _Colours("bg")
    bold, nobold = "<b>", "</b>"


LIGHT_THEME = {          # cosmic-light.conf's
    "background": (0xf7, 0xf6, 0xf9), "foreground": (0x1c, 0x1a, 0x21),
    "inactive_tab_background": (0xe2, 0xe1, 0xe6), "inactive_tab_foreground": (0x55, 0x51, 0x5c),
    "active_tab_background": (0x00, 0x52, 0x5a), "active_tab_foreground": (0xff, 0xff, 0xff),
    "selection_background": (0xa9, 0xd0, 0xd4), "selection_foreground": (0x1a, 0x18, 0x1e),
    "color3": (0x80, 0x62, 0x2a), "color7": (0x5b, 0x57, 0x63),
}


def rgb_pairs(sgr: str) -> tuple:
    """(background, foreground) of a "\x1b[48;2;r;g;bm\x1b[38;2;r;g;bm" pair."""
    import re
    bg = tuple(int(x) for x in re.search(r"48;2;(\d+);(\d+);(\d+)", sgr).groups())
    fg = tuple(int(x) for x in re.search(r"38;2;(\d+);(\d+);(\d+)", sgr).groups())
    return bg, fg


class Dice:
    """The cat's dice, scripted: random() hands out `rolls` in turn (then 0.99: no move), choice()
    takes the `pick`-th of what it is offered."""
    def __init__(self, *rolls, pick=0):
        self.rolls, self.pick = list(rolls), pick

    def random(self):
        return self.rolls.pop(0) if self.rolls else 0.99

    def choice(self, seq):
        return seq[self.pick % len(seq)]


# ---- loading tab_bar.py fresh for every test --------------------------------------------------
class TabBarCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = self.tmp.name
        os.makedirs(os.path.join(home, ".config", "kitty", "sounds"))
        for s in ("done", "done-2", "done-3", "needs-you", "error", "badge", "rank", "drop"):
            open(os.path.join(home, ".config", "kitty", "sounds", s + ".oga"), "w").close()
        self.env = mock.patch.dict(os.environ, {"HOME": home, "NINELIVES_STATE": os.path.join(home, "state"),
                                                "KITTY_CONFIG_DIRECTORY": os.path.join(home, ".config", "kitty")})
        self.env.start()
        self.boss = FakeBoss()
        self.focused = 1
        self.modules = mock.patch.dict(sys.modules, fake_kitty(self.boss, lambda: self.focused))
        self.modules.start()
        self.popen = mock.patch("subprocess.Popen")
        self.played = self.popen.start()
        spec = importlib.util.spec_from_file_location("nl_tab_bar", TAB_BAR)
        assert spec is not None and spec.loader is not None
        self.tb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tb)
        self.tb.IS_MACOS = False        # the Linux paths, on any system (class MacOS tries the other)
        self.played.reset_mock()
        self.tb._last_sound.update(at=-99.0, priority=-1)
        # the cat's clock and dice: daytime, and dice that never start a move (CatMoves sets its own),
        # so no test depends on the hour it runs at or on luck
        self.real_night = self.tb._night
        self.tb._night = lambda: False
        self.tb._cat_rng = Dice()

    def tearDown(self):
        self.popen.stop()
        self.modules.stop()
        self.env.stop()
        self.tmp.cleanup()

    def kitty_path(self, name):
        return os.path.join(self.tmp.name, ".config", "kitty", name)

    def sounds(self):
        """[(file, volume)] of every paplay started so far."""
        out = []
        for call in self.played.call_args_list:
            args = call.args[0]
            if args and args[0] == "paplay":
                out.append((os.path.basename(args[2]), int(args[1].split("=")[1])))
        return out

    def window(self, *tabs, active=0):
        tm = FakeTabManager(list(tabs))
        tm.active_tab = tabs[active]
        self.boss.all_tab_managers = [tm]
        return tm


class Loading(TabBarCase):
    def test_loads_without_kitty_internals(self):
        # TabManager, TabBar, Boss.dispatch_action … are missing from the fake kitty: every patch
        # must skip itself instead of raising (PRODUCT.md: survive kitty updates).
        self.assertTrue(hasattr(self.tb, "draw_title"))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "state", "quests.txt")))

    def test_draw_title_falls_back_instead_of_raising(self):
        self.assertEqual(self.tb.draw_title({"index": 3, "title": "x"}), "  3    x")



class ShortWindow(TabBarCase):
    """Not every tab fits: keep "+ New tab", the active tab and tabs waiting for you."""
    def entries(self, n, active):
        T = lambda tid, act=False: types.SimpleNamespace(tab_id=tid, is_active=act)
        return [T(i + 1, i == active) for i in range(n)] + [T(-1)]        # -1: "+ New tab"

    def ids(self, kept):
        return [t.tab_id for t in kept]

    def test_everything_fits(self):
        d = self.entries(3, 0)
        self.assertEqual(self.tb._pick_tabs(d, 4), d)

    def test_new_tab_active_and_waiting_tabs_stay_in_order(self):
        kept = self.tb._pick_tabs(self.entries(12, 0), 5, urgent={11}, notable={9})
        self.assertEqual(self.ids(kept), [1, 2, 9, 11, -1])

    def test_fills_with_the_tabs_nearest_the_active_one(self):
        kept = self.tb._pick_tabs(self.entries(12, 7), 4)
        self.assertEqual(self.ids(kept), [7, 8, 9, -1])

    def test_hidden_numbers_read_as_ranges(self):
        self.assertEqual(self.tb._number_ranges([10, 1, 2, 3, 7]), "1\u20133, 7, 10")

    def test_real_number_is_drawn_for_a_hidden_list(self):
        sys.modules["kitty.tab_bar"]._vye_tab_numbers = {5: 11}
        self.assertEqual(self.tb._tab_number({"tab_id": 5, "index": 2}), 11)
        self.assertEqual(self.tb._tab_number({"tab_id": 6, "index": 3}), 3)


class Coach(TabBarCase):
    """Clicking a tab with the mouse teaches Alt+N (until the Jumper badge), without nagging."""
    def click(self, tab_index, active=0):
        tabs = [FakeTab() for _ in range(3)]
        tm = self.window(*tabs, active=active)
        tm.tabs_to_be_shown_in_tab_bar = tabs
        tm.tab_bar = types.SimpleNamespace(tab_id_at=lambda x, y: tabs[tab_index].id)
        fdt = sys.modules["kitty.fast_data_types"]
        fdt.GLFW_MOUSE_BUTTON_LEFT, fdt.GLFW_PRESS = 0, 1
        self.tb._tab_clicked(tm, 0, 0, 0, 1)
        return self.tb._quest_line()

    def test_click_shows_the_key(self):
        self.assertIn("Alt+3 also gets here", self.click(2))

    def test_not_again_right_away(self):
        self.click(2)
        self.tb._coach["until"] = 0
        self.assertNotIn("gets here", self.click(1))

    def test_quiet_once_jumper_is_earned_or_on_the_active_tab(self):
        self.assertNotIn("gets here", self.click(0, active=0))
        self.tb._earned["jump"] = "2026-11-22"
        self.assertNotIn("gets here", self.click(2))


class QuestOfTheDay(TabBarCase):
    def test_rotates_daily_among_the_first_three_not_done(self):
        seen = []
        for day in range(6):
            with mock.patch.object(self.tb, "_day", lambda d=day: d):
                seen.append(self.tb._next_quest()[0])
        self.assertEqual(set(seen), {"split", "panes", "zoom"})
        self.assertNotEqual(seen[0], seen[1])

    def test_skips_earned_and_ends(self):
        self.tb._earned.update({q[0]: "x" for q in self.tb.QUESTS[:-1]})
        self.assertEqual(self.tb._next_quest()[0], self.tb.QUESTS[-1][0])
        self.tb._earned[self.tb.QUESTS[-1][0]] = "x"
        self.assertIsNone(self.tb._next_quest())


class Buttons(TabBarCase):
    """The search row on top (a field, then ⚠ ⚙ + as chips) and the × on the current tab."""
    def test_search_row_and_its_buttons(self):
        for blocked in (0, 2):
            self.tb._cat["blocked"] = blocked
            row = self.tb._visible(self.tb._search_row())
            self.assertTrue(row.startswith("  Search tabs "), row)    # the words alone: no ❯, no …
            self.assertNotIn("…", row)
            self.assertEqual(self.tb._cells(row), 30)
            self.assertEqual(row.index("+"), 28)                # in the current tab's × column
            cols = self.tb._buttons["cols"]
            for c0, c1, name in cols:
                part = row[c0:c1 + 1]
                self.assertIn({"search": "Search", "waiting": "⚠", "settings": "⚙", "new": "+"}[name], part, (name, part))
                if name != "search":
                    self.assertEqual(row[c0 + 1], self.tb.GLYPHS[name])   # sidebar.txt points at c0 + 1

    def test_field_and_chips_are_filled_and_readable_in_both_themes(self):
        for theme in (self.tb.THEME_FALLBACK, LIGHT_THEME):
            with mock.patch.object(self.tb, "_theme", lambda t=theme: dict(t)):
                c = self.tb._row_colours()
                text, _ = self.tb._row_layout(30, 2)
            for part in ("field", "chip", "warn", "pressed"):
                self.assertIn(c[part], text if part != "pressed" else c["pressed"])
                bg, fg = rgb_pairs(c[part])
                self.assertGreaterEqual(self.tb._contrast(fg, bg), 4.5, (part, theme is LIGHT_THEME))
            row_bg, _ = rgb_pairs(c["row"])
            for part in ("field", "chip"):          # a field and buttons you can tell from the row
                self.assertGreater(self.tb._contrast(rgb_pairs(c[part])[0], row_bg), 1.2, part)
            self.assertNotEqual(rgb_pairs(c["field"])[0], rgb_pairs(c["chip"])[0])

    def test_a_held_button_lights_up_until_it_is_released(self):
        fdt = sys.modules["kitty.fast_data_types"]
        fdt.GLFW_MOUSE_BUTTON_LEFT, fdt.GLFW_PRESS, fdt.GLFW_RELEASE = 0, 1, 2
        self.boss.combine = lambda a: None
        self.tb._search_row(30, 1)
        R = types.SimpleNamespace
        bar = R(window_geometry=R(left=0, right=310, top=0, bottom=400), cell_width=10, cell_height=20,
                tab_extents=[R(tab_id=-2, y=R(start=0, end=0))])
        tm = FakeTabManager([FakeTab()])
        tm.tab_bar, tm.active_tab = bar, None
        pressed = self.tb._row_colours()["pressed"]
        x = (self.tb._buttons["cols"][1][0] + 1) * 10 + 5                    # the ⚙
        self.assertTrue(self.tb._sidebar_click(tm, x, 5, 0, 1))
        self.assertGreater(tm.dirty, 0)                                       # redrawn at once
        self.assertIn(pressed + " ⚙ ", self.tb._search_row(30, 1))
        self.assertTrue(self.tb._sidebar_click(tm, x, 5, 0, 2))
        self.assertNotIn(pressed, self.tb._search_row(30, 1))
        # a release that never comes (the pointer left the window): the tick puts it out
        self.window(FakeTab())
        self.tb._sidebar_click(tm, x, 5, 0, 1)
        self.tb._press_at[1] -= self.tb.PRESS_LIMIT + 1
        self.tb._tick()
        self.assertNotIn(pressed, self.tb._search_row(30, 1))

    def test_turning_the_buttons_off_redraws_at_once(self):
        tm = self.window(FakeTab())
        self.tb._tick()
        before = tm.dirty
        open(self.kitty_path("buttons-off"), "w").close()
        self.tb._tick()
        self.assertGreater(tm.dirty, before)

    def test_waiting_count_shows_and_no_hazard_sign_without_it(self):
        self.tb._cat["blocked"] = 2
        self.assertIn("⚠2", self.tb._visible(self.tb._search_row()))
        self.tb._cat["blocked"] = 0
        self.assertNotIn("⚠", self.tb._search_row())
        self.assertNotIn("waiting", [n for *_, n in self.tb._buttons["cols"]])

    def test_off_switch(self):
        open(self.kitty_path("buttons-off"), "w").close()
        self.assertEqual(self.tb._search_row(), "")

    def test_current_tab_has_a_close_button_at_the_end(self):
        a, b = FakeTab(), FakeTab()
        self.window(a, b, active=0)
        line1 = Draw.strip(self.tb.draw_title(Draw.data(self, a, 1, "my work", "/w/x")).split("\n")[0])
        self.assertTrue(line1.endswith("× "), line1)         # under the search row's +
        self.assertEqual(self.tb._cells(line1), 30)
        self.assertEqual(line1.index("×"), 28)
        other = Draw.strip(self.tb.draw_title(Draw.data(self, b, 2, "other", "/w/x")).split("\n")[0])
        self.assertNotIn("×", other)

    def test_clicks_run_actions_without_earning_badges(self):
        ran = []
        boss = self.boss
        boss.combine = lambda a: (ran.append(a), self.tb._quest_action("launch", a.split()))
        fdt = sys.modules["kitty.fast_data_types"]
        fdt.GLFW_MOUSE_BUTTON_LEFT, fdt.GLFW_PRESS, fdt.GLFW_RELEASE = 0, 1, 0
        fdt.GLFW_RELEASE = 2
        self.tb._cat["blocked"] = 1                  # a tab waits, so the ⚠ button is there
        self.tb._search_row()
        R = types.SimpleNamespace
        ext = [R(tab_id=-2, y=R(start=0, end=1))]
        bar = R(window_geometry=R(left=0, right=310, top=0, bottom=400), cell_width=10, cell_height=20,
                tab_extents=ext)
        tm = R(tab_bar=bar, active_tab=None, os_window_id=1)
        c0 = self.tb._buttons["cols"][1][0] + 1                       # the ⚠ button
        self.assertTrue(self.tb._sidebar_click(tm, c0 * 10 + 5, 5, 0, 1))        # press: swallowed
        self.assertEqual(ran, [])
        self.assertTrue(self.tb._sidebar_click(tm, c0 * 10 + 5, 5, 0, 2))        # release: runs
        self.assertIn("tab-finder.py", ran[0])
        self.assertNotIn("waiting", self.tb._earned)                 # a click isn't the key
        c0 = self.tb._buttons["cols"][2][0] + 1                       # the ⚙: the settings list
        self.tb._sidebar_click(tm, c0 * 10 + 5, 5, 0, 1)
        self.tb._sidebar_click(tm, c0 * 10 + 5, 5, 0, 2)
        self.assertIn("settings.py", ran[1])
        self.assertIn("--type=overlay", ran[1])
        del ran[1]
        # a press elsewhere (on a tab) released on a button does nothing and goes to kitty
        self.assertFalse(self.tb._sidebar_click(tm, 50, 300, 0, 1))
        self.assertFalse(self.tb._sidebar_click(tm, c0 * 10 + 5, 5, 0, 2))
        self.assertEqual(len(ran), 1)

class NarrowSidebar(TabBarCase):
    """A small window or a big font makes kitty's sidebar narrower (at most a third of the window):
    the search row, its buttons, "+ New tab" and the × follow the real width."""
    def test_search_row_fits_every_width_and_keeps_its_buttons(self):
        for waiting in (0, 1, 12):
            for width in range(5, 41):          # kitty's sidebar is 6+ columns: 5+ cells a line
                text, cols = self.tb._row_layout(width, waiting)
                row = self.tb._visible(text)
                where = (width, waiting, row)
                self.assertEqual(self.tb._cells(row), width, where)
                self.assertEqual(row[width - 2], "+", where)          # + in the × column
                self.assertNotIn("…", row, where)                     # words are left out, never cut
                self.assertRegex(row, r"^ *((Search tabs|Search|Find) +)?(⚠\d+ +)?(⚙ +)?\+ ?$", where)
                if width >= 16 and waiting:
                    self.assertIn(f"⚠{waiting}", row, where)
                if width >= 10:
                    self.assertIn("⚙", row, where)
                last = -2                                             # (a chip in column 0 starts at -1)
                for c0, c1, name in cols:
                    if c1 < c0:
                        continue                                      # no room for the field
                    self.assertGreater(c0, last, where)               # in order, never overlapping
                    last = c1
                    if name != "search":
                        self.assertEqual(row[c0 + 1], self.tb.GLYPHS[name], (name,) + where)
                self.assertEqual(cols[-1][2], "new", where)
                self.assertEqual(cols[-1][1], width, where)           # + reaches the sidebar's edge

    def test_shorter_words_then_smaller_chips(self):
        rows = {w: self.tb._visible(self.tb._row_layout(w, 1)[0]) for w in (30, 25, 21, 16, 12)}
        self.assertEqual(rows[30], "  Search tabs      ⚠1   ⚙   + ")
        self.assertEqual(rows[25], "  Search      ⚠1   ⚙   + ")
        self.assertEqual(rows[21], "  Find    ⚠1   ⚙   + ")
        self.assertEqual(rows[16], "  Find   ⚠1 ⚙ + ")             # 1-cell chips before no words
        self.assertEqual(rows[12], " ⚠1   ⚙   + ")                # no room for words: buttons only
        self.assertEqual(self.tb._visible(self.tb._row_layout(5, 1)[0]), "⚠1 + ")   # ⚙ goes before ⚠

    def test_full_width_layout(self):
        text, cols = self.tb._row_layout(30, 0)
        self.assertEqual(self.tb._visible(text), "  Search tabs           ⚙   + ")
        self.assertEqual(cols, [(0, 22, "search"), (23, 26, "settings"), (27, 30, "new")])
        text, cols = self.tb._row_layout(30, 2)
        self.assertEqual(cols, [(0, 17, "search"), (18, 22, "waiting"), (23, 26, "settings"), (27, 30, "new")])

    def bar(self, columns, wid=1):
        R = types.SimpleNamespace
        return R(screen=R(columns=columns, lines=40), os_window_id=wid)

    def test_line_width_is_what_kitty_gives_a_tab(self):
        # kitty: max_title_length = min(sidebar columns - 1, tab_title_max_length)
        self.assertEqual(self.tb._line_width(self.bar(31)), 30)
        self.assertEqual(self.tb._line_width(self.bar(22)), 21)
        sys.modules["kitty.fast_data_types"].get_options = lambda: types.SimpleNamespace(tab_title_max_length=40)
        self.assertEqual(self.tb._line_width(self.bar(31)), 30)
        self.assertEqual(self.tb._line_width(self.bar(50)), 40)
        sys.modules["kitty.fast_data_types"].get_options = lambda: types.SimpleNamespace(tab_title_max_length=0)
        self.assertEqual(self.tb._line_width(self.bar(50)), 49)       # no limit set: the sidebar's
        self.assertEqual(self.tb._line_width(None), self.tb.ROW_WIDTH)  # unknown: as before

    def test_own_rows_are_made_for_each_windows_sidebar(self):
        import collections
        Row = collections.namedtuple("Row", "title tab_id is_active")
        self.tb._cat["blocked"] = 1
        data = (Row("wide", -2, False), Row("tab", 5, True), Row("  +   New tab", -1, False))
        narrow = self.tb._fit_own_rows(self.bar(17, wid=1), data)
        wide = self.tb._fit_own_rows(self.bar(31, wid=2), data)
        self.assertEqual(narrow[1], data[1])
        for rows, width in ((narrow, 16), (wide, 30)):
            for r in (rows[0], rows[2]):
                for line in self.tb._visible(r.title).split("\n"):
                    self.assertLessEqual(self.tb._cells(line), width, line)
            self.assertRegex(self.tb._visible(rows[0].title), r"⚠1 +⚙ +\+ $")
        self.assertEqual(self.tb._cols_for(1)[-1], (13, 16, "new"))
        self.assertEqual(self.tb._cols_for(2)[-1], (27, 30, "new"))
        # a click on the narrow window's + is the new-tab button there, not search
        R = types.SimpleNamespace
        ext = [R(tab_id=-2, y=R(start=0, end=0))]
        bar = R(window_geometry=R(left=0, right=170, top=0, bottom=400), cell_width=10, cell_height=20,
                tab_extents=ext)
        tm = R(tab_bar=bar, active_tab=None, os_window_id=1)
        self.assertEqual(self.tb._region(tm, 145, 5), ("button", "new"))
        self.assertEqual(self.tb._region(tm, 125, 5), ("button", "settings"))
        self.assertEqual(self.tb._region(tm, 95, 5), ("button", "waiting"))
        self.assertEqual(self.tb._region(tm, 35, 5), ("button", "search"))

    def test_new_tab_label_fits(self):
        for width in range(5, 31):
            for line in self.tb._visible(self.tb._new_tab_label(width)).split("\n"):
                self.assertLessEqual(self.tb._cells(line), width, (width, line))
        self.assertTrue(self.tb._new_tab_label(16).startswith("  +"))

    def test_close_button_follows_the_title_width(self):
        a, b = FakeTab(), FakeTab()
        tm = self.window(a, b, active=0)
        d = Draw.data(self, a, 1, "my work", "/w/x")
        d["max_title_length"] = 20
        line1 = Draw.strip(self.tb.draw_title(d).split("\n")[0])
        self.assertEqual(self.tb._cells(line1), 20)
        self.assertEqual(line1.index("×"), 18)
        self.assertEqual(self.tb._buttons["close_cols"][a.id], 18)
        # the close button is found per tab: another window's current tab has its own column
        R = types.SimpleNamespace
        self.tb._buttons["close_row"] = {1: 2}
        bar = R(window_geometry=R(left=0, right=210, top=0, bottom=400), cell_width=10, cell_height=20,
                tab_extents=[R(tab_id=a.id, y=R(start=2, end=3))])
        tm.tab_bar = bar
        self.assertEqual(self.tb._region(tm, 185, 45), ("close",))
        self.assertIsNone(self.tb._region(tm, 100, 45))


class HelperCat(TabBarCase):
    """A click on the cat at the end of "+ New tab" opens the helper cat (cat-helper.py), like ⚙
    opens the settings: per kitty window, only on its first line, and not when the cat is hidden."""
    def bar(self, row=10):
        R = types.SimpleNamespace
        ext = [R(tab_id=-1, y=R(start=row, end=row + 1))]
        return R(window_geometry=R(left=0, right=310, top=0, bottom=800), cell_width=10, cell_height=20,
                 tab_extents=ext)

    def test_a_click_on_the_cat_is_the_helper(self):
        tb = self.tb
        line = tb._visible(tb._new_tab_label(30, wid=1)).split("\n")[0]
        at = line.index("=")
        self.assertEqual(tb._cat_cols_for(1), (at - 1, 30))
        tm = types.SimpleNamespace(tab_bar=self.bar(), active_tab=None, os_window_id=1)
        y = 10 * 20 + 5
        self.assertEqual(tb._region(tm, (at + 2) * 10 + 5, y), ("cat",))
        self.assertEqual(tb._region(tm, (at - 1) * 10 + 5, y), ("cat",))               # a cell before it
        self.assertIsNone(tb._region(tm, 45, y))                                       # "+ New tab": kitty's
        self.assertIsNone(tb._region(tm, (at + 2) * 10 + 5, y + 20))                   # the quest line
        # another kitty window with a narrow sidebar has the cat elsewhere (or nowhere)
        tb._new_tab_label(12, wid=2)
        self.assertIsNone(tb._cat_cols_for(2))
        self.assertIsNone(tb._region(types.SimpleNamespace(tab_bar=self.bar(), active_tab=None, os_window_id=2),
                                     (at + 2) * 10 + 5, y))
        self.assertEqual(tb._cat_cols_for(1), (at - 1, 30))

    def test_kitty_cat_off_leaves_no_click_target(self):
        open(self.kitty_path("cat-off"), "w").close()
        tb = self.tb
        tb._new_tab_label(30, wid=1)
        self.assertIsNone(tb._cat_cols_for(1))
        tm = types.SimpleNamespace(tab_bar=self.bar(), active_tab=None, os_window_id=1)
        self.assertIsNone(tb._region(tm, 255, 205))

    def test_the_click_runs_the_helper_and_earns_no_badge(self):
        tb = self.tb
        self.assertIn("cat-helper.py", tb.ACTIONS["cat"])
        self.assertIn("--type=overlay", tb.ACTIONS["cat"])
        tb._quest_action("launch", tb.ACTIONS["cat"].split()[1:])       # as if from a key: no quest
        self.assertEqual(tb._earned, {})

    def test_the_key_in_kitty_conf_runs_the_same(self):
        with open(os.path.join(HERE, "..", "config", "kitty.conf"), encoding="utf-8") as f:
            line = next(l for l in f.read().splitlines() if l.startswith("map ctrl+alt+c "))
        self.assertEqual(line.split(None, 2)[2].strip(), self.tb.ACTIONS["cat"])


class NoCuts(TabBarCase):
    """Our own lines take a shorter wording instead of a word cut in half (or cut off silently)."""
    def states(self):
        tb, now = self.tb, self.tb.time.monotonic()
        yield "quest", lambda: None
        for qid, *_ in tb.QUESTS:                                  # every quest as today's
            yield f"quest {qid}", lambda q=qid: tb._earned.update(
                {x[0]: "d" for x in tb.QUESTS if x[0] != q})
        yield "all done", lambda: tb._earned.update({x[0]: "d" for x in tb.QUESTS})
        for kind in ("badge", "rank", "mastered"):
            yield kind, lambda k=kind: tb._badge_shown.update(
                id="waiting", until=now + 5, rank=k == "rank", mastered=k == "mastered")
        yield "coach", lambda: tb._coach.update(text="Alt+3 also gets here", until=now + 5)

    def test_new_tab_and_quest_lines_never_cut_a_word(self):
        tb = self.tb
        for name, setup in self.states():
            for width in range(5, 41):
                tb._earned.clear()
                tb._badge_shown.update(id=None, until=0.0)
                tb._coach["until"] = 0.0
                setup()
                for line in tb._visible(tb._new_tab_label(width)).split("\n"):
                    self.assertLessEqual(tb._cells(line), width, (name, width, line))
                    self.assertNotIn("…", line.replace("Alt+1…9", ""), (name, width, line))

    def test_the_quest_keeps_its_key_when_the_words_dont_fit(self):
        tb = self.tb
        with mock.patch.object(tb, "_next_quest", lambda: tb.QUEST_BY_ID["scrollback"]):
            self.assertEqual(tb._visible(tb._quest_line(30)), " ★0   Ctrl+Shift+H  history")
            self.assertEqual(tb._visible(tb._quest_line(26)), " ★0   Ctrl+Shift+H history")
            self.assertEqual(tb._visible(tb._quest_line(20)), " ★0   Ctrl+Shift+H")
            self.assertEqual(tb._visible(tb._quest_line(12)), " ★0")

    def test_every_quest_hint_fits_the_usual_sidebar(self):
        for q in self.tb.QUESTS:
            self.assertLessEqual(self.tb._cells(q[2]), self.tb.ROW_WIDTH - 6, q[2])

    def test_the_cat_stays_put_and_the_words_dont_flip(self):
        tb = self.tb
        tb._cat["quiet_since"] = tb.time.monotonic() - tb.SLEEP_AFTER - 1     # dozing: z, zz, zZ, zZz
        for width in range(5, 41):
            firsts = set()
            for f in range(0, 48, 12):
                tb._frame = f
                firsts.add(tb._visible(tb._new_tab_label(width)).split("\n")[0].split("=")[0])
            self.assertEqual(len(firsts), 1, (width, firsts))


class Calm(TabBarCase):
    """One strong signal per tab: the status icon and the name; numbers, agent marks, the new-output
    dot and the branch are quiet, and still readable (text 4.5:1, icons 3:1) in both themes."""
    def test_quiet_colours_stay_above_the_limits_in_both_themes(self):
        tb = self.tb
        for t in (tb.THEME_FALLBACK, LIGHT_THEME):
            fg, bg = t["inactive_tab_foreground"], t["inactive_tab_background"]
            text, icon = tb._quiet(fg, bg, tb.QUIET_TEXT), tb._quiet(fg, bg, tb.QUIET_ICON)
            self.assertGreaterEqual(tb._contrast(text, bg), 4.5)
            self.assertGreaterEqual(tb._contrast(icon, bg), 3.0)
            self.assertLess(tb._contrast(text, bg), tb._contrast(fg, bg))     # quieter than before
            self.assertLess(tb._contrast(icon, bg), tb._contrast(text, bg))

    def test_new_output_is_a_small_quiet_dot(self):
        a, b = FakeTab(), FakeTab()
        self.window(a, b, active=0)
        d = Draw.data(self, b, 2, "notes", "/w/notes")
        d["activity_symbol"] = "● "                   # an older kitty.conf's big dot, too
        out = self.tb.draw_title(d).split("\n")[0]
        quiet = self.tb._sgr_fg(self.tb._quiet(self.tb.THEME_FALLBACK["inactive_tab_foreground"],
                                               self.tb.THEME_FALLBACK["inactive_tab_background"], self.tb.QUIET_ICON))
        self.assertIn(quiet + "• ", out)
        self.assertNotIn("●", out)

    def test_number_and_agent_mark_are_quiet_and_the_branch_is_not_coloured(self):
        a, b = FakeTab(), FakeTab()
        self.window(a, b, active=0)
        wd = Draw.repo(self, "fix-parser")
        with mock.patch.object(self.tb, "_foreground_name", lambda w: "claude"):
            line1, line2 = self.tb.draw_title(Draw.data(self, b, 2, "✳ Fix", wd)).split("\n")
        t = self.tb.THEME_FALLBACK
        fg, bg = t["inactive_tab_foreground"], t["inactive_tab_background"]
        self.assertTrue(line1.startswith(self.tb._sgr_fg(self.tb._quiet(fg, bg, self.tb.QUIET_TEXT)) + "  2 "), line1)
        self.assertIn(self.tb._sgr_fg(self.tb._quiet(fg, bg, self.tb.QUIET_ICON)) + "✳", line2)
        self.assertNotIn("<fg5>", line2)              # no magenta branch: a detail, not a signal
        self.assertIn("⌥ fix-parser", Draw.strip(line2))

    def test_the_active_tab_stays_one_colour(self):
        a = FakeTab()
        self.window(a)
        out = self.tb.draw_title(Draw.data(self, a, 1, "here", "/w/x"))
        self.assertNotIn("38;2", out)


class CatColour(TabBarCase):
    def test_each_mood_has_its_colour(self):
        tb, now = self.tb, self.tb.time.monotonic()
        tb._cat.update(blocked=1, fresh_block=False)
        self.assertTrue(tb._cat_face().startswith("\x1b[33m=O.O="))           # amber, like ⚠
        tb._cat.update(blocked=0, working=True)
        self.assertTrue(tb._cat_face().startswith("\x1b[34m=^.^="))           # blue, like the spinner
        tb._cat.update(working=False, done_at=now)
        self.assertTrue(tb._cat_face().startswith("\x1b[32m=^ω^="))           # green: finished
        tb._cat.update(done_at=-99.0, error_at=now)
        self.assertTrue(tb._cat_face().startswith("\x1b[31m=>.<="))           # red: error
        tb._cat.update(error_at=-99.0, quiet_since=now - tb.SLEEP_AFTER - 61)
        self.assertTrue(tb._cat_face().startswith("\x1b[35m=-.-= zZ"))        # lavender: asleep
        tb._cat["quiet_since"] = now
        self.assertTrue(tb._cat_face().startswith("\x1b[38;5;130m=^.^="))     # idle: ginger
        self.assertEqual(tb._visible(tb._cat_face()), "=^.^=")

    def test_mood_colours_read_on_the_sidebar_in_both_themes(self):
        # cosmic-dark/light's palette, and the sidebar under the cat as measured from test-kitty shots
        dark = {1: "#c98a8a", 2: "#8fae8c", 3: "#cfae7c", 4: "#8a9cc6", 5: "#b391c1"}
        light = {1: "#a5514f", 2: "#4d7650", 3: "#80622a", 4: "#4c6699", 5: "#82609a"}
        h = lambda x: tuple(int(x[i:i + 2], 16) for i in (1, 3, 5))
        steps = (0, 95, 135, 175, 215, 255)                 # xterm's 256-colour cube (16-231)
        cube = lambda n: (steps[(n - 16) // 36], steps[(n - 16) // 6 % 6], steps[(n - 16) % 6])
        for pal, bg in ((dark, (0x26, 0x21, 0x2f)), (light, (0xe2, 0xe1, 0xe6))):
            for sgr in set(self.tb.CAT_COLOUR.values()) - {""}:
                if sgr.startswith("\x1b[38;5;"):
                    n = int(sgr[7:-1])
                    rgb = cube(n)
                else:
                    n = int(sgr[3])
                    rgb = h(pal[n])
                self.assertGreaterEqual(self.tb._contrast(rgb, bg), 3.0, (n, rgb))


class ConfigFolder(TabBarCase):
    def test_follows_kittys_config_folder(self):
        # a second kitty with its own config folder (dev-kitty.sh) keeps its own switches and sounds
        other = os.path.join(self.tmp.name, "dev")
        sys.modules["kitty.constants"].config_dir = other
        spec = importlib.util.spec_from_file_location("nl_tab_bar2", TAB_BAR)
        assert spec is not None and spec.loader is not None
        tb2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tb2)
        self.assertEqual(tb2.MUTE_FILE, os.path.join(other, "sounds-off"))
        self.assertEqual(tb2.SOUND_DIR, os.path.join(other, "sounds"))
        self.assertEqual(tb2.CAT_OFF, os.path.join(other, "cat-off"))


class RunningVersion(TabBarCase):
    def test_keeps_the_first_loaded_version_until_a_restart(self):
        import hashlib
        tb, conf = self.tb, os.path.join(self.tmp.name, ".config", "kitty")
        with open(os.path.join(conf, "tab_bar.py"), "w") as f:
            f.write("v1")
        kt = types.SimpleNamespace()                  # stands in for kitty.tab_bar in one process
        tb._record_running_version(kt)
        with open(os.path.join(conf, "tab_bar.py"), "w") as f:
            f.write("v2")                             # installed again; kitty only reloads
        tb._record_running_version(kt)
        with open(tb.RUNNING_FILE) as f:
            self.assertEqual(f.read().strip(), hashlib.sha1(b"v1").hexdigest())


class FirstUpgrade(TabBarCase):
    def test_an_older_tab_bar_already_running_counts_as_stale(self):
        tb = self.tb
        kt = types.SimpleNamespace(_vye_quest_action=lambda *a: None)   # patched by an older load
        tb._record_running_version(kt)
        with open(tb.RUNNING_FILE) as f:
            self.assertEqual(f.read().strip(), "older")


class Text(TabBarCase):
    def test_fit_cuts_with_ellipsis_and_counts_wide_chars(self):
        self.assertEqual(self.tb._fit("short", 10), "short")
        self.assertEqual(self.tb._fit("abcdefghij", 6), "abcde…")
        cut = self.tb._fit("日本語のタイトル", 7)
        self.assertLessEqual(self.tb._cells(cut), 7)
        self.assertTrue(cut.endswith("…"))

    def test_fit_start_keeps_the_end_of_a_path(self):
        self.assertEqual(self.tb._fit_start("a-very-long/inner-project", 14), "…inner-project")

    def test_tab_name(self):
        n = self.tb._tab_name
        self.assertEqual(n("~/work/beta", "/home/x/work/beta"), "beta")
        self.assertEqual(n("⠋ omp: refactor", "/w"), "omp: refactor")
        self.assertEqual(n("✳ Fix the login bug", "/w"), "Fix the login bug")
        self.assertEqual(n("π ⠋ task", "/w"), "π task")

    def test_a_bare_shell_title_shows_the_folder(self):
        # a shell without kitty's shell integration sets no title of its own: kitty names the window
        # "bash" (as kitty-relaunch's restored shells once were), and the sidebar shows the folder
        n = self.tb._tab_name
        for title in ("bash", "zsh", "-bash", "fish"):
            self.assertEqual(n(title, "/w/proj"), "proj", title)
        self.assertEqual(n("bash-scripts", "/w/proj"), "bash-scripts")
        self.assertEqual(n("✳ bash", "/w/proj"), "bash")              # Claude's title stays a title
        renamed, plain = FakeTab(), FakeTab()
        renamed.name, plain.name = "bash", ""
        self.window(renamed, plain)
        self.assertEqual(n("bash", "/w/proj", renamed.id), "bash")    # you named it that: kept
        self.assertEqual(n("bash", "/w/proj", plain.id), "proj")

    def test_tab_folder_uses_tilde_and_two_levels(self):
        home = self.tb.HOME
        self.assertEqual(self.tb._tab_folder(home + "/src/code/NineLives"), "code/NineLives")
        self.assertEqual(self.tb._tab_folder(home + "/x"), "~/x")


class Elapsed(TabBarCase):
    def at(self, t):
        return mock.patch.object(self.tb.time, "monotonic", return_value=t)

    def test_nothing_in_the_first_minute_then_minutes_then_hours(self):
        with self.at(1000.0):
            self.assertEqual(self.tb._elapsed(1, "working"), "")
        with self.at(1000.0 + 59):
            self.assertEqual(self.tb._elapsed(1, "working"), "")
        with self.at(1000.0 + 3 * 60):
            self.assertEqual(self.tb._elapsed(1, "working"), "3m")
        with self.at(1000.0 + 65 * 60):
            self.assertEqual(self.tb._elapsed(1, "working"), "1h05")

    def test_a_new_state_starts_the_clock_again(self):
        with self.at(1000.0):
            self.tb._elapsed(1, "working")
        with self.at(1000.0 + 300):
            self.assertEqual(self.tb._elapsed(1, "working"), "5m")
            self.assertEqual(self.tb._elapsed(1, "blocked"), "")

    def test_no_state_no_time(self):
        self.assertEqual(self.tb._elapsed(1, ""), "")


class Sparkle(TabBarCase):
    def test_burst_plays_every_frame_once_then_lands(self):
        tb = self.tb
        tb._frame = 100
        tb._start_sparkle(7)
        frames = []
        for f in range(100, 100 + len(tb.SPARKLE) + 2):
            tb._frame = f
            frames.append(tb._sparkle(7))
        self.assertEqual(frames[:len(tb.SPARKLE)], list(tb.SPARKLE))
        self.assertEqual(frames[-1], "")

    def test_starting_twice_in_a_row_does_not_restart(self):
        tb = self.tb
        tb._frame = 50
        tb._start_sparkle(7)
        tb._frame = 52
        tb._start_sparkle(7)
        self.assertEqual(tb._sparkle_start[7], 50)


class Cat(TabBarCase):
    def test_needs_you_beats_a_celebration(self):
        tb = self.tb
        tb._cat.update(blocked=2, fresh_block=False)
        tb._badge_shown.update(id="zoom", until=tb.time.monotonic() + 5)
        self.assertIn("=O.O=", tb._cat_face())
        self.assertIn("2!", tb._cat_face())

    def test_celebrates_a_badge(self):
        tb = self.tb
        tb._badge_shown.update(id="zoom", until=tb.time.monotonic() + 5, rank=True)
        face = tb._cat_face()
        self.assertIn("=^▽^=", face)
        self.assertIn("♛", face)

    def test_naps_then_holds_still(self):
        tb = self.tb
        now = tb.time.monotonic()
        tb._cat["quiet_since"] = now - tb.SLEEP_AFTER - 1
        self.assertIn("=-.-=", tb._cat_face())
        tb._cat["quiet_since"] = now - tb.SLEEP_AFTER - 61
        a = tb._cat_face()
        tb._frame += 37
        self.assertEqual(tb._cat_face(), a)        # fully asleep: no more changes (no redraws)

    def test_kitty_cat_off_hides_it(self):
        open(self.kitty_path("cat-off"), "w").close()
        self.assertEqual(self.tb._cat_face(), "")


class CatMoves(TabBarCase):
    """The cat moves: short moves (frames of 0.125 s) on top of the mood's face,
    reactions to what happens, and a roll of the dice once a second. A pinned clock and dice."""

    def setUp(self):
        super().setUp()
        self.clock = [1000.0]
        self.time = mock.patch.object(self.tb.time, "monotonic", lambda: self.clock[0])
        self.time.start()
        self.tb._cat.update(quiet_since=1000.0, done_at=-99.0, error_at=-99.0, blocked=0, working=False,
                            fresh_block=False)
        self.tb._frame = 100

    def tearDown(self):
        self.time.stop()
        super().tearDown()

    def play(self, name):
        """The faces, frame by frame, of `name` started now, and one frame after it ends."""
        tb = self.tb
        tb._cat["moves"] = {name: tb._frame}
        out = []
        for _ in range(tb._move_len(name) + 1):
            out.append(tb._visible(tb._cat_face()))
            tb._frame += 1
        return out

    def test_each_moves_frames(self):
        tb, now = self.tb, self.clock[0]
        I = "=^.^="
        for name, want in {
            "blink": ["=-.-=", I],                                  # 0.125 s
            "wink": ["=^ω-="] * 5 + [I],                            # 0.625 s, with a smile
            "look-left": ["=<.<="] * 8 + [I],                       # 1 s
            "look-right": ["=>.>="] * 8 + [I],
            "ear-left": ["~^.^="] * 2 + [I] * 2 + ["~^.^="] * 2 + [I] * 3,   # twitches twice
            "ear-right": ["=^.^~"] * 2 + [I] * 2 + ["=^.^~"] * 2 + [I] * 3,
            "tail": ["=^.^= ~"] * 2 + ["=^.^= -"] * 2 + ["=^.^= ~"] * 2 + ["=^.^= -"] * 2 + [I],
        }.items():
            self.assertEqual(self.play(name), want, name)
        tb._cat["blocked"] = 1                                      # a tab needs you
        self.assertEqual(self.play("surprise"), ["~OoO~ !"] * 2 + ["=OoO= !"] * 2 + ["=O.O= !"])
        tb._cat.update(blocked=0, error_at=now)
        self.assertEqual(self.play("flinch"), ["~>.<~ "] * 2 + ["=>.<= "] * 2 + ["~>.<~ "] * 2 + ["=>.<= "])
        tb._cat.update(error_at=-99.0, done_at=now)
        self.assertEqual(self.play("hop"), ["=>ω<= ♪"] * 4 + ["=^ω^= ♪"])
        up, down = "=^ω^/ ♪", "=^ω^= ♪"
        self.assertEqual(self.play("wave"), [up] * 2 + [down] * 2 + [up] * 2 + [down] * 2 + [up, down])
        tb._cat["done_at"] = -99.0
        tb._badge_shown.update(id="zoom", until=now + 5, rank=False)
        faces = [f[:5] for f in self.play("cheer")]                 # (the twinkle after it twinkles)
        up, down = "\\^▽^/", "=^▽^="
        self.assertEqual(faces, [up] * 2 + [down] * 2 + [up] * 2 + [down] * 2 + [up, down])

    def test_moves_overlap(self):
        tb = self.tb
        tb._cat["moves"] = {"tail": tb._frame, "blink": tb._frame + 2}    # a blink mid tail flick
        faces = []
        for _ in range(4):
            faces.append(tb._visible(tb._cat_face()))
            tb._frame += 1
        self.assertEqual(faces, ["=^.^= ~", "=^.^= ~", "=-.-= -", "=^.^= -"])
        tb._cat["moves"] = {"look-left": tb._frame - 3, "blink": tb._frame}
        self.assertEqual(tb._visible(tb._cat_face()), "=-.-=")        # a blink closes a glance too

    def test_a_move_shows_only_in_its_moods(self):
        tb, now = self.tb, self.clock[0]
        tb._cat.update(blocked=1, done_at=now)                       # finished, but another one waits
        tb._cat["moves"] = {"hop": tb._frame, "tail": tb._frame}
        self.assertEqual(tb._visible(tb._cat_face()), "=O.O= !")      # needs you wins, and stays still
        tb._cat.update(blocked=0, working=True)
        self.assertEqual(tb._visible(tb._cat_face()), "=>ω<= ♪")      # happy beats working
        tb._cat.update(done_at=-99.0)
        self.assertEqual(tb._visible(tb._cat_face()), "=^.^= -")      # working: its own tail swishes
        tb._cat.update(working=False, quiet_since=now - tb.SLEEP_AFTER - 61)
        tb._cat["moves"] = {"blink": tb._frame, "look-left": tb._frame}
        self.assertEqual(tb._visible(tb._cat_face()), "=-.-= zZ")     # asleep: nothing moves

    def test_the_face_stays_five_cells_in_one_place(self):
        tb, now = self.tb, self.clock[0]
        moods = {
            "idle": {}, "working": dict(working=True), "alert": dict(blocked=2),
            "happy": dict(done_at=now), "startled": dict(error_at=now),
            "asleep": dict(quiet_since=now - tb.SLEEP_AFTER - 1),
        }
        tb._streak.update(step=3, at=now)                            # ♪♪♪: the widest notes
        faces = set()
        for mood, state in list(moods.items()) + [("badge", None)]:
            tb._cat.update(blocked=0, working=False, done_at=-99.0, error_at=-99.0, quiet_since=now)
            tb._badge_shown.update(until=0.0)
            if state is None:
                tb._badge_shown.update(id="zoom", until=now + 5, rank=True)
            else:
                tb._cat.update(state)
            for name in tb.CAT_MOVES:
                tb._cat["moves"] = {name: tb._frame}
                for _ in range(tb._move_len(name) + 1):
                    faces.add(tb._cat_face())
                    tb._frame += 1
        self.assertGreater(len(faces), 35)
        for face in faces:
            seen = tb._visible(face)
            self.assertEqual(tb._cells(seen[:5]), 5, seen)
            self.assertLessEqual(tb._cells(seen), tb.CAT_WIDTH, seen)
            for ch in seen[:5]:                                        # single-width, never ambiguous
                self.assertTrue(ch.isascii() or ch in "ω▽", seen)       # (but the faces' own ω ▽)
        for width in range(14, 41):
            starts = set()
            for face in faces:
                with mock.patch.object(tb, "_cat_face", lambda: face):
                    line = tb._visible(tb._new_tab_label(width)).split("\n")[0]
                if line.endswith(tb._visible(face)):
                    starts.add(tb._cells(line[:len(line) - len(tb._visible(face))]))
            if width >= 20:                                            # the cat fits: one place
                self.assertEqual(len(starts), 1, (width, starts))
            self.assertLessEqual(len(starts), 1, (width, starts))

    def test_night_puts_the_idle_cat_to_sleep(self):
        tb, now = self.tb, self.clock[0]
        tb._night = self.real_night

        def at(hour):
            return mock.patch.object(tb.time, "localtime",
                                     lambda *a: time.struct_time((2026, 11, 25, hour, 30, 0, 2, 329, 0)))
        for hour in (23, 0, 3, 5):
            with at(hour):
                self.assertEqual(tb._cat_mood()[0], "asleep", hour)        # dozes off at once
                self.clock[0] = now + 61
                self.assertEqual(tb._cat_mood(), ("asleep", "=-.-= zZ"))   # then holds still
                self.clock[0] = now
        for hour in (6, 12, 22):
            with at(hour):
                self.assertEqual(tb._cat_mood(), ("idle", "=^.^="), hour)
        with at(2):                                                    # more important things wake it
            for state, mood in ((dict(working=True), "working"), (dict(blocked=1), "alert"),
                                (dict(done_at=now), "happy"), (dict(error_at=now), "startled")):
                tb._cat.update(state)
                self.assertEqual(tb._cat_mood()[0], mood)
                tb._cat.update(working=False, blocked=0, done_at=-99.0, error_at=-99.0)
            tb._badge_shown.update(id="zoom", until=now + 5)
            self.assertEqual(tb._cat_mood()[0], "badge")

    def test_the_dice(self):
        tb = self.tb
        tb._cat_rng = Dice(0.1)                                      # under CAT_BLINK: a blink
        tb._cat_react()
        self.assertEqual(list(tb._cat["moves"]), ["blink"])
        for pick, want in enumerate(tb.CAT_FIDGETS):                 # just over: a fidget
            tb._cat.update(moves={}, roll=0)
            tb._cat_rng = Dice(tb.CAT_BLINK + 0.01, pick=pick)
            tb._cat_react()
            self.assertEqual(list(tb._cat["moves"]), [want])
        tb._cat.update(moves={}, roll=0)
        tb._cat_rng = Dice(0.5)                                      # most seconds: nothing
        tb._cat_react()
        self.assertEqual(tb._cat["moves"], {})
        tb._cat.update(moves={"look-left": tb._frame}, roll=0)        # no fidget over another move
        tb._cat_rng = Dice(tb.CAT_BLINK + 0.01, pick=0)
        tb._cat_react()
        self.assertEqual(list(tb._cat["moves"]), ["look-left"])
        tb._cat.update(moves={}, roll=0, working=True)               # working: no idle tail flick
        tb._cat_rng = Dice(tb.CAT_BLINK + 0.01, pick=5)
        tb._cat_react()
        self.assertNotIn("tail", tb._cat["moves"])

    def test_rolls_once_a_second_and_never_waiting_asleep_or_hidden(self):
        tb = self.tb
        rolls = []

        class Counting(Dice):
            def random(self):
                rolls.append(tb._frame)
                return 0.99
        tb._cat_rng = Counting()
        for _ in range(80):
            tb._cat_react()
            tb._frame += 1
        self.assertEqual(len(rolls), 10)
        self.assertEqual({b - a for a, b in zip(rolls, rolls[1:])}, {tb.CAT_ROLL})
        rolls.clear()
        tb._cat["blocked"] = 1                                          # a tab waits: the cat stares
        for _ in range(80):
            tb._cat_react()
            tb._frame += 1
        tb._cat["blocked"] = 0
        tb._cat["quiet_since"] = self.clock[0] - tb.SLEEP_AFTER - 1       # asleep
        for _ in range(80):
            tb._cat_react()
            tb._frame += 1
        tb._cat["quiet_since"] = self.clock[0]
        open(self.kitty_path("cat-off"), "w").close()                    # hidden
        for _ in range(80):
            tb._cat_react()
            tb._frame += 1
        self.assertEqual(rolls, [])

    def test_a_seeded_cat_does_the_same_again(self):
        tb = self.tb

        def run(seed):
            tb._frame = 100
            tb._cat.update(moves={}, roll=0)
            tb._cat_rng = random.Random(seed)
            started = []
            for _ in range(8 * 600):                                  # ten minutes
                before = dict(tb._cat["moves"])
                tb._cat_react()
                started += [(tb._frame, n) for n, f in tb._cat["moves"].items() if before.get(n) != f]
                tb._frame += 1
            return started
        a = run(42)
        self.assertEqual(a, run(42))
        blinks = sum(1 for _, n in a if n == "blink")
        self.assertTrue(90 < blinks < 175, blinks)                    # about 22% of 600 rolls
        self.assertTrue(any(n != "blink" for _, n in a))

    def test_reacts_to_what_happens(self):
        tb, now = self.tb, self.clock[0]
        tb._cat.update(blocked=1, waits=1)
        tb._cat_react()                                               # the first look: nothing new
        self.assertEqual(tb._cat["moves"], {})
        tb._cat.update(blocked=1, waits=2)                            # one stopped waiting as another began
        tb._cat_react()
        self.assertEqual(tb._cat["moves"], {"surprise": tb._frame})
        tb._cat.update(blocked=0, moves={}, done_at=now)              # one finished: hop, then wave
        tb._cat_react()
        self.assertEqual(tb._cat["moves"], {"hop": tb._frame, "wave": tb._frame + tb._move_len("hop")})
        tb._cat.update(moves={}, error_at=now)
        tb._cat_react()
        self.assertEqual(tb._cat["moves"], {"flinch": tb._frame})
        tb._cat["moves"] = {}
        tb._badge_shown.update(id="zoom", until=now + 5)
        tb._cat_react()
        self.assertEqual(tb._cat["moves"], {"cheer": tb._frame})
        tb._frame += 20
        tb._cat_react()
        self.assertEqual(tb._cat["moves"], {})                       # done ones are dropped

    def test_redraws_only_while_a_move_plays(self):
        tb = self.tb

        class Drawing(FakeTabManager):
            def mark_tab_bar_dirty(self):
                super().mark_tab_bar_dirty()
                tb._new_tab_label(30)                                 # what kitty's redraw does
        tm = Drawing([FakeTab()])
        self.boss.all_tab_managers = [tm]
        tb._tick()                                                    # the first tick draws once
        tb._tick()
        start = tm.dirty
        for _ in range(8 * 60):                                       # a quiet minute, no moves
            tb._tick()
        self.assertEqual(tm.dirty, start)
        tb._cat["roll"] = 0
        tb._cat_rng = Dice(0.1)                                       # one blink: on, then off
        for _ in range(16):
            tb._tick()
        self.assertEqual(tm.dirty, start + 2)
        tb._cat.update(roll=0, moves={})
        tb._cat_rng = Dice(tb.CAT_BLINK + 0.01, pick=5)               # a tail flick: ~ - ~ - gone
        for _ in range(16):
            tb._tick()
        self.assertEqual(tm.dirty, start + 2 + 5)
        tb._cat["quiet_since"] = self.clock[0] - tb.SLEEP_AFTER - 61   # fully asleep
        tb._tick()
        asleep = tm.dirty
        tb._cat_rng = Dice(*[0.1] * 100)                              # dice that would always blink
        for _ in range(8 * 60):
            tb._tick()
        self.assertEqual(tm.dirty, asleep)
        tb._cat.update(quiet_since=self.clock[0], blocked=0)

    def test_a_waiting_tab_holds_the_cat_still(self):
        tb = self.tb

        class Drawing(FakeTabManager):
            def mark_tab_bar_dirty(self):
                super().mark_tab_bar_dirty()
                tb._new_tab_label(30)
        waiting = FakeTab(FakeWindow("blocked"))
        tm = Drawing([waiting])
        self.boss.all_tab_managers = [tm]
        tb._tick()                                                    # (loaded with it waiting)
        tb._tick()
        self.assertEqual(tb._visible(tb._cat_face()), "=O.O= !")
        start = tm.dirty
        tb._cat_rng = Dice(*[0.1] * 100)                              # dice that would always blink
        for _ in range(8 * 60):
            tb._tick()
        self.assertEqual(tm.dirty, start)


class Sounds(TabBarCase):
    def test_plays_its_own_file_at_full_volume(self):
        self.tb._play("blocked")
        self.assertEqual(self.sounds(), [("needs-you.oga", 40000)])

    def test_muted(self):
        open(self.kitty_path("sounds-off"), "w").close()
        self.tb._play("done")
        self.assertEqual(self.sounds(), [])

    def test_volume_setting_scales(self):
        with open(self.kitty_path("sounds-volume"), "w") as f:
            f.write("30\n")
        self.tb._play("done")
        self.assertEqual(self.sounds(), [("done.oga", 12000)])

    def test_bad_volume_setting_is_ignored(self):
        with open(self.kitty_path("sounds-volume"), "w") as f:
            f.write("loud")
        self.tb._play("done")
        self.assertEqual(self.sounds(), [("done.oga", 40000)])

    def test_tabs_finishing_one_after_another_climb_a_step(self):
        clock = [1000.0]
        with mock.patch.object(self.tb.time, "monotonic", lambda: clock[0]):
            for gap in (0, 20, 20, 20, 200):          # four in a row, then a long quiet spell
                clock[0] += gap
                self.tb._note_done(clock[0])
                self.tb._play("done")
        self.assertEqual([s for s, _ in self.sounds()],
                         ["done.oga", "done-2.oga", "done-3.oga", "done-3.oga", "done.oga"])

    def test_classic_streak_stays_the_desktop_chime(self):
        open(self.kitty_path("sounds-classic"), "w").close()
        with mock.patch.object(self.tb, "CLASSIC_DIR", self.tmp.name):
            open(os.path.join(self.tmp.name, "complete.oga"), "w").close()
            clock = [1000.0]
            with mock.patch.object(self.tb.time, "monotonic", lambda: clock[0]):
                for gap in (0, 20):
                    clock[0] += gap
                    self.tb._note_done(clock[0])
                    self.tb._play("done")
        self.assertEqual([s for s, _ in self.sounds()], ["complete.oga", "complete.oga"])

    def test_the_cat_sings_one_note_per_finish_in_a_row(self):
        clock = [1000.0]
        with mock.patch.object(self.tb.time, "monotonic", lambda: clock[0]):
            faces = []
            for gap in (0, 20, 20, 20):
                clock[0] += gap
                self.tb._note_done(clock[0])
                self.tb._cat["done_at"] = clock[0]
                faces.append(self.tb._visible(self.tb._cat_face()))
        self.assertEqual(faces, ["=^ω^= ♪", "=^ω^= ♪♪", "=^ω^= ♪♪♪", "=^ω^= ♪♪♪"])

    def test_a_burst_plays_only_the_most_important(self):
        tb = self.tb
        tb._play("done")
        tb._play("done")
        tb._play("error")
        tb._play("blocked")
        tb._play("done")
        self.assertEqual([s for s, _ in self.sounds()], ["done.oga", "error.oga", "needs-you.oga"])

    def test_classic_uses_the_desktop_sounds(self):
        open(self.kitty_path("sounds-classic"), "w").close()
        with mock.patch.object(self.tb.os.path, "isfile", return_value=True):
            self.tb._play("done")
        self.assertEqual(self.sounds(), [("complete.oga", 40000)])

    def test_no_chime_for_the_tab_you_are_watching(self):
        a, b = FakeTab(), FakeTab()
        self.window(a, b, active=0)
        self.tb._play("done", a.id)
        self.assertEqual(self.sounds(), [])
        self.tb._play("done", b.id)
        self.assertEqual(self.sounds(), [("done.oga", 40000)])

    def test_watching_needs_kitty_focused(self):
        a = FakeTab()
        self.window(a)
        self.focused = 0                              # you're in another app
        self.tb._play("done", a.id)
        self.assertEqual(self.sounds(), [("done.oga", 40000)])


class Tick(TabBarCase):
    """State changes going through the real timer function."""

    def test_working_to_done_in_a_background_tab_chimes_and_bursts(self):
        tb = self.tb
        a, b = FakeTab(), FakeTab(FakeWindow("working"))
        self.window(a, b, active=0)
        tb._tick()                                    # first sight: no noise for existing states
        tb._tick()
        b.windows[0].program_status.state = "done"
        tb._tick()
        self.assertEqual(self.sounds(), [("done.oga", 40000)])
        self.assertIn(b.id, tb._sparkle_start)

    def test_existing_states_at_load_make_no_noise(self):
        self.window(FakeTab(), FakeTab(FakeWindow("blocked")), FakeTab(FakeWindow("error")))
        self.tb._tick()
        self.tb._tick()
        self.assertEqual(self.sounds(), [])

    def test_needs_you_then_one_soft_reminder(self):
        tb = self.tb
        a, b = FakeTab(), FakeTab(FakeWindow())
        self.window(a, b, active=0)
        tb._tick()
        b.windows[0].program_status.state = "blocked"
        tb._tick()
        self.assertEqual(self.sounds(), [("needs-you.oga", 40000)])
        tb._blocked_since[b.id] -= tb.REMIND_AFTER + 1
        tb._last_sound.update(at=-99.0)
        tb._tick()
        tb._tick()
        self.assertEqual(self.sounds()[1:], [("needs-you.oga", 28000)])   # once, softer

    def test_needs_you_never_asks_the_desktop_for_attention(self):
        # COSMIC answers kitty's attention request by raising and focusing kitty (seen 2026-11-22):
        # it would steal focus while you type elsewhere. The sound and the cat do the telling.
        with open(TAB_BAR) as f:
            code = f.read()
        self.assertNotIn("request_attention", code)
        self.assertNotIn("request_window_attention", code)
        a, b = FakeTab(), FakeTab(FakeWindow())
        self.window(a, b, active=0)
        self.tb._tick()
        self.focused = 0                              # you're in another app
        b.windows[0].program_status.state = "blocked"
        self.tb._tick()
        self.assertEqual([f for f, _ in self.sounds()], ["needs-you.oga"])

    def test_no_reminder_once_you_have_looked(self):
        tb = self.tb
        a, b = FakeTab(), FakeTab(FakeWindow())
        tm = self.window(a, b, active=0)
        tb._tick()
        b.windows[0].program_status.state = "blocked"
        tb._tick()
        tm.active_tab = b                             # you looked at it
        tb._tick()
        tm.active_tab = a
        tb._blocked_since[b.id] -= tb.REMIND_AFTER + 1
        tb._last_sound.update(at=-99.0)
        tb._tick()
        self.assertEqual(len(self.sounds()), 1)

    def test_closed_tabs_are_forgotten(self):
        tb = self.tb
        a, b = FakeTab(), FakeTab(FakeWindow("working"))
        tm = self.window(a, b)
        tb._tick()
        self.assertIn(b.id, tb._working_tabs)
        tm.tabs.remove(b)
        tb._tick()
        self.assertNotIn(b.id, tb._working_tabs)
        self.assertFalse(tb._cat["working"])


    def test_a_command_under_the_search_box_keeps_running(self):
        # the search box (an overlay) over a tab running a build: the build hasn't ended, so no
        # sparkle, and no "done" chime when the box is left open there and you're in another tab
        # (the overlay's foreground is its own program, which isn't running a command)
        tb = self.tb
        a, b = FakeTab(), FakeTab()
        self.window(a, b, active=0)
        under = b.windows[0]
        with mock.patch.object(tb, "_plain_command_running", lambda w: w is under):
            tb._tick()
            self.assertIn(b.id, tb._running)
            top = FakeWindow()
            b.windows.append(top)
            b.active_window, b.active_window_for_cwd = top, under
            tb._running[b.id] -= tb.LONG_JOB + 1
            tb._tick()
            tb._tick()
        self.assertIn(b.id, tb._running)
        self.assertNotIn(b.id, tb._sparkle_start)
        self.assertEqual(self.sounds(), [])


class AgentMarkRecheck(TabBarCase):
    """A restart reopens every tab at once, and an agent can still be starting when the sidebar
    first draws its tab. That empty answer must not stand until some later redraw (it once took 6 s)."""

    def setUp(self):
        super().setUp()
        self.clock = [100.0]
        self.time = mock.patch.object(self.tb.time, "monotonic", lambda: self.clock[0])
        self.time.start()
        self.names = {}
        self.looks = []

        def fg(w):
            self.looks.append(w.id)
            return self.names.get(w.id, "kitten")
        self.fg = mock.patch.object(self.tb, "_foreground_name", fg)
        self.fg.start()
        self.cat = mock.patch.object(self.tb, "_cat_face", lambda: "=^.^=")   # a still cat: only
        self.cat.start()                                                      # marks ask to redraw
        self.tb._cat["drawn"] = "=^.^="

    def tearDown(self):
        self.cat.stop()
        self.fg.stop()
        self.time.stop()
        super().tearDown()

    def tick_at(self, t):
        self.clock[0] = 100.0 + t
        self.tb._tick()

    def test_a_mark_that_was_still_starting_appears_within_a_second(self):
        tb = self.tb
        a, b = FakeTab(), FakeTab()
        tm = self.window(a, b)
        self.tick_at(0)                                 # the new kitty's first tick: windows seen
        self.assertEqual(tb._agent_mark(b.id), "")      # drawn while kitten still starts the agent
        self.names[b.windows[0].id] = "claude"          # the agent is up now; nothing redraws by itself
        dirty = tm.dirty
        self.tick_at(0.25)
        self.assertEqual(tm.dirty, dirty)               # too soon to look again
        self.tick_at(0.5)
        self.assertEqual(tb._agents[b.id][1], "✳")
        self.assertEqual(tm.dirty, dirty + 1)           # redrawn once, with the mark
        self.tick_at(0.75)
        self.assertEqual(tm.dirty, dirty + 1)           # and not again: it's known now

    def test_no_agent_costs_a_few_looks_and_no_redraws(self):
        tb = self.tb
        a = FakeTab()
        tm = self.window(a)
        self.tick_at(0)
        tb._agent_mark(a.id)
        dirty, looks = tm.dirty, len(self.looks)
        for i in range(1, 160):                         # 20 s of ticks
            self.tick_at(i * tb.TICK)
        self.assertEqual(tm.dirty, dirty)               # an idle sidebar stays idle
        self.assertLessEqual(len(self.looks) - looks, tb.AGENT_YOUNG / tb.AGENT_RECHECK + 1)
        self.names[a.windows[0].id] = "claude"          # an old window: the usual 3 s cache
        looks = len(self.looks)
        self.tick_at(30)
        self.assertEqual(len(self.looks), looks)

    def test_closed_windows_are_forgotten(self):
        a, b = FakeTab(), FakeTab()
        tm = self.window(a, b)
        self.tick_at(0)
        self.assertIn(b.windows[0].id, self.tb._born)
        tm.tabs.remove(b)
        self.tick_at(1)
        self.assertNotIn(b.windows[0].id, self.tb._born)


class Draw(TabBarCase):
    def data(self, tab, index, title, wd):
        acc = types.SimpleNamespace(program_status="", last_focused_progress_percent="", active_wd=wd)
        return {"fmt": Fmt(), "tab": acc, "tab_id": tab.id, "index": index, "title": title,
                "max_title_length": 30, "activity_symbol": "", "bell_symbol": ""}

    def test_two_lines_aligned(self):
        a, b = FakeTab(), FakeTab()
        self.window(a, b, active=0)
        out = self.tb.draw_title(self.data(b, 12, "✳ Write release notes", self.tb.HOME + "/work/beta"))
        line1, line2 = out.split("\n")
        plain1 = self.strip(line1)
        self.assertTrue(plain1.startswith(" 12   Write release notes"), plain1)
        self.assertEqual(self.strip(line2), "      work/beta")

    def test_long_names_fit_the_sidebar(self):
        a = FakeTab()
        self.window(FakeTab(), a, active=0)
        out = self.tb.draw_title(self.data(a, 2, "A renamed tab with quite a long title here", "/w/x"))
        self.assertLessEqual(self.tb._cells(self.strip(out.split("\n")[0])), 30)

    def repo(self, branch, worktree=False):
        root = os.path.join(self.tmp.name, "repo-" + branch.replace("/", "-"))
        os.makedirs(os.path.join(root, ".git"), exist_ok=True)
        with open(os.path.join(root, ".git", "HEAD"), "w") as f:
            f.write(f"ref: refs/heads/{branch}\n")
        if worktree:                    # a worktree's .git is a file pointing at the real HEAD's folder
            wt = root + "-wt"
            os.makedirs(os.path.join(wt, "src"), exist_ok=True)
            with open(os.path.join(wt, ".git"), "w") as f:
                f.write(f"gitdir: {os.path.join(root, '.git')}\n")
            return os.path.join(wt, "src")
        os.makedirs(os.path.join(root, "src"), exist_ok=True)
        return os.path.join(root, "src")

    def test_agent_mark_under_the_status_icon(self):
        a, b = FakeTab(), FakeTab()
        self.window(a, b, active=0)
        names = {b.windows[0].id: "claude"}
        with mock.patch.object(self.tb, "_foreground_name", lambda w: names.get(w.id, "bash")):
            line2 = self.strip(self.tb.draw_title(self.data(b, 2, "✳ Fix", "/w/x")).split("\n")[1])
            self.assertEqual(line2, "    ✳ w/x")
            self.assertEqual(self.tb._agent_mark(a.id), "")

    def test_agent_found_after_an_option_value(self):
        argv = b"node\0--require\0/x/hook.js\0/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js\0"
        w = types.SimpleNamespace(child=types.SimpleNamespace(child_fd=5))
        with mock.patch("os.tcgetpgrp", lambda fd: 42), \
                mock.patch("builtins.open", mock.mock_open(read_data=argv)):
            self.assertEqual(self.tb._foreground_name(w), "claude")

    def test_foreground_name_sees_through_node(self):
        argv = b"node\0--no-warnings\0/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js\0"
        w = types.SimpleNamespace(child=types.SimpleNamespace(child_fd=5))
        with mock.patch("os.tcgetpgrp", lambda fd: 42), \
                mock.patch("builtins.open", mock.mock_open(read_data=argv)):
            self.assertEqual(self.tb._foreground_name(w), "claude")

    def procs(self, table):
        """Patch tab_bar's /proc readers with a fake table: pid -> (argv, pgrp, children)."""
        def get(pid, i):
            if pid not in table:
                raise OSError("gone")
            return table[pid][i]
        return mock.patch.multiple(self.tb, _proc_argv=lambda pid: get(pid, 0),
                                   _proc_pgrp=lambda pid: get(pid, 1), _proc_children=lambda pid: get(pid, 2))

    def test_an_agent_under_a_shell_in_the_same_group_is_found(self):
        # a tab kitty-relaunch reopened: launch --hold leads with kitten run-shell, then bash -lc
        # runs claude, all in kitten's process group (issue #1: the ✳ mark was lost)
        w = types.SimpleNamespace(child=types.SimpleNamespace(child_fd=5))
        table = {42: (["/opt/kitty/bin/kitten", "run-shell", "--shell=/bin/bash", "bash", "-lc", "claude --resume x"], 42, [43]),
                 43: (["/usr/bin/bash", "-lc", "claude --resume x; echo"], 42, [44]),
                 44: (["node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js", "--resume", "x"], 42, [])}
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.procs(table):
            self.assertEqual(self.tb._foreground_name(w), "claude")
        table[42] = (["bash", "-lc", "omp --continue"], 42, [44])
        table[44] = (["omp", "--continue"], 42, [])
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.procs(table):
            self.assertEqual(self.tb._foreground_name(w), "omp")

    def test_a_shell_at_its_prompt_stays_the_shell(self):
        # an interactive shell's background job (its own group) is not the tab's program
        w = types.SimpleNamespace(child=types.SimpleNamespace(child_fd=5))
        table = {42: (["-bash"], 42, [50]), 50: (["claude"], 50, [])}
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.procs(table):
            self.assertEqual(self.tb._foreground_name(w), "-bash")
        table = {42: (["bash", "-c", "make"], 42, [43]), 43: (["make"], 42, [])}   # not an agent
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.procs(table):
            self.assertEqual(self.tb._foreground_name(w), "bash")

    def test_only_a_shell_or_kitten_is_looked_below(self):
        w = types.SimpleNamespace(child=types.SimpleNamespace(child_fd=5))
        table = {42: (["vim", "x"], 42, [43]), 43: (["claude"], 42, [])}
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.procs(table):
            self.assertEqual(self.tb._foreground_name(w), "vim")

    def test_looking_below_is_bounded_and_survives_vanishing_processes(self):
        w = types.SimpleNamespace(child=types.SimpleNamespace(child_fd=5))
        table = {42: (["bash", "-c", "x"], 42, list(range(100, 160)) + [7])}
        table.update({i: (["sleep", "1"], 42, []) for i in range(100, 160)})
        table[7] = (["claude"], 42, [])             # past the limit: not looked at
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.procs(table):
            self.assertEqual(self.tb._foreground_name(w), "bash")
        table = {42: (["bash", "-c", "x"], 42, [43, 44]), 44: (["claude"], 42, [])}   # 43 exited meanwhile
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.procs(table):
            self.assertEqual(self.tb._foreground_name(w), "claude")

    @unittest.skipUnless(os.path.isdir("/proc/self"), "no /proc here (macOS: MacOS covers that path)")
    def test_reads_the_real_proc(self):
        # this test's own process: its group, argv and the children of every thread
        import signal
        child = os.posix_spawnp("sleep", ["sleep", "5"], dict(os.environ))   # (subprocess is mocked here)
        try:
            me = os.getpid()
            self.assertEqual(self.tb._proc_pgrp(me), os.getpgrp())
            self.assertTrue(self.tb._proc_argv(me))
            if os.path.exists(f"/proc/{me}/task/{me}/children"):
                self.assertIn(child, self.tb._proc_children(me))
        finally:
            os.kill(child, signal.SIGKILL)
            os.waitpid(child, 0)

    def test_branch_shows_unless_main(self):
        self.assertEqual(self.tb._git_branch(self.repo("fix-login")), "fix-login")
        self.assertEqual(self.tb._git_branch(self.repo("main")), "")
        self.assertEqual(self.tb._git_branch(self.repo("feat/x", worktree=True)), "feat/x")
        self.assertEqual(self.tb._git_branch(self.tmp.name), "")

    def test_branch_on_the_folder_line_fits(self):
        a = FakeTab()
        self.window(FakeTab(), a, active=0)
        wd = self.repo("a-really-long-feature-branch-name")
        line2 = self.strip(self.tb.draw_title(self.data(a, 2, "x", wd)).split("\n")[1])
        self.assertIn("⌥ a-real", line2)
        self.assertLessEqual(self.tb._cells(line2), 30)

    def overlay(self, tab, cwd, title):
        """Open an overlay (the search box) over the tab's window, as kitty 0.51 does: the overlay
        joins the window's group on top and becomes the active window; the group's main window,
        Tab.active_window_for_cwd, stays the one underneath. Returns the overlay."""
        under = tab.windows[0]
        under.title, under.get_cwd_of_child = title, lambda: cwd
        top = FakeWindow()
        top.title = title                     # --title current: a copy of the window's title
        top.get_cwd_of_child = lambda: "/w/start"     # kitty's start folder (no --cwd)
        tab.windows.append(top)
        tab.active_window, tab.active_window_for_cwd = top, under
        return top

    def test_the_search_box_keeps_the_folder_mark_and_branch_of_the_window_under_it(self):
        a, b = FakeTab(), FakeTab()
        self.window(a, b, active=1)
        wd = self.repo("fix-parser")
        top = self.overlay(b, wd, "✳ Write release notes")
        names = {b.windows[0].id: "claude", top.id: "python3"}
        # what kitty hands the template while the box is open: the overlay's folder (and title)
        data = self.data(b, 2, "tab-finder", "/w/start")
        with mock.patch.object(self.tb, "_foreground_name", lambda w: names.get(w.id, "bash")):
            line1, line2 = (self.strip(x) for x in self.tb.draw_title(data).split("\n"))
        self.assertIn("Write release notes", line1)
        self.assertEqual(line2.split()[::2], ["✳", "⌥"])
        self.assertTrue(line2.split()[1].endswith("parser/src") and line2.endswith("fix-parser"), line2)
        b.name = "Mine"                       # a renamed tab keeps its name (kitty's title is it)
        with mock.patch.object(self.tb, "_foreground_name", lambda w: names.get(w.id, "bash")):
            line1 = self.strip(self.tb.draw_title(self.data(b, 2, "Mine", "/w/start")).split("\n")[0])
        self.assertIn("Mine", line1)
        # closed again: back to what kitty says about the tab's active window
        b.windows.remove(top)
        b.active_window = b.active_window_for_cwd = b.windows[0]
        self.tb._agents.clear()
        line2 = self.strip(self.tb.draw_title(self.data(b, 2, "x", "/w/other")).split("\n")[1])
        self.assertEqual(line2.split(), ["w/other"])

    def test_no_overlay_no_change(self):
        a = FakeTab()
        self.window(a)
        self.assertIsNone(self.tb._covered(a.id))
        self.assertIs(self.tb._base_window(a), a.windows[0])     # a kitty without active_window_for_cwd
        a.active_window_for_cwd = a.windows[0]
        self.assertIsNone(self.tb._covered(a.id))

    @staticmethod
    def strip(s):
        import re
        return re.sub(r"<[^>]*>|\x1b\[[0-9;]*m", "", s)


class CommandTitles(TabBarCase):
    """A running command's title is its command line (kitty's shell integration): the row shows its
    program and subcommand (config/command_title.py; the rule's own tests: test_command_title.py)."""
    MARK = "zq7PRIVzq"          # stands in for a password or token

    def tab_running(self, title, cmdline=None, **attrs):
        w = FakeWindow()
        w.title, w.last_cmd_cmdline, w.at_prompt, w.override_title = title, (
            title if cmdline is None else cmdline), False, None
        for k, v in attrs.items():
            setattr(w, k, v)
        t = FakeTab(w)
        t.name = ""
        return t

    data, strip = Draw.data, staticmethod(Draw.strip)

    def name(self, tab, title=None):
        out = self.tb.draw_title(self.data(tab, 1, title if title is not None else tab.windows[0].title, "/w/proj"))
        return self.strip(out.split("\n")[0])[6:].strip().removesuffix("×").strip()   # the active tab's ×

    def test_a_command_shows_its_program_and_subcommand(self):
        a = self.tab_running("git push https://me:" + self.MARK + "@git.test/x main")
        b = self.tab_running("API_KEY=" + self.MARK + " npm run build")
        c = self.tab_running("API_KEY=" + self.MARK)                          # nothing to name: the folder
        self.window(a, b, c)
        self.assertEqual(self.name(a), "git push")
        self.assertEqual(self.name(b), "npm run build")
        self.assertEqual(self.name(c), "proj")

    def test_titles_set_by_agents_and_people_stay(self):
        a = self.tab_running("✳ Fix the login bug", "claude")
        b = self.tab_running("make deploy " + self.MARK)
        b.name = "make deploy " + self.MARK                                    # you named it (Ctrl+Shift+R)
        c = self.tab_running("notes " + self.MARK, "make", override_title="notes " + self.MARK)
        self.window(a, b, c)
        self.assertEqual(self.name(a), "Fix the login bug")
        self.assertIn(self.MARK, self.name(b, b.name))
        self.assertIn(self.MARK, self.name(c))

    def test_the_moment_before_bash_reports_the_command(self):
        a = self.tab_running("API_KEY=" + self.MARK + " read -t 30 v", "ls", at_prompt=True)
        self.window(a)
        self.assertEqual(self.name(a), "read")

    def test_under_an_overlay_the_covered_window_decides(self):
        base = self.tab_running("mysql -p" + self.MARK).windows[0]
        sheet = FakeWindow()
        sheet.title, sheet.override_title, sheet.last_cmd_cmdline = base.title, base.title, ""
        t = FakeTab(base, sheet)
        t.name, t.active_window, t.active_window_for_cwd = "", sheet, base
        self.window(t)
        self.assertEqual(self.name(t, sheet.title), "mysql")

    def test_the_switch_and_the_timer(self):
        a = self.tab_running("make deploy KEY=" + self.MARK)
        tm = self.window(a)
        self.tb._tick()
        before = tm.dirty
        open(self.kitty_path("full-commands"), "w").close()                  # kitty-commands full
        self.tb._tick()
        self.assertGreater(tm.dirty, before)                                  # redrawn at once
        self.assertTrue(self.name(a).startswith("make deploy KEY=zq"), self.name(a))   # (cut to fit)
        os.remove(self.kitty_path("full-commands"))
        self.tb._tick()
        self.assertEqual(self.name(a), "make deploy")

    def test_the_fallback_row_never_shows_the_command_line(self):
        a = self.tab_running("make deploy KEY=" + self.MARK)
        self.window(a)
        with mock.patch.object(self.tb, "_draw_title", side_effect=RuntimeError):
            out = self.tb.draw_title(self.data(a, 1, a.windows[0].title, "/w/proj"))
        self.assertNotIn(self.MARK, out)
        self.assertIn("make deploy", out)

    def test_a_reported_command_needs_no_process_lookup(self):
        a = self.tab_running("make test")
        self.window(a)
        with mock.patch.object(self.tb, "_foreground_name", side_effect=AssertionError("looked up")):
            self.assertEqual(self.name(a), "make test")


class MacOS(TabBarCase):
    """The macOS paths (sys.platform darwin), tried on any system: afplay and the .wav sounds,
    osascript notifications, and the agent marks from kitty's own process helpers instead of /proc.
    (scripts/check-macos.sh runs the agent lookup against real processes on a Mac.)"""

    def setUp(self):
        super().setUp()
        self.tb.IS_MACOS = True
        for s in ("done", "done-2", "done-3", "needs-you", "error", "badge", "rank", "drop"):
            open(self.kitty_path(os.path.join("sounds", s + ".wav")), "w").close()
        self.system_sounds = os.path.join(self.tmp.name, "System-Sounds")
        os.makedirs(self.system_sounds)
        self.tb.MAC_SOUNDS = self.system_sounds
        # kitty's own helpers (kitty.child), faked: pid -> argv, and process group -> pids
        self.argv, self.group_of = {}, {}
        self.map_calls = 0
        child = types.ModuleType("kitty.child")

        def cmdline_of_pid(pid):
            if pid not in self.argv:
                raise ProcessLookupError(pid)
            return list(self.argv[pid])

        def process_group_map():
            self.map_calls += 1
            groups = {}
            for pid, pg in self.group_of.items():
                groups.setdefault(pg, []).append(pid)
            return groups
        child.cmdline_of_pid, child.process_group_map = cmdline_of_pid, process_group_map
        sys.modules["kitty.child"] = child          # (undone with the rest of the fake kitty)
        self.no_proc = mock.patch("builtins.open", side_effect=self.refuse_proc)
        self._open = open

    def refuse_proc(self, path, *a, **k):
        if str(path).startswith("/proc"):
            raise AssertionError(f"read {path} on macOS")
        return self._open(path, *a, **k)

    def procs(self, table):
        """pid -> (argv, process group)"""
        self.argv = {p: v[0] for p, v in table.items()}
        self.group_of = {p: v[1] for p, v in table.items()}
        self.tb._groups.update(at=-99.0, map={})

    def afplays(self):
        return [c.args[0] for c in self.played.call_args_list if c.args[0][0] == "afplay"]

    def test_sounds_play_the_wav_with_afplay_at_the_linux_level(self):
        self.tb._play("blocked")
        self.assertEqual(self.afplays(), [["afplay", "-v", "0.22737368", self.kitty_path("sounds/needs-you.wav")]])
        self.assertFalse([c for c in self.played.call_args_list if c.args[0][0] == "paplay"])
        with open(self.tb.VOLUME_FILE, "w") as f:
            f.write("50")
        self.tb._last_sound.update(at=-99.0, priority=-1)
        self.tb._play("remind")                      # 28000 * 50% = 14000 on paplay's scale
        self.assertEqual(self.afplays()[-1][2], "0.00974865")

    def test_the_lowest_volume_is_quiet_not_silent(self):
        # kitty-sounds volume 5: the reminder (28000 * 5% = 1400) once rounded to -v 0.0000
        with open(self.tb.VOLUME_FILE, "w") as f:
            f.write("5")
        for kind in ("done", "remind"):
            self.tb._last_sound.update(at=-99.0, priority=-1)
            self.tb._play(kind)
            gain = float(self.afplays()[-1][2])
            self.assertGreater(gain, 0, self.afplays()[-1])
        self.assertEqual([a[2] for a in self.afplays()], ["0.00002842", "0.00000975"])

    def test_without_the_wav_it_uses_macos_own_sound(self):
        os.remove(self.kitty_path("sounds/error.wav"))
        self.assertEqual(self.tb._sound_file("error"), "")          # no Basso.aiff here either
        open(os.path.join(self.system_sounds, "Basso.aiff"), "w").close()
        self.assertEqual(self.tb._sound_file("error"), os.path.join(self.system_sounds, "Basso.aiff"))
        self.assertEqual(self.tb._sound_file("drop"), self.kitty_path("sounds/drop.wav"))

    def test_classic_means_macos_own_sounds(self):
        open(self.tb.CLASSIC_FILE, "w").close()
        for name in ("Glass.aiff", "Ping.aiff"):
            open(os.path.join(self.system_sounds, name), "w").close()
        self.assertEqual(self.tb._sound_file("done"), os.path.join(self.system_sounds, "Glass.aiff"))
        self.assertEqual(self.tb._sound_file("blocked"), os.path.join(self.system_sounds, "Ping.aiff"))
        self.assertEqual(self.tb._sound_file("drop"), "")

    def test_notifications_pass_the_text_as_arguments(self):
        title, body = 'Badge "x" \\ & end tell', "line one\n-two"
        self.tb._notify(title, body)
        cmd = [c.args[0] for c in self.played.call_args_list if c.args[0][0] == "osascript"][0]
        self.assertEqual(cmd[-2:], [title, body])
        script = [a for i, a in enumerate(cmd) if i and cmd[i - 1] == "-e"]
        self.assertTrue(all(title not in a and body not in a for a in script), script)
        self.assertEqual(self.tb._notify_cmd("-x", "y")[-2], " -x")     # never read as an option
        self.played.reset_mock()
        with mock.patch.dict(os.environ, {"NINELIVES_QUIET": "1"}):
            self.tb._notify("t", "b")
        self.assertFalse(self.played.called)

    def test_an_agent_below_a_shell_is_found_without_proc(self):
        w = types.SimpleNamespace(child=types.SimpleNamespace(child_fd=5))
        self.procs({42: (["/Applications/kitty.app/Contents/MacOS/kitten", "run-shell", "bash", "-lc", "claude"], 42),
                    43: (["/bin/bash", "-lc", "claude --resume x; echo"], 42),
                    44: (["node", "/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/cli.js"], 42),
                    50: (["claude"], 50)})                      # another group: not this tab's
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.no_proc:
            self.assertEqual(self.tb._foreground_name(w), "claude")
        self.procs({42: (["-zsh"], 42), 50: (["claude"], 50)})  # a background job at the prompt
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.no_proc:
            self.assertEqual(self.tb._foreground_name(w), "-zsh")
        self.procs({42: (["omp", "--continue"], 42)})
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.no_proc:
            self.assertEqual(self.tb._foreground_name(w), "omp")

    def test_one_process_scan_serves_every_tab(self):
        tabs = [FakeTab() for _ in range(6)]
        for t in tabs:
            t.windows[0].child = types.SimpleNamespace(child_fd=5)
        self.window(*tabs)
        self.procs({42: (["bash"], 42), 43: (["claude"], 42)})
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.no_proc:
            self.assertEqual([self.tb._agent_mark(t.id) for t in tabs], ["✳"] * 6)
        self.assertEqual(self.map_calls, 1)

    def test_looking_below_is_bounded_and_survives_vanishing_processes(self):
        w = types.SimpleNamespace(child=types.SimpleNamespace(child_fd=5))
        table = {42: (["bash"], 42), 999: (["claude"], 42)}        # past the limit: not looked at
        table.update({i: (["sleep", "1"], 42) for i in range(100, 160)})
        self.procs(table)
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.no_proc:
            self.assertEqual(self.tb._foreground_name(w), "bash")
        self.procs({42: (["bash"], 42), 43: (["claude"], 42)})
        del self.argv[43]                                          # exited meanwhile
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.no_proc:
            self.assertEqual(self.tb._foreground_name(w), "bash")

    def test_without_kitty_child_nothing_breaks(self):
        del sys.modules["kitty.child"]
        sys.modules["kitty.child"] = None                          # a kitty that renamed it
        w = types.SimpleNamespace(child=types.SimpleNamespace(child_fd=5))
        with mock.patch("os.tcgetpgrp", lambda fd: 42):
            self.assertEqual(self.tb._foreground_name(w), "")

    def test_plain_command_check_reads_one_argv_and_never_scans(self):
        w = types.SimpleNamespace(child=types.SimpleNamespace(child_fd=5, pid=40),
                                  screen=types.SimpleNamespace(is_main_linebuf=lambda: True))
        self.procs({42: (["make", "-j8"], 42)})
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.no_proc:
            self.assertTrue(self.tb._plain_command_running(w))
        self.procs({42: (["/bin/zsh"], 42)})
        with mock.patch("os.tcgetpgrp", lambda fd: 42), self.no_proc:
            self.assertFalse(self.tb._plain_command_running(w))
        self.assertEqual(self.map_calls, 0)


class Quests(TabBarCase):
    def test_a_shortcut_earns_its_badge_once(self):
        tb = self.tb
        tb._quest_action("toggle_layout", ["stack"])
        tb._quest_action("toggle_layout", ["stack"])
        with open(os.path.join(self.tmp.name, "state", "badges")) as f:
            self.assertEqual([l.split("\t")[0] for l in f], ["zoom"])
        self.assertEqual([s for s, _ in self.sounds()], ["badge.oga"])

    def test_ten_uses_master_a_shortcut(self):
        tb = self.tb
        for i in range(tb.MASTER_AT):
            tb._last_sound.update(at=-99.0, priority=-1)          # no coalescing between uses
            tb._quest_action("toggle_layout", ["stack"])
            if i == tb.MASTER_AT - 2:
                self.assertNotIn("mastered", tb._visible(tb._quest_line()))
        self.assertEqual(tb._uses["zoom"], tb.MASTER_AT)
        self.assertEqual([s for s, _ in self.sounds()], ["badge.oga", "badge.oga"])   # earned, mastered
        self.assertIn("mastered: Zoom Lens!", tb._visible(tb._quest_line()))
        with open(os.path.join(self.tmp.name, "state", "uses")) as f:
            self.assertEqual(f.read(), f"zoom\t{tb.MASTER_AT}\n")
        with open(os.path.join(self.tmp.name, "state", "quests.txt")) as f:
            text = tb._visible(f.read())
        self.assertIn("✪ Zoom Lens", text)
        self.assertIn("1 mastered", text)

    def test_uses_counted_but_clicks_are_not(self):
        tb = self.tb
        tb._quest_action("toggle_layout", ["stack"])
        tb._clicking["on"] = True
        tb._quest_action("toggle_layout", ["stack"])
        tb._clicking["on"] = False
        self.assertEqual(tb._uses["zoom"], 1)

    def test_kitty_quests_shows_the_current_tally(self):
        tb = self.tb
        for _ in range(3):
            tb._quest_action("toggle_layout", ["stack"])
        with open(os.path.join(self.tmp.name, "state", "quests.txt")) as f:
            row = next(l for l in tb._visible(f.read()).splitlines() if "Zoom Lens" in l)
        self.assertIn(f"3/{tb.MASTER_AT}", row)

    def test_launch_actions_map_to_their_quests(self):
        tb = self.tb
        tb._quest_action("launch", ["--location=vsplit", "--cwd=current"])
        tb._quest_action("launch", ["--type=overlay", "~/.config/kitty/shortcuts.sh"])
        self.assertEqual(set(tb._earned), {"split", "help"})
        tb._quest_action("launch", ["--type=background", "--allow-remote-control", "sh", "-c",
                                    'exec python3 "${KITTY_CONFIG_DIRECTORY}/tab-finder.py" waiting'])
        self.assertIn("waiting", tb._earned)

    def test_fourth_badge_is_a_new_rank(self):
        tb = self.tb
        for q in ("split", "panes", "zoom"):
            tb._earned[q] = "2026-11-01"
        tb._quest_action("goto_tab", [1])
        self.assertEqual([s for s, _ in self.sounds()], ["rank.oga"])
        self.assertTrue(tb._badge_shown["rank"])
        self.assertIn("new rank: House Cat", tb._quest_line())

    def test_quests_off_earns_nothing(self):
        open(self.kitty_path("quests-off"), "w").close()
        self.tb._quest_action("toggle_layout", ["stack"])
        self.assertEqual(self.tb._earned, {})
        self.assertEqual(self.tb._quest_line(), "")


if __name__ == "__main__":
    unittest.main()
