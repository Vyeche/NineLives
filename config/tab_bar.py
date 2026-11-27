# tab_bar.py — draws each sidebar tab (number, live status icon, name, folder) and plays the tab
# sounds. Used by {custom} in tab_title_template in kitty.conf. Part of NineLives
# (config/ in the NineLives repository); install with scripts/install.sh.
#
# Each tab:   " 12 ◐ name"         number right-aligned, a 2-cell status slot, the name (cut with …)
#             "    ✳ folder   12m"  the agent mark, the last two folders, muted, not bold; at the
#                                  right, how long the tab has been working / waiting / finished
# Status icons are coloured on inactive tabs (palette colours, so both themes work): working blue,
# finished green, sparkle gold, waiting-for-you amber, error red. They are the tab's one strong
# signal: the number, the agent mark and the "new output" dot are quieter shades of the tab's own
# colour (just above 4.5:1 / 3:1), and the branch is in the folder's colour. On the active tab
# everything stays the tab's own colour.
#
# Each tab shows ONE marker in front of its name:
#   ◐◓◑◒  spinning   working (Claude's status to kitty, or omp/opencode's title spinner, or a
#                    progress report; a percentage is shown too, e.g. "◐ 42%"), and in plain
#                    terminal tabs while a command runs (not at the prompt; full-screen apps like
#                    vim/htop/less and idle AI tools are ignored)
#   ✦✧✶ → ✓          just finished: a short sparkle, then ✓ until you look at the tab
#   ⚠ (pulses ~6 s)  waiting for you (permission prompt / question); on inactive tabs it is a
#                    filled amber chip, the strongest mark in the sidebar, and it stays filled.
#                    (No desktop "attention" request: on COSMIC that pulls kitty to the front.)
#   ✗                error            ‖ paused            • new output in a background tab
# Sounds: NineLives' own (<kitty config folder>/sounds, built by scripts/make-sounds.py), each with its own
# pitch shape: finished = two notes up, needs you = a rising "mrrp?" (the loudest), error = two low
# notes down, badge = a glockenspiel run, new rank = a run up to a chord, a dragged tab landing = a
# tiny tick. A plain command that ran 15 s+ also chimes when it ends. Sounds that arrive together
# play once (the most important one). They are quiet on purpose, and a tab you are looking at
# doesn't chime when it finishes or fails (you can see it). Volume: kitty-sounds volume 10-100. Mute/unmute: Ctrl+Alt+M (creates/removes
# <kitty config folder>/sounds-off). The desktop's standard sounds instead: kitty-sounds classic.
# The config folder is the one this kitty uses: KITTY_CONFIG_DIRECTORY, or ~/.config/kitty.
#
# kitty only redraws the tab bar when something changes and templates have no clock, so a timer
# (8 times a second) watches the tabs' states and redraws only when a frame actually changes.
# Animations count timer ticks, not the clock, so every frame is shown once, in order.
import os
import random
import re
import subprocess
import sys
import time

from kitty.boss import get_boss
from kitty.fast_data_types import add_timer, remove_timer, wcswidth

TICK = 0.125                # seconds per animation frame
FRAMES = "◐◓◑◒"             # working: one quarter turn every 2 ticks (4 a second)
# Just finished: a small burst that twinkles and lands on ✓ (15 frames, about 2 s)
SPARKLE = ("· ", "✧ ", "✦ ", "✶ ", "✦ ", "✧ ", "✦ ", "✶ ", "✦ ", "✧ ", "✦ ", "✶ ", "✦ ", "✧ ", "· ")
TWINKLE = ("✦", "✦", "✧", "✧", "✶", "✶", "✧", "✧")   # the badge line's sparkle, looping
PULSE_SECONDS = 6.0         # needs you: the block blinks (2 a second) this long, then stays filled
WORKING_ICON = ""  # what kitty's own program_status shows for state=working
# kitty's own icons are Nerd Font glyphs this font can't draw (they showed as a thin bar) -> plain
ICONS = {"": "✓ ", "": "⚠ ", "": "✗ ", "": "‖ "}
SPINNER_RE = re.compile("[⠁-⣿◐-◓]")  # braille spinners (omp, opencode, …) and ◐◓◑◒
ICON_KIND = {"✓ ": "done", "⚠ ": "blocked", "✗ ": "error", "‖ ": "paused"}
# Palette colours (theme-aware): blue, green, gold, amber, red. Contrast on the inactive tab is at
# least 5.6:1 on the dark theme and 3.9:1 on the light one (icons need 3:1).
STATUS_COLOUR = {"working": 4, "done": 2, "sparkle": 3, "blocked": 3, "error": 1}
NAME_COLOUR = 15            # bright text on the dark theme, near-black on the light one
INDENT = 6                  # " 12 " + 2-cell status slot: where names and folders start
HOME = os.path.expanduser("~")
USER_AT = os.environ.get("USER", "") + "@"
TOOL_SPINNER_RE = re.compile(r"^\s*π?\s*[⠁-⣿◐◓◑◒]\s*")
# Claude Code starts its title with ✳ (idle) or a spinner; the status slot already says that.
IDLE_MARK_RE = re.compile(r"^\s*[✳✻✽✢✶]\s+")
def _config_dir() -> str:
    """The folder this kitty reads its config from (KITTY_CONFIG_DIRECTORY or ~/.config/kitty).
    Sounds and the on/off switch files live there, so a second kitty with its own config folder
    (scripts/dev-kitty.sh) never touches the main one's."""
    try:
        from kitty.constants import config_dir
        if config_dir:
            return config_dir
    except Exception:
        pass
    return os.environ.get("KITTY_CONFIG_DIRECTORY") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "kitty")


CONFIG_DIR = _config_dir()
SOUND_DIR = os.path.join(CONFIG_DIR, "sounds")
CLASSIC_DIR = "/usr/share/sounds/freedesktop/stereo"
# macOS (new, not yet tried on a real Mac): no /proc, paplay, gdbus or freedesktop sounds. Read at
# call time, so the tests can try both. The Linux code paths are the same as before macOS support.
IS_MACOS = sys.platform == "darwin"
MAC_SOUNDS = "/System/Library/Sounds"
# "kitty-sounds classic" on a Mac: macOS's own alert sounds stand in for the freedesktop ones
MAC_CLASSIC = {"complete.oga": "Glass.aiff", "window-question.oga": "Ping.aiff", "dialog-error.oga": "Basso.aiff"}
# event: (NineLives file, desktop file for "kitty-sounds classic" or if ours is missing, volume
# out of 65536). The loudness is in the files themselves; needs-you is the loudest of them.
SOUNDS = {
    "done": ("done.oga", "complete.oga", 40000),
    "done-2": ("done-2.oga", "complete.oga", 40000),   # the done streak: each one a step higher
    "done-3": ("done-3.oga", "complete.oga", 40000),
    "blocked": ("needs-you.oga", "window-question.oga", 40000),
    "remind": ("needs-you.oga", "window-question.oga", 28000),   # still waiting: softer
    "error": ("error.oga", "dialog-error.oga", 40000),
    "badge": ("badge.oga", "complete.oga", 40000),
    "rank": ("rank.oga", "complete.oga", 40000),
    "drop": ("drop.oga", "", 40000),
    # the cat's voice (kitty-cat sounds off silences just these; the desktop's set has no cat)
    "meow": ("meow.oga", "", 40000),
    "mrrp": ("mrrp.oga", "", 40000),
    "purr": ("purr.oga", "", 40000),
}
# Sounds within COALESCE seconds of each other play once: the most important one wins.
PRIORITY = {"meow": 0, "mrrp": 0, "purr": 0, "drop": 0, "done": 1, "done-2": 1, "done-3": 1, "remind": 2, "error": 3, "blocked": 4, "badge": 5, "rank": 6}
COALESCE = 1.2
MUTE_FILE = os.path.join(CONFIG_DIR, "sounds-off")
CLASSIC_FILE = os.path.join(CONFIG_DIR, "sounds-classic")
VOLUME_FILE = os.path.join(CONFIG_DIR, "sounds-volume")   # a percentage, written by kitty-sounds

_last_working = 0.0
_prev_state: dict = {}      # window id -> last seen state
_frame = 0                  # timer ticks so far: every animation counts these
_sparkle_start: dict = {}   # tab id -> frame its "just finished" burst started
_working_tabs: set = set()  # tabs the timer last saw working (to catch "done" on the very next draw)
_wave_start = -99           # frame a badge's gold wave started down the tab numbers
WAVE_FRAMES = 40
REMIND_AFTER = 180.0        # a tab still waiting this long, and not looked at: one soft reminder
_reminded: set = set()      # tab ids reminded (or looked at) since they started waiting
# The cat at the end of "+ New tab" sums up the whole window (kitty-cat off hides it).
CAT_OFF = os.path.join(CONFIG_DIR, "cat-off")
SLEEP_AFTER = 180.0         # nothing working or waiting this long: the cat dozes off
_cat = {"blocked": 0, "fresh_block": False, "working": False, "done_at": -99.0, "error_at": -99.0, "waits": 0,
        "quiet_since": time.monotonic(), "drawn": None,
        "moves": {}, "roll": 0, "seen": None}   # its moves: name -> start frame (see CAT_MOVES)
_cat_rng = random.Random()  # the cat's dice (tests seed or replace it)
_blocked_since: dict = {}   # tab id -> time
_running: dict = {}         # tab id -> start time of the command running in a plain terminal tab
_since: dict = {}           # tab id -> [state, time first drawn in that state, minutes last drawn]
TIMED = {"working": "working", "blocked": "blocked", "done": "done", "sparkle": "done", "error": "error"}
AGENTS = {"claude", "omp", "opencode", "codex", "aider", "gemini", "node", "bun"}  # idle != busy
LONG_JOB = 15.0


def _plain_command_running(w) -> bool:
    """True while a plain terminal tab runs a command (the shell isn't in the foreground)."""
    try:
        pg = os.tcgetpgrp(w.child.child_fd)
    except Exception:
        return False
    if not pg or pg == w.child.pid or not w.screen.is_main_linebuf():
        return False
    if IS_MACOS:                    # this runs 8 times a second: one process's argv, never a scan
        try:
            name = os.path.basename((_mac_argv(pg) or [""])[0])
        except Exception:
            return False
        return name not in AGENTS and name not in ("bash", "sh", "zsh", "fish")
    try:
        with open(f"/proc/{pg}/cmdline", "rb") as f:
            name = os.path.basename(f.read().split(b"\0", 1)[0].decode(errors="ignore"))
    except OSError:
        return False
    return name not in AGENTS and name not in ("bash", "sh", "zsh", "fish")


# Which agent runs in a tab, as a small mark under its status icon (like Warp's per-tab app icons).
AGENT_MARK = {"claude": "✳", "omp": "π", "opencode": "oc", "codex": "cx", "gemini": "gm", "aider": "ai",
              "devin": "dv", "cursor-agent": "cu", "goose": "go", "amp": "am"}
AGENT_TTL = 3.0
# A window's agent can still be starting when the sidebar first draws it (a restart reopens every
# tab at once: kitten, then bash -lc, then the agent). An empty answer then would stand until the
# next redraw, which on an idle sidebar came seconds later, so for a new window the timer looks
# again (_recheck_mark) and redraws only if a mark turned up.
AGENT_RECHECK = 0.5         # seconds between looks while a new window has no mark
AGENT_YOUNG = 10.0          # how long a window counts as new
_agents: dict = {}           # tab id -> (checked at, mark)
_born: dict = {}             # window id -> when the timer first saw it


def _mac_argv(pid) -> list:
    """macOS: a process's argv from kitty's own helper (libproc), as `kitty @ ls` gets it there."""
    from kitty.child import cmdline_of_pid
    return cmdline_of_pid(pid)


GROUPS_TTL = 1.0
_groups = {"at": -99.0, "map": {}}


def _mac_groups() -> dict:
    """macOS: process group -> its pids, from kitty's own process_group_map. That looks at every
    process, so one map serves every tab for GROUPS_TTL seconds (agent marks are kept 3 s anyway)."""
    now = time.monotonic()
    if now - _groups["at"] >= GROUPS_TTL:
        try:
            from kitty.child import process_group_map
            _groups["map"] = dict(process_group_map())
        except Exception:
            _groups["map"] = {}
        _groups["at"] = now
    return _groups["map"]


def _proc_argv(pid) -> list:
    if IS_MACOS:
        return _mac_argv(pid)
    with open(f"/proc/{pid}/cmdline", "rb") as f:
        return [a.decode(errors="ignore") for a in f.read().split(b"\0") if a]


def _proc_children(pid) -> list:
    """pid's child processes. Each thread keeps its own list (kitten is a Go program: it starts
    the command from whichever thread runs), so all of them are read."""
    out = []
    for t in os.listdir(f"/proc/{pid}/task"):
        try:
            with open(f"/proc/{pid}/task/{t}/children") as f:
                out += [int(c) for c in f.read().split()]
        except (OSError, ValueError):
            pass
    return out


def _proc_pgrp(pid) -> int:
    with open(f"/proc/{pid}/stat", "rb") as f:          # "pid (comm) state ppid pgrp …"; comm may hold ")"
        return int(f.read().rsplit(b")", 1)[1].split()[2])


def _program(argv) -> str:
    """The program an argv runs (node/bun: the script it runs, e.g. claude)."""
    if not argv:
        return ""
    name = os.path.basename(argv[0])
    if name in ("node", "bun"):
        # the script is the first argument that names an agent (an option's value, e.g. --require
        # hook.js, can come before it); else the first non-option argument
        for a in argv[1:]:
            base = os.path.basename(a)
            if "claude-code" in a or base in AGENT_MARK:
                return "claude" if "claude-code" in a else base
        script = next((a for a in argv[1:] if not a.startswith("-")), "")
        name = os.path.basename(script)
    return name


# A foreground group led by one of these can have the agent below it, in the same group: a tab
# kitty-relaunch reopened (launch --hold: kitten run-shell, then bash -lc 'claude --resume …'), any
# `bash -c 'claude …'`, or a command kitty's own session restore runs as the shell starts. (A shell
# at its prompt gives each command a group of its own, led by the command.)
LOOK_BELOW = {"bash", "sh", "zsh", "fish", "dash", "kitten"}
LOOK_LIMIT = 24             # processes looked at below the leader, at most


def _agent_in_group(pg) -> str:
    """macOS (no /proc): the first agent among the other processes in the leader's group, oldest
    (lowest pid) first. On Linux _agent_below walks the leader's children instead."""
    for pid in sorted(p for p in _mac_groups().get(pg, ()) if p != pg)[:LOOK_LIMIT]:
        try:
            name = _program(_mac_argv(pid))
        except Exception:
            continue                            # exited meanwhile
        if name in AGENT_MARK:
            return name
    return ""


def _agent_below(pg) -> str:
    """The first agent among the leader's descendants in its process group, or "". A few small
    reads of /proc/<pid>/task/*/children, not a scan of all of /proc (this runs from draw code)."""
    if IS_MACOS:
        return _agent_in_group(pg)
    todo, seen = [pg], 0
    while todo and seen < LOOK_LIMIT:
        try:
            kids = _proc_children(todo.pop(0))
        except OSError:
            continue
        for k in kids:
            seen += 1
            if seen > LOOK_LIMIT:
                break
            try:
                if _proc_pgrp(k) != pg:         # a background job: not what the tab shows
                    continue
                name = _program(_proc_argv(k))
            except (OSError, ValueError, IndexError):
                continue
            if name in AGENT_MARK:
                return name
            todo.append(k)
    return ""


def _foreground_name(w) -> str:
    """The program in the window's foreground (node/bun: the script it runs, e.g. claude). When a
    shell or kitten leads the foreground group, an agent it runs (same group) counts instead."""
    try:
        pg = os.tcgetpgrp(w.child.child_fd)
        name = _program(_proc_argv(pg))
    except Exception:
        return ""
    if name.lstrip("-") in LOOK_BELOW:
        try:
            return _agent_below(pg) or name
        except Exception:
            return name
    return name


def _tab_obj(tab_id):
    """kitty's Tab for an id (draw code gets only a TabAccessor), or None."""
    try:
        for tm in get_boss().all_tab_managers:
            for tab in tm:
                if tab.id == tab_id:
                    return tab
    except Exception:
        pass
    return None


def _base_window(tab):
    """The window a tab's row describes: its active window, or, while an overlay covers it (the
    search box, the F1 sheet), the window underneath. kitty 0.51 keeps an overlay in the same window
    group, on top of the window it covers; the group's main window (Tab.active_window_for_cwd, which
    kitty's own launch --cwd=current and --title current start from) is the one under the overlays."""
    try:
        w = tab.active_window_for_cwd
    except Exception:
        w = None
    if w is None:
        try:
            w = tab.active_window
        except Exception:
            w = None
    return w


def _covered(tab_id):
    """(tab, the window under the overlay) while an overlay covers the tab's window, else None."""
    tab = _tab_obj(tab_id)
    if tab is None:
        return None
    try:
        top = tab.active_window
    except Exception:
        return None
    base = _base_window(tab)
    return (tab, base) if base is not None and top is not None and base is not top else None


def _agent_mark(tab_id, ttl: float = AGENT_TTL) -> str:
    """ "✳" for Claude, "π" for omp, two letters for other agents, "" for anything else."""
    now = time.monotonic()
    hit = _agents.get(tab_id)
    if hit and now - hit[0] < ttl:
        return hit[1]
    mark = ""
    try:
        w = _base_window(_tab_obj(tab_id))
        if w is not None:
            mark = AGENT_MARK.get(_foreground_name(w), "")
    except Exception:
        pass
    if len(_agents) > 500:
        _agents.clear()
    _agents[tab_id] = (now, mark)
    return mark


_last_sound = {"at": -99.0, "priority": -1}
STREAK_SECONDS = 90.0            # a "done" within this long of the last one is a step higher
_streak = {"step": 0, "at": -999.0}


def _note_done(now: float) -> int:
    """A tab really finished (Claude/omp done, or a plain command of LONG_JOB+): count the streak.
    Tabs finishing within STREAK_SECONDS of each other climb: the chime goes a step higher and
    the cat sings more notes."""
    step = _streak["step"] + 1 if now - _streak["at"] < STREAK_SECONDS else 1
    _streak.update(step=step, at=now)
    return step


def _sound_file(kind: str) -> str:
    ours, classic, _vol = SOUNDS[kind]
    if IS_MACOS:
        # the .wav install.sh adds of each sound (older macOS can't play .oga; 15 can); classic:
        # macOS's own sounds
        path = os.path.join(SOUND_DIR, os.path.splitext(ours)[0] + ".wav")
        if os.path.exists(CLASSIC_FILE) or not os.path.isfile(path):
            path = os.path.join(MAC_SOUNDS, MAC_CLASSIC[classic]) if classic in MAC_CLASSIC else ""
        return path if path and os.path.isfile(path) else ""
    path = os.path.join(SOUND_DIR, ours)
    if os.path.exists(CLASSIC_FILE) or not os.path.isfile(path):
        path = os.path.join(CLASSIC_DIR, classic) if classic else ""
    return path if path and os.path.isfile(path) else ""


def _volume_percent() -> int:
    try:
        with open(VOLUME_FILE, encoding="utf-8") as f:
            return max(5, min(100, int(f.read().strip())))
    except (OSError, ValueError):
        return 100


def _watching(tab_id) -> bool:
    """True if this tab is the one on screen in the kitty window you're using."""
    try:
        from kitty.fast_data_types import current_focused_os_window_id
        focused = current_focused_os_window_id()
        for tm in get_boss().all_tab_managers:
            if tm.os_window_id == focused and tm.active_tab is not None:
                return tm.active_tab.id == tab_id
    except Exception:
        pass
    return False


