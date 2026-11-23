# tab_bar.py — draws each sidebar tab (number, live status icon, name, folder) and plays the tab
# sounds. Used by {custom} in tab_title_template in kitty.conf. Part of NineLives
# (config/ in the NineLives repository); install with scripts/install.sh.
#
# Each tab:   " 12 ◐ name"         number right-aligned, a 2-cell status slot, the name (cut with …)
#             "      folder   12m"  the last two folders, muted, not bold; at the right, how long
#                                  the tab has been working / waiting / finished (from 1 minute on)
# Status icons are coloured on inactive tabs (palette colours, so both themes work): working blue,
# finished green, sparkle gold, waiting-for-you amber, error red. On the active tab they stay the
# tab's own colour.
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
#   ✗                error            ‖ paused            ● new output in a background tab
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
}
# Sounds within COALESCE seconds of each other play once: the most important one wins.
PRIORITY = {"drop": 0, "done": 1, "done-2": 1, "done-3": 1, "remind": 2, "error": 3, "blocked": 4, "badge": 5, "rank": 6}
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
_cat = {"blocked": 0, "fresh_block": False, "working": False, "done_at": -99.0, "error_at": -99.0,
        "quiet_since": time.monotonic(), "drawn": None}
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
_agents: dict = {}           # tab id -> (checked at, mark)


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


def _agent_mark(tab_id) -> str:
    """ "✳" for Claude, "π" for omp, two letters for other agents, "" for anything else."""
    now = time.monotonic()
    hit = _agents.get(tab_id)
    if hit and now - hit[0] < AGENT_TTL:
        return hit[1]
    mark = ""
    try:
        for tm in get_boss().all_tab_managers:
            for tab in tm:
                if tab.id == tab_id and tab.active_window is not None:
                    mark = AGENT_MARK.get(_foreground_name(tab.active_window), "")
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
        # afplay can't read .oga: install.sh adds a .wav of each sound; classic: macOS's own sounds
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
        return ["afplay", "-v", f"{(vol / 65536) ** 3:.4f}", path]
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
        return f" {_tab_number(data):>2}    {data.get('title') or ''}"


def _draw_title(data) -> str:
    fmt = data["fmt"]
    tab = data.get("tab")
    width = data.get("max_title_length") or 30
    try:
        wd = tab.active_wd if tab is not None else ""
    except Exception:
        wd = ""
    icon, kind, extra = _status(data)
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
    if kind == "blocked" and not active:
        # Waiting for you is the one state that must not be missed: a filled chip (the glyph cut
        # out of an amber cell) instead of a thin outline. While it pulses it swaps with the outline.
        slot = f"{icon_fg}\x1b[7m{slot[:1]}\x1b[27m{slot[1:]}"
    else:
        slot = f"{icon_fg}{slot}"
    index = _tab_number(data)
    head = f" {index:>2} "
    try:
        pos = int(index or 0) - 1
    except ValueError:
        pos = 0
    if not active and 0 <= (_frame - _wave_start) - pos // 2 < 3:
        # a badge was just earned: a gold wave runs down the tab numbers (two tabs a frame)
        head = f"{fmt.fg.color3}{fmt.bold}{head}{fmt.nobold}{tab_fg}"
    room = max(1, width - INDENT)
    if active and _buttons_on() and room > 8:
        # the current tab gets a × at its right end: click it to close the tab (_sidebar_click)
        # (width is kitty's max_title_length: the sidebar's real width, narrower in a small window)
        shown = _fit(name, room - 2)
        _buttons.setdefault("close_cols", {})[data.get("tab_id")] = INDENT + room - 1
        line1 = f"{head}{slot}{tab_fg}{name_fg}{shown}{' ' * (room - 1 - _cells(shown))}×{tab_fg}"
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
    if branch and avail - 3 - fw >= 4:
        # a branch that isn't main/master, after the folder: "code/webapp ⌥ fix-login" (⌥: DejaVu has it)
        folder = _fit_start(folder, fw)
        b = _fit(branch, avail - 3 - _cells(folder))
        bcol = "" if active else getattr(fmt.fg, f"color{BRANCH_COLOUR}")
        tail = f" {bcol}⌥ {b}{tab_fg}"
        used = _cells(folder) + 3 + _cells(b)
    else:
        folder = _fit_start(folder, avail)
        used = _cells(folder)
    if took:                                       # the time at the right edge
        tail += " " * (room - used - _cells(took) - 1) + took
    mark = _agent_mark(data.get("tab_id"))         # under the status icon: which agent runs here
    if mark:
        mcol = "" if active else getattr(fmt.fg, f"color{AGENT_COLOUR}")
        lead = f"{' ' * (INDENT - 2)}{mcol}{mark}{' ' * (2 - _cells(mark))}{tab_fg}"
    else:
        lead = " " * INDENT
    return f"{line1}\n{fmt.nobold}{lead}{folder}{tail}"


