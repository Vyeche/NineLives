#!/usr/bin/env python3
"""kitty-tabs.py — read `kitty @ ls` (JSON on stdin) for kitty-relaunch.sh.

    kitty @ ls | python3 scripts/kitty-tabs.py session [SAVED]  a kitty session file that reopens it all
    kitty @ ls | python3 scripts/kitty-tabs.py show [SAVED]     what would reopen, for people (--dry-run)
    kitty @ ls | python3 scripts/kitty-tabs.py refocus    window ids to focus after starting from it
    kitty @ ls | python3 scripts/kitty-tabs.py snapshot   one line per tab: folder US command US name US active
    kitty @ ls | python3 scripts/kitty-tabs.py busy       one line per busy tab: number, why, title
    python3 scripts/kitty-tabs.py sockets                 which kitty to restart: candidate sockets
(US is \x1f: tabs would collapse an empty name field when the shell splits the line.)
SAVED: a session file kitty wrote itself (`kitty @ action save_as_session --save-only FILE`); its
layout states are used where they match a tab's windows, so a zoomed tab (Ctrl+Alt+Z) keeps its splits.

How each window comes back (every pane of a split tab, each in its own folder):
  - Claude with a session id (claude --resume <id>) resumes that session.
  - Claude without one: `claude --continue` (the newest session in that folder), but only when no
    other Claude pane shares the folder (--continue could pick that one's session); otherwise a shell
    with a hint to `claude --resume`.
  - omp continues its last session; anything else becomes a shell in the same folder.
session: splits come back in the same layout and sizes (kitty's layout_state, as save_as_session
  writes it), with the pane you were in focused; a tab without a layout state comes back as one
  window (its active one). Tab names you set (Ctrl+Shift+R; kitty's title_overridden) come back, and
  so does the tab you were on. A folder that no longer exists becomes your home folder (a Claude
  pane without a session id then gets a hint, not `claude --continue`, which would pick home's).
snapshot: the same for each tab's active pane; name is the tab's own name if you renamed it, else
  empty; active is 1 for the tab you were on.
busy: tabs a restart would interrupt (see kitty-relaunch.sh --status).
sockets (no stdin): "here ADDRESS" for the kitty this runs in ($KITTY_LISTEN_ON), then "found ADDRESS"
  for every other kitty of yours with a remote-control socket (one started with --listen-on, or one
  with NineLives' listen_on from kitty.conf). The test and dev kittys' sockets are never offered:
  their own scripts restart them. kitty-relaunch.sh uses the first one that answers.
Tabs from every kitty OS window on the socket are included, in order (they reopen in one window).
"""
import json
import os
import re
import shlex
import sys

SHELLS = {"bash", "sh", "zsh", "fish", "dash"}
AGENTS = {"claude", "omp", "opencode", "codex", "aider", "gemini"}   # idle at their prompt != busy
RUNTIMES = {"node", "bun"}          # an agent when running one (node …/claude), else a command
# programs that just sit open: a restart loses nothing that matters
IDLE_OK = {"vim", "nvim", "vi", "nano", "micro", "hx", "emacs", "less", "more", "man", "most",
           "htop", "top", "btop", "watch", "tmux", "screen", "ssh", "kitten", "cat", "tail"}
SPINNER_RE = re.compile(r"[◐◑◒◓⠁-⣿]")
SHELL_AFTER = "; exec bash"
US = "\x1f"
FOCUS_VAR = "ninelives_focus"       # marks the pane to focus in a split tab (see refocus)
# kitty reads a session file with str.splitlines(), which also breaks lines at these: one inside a
# name, folder or command would split its line, and kitty then opens only an error window
LINE_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"


def _has_break(s: str) -> bool:
    return any(c in LINE_BREAKS for c in s)


def _name(arg: str) -> str:
    return os.path.basename(arg or "")


def _script_index(cmdline):
    """For `node [--flags] script …` the script's index, else None."""
    if not cmdline or _name(cmdline[0]) not in RUNTIMES:
        return None
    return next((i for i, a in enumerate(cmdline[1:], 1) if not a.startswith("-")), None)


