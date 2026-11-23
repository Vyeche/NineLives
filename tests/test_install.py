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


class MacSounds(unittest.TestCase):
    """On macOS (a stub uname says Darwin) install.sh adds a .wav of each sound for afplay, which
    can't play .oga; uninstall.sh removes them again unless you changed one."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "kitty")
        self.bin = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "uname"), "w") as f:
            f.write("#!/bin/sh\necho Darwin\n")
        os.chmod(os.path.join(self.bin, "uname"), 0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, script, *args):
        e = dict(os.environ, KITTY_CONFIG_DIRECTORY=self.dest, PATH=self.bin + os.pathsep + os.environ["PATH"])
        r = subprocess.run(["bash", script, *args], env=e, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def wavs(self):
        d = os.path.join(self.dest, "sounds")
        return sorted(n for n in os.listdir(d) if n.endswith(".wav")) if os.path.isdir(d) else []

    def test_every_sound_gets_a_wav_and_goes_again(self):
        oga = sorted(n[:-4] + ".wav" for n in os.listdir(os.path.join(CONFIG, "sounds")) if n.endswith(".oga"))
        out = self.run_script(INSTALL, "--dry-run")
        self.assertIn("new     sounds/done.wav", out)
        self.assertEqual(self.wavs(), [])
        self.run_script(INSTALL)
        self.assertEqual(self.wavs(), oga)
        with open(os.path.join(self.dest, "sounds", "done.wav"), "rb") as f:
            self.assertEqual(f.read(4), b"RIFF")
        self.assertIn("same    sounds/done.wav", self.run_script(INSTALL))      # made the same every time
        with open(os.path.join(self.dest, "sounds", "drop.wav"), "ab") as f:
            f.write(b"mine")                                                # one you changed
        out = self.run_script(UNINSTALL)
        self.assertIn("remove  sounds/done.wav", out)
        self.assertIn("keep    sounds/drop.wav", out)
        self.assertEqual(self.wavs(), ["drop.wav"])
        self.assertFalse(os.path.exists(os.path.join(self.dest, "ninelives-macos.conf")))

    def test_a_different_wav_is_backed_up_and_pruned_like_any_file(self):
        self.run_script(INSTALL)
        done = os.path.join(self.dest, "sounds", "done.wav")
        for day in range(10, 16):                          # 6 backups from older updates
            open(f"{done}.bak-202611{day:02d}-120000", "w").close()
        with open(done, "ab") as f:
            f.write(b"older")                              # an older build, or yours
        before = sorted(os.listdir(os.path.join(self.dest, "sounds")))
        out = self.run_script(INSTALL, "--dry-run")
        self.assertIn("update  sounds/done.wav   (old one saved as sounds/done.wav.bak-", out)
        self.assertIn("prune   sounds/done.wav.bak-20261111-120000", out)
        self.assertEqual(sorted(os.listdir(os.path.join(self.dest, "sounds"))), before)   # dry run
        self.run_script(INSTALL)
        baks = sorted(n for n in os.listdir(os.path.join(self.dest, "sounds")) if n.startswith("done.wav.bak-"))
        self.assertEqual(len(baks), 4)                     # the newest 3 (the new one too) and the oldest
        self.assertEqual(baks[0], "done.wav.bak-20261110-120000")
        with open(os.path.join(self.dest, "sounds", baks[-1]), "rb") as f:
            self.assertTrue(f.read().endswith(b"older"))   # what was there is kept
        out = self.run_script(UNINSTALL)
        self.assertIn("keep    sounds/done.wav.bak-", out)    # can't tell whose: kept, and listed

    def test_linux_gets_no_wav(self):
        e = dict(os.environ, KITTY_CONFIG_DIRECTORY=self.dest)
        if subprocess.run(["uname", "-s"], capture_output=True, text=True).stdout.strip() == "Darwin":
            self.skipTest("this is a Mac")
        r = subprocess.run(["bash", INSTALL], env=e, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.wavs(), [])


class KittyAppBundle(unittest.TestCase):
    """On a Mac kitty is often only in kitty.app, not on PATH: install.sh finds it there for its
    version and config check (a stub kitty.app here, and a PATH without kitty)."""
    TOOLS = ("bash", "dirname", "date", "find", "grep", "sort", "sed", "tail", "cmp", "cp", "mkdir",
             "awk", "basename", "rm", "cut", "head", "uname", "wc", "cat", "python3", "mktemp", "tr")

    def test_finds_kitty_in_applications(self):
        import shutil
        with tempfile.TemporaryDirectory() as t:
            tools = {n: shutil.which(n) for n in self.TOOLS}
            if not all(tools.values()):
                self.skipTest(f"missing: {[n for n, p in tools.items() if not p]}")
            os.makedirs(os.path.join(t, "path"))
            for n, p in tools.items():
                os.symlink(p, os.path.join(t, "path", n))
            app = os.path.join(t, "home", "Applications", "kitty.app", "Contents", "MacOS")
            os.makedirs(app)
            log = os.path.join(t, "kitty.log")
            with open(os.path.join(app, "kitty"), "w") as f:
                f.write(f'#!/bin/sh\necho "$1" >> "{log}"\n[ "$1" = --version ] && echo "kitty 0.51.0 created by Kovid Goyal"\nexit 0\n')
            os.chmod(os.path.join(app, "kitty"), 0o755)
            e = {"PATH": os.path.join(t, "path"), "HOME": os.path.join(t, "home"),
                 "KITTY_CONFIG_DIRECTORY": os.path.join(t, "kitty"),
                 # only this folder: never the real /Applications or ~/Applications
                 "NL_APP_DIRS": os.path.join(t, "nowhere") + ":" + os.path.join(t, "home", "Applications")}
            r = subprocess.run(["bash", INSTALL], env=e, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Config check: OK", r.stdout)
            self.assertNotIn("kitty not found", r.stderr)
            with open(log) as f:
                self.assertEqual(f.read().split(), ["--version", "+runpy"])


def kitty_conf(os_name, *names):
    """Options from config/kitty.conf as kitty itself reads it on os_name ("linux" or "macos"), by
    kitty's own parser (kitty +runpy). None when there is no kitty 0.50+ here."""
    import json, shutil
    kitty = shutil.which("kitty")
    if not kitty:
        return None
    code = ("import json, sys, kitty.conf.utils as u\n"
            f"u.os_name = lambda: {os_name!r}\n"
            "from kitty.config import load_config\n"
            "o = load_config(sys.argv[-1])\n"
            "km = [d.definition for v in o.keyboard_modes[''].keymap.values() for d in v]\n"
            "print(json.dumps({'listen_on': o.listen_on, 'maps': km}))")
    # (kitty prints a bad line or a missing include on stderr: there must be none)
    r = subprocess.run([kitty, "+runpy", code, os.path.join(CONFIG, "kitty.conf")], capture_output=True, text=True)
    try:
        return dict(json.loads(r.stdout.strip().splitlines()[-1]), errors=r.stderr.strip())
    except (ValueError, IndexError):
        return None