BRANCH_COLOUR = 5            # magenta, like the branch in the prompt
AGENT_COLOUR = 8             # the theme's dim grey: a quiet label, not a status
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
                                _reminded.discard(tab.id)
                                _play("blocked")
                            elif state == "error":
                                _cat["error_at"] = now
                                _play("error", tab.id)
                            if state == "done" and prev == "working":
                                _cat["done_at"] = now
                        _prev_state[w.id] = state
                    if state == "blocked" and now - _blocked_since.get(tab.id, 0) < PULSE_SECONDS + 0.5:
                        slow = True
                if any(_prev_state.get(w.id) == "working" for w in tab):
                    _working_tabs.add(tab.id)
                else:
                    _working_tabs.discard(tab.id)
                # plain terminal tabs: spin while a command runs, sparkle (+ chime if long) when it ends
                w = tab.active_window
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
                    if now - started >= LONG_JOB:
                        _note_done(now)
                        _play("done", tab.id)
                if 0 <= _frame - _sparkle_start.get(tab.id, -99) <= len(SPARKLE):
                    animate = True                 # (one more frame after the last, to land on ✓)
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
        for wid in list(_prev_state):
            if wid not in seen:
                del _prev_state[wid]
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
        if _cat_face() != _cat["drawn"]:
            animate = True
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
_ICON_RE = re.compile("[⠁-⣿◐-◓✓⚠✗‖●✦✧✶\U0001f514-]")
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
    """Lay out the sidebar; when kitty can't fit every tab, show the ones that matter
    (_pick_tabs) and name the hidden ones on the line under them (a click there goes to the first
    hidden tab: _hidden_line_click). Returns (kitty's result, how many tabs are hidden)."""
    import kitty.tab_bar as kt
    data = _fit_own_rows(bar, data)
    # tabs keep their real numbers (Alt+N means the Nth tab): kitty numbers every entry it draws,
    # the search row on top and hidden tabs included
    nums = {t.tab_id: n for n, t in enumerate((t for t in data if t.tab_id > 0), 1)}
    kt._vye_tab_numbers = nums
    bar._vye_hidden = None
    r = orig(bar, data, *a, **k)
    shown = len(bar.tab_extents)                    # kitty kept a line for its red … under these
    if shown >= len(data) or shown < 1:
        _note_close_row(bar, data)
        _note_layout(bar, data, {e.tab_id for e in bar.tab_extents}, [])
        return r, 0
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
            s.cursor.bg = kt.as_rgb(kt.color_as_int(bar.draw_data.default_bg))
            s.cursor.fg = kt.as_rgb(kt.color_as_int(bar.draw_data.inactive_fg))
            s.cursor.bold = s.cursor.italic = False
            s.draw(_fit(f"  ⋯   hidden: {_number_ranges(hidden)}", s.columns - 1))
            bar._vye_hidden = (row, next(t for t, n in nums.items() if n == hidden[0]))
        except Exception:
            pass
    _note_close_row(bar, data)
    _note_layout(bar, data, shown_ids, hidden)
    return r, len(hidden) if bar._vye_hidden else 0


