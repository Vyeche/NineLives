#!/usr/bin/env python3
"""Unit tests for scripts/install.sh (what it copies, which old backups it removes) and
scripts/uninstall.sh (what it takes out and puts back). Both run on a temp folder
(KITTY_CONFIG_DIRECTORY), so the real ~/.config/kitty is never touched.
    python3 tests/test_install.py"""
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALL = os.path.join(HERE, "..", "scripts", "install.sh")
UNINSTALL = os.path.join(HERE, "..", "scripts", "uninstall.sh")
CONFIG = os.path.join(HERE, "..", "config")


class Backups(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "kitty")
        os.makedirs(self.dest)
        with open(os.path.join(self.dest, "tips.sh"), "w") as f:
            f.write("# an older tips.sh\n")
        self.ours = [f"tips.sh.bak-202611{d:02d}-120000" for d in range(10, 16)]      # 6 old backups
        self.theirs = ["tips.sh.bak-mine", "notes.txt.bak-20261101-120000", "kitty.conf.backup"]
        for name in self.ours + self.theirs:
            open(os.path.join(self.dest, name), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, *args, **env):
        e = dict(os.environ, KITTY_CONFIG_DIRECTORY=self.dest, **env)
        r = subprocess.run(["bash", INSTALL, *args], env=e, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def backups(self):
        return sorted(n for n in os.listdir(self.dest) if n.startswith("tips.sh.bak-2"))

    def test_keeps_the_newest_three_and_the_oldest_of_its_own_backups(self):
        out = self.run_install()
        kept = self.backups()
        self.assertEqual(len(kept), 4, kept)
        self.assertEqual(kept[0], "tips.sh.bak-20261110-120000")     # the oldest: likely pre-NineLives
        self.assertTrue(all(k > "tips.sh.bak-20261114" for k in kept[1:]), kept)   # + the newest 3
        self.assertIn("Removed 3", out)
        for name in self.theirs:                                              # never anyone else's
            self.assertTrue(os.path.exists(os.path.join(self.dest, name)), name)

    def test_dry_run_removes_nothing_and_counts_like_the_real_run(self):
        out = self.run_install("--dry-run")
        self.assertEqual(self.backups(), sorted(self.ours))
        self.assertIn("3 old backup(s) would be removed", out)

    def test_zero_is_refused(self):
        e = dict(os.environ, KITTY_CONFIG_DIRECTORY=self.dest, NL_KEEP_BACKUPS="0")
        r = subprocess.run(["bash", INSTALL], env=e, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)

    def test_keep_all(self):
        self.run_install(NL_KEEP_BACKUPS="all")
        self.assertEqual(len(self.backups()), len(self.ours) + 1)            # + this install's own

    def test_bad_setting_is_refused(self):
        e = dict(os.environ, KITTY_CONFIG_DIRECTORY=self.dest, NL_KEEP_BACKUPS="lots")
        r = subprocess.run(["bash", INSTALL], env=e, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.backups(), sorted(self.ours))



class Uninstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "kitty")
        os.makedirs(self.dest)
        self.write("kitty.conf", "# my own kitty.conf from before\n")
        # an old NineLives copy kept as a backup by an earlier update: not the user's, so it goes
        with open(os.path.join(CONFIG, "tips.sh"), encoding="utf-8") as f:
            self.write("tips.sh.bak-20261101-120000", f.read())
        self.write("notes.txt", "mine\n")
        self.run_script(INSTALL)
        self.write("sounds-off", "")                                   # a switch: stays

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        with open(os.path.join(self.dest, name), "w", encoding="utf-8") as f:
            f.write(text)

    def read(self, name):
        with open(os.path.join(self.dest, name), encoding="utf-8") as f:
            return f.read()

    def run_script(self, script, *args):
        e = dict(os.environ, KITTY_CONFIG_DIRECTORY=self.dest)
        r = subprocess.run(["bash", script, *args], env=e, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_puts_your_own_config_back_and_removes_the_rest(self):
        self.run_script(UNINSTALL)
        self.assertEqual(sorted(os.listdir(self.dest)), ["kitty.conf", "notes.txt", "sounds-off"])
        self.assertEqual(self.read("kitty.conf"), "# my own kitty.conf from before\n")

    def test_keeps_a_file_you_changed(self):
        self.write("tips.sh", "# my tweaked tips.sh\n")
        out = self.run_script(UNINSTALL)
        self.assertIn("keep    tips.sh", out)
        self.assertEqual(self.read("tips.sh"), "# my tweaked tips.sh\n")
        self.assertFalse(os.path.exists(os.path.join(self.dest, "tab_bar.py")))

    def test_an_older_ninelives_version_from_git_history_counts_as_ours(self):
        try:
            revs = subprocess.run(["git", "-C", HERE, "log", "--format=%H", "--", "../config/kitty.conf"],
                                  capture_output=True, text=True, check=True).stdout.split()
            with open(os.path.join(CONFIG, "kitty.conf"), encoding="utf-8") as f:
                now = f.read()
            old = next((t for t in (subprocess.run(["git", "-C", HERE, "show", f"{r}:config/kitty.conf"],
                        capture_output=True, text=True).stdout for r in revs) if t and t != now), None)
        except (OSError, subprocess.CalledProcessError):
            old = None
        if not old:
            self.skipTest("no older kitty.conf in git history (a shallow clone)")
        self.write("kitty.conf.bak-20261102-120000", old)    # older than the user's own backup
        self.run_script(UNINSTALL)
        self.assertEqual(self.read("kitty.conf"), "# my own kitty.conf from before\n")
        self.assertFalse(any(n.startswith("kitty.conf.bak-") for n in os.listdir(self.dest)))

    def test_dry_run_touches_nothing(self):
        before = sorted(os.listdir(self.dest))
        out = self.run_script(UNINSTALL, "--dry-run")
        self.assertEqual(sorted(os.listdir(self.dest)), before)
        self.assertIn("restore kitty.conf", out)
        self.assertIn("Nothing was touched", out)


if __name__ == "__main__":
    unittest.main()