class KittyConf(unittest.TestCase):
    """config/kitty.conf on each system, read by the real kitty: Linux keeps its socket in
    $XDG_RUNTIME_DIR as before; macOS (no XDG_RUNTIME_DIR) reads ninelives-macos.conf too."""
    def setUp(self):
        self.linux, self.mac = kitty_conf("linux"), kitty_conf("macos")
        if self.linux is None or self.mac is None:
            self.skipTest("no kitty 0.50+ here to read the config")

    def mute_map(self, conf):
        # kitty uses the last mapping of a key: the one ninelives-macos.conf adds, on a Mac
        return [m for m in conf["maps"] if "sounds-off" in m][-1]

    def test_kitty_reads_both_without_complaint(self):
        self.assertEqual(self.linux["errors"], "")
        self.assertEqual(self.mac["errors"], "")

    def test_linux_is_unchanged(self):
        self.assertEqual(self.linux["listen_on"], "unix:${XDG_RUNTIME_DIR}/ninelives-kitty-{kitty_pid}")
        self.assertIn("paplay --volume=", self.mute_map(self.linux))

    def test_macos_socket_and_player(self):
        self.assertEqual(self.mac["listen_on"], "unix:ninelives-kitty-{kitty_pid}")
        self.assertIn("afplay -v", self.mute_map(self.mac))
        # kitty puts a relative socket in tempfile.gettempdir(): macOS's $TMPDIR is about 49
        # characters; a socket path can be at most 103 there
        tmpdir = "/var/folders/zz/zyxvpxvq6csfxvn_n0000000000000/T"
        self.assertLess(len(f"{tmpdir}/ninelives-kitty-{2**31}"), 104)


class MacMuteKey(unittest.TestCase):
    """The Ctrl+Alt+M command in ninelives-macos.conf, run with a stub afplay."""
    def setUp(self):
        import shlex
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.conf, self.bin, self.log = os.path.join(t, "kitty"), os.path.join(t, "bin"), os.path.join(t, "log")
        os.makedirs(os.path.join(self.conf, "sounds"))
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "afplay"), "w") as f:
            f.write(f'#!/bin/sh\necho "$*" >> "{self.log}"\n')
        os.chmod(os.path.join(self.bin, "afplay"), 0o755)
        with open(os.path.join(CONFIG, "ninelives-macos.conf"), encoding="utf-8") as f:
            line = next(l for l in f if l.startswith("map ctrl+alt+m "))
        args = shlex.split(line.split(None, 2)[2])            # launch --type=background sh -c '…'
        self.command = args[args.index("-c") + 1]

    def tearDown(self):
        self.tmp.cleanup()

    def press(self):
        env = {"KITTY_CONFIG_DIRECTORY": self.conf, "PATH": self.bin + ":/usr/bin:/bin", "HOME": self.tmp.name}
        subprocess.run(["sh", "-c", self.command], env=env, check=True, timeout=10)

    def test_mutes_then_unmutes_with_the_finished_chime(self):
        open(os.path.join(self.conf, "sounds", "done.wav"), "w").close()
        self.press()
        self.assertTrue(os.path.exists(os.path.join(self.conf, "sounds-off")))
        self.assertFalse(os.path.exists(self.log))
        with open(os.path.join(self.conf, "sounds-volume"), "w") as f:
            f.write("50\n")
        self.press()
        self.assertFalse(os.path.exists(os.path.join(self.conf, "sounds-off")))
        with open(self.log) as f:
            self.assertEqual(f.read().split(), ["-v", "0.02842171", os.path.join(self.conf, "sounds", "done.wav")])

    def test_the_lowest_volume_is_quiet_not_silent(self):
        open(os.path.join(self.conf, "sounds", "done.wav"), "w").close()
        open(os.path.join(self.conf, "sounds-off"), "w").close()
        for v, gain in (("5", "0.00002842"), ("100", "0.22737368")):
            with open(os.path.join(self.conf, "sounds-volume"), "w") as f:
                f.write(v + "\n")
            self.press()                                  # unmute: plays the chime
            with open(self.log) as f:
                self.assertEqual(f.read().split()[-2], gain)
            self.press()                                  # mute again


if __name__ == "__main__":
    unittest.main()
