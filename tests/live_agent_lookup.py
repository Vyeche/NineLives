"""live_agent_lookup.py — tab_bar.py's agent marks and "command running" check against REAL processes,
run with kitty's own Python, so on macOS it uses kitty's real process helpers (kitty.child, libproc)
and on Linux the real /proc:

    NINELIVES_STATE=/tmp/x KITTY_CONFIG_DIRECTORY=/tmp/y kitty +launch tests/live_agent_lookup.py [--mac-path]

--mac-path takes tab_bar.py's macOS branch on any system (kitty.child exists on Linux too, where it
reads /proc), so check.sh tries that branch against real processes on Linux as well.

It starts bash in a terminal of its own (a pty, as kitty does) running a fake agent (sleep under
the name claude) and checks that tab_bar.py finds the agent below the bash that leads the
terminal's foreground process group, as it must for a tab kitty-relaunch.sh reopened. Prints one
line per check; exits 1 if any failed. scripts/check.sh runs it on Linux, scripts/check-macos.sh on
the Gauntlet's macOS runner. (Not a unittest module: it needs kitty's Python, not python3.)
"""
import importlib.util
import os
import pty
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types

if not os.environ.get("NINELIVES_STATE"):
    sys.exit("set NINELIVES_STATE (and KITTY_CONFIG_DIRECTORY) to temp folders: loading tab_bar.py writes quest files")

import kitty.fast_data_types as fdt  # noqa: E402  (kitty's own module: only under kitty +launch)

fdt.add_timer = lambda *a: 0            # no event loop here: tab_bar.py's timer must not start
fdt.remove_timer = lambda *a: None
TAB_BAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "tab_bar.py")
spec = importlib.util.spec_from_file_location("nl_tab_bar", TAB_BAR)
tb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tb)

fails = 0


def check(ok, what, detail=""):
    global fails
    print(("ok    " if ok else "FAIL  ") + what + (f"   ({detail})" if detail and not ok else ""))
    fails += 0 if ok else 1


def in_terminal(argv):
    """Start argv in a new pty, as its session leader (what kitty does for a window): (pid, master fd)."""
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execv(argv[0], argv)
        finally:
            os._exit(127)
    return pid, fd


def window(pid, fd):
    return types.SimpleNamespace(child=types.SimpleNamespace(child_fd=fd, pid=pid),
                                 screen=types.SimpleNamespace(is_main_linebuf=lambda: True))


def until(fn, want, seconds=5.0):
    """fn() until it returns want (processes take a moment to start); the last value."""
    end = time.monotonic() + seconds
    while True:
        tb._groups.update(at=-99.0)          # macOS: a fresh process-group map each try
        got = fn()
        if got == want or time.monotonic() > end:
            return got
        time.sleep(0.1)


def stop(pid, fd):
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        os.waitpid(pid, 0)
    except OSError:
        pass
    os.close(fd)


macos = sys.platform == "darwin"
check(tb.IS_MACOS == macos, f"tab_bar.py takes the {'macOS' if macos else 'Linux'} path on {sys.platform}")
if "--mac-path" in sys.argv[1:]:
    tb.IS_MACOS = True
    print("      (tab_bar.py's macOS branch, through kitty.child)")
with tempfile.TemporaryDirectory() as tmp:
    claude = os.path.join(tmp, "claude")
    os.symlink(shutil.which("sleep"), claude)            # a fake agent: sleep, named claude
    bash = shutil.which("bash") or "/bin/bash"

    # a restored tab: bash leads the foreground group, the agent runs below it in the same group
    pid, fd = in_terminal([bash, "-c", f"'{claude}' 60; :"])
    try:
        w = window(pid, fd)
        got = until(lambda: os.tcgetpgrp(fd), pid)
        check(got == pid, "the terminal's foreground group is bash's", f"{got} != {pid}")
        got = until(lambda: os.path.basename((tb._proc_argv(pid) or [""])[0]), "bash")   # (once it has exec'd)
        check(got == "bash", "bash's argv is read", repr(got))
        got = until(lambda: tb._foreground_name(w), "claude")
        check(got == "claude", "the agent below bash is found (✳ mark)", repr(got))
        check(tb._plain_command_running(w) is False, "bash leading its own terminal is not a running command")
    finally:
        stop(pid, fd)

    # a background job (its own group: job control is on while it starts) is not what the tab
    # shows; bash leads the foreground again (job control off) with a non-agent below it
    pid, fd = in_terminal([bash, "-c", f"set -m; '{claude}' 15 & set +m; sleep 60; :"])
    try:
        w = window(pid, fd)
        until(lambda: os.path.basename((tb._proc_argv(pid) or [""])[0]), "bash")
        time.sleep(0.5)
        fg = os.tcgetpgrp(fd)
        got = until(lambda: tb._foreground_name(w), "claude", seconds=1.5)
        check(fg == pid and got == "bash", "an agent in another process group is not this tab's",
              f"foreground group {fg} (bash {pid}), found {got!r}")
    finally:
        stop(pid, fd)

    # a plain command in the foreground (the spinner for plain shells): its argv, no process scan
    sleep = shutil.which("sleep")
    pid, fd = in_terminal([sleep, "60"])
    try:
        w = window(-1, fd)                   # (the shell's pid: not the foreground's)
        got = until(lambda: tb._plain_command_running(w), True)
        check(got is True, "a running command is seen", repr(got))
    finally:
        stop(pid, fd)

    if tb.IS_MACOS:      # kitty's own helpers, which the lookups above went through
        from kitty.child import cmdline_of_pid, process_group_map
        me = os.getpid()
        check(cmdline_of_pid(me)[:1] != [], "kitty.child.cmdline_of_pid reads a process's argv")
        check(me in process_group_map().get(os.getpgrp(), []), "kitty.child.process_group_map has this process")

print(f"{fails} failed" if fails else "all live checks passed")
sys.exit(1 if fails else 0)
