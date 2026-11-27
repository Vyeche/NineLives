#!/usr/bin/env python3
"""settings.py — NineLives settings, one row per setting. Part of NineLives.

    settings.py [panel]   the settings list (Ctrl+Shift+F2, the sidebar's ⚙, `ninelives`): ↑/↓ (j/k)
                          choose, Enter/Space/←/→ change, Esc or q closes; a click changes a row
    settings.py list      print every setting and its value

Each change is made at once, in the same files the kitty-* shell commands use (in kitty's config
folder: sounds-off, sounds-volume, sounds-classic, cat-off, cat-talk, cat-sounds-off, quests-off,
buttons-off, full-commands, tips-off), so the sidebar, the shell commands and this list always agree.
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import unicodedata

MUTED = "\x1b[37m"           # palette colour 7: secondary text that still reads (not SGR dim)
B, R = "\x1b[1m", "\x1b[0m"
AMBER = "\x1b[33m"
IS_MACOS = sys.platform == "darwin"
CLASSIC_DIR = "/usr/share/sounds/freedesktop/stereo"
MAC_SOUNDS = "/System/Library/Sounds"
QUEST_TOTAL = 16             # as in tab_bar.py's QUESTS
TOP = 4                      # the terminal line (1-based) the first row is drawn on

# key, label, file, (value when the file is missing, value when it's there), description
TOGGLES = {
    "sounds": ("Sounds", "sounds-off", ("on", "off"),
               "Sounds when a tab finishes, needs you or fails. Ctrl+Alt+M also mutes. (kitty-sounds)"),
    "soundset": ("Sound set", "sounds-classic", ("NineLives", "desktop"),
                 "NineLives' own sounds, or the desktop's standard ones. (kitty-sounds classic)"),
    "cat": ("The cat", "cat-off", ("shown", "hidden"),
            "Nine, the cat in the sidebar: it sits under your tabs, goes to the one that needs you, and "
            "a click on it tells you what's up. Hidden: no cat. (kitty-cat)"),
    "catsounds": ("Cat sounds", "cat-sounds-off", ("on", "off"),
                  "A soft meow or mrrp when the cat says something (with the other sounds, at their "
                  "volume). (kitty-cat sounds)"),
    "quests": ("Quests", "quests-off", ("on", "off"),
               "Shortcut quests and badges; the next one shows under + New tab. Badges are kept. (kitty-quests)"),
    "buttons": ("Sidebar buttons", "buttons-off", ("shown", "hidden"),
                "The search field and buttons on top of the sidebar, and × on the current tab. (kitty-buttons)"),
    # the other way round: off (short names) while the file is missing
    "commands": ("Full commands in tab names", "full-commands", ("off", "on"),
                 "Off: a running command's tab shows its program and subcommand (git push) or script "
                 "name, not its arguments, which can hold a password. On: the whole line. (kitty-commands)"),
    "tips": ("Prompt tips", "tips-off", ("on", "off"),
             "A tip or your next quest under each new shell prompt. (kitty-tips)"),
}
LABELS = {k: v[0] for k, v in TOGGLES.items()}
LABELS.update(volume="Volume", cattalk="The cat talks", edit="Edit kitty.conf in your editor…")
TALK_VALUES = ("on", "events only", "off")   # in the cat-talk file: (missing), events, off
DESCRIPTIONS = {k: v[3] for k, v in TOGGLES.items()}
DESCRIPTIONS.update(
    volume="How loud the tab sounds are, 5–100 %. You hear the new level. (kitty-sounds volume N)",
    cattalk="On: the cat speaks up by itself now and then, briefly (a tab needs you or finished, a "
            "badge, a tip), never while you type. Events only: no tips. Off: only when you click it. "
            "(kitty-cat talk)",
    edit="Opens kitty.conf in your editor; Ctrl+Shift+F5 reloads it after you save.")
# the rows in order; None is a blank line
ROWS = ("sounds", "volume", "soundset", "cat", "cattalk", "catsounds", "quests", "buttons", "commands", "tips",
        None, "edit")
OFF_VALUES = {"off", "hidden"}
SHORT_LABELS = {"edit": "Edit kitty.conf…", "buttons": "Buttons", "commands": "Full commands",
                "cattalk": "Cat talks"}   # for a narrow window
FOOTERS = ("↑↓ move · ←→ Enter change · Esc close", "↑↓ · Enter change · Esc close", "Enter change · Esc close")
ROW_MAX = 64                 # rows are at most this wide, so a label and its value stay close


def conf_dir() -> str:
    """This kitty's config folder (where the switch files live), as tips.sh finds it."""
    return os.environ.get("KITTY_CONFIG_DIRECTORY") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "kitty")