def _fit_own_rows(bar, data):
    """Our own rows (the search row, "+ New tab") are drawn as they are, so make them for the
    sidebar's real width (_line_width): a small window or a big font makes kitty's sidebar narrower,
    and kitty would cut the buttons off the end with … (and clicks would miss them)."""
    try:
        width = _line_width(bar)
        wid = getattr(bar, "os_window_id", None)
        out = []
        for t in data:
            if t.tab_id == SEARCH_ROW_ID:
                t = t._replace(title=_search_row(width, wid) or t.title)
            elif t.tab_id < 0 and t.title != "+":    # kitty's bare + is left alone: no label patch
                t = t._replace(title=_new_tab_label(width))
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
# A row on top of the sidebar:  "  ❯   Search tabs…     ⚠2  +"  — click the words to search (the
# Ctrl+Shift+Space box), ⚠ for the tab waiting for you (Ctrl+Alt+U), + for a new tab. A narrow
# sidebar (small window, big font) gets shorter words; ⚠ and + always stay whole. The tab you're
# on has a × at its right end that closes it (kitty can't tell where the mouse hovers, so it's the
# current tab that gets it). kitty-buttons off hides the row and the ×.
SEARCH_ROW_ID = -2           # a made-up entry like kitty's own "+" (-1); our click hook handles it
BUTTONS_OFF = os.path.join(CONFIG_DIR, "buttons-off")
_FINDER = '"${KITTY_CONFIG_DIRECTORY:-${XDG_CONFIG_HOME:-$HOME/.config}/kitty}/tab-finder.py"'
ACTIONS = {   # the same actions as the keys in kitty.conf
    "search": f"launch --type=overlay --allow-remote-control --title current sh -c 'exec python3 {_FINDER} search'",
    "waiting": f"launch --type=background --allow-remote-control sh -c 'exec python3 {_FINDER} waiting'",
    "new": "new_tab_with_cwd",
    "close": "close_tab",
}
ROW_WIDTH = 30               # = tab_title_max_length: the row's width when nothing narrows the sidebar
_buttons: dict = {}          # what the search row's columns do (per kitty window), the × columns (per tab)
# the words in front of the buttons, longest first: a narrow sidebar (a small window, a big font)
# gets a shorter one, and the buttons always stay whole
SEARCH_LABELS = ("  ❯   Search tabs…", "  ❯   Search…", "  ❯   Find…", "  ❯", "")


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


def _row_layout(width: int, waiting: int) -> tuple:
    """(the search row's text, [(first col, last col, action)]) for a row `width` cells wide.
    + is in the last column (where the current tab's × is), ⚠N (tabs waiting) in front of it; the
    words get whatever room is left: the full label, a shorter one, only ❯, or nothing."""
    warn = f"⚠{waiting}" if waiting else ""
    for left in SEARCH_LABELS:
        for sep in ("  ", " "):                    # between ⚠N and +
            right = f"{warn}{sep}+" if warn else "+"
            if _cells(left) + 1 + _cells(right) <= width:       # (a blank cell before ⚠ and +)
                break
        else:
            continue
        break
    else:
        left, sep, warn = "", "", ""                # no room even for ⚠N: + alone
    plus = max(0, width - 1)
    if not warn:
        gap = max(0, plus - _cells(left))
        return f"{left}{' ' * gap}+", [(0, plus - 2, "search"), (plus - 1, width, "new")]
    wc = plus - len(sep) - _cells(warn)              # where ⚠ is
    gap = max(0, wc - _cells(left))
    cols = [(0, wc - 2, "search"), (max(0, wc - 1), plus - 2, "waiting"), (plus - 1, width, "new")]
    return f"{left}{' ' * gap}{AMBER}{warn}{FG}{sep}+", cols


def _search_row(width=None, wid=None) -> str:
    """The row's text (kitty draws it as is), and where its buttons are. Called without arguments
    by the "+ New tab" patch (which may be an older load's), then again by _fit_vertical with the
    sidebar's real width."""
    if not _buttons_on():
        return ""
    # ❯ sits in the number column like "+ New tab"'s +, and is the search box's own prompt mark.
    # Nothing waiting: no ⚠ at all (a grey hazard sign with nothing behind it only puzzles); tabs
    # waiting: an amber ⚠ with the count (amber means "needs you" everywhere); click = go there.
    text, cols = _row_layout(width or ROW_WIDTH, _cat.get("blocked", 0))
    _buttons["cols"] = cols
    if wid is not None:
        _buttons.setdefault("cols_by", {})[wid] = cols
    return text