def _play(kind: str, tab_id=None) -> None:
    if kind not in SOUNDS or os.path.exists(MUTE_FILE):
        return
    if kind in ("done", "error") and tab_id is not None and _watching(tab_id):
        return                                     # you can see it happen: no need to chime
    now = time.monotonic()
    if now - _last_sound["at"] < COALESCE and PRIORITY[kind] <= _last_sound["priority"]:
        return                                     # something as important just played
    if kind == "done":
        # tabs finishing one after another climb a step each: done, done-2, done-3, done-3 …
        step = _streak["step"] if now - _streak["at"] < 2 else 1     # (_note_done just counted it)
        if step > 1 and _sound_file(f"done-{min(step, 3)}"):
            kind = f"done-{min(step, 3)}"
    path = _sound_file(kind)
    if not path:
        return
    _last_sound.update(at=now, priority=PRIORITY[kind])
    try:
        vol = SOUNDS[kind][2] * _volume_percent() // 100
        subprocess.Popen(_player(vol, path), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def _player(vol: int, path: str) -> list:
    """The command that plays a sound at vol (paplay's scale: 65536 = full)."""
    if IS_MACOS:
        # afplay -v taken as a plain gain (1 = as recorded); PulseAudio cubes paplay's volume, so
        # this is meant to be the same level (not compared by ear on a Mac yet)
        # (8 decimals: at 5 % the gain is about 0.00003, which 4 would round to silence)
        return ["afplay", "-v", f"{(vol / 65536) ** 3:.8f}", path]
    return ["paplay", f"--volume={vol}", path]


def _status(data) -> tuple:
    """(icon, kind, extra) for the tab's status slot; kind picks the icon's colour (STATUS_COLOUR),
    extra is a progress percentage ("42% ") shown in front of the name."""
    global _last_working
    tab = data.get("tab")
    tab_id = data.get("tab_id")
    now = time.monotonic()
    try:
        status = tab.program_status if tab is not None else ""
    except Exception:
        status = ""
    working = status.startswith(WORKING_ICON)
    extra = ""
    if not working:
        # Tools that don't report status to kitty (omp, opencode, …) still show they're busy:
        # a spinner character in their title, or a progress report (OSC 9;4).
        title = data.get("title", "") or ""
        if SPINNER_RE.search(title[:8]):
            working = True
        else:
            try:
                prog = tab.last_focused_progress_percent if tab is not None else ""
            except Exception:
                prog = ""
            if prog.startswith(WORKING_ICON):
                working = True
            elif prog.strip().endswith("%"):
                working, extra = True, prog.strip() + " "
    if not working and not status and tab_id in _running:
        working = True
    if working:
        _last_working = now
        return FRAMES[(_frame // 2) % len(FRAMES)] + " ", "working", extra
    if tab_id in _working_tabs and status and ICONS.get(status[:1]) == "✓ ":
        _start_sparkle(tab_id)       # kitty redrew before the timer saw "done": start the burst now
    spark = _sparkle(tab_id)
    if status:
        icon = ICONS.get(status[:1], "• ")
        if icon == "✓ " and spark:
            return spark, "sparkle", ""
        if icon == "⚠ " and now - _blocked_since.get(tab_id, now - PULSE_SECONDS) < PULSE_SECONDS:
            return icon, ("blocked" if (_frame // 4) % 2 == 0 else "blocked-dim"), ""
        return icon, ICON_KIND.get(icon, ""), ""
    if spark:
        return spark, "sparkle", ""
    # No status: kitty's "new output" dot (set when a background tab printed something).
    return data.get("activity_symbol", "") or "", "", ""


def _start_sparkle(tab_id) -> None:
    start = _sparkle_start.get(tab_id)
    if start is None or not 0 <= _frame - start <= 2:     # already started a moment ago: keep it
        _sparkle_start[tab_id] = _frame


def _sparkle(tab_id) -> str:
    """The tab's "just finished" frame, or "" once it has landed."""
    start = _sparkle_start.get(tab_id)
    if start is None or not 0 <= _frame - start < len(SPARKLE):
        return ""
    return SPARKLE[_frame - start]


def _elapsed(tab_id, kind: str) -> str:
    """ "3m" / "1h05": how long the tab has been in its state. Nothing in the first minute."""
    state = TIMED.get(kind.partition("-")[0])
    if state is None:
        _since.pop(tab_id, None)
        return ""
    now = time.monotonic()
    entry = _since.get(tab_id)
    if entry is None or entry[0] != state:
        # a plain command's real start is known; otherwise count from the first time we drew it
        entry = _since[tab_id] = [state, _running.get(tab_id, now) if state == "working" else now, 0]
    mins = entry[2] = int((now - entry[1]) // 60)
    if mins < 1:
        return ""
    return f"{mins}m" if mins < 60 else f"{mins // 60}h{mins % 60:02d}"


def _cells(s: str) -> int:
    w = wcswidth(s)
    return w if w >= 0 else len(s)


def _fit(s: str, width: int) -> str:
    """Cut the end off to fit `width` cells, marked with …"""
    if _cells(s) <= width:
        return s
    while s and _cells(s) > width - 1:
        s = s[:-1]
    return s.rstrip() + "…"


def _fit_start(s: str, width: int) -> str:
    """Cut the start off to fit `width` cells, marked with … (for folder paths)"""
    if _cells(s) <= width:
        return s
    while s and _cells(s) > width - 1:
        s = s[1:]
    return "…" + s


SHELL_NAMES = {"bash", "sh", "zsh", "fish", "dash", "ksh", "tcsh"}


def _renamed(tab_id) -> bool:
    """True if you gave the tab its own name (Ctrl+Shift+R; kitty keeps it in Tab.name)."""
    try:
        for tm in get_boss().all_tab_managers:
            for tab in tm:
                if tab.id == tab_id:
                    return bool(getattr(tab, "name", ""))
    except Exception:
        pass
    return False


def _tab_name(title: str, wd: str, tab_id=None) -> str:
    # A plain shell's title is its folder ("~/…", "/…", "user@host: …"): show the folder's name.
    # So is a bare shell name: with nothing setting a title kitty names the window after its program,
    # "bash" (a shell without kitty's shell integration, which sets no title). A tab you renamed
    # "bash" yourself keeps that name.
    if title[:1] in ("", "~", "/") or (USER_AT != "@" and title.startswith(USER_AT)) or (
            title.strip().lstrip("-") in SHELL_NAMES and not _renamed(tab_id)):
        return wd.rstrip("/").rsplit("/", 1)[-1] or "/"
    # omp/opencode put their own spinner in front of the title; ours is in the status slot.
    title = TOOL_SPINNER_RE.sub(lambda m: "π " if "π" in m.group() else "", title, count=1)
    return IDLE_MARK_RE.sub("", title, count=1) or title


# A running command's title is its whole command line (kitty's shell integration), which can hold a
# password or a token: the sidebar shows only its program and subcommand ("git push"), unless
# kitty-commands full (the full-commands file) asks for whole command lines. The rule and how a
# command line is told from a title a program set itself: command_title.py, next to this file.
FULL_COMMANDS = os.path.join(CONFIG_DIR, "full-commands")
_full = {"on": os.path.exists(FULL_COMMANDS)}


def _load_command_title():
    """command_title.py from this file's folder (loaded afresh on every config reload), or None."""
    try:
        import importlib.util
        here = os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join(CONFIG_DIR, "tab_bar.py")))
        spec = importlib.util.spec_from_file_location("ninelives_command_title", os.path.join(here, "command_title.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_ct = _load_command_title()


def _shown_title(title: str, w) -> str:
    """The title of window w as the sidebar names the tab: a command line its shell set, cut to its
    program and subcommand; any other title as it is (callers leave out tabs you renamed)."""
    if not title or w is None or _full["on"] or getattr(w, "override_title", None):
        return title or ""                     # set_window_title / launch --title: someone chose it
    cmdline = getattr(w, "last_cmd_cmdline", "") or ""
    try:
        at_prompt = bool(getattr(w, "at_prompt", False))
    except Exception:
        at_prompt = False
    if _ct is None:                            # command_title.py missing: the program alone
        if cmdline and " ".join(title.split()) == " ".join(cmdline.split()):
            return os.path.basename((title.split() or [""])[0])
        return title
    return _ct.shown_title(title, cmdline, at_prompt, foreground=lambda: [_foreground_name(w)])


def _row_title(data) -> str:
    """The tab's title for its row: kitty's, with a command line cut short (_shown_title), unless
    you renamed the tab (Ctrl+Shift+R)."""
    title = data.get("title") or ""
    tab = _tab_obj(data.get("tab_id"))
    if tab is None or getattr(tab, "name", ""):
        return title
    under = _covered(data.get("tab_id"))
    w = under[1] if under is not None else getattr(tab, "active_window", None)
    return _shown_title(title, w)


def _tab_folder(wd: str) -> str:
    """The last two folders, with ~ for home: code/NineLives"""
    if wd == HOME or wd.startswith(HOME + "/"):
        wd = "~" + wd[len(HOME):]
    return "/".join(wd.rstrip("/").split("/")[-2:])


def _is_active(tab_id) -> bool:
    try:
        for tm in get_boss().all_tab_managers:
            at = tm.active_tab
            if at is not None and at.id == tab_id:
                return True
    except Exception:
        pass
    return False


def _tab_number(data):
    """The tab's number. kitty numbers the tabs it draws, so when some are hidden (a short window,
    _fit_vertical) the real number comes from there."""
    try:
        import kitty.tab_bar as kt
        n = getattr(kt, "_vye_tab_numbers", {}).get(data.get("tab_id"))
        if n:
            return n
    except Exception:
        pass
    return data.get("index", "")


def draw_title(data) -> str:
    """The whole tab, as two lines:   " 12 ◐ name"   and   "      folder   12m".
    The number is right-aligned in 2 cells and the status icon has a fixed 2-cell slot, so every
    name and folder starts in the same column. Names are cut to the sidebar's width with …
    If anything here fails, the tab still shows its number and title (kitty would otherwise
    drop the whole template)."""
    try:
        return _draw_title(data)
    except Exception:
        try:
            title = _row_title(data)
        except Exception:                      # never the raw title: it may be a command line
            title = "" if not _full["on"] else data.get("title") or ""
        return f" {_tab_number(data):>2}    {title}"


def _draw_title(data) -> str:
    fmt = data["fmt"]
    tab = data.get("tab")
    width = data.get("max_title_length") or 30
    try:
        wd = tab.active_wd if tab is not None else ""
    except Exception:
        wd = ""
    under = _covered(data.get("tab_id"))
    if under is not None:
        # an overlay (the search box, the F1 sheet) is open in this tab: kitty describes the tab by
        # the overlay (its folder is kitty's start folder, its program no agent), so the row
        # describes the window under it: its folder, branch and agent mark, and its title unless
        # you renamed the tab
        t, w = under
        try:
            wd = w.get_cwd_of_child() or wd
        except Exception:
            pass
        try:
            if not getattr(t, "name", "") and w.title:
                data = dict(data, title=w.title)
        except Exception:
            pass
    # the status reads the title kitty set (spinners), the name the shortened one
    shown = _row_title(data)
    icon, kind, extra = _status(data)
    data = dict(data, title=shown)
    slot = icon if _cells(icon) >= 2 else (icon + "  ")[:2]
    name = (data.get("bell_symbol") or "") + extra + _tab_name(data.get("title") or "", wd, data.get("tab_id"))
    tab_fg = fmt.fg.tab
    active = _is_active(data.get("tab_id"))
    base = kind.partition("-")[0]
    if active:
        icon_fg = name_fg = ""                     # the active tab stays one colour on the accent
    else:
        icon_fg = getattr(fmt.fg, f"color{STATUS_COLOUR[base]}") if base in STATUS_COLOUR else ""
        name_fg = getattr(fmt.fg, f"color{NAME_COLOUR}")
    quiet_text = quiet_icon = ""
    if not active:
        # one strong signal per tab (its status icon, and the name); the number, the agent mark and
        # the "new output" dot are the theme's tab colour turned down to just above the limits
        t = _theme()
        fg, bg = t["inactive_tab_foreground"], t["inactive_tab_background"]
        quiet_text, quiet_icon = _sgr_fg(_quiet(fg, bg, QUIET_TEXT)), _sgr_fg(_quiet(fg, bg, QUIET_ICON))
    if not kind and icon.strip() in ACTIVITY_DOTS:
        # new output in a background tab: a small dot that doesn't compete with ⚠ or ✓
        slot = f"{quiet_icon}• "
    elif kind == "blocked" and not active:
        # Waiting for you is the one state that must not be missed: a filled chip (the glyph cut
        # out of an amber cell) instead of a thin outline. While it pulses it swaps with the outline.
        slot = f"{icon_fg}\x1b[7m{slot[:1]}\x1b[27m{slot[1:]}"
    else:
        slot = f"{icon_fg}{slot}"
    index = _tab_number(data)
    head = f"{quiet_text} {index:>2} {tab_fg}"
    try:
        pos = int(index or 0) - 1
    except ValueError:
        pos = 0
    if not active and 0 <= (_frame - _wave_start) - pos // 2 < 3:
        # a badge was just earned: a gold wave runs down the tab numbers (two tabs a frame)
        head = f"{fmt.fg.color3}{fmt.bold} {index:>2} {fmt.nobold}{tab_fg}"
    room = max(1, width - INDENT)
    if active and _buttons_on() and room > 8:
        # the current tab gets a × at its right end: click it to close the tab (_sidebar_click)
        # (width is kitty's max_title_length: the sidebar's real width, narrower in a small window);
        # one column short of the edge, under the search row's + and in line with the times
        shown = _fit(name, room - 3)
        _buttons.setdefault("close_cols", {})[data.get("tab_id")] = INDENT + room - 2
        line1 = f"{head}{slot}{tab_fg}{name_fg}{shown}{' ' * (room - 2 - _cells(shown))}× {tab_fg}"
    else:
        if active:
            _buttons.setdefault("close_cols", {}).pop(data.get("tab_id"), None)   # no ×: nothing to click
        line1 = f"{head}{slot}{tab_fg}{name_fg}{_fit(name, room)}{tab_fg}"
    folder, took = _tab_folder(wd), _elapsed(data.get("tab_id"), kind)
    branch = _git_branch(wd)
    avail = room - (_cells(took) + 2 if took and room - _cells(took) - 2 >= 6 else 0)
    if took and avail == room:
        took = ""                                  # too narrow for the time
    tail = ""
    fw = min(_cells(folder), max(8, avail - 3 - _cells(branch))) if branch else 0
    if branch and avail - 3 - fw >= min(_cells(branch), 6):     # whole, or 5 letters and …
        # a branch that isn't main/master, after the folder: "code/webapp ⌥ fix-login" (⌥: DejaVu has it)
        folder = _fit_start(folder, fw)
        b = _fit(branch, avail - 3 - _cells(folder))
        tail = f" ⌥ {b}"                           # in the folder's colour: a detail, not a signal
        used = _cells(folder) + 3 + _cells(b)
    else:
        folder = _fit_start(folder, avail)
        used = _cells(folder)
    if took:                                       # the time at the right edge
        tail += " " * (room - used - _cells(took) - 1) + took
    mark = _agent_mark(data.get("tab_id"))         # under the status icon: which agent runs here
    if mark:
        lead = f"{' ' * (INDENT - 2)}{quiet_icon}{mark}{' ' * (2 - _cells(mark))}{tab_fg}"
    else:
        lead = " " * INDENT
    return f"{line1}\n{fmt.nobold}{lead}{folder}{tail}"


ACTIVITY_DOTS = ("●", "•")   # kitty's "new output" symbol (tab_activity_symbol), old and new
BRANCH_TTL = 5.0             # seconds a folder's branch is cached (drawing happens many times a second)
_branches: dict = {}         # folder -> (checked at, branch or "")


def _git_branch(wd: str) -> str:
    """The git branch of the folder, if it isn't main or master (those go without saying), else "".
    Reads .git/HEAD directly (worktrees too): no git process per redraw."""
    if not wd:
        return ""
    now = time.monotonic()
    hit = _branches.get(wd)
    if hit and now - hit[0] < BRANCH_TTL:
        return hit[1]
    branch = ""
    try:
        d = wd
        # don't walk off this disk: on a stalled network mount every stat would block kitty's
        # drawing, so stop where the device changes (and after a sane depth)
        dev = os.stat(wd).st_dev
        for _depth in range(40):
            git = os.path.join(d, ".git")
            if os.path.isdir(git):
                head = os.path.join(git, "HEAD")
                break
            if os.path.isfile(git):                # a worktree: "gitdir: /path/to/.git/worktrees/x"
                with open(git, encoding="utf-8") as f:
                    gd = f.read().strip().partition("gitdir:")[2].strip()
                head = os.path.join(gd if os.path.isabs(gd) else os.path.join(d, gd), "HEAD")
                break
            parent = os.path.dirname(d)
            if parent == d or os.stat(parent).st_dev != dev:
                head = ""
                break
            d = parent
        else:
            head = ""
        if head:
            with open(head, encoding="utf-8") as f:
                ref = f.read().strip()
            branch = ref[16:] if ref.startswith("ref: refs/heads/") else ref[:7]   # detached: short sha
    except OSError:
        branch = ""
    if branch in ("main", "master"):
        branch = ""
    if len(_branches) > 200:
        _branches.clear()
    _branches[wd] = (now, branch)
    return branch


_first_tick = True


def _recheck_mark(tab_id, wid, now: float) -> bool:
    """A window the timer first saw under AGENT_YOUNG seconds ago, drawn without an agent mark:
    look again every AGENT_RECHECK seconds (its agent may still have been starting). True when a
    mark turned up, so the sidebar is redrawn; nothing is redrawn while the answer stays the same."""
    if now - _born.setdefault(wid, now) >= AGENT_YOUNG:
        return False
    hit = _agents.get(tab_id)
    if hit is None or hit[1] or now - hit[0] < AGENT_RECHECK:
        return False                    # not drawn yet (drawing looks), has its mark, or just looked
    return bool(_agent_mark(tab_id, AGENT_RECHECK))


def _tick(timer_id=None) -> None:
    global _first_tick, _frame
    _frame += 1
    now = time.monotonic()
    # slow: frames that change every other tick (spinner, pulse); fast: every tick (sparkles)
    slow, animate = now - _last_working < 1.0, False
    if _first_tick:
        # kitty asks for the tabs before it loads this file, so the first frame has its bare "+"
        # button; with nothing else changing it stayed that way. Draw once more with our label.
        _first_tick, animate = False, True
    if any(int((now - t0) // 60) != shown for _state, t0, shown in _since.values()):
        animate = True                             # a tab's elapsed time just changed
    try:
        boss = get_boss()
        seen = set()
        for tm in boss.all_tab_managers:
            for tab in tm:
                for w in tab:
                    ps = getattr(w, "program_status", None)
                    try:
                        records = ps.as_list() if ps is not None else []
                    except Exception:
                        records = []
                    state = records[0].get("state") if records else None
                    seen.add(w.id)
                    prev = _prev_state.get(w.id, "unknown")
                    if state != prev:
                        if prev != "unknown":  # don't make noise for states that existed at load
                            if state == "done" and prev == "working":
                                _start_sparkle(tab.id)
                                _note_done(now)
                                _play("done", tab.id)
                            elif state == "blocked":
                                _blocked_since[tab.id] = now
                                _cat["waiting_tab"] = tab.id
                                _cat["waits"] += 1   # a new wait (one tab can start as another stops)
                                _reminded.discard(tab.id)
                                _play("blocked")
                            elif state == "error":
                                _cat["error_at"] = now
                                _cat["error_tab"] = tab.id
                                _play("error", tab.id)
                            if state == "done" and prev == "working":
                                _cat["done_at"] = now
                                _cat["done_tab"] = tab.id
                        _prev_state[w.id] = state
                    if state == "blocked" and now - _blocked_since.get(tab.id, 0) < PULSE_SECONDS + 0.5:
                        slow = True
                if any(_prev_state.get(w.id) == "working" for w in tab):
                    _working_tabs.add(tab.id)
                else:
                    _working_tabs.discard(tab.id)
                # plain terminal tabs: spin while a command runs, sparkle (+ chime if long) when it ends
                # (in the window under an overlay: the search box over a build isn't its end)
                w = _base_window(tab)
                has_status = False
                try:
                    has_status = bool(w.program_status.as_list())
                except Exception:
                    pass
                busy = w is not None and not has_status and _plain_command_running(w)
                if busy:
                    _running.setdefault(tab.id, now)
                    slow = True
                elif tab.id in _running:
                    started = _running.pop(tab.id)
                    _start_sparkle(tab.id)
                    _cat["done_at"] = now
                    _cat["done_tab"] = tab.id
                    if now - started >= LONG_JOB:
                        _note_done(now)
                        _play("done", tab.id)
                if 0 <= _frame - _sparkle_start.get(tab.id, -99) <= len(SPARKLE):
                    animate = True                 # (one more frame after the last, to land on ✓)
                if w is not None and _recheck_mark(tab.id, w.id, now):
                    animate = True
        # who is looking at what: the active tab of the focused kitty window counts as seen
        try:
            from kitty.fast_data_types import current_focused_os_window_id
            focused = current_focused_os_window_id()
        except Exception:
            focused = 0
        blocked = 0
        for tm in boss.all_tab_managers:
            at = tm.active_tab
            for tab in tm:
                if not any(_prev_state.get(w.id) == "blocked" for w in tab):
                    continue
                blocked += 1
                if at is not None and at.id == tab.id and tm.os_window_id == focused:
                    _reminded.add(tab.id)          # you've seen it: no reminder needed
                elif tab.id not in _reminded and now - _blocked_since.get(tab.id, now) >= REMIND_AFTER:
                    _reminded.add(tab.id)
                    _blocked_since[tab.id] = now - 0.01   # pulse again
                    _play("remind")
        quests_off = os.path.exists(QUESTS_OFF)    # kitty-quests off/on: show it right away
        if quests_off != _badge_shown.get("off", quests_off):
            animate = True
        _badge_shown["off"] = quests_off
        buttons_on = _buttons_on()                 # kitty-buttons / the settings panel: the same
        if buttons_on != _buttons.get("on", buttons_on):
            animate = True
        _buttons["on"] = buttons_on
        full = os.path.exists(FULL_COMMANDS)       # kitty-commands full/short: rename the tabs now
        if full != _full["on"]:
            animate = True
        _full["on"] = full
        for wid in [w for w, t0 in _press_at.items() if now - t0 > PRESS_LIMIT]:
            _press_at.pop(wid, None)               # a release that never came: unlight the chip
            _pressed.pop(wid, None)
            animate = True
        for wid in list(_prev_state):
            if wid not in seen:
                del _prev_state[wid]
        for wid in [w for w in _born if w not in seen]:
            del _born[wid]
        tab_ids = {tab.id for tm in boss.all_tab_managers for tab in tm}
        for d in (_since, _sparkle_start, _blocked_since, _running, _buttons.setdefault("close_cols", {})):   # closed tabs
            for tid in [t for t in d if t not in tab_ids]:
                del d[tid]
        _reminded.intersection_update(tab_ids)
        _working_tabs.intersection_update(tab_ids)
        working = bool(_working_tabs or _running or now - _last_working < 1.0)
        fresh = any(now - _blocked_since.get(t, -99) < PULSE_SECONDS for t in _blocked_since)
        if working or blocked:
            _cat["quiet_since"] = now
        _cat.update(blocked=blocked, working=working, fresh_block=fresh)
        _cat_react()
        if _quest_day["day"] != _day():             # a new day: a new quest under "+ New tab"
            if _quest_day["day"] is not None:
                _write_quest_files()
                animate = True
            _quest_day["day"] = _day()
        coach_on = _coach["until"] > now           # the Alt+N hint appears / goes away
        if coach_on != _coach.get("shown"):
            _coach["shown"], animate = coach_on, True
        if _badge_shown["until"] > now - 0.5 or 0 <= _frame - _wave_start <= WAVE_FRAMES:
            animate = True
        if slow and _frame % 2 == 0:
            animate = True
        if _text_cat_shown() and _cat_face() != _cat["drawn"]:
            animate = True                         # (the drawn cat changes its pictures, not the text)
        _cat_tick(now)
        if animate:
            import kitty.tab_bar as tb
            cache = getattr(tb, "title_cache", None)
            if isinstance(cache, dict):
                cache.clear()
            for tm in boss.all_tab_managers:
                tm.mark_tab_bar_dirty()
            # Marking the bar dirty doesn't always make kitty paint: in a test kitty (X11, 0.50) the
            # spinner and pulse froze once the cursor stopped blinking, 15 s after the last key
            # press. Waking the main loop makes it draw. kitty 0.51 fixed stale displays after
            # timers (#10878); this stays for 0.50 and costs nothing.
            from kitty.fast_data_types import wakeup_main_loop
            wakeup_main_loop()
    except Exception:
        pass


def _start_timer() -> None:
    """kitty runs this file again on every config reload (Ctrl+Shift+F5). Stop the previous run's
    timer first, or every reload adds one more and the sounds play twice."""
    import kitty.tab_bar as kt
    old = getattr(kt, "_vye_tick_timer", None)
    if old is not None:
        try:
            remove_timer(old)
        except Exception:
            pass
    kt._vye_tick_timer = add_timer(_tick, TICK, True)


_start_timer()


# ---- Nicer tab dragging (kitty 0.50; patched at load, safely skipped if kitty changes) ----
# While a tab is dragged kitty shows a "ghost" under the mouse and a marker where the tab will land.
#   ghost:  the tab itself, lifted: a solid rounded card with a lighter edge, a drawn grip, the tab
#           number in the accent colour, the name, and the folder underneath (like in the sidebar)
#   marker: one thin accent line between tabs
# kitty draws the ghost from one line of text; we draw our own image instead, using kitty's own
# text renderer (draw_single_line_of_text, transparent background) for the words.
# Colours: see GHOST_DARK_THEME / GHOST_LIGHT_THEME below (cosmic-dark.conf / cosmic-light.conf).
_ICON_RE = re.compile("[⠁-⣿◐-◓✓⚠✗‖●•✦✧✶\U0001f514-]")
# The card is the opposite of the theme so it always stands out: a bright card on the dark theme,
# a dark card on the light theme. Picked when a drag starts, so it follows kitty's auto theme switch.
GHOST_DARK_THEME = dict(        # cosmic-dark: bar #110e18, terminal #17141f, accent #e67e00
    card=0xF3F0F7, edge=0xFF9A1F, text=0x17141F, muted=0x5E556E, accent=0xA64F00,
    grip=0x9A90AB, outside=0x141119, shine=0xFFFFFF,
    marker=0xFF9A1F)            # bright enough to pass text_fg_override_threshold on the dark bar
GHOST_LIGHT_THEME = dict(       # cosmic-light: bar #d4d3da, terminal #f7f6f9, accent #00525a
    card=0x24212B, edge=0x12A5B0, text=0xF7F6F9, muted=0xB8B3C2, accent=0x6FD6DE,
    grip=0x6E6879, outside=0xE5E4EA, shine=0x3A3641,
    marker=0x00737E)            # dark enough to pass text_fg_override_threshold on the light bar


def _ghost_palette() -> dict:
    try:
        from kitty.fast_data_types import get_options
        from kitty.utils import color_as_int
        c = color_as_int(get_options().background)
        r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
        if 0.2126 * r + 0.7152 * g + 0.0722 * b > 128:
            return GHOST_LIGHT_THEME
    except Exception:
        pass
    return GHOST_DARK_THEME


_drag_lines: list = []       # [index, name, folder] of the tab being dragged


def _rgb(c: int):
    return (c >> 16) & 255, (c >> 8) & 255, c & 255


def _render_ghost(os_window_id, width: int, orig_text):
    """Return premultiplied RGBA bytes (width x H) for the drag ghost, or None to fall back."""
    if not _drag_lines or width < 120:
        return None
    index, name, folder = (_drag_lines + ["", "", ""])[:3]
    # The X11 drag image has no transparency (transparent pixels show as black), so the image is
    # fully opaque: no outer shadow; the corners blend into a dark between the bar and terminal.
    M_X, M_TOP, M_BOT, R = 0, 0, 0, 5
    line_h, line_gap, pad_y = 22, 18, 2                   # kitty's strip is 22px with ink at 6..17
    rows = 2 if folder else 1
    card_h = pad_y * 2 + line_h + (line_gap if rows == 2 else 0) + 4   # +4: room for descenders
    H = M_TOP + card_h + M_BOT
    W = width
    cx0, cy0, cx1, cy1 = M_X, M_TOP, W - M_X, M_TOP + card_h   # card box (exclusive end)
    P = _ghost_palette()
    br, bgc, bb = _rgb(P['outside'])
    out = [[br / 255, bgc / 255, bb / 255, 1.0] for _ in range(W * H)]   # premultiplied float RGBA

    def coverage(x, y, x0, y0, x1, y1, r):
        # 4x4 supersampled coverage of pixel (x,y) by a rounded rect (fast path away from edges)
        if x0 <= x and x + 1 <= x1 and y0 <= y and y + 1 <= y1 and (
                x0 + r <= x <= x1 - r - 1 or y0 + r <= y <= y1 - r - 1):
            return 1.0
        if x + 1 <= x0 or x >= x1 or y + 1 <= y0 or y >= y1:
            return 0.0
        hit = 0
        for sy in range(4):
            for sx in range(4):
                px, py = x + (sx + 0.5) / 4, y + (sy + 0.5) / 4
                if px < x0 or px > x1 or py < y0 or py > y1:
                    continue
                qx = min(max(px, x0 + r), x1 - r)
                qy = min(max(py, y0 + r), y1 - r)
                if (px - qx) ** 2 + (py - qy) ** 2 <= r * r:
                    hit += 1
        return hit / 16.0

    def blend(i, rgb, a):
        if a <= 0:
            return
        r, g, b = rgb
        o = out[i]
        k = 1 - a
        o[0] = r / 255 * a + o[0] * k
        o[1] = g / 255 * a + o[1] * k
        o[2] = b / 255 * a + o[2] * k
        o[3] = a + o[3] * k

    # 2) card: 2px edge, then the fill inset by 2px
    for y in range(cy0, cy1):
        for x in range(cx0, cx1):
            edge_cov = coverage(x, y, cx0, cy0, cx1, cy1, R)
            if edge_cov:
                blend(y * W + x, _rgb(P['edge']), edge_cov)
                fill_cov = coverage(x, y, cx0 + 2, cy0 + 2, cx1 - 2, cy1 - 2, R - 2)
                blend(y * W + x, _rgb(P['card']), fill_cov)
    for x in range(cx0 + R, cx1 - R):
        blend((cy0 + 2) * W + x, _rgb(P['shine']), 0.8)

    # 3) grip: 2 x 3 dots, vertically centred on the first text line
    gx, gy = cx0 + 11, cy0 + pad_y + 7
    for row in range(3):
        for col in range(2):
            for dy in range(2):
                for dx in range(2):
                    blend((gy + row * 4 + dy) * W + gx + col * 4 + dx, _rgb(P['grip']), 1.0)

    # 4) text via kitty's renderer on a transparent background, clipped with a soft fade at the right
    text_x0 = gx + 15
    clip_x = cx1 - 10

    def place(text, colour, x, y):
        if not text:
            return x
        px, w = orig_text(os_window_id, text, 0xFF000000 | colour, 0x00000000, W)
        h = len(px) // (4 * w) if w else 0
        right = 0
        for yy in range(h):
            ty = y + yy
            if not (0 <= ty < H):
                continue
            for xx in range(w):
                j = (yy * w + xx) * 4
                a = px[j + 3] / 255
                if not a:
                    continue
                tx = x + xx - 1
                if tx >= clip_x or tx < 0:
                    continue
                right = max(right, xx)
                fade = min(1.0, (clip_x - tx) / 14)
                o = out[ty * W + tx]
                k = 1 - a * fade
                o[0] = px[j] / 255 * fade + o[0] * k
                o[1] = px[j + 1] / 255 * fade + o[1] * k
                o[2] = px[j + 2] / 255 * fade + o[2] * k
                o[3] = a * fade + o[3] * k
        return x + right + 1

    ty = cy0 + pad_y
    after = place(index, P['accent'], text_x0, ty)
    place(name, P['text'], (after + 7) if index else text_x0, ty)
    if folder:
        place(folder, P['muted'], (after + 7) if index else text_x0, ty + line_gap)

    buf = bytearray(W * H * 4)
    for i, (r, g, b, a) in enumerate(out):
        buf[i * 4:i * 4 + 4] = bytes((min(255, int(r * 255 + .5)), min(255, int(g * 255 + .5)),
                                      min(255, int(b * 255 + .5)), min(255, int(a * 255 + .5))))
    return bytes(buf)


def _patch_drag_visuals() -> None:
    try:
        import kitty.tabs as _tabs
        from kitty.tab_bar import TabBar
    except Exception:
        return
    orig_apply = getattr(_tabs, "apply_title_template", None)
    if orig_apply is not None and not getattr(orig_apply, "_vye_patched", False):
        def drag_label(*args, **kwargs):
            text = orig_apply(*args, **kwargs)
            try:
                clean = _ICON_RE.sub("", re.sub("\x1b\\[.+?[a-zA-Z]", "", text))
                # (the folder line may end in the elapsed time, "   12m": not part of the card)
                parts = [" ".join(re.sub(r"\s{2,}\d+(m|h\d\d)\s*$", "", p).split())
                         for p in clean.split("\n") if p.strip()]
                first = parts[0] if parts else ""
                index, _, name = first.partition(" ")
                if not index.isdigit():
                    index, name = "", first
                _drag_lines[:] = [index, name.strip(), parts[1] if len(parts) > 1 else ""]
                return (index + "  " + name).strip()
            except Exception:
                return text
        drag_label._vye_patched = True
        _tabs.apply_title_template = drag_label   # in kitty.tabs this is only used for drag images
    orig_text = getattr(_tabs, "draw_single_line_of_text", None)
    if orig_text is not None and not getattr(orig_text, "_vye_patched", False):
        def draw_ghost(os_window_id, text, fg, bg, width, *rest):
            try:
                pixels = _render_ghost(os_window_id, width, orig_text)
                if pixels:
                    return pixels, width
            except Exception:
                pass
            return orig_text(os_window_id, text, fg, bg, width, *rest)
        draw_ghost._vye_patched = True
        _tabs.draw_single_line_of_text = draw_ghost  # in kitty.tabs this is only used for drag images
    orig_marker = getattr(TabBar, "draw_drop_insert_marker", None)
    if orig_marker is not None and not getattr(orig_marker, "_vye_patched", False):
        def draw_drop_insert_marker(self):
            try:
                from kitty.fast_data_types import get_options
                from kitty.utils import color_as_int
                opts = get_options()
                bar = opts.tab_bar_background or opts.background
                fg, bg = self.active_fg, self.active_bg
                self.active_fg, self.active_bg = (_ghost_palette()['marker'] << 8) | 2, (color_as_int(bar) << 8) | 2
            except Exception:
                return orig_marker(self)
            try:
                return orig_marker(self)
            finally:
                self.active_fg, self.active_bg = fg, bg
        draw_drop_insert_marker._vye_patched = True
        TabBar.draw_drop_insert_marker = draw_drop_insert_marker


def _patch_tab_hit_areas() -> None:
    """Vertical sidebar: kitty counts only a tab's text rows as the tab, so the blank row between
    tabs belongs to no tab and clicking/dragging there does nothing. Give each gap row to the tab
    above it (and the rows above the first tab to the first tab). kitty 0.51 does this itself for
    clicks (#10810); the patch gives the same areas there, and still matters on 0.50."""
    try:
        from kitty.tab_bar import TabBar, CellRange
    except Exception:
        return
    orig = getattr(TabBar, "update_vertical", None)
    if orig is None or getattr(orig, "_vye_patched", False):
        return

    def update_vertical(self, data, *a, **k):
        import kitty.tab_bar as kt
        fit = getattr(kt, "_vye_fit_vertical", None)        # the latest load's, so a reload updates it
        more = 0
        if fit is not None:
            try:
                r, more = fit(self, orig, data, *a, **k)
            except Exception:
                fit = None
        if fit is None:
            r = orig(self, data, *a, **k)
        try:
            ext = sorted(self.tab_extents, key=lambda e: e.y.start)
            if ext:
                out = []
                for i, e in enumerate(ext):
                    start = 0 if i == 0 else e.y.start
                    # the last one also takes the row below it, unless that row says "N more tabs"
                    end = ext[i + 1].y.start - 1 if i + 1 < len(ext) else e.y.end + (0 if more else 1)
                    out.append(e._replace(y=CellRange(start, max(end, e.y.end))))
                self.tab_extents = out
        except Exception:
            pass
        return r
    update_vertical._vye_patched = True
    TabBar.update_vertical = update_vertical


def _pick_tabs(data, n: int, urgent=frozenset(), notable=frozenset()) -> list:
    """Which `n` of the sidebar's entries to show when they don't all fit. kitty draws tabs from the
    top and drops the rest, so a tab needing you near the bottom, the active tab and "+ New tab"
    with the cat could all vanish in a short window. Keep, in this order: "+ New tab" (the cat sums
    up every tab), the active tab, tabs waiting for you, tabs with an error, then the tabs nearest
    the active one. They stay in their sidebar order."""
    items = list(data)
    if n >= len(items):
        return items
    if n <= 0:
        return []
    active = next((i for i, t in enumerate(items) if getattr(t, "is_active", False)), 0)
    def rank(i):
        t = items[i]
        if t.tab_id < 0:
            return (0, 0)
        if i == active:
            return (1, 0)
        if t.tab_id in urgent:
            return (2, i)
        if t.tab_id in notable:
            return (3, i)
        return (4, abs(i - active), i)
    keep = sorted(sorted(range(len(items)), key=rank)[:n])
    return [items[i] for i in keep]


def _tab_states() -> tuple:
    """(tabs waiting for you, tabs with an error), by tab id."""
    urgent, notable = set(), set()
    try:
        for tm in get_boss().all_tab_managers:
            for tab in tm:
                states = {_prev_state.get(w.id) for w in tab}
                if "blocked" in states:
                    urgent.add(tab.id)
                elif "error" in states:
                    notable.add(tab.id)
    except Exception:
        pass
    return urgent, notable


def _fit_vertical(bar, orig, data, *a, **k) -> tuple:
    """Lay out the sidebar (_lay_out), then find the cat its place (_cat_choose: the floor, small
    at the end of "+ New tab", or the cat face) and lay it out again if that changes what the rows
    say or which rows stay free; then the cat's pictures and its bubble go on top (_cat_settle).
    Returns (kitty's result, how many tabs are hidden)."""
    try:
        st = _cat_state(bar)
    except Exception:
        st = {"mode": None, "pad": 0}
    r, hidden, fit = _lay_out(bar, orig, data, st.get("mode"), st.get("pad", 0), a, k)
    try:
        if not fit:                                 # (rows kept for the floor didn't fit after all)
            st["mode"], st["pad"] = "text", 0
            r, hidden, fit = _lay_out(bar, orig, data, "text", 0, a, k)
        mode, pad = _cat_choose(bar, st, hidden)
        if (mode, pad) != (st.get("mode"), st.get("pad", 0)):
            again = _label_kind(mode) != _label_kind(st.get("mode")) or pad != st.get("pad", 0)
            st["mode"], st["pad"] = mode, pad
            if again:
                r, hidden, fit = _lay_out(bar, orig, data, mode, pad, a, k)
                if not fit:
                    st["mode"], st["pad"] = "text", 0
                    r, hidden, fit = _lay_out(bar, orig, data, "text", 0, a, k)
        _cat_settle(bar, st)
    except Exception:
        pass
    return r, hidden


def _lay_out(bar, orig, data, mode, pad, a, k) -> tuple:
    """Lay out the sidebar; when kitty can't fit every tab, show the ones that matter
    (_pick_tabs) and name the hidden ones on the line under them (a click there goes to the first
    hidden tab: _hidden_line_click). `pad` rows are kept free at the bottom for the cat (made-up
    entries kitty lays out, then taken out). Returns (kitty's result, how many tabs are hidden,
    False if the kept rows didn't fit)."""
    import kitty.tab_bar as kt
    data = _fit_own_rows(bar, data, mode)
    # tabs keep their real numbers (Alt+N means the Nth tab): kitty numbers every entry it draws,
    # the search row on top and hidden tabs included
    nums = {t.tab_id: n for n, t in enumerate((t for t in data if t.tab_id > 0), 1)}
    kt._vye_tab_numbers = nums
    bar._vye_hidden = None
    if pad and data:
        padded = tuple(data) + _pad_entries(bar, data, pad)
        r = orig(bar, padded, *a, **k)
        if len(bar.tab_extents) < len(padded):
            return r, 0, False
        _unpad(bar)
        _note_close_row(bar, data)
        _note_layout(bar, data, {e.tab_id for e in bar.tab_extents}, [])
        return r, 0, True
    r = orig(bar, data, *a, **k)
    shown = len(bar.tab_extents)                    # kitty kept a line for its red … under these
    if shown >= len(data) or shown < 1:
        _note_close_row(bar, data)
        _note_layout(bar, data, {e.tab_id for e in bar.tab_extents}, [])
        return r, 0, True
    states = _tab_states()
    s = bar.screen
    while True:
        kept = _pick_tabs(data, shown, *states)
        r = orig(bar, kept, *a, **k)
        shown_ids = {e.tab_id for e in bar.tab_extents}     # what kitty really drew, not what we asked
        row = max((e.y.end for e in bar.tab_extents), default=-1) + 1
        if row < s.lines or shown <= 1:
            break
        shown -= 1          # the kept tabs filled every row (some are taller): make room for the line
    hidden = [nums[t.tab_id] for t in data if t.tab_id > 0 and t.tab_id not in shown_ids]
    if hidden and row < s.lines:
        try:
            s.cursor.x, s.cursor.y = 0, row
            try:
                s.cursor.reset_display_attrs()     # no underline or reverse from the tab above
            except Exception:
                pass
            s.cursor.bg = kt.as_rgb(kt.color_as_int(bar.draw_data.default_bg))
            s.cursor.fg = kt.as_rgb(kt.color_as_int(bar.draw_data.inactive_fg))
            s.cursor.bold = s.cursor.italic = False
            s.draw(_fit(f"  ⋯   hidden: {_number_ranges(hidden)}", s.columns - 1))
            bar._vye_hidden = (row, next(t for t, n in nums.items() if n == hidden[0]))
        except Exception:
            pass
    _note_close_row(bar, data)
    _note_layout(bar, data, shown_ids, hidden)
    return r, (len(hidden) if bar._vye_hidden else 0), True


def _fit_own_rows(bar, data, cat_mode=None):
    """Our own rows (the search row, "+ New tab") are drawn as they are, so make them for the
    sidebar's real width (_line_width): a small window or a big font makes kitty's sidebar narrower,
    and kitty would cut the buttons off the end with … (and clicks would miss them). cat_mode: where
    the cat is (no cat face on "+ New tab" while the drawn one shows)."""
    try:
        width = _line_width(bar)
        wid = getattr(bar, "os_window_id", None)
        out = []
        for t in data:
            if t.tab_id == SEARCH_ROW_ID:
                t = t._replace(title=_search_row(width, wid) or t.title)
            elif t.tab_id < 0 and t.title != "+":    # kitty's bare + is left alone: no label patch
                t = t._replace(title=_new_tab_label(width, wid, cat_mode))
            out.append(t)
        return tuple(out)
    except Exception:
        return data


def _note_close_row(bar, data) -> None:
    """Which row the current tab's first line (with its ×) is on, for _sidebar_click."""
    try:
        at = next((t.tab_id for t in data if t.tab_id > 0 and t.is_active), None)
        e = next((e for e in bar.tab_extents if e.tab_id == at), None)
        _buttons.setdefault("close_row", {})[getattr(bar, "os_window_id", 0)] = e.y.start if e else -1
    except Exception:
        pass


# ---- The search row and buttons (like Warp's sidebar) ----------------------------------------------
# A row on top of the sidebar: a search field, then a few buttons, each a filled chip:
#     [ Search tabs      ] [⚠2] [⚙] [+]
# Click the field to search your tabs (the Ctrl+Shift+Space box), ⚠ for the tab waiting for you
# (Ctrl+Alt+U; only there while a tab waits), ⚙ for the NineLives settings (Ctrl+Shift+F2), + for a
# new tab. A narrow sidebar (small window, big font) gets shorter words, then smaller chips; the
# buttons always stay whole. The tab you're on has a × at its right end that closes it.
# kitty can't tell where the mouse hovers over the sidebar (kitty 0.51 hands the tab bar no mouse
# moves except during a tab drag or a text selection, and has no call for the pointer's position;
# it does show a hand pointer there), so there is no hover look: the buttons look like buttons all
# the time, a chip lights up in the accent colour while you hold it down, and only the current tab
# gets a ×. kitty-buttons off hides the row and the ×.
SEARCH_ROW_ID = -2           # a made-up entry like kitty's own "+" (-1); our click hook handles it
BUTTONS_OFF = os.path.join(CONFIG_DIR, "buttons-off")
_CONF_DIR_SH = '"${KITTY_CONFIG_DIRECTORY:-${XDG_CONFIG_HOME:-$HOME/.config}/kitty}'
_FINDER = _CONF_DIR_SH + '/tab-finder.py"'
_SETTINGS = _CONF_DIR_SH + '/settings.py"'
_CAT_HELPER = _CONF_DIR_SH + '/cat-helper.py"'
ACTIONS = {   # the same actions as the keys in kitty.conf
    "search": f"launch --type=overlay --allow-remote-control --title current sh -c 'exec python3 {_FINDER} search'",
    "waiting": f"launch --type=background --allow-remote-control sh -c 'exec python3 {_FINDER} waiting'",
    "settings": f"launch --type=overlay --allow-remote-control --title current sh -c 'exec python3 {_SETTINGS}'",
    # the cat at the end of "+ New tab": the helper cat (cat-helper.py, Ctrl+Alt+C); again closes it
    "cat": f"launch --type=overlay --allow-remote-control --title current sh -c 'exec python3 {_CAT_HELPER}'",
    "new": "new_tab_with_cwd",
    "close": "close_tab",
    # the cat's bubble: "All shortcuts" (the F1 sheet, as in kitty.conf)
    "help": "launch --type=overlay --title current sh -c 'exec \"${KITTY_CONFIG_DIRECTORY:-${XDG_CONFIG_HOME:-$HOME/.config}/kitty}/shortcuts.sh\"'",
}
ROW_WIDTH = 30               # = tab_title_max_length: the row's width when nothing narrows the sidebar
_buttons: dict = {}          # what the search row's columns do (per kitty window), the × columns (per tab)
# the field's words, longest first: a narrow sidebar gets a shorter one (never cut), then none
SEARCH_LABELS = ("Search tabs", "Search", "Find", "")
GLYPHS = {"waiting": "⚠", "settings": "⚙", "new": "+"}   # ⚙ and ⚠ are in DejaVu Sans Mono


def _buttons_on() -> bool:
    return not os.path.exists(BUTTONS_OFF)


def _line_width(bar=None) -> int:
    """How many cells a sidebar line can use. kitty makes the sidebar tab_title_max_length + 1
    columns wide, but never more than a third of the window (state.c, vertical_tab_bar_cols), and
    gives each tab min(columns - 1, tab_title_max_length) cells (its max_title_length). Our own
    rows (search, "+ New tab") are drawn as they are, so they're cut to the same width here."""
    try:
        if bar is None:
            bar = get_boss().active_tab_manager.tab_bar
        width = int(bar.screen.columns) - 1
    except Exception:
        return ROW_WIDTH
    try:
        from kitty.fast_data_types import get_options
        cap = int(get_options().tab_title_max_length)
    except Exception:
        cap = ROW_WIDTH
    if cap > 0:
        width = min(width, cap)
    return max(1, width)


# ---- theme colours (live, so they follow kitty's light/dark switch) ----
# (cosmic-dark's, for when kitty's options can't be read)
THEME_FALLBACK = {
    "background": (0x17, 0x14, 0x1f), "foreground": (0xeb, 0xe7, 0xf2),
    "inactive_tab_background": (0x26, 0x21, 0x2f), "inactive_tab_foreground": (0xa5, 0x9f, 0xb3),
    "active_tab_background": (0xe6, 0x7e, 0x00), "active_tab_foreground": (0x17, 0x14, 0x1f),
    "selection_background": (0x4a, 0x3f, 0x5f), "selection_foreground": (0xf2, 0xef, 0xf7),
    "color3": (0xcf, 0xae, 0x7c), "color7": (0xc8, 0xc3, 0xd2),
}


def _theme() -> dict:
    """The theme's colours as (r, g, b), from kitty's live options."""
    try:
        from kitty.fast_data_types import get_options
        from kitty.utils import color_as_int
        o = get_options()
        out = {}
        for name, fallback in THEME_FALLBACK.items():
            c = getattr(o, name, None)
            if c is None and name == "selection_foreground":
                c = o.foreground
            v = color_as_int(c) if c is not None else None
            out[name] = ((v >> 16) & 255, (v >> 8) & 255, v & 255) if v is not None else fallback
        return out
    except Exception:
        return dict(THEME_FALLBACK)


def _lum(rgb) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _mix(a, b, t: float) -> tuple:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


_quiet_cache: dict = {}


def _quiet(fg, bg, target: float) -> tuple:
    """fg moved toward bg as far as it can go while keeping `target` contrast on bg (fg itself if
    that is already lower): a quieter shade of the theme's own colour, never below the limit
    (AGENTS.md: text 4.5:1, icons 3:1)."""
    key = (fg, bg, target)
    if key not in _quiet_cache:
        lo, hi = 0.0, 1.0
        if _contrast(fg, bg) > target:
            for _ in range(24):
                mid = (lo + hi) / 2
                if _contrast(_mix(fg, bg, mid), bg) >= target:
                    lo = mid
                else:
                    hi = mid
        if len(_quiet_cache) > 64:
            _quiet_cache.clear()
        _quiet_cache[key] = _mix(fg, bg, lo)
    return _quiet_cache[key]


FIELD_CONTRAST = 1.45


def _away(bg, toward, target: float) -> tuple:
    """bg moved toward `toward` until it stands `target` apart from bg (or as far as it can go)."""
    for i in range(1, 41):
        c = _mix(bg, toward, i / 40)
        if _contrast(c, bg) >= target:
            return c
    return toward


def _sgr_fg(rgb) -> str:
    return "\x1b[38;2;%d;%d;%dm" % rgb


def _sgr_bg(rgb) -> str:
    return "\x1b[48;2;%d;%d;%dm" % rgb


QUIET_TEXT, QUIET_ICON = 4.6, 3.2     # just above AGENTS.md's 4.5:1 (text) and 3:1 (icons)


def _row_colours() -> dict:
    """SGR for the search row. The row sits on the inactive tab colour; the field is the terminal's
    own background (an input, set into the row); the buttons are filled with the selection colour
    (its text colour is the theme's pair for it); a held button is the accent (the active tab's
    pair); ⚠ is the amber block it is on a waiting tab. Every pair is at least 4.5:1."""
    t = _theme()
    row_bg, row_fg = t["inactive_tab_background"], t["inactive_tab_foreground"]
    # the field stands out from the row: lighter on a dark theme, white on a light one
    toward = (255, 255, 255) if _lum(row_bg) > 0.4 else t["foreground"]
    field = _away(row_bg, toward, FIELD_CONTRAST)
    hint = t["color7"] if _contrast(t["color7"], field) >= 4.5 else t["foreground"]
    chip_fg = t["selection_foreground"]
    if _contrast(chip_fg, t["selection_background"]) < 4.5:
        chip_fg = max((t["foreground"], t["background"]), key=lambda c: _contrast(c, t["selection_background"]))
    warn_fg = max((t["background"], t["foreground"]), key=lambda c: _contrast(c, t["color3"]))
    return {
        "row": _sgr_bg(row_bg) + _sgr_fg(row_fg),
        "field": _sgr_bg(field) + _sgr_fg(hint),
        "chip": _sgr_bg(t["selection_background"]) + _sgr_fg(chip_fg),
        "warn": _sgr_bg(t["color3"]) + _sgr_fg(warn_fg),
        "pressed": _sgr_bg(t["active_tab_background"]) + _sgr_fg(t["active_tab_foreground"]),
    }


def _row_layout(width: int, waiting: int, pressed=None, colours=None) -> tuple:
    """(the search row's text, [(first col, last col, action)]) for a row `width` cells wide.
    Column 0 is left blank (the tabs' numbers start at 1), the field runs from column 1, and the
    buttons are chips at the right with a cell of row between them, + last with its glyph in
    column width - 2 (where the current tab's × and the times end). A narrower row gets shorter
    words, then 1-cell chips, then no words; ⚙, then ⚠, are left out only when even that doesn't
    fit. A button's click area starts one column before its glyph and runs up to the next button
    (the last one to the sidebar's edge); the field's is everything to the left of the first.
    `pressed`: the action held down right now, drawn in the accent colour."""
    c = colours or _row_colours()
    warn = f"⚠{waiting}" if waiting else ""
    every = (["waiting"] if warn else []) + ["settings", "new"]

    def chips(names, pad):
        return [(n, f" {g} " if pad else g) for n in names
                for g in [warn if n == "waiting" else GLYPHS[n]]]

    def left_of(cs):                               # the chips' first column: the last glyph at width - 2
        pad = _cells(cs[-1][1]) > 1
        return width - (0 if pad else 1) - (sum(_cells(t) for _, t in cs) + len(cs) - 1)

    tries = [(every, pad, label) for pad in (True, False) for label in SEARCH_LABELS[:-1]]
    tries += [(every, pad, "") for pad in (True, False)]
    tries += [([n for n in every if n != "settings"], False, label) for label in SEARCH_LABELS]
    tries += [(["new"], False, label) for label in SEARCH_LABELS]
    pick = None
    for names, pad, label in tries:
        cs = chips(names, pad)
        need = _cells(label) + 4 if label else 0   # margin, " label ", a gap
        if left_of(cs) >= need:
            pick = (cs, pad, label)
            break
    if pick is None:
        pick = (chips(["new"], False), False, "")
    cs, pad, label = pick
    left = max(0, left_of(cs))
    out = c["row"] + (" " if left else "")
    field_w = left - 2                             # between column 0 and the gap before the chips
    if field_w > 0:
        words = f" {label}" if label else ""
        out += (c["pressed"] if pressed == "search" else c["field"]) + words + " " * (field_w - _cells(words))
        out += c["row"] + " "
    elif left > 1:
        out += " " * (left - 1)
    cols, col = [], left
    for i, (n, t) in enumerate(cs):
        if i:
            out += c["row"] + " "
            col += 1
        glyph = col + (1 if pad else 0)
        cols.append([glyph - 1, glyph, n])
        out += (c["pressed"] if pressed == n else c["warn"] if n == "waiting" else c["chip"]) + t
        col += _cells(t)
    out += c["row"] + " " * max(0, width - col)
    for i in range(len(cols) - 1):
        cols[i][1] = cols[i + 1][0] - 1
    cols[-1][1] = width
    return out, [(0, cols[0][0] - 1, "search")] + [tuple(x) for x in cols]


def _search_row(width=None, wid=None) -> str:
    """The row's text (kitty draws it as is), and where its buttons are. Called without arguments
    by the "+ New tab" patch (which may be an older load's), then again by _fit_vertical with the
    sidebar's real width."""
    if not _buttons_on():
        return ""
    held = _pressed.get(wid) if wid is not None else None
    pressed = held[1][1] if held and held[1][0] == "button" else None
    text, cols = _row_layout(width or ROW_WIDTH, _cat.get("blocked", 0), pressed)
    _buttons["cols"] = cols
    if wid is not None:
        _buttons.setdefault("cols_by", {})[wid] = cols
    return text

def _cols_for(wid) -> list:
    """The search row's buttons as last drawn in this kitty window."""
    return _buttons.get("cols_by", {}).get(wid) or _buttons.get("cols", ())


def _cat_cols_for(wid):
    """(first col, last col) of the cat at the end of "+ New tab" as last drawn in this kitty
    window, or None (hidden with kitty-cat off, or no room for it)."""
    by = _buttons.get("cat_by", {})
    return by[wid] if wid in by else _buttons.get("cat")


_clicking = {"on": False}


def _run(name: str) -> None:
    """Run a button's action. Quests teach the keys, so a click doesn't earn their badge."""
    _clicking["on"] = True
    try:
        get_boss().combine(ACTIONS[name])
    except Exception:
        pass
    finally:
        _clicking["on"] = False


_pressed: dict = {}          # os window id -> the region a press of ours landed on
_press_at: dict = {}         # os window id -> when (a lost release mustn't leave a chip lit)
PRESS_LIMIT = 3.0


def _redraw(tm=None) -> None:
    try:
        for m in ([tm] if tm is not None else get_boss().all_tab_managers):
            m.mark_tab_bar_dirty()
        from kitty.fast_data_types import wakeup_main_loop
        wakeup_main_loop()
    except Exception:
        pass


def _region(tm, x, y):
    """Which of our click targets (x, y) is on: ("bubble", command) in the cat's bubble (command
    None between its buttons), ("close",), ("cat",) on the cat (drawn, or its face), ("hidden",),
    ("button", name) or None."""
    bar = tm.tab_bar
    g = bar.window_geometry
    if not (g.left <= x < g.right and g.top <= y < g.bottom):
        return None
    row, col = int((y - g.top) // bar.cell_height), int((x - g.left) // bar.cell_width)
    st = getattr(bar, "_vye_cat", None)
    if isinstance(st, dict):
        cmd = _bubble_hit(bar, st, x - g.left, y - g.top)
        if cmd is not None:
            return ("bubble", None if cmd == "inside" else cmd)
    ext = next((e for e in bar.tab_extents if e.y.start <= row <= e.y.end), None)
    at = tm.active_tab
    close_col = _buttons.get("close_cols", {}).get(at.id) if at is not None else None
    if (ext is not None and at is not None and ext.tab_id == at.id and close_col is not None and _buttons_on()
            and row == _buttons.get("close_row", {}).get(tm.os_window_id, -1) and col >= close_col - 1):
        return ("close",)
    if isinstance(st, dict) and _cat_hit(bar, st, x - g.left, y - g.top):
        return ("cat",)
    info = getattr(bar, "_vye_hidden", None)
    if info and row == info[0]:
        return ("hidden",)
    if ext is None:
        return None
    if ext.tab_id == SEARCH_ROW_ID:
        return ("button", next((a for c0, c1, a in _cols_for(tm.os_window_id) if c0 <= col <= c1), "search"))
    if ext.tab_id < 0 and row == ext.y.start:
        cat = _cat_cols_for(tm.os_window_id)          # the cat face at the end of "+ New tab"
        if cat and cat[0] <= col <= cat[1]:
            return ("cat",)
        return None
    return None


def _sidebar_click(tm, x, y, button, action) -> bool:
    """Clicks kitty mustn't see: the cat (a click opens its bubble; a drag carries it), the bubble's
    buttons, the "hidden: …" line (goes to the first hidden tab), the search row's words and
    buttons, and the × on the current tab. A press there is swallowed (kitty never starts a drag or
    counts a click), and the action runs on the release only if it lands on the same target as the
    press; releases of presses kitty saw go to kitty. A press anywhere else closes the cat's bubble.
    True when the event was ours."""
    try:
        from kitty.fast_data_types import GLFW_MOUSE_BUTTON_LEFT, GLFW_PRESS, GLFW_RELEASE
        wid = tm.os_window_id
        if button == -1:
            if wid in _cat_drag:                    # carrying the cat: it follows the pointer
                _cat_drag_motion(tm, x, y)
                return True
            return False
        if action not in (GLFW_PRESS, GLFW_RELEASE):
            return False
        if action == GLFW_PRESS and wid in _cat_drag:   # a release we never got: drop it first
            _cat_drop(tm)
        if action == GLFW_RELEASE and wid in _cat_drag:
            _pressed.pop(wid, None)
            _press_at.pop(wid, None)
            if _cat_drop(tm):
                return True                         # it was carried: no click
            _cat_clicked(tm)
            return True
        here = _region(tm, x, y)
        if action == GLFW_PRESS:
            st = getattr(tm.tab_bar, "_vye_cat", None)
            if isinstance(st, dict) and st.get("bubble") is not None and (here is None or here[0] not in ("bubble", "cat")):
                _bubble_close(tm, st)               # a click elsewhere: the bubble goes (the click still works)
            if here is None:
                _pressed.pop(wid, None)
                return False
            _pressed[wid] = (button, here)
            _press_at[wid] = time.monotonic()
            if here == ("cat",) and button == GLFW_MOUSE_BUTTON_LEFT and isinstance(st, dict) and st.get("mode") == "floor":
                _cat_drag_start(tm, x, y)           # a click, or the start of carrying it
            if here[0] == "button" and button == GLFW_MOUSE_BUTTON_LEFT:
                _redraw(tm)                         # the chip lights up while it's held
            return True
        pressed = _pressed.pop(wid, None)
        _press_at.pop(wid, None)
        if pressed is None:
            return False                            # kitty saw the press: it gets the release
        if pressed[1][0] == "button":
            _redraw(tm)                             # and goes back to normal
        if pressed == (GLFW_MOUSE_BUTTON_LEFT, here):
            if here == ("hidden",):
                tab = tm.tab_for_id(tm.tab_bar._vye_hidden[1])
                if tab is not None:
                    tm.set_active_tab(tab)
            elif here == ("close",):
                _close_current(tm)
            elif here == ("cat",):
                _cat_clicked(tm)
            elif here[0] == "bubble":
                _bubble_do(tm, here[1])
            else:
                _run(here[1])
        return True
    except Exception:
        _pressed.pop(getattr(tm, "os_window_id", 0), None)
        if getattr(tm, "os_window_id", None) in _cat_drag:
            _cat_drag.pop(tm.os_window_id, None)
            _cat_drag_end()
        return False


def _close_current(tm) -> None:
    """Close the clicked window's current tab (asks first if something runs), not the boss's."""
    tab = tm.active_tab
    boss = get_boss()
    _clicking["on"] = True
    try:
        if tab is not None and hasattr(boss, "close_tab"):
            boss.close_tab(tab)
        else:
            boss.combine(ACTIONS["close"])
    except Exception:
        pass
    finally:
        _clicking["on"] = False


_hidden_line_click = _sidebar_click      # the name earlier loads' mouse patch looks up


_layout_noted: dict = {}      # os window id -> what it shows


def _note_layout(bar, data, shown_ids, hidden) -> None:
    """sidebar.txt in the state folder: which tabs the active kitty window's sidebar shows, which
    agent marks they have, and where the "hidden" line is, written when it changes (check.sh reads
    it to test a short window and restored agents; it's also handy when a tab seems to be missing)."""
    try:
        wid = getattr(bar, "os_window_id", 0)
        nums = {t.tab_id: n for n, t in enumerate((t for t in data if t.tab_id > 0), 1)}
        marks = [("❯" if t.tab_id == SEARCH_ROW_ID else "+" if t.tab_id < 0 else str(nums[t.tab_id]))
                 for t in data if t.tab_id in shown_ids]
        text = f"shown: {' '.join(marks)}\nhidden: {_number_ranges(hidden) or 'none'}\n"
        # the agent marks drawn under the status icons (from their cache: no /proc reads here)
        agents = [f"{nums[t.tab_id]}:{_agents[t.tab_id][1]}" for t in data
                  if t.tab_id in shown_ids and t.tab_id > 0 and _agents.get(t.tab_id, (0, ""))[1]]
        text += f"agents: {' '.join(agents) or 'none'}\n"
        # which kitty wrote it: after a restart, tells the new kitty's first write from the old one's
        text += f"kitty: {os.getpid()}\n"
        info = getattr(bar, "_vye_hidden", None)
        g = bar.window_geometry

        def px(col, row):
            return f"{g.left + col * bar.cell_width + bar.cell_width // 2} {g.top + row * bar.cell_height + bar.cell_height // 2}"
        if info:
            text += f"click: {px(4, info[0])}\n"
        top = next((e for e in bar.tab_extents if e.tab_id == SEARCH_ROW_ID), None)
        if top is not None:                         # where the search row's buttons are (check.sh)
            for c0, c1, name in _cols_for(wid):
                text += f"button {name}: {px((c0 + c1) // 2 if name == 'search' else c0 + 1, top.y.start)}\n"
        new = next((e for e in bar.tab_extents if e.tab_id < 0 and e.tab_id != SEARCH_ROW_ID), None)
        cat = _cat_cols_for(wid)
        if new is not None and cat:                 # the cat at the end of "+ New tab" (the helper)
            text += f"button cat: {px(cat[0] + 3, new.y.start)}\n"
        at = next((t.tab_id for t in data if t.tab_id > 0 and t.is_active), None)
        close_col = _buttons.get("close_cols", {}).get(at)
        crow = _buttons.get("close_row", {}).get(wid, -1)
        if crow >= 0 and close_col is not None and _buttons_on():
            text += f"button close: {px(close_col, crow)}\n"
        # what kitty really drew there, read back from the sidebar's cells, so check.sh can compare
        # it with the columns above: the column of each glyph, and the sidebar's cell grid
        text += f"cells: {g.left} {g.top} {bar.cell_width} {bar.cell_height} {bar.screen.columns}\n"
        # the first row of each tab shown (number:row), e.g. to click one, or to point at one
        rows = {e.tab_id: e.y.start for e in bar.tab_extents}
        text += "tabs: " + " ".join(f"{nums[t.tab_id]}:{rows[t.tab_id]}" for t in data if t.tab_id in rows and t.tab_id > 0) + "\n"
        if crow >= 0 and at in nums:
            # the current tab's folder line (agent mark, folder, branch), read back from the cells
            text += f"active: {nums[at]}\ndrawn folder: {_screen_text(bar, crow + 1).strip()}\n"
            if not _full["on"]:
                # and its name line (check.sh: a command shows no arguments); never with
                # kitty-commands full, so a whole command line is never written down
                text += f"drawn name: {_screen_text(bar, crow).strip()}\n"
        for row, glyphs in ((top.y.start if top is not None else -1, "⚠⚙+"), (crow, "×")):
            line = _screen_text(bar, row)
            for ch in glyphs:
                if ch in line:
                    text += f"drawn {ch}: {_cells(line[:line.index(ch)])}\n"
        if _layout_noted.get(wid) == text:
            return
        _layout_noted[wid] = text
        atm = get_boss().active_tab_manager
        if atm is not None and atm.os_window_id != wid:
            return                                  # another kitty window: only the active one is written
        _write_atomic(os.path.join(QUEST_DIR, "sidebar.txt"), text)
    except Exception:
        pass


def _screen_text(bar, row: int) -> str:
    """The text kitty drew on one row of the sidebar ("" if unknown)."""
    try:
        return str(bar.screen.line(row)) if 0 <= row < bar.screen.lines else ""
    except Exception:
        return ""


def _number_ranges(nums) -> str:
    """[1, 2, 3, 7] -> "1–3, 7" """
    out, run = [], []
    for n in sorted(nums):
        if run and n == run[-1] + 1:
            run.append(n)
            continue
        if run:
            out.append(f"{run[0]}–{run[-1]}" if len(run) > 1 else str(run[0]))
        run = [n]
    if run:
        out.append(f"{run[0]}–{run[-1]}" if len(run) > 1 else str(run[0]))
    return ", ".join(out)


_dragging: dict = {}         # os window id -> id of the tab being dragged inside the sidebar


def _patch_tab_drag_in_window() -> None:
    """Wayland (COSMIC): kitty 0.50 hands a dragged tab to the compositor's drag-and-drop, gives up
    before COSMIC confirms it ("start_drag was silently ignored by the compositor") and cancels, so
    tabs can't be dragged at all. Reorder inside the sidebar ourselves instead: past drag_threshold we
    never tell kitty a drag started, so kitty keeps sending us every move and the release, and we use
    kitty's own drop marker and re-ordering. Release outside the sidebar to cancel. Dragging a tab to
    another kitty window isn't possible this way. X11 keeps kitty's normal drag."""
    try:
        import kitty.tabs as _tabs
        from kitty.constants import is_wayland
        from kitty.fast_data_types import (GLFW_MOUSE_BUTTON_LEFT, GLFW_RELEASE, get_options,
                                           get_tab_being_dragged, set_tab_being_dragged)
    except Exception:
        return
    TabManager = getattr(_tabs, "TabManager", None)
    TabBeingDropped = getattr(_tabs, "TabBeingDropped", None)
    orig = getattr(TabManager, "handle_tab_bar_mouse", None)
    if orig is None or TabBeingDropped is None or getattr(orig, "_vye_patched", False):
        return

    def show_marker(tm, tab_id, x, y):
        bar = tm.tab_bar
        g = bar.window_geometry
        before = None                 # None: no marker (pointer is outside the sidebar)
        tm.tab_being_dropped = None
        if g.left <= x < g.right and g.top <= y < g.bottom:
            ids = [t.id for t in tm.tabs_to_be_shown_in_tab_bar]
            before = bar.tab_insertion_target_at(x, y)    # 0: after the last tab
            i = ids.index(before) if before in ids else len(ids)
            order = [t for t in ids[:i] if t != tab_id] + [tab_id] + [t for t in ids[i:] if t != tab_id]
            tm.tab_being_dropped = TabBeingDropped(tab_id=tab_id, tab_ids=order)
        if bar.tab_drop_insert_before != before:
            bar.tab_drop_insert_before = before
            tm.mark_tab_bar_dirty()

    def handle_tab_bar_mouse(self, x, y, button, modifiers, action):
        try:
            ours = _dragging.get(self.os_window_id)
            import kitty.tab_bar as kt
            click = getattr(kt, "_vye_hidden_line_click", None)
            if not ours and click is not None and click(self, x, y, button, action):
                return
            coach = getattr(kt, "_vye_tab_clicked", None)
            if not ours and coach is not None:
                coach(self, x, y, button, action)
            if not ours and not is_wayland():
                return orig(self, x, y, button, modifiers, action)
            if button == -1:          # motion
                tab_id, started, sx, sy = get_tab_being_dragged()
                if tab_id and not started and self.tab_for_id(tab_id) is not None:
                    threshold = get_options().drag_threshold
                    if ours != tab_id and threshold and (x - sx) ** 2 + (y - sy) ** 2 > threshold ** 2:
                        _dragging[self.os_window_id] = ours = tab_id
                        self.recent_tab_bar_mouse_events.clear()  # the press must not count as a click
                    if ours == tab_id:
                        show_marker(self, tab_id, x, y)
                        return
            elif ours:
                del _dragging[self.os_window_id]
                if button == GLFW_MOUSE_BUTTON_LEFT and action == GLFW_RELEASE:
                    show_marker(self, ours, x, y)
                    if self.tab_being_dropped is not None:
                        _quest_hit("drag")
                        _hook("drop")
                        self.on_tab_drop(x, y, bypass_move=True)   # re-orders, clears the drag
                        return
                self.tab_being_dropped = None                    # cancelled
                self.tab_bar.tab_drop_insert_before = None
                set_tab_being_dragged()
                self.mark_tab_bar_dirty()
                return
        except Exception:
            _dragging.pop(self.os_window_id, None)
        return orig(self, x, y, button, modifiers, action)
    handle_tab_bar_mouse._vye_patched = True
    TabManager.handle_tab_bar_mouse = handle_tab_bar_mouse


NEW_TAB_LABEL = "  +   New tab"   # "+" in the number column, the words in the name column


AMBER, GREEN = "\x1b[33m", "\x1b[32m"
# The cat's colour follows its mood (palette colours, so both themes work; each is at least 3.9:1 on
# the sidebar in either theme): amber when a tab needs you (the colour of ⚠), gold for a badge, green
# when a tab just finished, red for an error, blue while tabs work (the spinner's colour), lavender
# asleep. Idle, it is a ginger cat: colour 130 of the 256 (#af5f00, the same in both themes; the
# palette has no orange), 3.3:1 on the dark sidebar and 3.6:1 on the light one.
CAT_COLOUR = {"alert": "\x1b[33m", "badge": "\x1b[33m", "happy": "\x1b[32m", "startled": "\x1b[31m",
              "working": "\x1b[34m", "asleep": "\x1b[35m", "idle": "\x1b[38;5;130m"}
CAT_WIDTH = 9                # the widest face and its extras ("=-.-= zZz", "=^ω^= ♪♪♪")
CAT_NIGHT = (23, 6)          # from 23:00 to 06:00 (local time) the idle cat sleeps

# The cat moves like a small animated pet. Its face is five cells, each a channel:
# left whisker, left eye, mouth, right eye, right whisker ("=^.^="), and its tail is the cell after
# the gap (" ~"). A move changes some channels for a few frames (one frame = TICK, 0.125 s), on top
# of the mood's own face, so moves overlap: a blink during a tail flick changes both. Each channel
# is one glyph per frame; a space leaves the mood's own. A move shows only in the moods it lists
# (a hop queued for "happy" stays hidden when a tab starts waiting), and the later entries here win
# a channel they share (a blink closes the eyes even mid-glance). Only plain ASCII and the ω the
# happy face already has, so every frame is single-width and crisp in DejaVu Sans Mono, and the
# face never moves: it is always 5 cells, the extras at most CAT_WIDTH.
_CAT_CHANNELS = {"lw": 0, "le": 1, "m": 2, "re": 3, "rw": 4}
CAT_MOVES = {
    #  name          moods it shows in               channel: a glyph per frame
    "tail":        ({"idle"},                        {"tail": "~~--~~--"}),             # 1.0 s flick
    "ear-left":    ({"idle", "working"},             {"lw": "~~  ~~  "}),               # twitch twice
    "ear-right":   ({"idle", "working"},             {"rw": "~~  ~~  "}),
    "look-left":   ({"idle", "working"},             {"le": "<" * 8, "re": "<" * 8}),   # =<.<=, 1 s
    "look-right":  ({"idle", "working"},             {"le": ">" * 8, "re": ">" * 8}),   # =>.>=
    "wink":        ({"idle", "working"},             {"re": "-" * 5, "m": "ω" * 5}),    # =^ω-=, 0.6 s
    "surprise":    ({"alert"},                       {"lw": "~~  ", "m": "oooo", "rw": "~~  "}),  # ~OoO~
    "flinch":      ({"startled"},                    {"lw": "~~  ~~", "rw": "~~  ~~"}),  # ~>.<~
    "hop":         ({"happy"},                       {"le": ">>>>", "re": "<<<<"}),     # =>ω<=, 0.5 s
    "wave":        ({"happy"},                       {"rw": "//  //  /"}),              # =^ω^/, 1.1 s
    "cheer":       ({"badge"},                       {"lw": "\\\\  \\\\  \\", "rw": "//  //  /"}),  # \^▽^/
    "blink":       ({"idle", "working", "happy", "badge"}, {"le": "-", "re": "-"}),  # =-.-=, 1 frame
}
CAT_FIDGETS = ("wink", "ear-left", "ear-right", "look-left", "look-right", "tail")
CAT_ROLL = 8                 # frames between rolls of the dice (once a second)
CAT_BLINK = 0.22             # chance of a blink at each roll
CAT_FIDGET = 0.03            # chance of a fidget at each roll (when no other move plays)


def _move_len(name: str) -> int:
    return max(len(g) for g in CAT_MOVES[name][1].values())


def _cat_start(name: str, delay: int = 0) -> None:
    _cat["moves"][name] = _frame + delay


def _cat_react() -> None:
    """Called by the timer: start the cat's moves. A reaction to what just happened (a tab starts
    waiting: surprise; one finished: a hop, then a wave; a badge: a cheer; an error: a flinch), or,
    once a second, a roll of the dice: often a blink, now and then a fidget. Never while a tab
    waits (that stare holds still, however long the wait), asleep or hidden. The face itself (_cat_mood) only reads what this left, so drawing it twice gives the
    same frame, and nothing is redrawn between moves."""
    try:
        seen = _cat_seen()
        before = _cat["seen"]
        _cat["seen"] = seen
        moves = _cat["moves"]
        for name in [n for n, start in moves.items() if _frame - start >= _move_len(n)]:
            del moves[name]                       # finished
        if before is not None:                    # (the first look after loading reacts to nothing)
            if seen[0] > before[0]:              # (a count of new waits: only goes up)
                _cat_start("surprise")
            if seen[1] != before[1]:
                _cat_start("hop")
                _cat_start("wave", _move_len("hop"))
            if seen[2] != before[2]:
                _cat_start("flinch")
            if seen[3] > before[3]:
                _cat_start("cheer")
        if _frame < _cat["roll"]:
            return
        _cat["roll"] = _frame + CAT_ROLL
        mood = _cat_base(time.monotonic())[0]
        if mood not in CAT_MOVES["blink"][0] or os.path.exists(CAT_OFF) or not _text_cat_shown():
            return                                # (alert, startled, asleep, the drawn cat out: no dice)
        r = _cat_rng.random()
        if r < CAT_BLINK:
            _cat_start("blink")
        elif r < CAT_BLINK + CAT_FIDGET and not moves:
            pool = [n for n in CAT_FIDGETS if mood in CAT_MOVES[n][0]]
            if pool:
                _cat_start(_cat_rng.choice(pool))
    except Exception:
        pass


def _text_cat_shown() -> bool:
    """Some kitty window shows the cat face at the end of "+ New tab" (not the drawn cat)."""
    try:
        modes = [_cat_modes.get(tm.os_window_id, "text") for tm in get_boss().all_tab_managers]
        return not modes or "text" in modes
    except Exception:
        return True


def _night() -> bool:
    h = time.localtime().tm_hour
    return h >= CAT_NIGHT[0] or h < CAT_NIGHT[1]


def _cat_base(now: float) -> tuple:
    """(mood, face, extras) before any move: the face is 5 cells, the extras (its tail, notes, the
    "!") follow it. Most important mood first: alert (a tab needs you; "2!" = two tabs) · badge
    (cheering; ♛ = new rank) · happy (just finished) · startled (error) · working (watching; the
    tail swishes) · asleep (zZ; at night as soon as nothing works or waits) · idle."""
    if _cat["blocked"]:                # status first: a waiting tab beats any celebration
        n = _cat["blocked"]
        bang = (str(n) if n > 1 else "") + "!"
        if _cat["fresh_block"] and (_frame // 4) % 2:
            bang = " " * len(bang)
        return "alert", "=O.O=", f" {bang}"
    if _badge_shown["until"] > now:
        crown = "♛" if _badge_shown.get("rank") else ""
        return "badge", "=^▽^=", f"{crown}{TWINKLE[_frame % len(TWINKLE)]}"
    if now - _cat["done_at"] < 4:
        # one note per tab in the current run of finishes (the streak), up to three
        notes = min(3, _streak["step"]) if now - _streak["at"] < 4 else 1
        return "happy", "=^ω^=", f" {'♪' * max(1, notes)}"
    if now - _cat["error_at"] < 4:
        return "startled", "=>.<=", " "
    if _cat["working"]:
        return "working", "=^.^=", " " + "~-"[(_frame // 4) % 2]
    quiet = now - _cat["quiet_since"]
    if _night():
        quiet += SLEEP_AFTER           # at night it dozes off as soon as nothing works or waits
    if quiet >= SLEEP_AFTER:
        if quiet >= SLEEP_AFTER + 60:
            return "asleep", "=-.-=", " zZ"         # fully asleep: no more redraws
        return "asleep", "=-.-=", " " + ("z", "zz", "zZ", "zZz")[(_frame // 12) % 4]
    return "idle", "=^.^=", ""


def _cat_mood() -> tuple:
    """(mood, face) for the cat at the end of "+ New tab": the mood's face (_cat_base) with the
    moves playing now (CAT_MOVES) on top. Reads only, so the timer and the draw agree."""
    mood, face, extras = _cat_base(time.monotonic())
    cells = list(face)
    moves = _cat["moves"]
    for name, (moods, channels) in CAT_MOVES.items():
        start = moves.get(name)
        if start is None or mood not in moods:
            continue
        i = _frame - start
        for ch, glyphs in channels.items():
            if 0 <= i < len(glyphs) and glyphs[i] != " ":
                if ch == "tail":
                    extras = " " + glyphs[i]
                else:
                    cells[_CAT_CHANNELS[ch]] = glyphs[i]
    return mood, "".join(cells) + extras


def _cat_face() -> str:
    """The cat's current frame in its mood's colour, e.g. "\x1b[34m=^.^= ~\x1b[39m" ("" when
    kitty-cat off hides it)."""
    if os.path.exists(CAT_OFF):
        return ""
    mood, face = _cat_mood()
    col = CAT_COLOUR.get(mood, "")
    return f"{col}{face}{FG}" if col else face


def _visible(s: str) -> str:
    return re.sub("\x1b\\[[0-9;:]*m", "", s)


NEW_TAB_LABELS = (NEW_TAB_LABEL, "  +   New", "  +")   # shorter ones for a narrow sidebar


def _new_tab_label(width=None, wid=None, cat_mode=None) -> str:
    """ "+ New tab" with the cat at its right end, and under it the next quest (or the badge
    just earned), both fitted to `width` cells (the sidebar's; ROW_WIDTH if not known). Where the
    cat went is kept for clicks (a click on it opens its bubble), per kitty window `wid`. While the
    drawn cat shows (cat_mode "floor" or "small"), no cat face; "small": the drawn cat sits at the
    right end of both lines, so the quest takes a shorter wording."""
    width = width or ROW_WIDTH
    if _label_kind(cat_mode) != "text":
        line1 = next((l for l in NEW_TAB_LABELS if _cells(l) <= width), "")
        if wid is None:
            _buttons["cat"] = None
        else:
            _buttons.setdefault("cat_by", {})[wid] = None
        line2 = ""
        try:
            line2 = _quest_line(width - (6 if cat_mode == "small" else 0))
        except Exception:
            pass
        return line1 + ("\n" + line2 if line2 else "")
    line1, line2 = next((l for l in NEW_TAB_LABELS if _cells(l) <= width), ""), ""
    where = None
    try:
        cat = _cat_face()
        _cat["drawn"] = cat
        if cat:
            # the cat starts at a fixed column, so its face stays put while its extras (z, zZz, ♪♪)
            # come and go, and the words don't flip between "New tab" and "New"; it ends by the
            # column of the search row's + and the ×. A narrow sidebar shortens the words first
            # (the + says it), then leaves the cat out.
            seen = _cells(_visible(cat))
            at = max(0, width - 1 - max(CAT_WIDTH, seen))
            label = next((l for l in NEW_TAB_LABELS if _cells(l) + 2 <= at), None)
            if label is not None:
                line1 = label + " " * (at - _cells(label)) + cat
                where = (at - 1, width)               # a cell before the face, to the row's end
    except Exception:
        pass
    if wid is None:
        _buttons["cat"] = where
    else:
        _buttons.setdefault("cat_by", {})[wid] = where
    try:
        line2 = _quest_line(width)
    except Exception:
        pass
    return line1 + ("\n" + line2 if line2 else "")


def _patch_new_tab_button() -> None:
    """kitty draws its new-tab button as a bare "+" against the left edge. Label it and line it up
    with the tabs above it."""
    try:
        import kitty.tabs as _tabs
    except Exception:
        return
    prop = getattr(getattr(_tabs, "TabManager", None), "tab_bar_data", None)
    fget = getattr(prop, "fget", None)
    if fget is None or getattr(fget, "_vye_patched", False):
        return

    def tab_bar_data(self):
        tabs = fget(self)
        try:
            last = tabs[-1] if tabs else None
            if last is not None and last.tab_id < 0 and last.title == "+":
                import kitty.tab_bar as kt
                label = getattr(kt, "_vye_new_tab_label", None)
                tabs = tabs[:-1] + (last._replace(title=label() if label else "  +   New tab"),)
                top = getattr(kt, "_vye_search_row", None)        # the search row and buttons on top
                text = top() if top else ""
                if text:
                    tabs = (last._replace(title=text, tab_id=SEARCH_ROW_ID, is_active=False),) + tabs
        except Exception:
            pass
        return tabs
    tab_bar_data._vye_patched = True
    _tabs.TabManager.tab_bar_data = property(tab_bar_data)


# ---- Quests and badges: learn kitty by doing ----
# Each quest is one shortcut worth knowing. kitty sees every shortcut you press (Boss.dispatch_action),
# so when you use one for the first time you earn its badge: a bell run (muted with the sounds; a new rank gets a fanfare), a
# desktop notification, and a short sparkle in the sidebar. The next quest is shown under
# "+ New tab" and sometimes as the tip under a new shell prompt.
#   kitty-quests        list every quest and badge      kitty-quests off / on   hide / show them
# Progress: ~/.local/state/ninelives/badges (one "id<TAB>date" line per badge; never overwritten by
# install.sh). kitty also writes quests.txt (what kitty-quests prints) and next-quest there.
QUEST_DIR = os.environ.get("NINELIVES_STATE") or os.path.expanduser("~/.local/state/ninelives")
BADGES_FILE = os.path.join(QUEST_DIR, "badges")
QUEST_LIST_FILE = os.path.join(QUEST_DIR, "quests.txt")
NEXT_QUEST_FILE = os.path.join(QUEST_DIR, "next-quest")
QUESTS_OFF = os.path.join(CONFIG_DIR, "quests-off")
BADGE_SECONDS = 8.0
# id, badge, short hint (sidebar, ≤ 24 cells), full hint (prompt tip and kitty-quests)
QUESTS = (
    ("split", "Splitter", "Ctrl+Alt+→  split", "Ctrl+Alt+→ splits this tab side by side (Ctrl+Alt+↓: top/bottom)"),
    ("panes", "Pathfinder", "Ctrl+Alt+←  go to pane", "Ctrl+Alt+arrows move between split panes"),
    ("zoom", "Zoom Lens", "Ctrl+Alt+Z  zoom pane", "Ctrl+Alt+Z zooms one pane to full size (again to go back)"),
    ("jump", "Jumper", "Alt+1…9  jump to tab", "Alt+1 … Alt+9 jumps straight to that tab"),
    ("drag", "Shuffler", "drag a tab  reorder", "Drag a tab in the sidebar to reorder it (or Ctrl+Shift+←/→)"),
    ("rename", "Name Tag", "Ctrl+Shift+R  rename", "Ctrl+Shift+R gives the current tab your own name"),
    ("prompts", "Time Traveller", "Ctrl+Shift+Z  prev cmd", "Ctrl+Shift+Z / X jumps to the previous / next command you ran"),
    ("output", "Replay", "Ctrl+Shift+G  output", "Ctrl+Shift+G shows the last command's output on its own"),
    ("scrollback", "Deep Diver", "Ctrl+Shift+H  history", "Ctrl+Shift+H opens the scrollback in a pager (/ searches, q quits)"),
    ("hints", "Link Hunter", "Ctrl+Shift+E  open link", "Ctrl+Shift+E opens any link on screen by typing its hint letter"),
    ("unicode", "Glyph Finder", "Ctrl+Shift+U  emoji", "Ctrl+Shift+U types any emoji or symbol by name"),
    ("fontsize", "Big Print", "Ctrl+Shift+=  text size", "Ctrl+Shift+= / - changes the text size (Ctrl+Shift+Backspace resets)"),
    ("help", "Map Reader", "F1  all shortcuts", "F1 shows every shortcut on one page"),
    ("mute", "Hush", "Ctrl+Alt+M  mute", "Ctrl+Alt+M mutes / unmutes the tab sounds"),
    ("search", "Seeker", "Ctrl+Shift+Space  find", "Ctrl+Shift+Space searches your tabs by name, folder or number"),
    ("waiting", "First Responder", "Ctrl+Alt+U  waiting tab", "Ctrl+Alt+U jumps to the tab waiting for you (⚠)"),
)
QUEST_BY_ID = {q[0]: q for q in QUESTS}
# Ranks by number of badges, cat-themed.
RANKS = ((0, "Kitten"), (4, "House Cat"), (9, "Alley Cat"), (len(QUESTS), "Nine Lives"))
# kitty action name -> quest (args are checked for the ones that share an action)
ACTION_QUEST = {
    "neighboring_window": "panes", "toggle_layout": "zoom", "goto_tab": "jump",
    "move_tab_forward": "drag", "move_tab_backward": "drag", "set_tab_title": "rename",
    "scroll_to_prompt": "prompts", "show_last_command_output": "output",
    "show_scrollback": "scrollback", "open_url_with_hints": "hints", "unicode_input": "unicode",
    "change_font_size": "fontsize",
}


def _load_badges() -> dict:
    earned = {}
    try:
        with open(BADGES_FILE, encoding="utf-8") as f:
            for line in f:
                qid, _, day = line.rstrip("\n").partition("\t")
                if qid in QUEST_BY_ID:
                    earned[qid] = day
    except OSError:
        pass
    return earned


_earned = _load_badges()
_badge_shown = {"id": None, "until": 0.0}

# Mastery: a badge is earned with the first use; using the shortcut MASTER_AT times masters it (✪).
# Counts live in the state folder's `uses` (one "id<TAB>count" line per quest).
USES_FILE = os.path.join(QUEST_DIR, "uses")
MASTER_AT = 10


def _load_uses() -> dict:
    uses = {}
    try:
        with open(USES_FILE, encoding="utf-8") as f:
            for line in f:
                qid, _, n = line.rstrip("\n").partition("\t")
                if qid in QUEST_BY_ID and n.isdigit():
                    uses[qid] = int(n)
    except OSError:
        pass
    return uses


_uses = _load_uses()


def _mastered() -> list:
    return [q[0] for q in QUESTS if _uses.get(q[0], 0) >= MASTER_AT]


def _rank(n: int) -> tuple:
    """(current rank, next rank or None, badges needed for it)."""
    cur, nxt = RANKS[0][1], None
    for need, name in RANKS:
        if n >= need:
            cur = name
        elif nxt is None:
            nxt = (name, need)
    return cur, nxt


QUEST_CHOICES = 3     # the next quest rotates daily among the first few not done yet (easy ones first)


def _day() -> int:
    t = time.localtime()
    return t.tm_year * 366 + t.tm_yday


def _next_quest():
    """Today's quest: one of the first QUEST_CHOICES not done yet, a different one each day, so a
    quest you don't care for doesn't sit under "+ New tab" forever."""
    left = [q for q in QUESTS if q[0] not in _earned][:QUEST_CHOICES]
    return left[_day() % len(left)] if left else None


def _write_atomic(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _write_quest_files(badges: bool = True) -> None:
    """badges (the progress), quests.txt (kitty-quests prints it) and next-quest (prompt tip).
    badges=False leaves the badges file alone (a use of a shortcut already earned changes nothing there)."""
    try:
        os.makedirs(QUEST_DIR, exist_ok=True)
        if badges:
            _write_atomic(BADGES_FILE, "".join(f"{q[0]}\t{_earned[q[0]]}\n" for q in QUESTS if q[0] in _earned))
        n = len(_earned)
        rank, nxt = _rank(n)
        # Colours are palette colours (follow the theme); gold is only used on glyphs (★ →), where
        # 3:1 is enough, so the words stay readable on the light theme too.
        B, NB, D, ND, G, Y, F = "\x1b[1m", "\x1b[22m", "\x1b[37m", "\x1b[39m", "\x1b[32m", "\x1b[33m", "\x1b[39m"
        bar = f"{Y}{'★' * n}{F}{D}{'·' * (len(QUESTS) - n)}{ND}"
        # Rows are "prefix US style US description" (US = \x1f): kitty-quests wraps the description
        # to the window, indented under itself, so narrow windows and split panes stay tidy.
        US = "\x1f"
        head = f"{B}NineLives quests{NB}   {bar}  {n}/{len(QUESTS)}   rank: {B}{rank}{NB}"
        rows = [head] + ([f"{D}next rank: {nxt[0]} at {nxt[1]} badges{ND}"] if nxt else []) + [""]
        width = max(len(q[1]) for q in QUESTS)
        upcoming = _next_quest()
        for qid, badge, _short, full in QUESTS:
            used = _uses.get(qid, 0)
            if used >= MASTER_AT:                 # mastered: a gold ✪, the count in full colour
                rows.append(f"  {Y}✪{F} {badge:<{width}}  {_earned.get(qid, ''):<10}  {f'{used}×':>4}  {US}{D}{US}{full}")
            elif qid in _earned:
                tally = f"{used}/{MASTER_AT}" if used else ""
                rows.append(f"  {G}✓{F} {D}{badge:<{width}}  {_earned[qid]:<10}  {tally:>5} {ND}{US}{D}{US}{full}")
            elif upcoming and qid == upcoming[0]:
                rows.append(f"  {Y}→{F} {B}{badge:<{width}}  {'next up':<10}  {'':>5} {NB}{US}{B}{US}{full}")
            else:
                rows.append(f"  {D}·{ND} {badge:<{width}}  {'':<10}  {'':>5} {US}{US}{full}")
        m = len(_mastered())
        rows += ["", f"{D}Use a shortcut once to earn its badge, {MASTER_AT} times to master it (✪)"
                     f"{f': {m} mastered' if m else ''}.{ND}",
                 f"{D}kitty-quests off hides quests (badges are kept).{ND}"]
        _write_atomic(QUEST_LIST_FILE, "\n".join(rows) + "\n")
        q = _next_quest()
        _write_atomic(NEXT_QUEST_FILE, (q[3] + "\n") if q else "")
    except OSError:
        pass


def _notify(title: str, body: str) -> None:
    if os.environ.get("NINELIVES_QUIET"):            # a dev/test kitty: no desktop notifications
        return
    try:
        subprocess.Popen(_notify_cmd(title, body),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def _notify_cmd(title: str, body: str) -> list:
    if IS_MACOS:
        # The text goes to the script as arguments, never into its source. (osascript would read
        # a first argument starting with "-" as an option.)
        return ["osascript", "-e", "on run argv",
                "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
                "-e", "end run", " " + title if title.startswith("-") else title, body]
    return ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
            "--object-path", "/org/freedesktop/Notifications",
            "--method", "org.freedesktop.Notifications.Notify",
            "NineLives", "0", "starred-symbolic", title, body, "[]", "{}", "6000"]


def _count_use(qid: str, write: bool = True) -> None:
    """One more use of a learned shortcut; the MASTER_AT-th masters it: the line under "+ New tab"
    sparkles "mastered: …", the gold wave runs, and the badge sound plays (no notification: it's a
    quiet milestone, not news). write: rewrite quests.txt, whose n/10 tally kitty-quests shows
    (the caller does it when it writes the files itself anyway)."""
    _uses[qid] = _uses.get(qid, 0) + 1
    try:
        _write_atomic(USES_FILE, "".join(f"{q[0]}\t{_uses[q[0]]}\n" for q in QUESTS if q[0] in _uses))
    except OSError:
        pass
    if write:
        _write_quest_files(badges=False)
    if _uses[qid] == MASTER_AT:
        global _wave_start
        _badge_shown.update(id=qid, until=time.monotonic() + BADGE_SECONDS, rank=False, mastered=True)
        _wave_start = _frame
        _play("badge")
        try:
            for tm in get_boss().all_tab_managers:
                tm.mark_tab_bar_dirty()
        except Exception:
            pass


def _quest_done(qid: str) -> None:
    if qid not in QUEST_BY_ID or os.path.exists(QUESTS_OFF):
        return
    if qid in _earned:
        _count_use(qid)
        return
    _uses[qid] = 0                       # the first use earns the badge; _count_use makes it 1
    _count_use(qid, write=False)
    before = _rank(len(_earned))[0]
    _earned[qid] = time.strftime("%Y-%m-%d")
    _write_quest_files()
    n = len(_earned)
    rank = _rank(n)[0]
    global _wave_start
    _badge_shown.update(id=qid, until=time.monotonic() + BADGE_SECONDS, rank=rank != before, mastered=False)
    _wave_start = _frame
    _play("rank" if rank != before else "badge")
    body = f"{QUEST_BY_ID[qid][3]}\n★ {n}/{len(QUESTS)}"
    if rank != before:
        body += f" · new rank: {rank}!"
    nxt = _next_quest()
    if nxt:
        body += f"\nNext quest: {nxt[3]}"
    _notify(f"Badge earned: {QUEST_BY_ID[qid][1]}", body)
    try:
        for tm in get_boss().all_tab_managers:
            tm.mark_tab_bar_dirty()
    except Exception:
        pass


def _quest_action(func: str, args) -> None:
    """Called for every shortcut kitty runs."""
    if _clicking["on"]:
        return                          # a sidebar button, not the key: no badge
    qid = ACTION_QUEST.get(func)
    text = " ".join(str(a) for a in (args or ()))
    if func == "launch":
        finder = re.search(r"tab-finder\.py\"?\s+(search|waiting)\b", text)
        qid = ("split" if "split" in text else "help" if "shortcuts.sh" in text
               else "mute" if "sounds-off" in text else finder.group(1) if finder else None)
    elif func == "kitten":
        qid = "hints" if "hints" in text else "unicode" if "unicode_input" in text else None
    if qid:
        _quest_done(qid)


GOLD, FG = "\x1b[33m", "\x1b[39m"   # palette gold (theme-aware) for the ★ and the sparkle only


_quest_day = {"day": None}
COACH_SECONDS, COACH_EVERY = 6.0, 90.0
_coach = {"text": "", "until": 0.0, "last": -999.0}


def _tab_clicked(tm, x, y, button, action) -> None:
    """You clicked a tab with the mouse: until you've earned the Jumper badge, the line under
    "+ New tab" says which key does the same (at most every COACH_EVERY seconds, so it never nags)."""
    try:
        from kitty.fast_data_types import GLFW_MOUSE_BUTTON_LEFT, GLFW_PRESS
        if button != GLFW_MOUSE_BUTTON_LEFT or action != GLFW_PRESS or "jump" in _earned:
            return
        if os.path.exists(QUESTS_OFF):
            return
        now = time.monotonic()
        if now - _coach["last"] < COACH_EVERY:
            return
        tab_id = tm.tab_bar.tab_id_at(x, y)
        ids = [t.id for t in tm.tabs_to_be_shown_in_tab_bar]
        if tab_id <= 0 or tab_id not in ids or ids.index(tab_id) >= 9:
            return
        n = ids.index(tab_id) + 1
        if tm.active_tab is not None and tm.active_tab.id == tab_id:
            return                                  # already there: nothing to teach
        _coach.update(text=f"Alt+{n} also gets here", until=now + COACH_SECONDS, last=now)
    except Exception:
        pass


def _shortest_fit(texts, room: int) -> str:
    """The first of `texts` (longest first) that fits `room` cells, or "": a shorter wording instead
    of a word cut in half."""
    return next((t for t in texts if t and _cells(t) <= room), "")


def _hint_forms(hint: str) -> tuple:
    """A quest's sidebar hint, "Ctrl+Alt+←  go to pane", and its shorter forms: the key with a
    one-space gap, then the key alone (the key is what the quest teaches)."""
    key, _, verb = hint.partition("  ")
    return (hint, f"{key} {verb}" if verb else "", key)


def _quest_line(width=None) -> str:
    """The line under "+ New tab": the badge just earned (sparkling), else the next quest. It fits
    `width` cells (the mark and its gap are 6) by taking a shorter wording, never by cutting one;
    with no room for any, the mark alone."""
    if os.path.exists(QUESTS_OFF):
        return ""
    room = (width or ROW_WIDTH) - 6
    now = time.monotonic()
    n = len(_earned)
    mark, words = f"{'★' + str(n):>3}", ()
    if _badge_shown["until"] > now and _badge_shown["id"] in QUEST_BY_ID:
        mark = f"{TWINKLE[_frame % len(TWINKLE)]:>3}"
        badge = QUEST_BY_ID[_badge_shown["id"]][1]
        if _badge_shown.get("rank"):
            words = (f"new rank: {_rank(n)[0]}!", f"{_rank(n)[0]}!")
        elif _badge_shown.get("mastered"):
            words = (f"mastered: {badge}!", f"mastered {badge}", f"{badge}!", "mastered!")
        else:
            words = (f"badge: {badge}!", f"{badge}!", "badge!")
    elif _coach["until"] > now:
        mark = f"{'→':>3}"
        words = (_coach["text"], _coach["text"].replace(" also", ""), _coach["text"].split(" ")[0])
    else:
        q = _next_quest()
        words = _hint_forms(q[2]) if q else (f"all done: {RANKS[-1][1]}!", "all done!")
    text = _shortest_fit(words, room)
    return f"{GOLD}{mark}{FG}" + (f"   {text}" if text else "")


def _quest_hit(qid: str) -> None:
    """For patches installed by an earlier load: always reach the current load's quest code."""
    try:
        import kitty.tab_bar as kt
        fn = getattr(kt, "_vye_quest_done", None)
        if fn:
            fn(qid)
    except Exception:
        pass


def _hook(name: str) -> None:
    """Patches stay installed across a config reload, so they reach the current load's code here."""
    try:
        import kitty.tab_bar as kt
        fn = getattr(kt, "_vye_hooks", {}).get(name)
        if fn:
            fn()
    except Exception:
        pass


def _patch_quest_actions() -> None:
    try:
        import kitty.boss as kb
    except Exception:
        return
    Boss = getattr(kb, "Boss", None)                  # renamed by a kitty update: no quests, no crash
    orig = getattr(Boss, "dispatch_action", None)
    if Boss is None or orig is None or getattr(orig, "_vye_patched", False):
        return

    def dispatch_action(self, key_action, *a, **k):
        try:
            import kitty.tab_bar as kt
            fn = getattr(kt, "_vye_quest_action", None)
            if fn and key_action is not None:
                fn(key_action.func, key_action.args)
        except Exception:
            pass
        return orig(self, key_action, *a, **k)
    dispatch_action._vye_patched = True
    Boss.dispatch_action = dispatch_action


# ---- Nine, the drawn cat that lives in the sidebar ----------------------------------------------------
# A silver tabby (config/cat/, drawn by scripts/make-cat.py) sits on the sidebar's floor under the
# tabs: it blinks and fidgets, now and then walks a few steps, goes up to the tab that needs you and
# points at it, hops when one finishes, sleeps at night (and after 3 quiet minutes) and can be
# dragged about. A click on it opens its speech bubble (what needs you, today's quest, a tip, a joke,
# a word: cat-helper.py's suggestions) with Go there ↵ / Next tip › and a × to close it. It speaks up
# by itself too, briefly and rarely: a tab needs you, a tab finished, a badge, now and then a tip
# (kitty-cat talk on | events | off), with a soft meow (kitty-cat sounds off), never while you
# type, never the same thing twice in a row (nine.py's Memory). The bubble floats with the cat,
# its tail pointing at it; the words come out at a steady pace while its mouth moves.
#
# How: kitty draws the sidebar from a Screen of its own (TabBar.screen) with the same code as a
# terminal window, pictures included. Its pictures go in as kitty graphics-protocol commands, fed to
# that Screen's parser (Screen.restore_scrollback) from inside kitty:
#   - kitty makes the sidebar's Screen with no window id, and a picture is sent to the GPU only for a
#     Screen that has one (graphics.c), so the cat's sidebar gets a new Screen tied to one of its
#     kitty window's windows (_cat_adopt), and gets it again before sending pictures if that window
#     closed. With a window id a graphics reply would be typed into that window's program: every
#     command is quiet (q=2), and _cat_feed lets nothing but our own graphics commands through (a BEL
#     there would make kitty ask the desktop for attention, which NineLives never does).
#   - every sidebar redraw erases the screen, which takes pictures off and frees the ones nothing
#     shows: each picture also has a placement that is never drawn (U=1), and the cat and its bubble
#     are put back at the end of every redraw (_cat_settle, from _fit_vertical).
#   - it moves a pixel at a time (a cell plus a pixel offset); a 15-a-second timer runs only while it
#     walks, a 30-a-second one only while it talks; neither redraws the sidebar's text.
#   - pictures can't leave the sidebar (kitty clips them at its edge): the cat and its bubble stay in it.
# The bubble is a picture (nine.py's Bubble, its words drawn with kitty's own text renderer); the
# words are a picture of their own, shown a little more at a time by cropping it. Where kitty can't
# draw text that way, the bubble is drawn in the sidebar's cells instead (_bubble_draw_cells).
# Where: on the floor (the bottom rows) while the tabs leave room for it; when they fill the sidebar,
# small at the end of "+ New tab"; with no room even for that, or on a kitty without what it needs,
# the cat face at the end of "+ New tab" (_cat_face) as before.
CAT_TALK = os.path.join(CONFIG_DIR, "cat-talk")               # "events" or "off"; missing: on
CAT_SOUNDS_OFF = os.path.join(CONFIG_DIR, "cat-sounds-off")
SPRITE_BASE = 4200           # image ids in the sidebar's own graphics manager (nothing else draws there)
BUB_BODY, BUB_TEXT, BUB_TAIL_DOWN, BUB_TAIL_UP = SPRITE_BASE + 100, SPRITE_BASE + 101, SPRITE_BASE + 102, SPRITE_BASE + 103
KEEP_P, BODY_P, MOUTH_P = 1, 7, 8
BUB_P, LINES_P, PART_P, TAIL_P = 20, 21, 22, 23
FLOOR_ROWS, SMALL_ROWS = 4, 2
PAD_ID = -20                 # made-up sidebar entries that keep the floor free (_lay_out)
DRAWN = ("floor", "small")
WALK_FPS, TALK_FPS = 15.0, 30.0
WALK_SPEED, CLIMB_SPEED = 45.0, 180.0       # px a second
CHARS_PER_SECOND = 50.0
WANDER_EVERY = (40.0, 110.0)                # seconds between little walks
VISIT_SECONDS = 20.0
PERCH_SECONDS = 30.0         # dropped somewhere up the sidebar: it sits there this long
SAY_HOLD = 7.0               # a line it said by itself stays this long after its last word
ASK_HOLD = 90.0              # a bubble you opened: until × or this long
UNPROMPTED_GAP = 180.0       # at most one line by itself every 3 minutes
TIP_EVERY = (1500.0, 2700.0)                # and a tip every 25 to 45 minutes (kitty-cat talk on)
TYPING_QUIET = 4.0           # not while the window you're in changed this recently
CAT_DRAG_ID = 2 ** 31 - 11   # what kitty is told is being dragged while you carry the cat (no tab has it)
NEXT_WORDS = {"waiting": "tab", "error": "tab", "done": "tab", "hello": "hello", "badge": "badge",
              "quest": "quest", "tip": "tip", "joke": "joke", "word": "word"}
_cat_modes: dict = {}        # os window id -> where its cat is (floor, small, text, off)
_cat_drag: dict = {}         # os window id -> a press on the cat that may become a drag
_cat_talk = {"last": -1e9, "tip_at": None, "typing": {}, "memory": None}
_mods = {}


def _load(name: str, file: str):
    """A file next to this one (cat-helper.py, nine.py), loaded once, or None."""
    if name not in _mods:
        try:
            import importlib.util
            here = os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join(CONFIG_DIR, "tab_bar.py")))
            spec = importlib.util.spec_from_file_location(name, os.path.join(here, file))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _mods[name] = mod
        except Exception:
            _mods[name] = None
    return _mods[name]


def _ch():
    """cat-helper.py: the suggestions, the cell bubble, the frame lists."""
    return _load("ninelives_cat_helper", "cat-helper.py")


def _nine():
    """nine.py: the cat's moves, walking, talking, its bubble picture and its memory."""
    return _load("ninelives_nine", "nine.py")


def _memory():
    if _cat_talk["memory"] is None:
        _cat_talk["memory"] = _nine().Memory(os.path.join(QUEST_DIR, "cat-said"))
    return _cat_talk["memory"]


def _cat_dir() -> str:
    here = os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join(CONFIG_DIR, "tab_bar.py")))
    return os.path.join(here, "cat")


def _talk_setting() -> str:
    """on, events (only news about your tabs) or off: kitty-cat talk, the settings list."""
    try:
        with open(CAT_TALK, encoding="utf-8") as f:
            v = f.read().strip()
        return v if v in ("events", "off") else "on"
    except OSError:
        return "on"


def _moves(name: str) -> list:
    return [list(x) for x in _nine().MOVES[name]]


# -- the graphics commands --------------------------------------------------------------------------
_APC_RE = re.compile(b"\x1b_G([A-Za-z0-9=,-]*)(?:;([A-Za-z0-9+/=]*))?\x1b\\\\")


def _gfx(control: str, data: bytes = b"") -> bytes:
    """One graphics command, quiet (q=2: kitty answers nothing); data goes base64 in chunks of 4096,
    the first with the keys, the rest with m= only."""
    control += ",q=2"
    if not data:
        return b"\x1b_G" + control.encode("ascii") + b"\x1b\\"
    import base64
    b64 = base64.standard_b64encode(data)
    parts = [b64[i:i + 4096] for i in range(0, len(b64), 4096)]
    out = []
    for i, p in enumerate(parts):
        head = (control + "," if i == 0 else "") + f"m={1 if i < len(parts) - 1 else 0}"
        out.append(b"\x1b_G" + head.encode("ascii") + b";" + p + b"\x1b\\")
    return b"".join(out)


def _gfx_only(data: bytes) -> bool:
    """True when data is nothing but whole graphics commands, each quiet (q=2), a chunked one's
    later chunks carrying m= alone: nothing else may reach the sidebar's parser."""
    pos, more = 0, False
    while pos < len(data):
        m = _APC_RE.match(data, pos)
        if m is None:
            return False
        items = m.group(1).split(b",") if m.group(1) else []
        if any(b"=" not in kv for kv in items):
            return False
        keys = dict(kv.split(b"=", 1) for kv in items)
        if more:
            if set(keys) != {b"m"}:
                return False
        elif keys.get(b"q") != b"2":
            return False
        more = keys.get(b"m") == b"1"
        pos = m.end()
    return pos > 0 and not more


def _cat_feed(screen, data: bytes) -> None:
    if not _gfx_only(data):
        raise ValueError("only quiet graphics commands go to the sidebar")
    screen.restore_scrollback(data)


def _at(screen, x: float, y: float, cw: int, ch: int, cmd: bytes) -> None:
    """Feed a placement command with the sidebar's cursor at pixel (x, y): its cell, and the rest
    of the way as the command's X= Y= (put in here)."""
    col, xo = divmod(max(0, int(round(x))), cw)
    row, yo = divmod(max(0, int(round(y))), ch)
    col, row = min(col, max(0, screen.columns - 1)), min(row, max(0, screen.lines - 1))
    cx, cy = screen.cursor.x, screen.cursor.y
    try:
        screen.cursor.x, screen.cursor.y = col, row
        _cat_feed(screen, cmd.replace(b"X=?,Y=?", f"X={xo},Y={yo}".encode()))
    finally:
        screen.cursor.x, screen.cursor.y = cx, cy


_png_cache: dict = {}


def _cat_png(size: int, name: str):
    key = (size, name)
    if key not in _png_cache:
        try:
            with open(os.path.join(_cat_dir(), str(size), name + ".png"), "rb") as f:
                _png_cache[key] = f.read()
        except OSError:
            _png_cache[key] = None
    return _png_cache[key]


def _cat_iid(name: str) -> int:
    ch = _ch()
    if name.startswith("mouth-"):
        return SPRITE_BASE + 80 + ch.MOUTHS.index(name[6:])
    return SPRITE_BASE + ch.FRAMES.index(name)


# -- sizes and places ------------------------------------------------------------------------------
def _cat_rows(cell_h: int, want: int = FLOOR_ROWS) -> int:
    """How many rows tall: `want`, fewer when that is taller than the biggest frames (never scaled up)."""
    return max(1, min(want, 384 // max(1, cell_h)))


def _cat_size(px: int) -> int:
    """The frames to show for a cat px tall: the smallest at least that big (kitty scales it down)."""
    return next((s for s in (96, 192, 384) if s >= px), 384)


def _cell(bar) -> tuple:
    s = bar.screen
    cw = int(getattr(bar, "cell_width", 0) or 10)
    ch = getattr(bar, "cell_height", None)
    if not ch:
        g = bar.window_geometry
        ch = max(1, (g.bottom - g.top) // max(1, s.lines))
    return cw, int(ch)


def _cat_state(bar) -> dict:
    """The cat of one sidebar, kept on its TabBar: per kitty window, kept over a config reload."""
    st = getattr(bar, "_vye_cat", None)
    if not isinstance(st, dict):
        st = {}
        try:
            bar._vye_cat = st
        except Exception:
            pass
    now = time.monotonic()
    for k, v in (("mode", None), ("pad", 0), ("x", None), ("y", None), ("path", []), ("facing", 1),
                 ("phase", 0.0), ("queue", []), ("shown", None), ("loaded", None), ("spot", "floor"),
                 ("visit", None), ("until", 0.0), ("next_wander", now + 20.0), ("seen", None),
                 ("bubble", None), ("geom", None), ("roll", 0), ("failed", False), ("errors", 0),
                 ("noted", None), ("frozen", False), ("home_x", None), ("carried", False)):
        st.setdefault(k, v)
    return st


_internals = {"ok": None}


def _cat_possible() -> bool:
    """kitty has what the drawn cat needs (a Screen to make, a parser to feed), and its pictures,
    cat-helper.py and nine.py are there. Else the text cat."""
    if _internals["ok"] is None:
        ok = False
        try:
            from kitty.fast_data_types import Screen
            ch, nine = _ch(), _nine()
            ok = (ch is not None and nine is not None and hasattr(Screen, "restore_scrollback") and all(
                hasattr(ch, n) for n in ("FRAMES", "MOUTHS", "MOUTH", "bubble", "suggestions", "Helper"))
                and _cat_png(96, "idle") is not None)
        except Exception:
            ok = False
        _internals["ok"] = ok
    return _internals["ok"]


def _cat_choose(bar, st, hidden: int) -> tuple:
    """(where the cat goes, how many rows to keep free for it) from the sidebar just laid out:
    "floor" when the tabs leave it FLOOR_ROWS rows at the bottom (kitty's blank lines between the
    tabs go first if that's what it takes: then the second number says how many rows to keep),
    "small" at the end of "+ New tab", "text" (the cat face) or "off"."""
    if os.path.exists(CAT_OFF):
        return "off", 0
    if st.get("failed") or not _cat_possible():
        return "text", 0
    s = bar.screen
    lines, cols = s.lines, s.columns
    cw, ch = _cell(bar)
    real = sorted((e for e in bar.tab_extents if e.tab_id > PAD_ID), key=lambda e: e.y.start)
    rows = _cat_rows(ch)
    if (not hidden and real and rows * ch * 1.5 <= cols * cw and rows >= 2
            and getattr(bar, "tab_bar_align", "start") == "start" and real[0].y.start == 0):
        h = sum(e.y.end - e.y.start + 1 for e in real)
        if h + len(real) - 1 + rows <= lines:
            return "floor", 0
        if h + rows <= lines:
            return "floor", rows
    new = next((e for e in real if e.tab_id == -1), None)
    small = _cat_rows(ch, SMALL_ROWS)
    if new is not None and new.y.end - new.y.start + 1 >= small and small >= 2 and cols >= 18:
        return "small", 0
    return "text", 0


def _pad_entries(bar, data, rows: int) -> tuple:
    """Blank made-up entries `rows` lines tall in all, put after "+ New tab": kitty can't fit them
    with its blank lines between tabs, so it drops those and the floor stays free."""
    most = max(1, int(getattr(bar, "max_tab_title_lines", 1) or 1))
    out, left, i = [], rows, 0
    last = data[-1]
    while left > 0:
        h = min(most, left)
        out.append(last._replace(title=" " + "\n " * (h - 1), tab_id=PAD_ID - 1 - i, is_active=False))
        left -= h
        i += 1
    return tuple(out)


def _unpad(bar) -> None:
    """Take the made-up entries out again: no tab there, and the sidebar's own colour."""
    import kitty.tab_bar as kt
    pads = [e for e in bar.tab_extents if e.tab_id <= PAD_ID]
    if not pads:
        return
    bar.tab_extents = tuple(e for e in bar.tab_extents if e.tab_id > PAD_ID)
    s = bar.screen
    for e in pads:
        for row in range(e.y.start, e.y.end + 1):
            s.cursor.x, s.cursor.y = 0, row
            try:
                s.cursor.reset_display_attrs()
            except Exception:
                pass
            s.cursor.bg = kt.as_rgb(kt.color_as_int(bar.draw_data.default_bg))
            s.erase_in_line(2, False)


def _label_kind(mode) -> str:
    return {"floor": "none", "off": "none", "small": "small"}.get(mode, "text")


# -- after each sidebar redraw ------------------------------------------------------------------------
def _cat_settle(bar, st) -> None:
    """The sidebar was just drawn: where the cat is now (the floor may have moved), its pictures put
    back (the redraw took them off), its bubble too. (Runs inside kitty's redraw: nothing slow, no
    files; a bubble that no longer fits how the cat is drawn is made again by _bubble_refit.)"""
    mode = st["mode"]
    wid = getattr(bar, "os_window_id", 0)
    _cat_modes[wid] = mode
    st["shown"] = None                               # (the redraw erased them)
    b = st.get("bubble")
    if b is not None:
        b["placed"] = None
    s = bar.screen
    cw, ch = _cell(bar)
    lines, cols = s.lines, s.columns
    width = cols * cw
    if mode == "floor":
        rows = _cat_rows(ch)
        size = rows * ch
        floor_y = (lines - rows) * ch
        st["geom"] = {"rows": rows, "px": size, "size": _cat_size(size), "floor_y": floor_y, "width": width,
                      "height": lines * ch, "cw": cw, "ch": ch, "lines": lines, "cols": cols}
        if st["x"] is None or st["spot"] == "small":
            st["x"], st["y"], st["spot"] = width * 0.06, floor_y, "floor"
        if st["home_x"] is None:
            st["home_x"] = st["x"]
        st["x"] = min(max(0.0, st["x"]), max(0.0, width - size))
        st["y"] = min(max(0.0, st["y"]), floor_y)
        if st["spot"] == "floor" and not st["path"]:
            st["y"] = floor_y
        if st["spot"] == "visit":
            spot = _visit_spot(bar, st, st.get("visit"))
            if spot is None:
                _cat_go_home(st)
            elif not st["path"]:
                st["x"], st["y"] = spot
            else:
                st["path"][-1] = spot
    elif mode == "small":
        rows = _cat_rows(ch, SMALL_ROWS)
        size = rows * ch
        new = next((e for e in bar.tab_extents if e.tab_id == -1), None)
        ncols = -(-size // cw)
        st["geom"] = {"rows": rows, "px": size, "size": _cat_size(size), "floor_y": 0, "width": width,
                      "height": lines * ch, "cw": cw, "ch": ch, "lines": lines, "cols": cols}
        st["path"], st["spot"] = [], "small"
        st["x"] = float(max(0, cols - 1 - ncols) * cw)
        st["y"] = float((new.y.start if new is not None else 0) * ch)
    else:
        st["geom"] = None
        if mode == "off":
            st["bubble"] = None
    b = st.get("bubble")
    if b is not None and not b.get("image"):
        try:
            _bubble_draw_cells(bar, st)
        except Exception:
            st["bubble"] = None
    if mode in DRAWN:
        _cat_place(bar, st, force=True)
    # (cat.txt is written from the cat's timer, _cat_tick_one: no file I/O in kitty's redraw)


def _visit_spot(bar, st, tab_id):
    """Where the cat sits to point at a tab: at the sidebar's right edge, all of it inside, its paw
    at the tab's first line. None if that tab isn't shown."""
    g = st.get("geom")
    e = next((e for e in bar.tab_extents if e.tab_id == tab_id), None) if tab_id else None
    if g is None or e is None:
        return None
    x = max(0.0, g["width"] - g["px"])
    y = min(max(0.0, e.y.start * g["ch"] + g["ch"] * 0.5 - g["px"] * 0.58), g["floor_y"])
    return (x, y)


def _cat_go_home(st) -> None:
    g = st.get("geom")
    st["visit"] = None
    st["spot"] = "floor"
    if g is None:
        return
    hx = st.get("home_x")
    if hx is None:
        hx = g["width"] * 0.06
    _cat_walk(st, (hx, g["floor_y"]))


def _cat_walk(st, target) -> None:
    g = st["geom"]
    st["path"] = _nine().route((st["x"], st["y"]), target, g["floor_y"])
    _timer_on("walk")


# -- what it shows ---------------------------------------------------------------------------------
def _cat_frame(st, now: float) -> str:
    b = st.get("bubble")
    pointing = b is not None and _bubble_item(b).get("action") == ("focus", st.get("visit"))
    asleep = b is None and _cat_base(now)[0] == "asleep"
    return _nine().pick_frame(st["path"][0] if st["path"] else None, (st["x"], st["y"]), st["phase"],
                              st["facing"], st["queue"], st["spot"], pointing, asleep, st.get("carried"))


def _cat_lips(st, frame: str, now: float) -> str:
    """The mouth over a sitting pose: the pose's own, or while it talks, the letter it says."""
    ch = _ch()
    if frame not in ch.MOUTH:
        return ""
    b = st.get("bubble")
    r = b.get("reveal") if b is not None else None
    if r is not None and not r.done(now):
        return "mouth-" + r.mouth(now)
    return "mouth-" + ch.MOUTH[frame]


def _cat_place(bar, st, force: bool = False) -> bool:
    """Put the cat's frame (and its mouth) where it is, and its bubble with it; the old ones off, in
    the same write. False when nothing was sent (not ready, or nothing changed)."""
    g = st.get("geom")
    s = bar.screen
    if g is None or st["loaded"] != (id(s), g["size"]):
        return False
    now = time.monotonic()
    frame = _cat_frame(st, now)
    if _cat_png(g["size"], frame) is None:
        frame = "idle"
    lips = _cat_lips(st, frame, now)
    cw, ch = g["cw"], g["ch"]
    want = (id(s), frame, lips, int(round(st["x"])), int(round(st["y"])), g["rows"])
    sent = False
    if want != st["shown"] or force:
        old = st["shown"]
        cmds = [_gfx(f"a=p,i={_cat_iid(frame)},p={BODY_P},r={g['rows']},X=?,Y=?,z=1,C=1")]
        if lips:
            cmds.append(_gfx(f"a=p,i={_cat_iid(lips)},p={MOUTH_P},r={g['rows']},X=?,Y=?,z=2,C=1"))
        if old is not None and old[0] == id(s):
            if old[1] != frame:
                cmds.append(_gfx(f"a=d,d=i,i={_cat_iid(old[1])},p={BODY_P}"))
            if old[2] and old[2] != lips:
                cmds.append(_gfx(f"a=d,d=i,i={_cat_iid(old[2])},p={MOUTH_P}"))
        _at(s, st["x"], st["y"], cw, ch, b"".join(cmds[:2]))
        if len(cmds) > 2:
            _cat_feed(s, b"".join(cmds[2:]))
        st["shown"] = want
        sent = True
    if _bubble_place(bar, st, force):
        sent = True
    return sent


def _cat_unplace(bar, st) -> None:
    old = st.get("shown")
    st["shown"] = None
    if old is None or old[0] != id(bar.screen):
        return
    cmds = [_gfx(f"a=d,d=i,i={_cat_iid(old[1])},p={BODY_P}")]
    if old[2]:
        cmds.append(_gfx(f"a=d,d=i,i={_cat_iid(old[2])},p={MOUTH_P}"))
    _cat_feed(bar.screen, b"".join(cmds))
    _bubble_unplace(bar, st)


def _wake() -> None:
    try:
        from kitty.fast_data_types import wakeup_main_loop
        wakeup_main_loop()
    except Exception:
        pass


# -- getting the pictures in -----------------------------------------------------------------------
def _cat_adopt(tm, bar) -> bool:
    """Give the sidebar a Screen tied to a live window of its kitty window (see above), unless the
    one it has is still tied to one. kitty then lays it out and redraws it."""
    boss = get_boss()
    wid = getattr(bar, "_vye_cat_wid", 0)
    w = boss.window_id_map.get(wid) if wid else None
    if (w is not None and getattr(bar, "_vye_cat_screen", None) is bar.screen
            and getattr(w, "os_window_id", None) == getattr(bar, "os_window_id", None)):
        return True
    w = getattr(tm, "active_window", None) or next((x for t in tm for x in t), None)
    if w is None:
        return False
    from kitty.fast_data_types import Screen
    old = bar.screen
    cw, ch = _cell(bar)
    new = Screen(None, old.lines, old.columns, 0, cw, ch, w.id)
    new.color_profile.default_fg = old.color_profile.default_fg
    new.color_profile.default_bg = old.color_profile.default_bg
    bar.screen = new
    bar._vye_cat_wid, bar._vye_cat_screen = w.id, new
    bar.layout()                                      # sizes it and hands it to kitty's renderer
    tm.mark_tab_bar_dirty()
    return True


def _cat_ready(tm, bar, st) -> bool:
    """The frames are in this sidebar's Screen at the size it needs (sent now if not)."""
    g = st.get("geom")
    if g is None:
        return False
    s = bar.screen
    if st["loaded"] == (id(s), g["size"]) and s.grman.image_for_client_id(SPRITE_BASE) is not None:
        return True
    if not _cat_adopt(tm, bar):
        return False
    s = bar.screen
    ch = _ch()
    out = []
    for name in ch.FRAMES + tuple(f"mouth-{m}" for m in ch.MOUTHS):
        data = _cat_png(g["size"], name)
        if data is None:
            continue
        iid = _cat_iid(name)
        out.append(_gfx(f"a=t,f=100,i={iid}", data))
        out.append(_gfx(f"a=p,U=1,i={iid},p={KEEP_P},c=1,r=1"))   # keeps it while nothing shows it
    _cat_feed(s, b"".join(out))
    if s.grman.image_for_client_id(SPRITE_BASE) is None:
        st["failed"] = True                           # kitty took none of it: the text cat
        tm.mark_tab_bar_dirty()
        return False
    st["loaded"], st["shown"] = (id(s), g["size"]), None
    b = st.get("bubble")
    if b is not None and b.get("image"):
        b["sent"] = None                              # (its pictures again, for this Screen: _bubble_refit)
    tm.mark_tab_bar_dirty()                           # drawn again, with the cat on it
    return True


# -- the clocks ------------------------------------------------------------------------------------
def _timer_on(which: str) -> None:
    """The walking timer (15 a second) or the talking one (30): only while a cat walks or talks."""
    import kitty.tab_bar as kt
    attr = f"_vye_cat_{which}_timer"
    if getattr(kt, attr, None) is None:
        fn, fps = (_cat_walk_tick, WALK_FPS) if which == "walk" else (_cat_talk_tick, TALK_FPS)
        setattr(kt, attr, add_timer(fn, 1.0 / fps, True))
        fn.last = time.monotonic()


def _timer_off(which: str) -> None:
    import kitty.tab_bar as kt
    attr = f"_vye_cat_{which}_timer"
    t = getattr(kt, attr, None)
    setattr(kt, attr, None)
    if t is not None:
        try:
            remove_timer(t)
        except Exception:
            pass


def _cat_bars():
    try:
        for tm in get_boss().all_tab_managers:
            bar = getattr(tm, "tab_bar", None)
            if bar is not None and getattr(bar, "laid_out_once", False) and isinstance(getattr(bar, "_vye_cat", None), dict):
                yield tm, bar, bar._vye_cat
    except Exception:
        return


def _cat_walk_tick(timer_id=None) -> None:
    """15 times a second, only while a cat walks: a step, the walk cycle's next frame."""
    now = time.monotonic()
    dt = min(0.2, now - getattr(_cat_walk_tick, "last", now))
    _cat_walk_tick.last = now
    moving = False
    for tm, bar, st in list(_cat_bars()):
        if not st["path"] or st.get("mode") != "floor":
            continue
        moving = True
        try:
            tx, ty = st["path"][0]
            vertical = abs(ty - st["y"]) > abs(tx - st["x"])
            if abs(tx - st["x"]) > 1:
                st["facing"] = 1 if tx > st["x"] else -1
            speed = CLIMB_SPEED if vertical else WALK_SPEED * (2.5 if st["spot"] == "visit" else 1.0)
            st["x"], st["y"], arrived = _nine().step((st["x"], st["y"]), (tx, ty), dt, speed)
            st["phase"] += dt * (6.0 if vertical else 8.0 * (1.6 if st["spot"] == "visit" else 1.0))
            if arrived:
                st["path"].pop(0)
                if not st["path"]:
                    _cat_note(bar, st)
                    if st["spot"] == "floor":
                        st["home_x"] = st["x"]
            if _cat_place(bar, st):
                _wake()
        except Exception:
            st["path"] = []
    if not moving:
        _timer_off("walk")


def _cat_talk_tick(timer_id=None) -> None:
    """30 times a second, only while a cat talks: a few more letters of its line, its mouth in step."""
    now = time.monotonic()
    log = _cat_talk_tick.__dict__.setdefault("log", [])
    log.append(now)                                   # (cat_ctl timing: how steady this clock is)
    del log[:-400]
    talking = False
    for tm, bar, st in list(_cat_bars()):
        b = st.get("bubble")
        if b is None or b.get("reveal") is None:
            continue
        try:
            if not b["reveal"].done(now):
                talking = True
            elif not b.get("said_all"):
                b["said_all"] = True
                b["close_at"] = max(b["close_at"], now + (ASK_HOLD if b["prompted"] else SAY_HOLD))
                _cat_note(bar, st)
            if _cat_place(bar, st):
                _wake()
        except Exception:
            b["reveal"] = None
    if not talking:
        _timer_off("talk")


def _cat_tick(now: float) -> None:
    """From the sidebar's timer (8 times a second): each kitty window's cat."""
    _typing_sample(now)
    for tm, bar, st in list(_cat_bars()):
        try:
            _cat_tick_one(tm, bar, st, now)
            st["errors"] = 0
        except Exception:
            st["errors"] += 1
            if st["errors"] > 40:                     # something keeps failing: the text cat instead
                st["failed"] = True
                tm.mark_tab_bar_dirty()


def _cat_seen() -> tuple:
    """What the cats react to: how many waits began (a count of new waits, not of the tabs waiting
    now: one tab can start waiting in the same tick another stops), the last finish, error, badge."""
    return (_cat["waits"], _cat["done_at"], _cat["error_at"], _badge_shown.get("until", 0.0))


def _cat_tick_one(tm, bar, st, now: float) -> None:
    mode = st.get("mode")
    off = os.path.exists(CAT_OFF)
    if off or mode == "off":
        if st.get("shown"):
            _cat_unplace(bar, st)
            _wake()
        if off != (mode == "off"):                   # kitty-cat off / on: lay the sidebar out again
            tm.mark_tab_bar_dirty()
        _cat_note(bar, st)
        return
    seen, before = _cat_seen(), st["seen"]
    st["seen"] = seen
    if mode in DRAWN and not _cat_ready(tm, bar, st):
        return
    _bubble_refit(tm, bar, st, now)
    asleep = _cat_base(now)[0] == "asleep"
    events = []
    if before is not None:
        if seen[0] > before[0]:                       # (a count of new waits: only goes up)
            events.append("waiting")
        if seen[1] != before[1]:
            events.append("done")
        if seen[2] != before[2]:
            events.append("error")
        if seen[3] > before[3]:
            events.append("badge")
    for ev in events:                                 # its moves first
        st["queue"] = _moves({"waiting": "surprise", "done": "hop", "error": "flinch", "badge": "cheer"}[ev])
    if events:
        _cat_speak_up(tm, bar, st, events, now)
    else:
        _cat_tip_time(tm, bar, st, now)
    _bubble_tick(tm, bar, st, now)
    if st["queue"]:
        st["queue"][0][1] -= 1
        if st["queue"][0][1] <= 0:
            st["queue"].pop(0)
    if mode == "floor" and not st["path"] and not st.get("carried"):
        _cat_wander(tm, bar, st, now, asleep)
    if mode in DRAWN and _cat_place(bar, st):
        _wake()
    if not st["path"]:
        _cat_note(bar, st)


def _cat_wander(tm, bar, st, now: float, asleep: bool) -> None:
    """The dice (once a second) and the cat's own little trips: a few steps along the floor, back
    home from a visit or a perch."""
    nine = _nine()
    b = st.get("bubble")
    if st["spot"] == "visit":
        if (now > st["until"] and b is None) or (b is None and not _visit_wanted(st.get("visit"))):
            _cat_go_home(st)
        return
    if st["spot"] == "perch" and now > st["until"] and b is None:
        _cat_go_home(st)
        return
    if _frame < st["roll"] or st["queue"] or asleep or st.get("frozen"):
        return
    st["roll"] = _frame + CAT_ROLL
    rng = _cat_rng
    r = rng.random()
    if r < nine.BLINK:
        st["queue"] = _moves("blink")
    elif r < nine.BLINK + nine.FIDGET:
        name = rng.choice(nine.FIDGETS)
        if name == "walk":
            if b is None and st["spot"] == "floor":
                _cat_little_walk(st, rng)
        else:
            st["queue"] = _moves(name)
    elif now > st["next_wander"] and b is None and st["spot"] == "floor":
        st["next_wander"] = now + rng.uniform(*WANDER_EVERY)
        _cat_little_walk(st, rng)


def _cat_little_walk(st, rng) -> None:
    """A few steps left or right along the floor (it stays inside the sidebar)."""
    g = st["geom"]
    lo, hi = 0.0, max(0.0, g["width"] - g["px"])
    step = rng.uniform(20.0, 90.0) * (1 if rng.random() < 0.5 else -1)
    x = st["x"] + step
    if not lo <= x <= hi:
        x = st["x"] - step
    x = min(max(lo, x), hi)
    st["home_x"] = x
    _cat_walk(st, (x, g["floor_y"]))


def _visit_wanted(tab_id) -> bool:
    """Still worth sitting by: the tab waits for you, failed or finished, and isn't the one you're on."""
    if not tab_id:
        return False
    tab = _tab_obj(tab_id)
    if tab is None or _is_active(tab_id):
        return False
    return any(_prev_state.get(w.id) in ("blocked", "error", "done") for w in tab)


def _cat_visit(tm, bar, st, tab_id) -> bool:
    """Walk up to a tab and sit by it (it points while it talks about it)."""
    if st.get("mode") != "floor" or st.get("carried"):
        return False
    spot = _visit_spot(bar, st, tab_id)
    if spot is None:
        return False
    st["visit"], st["spot"], st["until"] = tab_id, "visit", time.monotonic() + VISIT_SECONDS
    _cat_walk(st, spot)
    return True


# -- talking ---------------------------------------------------------------------------------------
def _tab_rows(focused_wid=None) -> list:
    """The tabs as cat-helper.py's suggestions want them (as tab-finder.py makes them from
    kitty @ ls), from kitty itself: number, id, the name the sidebar shows, state, active."""
    out = []
    boss = get_boss()
    for tm in boss.all_tab_managers:
        tabs = list(getattr(tm, "tabs_to_be_shown_in_tab_bar", None) or tm)
        for i, tab in enumerate(tabs):
            states = {_prev_state.get(w.id) for w in tab}
            state = next((x for x in ("blocked", "error", "working", "done") if x in states), "")
            if not state and tab.id in _running:
                state = "working"
            try:
                w = _base_window(tab)
                wd = (w.get_cwd_of_child() if w is not None else "") or ""
            except Exception:
                wd = ""
            try:
                title = _row_title({"title": getattr(tab, "name", "") or getattr(tab, "title", "") or "", "tab_id": tab.id})
                name = _tab_name(title, wd, tab.id)
            except Exception:
                name = ""
            name = "".join(c for c in name if c.isprintable())[:60] or f"tab {i + 1}"
            out.append({"n": i + 1, "id": tab.id, "name": name, "state": state,
                        "active": tm.active_tab is tab and (focused_wid is None or tm.os_window_id == focused_wid)})
    return out


def _bubble_item(b) -> dict:
    return b["items"][b["sel"]] if b and b.get("items") else {}


def _suggest(focused_wid) -> list:
    ch = _ch()
    import datetime
    return ch.suggestions(_tab_rows(focused_wid), datetime.datetime.now(), QUEST_DIR, CONFIG_DIR,
                          ch.load_hidden(QUEST_DIR), first=_cat.get("waiting_tab"), vary=True,
                          recent={"done": _cat.get("done_tab"), "error": _cat.get("error_tab")})


def _bubble_open(tm, bar, st, items, sel: int = 0, prompted: bool = True, sound: str = "") -> None:
    now = time.monotonic()
    _bubble_unplace(bar, st)
    st["bubble"] = {"items": items, "sel": sel, "prompted": prompted, "opened": now, "shown": set(),
                    "close_at": now + (ASK_HOLD if prompted else 60.0), "sig": _tab_sig()}
    _bubble_show(tm, bar, st, now)
    if sound:
        _cat_voice(sound)


def _bubble_show(tm, bar, st, now: float) -> None:
    """Show the bubble's current line: drawn (a picture, or cells), said from the start, noted in
    the cat's memory; the cat goes to point at the tab it's about (or back down)."""
    b = st["bubble"]
    item = _bubble_item(b)
    b["shown"].add(item.get("key"))
    _memory().note(item)
    b["said_all"] = False
    b["close_at"] = max(b["close_at"], now + 4.0)
    b["image"] = False
    if st.get("mode") in DRAWN:
        try:
            b["image"] = _bubble_render(bar, st)
        except Exception:
            b["image"] = False
    if b["image"]:
        b["reveal"] = _nine().Reveal(b["spec"]["chars"], now, CHARS_PER_SECOND)
        b["placed"] = None
        _timer_on("talk")
        _cat_place(bar, st)
        _wake()
    else:
        b["reveal"] = None                            # (cells: all at once; a redraw per letter would flicker)
        b["said_all"] = True
        b["close_at"] = max(b["close_at"], now + (ASK_HOLD if b["prompted"] else SAY_HOLD))
        tm.mark_tab_bar_dirty()
    _cat_pointing(tm, bar, st)
    _cat_note(bar, st)


def _bubble_close(tm, st) -> None:
    b = st.get("bubble")
    if b is None:
        return
    bar = tm.tab_bar
    _bubble_unplace(bar, st)
    st["bubble"] = None
    if st["spot"] == "visit":
        st["until"] = min(st["until"], time.monotonic() + 4.0)
    if not b.get("image"):
        tm.mark_tab_bar_dirty()                       # (cells: drawn again without it)
    _wake()
    _cat_note(bar, st)


def _tab_sig() -> tuple:
    return tuple(sorted((tid, s) for tid, s in ((t.id, next((x for x in ("blocked", "error", "done")
                 if any(_prev_state.get(w.id) == x for w in t)), "")) for tm in get_boss().all_tab_managers
                 for t in tm) if s))


def _bubble_tick(tm, bar, st, now: float) -> None:
    b = st.get("bubble")
    if b is not None and now > b["close_at"]:
        _bubble_close(tm, st)


def _typing_sample(now: float) -> None:
    """(Each tick) where the cursor is in the window you're looking at: when it last moved."""
    try:
        from kitty.fast_data_types import current_focused_os_window_id
        focused = current_focused_os_window_id()
        tm = next((m for m in get_boss().all_tab_managers if m.os_window_id == focused), None)
        w = tm.active_window if tm is not None else None
        if w is None:
            return
        c = w.screen.cursor
        pos = (w.id, c.x, c.y)
        last = _cat_talk["typing"]
        if "pos" not in last:
            last.update(pos=pos, at=-1e9)
        elif last["pos"] != pos:
            last.update(pos=pos, at=now)
    except Exception:
        pass


def _typing_recently(now: float) -> bool:
    """You're busy in the window you're looking at: its cursor moved in the last TYPING_QUIET
    seconds (typing, or a program printing). The cheap sign kitty gives; the cat keeps quiet then."""
    return now - _cat_talk["typing"].get("at", -1e9) < TYPING_QUIET


def _focused() -> int:
    try:
        from kitty.fast_data_types import current_focused_os_window_id
        return current_focused_os_window_id()
    except Exception:
        return 0


def _cat_speak_up(tm, bar, st, events, now: float, force: bool = False) -> None:
    """Something happened: say so once (briefly, rarely, never the same thing again soon), pointing
    at the tab; else just the moves. force (check.sh, through _cat_ctl): whatever the setting, the
    clock and the typing."""
    talk = "on" if force else _talk_setting()
    if talk == "off" or st.get("bubble") is not None or tm.os_window_id != _focused():
        return
    if not force and (now - _cat_talk["last"] < UNPROMPTED_GAP or _typing_recently(now)):
        if "waiting" in events and st.get("mode") == "floor" and _cat_rng.random() < 0.5:
            _cat_visit(tm, bar, st, _cat.get("waiting_tab"))   # no words: it just goes and looks
        return
    if _ch() is None:
        return
    try:
        items = _suggest(_focused())
    except Exception:
        return
    episode = {"waiting": round(_blocked_since.get(_cat.get("waiting_tab"), 0.0), 1),
               "done": round(_cat["done_at"], 1), "error": round(_cat["error_at"], 1),
               "badge": round(_badge_shown.get("until", 0.0), 1)}
    news_tab = {"waiting": _cat.get("waiting_tab"), "done": _cat.get("done_tab"), "error": _cat.get("error_tab")}
    for ev in events:
        item = next((s for s in items if s["kind"] == ev), None)
        if item is None:
            continue
        if ev in news_tab and item.get("action") != ("focus", news_tab[ev]):
            continue                                  # (about another tab, not the one this news is about)
        item = dict(item, key=f"{item['key']}@{episode[ev]}")   # this event: said once, then never again
        if not _memory().fresh(item):
            continue
        _cat_talk["last"] = now
        _bubble_open(tm, bar, st, [item], prompted=False, sound="meow")
        return


def _cat_tip_time(tm, bar, st, now: float) -> None:
    """Now and then (kitty-cat talk on), a tip of the day, a joke or a word, said by itself, one it
    hasn't said today."""
    if _cat_talk["tip_at"] is None:
        _cat_talk["tip_at"] = now + _cat_rng.uniform(*TIP_EVERY)
        return
    if now < _cat_talk["tip_at"]:
        return
    _cat_talk["tip_at"] = now + _cat_rng.uniform(*TIP_EVERY)
    if (_talk_setting() != "on" or st.get("bubble") is not None or now - _cat_talk["last"] < UNPROMPTED_GAP
            or _typing_recently(now) or _cat_base(now)[0] in ("asleep", "alert") or tm.os_window_id != _focused()):
        return
    try:
        items = [s for s in _suggest(tm.os_window_id) if s["kind"] in ("tip", "quest", "joke", "word")]
    except Exception:
        return
    items = [s for s in items if _memory().fresh(s)]
    if items:                                         # (nothing new: it stays quiet)
        _cat_talk["last"] = now
        _bubble_open(tm, bar, st, [_cat_rng.choice(items)], prompted=False, sound="mrrp")


def _cat_voice(kind: str) -> None:
    """One soft cat sound for a line (kitty-cat sounds off, and every sound setting, apply)."""
    if os.path.exists(CAT_SOUNDS_OFF):
        return
    _play(kind)


# -- the bubble as a picture that floats with the cat ---------------------------------------------------
def _palette(n: int):
    try:
        from kitty.fast_data_types import get_options
        from kitty.utils import color_as_int
        v = color_as_int(getattr(get_options(), f"color{n}"))
        return ((v >> 16) & 255, (v >> 8) & 255, v & 255)
    except Exception:
        return THEME_FALLBACK.get(f"color{n}", (0xcf, 0xae, 0x7c))


def _bubble_colours() -> dict:
    """The bubble in the theme's colours: the terminal's own background and text, a quiet border,
    the buttons as the sidebar's chips (the action in the accent pair, Next in the selection pair),
    each text colour at least 4.5:1 on what it's on."""
    t = _theme()
    bg, fg = t["background"], t["foreground"]

    def ink(fill, want):
        return want if _contrast(want, fill) >= 4.5 else max((fg, bg), key=lambda c: _contrast(c, fill))
    muted = t["color7"] if _contrast(t["color7"], bg) >= 4.5 else _quiet(fg, bg, QUIET_TEXT)
    return {"bg": bg, "fg": fg, "muted": muted, "close": fg, "border": _quiet(fg, bg, 3.0),
            "do": (t["active_tab_background"], ink(t["active_tab_background"], t["active_tab_foreground"])),
            "next": (t["selection_background"], ink(t["selection_background"], t["selection_foreground"]))}


def _text_drawer(os_window_id: int):
    """kitty's own text renderer (as the tab drag's picture uses), as nine.Bubble wants it."""
    from kitty.fast_data_types import draw_single_line_of_text as draw

    def text(s, rgb):
        if not s:
            return b"", 0, 0
        col = 0xFF000000 | (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]
        try:
            px, w = draw(os_window_id, s, col, 0, 2000, 2, True)
        except TypeError:                             # (no max_width: as wide as asked)
            px, w = draw(os_window_id, s, col, 0, 2000)
        return px, w, (len(px) // (4 * w) if w else 0)
    return text


def _bubble_buttons(b, item) -> list:
    """The bubble's buttons: the action the line offers (Go there ↵), and Next › named after what it
    brings, while there's a line not shown yet."""
    out = []
    if item.get("action"):
        out.append((f"{item.get('button', 'Go')} ↵", "do", "do"))
    if b.get("prompted"):
        nxt = _nine().next_line(b["items"], b["sel"], b["shown"])
        if nxt >= 0:
            out.append((f"Next {NEXT_WORDS.get(b['items'][nxt]['kind'], 'line')} ›", "next", "next"))
    return out


def _bubble_render(bar, st) -> bool:
    """Draw the bubble's picture (nine.Bubble) for the line it shows and send it to the sidebar's
    Screen. False where kitty can't draw text that way (then: cells)."""
    b = st["bubble"]
    g = st["geom"]
    ch_mod, nine = _ch(), _nine()
    item = _bubble_item(b)
    s = bar.screen
    scale = g["ch"] / 20.0
    key = (getattr(bar, "os_window_id", 0), scale)
    if st.get("bubble_tool", (None,))[0] != key:
        st["bubble_tool"] = (key, nine.Bubble(_text_drawer(getattr(bar, "os_window_id", 0)), scale))
    tool = st["bubble_tool"][1]
    colours = _bubble_colours()
    kind_rgb = _palette(ch_mod.KIND_COLOUR.get(item.get("kind"), 4))
    if _contrast(kind_rgb, colours["bg"]) < 4.5:
        kind_rgb = colours["fg"]
    width = int(min(g["width"] - 4, 360 * scale))
    count = f"{b['sel'] + 1}/{len(b['items'])}" if b.get("prompted") and len(b["items"]) > 1 else ""
    text = "".join(c for c in item.get("text", "") if c.isprintable())
    spec = tool.render(width, item.get("title", ""), kind_rgb, count, text, _bubble_buttons(b, item), colours)
    if spec["h"] > g["height"] * 0.8:
        spec = tool.render(width, item.get("title", ""), kind_rgb, count, text, _bubble_buttons(b, item), colours, 2)
    tails = (tool.tail(colours, True), tool.tail(colours, False))
    import zlib
    out = []
    for iid, (w, h, px) in ((BUB_BODY, (spec["w"], spec["h"], spec["px"])), (BUB_TEXT, spec["text"]),
                            (BUB_TAIL_DOWN, tails[0]), (BUB_TAIL_UP, tails[1])):
        out.append(_gfx(f"a=t,f=32,s={w},v={h},o=z,i={iid}", zlib.compress(px, 6)))
        out.append(_gfx(f"a=p,U=1,i={iid},p={KEEP_P},c=1,r=1"))
    _cat_feed(s, b"".join(out))
    if s.grman.image_for_client_id(BUB_BODY) is None:
        return False
    b["spec"], b["tails"] = spec, (tails[0][:2], tails[1][:2])
    b["sent"], b["placed"] = id(s), None
    b["fit"] = _bubble_fit(bar, st)
    return True


def _bubble_fit(bar, st):
    """What a bubble picture was made for: the sidebar's Screen, the cat's size, the sidebar's width
    and height. None while the cat isn't drawn (its frames not in this Screen at its size)."""
    g = st.get("geom")
    if st.get("mode") not in DRAWN or g is None or st.get("loaded") != (id(bar.screen), g["size"]):
        return None
    return (id(bar.screen), g["size"], g["width"], g["height"])


def _bubble_refit(tm, bar, st, now: float) -> None:
    """(From the cat's timer.) The open bubble still fits how the cat is drawn now: a picture made
    again for a new Screen, frame size or sidebar width (the words said so far stay said); in cells
    if the cat is text now, or the picture can't be made; closed if that fails too."""
    b = st.get("bubble")
    if b is None or not b.get("image"):
        return
    fit = _bubble_fit(bar, st)
    if fit is not None and b.get("fit") == fit and b.get("sent") == id(bar.screen):
        return
    _bubble_unplace(bar, st)
    old = b.get("reveal")
    ok = False
    if fit is not None:
        try:
            ok = _bubble_render(bar, st)
        except Exception:
            ok = False
    if ok:
        if old is not None:                           # the same moment in the line, its words re-wrapped
            b["reveal"] = _nine().Reveal(b["spec"]["chars"], old.start, CHARS_PER_SECOND)
            if not b["reveal"].done(now):
                _timer_on("talk")
        b["placed"] = None
        if _cat_place(bar, st, force=True):
            _wake()
    else:
        b["image"], b["reveal"], b["said_all"] = False, None, True     # cells: all of it at once
        b["close_at"] = max(b["close_at"], now + (ASK_HOLD if b["prompted"] else SAY_HOLD))
        b.pop("fit", None)
        tm.mark_tab_bar_dirty()                       # (_cat_settle draws it in cells, or closes it)
    _cat_note(bar, st)


def _bubble_where(st) -> tuple:
    """(x, y, tail x, tail y, tail down) in the sidebar's pixels, for the cat where it is now."""
    b, g = st["bubble"], st["geom"]
    spec = b["spec"]
    th = b["tails"][0][1]
    return _nine().place_bubble(st["x"], st["y"], g["px"], spec["w"], spec["h"], g["width"], g["height"], th)


def _bubble_place(bar, st, force: bool = False) -> bool:
    """Put the bubble's pictures where the cat is now: the card, its tail at the cat, and as much of
    the words as it has said (the words' picture cropped: whole lines, then part of the next)."""
    b = st.get("bubble")
    if b is None or not b.get("image") or b.get("sent") != id(bar.screen):
        return False
    g = st["geom"]
    spec = b["spec"]
    now = time.monotonic()
    x, y, tx, ty, down = _bubble_where(st)
    n = b["reveal"].count(now) if b.get("reveal") is not None else len(spec["chars"])
    full, part, used = 0, 0, 0
    for chars, w in spec["lines"]:                    # whole lines said, then how far into the next
        if n >= used + chars:
            full += 1
            used += chars + 1
            continue
        part = int(w * max(0, n - used) / max(1, chars))
        break
    want = (int(x), int(y), int(tx), int(ty), down, full, part)
    if want == b.get("placed") and not force:
        return False
    s, cw, ch = bar.screen, g["cw"], g["ch"]
    lh, tw = spec["lh"], spec["text"][0]
    old = b.get("placed")
    _at(s, x, y, cw, ch, _gfx(f"a=p,i={BUB_BODY},p={BUB_P},X=?,Y=?,z=5,C=1"))
    tail = BUB_TAIL_DOWN if down else BUB_TAIL_UP
    if old is not None and old[4] != down:
        _cat_feed(s, _gfx(f"a=d,d=i,i={BUB_TAIL_UP if down else BUB_TAIL_DOWN},p={TAIL_P}"))
    _at(s, tx, ty, cw, ch, _gfx(f"a=p,i={tail},p={TAIL_P},X=?,Y=?,z=6,C=1"))
    if full:
        _at(s, x + spec["tx"], y + spec["ty"], cw, ch,
            _gfx(f"a=p,i={BUB_TEXT},p={LINES_P},x=0,y=0,w={tw},h={full * lh},X=?,Y=?,z=6,C=1"))
    elif old is not None and old[5]:
        _cat_feed(s, _gfx(f"a=d,d=i,i={BUB_TEXT},p={LINES_P}"))
    if part and full < len(spec["lines"]):
        _at(s, x + spec["tx"], y + spec["ty"] + full * lh, cw, ch,
            _gfx(f"a=p,i={BUB_TEXT},p={PART_P},x=0,y={full * lh},w={part},h={lh},X=?,Y=?,z=6,C=1"))
    elif old is None or old[6]:
        _cat_feed(s, _gfx(f"a=d,d=i,i={BUB_TEXT},p={PART_P}"))
    b["placed"] = want
    b["at"] = (x, y)
    return True


def _bubble_unplace(bar, st) -> None:
    b = st.get("bubble")
    if b is None or not b.get("image") or b.get("sent") != id(bar.screen):
        return
    _cat_feed(bar.screen, b"".join(_gfx(f"a=d,d=i,i={i},p={p}") for i, p in (
        (BUB_BODY, BUB_P), (BUB_TEXT, LINES_P), (BUB_TEXT, PART_P), (BUB_TAIL_DOWN, TAIL_P), (BUB_TAIL_UP, TAIL_P))))
    b["placed"] = None


# -- the bubble in cells (where kitty can't draw it as a picture) ----------------------------------------
def _cat_anchor(bar, st):
    """(top row, bottom row, middle column) of the cat the bubble points at, or None."""
    g = st.get("geom")
    if st.get("mode") in DRAWN and g is not None:
        x, y = st["path"][-1] if st.get("path") else (st["x"], st["y"])
        top = int(y // g["ch"])
        bottom = min(g["lines"] - 1, int((y + g["px"] - 1) // g["ch"]))
        left = max(0.0, x)
        right = min(g["width"], x + g["px"])
        return top, bottom, int((left + right) / 2 // g["cw"])
    cat = _cat_cols_for(getattr(bar, "os_window_id", 0))
    new = next((e for e in bar.tab_extents if e.tab_id == -1), None)
    if new is None:
        return None
    mid = (cat[0] + cat[1]) // 2 if cat else bar.screen.columns - 5
    return new.y.start, new.y.start, mid


def _bubble_draw_cells(bar, st) -> None:
    """The bubble over the sidebar's cells (cat-helper.py's bubble, the same buttons), above the cat
    (below it if there's more room there), its tail pointing at the cat."""
    b = st["bubble"]
    ch = _ch()
    anchor = _cat_anchor(bar, st)
    if anchor is None or ch is None:
        return
    s = bar.screen
    lines, cols = s.lines, s.columns
    width = min(cols, 54)
    item = _bubble_item(b)
    count, sel = (len(b["items"]), b["sel"]) if b.get("prompted") else (1, 0)
    nxt = _nine().next_line(b["items"], b["sel"], b["shown"]) if b.get("prompted") else -1
    if b.get("prompted") and nxt < 0:
        count = 1                                     # (no Next: every line was shown)
    c = _bubble_colours()
    chips = {k: _sgr_bg(c[k][0]) + _sgr_fg(c[k][1]) for k in ("do", "next")}
    kind = b["items"][nxt]["kind"] if nxt >= 0 else None
    top_row, bottom_row, mid = anchor
    above, below = top_row - 1, lines - 1 - bottom_row
    cc = min(max(1, mid), width - 2)
    if above >= 5 or above >= below:
        out, regions, _ = ch.bubble(item, sel, count, width, "", max(4, above), chips=chips, next_kind=kind)
        out[-1] = f"{ch.MUTED}╰{'─' * (cc - 1)}┬{'─' * (width - 2 - cc)}╯{ch.R}"
        top = top_row - len(out)
    else:
        out, regions, _ = ch.bubble(item, sel, count, width, "", max(4, below), tail=("top", cc), chips=chips,
                                    next_kind=kind)
        top = bottom_row + 1
    t = _theme()
    for i, text in enumerate(out):
        row = top + i
        if 0 <= row < lines:
            _draw_sgr(s, row, text, t["background"], t["foreground"])
    b["box"] = (max(0, top), min(lines - 1, top + len(out) - 1), 0, width - 1)
    b["regions"] = [(top + li, c0, c1, cmd) for li, c0, c1, cmd in regions if 0 <= top + li < lines]


_SGR_SPLIT = re.compile("(\x1b\\[[0-9;:]*m)")


def _draw_sgr(s, row: int, text: str, bg, fg) -> None:
    """One line of the cell bubble, with its colours, on the bubble's own background (the terminal's)."""
    def rgb(c):
        return (c[0] << 16 | c[1] << 8 | c[2]) << 8 | 2
    s.cursor.x, s.cursor.y = 0, row
    try:
        s.cursor.reset_display_attrs()
    except Exception:
        pass
    s.cursor.bg, s.cursor.fg = rgb(bg), rgb(fg)
    for part in _SGR_SPLIT.split(text):
        if not part:
            continue
        if part.startswith("\x1b["):
            params = part[2:-1]
            s.apply_sgr(params)
            if params in ("", "0"):
                s.cursor.bg, s.cursor.fg = rgb(bg), rgb(fg)
            elif params == "39":
                s.cursor.fg = rgb(fg)
        else:
            s.draw("".join(ch for ch in part if ch.isprintable()))


def _bubble_hit(bar, st, px: float, py: float):
    """A click in the bubble (px, py in the sidebar's pixels): its button's command, "inside"
    elsewhere on it, None outside it."""
    b = st.get("bubble")
    if not b:
        return None
    if b.get("image"):
        if b.get("placed") is None:
            return None
        x, y = b["at"]
        spec = b["spec"]
        for x0, y0, x1, y1, cmd in spec["regions"]:
            if x + x0 <= px < x + x1 and y + y0 <= py < y + y1:
                return cmd
        return "inside" if x <= px < x + spec["w"] and y <= py < y + spec["h"] else None
    if "box" not in b:
        return None
    cw, ch = _cell(bar)
    col, row = int(px // cw), int(py // ch)
    for r, c0, c1, cmd in b["regions"]:
        if r == row and c0 <= col <= c1:
            return cmd
    t, bt, l, rt = b["box"]
    return "inside" if t <= row <= bt and l <= col <= rt else None


def _cat_hit(bar, st, px: float, py: float) -> bool:
    """A point (px in the sidebar) on the drawn cat (its picture's box, a little inset)."""
    g = st.get("geom")
    if st.get("mode") not in DRAWN or g is None or st.get("shown") is None:
        return False
    x0, y0, size = st["x"], st["y"], g["px"]
    inset = size * 0.12
    return x0 + inset <= px < min(g["width"], x0 + size - inset) and y0 + inset * 0.5 <= py < y0 + size


def _cat_clicked(tm) -> None:
    """A click on the cat: its bubble, what needs you first, then the day's lines it hasn't said
    today (a second click: the next line, as Next)."""
    bar = tm.tab_bar
    st = _cat_state(bar)
    if _ch() is None:
        return
    if st.get("bubble") is not None and st["bubble"].get("prompted"):
        st["queue"] = _moves("wink")
        _bubble_do(tm, "next")
        return
    _bubble_close(tm, st)
    try:
        items = _suggest(tm.os_window_id)
    except Exception:
        return
    nine = _nine()
    mem = _memory()
    items = [s for s in items if s["kind"] in nine.STATUS or mem.fresh(s)] or [nine.ALL_SAID]
    st["queue"] = _moves("nod")
    _bubble_open(tm, bar, st, items, 0, prompted=True, sound="mrrp")


def _cat_pointing(tm, bar, st) -> None:
    """The line is about a tab: go and point at it; else come back down."""
    item = _bubble_item(st["bubble"]) if st.get("bubble") else {}
    act = item.get("action")
    if act and act[0] == "focus":
        if st.get("visit") != act[1]:
            _cat_visit(tm, bar, st, act[1])
    elif st.get("spot") == "visit":
        _cat_go_home(st)


def _bubble_do(tm, cmd) -> None:
    """A click on a button in the bubble: Go there (or All shortcuts), Next ›, ×."""
    bar = tm.tab_bar
    st = _cat_state(bar)
    b = st.get("bubble")
    if b is None or cmd in (None, "inside"):
        return
    now = time.monotonic()
    item = _bubble_item(b)
    if cmd == "quit":
        _bubble_close(tm, st)
        return
    if cmd == "next":
        nxt = _nine().next_line(b["items"], b["sel"], b["shown"]) if b.get("prompted") else -1
        if nxt < 0:
            b["items"], b["sel"] = b["items"] + [_nine().ALL_SAID], len(b["items"])
        else:
            b["sel"] = nxt
        if not st["queue"]:
            st["queue"] = _moves("nod")
        _bubble_unplace(bar, st)
        _bubble_show(tm, bar, st, now)
        return
    if cmd == "do":
        act = item.get("action")
        if not act:
            _bubble_do(tm, "next")
            return
        _bubble_close(tm, st)
        _clicking["on"] = True
        try:
            if act[0] == "focus":
                tab = _tab_obj(act[1])
                for m in get_boss().all_tab_managers:
                    if tab is not None and tab in list(m):
                        w = getattr(tab, "active_window", None)
                        if m is tm or w is None:
                            m.set_active_tab(tab)
                        else:                         # another kitty window: as kitty @ focus-tab does it
                            get_boss().set_active_window(w, switch_os_window_if_needed=True)
                        break
            elif act[0] == "help":
                get_boss().combine(ACTIONS["help"])
        except Exception:
            pass
        finally:
            _clicking["on"] = False


# -- carrying it (a drag) ---------------------------------------------------------------------------------
# kitty hands the sidebar the mouse's moves only while a tab is dragged (or text selected), so a press
# on the cat tells kitty a drag started with an id no tab has: the moves come (kitty's own handling
# finds no such tab and does nothing), the cat follows the pointer (its bubble with it), and the
# release (anywhere) puts it down: on the floor, or sitting where you left it for a while. A press
# with no move is a click.
def _cat_drag_start(tm, x, y) -> None:
    st = _cat_state(tm.tab_bar)
    g = tm.tab_bar.window_geometry
    _cat_drag[tm.os_window_id] = {"x0": x, "y0": y, "dx": x - g.left - st["x"], "dy": y - g.top - st["y"], "moved": False}
    try:
        from kitty.fast_data_types import set_tab_being_dragged
        set_tab_being_dragged(CAT_DRAG_ID, False, x, y)
    except Exception:
        pass


def _cat_drag_end() -> None:
    try:
        from kitty.fast_data_types import get_tab_being_dragged, set_tab_being_dragged
        if get_tab_being_dragged()[0] == CAT_DRAG_ID:
            set_tab_being_dragged()
    except Exception:
        pass


def _cat_drag_motion(tm, x, y) -> None:
    d = _cat_drag.get(tm.os_window_id)
    bar = tm.tab_bar
    st = _cat_state(bar)
    g = st.get("geom")
    if d is None or g is None or st.get("mode") != "floor":
        return
    if not d["moved"]:
        try:
            from kitty.fast_data_types import get_options
            threshold = get_options().drag_threshold
        except Exception:
            threshold = 3
        if (x - d["x0"]) ** 2 + (y - d["y0"]) ** 2 <= max(1, threshold) ** 2:
            return
        d["moved"] = True
        st["carried"], st["path"], st["queue"] = True, [], []
        st["visit"], st["spot"] = None, "perch"
    wg = bar.window_geometry
    st["x"] = min(max(0.0, x - wg.left - d["dx"]), max(0.0, g["width"] - g["px"]))
    st["y"] = min(max(0.0, y - wg.top - d["dy"]), g["floor_y"])
    if _cat_place(bar, st):
        _wake()


def _cat_drop(tm) -> bool:
    """The release of a press on the cat: True if it was carried (put it down), False for a click."""
    d = _cat_drag.pop(tm.os_window_id, None)
    _cat_drag_end()
    if d is None or not d["moved"]:
        return False
    st = _cat_state(tm.tab_bar)
    g = st.get("geom")
    st["carried"] = False
    st["visit"] = None
    if g is not None and st["y"] >= g["floor_y"] - g["ch"]:
        st["y"], st["spot"], st["home_x"] = g["floor_y"], "floor", st["x"]
    else:
        st["spot"], st["until"] = "perch", time.monotonic() + PERCH_SECONDS
    st["queue"] = _moves("land")
    if _cat_place(tm.tab_bar, st):
        _wake()
    _cat_note(tm.tab_bar, st)
    return True


# -- cat.txt: where it is, for check.sh ---------------------------------------------------------------
def _cat_note(bar, st) -> None:
    """cat.txt in the state folder (the active kitty window's cat): where it is drawn, its frame, its
    bubble and the bubble's buttons, in screen pixels, written when that changes (not while it walks)."""
    try:
        if st.get("path"):
            return
        atm = get_boss().active_tab_manager
        if atm is None or atm.os_window_id != getattr(bar, "os_window_id", None):
            return
        wg = bar.window_geometry
        g = st.get("geom")
        frame = st["shown"][1] if st.get("shown") else "-"
        text = f"mode: {st.get('mode')}\nspot: {st.get('spot')}\nframe: {frame}\ntalk: {_talk_setting()}\n"
        if g is not None and st.get("mode") in DRAWN:
            x0, y0 = wg.left + st["x"], wg.top + st["y"]
            text += f"cat: {int(x0)} {int(y0)} {g['px']} {g['px']} {g['size']}\n"
            text += f"click: {int(x0 + g['px'] / 2)} {int(y0 + g['px'] * 0.6)}\n"
        b = st.get("bubble")
        if b is not None:
            item = _bubble_item(b)
            said = "all" if b.get("said_all") else "talking"
            text += (f"bubble: open {item.get('kind')} {'asked' if b.get('prompted') else 'said'} "
                     f"{b['sel'] + 1}/{len(b['items'])} {item.get('key') if item.get('kind') in ('waiting', 'done', 'error', 'hello') else ''}\n")
            text += f"bubble said: {said}\nbubble drawn: {'picture' if b.get('image') else 'cells'}\n"
            if b.get("image") and b.get("placed") is not None:
                x, y = b["at"]
                spec = b["spec"]
                text += f"bubble box: {int(wg.left + x)} {int(wg.top + y)} {int(wg.left + x + spec['w'])} {int(wg.top + y + spec['h'])}\n"
                for x0, y0, x1, y1, cmd in spec["regions"]:
                    text += f"bubble {cmd}: {int(wg.left + x + (x0 + x1) / 2)} {int(wg.top + y + (y0 + y1) / 2)}\n"
            elif "box" in b:
                cw, ch = _cell(bar)
                t, bt, l, r = b["box"]
                text += f"bubble box: {wg.left + l * cw} {wg.top + t * ch} {wg.left + (r + 1) * cw} {wg.top + (bt + 1) * ch}\n"
                for row, c0, c1, cmd in b["regions"]:
                    text += f"bubble {cmd}: {wg.left + ((c0 + c1) // 2) * cw + cw // 2} {wg.top + row * ch + ch // 2}\n"
        else:
            text += "bubble: closed\n"
        if text == st.get("noted"):
            return
        st["noted"] = text
        _write_atomic(os.path.join(QUEST_DIR, "cat.txt"), text)
    except Exception:
        pass


# -- check.sh and record.sh drive it here (tests/cat_ctl.py, a kitten run in the test kitty) -----------
def _cat_ctl(boss, args) -> str:
    """walk X (px from the sidebar's left), visit (the tab waiting for you), home (bubble closed),
    freeze / thaw (no dice, no wandering), day (no night nap), say (speak up about the waiting tab
    now), pace N (to and fro, for measuring), timing (how steady the talking clock was), state."""
    global _night
    tm = boss.active_tab_manager
    bar = tm.tab_bar
    st = _cat_state(bar)
    cmd = args[0] if args else "state"
    if cmd == "walk" and st.get("geom") and st.get("mode") == "floor":
        x = min(max(0.0, float(args[1])), st["geom"]["width"] - st["geom"]["px"])
        st["home_x"] = x
        _cat_walk(st, (x, st["geom"]["floor_y"]))
    elif cmd == "visit":
        tid = next((t.id for t in tm for w in t if _prev_state.get(w.id) == "blocked"), None)
        return "visiting" if _cat_visit(tm, bar, st, tid) else "no visit"
    elif cmd == "home":
        _bubble_close(tm, st)
        _cat_go_home(st)
    elif cmd in ("freeze", "thaw"):
        st["frozen"] = cmd == "freeze"
    elif cmd == "day":
        _night = lambda: False   # noqa: E731
    elif cmd == "say":
        _bubble_close(tm, st)
        _memory().said.clear()
        _memory().recent.clear()
        _cat_speak_up(tm, bar, st, ["waiting"], time.monotonic(), force=True)
    elif cmd == "pace":                                  # walk to and fro (the CPU measurement)
        g = st["geom"]
        st["frozen"] = True
        st["path"] = [(g["width"] - g["px"], g["floor_y"]), (0.0, g["floor_y"])] * int(args[1] if len(args) > 1 else 4)
        _timer_on("walk")
    elif cmd == "timing":
        ts = getattr(_cat_talk_tick, "log", [])
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        if not gaps:
            return "no talking measured"
        gaps.sort()
        return (f"talk ticks: {len(ts)}, interval mean {sum(gaps) / len(gaps) * 1000:.1f} ms, median "
                f"{gaps[len(gaps) // 2] * 1000:.1f} ms, worst {gaps[-1] * 1000:.1f} ms")
    g = st.get("geom") or {}
    b = st.get("bubble")
    return (f"mode={st.get('mode')} spot={st.get('spot')} x={st.get('x')} y={st.get('y')} path={len(st.get('path') or [])} "
            f"frame={(st.get('shown') or [0, '-'])[1]} size={g.get('size')} rows={g.get('rows')} failed={st.get('failed')} "
            f"wid={getattr(bar, '_vye_cat_wid', 0)} images={bar.screen.grman.image_count} "
            f"bubble={'none' if b is None else ('picture' if b.get('image') else 'cells')} "
            f"said={'-' if b is None else ('all' if b.get('said_all') else 'talking')}")


def _cat_reload() -> None:
    """A config reload: the timers are the old load's; the cats keep where they are."""
    _timer_off("walk")
    _timer_off("talk")
    for tm, bar, st in list(_cat_bars()):
        try:
            _cat_unplace(bar, st)
        except Exception:
            pass
        st["path"], st["queue"], st["bubble"], st["loaded"] = [], [], None, None
        st["carried"], st["seen"] = False, None          # (this load's mood state starts afresh)
        st.pop("bubble_tool", None)
        if st.get("spot") in ("visit", "peek", "perch") and st.get("geom"):
            st["x"], st["y"], st["spot"] = st.get("home_x") or 0.0, st["geom"]["floor_y"], "floor"


RUNNING_FILE = os.path.join(QUEST_DIR, "tab_bar.running")


def _record_running_version(kt) -> None:
    """Write a fingerprint of the tab_bar.py this kitty is really running. The patches (dragging,
    "+ New tab", quests) keep the version of the first load until kitty restarts, so that's the one
    that counts. `ninelives` compares it with the installed file and says when a restart is due."""
    try:
        import hashlib
        if getattr(kt, "_vye_running_hash", None) is None:
            if getattr(kt, "_vye_quest_action", None) is not None:
                # an older tab_bar.py (from before this fingerprint) loaded first: its patches run
                kt._vye_running_hash = "older"
            else:                                               # first load in this kitty process
                with open(os.path.join(CONFIG_DIR, "tab_bar.py"), "rb") as f:
                    kt._vye_running_hash = hashlib.sha1(f.read()).hexdigest()
        os.makedirs(QUEST_DIR, exist_ok=True)
        _write_atomic(RUNNING_FILE, kt._vye_running_hash + "\n")
    except Exception:
        pass


def _install_quests() -> None:
    import kitty.tab_bar as kt
    _record_running_version(kt)
    kt._vye_quest_action = _quest_action
    kt._vye_quest_done = _quest_done
    kt._vye_new_tab_label = _new_tab_label
    kt._vye_fit_vertical = _fit_vertical
    kt._vye_hidden_line_click = _sidebar_click
    kt._vye_search_row = _search_row
    kt._vye_tab_clicked = _tab_clicked
    kt._vye_cat_ctl = _cat_ctl
    kt._vye_hooks = {"drop": lambda: _play("drop")}
    _write_quest_files()
    _patch_quest_actions()


_install_quests()
_cat_reload()
_patch_drag_visuals()
_patch_tab_hit_areas()
_patch_tab_drag_in_window()
_patch_new_tab_button()
