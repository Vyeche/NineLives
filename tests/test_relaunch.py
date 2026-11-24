#!/usr/bin/env python3
"""Unit test for scripts/kitty-relaunch.sh's normal path: no NL_KITTY_SOCKET, run from a tab of the
kitty to restart (KITTY_LISTEN_ON), going into the background with a clean environment.
Everything kitty does is faked: a stub `kitty` first on PATH answers only on unix:@fake and logs
every call, and the "old kitty" is a throwaway process, so no real kitty is ever contacted.
MacLike runs it as on macOS (uname says Darwin; no setsid, flock or systemctl on PATH); on a Mac,
NormalRestart is that for real (no /proc there: kitty's pid comes from ps).
    python3 tests/test_relaunch.py"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RELAUNCH = os.path.join(HERE, "..", "scripts", "kitty-relaunch.sh")

FAKE_KITTY = r"""#!/bin/bash
D="$(dirname "$0")/.."
echo "$*" >> "$D/calls"
alive() { [ -e "$D/started" ] && return 0      # (gone, or a zombie its parent hasn't reaped yet)
  local p; p="$(cat "$D/helper.pid")"; kill -0 "$p" 2>/dev/null && ! ps -o stat= -p "$p" | grep -q Z; }
case "$1" in
  @)  [ "$2" = --to ] && [ "$3" = "unix:@fake" ] || { echo "WRONG SOCKET: $*" >> "$D/calls"; exit 1; }
      alive || exit 1
      [ "$4" = ls ] && cat "$D/ls.json"
      exit 0 ;;
  +runpy)    exit 0 ;;
  --version) echo "kitty 9.9.9 (fake)"; exit 0 ;;
  *)  env > "$D/started-env"; echo "$*" > "$D/started-args"
      if { true >&9; } 2>/dev/null; then echo open; else echo closed; fi > "$D/started-fd9"
      touch "$D/started"; exit 0 ;;