def _claude_args(cmdline):
    """The arguments after `claude` (also as `node [--flags] …/claude`), or None."""
    if cmdline and _name(cmdline[0]) == "claude":
        return cmdline[1:]
    i = _script_index(cmdline)
    if i is not None and _name(cmdline[i]) == "claude":
        return cmdline[i + 1:]
    return None


def _session_id(args):
    """The session id from --resume ID, -r ID, --session-id ID (or the --flag=ID forms)."""
    for i, arg in enumerate(args):
        for flag in ("--resume", "-r", "--session-id"):
            if arg.startswith(flag + "=") and len(arg) > len(flag) + 1:
                return arg[len(flag) + 1:]
            if arg == flag and i + 1 < len(args) and not args[i + 1].startswith("-"):
                return args[i + 1]
    return None


def _active_window(tab):
    return next((w for w in tab["windows"] if w.get("is_active")), tab["windows"][0])


def _reopen(w):
    """How to bring one window back: (command, kind)."""
    for p in w.get("foreground_processes") or []:
        c = p.get("cmdline") or []
        args = _claude_args(c)
        if args is not None:
            sid = _session_id(args)
            if sid:
                return (f"claude --resume {shlex.quote(sid)}; echo; "
                        f"echo \"[Claude exited. This is a normal shell now.]\"{SHELL_AFTER}"), "claude-id"
            return "", "claude-new"                   # decided once every pane is known (plan)
        if c and _name(c[0]) == "omp":
            rest = [a for a in c[1:] if a not in ("-c", "--continue")]
            return "omp " + " ".join(shlex.quote(a) for a in rest + ["--continue"]) + SHELL_AFTER, "omp"
    return "exec bash", "shell"


def _leaves(pairs):
    """Group ids in a splits pairs tree ({"one": id | pair, "two": …, "horizontal", "bias"})."""
    if isinstance(pairs, dict):
        return [g for k in ("one", "two") if k in pairs for g in _leaves(pairs[k])]
    return [pairs] if isinstance(pairs, int) else []


def _panes(tab, state=None):
    """The windows to reopen in a tab, and the layout state that arranges them.

    With kitty's layout_state (kitty 0.43+ `kitty @ ls`, or the tab's state from save_as_session,
    which also keeps a zoomed tab's splits): one window per window group, in kitty's order. A group
    is a window plus any overlay on top of it (a search box, the F1 sheet); the window underneath
    comes back. Without a usable state: the active window only, as before splits were restored.
    Returns (state with only those windows, [(window, is_active_pane)]) or (None, [(window, True)])."""
    wins = {w.get("id"): w for w in tab["windows"]}
    active = _active_window(tab)
    state = state or tab.get("layout_state")
    try:
        groups = state["all_windows"]["window_groups"]
        bases = [next(i for i in g["window_ids"] if i in wins) for g in groups]
        gids = [g["id"] for g in groups]
        trees = [state.get("pairs")] + [o.get("pairs") for o in (state.get("other_layouts") or {}).values()]
        if not bases or len(set(bases)) != len(bases) or any(
                t is not None and sorted(_leaves(t)) != sorted(gids) for t in trees):
            raise ValueError("layout state does not match the tab's windows")
    except (KeyError, TypeError, AttributeError, StopIteration, ValueError):
        return None, [(active, True)]
    focus = next((b for g, b in zip(groups, bases) if active.get("id") in g["window_ids"]), bases[0])

    def only_bases(st):
        st = dict(st)
        aw = dict(st["all_windows"])
        aw["window_groups"] = [dict(g, window_ids=[b]) for g, b in zip(aw["window_groups"], bases)] \
            if [g["id"] for g in aw["window_groups"]] == gids else aw["window_groups"]
        st["all_windows"] = aw
        if st.get("other_layouts"):
            st["other_layouts"] = {k: only_bases(v) if isinstance(v, dict) and "all_windows" in v else v
                                   for k, v in st["other_layouts"].items()}
        return st
    return only_bases(state), [(wins[b], b == focus) for b in bases]


def _tab_name(tab, w):
    if "title_overridden" in tab:                       # kitty 0.50+: set by Ctrl+Shift+R
        return tab.get("title", "") if tab["title_overridden"] else ""
    # a kitty without the flag: compare titles
    return tab.get("title", "") if tab.get("title", "") != w.get("title", "") else ""


