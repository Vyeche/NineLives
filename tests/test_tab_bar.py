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
import sys
import tempfile
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
        self.played.reset_mock()
        self.tb._last_sound.update(at=-99.0, priority=-1)

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
    """The search row on top (❯ Search tabs…  ⚠  +) and the × on the current tab."""
    def test_search_row_and_its_buttons(self):
        for blocked in (0, 2):
            self.tb._cat["blocked"] = blocked
            row = self.tb._visible(self.tb._search_row())
            self.assertTrue(row.startswith("  ❯   Search tabs…"))
            self.assertEqual(self.tb._cells(row), 30)           # + in the current tab's × column
            cols = self.tb._buttons["cols"]
            for c0, c1, name in cols:
                part = row[c0:c1 + 1]
                self.assertIn({"search": "Search", "waiting": "⚠", "new": "+"}[name], part, (name, part))

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
        self.assertTrue(line1.endswith("×"), line1)
        self.assertEqual(self.tb._cells(line1), 30)
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
        # a press elsewhere (on a tab) released on a button does nothing and goes to kitty
        self.assertFalse(self.tb._sidebar_click(tm, 50, 300, 0, 1))
        self.assertFalse(self.tb._sidebar_click(tm, c0 * 10 + 5, 5, 0, 2))
        self.assertEqual(len(ran), 1)

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

    @staticmethod
    def strip(s):
        import re
        return re.sub(r"<[^>]*>|\x1b\[[0-9;]*m", "", s)


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