def state_dir() -> str:
    return os.environ.get("NINELIVES_STATE") or os.path.expanduser("~/.local/state/ninelives")


def cells(s: str) -> int:
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1
               for c in s)


def wrap(s: str, width: int, most: int) -> list:
    """s in lines of `width` cells (words kept whole), at most `most` lines; the last one cut with …"""
    out, line = [], ""
    for word in s.split():
        if line and cells(line) + 1 + cells(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        out.append(line)
    if len(out) > most:
        out = out[:most - 1] + [cut(" ".join(out[most - 1:]), width)]
    return [cut(x, width) for x in out]


def cut(s: str, width: int) -> str:
    """Cut the end off to fit `width` cells, marked with …"""
    if cells(s) <= width:
        return s
    while s and cells(s) > max(0, width - 1):
        s = s[:-1]
    return s.rstrip() + "…" if width > 0 else ""


# ---- reading and writing the settings ----------------------------------------------------------
def is_on(key: str, conf: str) -> bool:
    """A toggle's state: True while its switch file is missing (the first of its two values)."""
    return not os.path.exists(os.path.join(conf, TOGGLES[key][1]))


def set_on(key: str, conf: str, on: bool) -> None:
    path = os.path.join(conf, TOGGLES[key][1])
    if on:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    else:
        os.makedirs(conf, exist_ok=True)
        open(path, "a").close()


def volume(conf: str) -> int:
    """The tab sounds' volume in percent (sounds-volume; 100 when missing or unreadable)."""
    try:
        with open(os.path.join(conf, "sounds-volume"), encoding="utf-8") as f:
            return max(5, min(100, int(f.read().strip())))
    except (OSError, ValueError):
        return 100


def set_volume(conf: str, pct: int) -> int:
    pct = max(5, min(100, int(pct)))
    os.makedirs(conf, exist_ok=True)
    path = os.path.join(conf, "sounds-volume")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(f"{pct}\n")
    os.replace(path + ".tmp", path)
    return pct


def talk(conf: str) -> str:
    """How much the cat says by itself: on, events only, off (the cat-talk file: events, off)."""
    try:
        with open(os.path.join(conf, "cat-talk"), encoding="utf-8") as f:
            v = f.read().strip()
    except OSError:
        return "on"
    return {"events": "events only", "off": "off"}.get(v, "on")


def set_talk(conf: str, v: str) -> None:
    path = os.path.join(conf, "cat-talk")
    if v == "on":
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return
    os.makedirs(conf, exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(("events" if v.startswith("events") else "off") + "\n")
    os.replace(path + ".tmp", path)


def badges(state: str) -> int:
    try:
        with open(os.path.join(state, "badges"), encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def value(key: str, conf: str, state: str, compact: bool = False) -> str:
    """The row's value as shown; compact: the short form for a narrow window."""
    if key == "volume":
        pct = volume(conf)
        if compact:
            return f"{pct}%"
        full = (pct + 5) // 10
        return "■" * full + "□" * (10 - full) + f" {pct:>3}%"
    if key == "cattalk":
        v = talk(conf)
        return "events" if compact and v == "events only" else v
    if key not in TOGGLES:
        return ""
    on = is_on(key, conf)
    text = TOGGLES[key][2][0 if on else 1]
    if key == "soundset" and not on and IS_MACOS:
        text = "macOS"
    if key == "quests" and on and not compact:
        text += f" · ★{badges(state)}/{QUEST_TOTAL}"
    return text


def stale_notice(conf: str, state: str) -> str:
    """Like `ninelives`: kitty keeps the tab_bar.py it loaded first until it restarts."""
    try:
        with open(os.path.join(state, "tab_bar.running"), encoding="utf-8") as f:
            running = f.readline().strip()
        with open(os.path.join(conf, "tab_bar.py"), "rb") as f:
            installed = hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return ""
    if running and running != installed:
        return "kitty runs an older tab_bar.py: restart kitty to load the installed one"
    return ""


# ---- hearing a change ---------------------------------------------------------------------------
_preview = {"proc": None}


def sound_command(conf: str) -> list:
    """The command that plays the "done" chime at the set volume, as the sidebar would ([] if none)."""
    vol = 40000 * volume(conf) // 100                 # paplay's scale (65536 = full), as tab_bar.py
    classic = os.path.exists(os.path.join(conf, "sounds-classic"))
    if IS_MACOS:
        path = os.path.join(conf, "sounds", "done.wav")
        if classic or not os.path.isfile(path):
            path = os.path.join(MAC_SOUNDS, "Glass.aiff")
        return ["afplay", "-v", f"{(vol / 65536) ** 3:.8f}", path] if os.path.isfile(path) else []
    path = os.path.join(conf, "sounds", "done.oga")
    if classic or not os.path.isfile(path):
        path = os.path.join(CLASSIC_DIR, "complete.oga")
    return ["paplay", f"--volume={vol}", path] if os.path.isfile(path) else []


def preview(conf: str) -> None:
    """Play the chime once at the new setting, unless the sounds are off (or NINELIVES_QUIET: a
    dev or test kitty). A chime still playing is stopped first, so held arrows don't pile up."""
    if os.environ.get("NINELIVES_QUIET") or os.path.exists(os.path.join(conf, "sounds-off")):
        return
    cmd = sound_command(conf)
    if not cmd:
        return
    old = _preview["proc"]
    try:
        if old is not None and old.poll() is None:
            old.kill()
    except Exception:
        pass
    try:
        _preview["proc"] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            start_new_session=True)
    except OSError:
        _preview["proc"] = None


def change(key: str, conf: str, step: int = 1, wrap: bool = False) -> bool:
    """Change a setting one step (toggles flip either way; the volume moves 5, and with wrap goes
    from 100 back to 5). True if something changed."""
    if key == "volume":
        v = volume(conf)
        if wrap and step > 0 and v >= 100:
            new = 5
        elif step > 0:
            new = (v // 5 + 1) * 5
        else:
            new = ((v - 1) // 5) * 5
        new = max(5, min(100, new))
        if new == v:
            return False
        set_volume(conf, new)
        preview(conf)
        return True
    if key == "cattalk":
        i = TALK_VALUES.index(talk(conf))
        n = i + (1 if step > 0 else -1)
        if not wrap and not 0 <= n < len(TALK_VALUES):
            n %= len(TALK_VALUES)
        set_talk(conf, TALK_VALUES[n % len(TALK_VALUES)])
        return True
    if key not in TOGGLES:
        return False
    on = not is_on(key, conf)
    set_on(key, conf, on)
    if (key == "sounds" and on) or key == "soundset":
        preview(conf)
    return True


# ---- kitty ---------------------------------------------------------------------------------------
def kitty(*args) -> str:
    # launch --allow-remote-control hands us a connection as KITTY_LISTEN_ON=fd:N; subprocess would
    # close that fd in the child, so pass it on (as tab-finder.py does)
    listen = os.environ.get("KITTY_LISTEN_ON", "")
    fds = (int(listen[3:]),) if listen.startswith("fd:") and listen[3:].isdigit() else ()
    return subprocess.run(["kitty", "@", *args], capture_output=True, text=True, check=True,
                          pass_fds=fds, timeout=10).stdout


def editors() -> list:
    out = []
    for var in ("VISUAL", "EDITOR"):
        try:
            cmd = shlex.split(os.environ.get(var, ""))
        except ValueError:
            cmd = []
        if cmd:
            out.append(cmd)
    return out + [["nano"], ["vi"]]


def edit_config(conf: str, restore=None) -> int:
    """What Ctrl+Shift+F2 does in plain kitty: kitty.conf in kitty's editor, in a new kitty window.
    Without remote control (run from a shell elsewhere), the editor runs right here instead."""
    if os.environ.get("KITTY_LISTEN_ON"):
        try:
            kitty("action", "edit_config_file")
            return 0
        except (OSError, subprocess.SubprocessError):
            pass
    if restore is not None:
        restore()
    path = os.path.join(conf, "kitty.conf")
    for cmd in editors():
        if shutil.which(cmd[0]):
            try:
                os.execvp(cmd[0], cmd + [path])
                return 0                              # (only reached when execvp is a test's stub)
            except OSError:
                continue
    print(f"No editor found: open {path} in yours.", file=sys.stderr)
    return 1


SHELLS = {"bash", "sh", "zsh", "fish", "dash"}


def _is_panel(argv) -> bool:
    """argv is a settings panel: `python3 …/settings.py [panel]` (with kitty.conf next to it), or
    the window's own command `sh -c 'exec python3 "${KITTY_CONFIG_DIRECTORY…}/settings.py"'`.
    Not `settings.py list`, and not some other program's settings.py."""
    if len(argv) >= 2 and os.path.basename(argv[0]).startswith("python"):
        for i, a in enumerate(argv[1:], 1):
            if os.path.basename(a) == "settings.py":
                return argv[i + 1:] in ([], ["panel"]) and os.path.isfile(
                    os.path.join(os.path.dirname(a), "kitty.conf"))
        return False
    if len(argv) >= 3 and os.path.basename(argv[0]) in SHELLS and argv[1] == "-c":
        return "KITTY_CONFIG_DIRECTORY" in argv[2] and re.search(
            r'/settings\.py"?(\s+panel)?\s*$', argv[2]) is not None
    return False


def other_panels(data, here_only: bool = False) -> list:
    """Window ids of settings panels already open (not this one); here_only: in this one's tab."""
    ids = []
    for osw in data:
        for t in osw.get("tabs", []):
            wins = t.get("windows", [])
            if here_only and not any(w.get("is_self") for w in wins):
                continue
            for w in wins:
                if w.get("is_self"):
                    continue
                # the window's own command only: a shell running `ninelives settings` has the
                # panel in its foreground, and closing that window would close the shell too
                if _is_panel(w.get("cmdline") or []):
                    ids.append(w["id"])
    return ids


def toggle_off_others() -> bool:
    """The key (or the ⚙) toggles: a panel already open in this tab is closed and this one goes
    away; panels left open in other tabs are closed. True: don't open."""
    if not os.environ.get("KITTY_LISTEN_ON"):
        return False
    try:
        data = json.loads(kitty("ls"))
        here = other_panels(data, here_only=True)
        for wid in other_panels(data):
            try:
                kitty("close-window", "--match", f"id:{wid}")
            except (OSError, subprocess.SubprocessError):
                pass
        return bool(here)
    except Exception:
        return False


# ---- drawing ------------------------------------------------------------------------------------
def selectable(i: int) -> bool:
    return 0 <= i < len(ROWS) and ROWS[i] is not None


def move(sel: int, step: int) -> int:
    """The next row up or down, skipping blank lines; wraps around."""
    i = sel
    for _ in range(len(ROWS)):
        i = (i + step) % len(ROWS)
        if selectable(i):
            return i
    return sel


def _row(key: str, conf: str, state: str, chosen: bool, cols: int) -> str:
    avail = max(4, cols - 4)                          # " ❯ " in front, one cell spare at the end
    label = LABELS[key]
    if key in SHORT_LABELS and cells(label) + (0 if key == "edit" else 2 + cells(value(key, conf, state, True))) > avail:
        label = SHORT_LABELS[key]
    if key == "edit":
        text = cut(label, avail)
        return f" {B}❯{R} {B}{text}{R}" if chosen else f"   {text}"
    for compact in (False, True):
        val = value(key, conf, state, compact)
        shown = f"‹ {val} ›" if chosen else val
        if cells(label) + 2 + cells(shown) <= avail:
            break
    else:
        shown = val
        if cells(label) + 2 + cells(shown) > avail:
            label = cut(label, max(1, avail - 2 - cells(shown)))
    gap = max(2, avail - cells(label) - cells(shown))
    muted = val in OFF_VALUES
    if key == "volume" and not compact:
        filled = val.count("■")
        styled = "■" * filled + MUTED + "□" * (10 - filled) + R + val[10:]
        styled = f"‹ {styled} ›" if chosen and shown != val else styled
    else:
        styled = f"{MUTED}{shown}{R}" if muted else shown
    if cells(label) + gap + cells(shown) > avail:
        # a very narrow pane: one plain line cut to fit, so it never wraps (row_at counts lines)
        text = cut(f"{label}  {val}", avail)
        return f" {B}❯{R} {B}{text}{R}" if chosen else f"   {text}"
    if chosen:
        return f" {B}❯{R} {B}{label}{R}{' ' * gap}{styled}"
    return f"   {label}{' ' * gap}{styled}"


def render(conf: str, state: str, sel: int, cols: int, lines: int, header: str = "", notice: str = "") -> str:
    """The whole screen: the title, a notice if any, the rows, the highlighted row's description and
    the keys. The rows start on line TOP, so a click's line says which row it hit (row_at)."""
    title = "NineLives settings"
    top = f" {B}{cut(title, max(1, cols - 2))}{R}"
    room = cols - 2 - cells(title) - 3
    # the kitty version and the config folder, or only the version: never cut in the middle
    shown = next((h for h in (header, header.split(" · ")[0]) if h and cells(h) <= room), "")
    if shown:
        top += f"   {MUTED}{shown}{R}"
    out = ["\x1b[H\x1b[2J", top]
    out.append(f" {AMBER}!{R} {cut(notice, max(4, cols - 4))}" if notice else "")
    for i, key in enumerate(ROWS):
        out.append(_row(key, conf, state, i == sel, min(cols, ROW_MAX)) if key else "")
    width = max(4, cols - 2)
    # the description gets two lines, one in a short window, none in a very short one
    most = max(0, min(2, lines - len(out) - 2))
    desc = wrap(DESCRIPTIONS.get(ROWS[sel] if selectable(sel) else "", ""), width, most) if most else []
    keys_line = next((f for f in FOOTERS if cells(f) <= width), FOOTERS[-1])
    out += [""] * max(1, lines - len(out) - 1 - len(desc))
    out += [f" {MUTED}{line}{R}" for line in desc]
    out.append(f" {MUTED}{cut(keys_line, width)}{R}")
    return "\r\n".join(out[:max(1, lines)])     # never more lines than the window: it would scroll


def row_at(y: int) -> int:
    """The row on terminal line y (1-based), or -1."""
    i = y - TOP
    return i if selectable(i) else -1


# ---- keys -----------------------------------------------------------------------------------------
UP, DOWN, RIGHT, LEFT = ("\x1b[A", "\x1bOA"), ("\x1b[B", "\x1bOB"), ("\x1b[C", "\x1bOC"), ("\x1b[D", "\x1bOD")
KEYS = UP + DOWN + RIGHT + LEFT
MOUSE_RE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
PARTIAL_RE = re.compile(r"\x1b(?:\[[0-9;<?]*|O)?\Z")   # an escape sequence still on its way
ESC_WAIT = 0.05              # how long a lone Esc waits for the rest of an arrow key


def incomplete(chunk: str) -> bool:
    """Does the read end part-way through an escape sequence? A read can stop anywhere, so an
    arrow key can arrive as "\x1b" and then "[A"; reading on keeps it from closing the panel."""
    return bool(PARTIAL_RE.search(chunk))


def read_keys(fd: int) -> str:
    """One read, plus whatever completes an escape sequence it stopped inside (briefly; a lone Esc
    is still Esc)."""
    import select
    chunk = os.read(fd, 1024).decode("utf-8", "ignore")
    while incomplete(chunk) and select.select([fd], [], [], ESC_WAIT)[0]:
        more = os.read(fd, 1024).decode("utf-8", "ignore")
        if not more:
            break
        chunk += more
    return chunk


def keys(chunk: str):
    """Split what one read returned into keys (fast typing, held arrows and mouse reports arrive
    together). A mouse report comes out as ("mouse", button, x, y, pressed)."""
    i = 0
    while i < len(chunk):
        m = MOUSE_RE.match(chunk, i)
        if m:
            yield ("mouse", int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) == "M")
            i = m.end()
            continue
        k = next((k for k in KEYS if chunk.startswith(k, i)), None)
        if k is None and chunk[i] == "\x1b" and i + 1 < len(chunk) and chunk[i + 1] in "[O":
            j = i + 2                                    # some other escape sequence: skip it whole
            while j < len(chunk) and not chunk[j].isalpha() and chunk[j] != "~":
                j += 1
            yield ""
            i = j + 1
            continue
        k = k or chunk[i]
        yield k
        i += len(k)


def handle(key, sel: int):
    """(new selection, command) for a key: None, "quit", or ("change", step, wrap) for the row."""
    if isinstance(key, tuple):
        _, button, _x, y, pressed = key
        if button == 64:
            return move(sel, -1), None
        if button == 65:
            return move(sel, 1), None
        if button == 0 and pressed:
            i = row_at(y)
            if i >= 0:
                return i, ("change", 1, True)
        return sel, None
    if key in UP or key in ("k", "\x10"):
        return move(sel, -1), None
    if key in DOWN or key in ("j", "\x0e"):
        return move(sel, 1), None
    if key in ("\r", "\n", " "):
        return sel, ("change", 1, True)
    if key in RIGHT or key == "l":
        return sel, ("change", 1, False)
    if key in LEFT or key == "h":
        return sel, ("change", -1, False)
    if key in ("\x1b", "q", "\x03", "\x07"):
        return sel, "quit"
    return sel, None


# ---- running it -------------------------------------------------------------------------------------
def listing(conf: str, state: str) -> str:
    rows = [f"{LABELS[k]}: {value(k, conf, state, compact=(k == 'volume'))}" for k in ROWS if k and k != "edit"]
    notice = stale_notice(conf, state)
    return "\n".join(rows + ([notice] if notice else [])) + "\n"


def _header(conf: str) -> str:
    try:
        ver = subprocess.run(["kitty", "--version"], capture_output=True, text=True, timeout=5).stdout.split()[1]
    except Exception:
        ver = ""
    home = os.path.expanduser("~")
    shown = "~" + conf[len(home):] if conf == home or conf.startswith(home + "/") else conf
    return f"kitty {ver} · {shown}" if ver else shown


def panel(conf: str, state: str) -> int:
    import termios
    import tty
    if toggle_off_others():
        return 0
    header = _header(conf)
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setraw(fd)
    out = sys.stdout
    # the alternate screen (run from a shell, the screen comes back as it was), no cursor, clicks
    out.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
    done = []

    def restore():
        if done:
            return
        done.append(1)
        out.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[?1049l")
        out.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    sel = 0
    try:
        while True:
            size = os.get_terminal_size()
            out.write(render(conf, state, sel, size.columns, size.lines, header, stale_notice(conf, state)))
            out.flush()
            for key in keys(read_keys(fd)):
                sel, cmd = handle(key, sel)
                if cmd == "quit":
                    return 0
                if cmd:
                    if ROWS[sel] == "edit":
                        return edit_config(conf, restore)
                    change(ROWS[sel], conf, cmd[1], cmd[2])
    finally:
        restore()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "panel"
    conf, state = conf_dir(), state_dir()
    if mode == "list" or (mode == "panel" and not (sys.stdin.isatty() and sys.stdout.isatty())):
        sys.stdout.write(listing(conf, state))
        return 0
    if mode == "panel":
        return panel(conf, state)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