def _window_ids(state):
    try:
        return frozenset(i for g in state["all_windows"]["window_groups"] for i in g["window_ids"])
    except (KeyError, TypeError):
        return None


def plan(tabs, saved_states=None):
    """What to reopen: one dict per tab with its name, whether it was the active tab, its layout
    and layout state, and its panes (cwd, cmd, kind, id, focus). saved_states: layout states from
    kitty's own save_as_session file, keyed by their window ids (see saved_layout_states)."""
    out = []
    for tab in tabs:
        saved = (saved_states or {}).get(_window_ids(tab.get("layout_state")) or
                                         frozenset(w.get("id") for w in tab["windows"]))
        state, panes = _panes(tab, saved)
        if state is None and saved is not None:
            state, panes = _panes(tab)
        rows = []
        for w, focus in panes:
            cmd, kind = _reopen(w)
            rows.append({"cwd": w["cwd"], "cmd": cmd, "kind": kind, "id": w.get("id"), "focus": focus})
        out.append({"name": _tab_name(tab, _active_window(tab)).replace(US, " ").replace("\n", " "),
                    "active": bool(tab.get("is_active")), "layout": tab.get("layout"),
                    "enabled_layouts": tab.get("enabled_layouts"), "state": state, "panes": rows})
    # Claude without a session id: --continue picks the newest session in the folder, which could
    # be another Claude pane's (with or without an id, in any tab), so only when it's the folder's
    # only Claude pane.
    claude_per_cwd = {}
    for r in (r for t in out for r in t["panes"]):
        if r["kind"].startswith("claude"):
            claude_per_cwd[r["cwd"]] = claude_per_cwd.get(r["cwd"], 0) + 1
    for r in (r for t in out for r in t["panes"]):
        if r["kind"] == "claude-new":
            if claude_per_cwd[r["cwd"]] == 1:
                r["cmd"] = ("claude --continue; echo; "
                            f"echo \"[Claude exited. This is a normal shell now.]\"{SHELL_AFTER}")
            else:
                r["cmd"] = ("echo \"[Several Claude tabs were open in this folder: "
                            f"claude --resume to pick yours.]\"{SHELL_AFTER}")
    return out


def snapshot(tabs):
    """One row per tab, for its active pane: folder US command US name US active."""
    out = []
    for t in plan(tabs):
        r = next(p for p in t["panes"] if p["focus"])
        out.append(US.join((r["cwd"], r["cmd"], t["name"], "1" if t["active"] else "0")))
    return out


def saved_layout_states(text):
    """Layout states from a session file kitty wrote (save_as_session), keyed by their window ids.
    Unlike `kitty @ ls`, these keep a zoomed tab's splits (Ctrl+Alt+Z: the stack layout remembers
    them under other_layouts)."""
    states = {}
    for line in text.splitlines():
        if line.startswith("set_layout_state "):
            try:
                st = json.loads(line.split(" ", 1)[1])
            except ValueError:
                continue
            ids = _window_ids(st)
            if ids:
                states[ids] = st
    return states