esac
"""


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_exe(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o755)


class NormalRestart(unittest.TestCase):
    SYSTEMCTL = "#!/bin/sh\nprintf 'HOME=x\\nPATH=x\\n'\n"   # the desktop's variables: only these survive

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = self.tmp.name
        os.makedirs(f"{d}/bin")
        os.makedirs(f"{d}/home")
        self.fake_kitty = FAKE_KITTY.replace('D="$(dirname "$0")/.."', f'D="{d}"')   # wherever it lives
        write_exe(f"{d}/bin/kitty", self.fake_kitty)
        if self.SYSTEMCTL is not None:
            write_exe(f"{d}/bin/systemctl", self.SYSTEMCTL)
        # the "old kitty": a process named kitty (bash under that name: the restart looks for a
        # process called kitty above a window's) whose child stands in for the shell in its window.
        # (macOS: a copy, so ps names it kitty whether it reports the program or its first argument)
        os.makedirs(f"{d}/old")
        if sys.platform == "darwin":
            shutil.copy("/bin/bash", f"{d}/old/kitty")
        else:
            os.symlink("/bin/bash", f"{d}/old/kitty")
        self.helper = subprocess.Popen(
            [f"{d}/old/kitty", "-c", f'echo $$ > "{d}/helper.pid"; sleep 60 & echo $! > "{d}/child.pid"; wait'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(50):
            if os.path.exists(f"{d}/child.pid") and read(f"{d}/child.pid").strip():
                break
            time.sleep(0.05)
        child = int(read(f"{d}/child.pid"))
        ls = [{"is_focused": True, "tabs": [{"title": "t", "is_active": True, "windows": [
            {"id": 1, "pid": child, "cwd": d, "title": "t", "is_active": True, "cmdline": ["bash"],
             "foreground_processes": [{"cmdline": ["bash"]}]}]}]}]
        with open(f"{d}/ls.json", "w") as f:
            json.dump(ls, f)

    def tearDown(self):
        for n in ("helper.pid", "child.pid"):
            try:
                os.kill(int(read(f"{self.d}/{n}")), 15)
            except (OSError, ValueError):
                pass
        self.helper.wait(timeout=10)
        self.tmp.cleanup()

    def path(self):
        return f"{self.d}/bin:/usr/bin:/bin"

    def test_restarts_the_kitty_it_runs_in_from_the_background(self):
        d = self.d
        env = {"PATH": self.path(), "HOME": f"{d}/home", "KITTY_LISTEN_ON": "unix:@fake",
               "XDG_CACHE_HOME": f"{d}/cache", "XDG_RUNTIME_DIR": f"{d}/run",
               "CLAUDE_CODE_CHILD_SESSION": "1", "LC_ALL": "C",
               # a kitty with a config folder of its own (KITTY_CONFIG_DIRECTORY or XDG_CONFIG_HOME)
               # must come back with that folder, not the default one
               "KITTY_CONFIG_DIRECTORY": f"{d}/my kitty conf", "XDG_CONFIG_HOME": f"{d}/xdg",
               # kitty.app is looked for here only, never in the real /Applications
               "NL_APP_DIRS": f"{d}/home/Applications"}
        r = subprocess.run(["bash", RELAUNCH], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("running in the background", r.stdout)
        log = f"{d}/cache/ninelives/kitty-relaunch.log"
        for _ in range(100):                    # the background copy: ~3 s with the fake
            if os.path.exists(log) and ("done: " in read(log) or "FAILED" in read(log)):
                break
            time.sleep(0.1)
        text = read(log) if os.path.exists(log) else "(no log in XDG_CACHE_HOME)"
        self.assertIn("done: kitty 9.9.9", text)
        calls = read(f"{d}/calls")
        self.assertNotIn("WRONG SOCKET", calls)            # only ever the kitty it was run in
        args = read(f"{d}/started-args")
        self.assertIn("--listen-on unix:@fake", args)       # the new kitty keeps the address
        self.assertIn("--session", args)
        # the restart's lock (fd 9) stays with the restart: a new kitty holding it turned every
        # later restart away ("another restart is already running")
        self.assertEqual(read(f"{d}/started-fd9").strip(), "closed")
        started_env = read(f"{d}/started-env")
        leaks = getattr(self, "leaks", ("_KR_SOCK=", "_KR_CACHE=", "_KR_DETACHED=", "_KR_NEW=", "KITTY_LISTEN_ON=", "XDG_CACHE_HOME="))
        for leak in leaks:
            self.assertNotIn("\n" + leak, "\n" + started_env, leak)
        self.started_env, self.log = started_env, text
        self.assertIn(f"\nKITTY_CONFIG_DIRECTORY={d}/my kitty conf\n", "\n" + started_env)
        self.assertIn(f"\nXDG_CONFIG_HOME={d}/xdg\n", "\n" + started_env)



class OldLockHeld(NormalRestart):
    """A kitty started by kitty-relaunch.sh before v1.1.1 kept the restart's lock file open (fd 9)
    and locked for its whole life, so the next restart of it stopped with "another restart is
    already running". The lock moved to a new file name for that: a restart must go through while
    something holds the old one."""
    OLD_LOCK = "kitty-relaunch.lock"       # the name before v1.1.1 (git show b65e7b0^:scripts/kitty-relaunch.sh)

    def setUp(self):
        super().setUp()
        os.makedirs(f"{self.d}/cache/ninelives", exist_ok=True)
        self.holder = subprocess.Popen(
            [sys.executable, "-c", "import fcntl, sys, time\n"
             "f = open(sys.argv[1], 'w'); fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
             "print('held', flush=True); time.sleep(60)", f"{self.d}/cache/ninelives/{self.OLD_LOCK}"],
            stdout=subprocess.PIPE, text=True)
        self.assertEqual(self.holder.stdout.readline().strip(), "held")

    def tearDown(self):
        self.holder.kill()
        self.holder.wait(timeout=10)
        self.holder.stdout.close()
        super().tearDown()

    def test_restarts_the_kitty_it_runs_in_from_the_background(self):
        super().test_restarts_the_kitty_it_runs_in_from_the_background()
        self.assertNotIn("another restart is already running", self.log)


class NoSystemdUserManager(NormalRestart):
    """No systemd user manager to ask (another init, or no XDG_RUNTIME_DIR): the restart used to
    stop silently there (pipefail on the failed systemctl); it keeps the environment instead."""
    SYSTEMCTL = "#!/bin/sh\nexit 1\n"

    def test_restarts_the_kitty_it_runs_in_from_the_background(self):
        self.leaks = ("_KR_SOCK=", "_KR_CACHE=", "_KR_DETACHED=", "_KR_NEW=")     # nothing is cleaned up here
        if sys.platform == "darwin":                  # (on a Mac it keeps what a Mac app gets)
            self.leaks += ("CLAUDE_CODE_CHILD_SESSION=", "KITTY_LISTEN_ON=")
        super().test_restarts_the_kitty_it_runs_in_from_the_background()


# what kitty-relaunch.sh and the fake kitty above run, for a PATH without setsid, flock and systemctl
TOOLS = ("bash", "sh", "python3", "dirname", "readlink", "mkdir", "date", "grep", "cut", "tr", "nohup",
         "seq", "sleep", "rm", "mv", "cat", "env", "touch", "ps", "head", "tail", "sed", "awk", "basename")


class MacLike(NormalRestart):
    """As on macOS: uname says Darwin, and PATH has no setsid, flock or systemctl. python3 detaches
    and locks instead, and the new kitty gets only what a Mac app gets from the system (launchd),
    plus the locale and PATH."""
    SYSTEMCTL = None
    MAC_KEEP = {"HOME", "USER", "LOGNAME", "SHELL", "PATH", "TMPDIR", "LANG", "SSH_AUTH_SOCK",
                "__CF_USER_TEXT_ENCODING", "__CFBundleIdentifier", "COMMAND_MODE", "SECURITYSESSIONID",
                "XPC_FLAGS", "XPC_SERVICE_NAME", "LaunchInstanceID", "KITTY_CONFIG_DIRECTORY", "XDG_CONFIG_HOME",
                "LC_ALL", "PWD", "SHLVL", "_", "OLDPWD"}        # (the last four: bash's own)

    def setUp(self):
        super().setUp()
        tools = {t: shutil.which(t) for t in TOOLS}
        if not all(tools.values()):
            self.skipTest(f"missing: {[t for t, p in tools.items() if not p]}")
        os.makedirs(f"{self.d}/sys")
        for t, p in tools.items():
            os.symlink(p, f"{self.d}/sys/{t}")
        write_exe(f"{self.d}/sys/uname", "#!/bin/sh\necho Darwin\n")
        # macOS's /usr/bin/python3 is an xcrun shim that adds SDKROOT, CPATH, LIBRARY_PATH and
        # MANPATH to the environment of the python it starts (seen on the Gauntlet's macOS runner):
        # none of them may reach the new kitty through the python3 that detaches it. On a Mac the
        # real one is that shim (and a made-up SDKROOT would break it), so the fake only stands in
        # for it elsewhere.
        if sys.platform != "darwin":
            os.remove(f"{self.d}/sys/python3")
            write_exe(f"{self.d}/sys/python3", "#!/bin/sh\nSDKROOT=/sdk CPATH=/sdk/include LIBRARY_PATH=/sdk/lib "
                      f'MANPATH=/sdk/man; export SDKROOT CPATH LIBRARY_PATH MANPATH\nexec "{tools["python3"]}" "$@"\n')
        # BSD date has no %N: it prints a plain N (which once made the detached copy detach again)
        os.remove(f"{self.d}/sys/date")
        write_exe(f"{self.d}/sys/date", f'#!/bin/sh\nf=$(printf %s "$1" | sed s/%N/N/)\nshift\nexec "{tools["date"]}" "$f" "$@"\n')

    def path(self):
        return f"{self.d}/bin:{self.d}/sys"

    def test_restarts_the_kitty_it_runs_in_from_the_background(self):
        self.leaks = ("_KR_SOCK=", "_KR_CACHE=", "_KR_DETACHED=", "_KR_NEW=", "KITTY_LISTEN_ON=", "XDG_CACHE_HOME=",
                      "CLAUDE_CODE_CHILD_SESSION=")
        super().test_restarts_the_kitty_it_runs_in_from_the_background()
        names = {l.split("=", 1)[0] for l in self.started_env.splitlines() if "=" in l}
        self.assertLessEqual(names, self.MAC_KEEP)
        self.assertIn("LC_ALL", names)
        self.assertNotIn("already running", self.log)


class MacAppBundle(MacLike):
    """kitty only in ~/Applications/kitty.app (not on PATH, as outside kitty's own tabs on a Mac):
    the restart finds it there and starts the new kitty from it."""
    def setUp(self):
        super().setUp()
        app = f"{self.d}/home/Applications/kitty.app/Contents/MacOS"
        os.makedirs(app)
        os.remove(f"{self.d}/bin/kitty")
        write_exe(f"{app}/kitty", self.fake_kitty)

    def test_restarts_the_kitty_it_runs_in_from_the_background(self):
        super().test_restarts_the_kitty_it_runs_in_from_the_background()
        self.assertIn("done: kitty 9.9.9", self.log)



class NoFlock(unittest.TestCase):
    """Where there is no flock(1) (macOS), kitty-relaunch.sh locks with python3's fcntl.flock."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_lock_without_flock_lets_one_restart_through(self):
        # the python3 lock from the script, on fd 9 of two shells: the second is turned away while
        # the first holds it (after its python3 has exited: the lock stays with the shell's fd)
        line = next(l for l in read(RELAUNCH).splitlines() if "fcntl.flock(9" in l)
        py = re.search(r"python3 -c '([^']+)'", line).group(1)
        lock = f"{self.tmp.name}/lock"
        first = subprocess.Popen(["bash", "-c", f"exec 9>'{lock}'; python3 -c '{py}' && echo got; sleep 3"],
                                 stdout=subprocess.PIPE, text=True)
        time.sleep(1)
        second = subprocess.run(["bash", "-c", f"exec 9>'{lock}'; python3 -c '{py}' 2>/dev/null && echo got || echo busy"],
                                capture_output=True, text=True, timeout=10)
        first.kill()
        self.assertEqual(first.communicate()[0].strip(), "got")
        self.assertEqual(second.stdout.strip(), "busy")


if __name__ == "__main__":
    unittest.main()
