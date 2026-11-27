#!/usr/bin/env python3
"""Unit tests for config/settings.py (the NineLives settings list: Ctrl+Shift+F2, the sidebar's ⚙,
`ninelives`). A temp config and state folder, no kitty, no terminal, no sound:
    python3 -m unittest discover -s tests          (or: python3 tests/test_settings.py)"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, "..", "config", "settings.py")


def load():
    spec = importlib.util.spec_from_file_location("nl_settings", SETTINGS)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def plain(s: str) -> str:
    return re.sub("\x1b\\[[0-9;?]*[a-zA-Z]", "", s)


class SettingsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conf = os.path.join(self.tmp.name, "kitty")
        self.state = os.path.join(self.tmp.name, "state")
        os.makedirs(os.path.join(self.conf, "sounds"))
        os.makedirs(self.state)
        env = {k: v for k, v in os.environ.items() if k not in ("KITTY_LISTEN_ON", "NINELIVES_QUIET", "VISUAL", "EDITOR")}
        env.update(HOME=self.tmp.name, KITTY_CONFIG_DIRECTORY=self.conf, NINELIVES_STATE=self.state)
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()
        self.popen = mock.patch("subprocess.Popen")
        self.played = self.popen.start()
        self.s = load()
        self.s.IS_MACOS = False

    def tearDown(self):
        self.popen.stop()
        self.env.stop()
        self.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.conf, name)

    def touch(self, name):
        open(self.path(name), "w").close()

    def ours(self, name):
        """A NineLives sound file in the temp config folder."""
        open(os.path.join(self.conf, "sounds", name), "w").close()

    def commands(self):
        return [c.args[0] for c in self.played.call_args_list]


class Reading(SettingsCase):
    def test_folders_follow_the_environment(self):
        self.assertEqual(self.s.conf_dir(), self.conf)
        self.assertEqual(self.s.state_dir(), self.state)
        del os.environ["KITTY_CONFIG_DIRECTORY"]
        os.environ["XDG_CONFIG_HOME"] = "/x/cfg"
        self.assertEqual(self.s.conf_dir(), "/x/cfg/kitty")

    def test_defaults_with_no_files(self):
        got = {k: self.s.value(k, self.conf, self.state, compact=True) for k in self.s.ROWS if k and k != "edit"}
        self.assertEqual(got, {"sounds": "on", "volume": "100%", "soundset": "NineLives", "cat": "shown",
                               "cattalk": "on", "catsounds": "on", "quests": "on", "buttons": "shown", "commands": "off", "tips": "on"})

    def test_switch_files_read_back(self):
        for key, (_label, name, (on, off), _d) in self.s.TOGGLES.items():
            self.touch(name)
            self.assertFalse(self.s.is_on(key, self.conf), key)
            self.assertEqual(self.s.value(key, self.conf, self.state, True), off)
            os.remove(self.path(name))
            self.assertEqual(self.s.value(key, self.conf, self.state, True), on)

    def test_volume_is_clamped_and_a_bad_file_ignored(self):
        for text, want in (("40\n", 40), ("3", 5), ("250", 100), ("loud", 100), ("", 100)):
            with open(self.path("sounds-volume"), "w") as f:
                f.write(text)
            self.assertEqual(self.s.volume(self.conf), want, text)

    def test_volume_bar_and_quest_progress(self):
        self.s.set_volume(self.conf, 50)
        self.assertEqual(self.s.value("volume", self.conf, self.state), "■■■■■□□□□□  50%")
        self.assertEqual(self.s.value("volume", self.conf, self.state, compact=True), "50%")
        with open(os.path.join(self.state, "badges"), "w") as f:
            f.write("zoom\t2026-11-20\nsplit\t2026-11-21\n")
        self.assertEqual(self.s.value("quests", self.conf, self.state), "on · ★2/16")
        self.touch("quests-off")
        self.assertEqual(self.s.value("quests", self.conf, self.state), "off")

    def test_desktop_sounds_are_macos_sounds_on_a_mac(self):
        self.touch("sounds-classic")
        self.assertEqual(self.s.value("soundset", self.conf, self.state), "desktop")
        self.s.IS_MACOS = True
        self.assertEqual(self.s.value("soundset", self.conf, self.state), "macOS")

    def test_stale_tab_bar_notice(self):
        with open(self.path("tab_bar.py"), "w") as f:
            f.write("# new\n")
        self.assertEqual(self.s.stale_notice(self.conf, self.state), "")          # nothing running
        import hashlib
        with open(os.path.join(self.state, "tab_bar.running"), "w") as f:
            f.write(hashlib.sha1(b"# new\n").hexdigest() + "\n")
        self.assertEqual(self.s.stale_notice(self.conf, self.state), "")
        with open(os.path.join(self.state, "tab_bar.running"), "w") as f:
            f.write("older\n")
        self.assertIn("restart kitty", self.s.stale_notice(self.conf, self.state))

    def test_the_cat_talks_on_events_only_or_off(self):
        conf = self.conf
        self.assertEqual(self.s.value("cattalk", conf, self.state), "on")
        seen = []
        for _ in range(3):
            self.assertTrue(self.s.change("cattalk", conf, 1))
            seen.append(self.s.value("cattalk", conf, self.state))
        self.assertEqual(seen, ["events only", "off", "on"])      # round and round, like the arrows
        self.s.change("cattalk", conf, -1)
        with open(os.path.join(conf, "cat-talk"), encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "off")             # what tab_bar.py and kitty-cat talk read
        self.assertEqual(self.s.value("cattalk", conf, self.state, compact=True), "off")
        self.s.change("cattalk", conf, 1)
        self.assertFalse(os.path.exists(os.path.join(conf, "cat-talk")))   # on: no file

    def test_list(self):
        self.touch("cat-off")
        self.s.set_volume(self.conf, 35)
        self.assertEqual(self.s.listing(self.conf, self.state).splitlines(),
                         ["Sounds: on", "Volume: 35%", "Sound set: NineLives", "The cat: hidden",
                          "The cat talks: on", "Cat sounds: on", "Quests: on · ★0/16", "Sidebar buttons: shown", "Full commands in tab names: off",
                          "Prompt tips: on"])

    def test_full_commands_is_off_until_its_file_is_there(self):
        # the other switches are on while their file is missing; this one is the other way round:
        # short tab names by default, full-commands (kitty-commands full) turns whole lines on
        self.assertEqual(self.s.value("commands", self.conf, self.state), "off")
        self.assertTrue(self.s.change("commands", self.conf, 1))
        self.assertTrue(os.path.exists(self.path("full-commands")))
        self.assertEqual(self.s.value("commands", self.conf, self.state), "on")
        self.assertTrue(self.s.change("commands", self.conf, 1))
        self.assertFalse(os.path.exists(self.path("full-commands")))
        self.played.assert_not_called()                              # no chime for this one


class Changing(SettingsCase):
    def test_each_toggle_writes_and_removes_its_file(self):
        for key, (_label, name, _values, _d) in self.s.TOGGLES.items():
            self.assertTrue(self.s.change(key, self.conf, 1))
            self.assertTrue(os.path.exists(self.path(name)), key)
            self.assertTrue(self.s.change(key, self.conf, -1))       # ← flips back too
            self.assertFalse(os.path.exists(self.path(name)), key)

    def test_volume_steps_by_five_and_stops_at_the_ends(self):
        s, c = self.s, self.conf
        s.set_volume(c, 50)
        s.change("volume", c, 1)
        self.assertEqual(s.volume(c), 55)
        s.change("volume", c, -1)
        s.change("volume", c, -1)
        self.assertEqual(s.volume(c), 45)
        s.set_volume(c, 42)                                  # an odd value set by hand snaps to 5s
        s.change("volume", c, 1)
        self.assertEqual(s.volume(c), 45)
        s.set_volume(c, 42)
        s.change("volume", c, -1)
        self.assertEqual(s.volume(c), 40)
        s.set_volume(c, 100)
        self.assertFalse(s.change("volume", c, 1))           # → at the top: stays
        self.assertTrue(s.change("volume", c, 1, wrap=True))  # Enter at the top: back to 5
        self.assertEqual(s.volume(c), 5)
        self.assertFalse(s.change("volume", c, -1))
        with open(self.path("sounds-volume")) as f:
            self.assertEqual(f.read(), "5\n")                # as kitty-sounds volume writes it
        self.assertFalse(os.path.exists(self.path("sounds-volume.tmp")))

    def test_the_edit_row_changes_nothing(self):
        self.assertFalse(self.s.change("edit", self.conf, 1))
        self.assertEqual(sorted(os.listdir(self.conf)), ["sounds"])


class Preview(SettingsCase):
    def test_a_new_volume_plays_our_chime_at_that_level(self):
        self.ours("done.oga")
        self.s.change("volume", self.conf, -1)               # 100 -> 95
        self.assertEqual(self.commands(), [["paplay", "--volume=38000", self.path("sounds/done.oga")]])
        kw = self.played.call_args.kwargs
        self.assertEqual((kw["stdout"], kw["stderr"], kw["start_new_session"]),
                         (subprocess.DEVNULL, subprocess.DEVNULL, True))

    def test_turning_sounds_on_plays_and_off_does_not(self):
        self.ours("done.oga")
        self.s.change("sounds", self.conf)                   # off
        self.assertEqual(self.commands(), [])
        self.s.change("volume", self.conf, -1)               # muted: no preview
        self.assertEqual(self.commands(), [])
        self.s.change("sounds", self.conf)                   # on again
        self.assertEqual(len(self.commands()), 1)

    def test_other_settings_are_silent(self):
        self.ours("done.oga")
        for key in ("cat", "quests", "buttons", "tips"):
            self.s.change(key, self.conf)
        self.assertEqual(self.commands(), [])

    def test_classic_plays_the_desktop_chime(self):
        self.ours("done.oga")
        classic = os.path.join(self.tmp.name, "freedesktop")
        os.makedirs(classic)
        open(os.path.join(classic, "complete.oga"), "w").close()
        self.s.CLASSIC_DIR = classic
        self.s.change("soundset", self.conf)                 # -> desktop
        self.assertEqual(self.commands()[-1][2], os.path.join(classic, "complete.oga"))
        self.s.change("soundset", self.conf)                 # -> NineLives
        self.assertEqual(self.commands()[-1][2], self.path("sounds/done.oga"))

    def test_nothing_to_play_or_quiet_kitty_plays_nothing(self):
        self.s.CLASSIC_DIR = os.path.join(self.tmp.name, "nowhere")
        self.s.change("volume", self.conf, -1)               # no sound file at all
        self.ours("done.oga")
        os.environ["NINELIVES_QUIET"] = "1"                  # the dev and test kitties
        self.s.change("volume", self.conf, -1)
        self.assertEqual(self.commands(), [])

    def test_a_chime_still_playing_is_stopped_first(self):
        self.ours("done.oga")
        first = mock.Mock()
        first.poll.return_value = None                       # still playing
        self.played.return_value = first
        self.s.change("volume", self.conf, -1)
        self.s.change("volume", self.conf, -1)
        first.kill.assert_called_once()

    def test_a_missing_player_is_not_an_error(self):
        self.ours("done.oga")
        self.played.side_effect = FileNotFoundError("paplay")
        self.assertTrue(self.s.change("volume", self.conf, -1))

    def test_macos_uses_afplay_and_the_wav(self):
        self.s.IS_MACOS = True
        self.ours("done.wav")
        self.s.set_volume(self.conf, 50)
        self.s.change("volume", self.conf, 1)                # 55 %: 40000 * 55 // 100 = 22000
        gain = f"{(22000 / 65536) ** 3:.8f}"
        self.assertEqual(self.commands(), [["afplay", "-v", gain, self.path("sounds/done.wav")]])
        self.s.set_volume(self.conf, 10)
        self.s.change("volume", self.conf, -1)               # 5 %: quiet, not rounded to silence
        self.assertGreater(float(self.commands()[-1][2]), 0)


class Keys(SettingsCase):
    def test_keys_split_arrows_mouse_and_letters(self):
        got = list(self.s.keys("\x1b[Aj\x1b[<0;5;7M\x1b[<0;5;7mq\x1b[1;5C\x1b"))
        self.assertEqual(got, ["\x1b[A", "j", ("mouse", 0, 5, 7, True), ("mouse", 0, 5, 7, False), "q", "", "\x1b"])

    def test_an_arrow_split_across_reads_is_still_an_arrow(self):
        s = self.s
        for part in ("\x1b", "\x1b[", "j\x1bO", "\x1b[<0;5"):
            self.assertTrue(s.incomplete(part), part)
        for whole in ("\x1b[A", "q", "\x1b[<0;5;7M", ""):
            self.assertFalse(s.incomplete(whole), whole)
        r, w = os.pipe()
        try:
            os.write(w, b"\x1b")
            def late(*_a, **_k):
                os.write(w, b"[A")              # the rest of the key arrives while it waits
                return ([r], [], [])
            with mock.patch("select.select", side_effect=late):
                self.assertEqual(list(s.keys(s.read_keys(r))), ["\x1b[A"])
            os.write(w, b"\x1b")               # a lone Esc: nothing more comes
            with mock.patch("select.select", return_value=([], [], [])):
                self.assertEqual(list(s.keys(s.read_keys(r))), ["\x1b"])
        finally:
            os.close(r)
            os.close(w)

    def test_moving_skips_the_blank_row_and_wraps(self):
        s = self.s
        edit = s.ROWS.index("edit")
        tips = s.ROWS.index("tips")
        self.assertEqual(s.handle("j", tips)[0], edit)            # over the blank line
        self.assertEqual(s.handle("\x1b[A", edit)[0], tips)
        self.assertEqual(s.handle("\x1bOB", edit)[0], 0)          # wraps to the top
        self.assertEqual(s.handle("k", 0)[0], edit)
        self.assertEqual(s.handle("\x0e", 0)[0], 1)               # Ctrl+N
        self.assertEqual(s.handle("\x10", 1)[0], 0)               # Ctrl+P

    def test_change_keys(self):
        for key, cmd in (("\r", ("change", 1, True)), (" ", ("change", 1, True)),
                         ("\x1b[C", ("change", 1, False)), ("l", ("change", 1, False)),
                         ("\x1b[D", ("change", -1, False)), ("h", ("change", -1, False)),
                         ("\x1b", "quit"), ("q", "quit"), ("\x03", "quit"), ("x", None)):
            self.assertEqual(self.s.handle(key, 2), (2, cmd), repr(key))

    def test_a_click_picks_its_row_and_changes_it(self):
        s = self.s
        cat = s.ROWS.index("cat")
        self.assertEqual(s.handle(("mouse", 0, 9, s.TOP + cat, True), 0), (cat, ("change", 1, True)))
        self.assertEqual(s.handle(("mouse", 0, 9, s.TOP + cat, False), 0), (0, None))      # the release
        self.assertEqual(s.handle(("mouse", 0, 9, s.TOP + s.ROWS.index(None), True), 0), (0, None))
        self.assertEqual(s.handle(("mouse", 0, 9, 1, True), 3), (3, None))                 # the title
        self.assertEqual(s.handle(("mouse", 65, 9, 1, True), 3)[0], 4)                     # wheel down
        self.assertEqual(s.handle(("mouse", 64, 9, 1, True), 3)[0], 2)                     # wheel up

    def test_a_click_lands_where_the_row_is_drawn(self):
        lines = plain(self.s.render(self.conf, self.state, 0, 60, 24)).split("\r\n")
        for i, key in enumerate(self.s.ROWS):
            if key:
                label = self.s.LABELS[key]
                self.assertIn(label, lines[self.s.TOP - 1 + i], key)   # TOP is 1-based


class Drawing(SettingsCase):
    def test_every_line_fits_and_the_screen_is_filled(self):
        for cols, lines in ((120, 30), (80, 24), (34, 20), (30, 16), (20, 14), (40, 8)):
            for sel in range(len(self.s.ROWS)):
                if not self.s.selectable(sel):
                    continue
                out = plain(self.s.render(self.conf, self.state, sel, cols, lines,
                                          "kitty 0.51.0 · ~/.config/kitty", "kitty runs an older tab_bar.py: restart"))
                rows = out.split("\r\n")
                self.assertEqual(len(rows), lines, (cols, lines))     # filled, and never scrolls
                for row in rows:
                    self.assertLessEqual(self.s.cells(row), cols, (cols, sel, row))

    def test_the_chosen_row_and_its_description(self):
        s = self.s
        sel = s.ROWS.index("cat")
        out = plain(s.render(self.conf, self.state, sel, 100, 24))
        self.assertIn("❯ The cat", out)
        self.assertIn("‹ shown ›", out)
        self.assertIn("goes to the one that needs you", out)
        self.assertIn("Esc close", out)
        self.assertEqual(out.count("❯"), 1)

    def test_off_values_are_muted(self):
        self.touch("tips-off")
        out = self.s.render(self.conf, self.state, 0, 80, 24)
        self.assertIn(f"{self.s.MUTED}off", out)

    def test_narrow_keeps_words_whole(self):
        out = plain(self.s.render(self.conf, self.state, self.s.ROWS.index("edit"), 24, 16,
                                  "kitty 0.51.0 · ~/.config/kitty"))
        self.assertIn("Edit kitty.conf…", out)                 # the short label, not a cut one
        self.assertIn("100%", out)                              # the volume without its bar
        self.assertNotIn("■", out)
        self.assertNotIn("0.51…", out)                          # the header is dropped, never cut
        self.assertIn("Enter change · Esc close", plain(self.s.render(self.conf, self.state, 0, 28, 18)))

    def test_a_very_narrow_pane_never_wraps(self):
        for cols in range(8, 30):
            for sel in range(len(self.s.ROWS)):
                lines = plain(self.s.render(self.conf, self.state, sel, cols, 16,
                                            "kitty 0.51.0 · ~/.config/kitty")).split("\r\n")
                for line in lines:
                    self.assertLessEqual(self.s.cells(line.replace("\x1b[H\x1b[2J", "")), cols, (cols, sel, line))

    def test_wide_window_keeps_values_near_their_labels(self):
        line = next(l for l in plain(self.s.render(self.conf, self.state, 1, 200, 24)).split("\r\n") if "Sounds" in l)
        self.assertLessEqual(self.s.cells(line), self.s.ROW_MAX)


class EditAndToggle(SettingsCase):
    def test_edit_asks_kitty_for_its_editor(self):
        os.environ["KITTY_LISTEN_ON"] = "fd:7"
        with mock.patch("subprocess.run") as run, mock.patch("os.execvp") as execvp:
            self.assertEqual(self.s.edit_config(self.conf), 0)
        self.assertEqual(run.call_args.args[0], ["kitty", "@", "action", "edit_config_file"])
        self.assertEqual(run.call_args.kwargs["pass_fds"], (7,))
        execvp.assert_not_called()

    def test_without_remote_control_the_editor_runs_here(self):
        os.environ["EDITOR"] = "myedit --wait"
        restored = []
        with mock.patch("subprocess.run") as run, mock.patch("os.execvp") as execvp, \
                mock.patch("shutil.which", lambda c: "/bin/" + c):
            self.s.edit_config(self.conf, lambda: restored.append(1))
        run.assert_not_called()
        self.assertEqual(restored, [1])                          # the terminal is put back first
        execvp.assert_called_once_with("myedit", ["myedit", "--wait", self.path("kitty.conf")])

    def test_kitty_refusing_falls_back_to_the_editor(self):
        os.environ["KITTY_LISTEN_ON"] = "unix:@x"
        fail = subprocess.CalledProcessError(1, "kitty")
        with mock.patch("subprocess.run", side_effect=fail), mock.patch("os.execvp") as execvp, \
                mock.patch("shutil.which", lambda c: "/usr/bin/nano" if c == "nano" else None):
            self.s.edit_config(self.conf)
        execvp.assert_called_once_with("nano", ["nano", self.path("kitty.conf")])

    def test_which_windows_are_settings_panels(self):
        p = self.s._is_panel
        here = os.path.join(self.conf, "settings.py")
        open(self.path("kitty.conf"), "w").close()
        self.assertTrue(p(["python3", here]))
        self.assertTrue(p(["/usr/bin/python3", here, "panel"]))
        self.assertFalse(p(["python3", here, "list"]))
        self.assertFalse(p(["python3", "/w/proj/settings.py"]))               # someone else's
        self.assertTrue(p(["sh", "-c", 'exec python3 "${KITTY_CONFIG_DIRECTORY:-${XDG_CONFIG_HOME:-$HOME/.config}/kitty}/settings.py"']))
        self.assertFalse(p(["sh", "-c", "python3 manage.py runserver --settings settings.py"]))
        self.assertFalse(p(["vim", here]))

    def test_toggle_closes_a_panel_in_this_tab_and_others(self):
        open(self.path("kitty.conf"), "w").close()
        here = os.path.join(self.conf, "settings.py")
        me = {"id": 1, "is_self": True, "cmdline": ["python3", here]}
        mine = {"id": 2, "cmdline": ["sh", "-c", 'exec python3 "${KITTY_CONFIG_DIRECTORY:-x}/settings.py"']}
        # a shell running `ninelives settings`: its window is the shell, never closed for the panel
        shell = {"id": 3, "cmdline": ["bash"], "foreground_processes": [{"cmdline": ["python3", here]}]}
        other = {"id": 4, "cmdline": ["sh", "-c", 'exec python3 "${KITTY_CONFIG_DIRECTORY:-x}/settings.py"']}
        data = [{"tabs": [{"windows": [mine, me]}, {"windows": [shell]}, {"windows": [other]}]}]
        self.assertEqual(self.s.other_panels(data, here_only=True), [2])
        self.assertEqual(self.s.other_panels(data), [2, 4])
        os.environ["KITTY_LISTEN_ON"] = "unix:@x"
        import json
        calls = []
        with mock.patch.object(self.s, "kitty", lambda *a: calls.append(a) or (json.dumps(data) if a == ("ls",) else "")):
            self.assertTrue(self.s.toggle_off_others())
        self.assertEqual(calls[1:], [("close-window", "--match", "id:2"), ("close-window", "--match", "id:4")])

    def test_no_remote_control_just_opens(self):
        with mock.patch.object(self.s, "kitty", side_effect=AssertionError("no kitty @")):
            self.assertFalse(self.s.toggle_off_others())


class Main(SettingsCase):
    def test_not_a_terminal_lists(self):
        with mock.patch.object(sys, "argv", ["settings.py"]), mock.patch("sys.stdin") as stdin, \
                mock.patch("sys.stdout") as stdout:
            stdin.isatty.return_value = False
            self.assertEqual(self.s.main(), 0)
        self.assertIn("Sounds: on", "".join(c.args[0] for c in stdout.write.call_args_list))

    def test_unknown_mode_shows_usage(self):
        with mock.patch.object(sys, "argv", ["settings.py", "nope"]), mock.patch("sys.stderr"):
            self.assertEqual(self.s.main(), 2)


if __name__ == "__main__":
    unittest.main()