def session(tabs, saved_states=None, isdir=os.path.isdir, home=None):
    """A kitty session file that reopens every tab, with its splits, names, active pane and active
    tab. It follows what kitty's own save_as_session writes: `set_layout_state` arranges the windows
    whose `kitty-unserialize-data` ids it names, so the pairs tree and split sizes come back as they
    were. A tab without a usable layout state comes back as one window (its active one)."""
    home = home or os.path.expanduser("~")
    lines, active = [], None
    for i, t in enumerate(plan(tabs, saved_states)):
        # kitty expands $VARS in a tab name ($$ is a literal $)
        name = "".join(" " if c in LINE_BREAKS else c for c in t["name"]).replace("$", "$$")
        lines.append(("new_tab " + name).rstrip())
        if t["layout"]:
            lines.append(f"layout {t['layout']}")
        if t["enabled_layouts"]:
            lines.append("enabled_layouts " + ",".join(t["enabled_layouts"]))
        if t["state"] is not None:
            lines.append("set_layout_state " + json.dumps(t["state"]))
        for r in t["panes"]:
            cmd = r["cmd"]
            if r["cwd"] and isdir(r["cwd"]) and not _has_break(r["cwd"]):
                cwd = r["cwd"]
            else:
                cwd = home
                if r["kind"] == "claude-new":   # --continue in home would pick an unrelated session
                    cmd = ("echo \"[Claude was open in a folder that no longer exists: "
                           f"claude --resume to find its session.]\"{SHELL_AFTER}")
            if _has_break(cmd):                 # e.g. an omp argument with a newline in it
                cmd = f"echo \"[This pane's command could not be brought back.]\"{SHELL_AFTER}"
            parts = ["launch"]
            if t["state"] is not None:
                parts.append(shlex.quote("kitty-unserialize-data=" + json.dumps({"id": r["id"]})))
            if "$" in cwd:          # kitty expands $VARS in launch options: cd in the command instead
                cmd = f"cd -- {shlex.quote(cwd)} 2>/dev/null; {cmd}"
            else:
                parts.append("--cwd=" + shlex.quote(cwd))
            if r["focus"] and len(t["panes"]) > 1:
                parts.append(f"--var={FOCUS_VAR}=1")       # for refocus, after kitty has started
            parts += ["bash", "-lc", shlex.quote(cmd)]
            lines.append(" ".join(parts))
            if r["focus"]:
                lines.append("focus")
        lines.append("")
        if t["active"]:
            active = i
    if active is not None:
        lines.append(f"focus_tab {active}")
    return lines


def refocus(tabs):
    """Run on the new kitty right after it started from the session file: the window ids to focus,
    in order, so every split tab has the pane you were in. With focus_follows_mouse the pane under
    the mouse can take the focus as the new window opens (seen on the hidden test kitty). Each id
    is a pane the session marked (launch --var) that isn't its tab's active pane; the active tab's
    pane comes last, since focusing a window also switches to its tab. Nothing when all is right."""
    def marked(tab):
        return next((w for w in tab["windows"] if (w.get("user_vars") or {}).get(FOCUS_VAR) == "1"), None)
    active_tab = next((t for t in tabs if t.get("is_active")), None)
    out, last = [], None
    for tab in tabs:
        w = marked(tab)
        if w is not None and not w.get("is_active"):
            if tab is active_tab:
                last = w.get("id")
            else:
                out.append(w.get("id"))
    if out and last is None and active_tab is not None:
        last = _active_window(active_tab).get("id")         # back to the tab you were on
    if last is not None:
        out.append(last)
    return [str(i) for i in out]


def show(tabs, saved_states=None):
    lines = []
    for i, t in enumerate(plan(tabs, saved_states), 1):
        many = len(t["panes"]) > 1
        for n, r in enumerate(t["panes"]):
            what = r["cmd"].split(";")[0] if not r["cmd"].startswith("exec bash") else "shell"
            extra = ""
            if n == 0:
                extra += (f'  name "{t["name"]}"' if t["name"] else "") + ("  (active)" if t["active"] else "")
                if many:
                    extra += f"  [{t['layout'] or 'split'}: {len(t['panes'])} panes]"
            if many and r["focus"]:
                extra += "  (active pane)"
            lines.append((f"{i:>3}  " if n == 0 else "     + ") + r["cwd"])
            lines.append(f"       {what}{extra}")
    return lines


def _command(w):
    """A running command a restart would kill, e.g. "make" or "node migrate.js", or ""."""
    for p in w.get("foreground_processes") or []:
        c = p.get("cmdline") or [""]
        name = _name(c[0])
        if name in RUNTIMES:
            i = _script_index(c)
            script = _name(c[i]) if i is not None else ""
            if script in AGENTS:
                continue                    # node [--flags] …/claude idling at its prompt
            return f"{name} {script}".strip()
        if name and name not in SHELLS | AGENTS | IDLE_OK:
            return name
    return ""


