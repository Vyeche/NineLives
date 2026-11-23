#!/usr/bin/env python3
"""Unit tests for config/tips.sh (kitty-sounds, kitty-cat, kitty-quests, kitty-tips, ninelives).
Each test sources tips.sh in a fresh bash with HOME, KITTY_CONFIG_DIRECTORY and NINELIVES_STATE in a
temp folder and paplay replaced by a stub, so nothing plays and nothing real is touched.
    python3 tests/test_tips.py"""
import os
import re
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TIPS = os.path.join(HERE, "..", "config", "tips.sh")


class TipsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.conf = os.path.join(t, "conf")
        self.state = os.path.join(t, "state")
        self.bin = os.path.join(t, "bin")
        for d in (self.conf, self.state, self.bin, os.path.join(self.conf, "sounds")):
            os.makedirs(d)
        for s in ("done", "done-2", "done-3", "needs-you", "error", "badge", "rank", "drop"):
            open(os.path.join(self.conf, "sounds", s + ".oga"), "w").close()
        self.log = os.path.join(t, "paplay.log")
        with open(os.path.join(self.bin, "paplay"), "w") as f:
            f.write(f'#!/bin/sh\necho "$*" >> "{self.log}"\n')
        os.chmod(os.path.join(self.bin, "paplay"), 0o755)
        with open(os.path.join(self.bin, "kitty"), "w") as f:
            f.write("#!/bin/sh\necho 'kitty 0.51.0 created by Kovid Goyal'\n")
        os.chmod(os.path.join(self.bin, "kitty"), 0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def sh(self, script):
        env = {"HOME": self.tmp.name, "KITTY_CONFIG_DIRECTORY": self.conf, "NINELIVES_STATE": self.state,
               "PATH": self.bin + ":/usr/bin:/bin", "COLUMNS": "100", "LANG": "C.UTF-8", "TERM": "dumb"}
        # tips-off first: sourcing tips.sh would otherwise print a random tip
        open(os.path.join(self.conf, "tips-off"), "a").close()
        r = subprocess.run(["bash", "--norc", "-c", f'source "{TIPS}"; rm -f "{self.conf}/tips-off"; {script}'],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return re.sub(r"\x1b\[[0-9;]*m", "", r.stdout)

    def exists(self, name):
        return os.path.exists(os.path.join(self.conf, name))

    def played(self):
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
        self.assertEqual([os.path.basename(p[-1]) for p in played],
                         ["done.oga", "done-2.oga", "needs-you.oga", "error.oga", "badge.oga", "rank.oga", "drop.oga"])
        self.assertTrue(all(p[0] == "--volume=20000" for p in played), played)


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

    def sheet(self):
        env = {"HOME": self.tmp.name, "KITTY_CONFIG_DIRECTORY": self.conf, "NINELIVES_STATE": self.state,
               "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TERM": "dumb", "COLUMNS": "100"}
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

    def test_no_marks_with_quests_off(self):
        open(os.path.join(self.conf, "quests-off"), "w").close()
        out = self.sheet()
        self.assertNotIn("★", out)
        self.assertTrue(self.line(out, "Ctrl+Alt+Z ").startswith("   "))

if __name__ == "__main__":
    unittest.main()