def _cols_for(wid) -> list:
    """The search row's buttons as last drawn in this kitty window."""
    return _buttons.get("cols_by", {}).get(wid) or _buttons.get("cols", ())


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


def _region(tm, x, y):
    """Which of our click targets (x, y) is on: ("hidden",), ("button", name), ("close",) or None."""
    bar = tm.tab_bar
    g = bar.window_geometry
    if not (g.left <= x < g.right and g.top <= y < g.bottom):
        return None
    row, col = int((y - g.top) // bar.cell_height), int((x - g.left) // bar.cell_width)
    info = getattr(bar, "_vye_hidden", None)
    if info and row == info[0]:
        return ("hidden",)
    ext = next((e for e in bar.tab_extents if e.y.start <= row <= e.y.end), None)
    if ext is None:
        return None
    if ext.tab_id == SEARCH_ROW_ID:
        return ("button", next((a for c0, c1, a in _cols_for(tm.os_window_id) if c0 <= col <= c1), "search"))
    at = tm.active_tab
    close_col = _buttons.get("close_cols", {}).get(at.id) if at is not None else None
    if (at is not None and ext.tab_id == at.id and close_col is not None and _buttons_on()
            and row == _buttons.get("close_row", {}).get(tm.os_window_id, -1) and col >= close_col - 1):
        return ("close",)
    return None


def _sidebar_click(tm, x, y, button, action) -> bool:
    """Clicks kitty mustn't see: the "hidden: …" line (goes to the first hidden tab), the search row's
    words and buttons, and the × on the current tab. A press there is swallowed (kitty never starts
    a drag or counts a click), and the action runs on the release only if it lands on the same
    target as the press; releases of presses kitty saw go to kitty. True when the event was ours."""
    try:
        from kitty.fast_data_types import GLFW_MOUSE_BUTTON_LEFT, GLFW_PRESS, GLFW_RELEASE
        if button == -1 or action not in (GLFW_PRESS, GLFW_RELEASE):
            return False
        wid = tm.os_window_id
        here = _region(tm, x, y)
        if action == GLFW_PRESS:
            if here is None:
                _pressed.pop(wid, None)
                return False
            _pressed[wid] = (button, here)
            return True
        pressed = _pressed.pop(wid, None)
        if pressed is None:
            return False                            # kitty saw the press: it gets the release
        if pressed == (GLFW_MOUSE_BUTTON_LEFT, here):
            if here == ("hidden",):
                tab = tm.tab_for_id(tm.tab_bar._vye_hidden[1])
                if tab is not None:
                    tm.set_active_tab(tab)
            elif here == ("close",):
                _close_current(tm)
            else:
                _run(here[1])
        return True
    except Exception:
        _pressed.pop(getattr(tm, "os_window_id", 0), None)
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
        at = next((t.tab_id for t in data if t.tab_id > 0 and t.is_active), None)
        close_col = _buttons.get("close_cols", {}).get(at)
        crow = _buttons.get("close_row", {}).get(wid, -1)
        if crow >= 0 and close_col is not None and _buttons_on():
            text += f"button close: {px(close_col, crow)}\n"
        # what kitty really drew there, read back from the sidebar's cells, so check.sh can compare
        # it with the columns above: the column of each glyph, and the sidebar's cell grid
        text += f"cells: {g.left} {g.top} {bar.cell_width} {bar.cell_height} {bar.screen.columns}\n"
        for row, glyphs in ((top.y.start if top is not None else -1, "⚠+"), (crow, "×")):
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


def _cat_face() -> str:
    """The cat's current frame, e.g. "=^.^= ~" (with colour codes). Most important mood first:
    alert (a tab needs you; "2!" = two tabs) · cheering (badge; ♛ = new rank) · happy (just finished) · startled
    (error) · watching (working; the tail swishes) · idle (blinks now and then) · asleep (zZ)."""
    if os.path.exists(CAT_OFF):
        return ""
    now = time.monotonic()
    if _cat["blocked"]:                # status first: a waiting tab beats any celebration
        n = _cat["blocked"]
        bang = (str(n) if n > 1 else "") + "!"
        if _cat["fresh_block"] and (_frame // 4) % 2:
            bang = " " * len(bang)
        return f"=O.O= {AMBER}{bang}{FG}"
    if _badge_shown["until"] > now:
        crown = f"{GOLD}♛{FG}" if _badge_shown.get("rank") else ""
        return f"=^▽^={crown}{GOLD}{TWINKLE[_frame % len(TWINKLE)]}{FG}"
    if now - _cat["done_at"] < 4:
        # one note per tab in the current run of finishes (the streak), up to three
        notes = min(3, _streak["step"]) if now - _streak["at"] < 4 else 1
        return f"=^ω^= {GREEN}{'♪' * max(1, notes)}{FG}"
    if now - _cat["error_at"] < 4:
        return "=>.<= "
    if _cat["working"]:
        return "=^.^= " + "~-"[(_frame // 4) % 2]
    quiet = now - _cat["quiet_since"]
    if quiet >= SLEEP_AFTER:
        if quiet >= SLEEP_AFTER + 60:
            return "=-.-= zZ"            # fully asleep: no more redraws
        return "=-.-= " + ("z", "zz", "zZ", "zZz")[(_frame // 12) % 4]
    return "=-.-=" if _frame % 48 == 0 else "=^.^="


def _visible(s: str) -> str:
    return re.sub("\x1b\\[[0-9;]*m", "", s)


NEW_TAB_LABELS = (NEW_TAB_LABEL, "  +   New", "  +")   # shorter ones for a narrow sidebar


def _new_tab_label(width=None) -> str:
    """ "+ New tab" with the cat at its right end, and under it the next quest (or the badge
    just earned), both fitted to `width` cells (the sidebar's; ROW_WIDTH if not known)."""
    width = width or ROW_WIDTH
    line1, line2 = _fit(NEW_TAB_LABEL, width), ""
    try:
        cat = _cat_face()
        _cat["drawn"] = cat
        if cat:
            # the cat ends 2 cells short of the right edge; a narrow sidebar shortens the words
            # first (the + says it), then leaves the cat out
            end = max(0, width - 2)
            label = next((l for l in NEW_TAB_LABELS if _cells(l) + 2 + _cells(_visible(cat)) <= end), None)
            if label is not None:
                line1 = label + " " * (end - _cells(label) - _cells(_visible(cat))) + cat
    except Exception:
        pass
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
    ("output", "Replay", "Ctrl+Shift+G  last output", "Ctrl+Shift+G shows the last command's output on its own"),
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


def _quest_line(width=None) -> str:
    """The line under "+ New tab": the badge just earned (sparkling), else the next quest. Cut to
    `width` cells (the mark and its gap are 6)."""
    if os.path.exists(QUESTS_OFF):
        return ""
    room = (width or ROW_WIDTH) - 6
    now = time.monotonic()
    n = len(_earned)
    if room < 2:                                   # no room for words: the ★ count alone
        return f"{GOLD}{'★' + str(n):>3}{FG}"
    if _badge_shown["until"] > now and _badge_shown["id"] in QUEST_BY_ID:
        spark = TWINKLE[_frame % len(TWINKLE)]
        if _badge_shown.get("rank"):
            return f"{GOLD}{spark:>3}{FG}   " + _fit(f"new rank: {_rank(n)[0]}!", room)
        if _badge_shown.get("mastered"):
            return f"{GOLD}{spark:>3}{FG}   " + _fit(f"mastered: {QUEST_BY_ID[_badge_shown['id']][1]}!", room)
        return f"{GOLD}{spark:>3}{FG}   " + _fit(f"badge: {QUEST_BY_ID[_badge_shown['id']][1]}!", room)
    if _coach["until"] > now:
        return f"{GOLD}{'→':>3}{FG}   " + _fit(_coach["text"], room)
    q = _next_quest()
    return f"{GOLD}{'★' + str(n):>3}{FG}   " + _fit(q[2] if q else f"all done: {RANKS[-1][1]}!", room)


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
    kt._vye_hooks = {"drop": lambda: _play("drop")}
    _write_quest_files()
    _patch_quest_actions()


_install_quests()
_patch_drag_visuals()
_patch_tab_hit_areas()
_patch_tab_drag_in_window()
_patch_new_tab_button()
