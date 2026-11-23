#!/usr/bin/env python3
"""Unit test for scripts/kitty-relaunch.sh's normal path: no NL_KITTY_SOCKET, run from a tab of the
kitty to restart (KITTY_LISTEN_ON), going into the background with a clean environment.
Everything kitty does is faked: a stub `kitty` first on PATH answers only on unix:@fake and logs
every call, and the "old kitty" is a throwaway process, so no real kitty is ever contacted.
    python3 tests/test_relaunch.py"""
import json
import os
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RELAUNCH = os.path.join(HERE, "..", "scripts", "kitty-relaunch.sh")

FAKE_KITTY = r"""#!/bin/bash
D="$(dirname "$0")/.."
echo "$*" >> "$D/calls"
alive() { [ -e "$D/started" ] && return 0
  local p; p="$(cat "$D/helper.pid")"; [ -d "/proc/$p" ] && ! grep -q '^[^)]*) Z' "/proc/$p/stat"; }
case "$1" in
  @)  [ "$2" = --to ] && [ "$3" = "unix:@fake" ] || { echo "WRONG SOCKET: $*" >> "$D/calls"; exit 1; }
      alive || exit 1
      [ "$4" = ls ] && cat "$D/ls.json"
      exit 0 ;;
  +runpy)    exit 0 ;;
  --version) echo "kitty 9.9.9 (fake)"; exit 0 ;;
  *)  env > "$D/started-env"; echo "$*" > "$D/started-args"; touch "$D/started"; exit 0 ;;
esac
"""


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class NormalRestart(unittest.TestCase):
    SYSTEMCTL = "#!/bin/sh\nprintf 'HOME=x\\nPATH=x\\n'\n"   # the desktop's variables: only these survive

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = self.tmp.name
        os.makedirs(f"{d}/bin")
        os.makedirs(f"{d}/home")
        with open(f"{d}/bin/kitty", "w") as f:
            f.write(FAKE_KITTY)
        with open(f"{d}/bin/systemctl", "w") as f:
            f.write(self.SYSTEMCTL)
        for n in ("kitty", "systemctl"):
            os.chmod(f"{d}/bin/{n}", 0o755)
        # the "old kitty": a process whose child stands in for the shell in its one window
        subprocess.run(["bash", "-c", f'setsid bash -c \'echo $$ > "{d}/helper.pid"; sleep 60 & '
                        f'echo $! > "{d}/child.pid"; wait\' >/dev/null 2>&1 < /dev/null &'], check=True)
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
        self.tmp.cleanup()

    def test_restarts_the_kitty_it_runs_in_from_the_background(self):
        d = self.d
        env = {"PATH": f"{d}/bin:/usr/bin:/bin", "HOME": f"{d}/home", "KITTY_LISTEN_ON": "unix:@fake",
               "XDG_CACHE_HOME": f"{d}/cache", "XDG_RUNTIME_DIR": f"{d}/run"}
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
        started_env = read(f"{d}/started-env")
        leaks = getattr(self, "leaks", ("_KR_SOCK=", "_KR_CACHE=", "_KR_DETACHED=", "KITTY_LISTEN_ON=", "XDG_CACHE_HOME="))
        for leak in leaks:
            self.assertNotIn("\n" + leak, "\n" + started_env, leak)



class NoSystemdUserManager(NormalRestart):
    """No systemd user manager to ask (another init, or no XDG_RUNTIME_DIR): the restart used to
    stop silently there (pipefail on the failed systemctl); it keeps the environment instead."""
    SYSTEMCTL = "#!/bin/sh\nexit 1\n"

    def test_restarts_the_kitty_it_runs_in_from_the_background(self):
        self.leaks = ("_KR_SOCK=", "_KR_CACHE=", "_KR_DETACHED=")     # nothing is cleaned up here
        super().test_restarts_the_kitty_it_runs_in_from_the_background()


if __name__ == "__main__":
    unittest.main()
