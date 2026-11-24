#!/usr/bin/env python3
"""Unit tests for config/tips.sh (kitty-sounds, kitty-cat, kitty-quests, kitty-tips, ninelives).
Each test sources tips.sh in a fresh bash with HOME, KITTY_CONFIG_DIRECTORY and NINELIVES_STATE in a
temp folder and paplay (afplay on macOS) replaced by a stub, so nothing plays and nothing real is
touched. bash runs with OSTYPE=linux-gnu (the Linux path, on any system) unless a test says darwin;
the same tests run again in zsh where there is one (macOS's default shell), on the system's own path.
bash is the first on PATH among /usr/bin and /bin: on macOS that is its bash 3.2.
    python3 tests/test_tips.py"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TIPS = os.path.join(HERE, "..", "config", "tips.sh")
LANG = "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8"    # macOS has no C.UTF-8
NATIVE_OS = "darwin" if sys.platform == "darwin" else "linux-gnu"


class TipsCase(unittest.TestCase):
    SHELL = "bash"
    OS = "linux-gnu"            # bash: OSTYPE is set to this before tips.sh is sourced

    @property
    def mac(self):
        return self.OS.startswith("darwin")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.conf = os.path.join(t, "conf")
        self.state = os.path.join(t, "state")
        self.bin = os.path.join(t, "bin")
        for d in (self.conf, self.state, self.bin, os.path.join(self.conf, "sounds")):
            os.makedirs(d)
        for s in ("done", "done-2", "done-3", "needs-you", "error", "badge", "rank", "drop"):
            for ext in (".oga", ".wav"):            # (install.sh makes the .wav ones on macOS)
                open(os.path.join(self.conf, "sounds", s + ext), "w").close()
        self.log = os.path.join(t, "paplay.log")
        for player in ("paplay", "afplay"):
            with open(os.path.join(self.bin, player), "w") as f:
                f.write(f'#!/bin/sh\necho "{player} $*" >> "{self.log}"\n')
            os.chmod(os.path.join(self.bin, player), 0o755)
        with open(os.path.join(self.bin, "kitty"), "w") as f:
            f.write("#!/bin/sh\necho 'kitty 0.51.0 created by Kovid Goyal'\n")
        os.chmod(os.path.join(self.bin, "kitty"), 0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def sh(self, script):
        env = {"HOME": self.tmp.name, "KITTY_CONFIG_DIRECTORY": self.conf, "NINELIVES_STATE": self.state,
               "PATH": self.bin + ":/usr/bin:/bin", "COLUMNS": "100", "LANG": LANG, "TERM": "dumb"}
        # tips-off first: sourcing tips.sh would otherwise print a random tip
        open(os.path.join(self.conf, "tips-off"), "a").close()
        body = f'source "{TIPS}"; rm -f "{self.conf}/tips-off"; {script}'
        if self.SHELL == "bash":            # (a zsh's full path: PATH here has only the stubs and system folders)
            cmd = ["bash", "--norc", "-c", f"OSTYPE={self.OS}; {body}"]
        else:
            cmd = [self.SHELL, "-f", "-c", body]           # zsh -f: no startup files
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return re.sub(r"\x1b\[[0-9;]*m", "", r.stdout)

    def exists(self, name):
        return os.path.exists(os.path.join(self.conf, name))

    def played(self):
        """[[player, args…]] for every sound played."""
        try:
            with open(self.log) as f:
                return [l.split() for l in f]
        except OSError:
            return []


class Sounds(TipsCase):
    def test_volume_is_saved_and_shown(self):
        self.sh("kitty-sounds volume 30")
        with open(os.path.join(self.conf, "sounds-volume")) as f:
            self.assertEqual(f.read().strip(), "30")
        self.assertIn("30%", self.sh("kitty-sounds volume"))

    def test_out_of_range_volume_is_refused(self):
        for bad in ("0", "150", "loud"):
            self.sh(f"kitty-sounds volume {bad}")
            self.assertFalse(self.exists("sounds-volume"), bad)

    def test_off_on_and_classic_flip_files_in_this_kittys_folder(self):
        self.sh("kitty-sounds off")
        self.assertTrue(self.exists("sounds-off"))
        self.sh("kitty-sounds on")
        self.assertFalse(self.exists("sounds-off"))
        self.sh("kitty-sounds classic")
        self.assertTrue(self.exists("sounds-classic"))
        self.sh("kitty-sounds ninelives")
        self.assertFalse(self.exists("sounds-classic"))

    def test_preview_plays_each_sound_at_the_set_volume(self):
        self.sh("sleep() { :; }; kitty-sounds volume 50 >/dev/null; kitty-sounds")
        played = self.played()
        ext = ".wav" if self.mac else ".oga"
        self.assertEqual([os.path.basename(p[-1]) for p in played],
                         [n + ext for n in ("done", "done-2", "needs-you", "error", "badge", "rank", "drop")])
        if self.mac:      # afplay: a plain gain, paplay's 20000 of 65536 cubed (the same level)
            self.assertTrue(all(p[:3] == ["afplay", "-v", "0.02842171"] for p in played), played)
        else:
            self.assertTrue(all(p[:2] == ["paplay", "--volume=20000"] for p in played), played)


class MacSounds(TipsCase):
    """bash with OSTYPE=darwin…, on any system: afplay and the .wav sounds, never paplay."""
    OS = "darwin23"

    def test_preview_uses_afplay_and_the_wav_files(self):
        self.sh("sleep() { :; }; kitty-sounds volume 100 >/dev/null; kitty-sounds")
        played = self.played()
        self.assertEqual(len(played), 7, played)
        self.assertTrue(all(p[:3] == ["afplay", "-v", "0.22737368"] and p[3].endswith(".wav") for p in played), played)

    def test_the_lowest_volume_is_quiet_not_silent(self):
        self.sh("sleep() { :; }; kitty-sounds volume 5 >/dev/null; kitty-sounds")
        played = self.played()
        self.assertTrue(played and all(p[:3] == ["afplay", "-v", "0.00002842"] for p in played), played)

    def test_a_mac_tip_only_on_a_mac(self):
        self.assertIn("On a Mac, Alt is Option", self.sh("kitty-tips all"))
        self.OS = "linux-gnu"
        self.assertNotIn("On a Mac", self.sh("kitty-tips all"))

    def test_without_its_wav_a_sound_falls_back_to_macos_own(self):
        os.remove(os.path.join(self.conf, "sounds", "done.wav"))
        self.sh("sleep() { :; }; kitty-sounds")
        files = [p[-1] for p in self.played()]
        self.assertNotIn(os.path.join(self.conf, "sounds", "done.oga"), files)   # afplay can't play it
        if os.path.exists("/System/Library/Sounds/Glass.aiff"):
            self.assertEqual(files[0], "/System/Library/Sounds/Glass.aiff")


class Switches(TipsCase):
    def test_cat_quests_tips(self):
        self.sh("kitty-cat off; kitty-quests off; kitty-tips off; kitty-buttons off")
        for f in ("cat-off", "quests-off", "tips-off", "buttons-off"):
            self.assertTrue(self.exists(f), f)
        self.sh("kitty-cat on; kitty-quests on; kitty-tips on; kitty-buttons on")
        for f in ("cat-off", "quests-off", "tips-off", "buttons-off"):
            self.assertFalse(self.exists(f), f)


class Status(TipsCase):
    def test_ninelives_shows_every_setting(self):
        with open(os.path.join(self.state, "badges"), "w") as f:
            f.write("split\t2026-11-01\npanes\t2026-11-02\nzoom\t2026-11-03\njump\t2026-11-04\n")
        with open(os.path.join(self.state, "next-quest"), "w") as f:
            f.write("Drag a tab in the sidebar to reorder it\n")
        with open(os.path.join(self.state, "uses"), "w") as f:
            f.write("split\t12\npanes\t3\n")
        out = self.sh("kitty-sounds volume 40 >/dev/null; kitty-cat off >/dev/null; ninelives")
        self.assertIn("✪1 mastered", out)
        self.assertIn("kitty 0.51.0", out)
        self.assertRegex(out, r"sounds\s+on, 40%, NineLives sounds")
        self.assertRegex(out, r"cat\s+hidden")
        self.assertRegex(out, r"quests\s+★4/16, House Cat")
        self.assertIn("next: Drag a tab", out)
        self.assertRegex(out, r"tips\s+on")

    def test_ninelives_settings_runs_the_settings_list(self):
        # (no terminal here, so settings.py prints its rows instead of opening the list)
        shutil.copy(os.path.join(HERE, "..", "config", "settings.py"), self.conf)
        out = self.sh("kitty-cat off >/dev/null; ninelives settings")
        self.assertIn("Sounds: on", out)
        self.assertIn("The cat: hidden", out)
        self.assertIn("ninelives settings", self.sh("ninelives"))      # the summary says where

    def test_ninelives_columns_line_up(self):
        out = self.sh("ninelives")
        rows = [l for l in out.splitlines() if re.match(r"  (sounds|cat|quests|buttons|tips) ", l)]
        cols = {l.index("kitty-") for l in rows}
        self.assertEqual(len(cols), 1, rows)          # ★ must not shift the command column


class RestartHint(TipsCase):
    def write(self, running_text, installed_text):
        import hashlib
        with open(os.path.join(self.conf, "tab_bar.py"), "w") as f:
            f.write(installed_text)
        with open(os.path.join(self.state, "tab_bar.running"), "w") as f:
            f.write(hashlib.sha1(running_text.encode()).hexdigest() + "\n")

    def test_warns_when_kitty_runs_an_older_tab_bar(self):
        self.write("old", "new")
        self.assertIn("restart kitty", self.sh("ninelives"))

    def test_quiet_when_up_to_date(self):
        self.write("same", "same")
        self.assertNotIn("restart kitty", self.sh("ninelives"))

    @unittest.skipUnless(shutil.which("shasum"), "no shasum here")
    def test_shasum_stands_in_for_sha1sum(self):
        # macOS has no sha1sum: its shasum (SHA-1 too) gives the same fingerprint
        with open(os.path.join(self.bin, "sha1sum"), "w") as f:
            f.write("#!/bin/sh\nexit 127\n")
        os.chmod(os.path.join(self.bin, "sha1sum"), 0o755)
        self.write("old", "new")
        self.assertIn("restart kitty", self.sh("ninelives"))
        self.write("same", "same")
        self.assertNotIn("restart kitty", self.sh("ninelives"))


class Hygiene(TipsCase):
    def test_ninelives_leaves_no_row_function_behind(self):
        out = self.sh("ninelives >/dev/null; type row >/dev/null 2>&1 && echo LEAKED || echo clean")
        self.assertIn("clean", out)

    def test_sourcing_twice_shows_one_tip(self):
        # (the harness's own first source runs with tips off, so source twice more with tips on)
        first = self.sh(f'unset _NL_TIP_SHOWN; source "{TIPS}"')
        both = self.sh(f'unset _NL_TIP_SHOWN; source "{TIPS}"; source "{TIPS}"')
        self.assertEqual(len(first.splitlines()), 1)
        self.assertEqual(len(both.splitlines()), 1)

    def test_a_random_tip_is_never_empty(self):
        # (zsh counts array elements from 1: an index from 0 once picked nothing)
        open(os.path.join(self.conf, "quests-off"), "w").close()
        out = self.sh("i=0; while [ $i -lt 60 ]; do kitty-tips; i=$((i + 1)); done")
        tips = [l for l in out.splitlines() if "kitty tip:" in l]
        self.assertEqual(len(tips), 60, out)
        self.assertTrue(all(re.search(r"kitty tip: \S", l) for l in tips), [l for l in tips if not re.search(r"kitty tip: \S", l)])

    def test_follows_xdg_config_home(self):
        r = self.sh('unset KITTY_CONFIG_DIRECTORY; XDG_CONFIG_HOME=/x/y; source "' + TIPS + '"; echo "$_nl_conf"')
        self.assertIn("/x/y/kitty", r)


class QuestList(TipsCase):
    def test_wraps_descriptions_under_themselves(self):
        us = "\x1f"
        row = "  · Splitter        " + " " * 12 + us + us + "word " * 30
        with open(os.path.join(self.state, "quests.txt"), "w") as f:
            f.write("NineLives quests\n\n" + row + "\n")
        out = self.sh("COLUMNS=60 kitty-quests").splitlines()
        body = [l for l in out if l.strip().startswith("word") or "Splitter" in l]
        self.assertGreater(len(body), 1)
        self.assertTrue(all(len(l) <= 60 for l in body), body)
        indent = len(row.split(us)[0])
        self.assertTrue(all(l.startswith(" " * indent) for l in body[1:]), body)



class ShortcutSheet(TipsCase):
    SHEET = os.path.join(HERE, "..", "config", "shortcuts.sh")

    def sheet(self, ostype="linux-gnu"):
        env = {"HOME": self.tmp.name, "KITTY_CONFIG_DIRECTORY": self.conf, "NINELIVES_STATE": self.state,
               "PATH": "/usr/bin:/bin", "LANG": LANG, "TERM": "dumb", "COLUMNS": "100", "OSTYPE": ostype}
        r = subprocess.run(["bash", self.SHEET], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return re.sub(r"\x1b\[[0-9;]*m", "", r.stdout)

    def line(self, out, keys):
        return next(l for l in out.splitlines() if keys in l)

    def test_quest_shortcuts_show_star_or_tick(self):
        with open(os.path.join(self.state, "badges"), "w") as f:
            f.write("zoom\t2026-11-01\n")
        with open(os.path.join(self.state, "quests.txt"), "w") as f:
            f.write("\x1b[1mNineLives quests\x1b[22m   ★···  1/16   rank: Kitten\n")
        out = self.sheet()
        self.assertTrue(self.line(out, "Ctrl+Alt+Z ").startswith(" ✓ "))
        self.assertTrue(self.line(out, "Ctrl+Shift+R ").startswith(" ★ "))
        self.assertTrue(self.line(out, "Ctrl+Shift+T ").startswith("   "))     # not a quest
        self.assertIn("1/16", out)

    def test_a_mac_note_only_on_a_mac(self):
        self.assertIn("On a Mac, Alt is Option", self.sheet("darwin23"))
        self.assertNotIn("On a Mac", self.sheet("linux-gnu"))

    def test_no_marks_with_quests_off(self):
        open(os.path.join(self.conf, "quests-off"), "w").close()
        out = self.sheet()
        self.assertNotIn("★", out)
        self.assertTrue(self.line(out, "Ctrl+Alt+Z ").startswith("   "))


# The same tests in zsh (macOS's default shell), sourced the way ~/.zshrc would. Skipped where there
# is no zsh; the Gauntlet's macOS lane has one and runs them.
ZSH = shutil.which("zsh")
for _case in (Sounds, Switches, Status, RestartHint, Hygiene, QuestList):
    _name = "Zsh" + _case.__name__
    globals()[_name] = unittest.skipUnless(ZSH, "zsh not installed")(
        type(_name, (_case,), {"SHELL": ZSH, "OS": NATIVE_OS}))
del _case, _name

if __name__ == "__main__":
    unittest.main()
