#!/usr/bin/env python3
"""tab-finder.py — find a kitty tab. Part of NineLives; kitty.conf runs it with remote control.

    tab-finder.py search    a search box over the current tab: type part of a tab's name, folder or
                            number, ↑/↓ to choose, Enter to go there, Esc to close; Tab shows
                            only waiting / working / done tabs  (Ctrl+Shift+Space)
    tab-finder.py waiting   go to the next tab waiting for you (⚠), or failed (✗) if none is waiting
                            (Ctrl+Alt+U)
"""
import json
import os
import re
import subprocess
import sys

SPINNER_RE = re.compile("[⠁-⣿◐-◓]")
LEAD_RE = re.compile(r"^\s*(?:[✳✻✽✶✢·*]|π?\s*[⠁-⣿◐-◓])\s*")   # Claude's ✳, omp/opencode spinners
# Secondary text: palette colour 7, not SGR dim. kitty's dim fades text toward the background, which
# fell to ~3:1 on the light theme; colour 7 is ~10:1 on dark and ~7:1 on light, still a step below
# the foreground.
MUTED = "\x1b[37m"
ICON = {"blocked": "⚠", "error": "✗", "working": "◐", "done": "✓"}
COLOUR = {"blocked": 3, "error": 1, "working": 4, "done": 2}      # palette: follows the theme
HOME = os.path.expanduser("~")


def kitty(*args) -> str:
    # launch --allow-remote-control hands us a connection as KITTY_LISTEN_ON=fd:N; subprocess
    # would close that fd in the child, so pass it on (a background launch has no tty to fall back on)
    listen = os.environ.get("KITTY_LISTEN_ON", "")
    fds = (int(listen[3:]),) if listen.startswith("fd:") and listen[3:].isdigit() else ()
    return subprocess.run(["kitty", "@", *args], capture_output=True, text=True, check=True,
                          pass_fds=fds).stdout


def folder(cwd: str) -> str:
    if cwd == HOME or cwd.startswith(HOME + "/"):
        cwd = "~" + cwd[len(HOME):]
    return "/".join(cwd.rstrip("/").split("/")[-2:]) or "/"


SHELLS = {"bash", "sh", "zsh", "fish", "dash"}


def tab_state(tab, win) -> str:
    """Like the sidebar: kitty's program status, else a spinner in the title, else a command
    running in a plain shell (the sidebar spins for those too)."""
    states = set()
    for w in tab.get("windows", []):
        for rec in w.get("program_status") or []:
            states.add(rec.get("state"))
    for s in ("blocked", "error", "working", "done"):
        if s in states:
            return s
    if states:                         # paused or another state the sidebar shows as is
        return ""
    if SPINNER_RE.search((win.get("title") or tab.get("title") or "")[:8]):
        return "working"
    procs = [os.path.basename((p.get("cmdline") or [""])[0]) for p in win.get("foreground_processes") or []]
    if any(p and p.lstrip("-") not in SHELLS for p in procs):
        return "working"
    return ""


def cells(s: str) -> int:
    import unicodedata
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1
               for c in s)


def tab_name(title: str, cwd: str) -> str:
    """The sidebar's name: a plain shell's title is its folder, so show the folder's name."""
    if title[:1] in ("", "~", "/") or re.match(r"^[\w.-]+@[\w.-]+:", title):
        return cwd.rstrip("/").rsplit("/", 1)[-1] or "/"
    return LEAD_RE.sub("", title, count=1) or title


AGENT_MARK = {"claude": "✳", "omp": "π", "opencode": "oc", "codex": "cx", "gemini": "gm", "aider": "ai",
              "devin": "dv", "cursor-agent": "cu", "goose": "go", "amp": "am"}   # as in tab_bar.py


def agent_mark(win) -> str:
    """The sidebar's agent mark for the window's foreground program (✳ Claude, π omp, …)."""
    for p in win.get("foreground_processes") or []:
        argv = p.get("cmdline") or []
        for a in argv[:1] + (argv[1:] if argv and os.path.basename(argv[0]) in ("node", "bun") else []):
            if "claude-code" in a:
                return AGENT_MARK["claude"]
            mark = AGENT_MARK.get(os.path.basename(a))
            if mark:
                return mark
    return ""