def busy(tabs):
    out = []
    for i, tab in enumerate(tabs, 1):
        for w in tab["windows"]:
            states = {r.get("state") for r in w.get("program_status") or []}
            why = ("working" if "working" in states else "needs you" if "blocked" in states
                   else "spinner" if SPINNER_RE.search(w.get("title", "")[:6])
                   else "command" if _command(w) else "")
            if why:
                out.append(f"{i:>3}  {why:<9}  {w.get('title', '')[:50]}")
                break
    return out


# Sockets kitty-relaunch.sh never picks by itself: the hidden test kitty and the dev kitty
# (scripts/test-kitty.sh, scripts/dev-kitty.sh). A restart started from inside them would bring them
# back with your desktop's environment (real config, display and sounds), so only NL_KITTY_SOCKET
# can point the restart at them.
OWN_SOCKETS = {"unix:@ninelives-test-kitty", "unix:@ninelives-dev-kitty"}
CONFIG_SOCKET = "ninelives-kitty-"      # listen_on in config/kitty.conf: $XDG_RUNTIME_DIR/ninelives-kitty-<pid>


def _listen_on(argv):
    """The --listen-on address in a kitty command line, or None."""
    for i, a in enumerate(argv):
        if a == "--listen-on" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--listen-on="):
            return a.split("=", 1)[1]
    return None


def socket_candidates(env, kitty_cmdlines=(), runtime_files=()):
    """[(where, address)]: where is "here" for the kitty this runs in, "found" for others.
    env: the environment; kitty_cmdlines: argv lists of your running kitty processes;
    runtime_files: socket files in $XDG_RUNTIME_DIR named like NineLives' listen_on."""
    out, seen = [], set(OWN_SOCKETS)
    here = env.get("KITTY_LISTEN_ON", "")
    # fd:N is a connection kitty hands one launched program (launch --allow-remote-control), not a socket
    if here.startswith(("unix:", "tcp:")) and here not in seen:
        out.append(("here", here))
        seen.add(here)
    found = [_listen_on(argv) for argv in kitty_cmdlines]
    found += ["unix:" + f for f in sorted(runtime_files)]
    for addr in found:
        if addr and addr.startswith(("unix:", "tcp:")) and addr not in seen:
            out.append(("found", addr))
            seen.add(addr)
    return out


def _running_kitties():
    """argv of each kitty process you own (from /proc; empty where there is no /proc)."""
    out = []
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        try:
            if os.stat(f"/proc/{pid}").st_uid != os.getuid():
                continue
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if argv and os.path.basename(argv[0]) == "kitty" and len(argv) > 1 and not argv[1].startswith("+"):
            out.append(argv)
    return out


def _runtime_sockets(env):
    d = env.get("XDG_RUNTIME_DIR", "")
    if not d:
        return []
    try:
        return [os.path.join(d, n) for n in os.listdir(d) if n.startswith(CONFIG_SOCKET)]
    except OSError:
        return []


def all_tabs(data):
    """Tabs from every kitty OS window, in order. Each OS window has its own active tab; only the one
    in the window you were using (focused, else last focused, else the first) stays "active"."""
    chosen = next((o for o in data if o.get("is_focused")), None) or \
        next((o for o in data if o.get("last_focused")), None) or (data[0] if data else None)
    tabs = []
    for o in data:
        for t in o.get("tabs", []):
            tabs.append(dict(t, is_active=bool(t.get("is_active")) and o is chosen))
    return tabs


def main():
    modes = {"snapshot": snapshot, "show": show, "busy": busy, "session": session, "refocus": refocus}
    args = sys.argv[1:]
    if args == ["sockets"]:
        env = dict(os.environ)
        for where, addr in socket_candidates(env, _running_kitties(), _runtime_sockets(env)):
            print(where, addr)
        return
    if not args or args[0] not in modes or len(args) > (2 if args[0] in ("show", "session") else 1):
        sys.exit(__doc__)
    data = json.load(sys.stdin)
    tabs = all_tabs(data)
    if len(args) == 2:      # kitty's own save_as_session file: layout states, zoomed splits included
        try:
            with open(args[1], encoding="utf-8") as f:
                saved = saved_layout_states(f.read())
        except OSError:
            saved = {}
        out = modes[args[0]](tabs, saved)
    else:
        out = modes[args[0]](tabs)
    for line in out:
        print(line)


if __name__ == "__main__":
    main()