def git_branch(cwd: str) -> str:
    """The folder's git branch if it isn't main/master (as the sidebar shows it), else ""."""
    try:
        d, dev = cwd, os.stat(cwd).st_dev
        for _ in range(40):
            git = os.path.join(d, ".git")
            if os.path.isdir(git) or os.path.isfile(git):
                if os.path.isfile(git):          # a worktree: "gitdir: …"
                    with open(git, encoding="utf-8") as f:
                        gd = f.read().strip().partition("gitdir:")[2].strip()
                    git = gd if os.path.isabs(gd) else os.path.join(d, gd)
                with open(os.path.join(git, "HEAD"), encoding="utf-8") as f:
                    ref = f.read().strip()
                b = ref[16:] if ref.startswith("ref: refs/heads/") else ref[:7]
                return "" if b in ("main", "master") else b
            parent = os.path.dirname(d)
            if parent == d or os.stat(parent).st_dev != dev:
                return ""
            d = parent
    except OSError:
        pass
    return ""


def rows(data) -> list:
    """One dict per tab, every kitty window in order: number (within its window), id, name,
    folder, state, active (the focused window's active tab)."""
    focused = next((w for w in data if w.get("is_focused")), None) or \
        next((w for w in data if w.get("last_focused")), None) or (data[0] if data else None)
    out = []
    for osw in data:
        for i, t in enumerate(osw.get("tabs", [])):
            # leave out this search box itself (an overlay in the current tab: is_self)
            wins = [x for x in t.get("windows", []) if not x.get("is_self")] or t.get("windows", [])
            w = next((x for x in wins if x.get("is_active")), wins[-1] if wins else {})
            mine = any(x.get("is_self") for x in t.get("windows", []))
            title = (w.get("title") if mine else t.get("title")) or w.get("title") or ""
            cwd = w.get("cwd") or ""
            out.append({"n": i + 1, "id": t["id"], "name": tab_name(title, cwd),
                        "folder": folder(cwd), "state": tab_state(t, w), "agent": agent_mark(w),
                        "branch": git_branch(cwd) if cwd else "",
                        "active": bool(t.get("is_active")) and osw is focused})
    return out


def next_waiting(tabs):
    """The next tab after the active one that is waiting for you, else the next one that failed."""
    if not tabs:
        return None
    start = next((i for i, t in enumerate(tabs) if t["active"]), -1)
    order = tabs[start + 1:] + tabs[:start + 1]
    for state in ("blocked", "error"):
        for t in order:
            if t["state"] == state and not t["active"]:
                return t
    return None


# The mode bar: Tab / Shift+Tab switch. (label, states shown; None = every tab)
MODES = (("All", None), ("Waiting", {"blocked", "error"}), ("Working", {"working"}), ("Done", {"done"}))


def _in_order(letters: str, text: str) -> bool:
    """Every letter of `letters` appears in `text` in that order ("mdb" in "migrate database")."""
    it = iter(text)
    return all(c in it for c in letters)


def matches(tabs, query: str, mode: int = 0) -> list:
    """Tabs whose number, name, folder or branch contain every word of the query (any case), in
    the chosen mode (MODES). Name matches come before folder-only matches. When no tab contains
    the words, letters in order still match (a typo-friendly fallback: "mdb" finds "Migrate
    database")."""
    states = MODES[mode][1]
    if states is not None:
        tabs = [t for t in tabs if t["state"] in states]
    words = query.lower().split()
    if not words:
        return list(tabs)
    hit, folder_only = [], []
    for t in tabs:
        name = f"{t['n']} {t['name']}".lower()
        where = f"{t['folder']} {t.get('branch', '')}".lower()
        if all(w in name or w in where for w in words):
            (hit if any(w in name for w in words) else folder_only).append(t)
    if hit or folder_only:
        return hit + folder_only
    joined = "".join(words)
    return [t for t in tabs if _in_order(joined, f"{t['name']} {t['folder']}".lower())]


# ---- the search box ---------------------------------------------------------------------------
def _cut(s: str, width: int, from_start: bool = False) -> str:
    if cells(s) <= width:
        return s
    while s and cells(s) > width - 1:
        s = s[1:] if from_start else s[:-1]
    return "…" + s if from_start else s + "…"


def mode_bar(tabs, mode: int, cols: int) -> str:
    """  All 11   Waiting 2   Working 5   Done 1  — the current mode bold and underlined, the
    others quiet; the waiting count amber while tabs wait (amber means "needs you" everywhere)."""
    parts = []
    for i, (label, states) in enumerate(MODES):
        n = len(tabs) if states is None else sum(t["state"] in states for t in tabs)
        count = f"\x1b[33m{n}\x1b[39m" if label == "Waiting" and n else str(n)
        if i == mode:
            parts.append(f"\x1b[1;4m{label}\x1b[22;24m {count}")
        else:
            parts.append(f"{MUTED}{label}\x1b[39m {count}")
    plain = "   " + "   ".join(f"{l} {len(tabs) if st is None else sum(t['state'] in st for t in tabs)}"
                                 for l, st in MODES)
    if cells(plain) > cols - 1:                    # a narrow split: the current mode only, with a hint
        label, states = MODES[mode]
        n = len(tabs) if states is None else sum(t["state"] in states for t in tabs)
        return "   " + _cut(f"{label} {n}  (Tab: next filter)", max(4, cols - 4))
    return "   " + "   ".join(parts)


def draw(tabs, query, sel, cols, lines, mode: int = 0) -> str:
    """Input on top (it has the focus), the modes under it, the tabs, and the keys in a quiet footer.
    The chosen row gets a ❯ pointer and bold text, so the highlight works in both themes without a
    full-width bar."""
    B, D, R = "\x1b[1m", MUTED, "\x1b[0m"
    caret = "\x1b[7m \x1b[27m"
    field = (f"{_cut(query, max(4, cols - 5), from_start=True)}{caret}" if query
             else f"{caret}{D}{_cut('Search tabs by name, folder or number', max(4, cols - 5))}{R}")
    out = ["\x1b[H\x1b[2J", "", f" {B}❯{R} {field}", mode_bar(tabs, mode, cols), ""]
    found = matches(tabs, query, mode)
    room = max(1, lines - 7)
    first = max(0, min(sel - room + 1, len(found) - room))
    width = max(20, cols - 2)
    for i, t in enumerate(found[first:first + room], first):
        mark = f"\x1b[3{COLOUR[t['state']]}m{ICON[t['state']]}\x1b[39m" if t["state"] else " "
        # the sidebar's agent mark in 2 cells (left out in a very narrow pane, where it can't fit)
        agent = t.get("agent", "") if width >= 24 else None
        lead = 12 if agent is not None else 9                        # cells before the name, plus one
        agent = f"{D}{agent}{R}{' ' * (2 - cells(agent))} " if agent is not None else ""
        # folder, then a branch other than main in magenta (as in the sidebar): "code/api ⌥ fix-parser"
        branch = t.get("branch", "")
        bw = min(cells(branch), max(0, width // 5)) if branch else 0
        for bw in ((bw, 0) if bw else (0,)):         # a branch only where the name keeps 6 cells
            where = _cut(t["folder"], max(8, width // 3 - (bw + 3 if bw else 0)), from_start=True)
            tail_cells = cells(where) + (bw + 3 if bw else 0)
            if not bw or width - lead - tail_cells - 2 >= 6:
                break
        name = _cut(t["name"], max(6, width - lead - tail_cells - 2))
        pad = width - lead - cells(name) - tail_cells
        bpart = f" \x1b[35m⌥ {_cut(branch, bw)}\x1b[39m" if bw else ""
        if i == sel:
            out.append(f" {B}❯{R}{t['n']:>3} {mark} {agent}{B}{name}{R}{' ' * max(1, pad)}{where}{bpart}")
        else:
            out.append(f"  {D}{t['n']:>3}{R} {mark} {agent}{name}{' ' * max(1, pad)}{D}{where}{R}{bpart}")
    if not found:
        out.append(f"   {D}no tab matches{R}" if query or mode == 0 else f"   {D}no {MODES[mode][0].lower()} tabs{R}")
    used = len(out) - 1
    out += [""] * max(0, lines - used - 2)
    # cut the plain text, then colour it: escape codes take no cells, and a cut must not drop the reset
    out.append(" " + D + _cut("↑↓ choose · Enter go · Tab filter · Esc close", max(4, cols - 2)) + R)
    return "\r\n".join(out)


KEYS = ("\x1b[A", "\x1bOA", "\x1b[B", "\x1bOB", "\x1b[Z")      # ↑ ↓ (both forms), Shift+Tab


def keys(chunk: str):
    """Split what one read returned into keys: fast typing or held arrows arrive together."""
    i = 0
    while i < len(chunk):
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


def _is_search_box(argv) -> bool:
    """argv is a search box: `python3 …/tab-finder.py search`, or the window's own command
    `sh -c 'exec python3 "…/tab-finder.py" search'`. Not just any command that mentions both words
    (claude "fix search in tab-finder.py", vim research/tab-finder.py): those windows would close."""
    if len(argv) >= 3 and os.path.basename(argv[0]).startswith("python"):
        return any(os.path.basename(a) == "tab-finder.py" and b == "search" for a, b in zip(argv[1:], argv[2:]))
    if len(argv) >= 3 and os.path.basename(argv[0]) in SHELLS and argv[1] == "-c":
        return re.search(r'tab-finder\.py"?\s+search\s*$', argv[2]) is not None
    return False


def other_search_boxes(data, here_only: bool = False) -> list:
    """Window ids of search boxes already open (not this one); here_only: in this box's own tab."""
    ids = []
    for osw in data:
        for t in osw.get("tabs", []):
            wins = t.get("windows", [])
            if here_only and not any(w.get("is_self") for w in wins):
                continue
            for w in wins:
                if w.get("is_self"):
                    continue
                cmds = [w.get("cmdline") or []] + [p.get("cmdline") or [] for p in w.get("foreground_processes") or []]
                if any(_is_search_box(c) for c in cmds):
                    ids.append(w["id"])
    return ids


def search() -> int:
    import termios
    import tty
    data = json.loads(kitty("ls"))
    # The key (or the sidebar's search row) toggles: with a search box already open in this tab,
    # this one closes it and goes away instead of stacking a second box on top. A box left open in
    # another tab (or kitty window) is closed too, but then this one opens: that one wasn't in view.
    here = other_search_boxes(data, here_only=True)
    for wid in other_search_boxes(data):
        try:
            kitty("close-window", "--match", f"id:{wid}")
        except subprocess.CalledProcessError:
            pass                                        # it closed by itself meanwhile
    if here:
        return 0
    tabs = rows(data)
    query, sel, mode = "", next((i for i, t in enumerate(tabs) if t["active"]), 0), 0
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setraw(fd)
    sys.stdout.write("\x1b[?25l")
    try:
        while True:
            size = os.get_terminal_size()
            found = matches(tabs, query, mode)
            sel = max(0, min(sel, len(found) - 1))
            sys.stdout.write(draw(tabs, query, sel, size.columns, size.lines, mode))
            sys.stdout.flush()
            for ch in keys(os.read(fd, 1024).decode("utf-8", "ignore")):
                found = matches(tabs, query, mode)
                sel = max(0, min(sel, len(found) - 1))
                if ch == "\t":
                    mode, sel = (mode + 1) % len(MODES), 0
                elif ch == "\x1b[Z":
                    mode, sel = (mode - 1) % len(MODES), 0
                elif ch in ("\x1b", "\x03", "\x07"):        # Esc, Ctrl+C, Ctrl+G
                    return 1
                elif ch in ("\r", "\n"):
                    if found:
                        kitty("focus-tab", "--match", f"id:{found[sel]['id']}")
                        return 0
                elif ch in ("\x1b[A", "\x10", "\x1bOA"):     # ↑, Ctrl+P
                    sel -= 1
                elif ch in ("\x1b[B", "\x0e", "\x1bOB"):     # ↓, Ctrl+N
                    sel += 1
                elif ch in ("\x7f", "\x08"):
                    query, sel = query[:-1], 0
                elif ch == "\x15":                           # Ctrl+U clears
                    query, sel = "", 0
                elif ch and ch.isprintable():
                    query, sel = query + ch, 0
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h")


def waiting() -> int:
    t = next_waiting(rows(json.loads(kitty("ls"))))
    if t is None:
        return 1
    kitty("focus-tab", "--match", f"id:{t['id']}")
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "search":
        return search()
    if mode == "waiting":
        return waiting()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
