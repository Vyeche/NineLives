#!/usr/bin/env python3
"""cat-helper.py — the cat, drawn, with a speech bubble: what needs you, then a tip, joke or word of
the day. Part of NineLives. It opens only when you ask (Ctrl+Alt+C, a click on the cat at the end of
"+ New tab", `ninelives cat`) and the same key or click closes it again.

    cat-helper.py [panel]   the cat over the current tab: Enter does what the bubble offers,
                            →/n/Space the next thing to say, ←/p the one before, d "don't suggest
                            this again", Esc or q closes; click a button in the bubble, or the cat
    cat-helper.py say       print what it would say, one line each (no kitty needed)

The cat is drawn (config/cat/, built by scripts/make-cat.py) and shown with kitty's graphics
protocol; it makes no sound. While it is open it looks at your tabs once a second (kitty @ ls, the
way the tab search does): a tab that starts waiting makes it jump and say so, a finished one makes it
hop. "Don't suggest this again" is kept in the state folder (cat-helper-hidden).
"""
import base64
import datetime
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
CAT_DIR = os.path.join(HERE, "cat")
B, R = "\x1b[1m", "\x1b[0m"
MUTED = "\x1b[37m"           # palette colour 7: secondary text that reads in both themes (not SGR dim)
KIND_COLOUR = {"waiting": 3, "error": 1, "done": 2, "badge": 3, "quest": 3,   # as in the sidebar:
               "hello": 4, "tip": 4, "joke": 5, "word": 5}                    # all ≥ 4.5:1 on both themes
TICK = 0.125                 # one frame of a move, as the sidebar cat's
POLL = 1.0                   # seconds between looks at the tabs (only while it is open)
BLINK, FIDGET = 0.22, 0.03   # the dice, rolled once a second: as the sidebar cat's
NIGHT = (23, 6)


def conf_dir() -> str:
    return os.environ.get("KITTY_CONFIG_DIRECTORY") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "kitty")


def state_dir() -> str:
    return os.environ.get("NINELIVES_STATE") or os.path.expanduser("~/.local/state/ninelives")


def cells(s: str) -> int:
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1
               for c in s)


def cut(s: str, width: int) -> str:
    if cells(s) <= width:
        return s
    while s and cells(s) > max(0, width - 1):
        s = s[:-1]
    return s.rstrip() + "…" if width > 0 else ""


def wrap(s: str, width: int, most: int) -> list:
    """s in lines of `width` cells (words kept whole), at most `most`; the last one cut with …"""
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


# ---- what it says ---------------------------------------------------------------------------------
JOKES = (
    "Nine lives, eleven tabs. I'm told the maths works out.",
    "I tried to resume my nap with --resume. Naps don't keep a session id.",
    "Why do I sit at the end of the sidebar? It's warm, and there are buttons.",
    "My favourite layout is stack: mostly me, on top of things.",
    "I asked an agent to fetch. It wrote fetch() instead.",
    "Some cats knock things off tables. I knock tabs into a new order.",
    "An amber block means a tab needs you. An amber cat means dinner. Same urgency.",
    "I'm not asleep. I'm waiting on a long build with my eyes closed.",
    "Scrollback is just a very long tail. I approve.",
    "Every tab comes back after a restart. I like those odds.",
    "If it fits, I sit. A split pane fits.",
    "I only run one git command: git purr.",
)
WORDS = (  # (word, a plain meaning)
    ("overlay", "a window laid over another, like me right now. Close it and what's under it is back."),
    ("scrollback", "the lines that scrolled off the top, kept so you can scroll back to them."),
    ("pane", "one part of a split tab. Each runs its own shell."),
    ("socket", "a meeting point two programs talk through. kitty's remote control listens on one."),
    ("escape code", "invisible text that tells the terminal to do something: a colour, a title, even a picture of me."),
    ("PTY", "a pretend terminal device. Your shell talks to it; kitty sits on the other end."),
    ("foreground process", "the program in front in a terminal: the one your keys go to."),
    ("exit code", "the number a program ends with. 0 means it went well."),
    ("prompt", "the text before your cursor that says the shell is ready."),
    ("shell integration", "small hooks that tell kitty where each prompt and each command's output begins."),
    ("SIGINT", "the \"please stop\" signal Ctrl+C sends to the program in front."),
    ("stderr", "where a program writes its errors, apart from its normal output (stdout)."),
    ("PATH", "the list of folders your shell looks in to find a command."),
    ("session id", "the name of an agent's conversation, so --resume can pick it up again."),
    ("dotfile", "a settings file whose name starts with a dot, so it's hidden by default."),
    ("glob", "a pattern like *.py that matches file names."),
)


def tips(path: str = "") -> list:
    """The prompt tips' pool, read from tips.sh's _kitty_tips=( … ) (not run: sourcing it would
    print a tip)."""
    try:
        with open(path or os.path.join(HERE, "tips.sh"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    m = re.search(r"^_kitty_tips=\(\n(.*?)^\)", text, re.S | re.M)
    if not m:
        return []
    return [s.replace('\\"', '"') for s in re.findall(r'^\s*"((?:[^"\\]|\\.)*)"\s*$', m.group(1), re.M)]


def key_of(kind: str, text: str) -> str:
    """A daily line's name in cat-helper-hidden: its kind and a short hash of its words."""
    return f"{kind}:{hashlib.sha1(text.encode()).hexdigest()[:10]}"


def daily(kind: str, pool, day: int, step: int, hidden) -> int:
    """Today's pick of a pool: the same all day (keyed on the date), a different one tomorrow, never
    one you said not to suggest. -1 when there is none left."""
    left = [i for i, x in enumerate(pool) if key_of(kind, x if isinstance(x, str) else x[0]) not in hidden]
    return left[(day * step) % len(left)] if left else -1


def load_hidden(state: str) -> set:
    try:
        with open(os.path.join(state, "cat-helper-hidden"), encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except OSError:
        return set()


def hide(state: str, key: str) -> None:
    hidden = load_hidden(state) | {key}
    os.makedirs(state, exist_ok=True)
    path = os.path.join(state, "cat-helper-hidden")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write("".join(k + "\n" for k in sorted(hidden)))
    os.replace(path + ".tmp", path)


ESC_RE = re.compile("\x1b\\[[0-9;]*m")


def quests(state: str) -> dict:
    """What tab_bar.py wrote to quests.txt (kitty-quests prints it): {"rank", "earned": n, "total": n,
    "rows": [(mark ✓ ✪ → ·, badge, the date earned or "", how)], "next": (badge, how) or None}"""
    out = {"rank": "", "earned": 0, "total": 0, "rows": [], "next": None}
    try:
        with open(os.path.join(state, "quests.txt"), encoding="utf-8") as f:
            lines = [ESC_RE.sub("", line.rstrip("\n")) for line in f]
    except OSError:
        return out
    m = re.search(r"(\d+)/(\d+)\s+rank:\s*(.+?)\s*$", lines[0]) if lines else None
    if m:
        out.update(earned=int(m.group(1)), total=int(m.group(2)), rank=m.group(3))
    for line in lines:
        if "\x1f" not in line:
            continue
        pre, how = line.split("\x1f")[0], line.split("\x1f")[-1]
        r = re.match(r"^\s*([✓✪→·])\s(.+?)(?:\s{2,}(\S+).*)?$", pre)
        if not r:
            continue
        mark, badge, when = r.group(1), r.group(2).strip(), r.group(3) or ""
        out["rows"].append((mark, badge, when, how))
        if mark == "→":
            out["next"] = (badge, how)
    return out


def _tab_words(t) -> str:
    return f"tab {t['n']} “{t['name']}”"


def _names(ts, most: int = 2) -> str:
    """tab 5 “Write notes”, 8 and 9 (the first by name, then numbers; past `most`: "and 3 more")"""
    rest = [str(t["n"]) for t in ts[1:]]
    if len(rest) > most:
        rest = rest[:most] + [f"{len(rest) - most} more"]
    if not rest:
        return _tab_words(ts[0])
    return _tab_words(ts[0]) + "".join(", " + r for r in rest[:-1]) + " and " + rest[-1]


NUMBER = ("No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine")


def _count(n: int, word: str) -> str:
    return f"{NUMBER[n] if n < len(NUMBER) else n} {word}{'s' if n != 1 else ''}"


def greeting(now: datetime.datetime) -> str:
    h = now.hour
    part = ("Good night" if h < 5 or h >= 22 else "Good morning" if h < 12 else "Good afternoon" if h < 17
            else "Good evening")
    return f"{part}! It's {now.strftime('%A')}, {now.strftime('%B')} {now.day}."


def suggestions(tabs, now: datetime.datetime, state: str, conf: str, hidden=frozenset(), tip_pool=None) -> list:
    """Everything the cat has to say, most important first: tabs waiting for you, tabs that failed,
    tabs that finished (or, with none of those, a hello that says nothing needs you), a badge earned
    today, today's quest; then the day's own lines (a tip, a joke, a word), each the same all day. Each is a dict: kind, key,
    title, text, action (("focus", tab id), ("help",) or None) and its button's words."""
    out = []
    others = [t for t in tabs if not t.get("active")]
    here = next((t for t in tabs if t.get("active")), None)
    for state_name, kind, title in (("blocked", "waiting", "Needs you"), ("error", "error", "Error")):
        ts = [t for t in tabs if t.get("state") == state_name]
        ts.sort(key=lambda t: t is here)              # another tab first: this one is under the cat
        if not ts:
            continue
        t = ts[0]
        who = "This tab" if t is here else f"Tab {t['n']}"
        if kind == "waiting":
            text = (f"{who} “{t['name']}” is waiting for you." if len(ts) == 1 else
                    f"{_count(len(ts), 'tab')} are waiting for you. First: {who.lower()} “{t['name']}”.")
        else:
            text = (f"{who} “{t['name']}” stopped with an error." if len(ts) == 1 else
                    f"{_count(len(ts), 'tab')} stopped with an error. First: {who.lower()} “{t['name']}”.")
        text += " Go there?" if t is not here else " Have a look?"
        out.append({"kind": kind, "key": f"{kind}:{t['id']}", "title": title, "text": text,
                    "action": ("focus", t["id"]), "button": "Go there", "ids": [x["id"] for x in ts]})
    done = [t for t in others if t.get("state") == "done"]
    if done:
        t = done[0]
        text = (f"Tab {t['n']} “{t['name']}” finished. Go there?" if len(done) == 1 else
                f"{_count(len(done), 'tab')} finished: {_names(done)}. Go to tab {t['n']}?")
        out.append({"kind": "done", "key": f"done:{t['id']}", "title": "Finished", "text": text,
                    "action": ("focus", t["id"]), "button": "Go there", "ids": [x["id"] for x in done]})
    day = now.date().toordinal()
    if not any(s["kind"] in ("waiting", "error", "done") for s in out):
        working = sum(1 for t in tabs if t.get("state") == "working")
        text = greeting(now) + " Nothing needs you right now."
        if working:
            text += f" {_count(working, 'tab')} {'is' if working == 1 else 'are'} working."
        out.append({"kind": "hello", "key": "hello", "title": "Hello", "text": text, "action": None})
    if not os.path.exists(os.path.join(conf, "quests-off")):
        q = quests(state)
        today = now.date().isoformat()
        for mark, badge, when, how in q["rows"]:
            k = f"badge:{badge}:{when}"
            if mark in "✓✪" and when == today and k not in hidden:
                out.append({"kind": "badge", "key": k, "title": "Badge", "action": ("help",), "button": "All shortcuts",
                            "text": f"You earned the {badge} badge today: ★ {q['earned']} of {q['total']}"
                                    + (f", rank {q['rank']}." if q["rank"] else ".")})
        if q["next"] and f"quest:{q['next'][0]}" not in hidden:
            badge, how = q["next"]
            out.append({"kind": "quest", "key": f"quest:{badge}", "title": "Today's quest", "action": ("help",),
                        "button": "All shortcuts", "text": f"{how.rstrip('.')}. Use it once to earn the {badge} badge."})
    pool = tips() if tip_pool is None else tip_pool
    for kind, items, step, title in (("tip", pool, 5, "Tip of the day"), ("joke", JOKES, 7, "Joke of the day"),
                                     ("word", WORDS, 3, "Word of the day")):
        i = daily(kind, items, day, step, hidden) if items else -1
        if i < 0:
            continue
        x = items[i]
        text = x if isinstance(x, str) else f"{x[0]}: {x[1]}"
        out.append({"kind": kind, "key": key_of(kind, x if isinstance(x, str) else x[0]), "title": title,
                    "text": text, "action": None, "hideable": True})
    for s in out:
        s.setdefault("hideable", s["kind"] in ("badge", "quest"))
    return out


# ---- the tabs (through tab-finder.py, which the search box uses) ------------------------------------
def _load_finder():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ninelives_tab_finder", os.path.join(HERE, "tab-finder.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_finder = _load_finder()


def kitty(*args) -> str:
    listen = os.environ.get("KITTY_LISTEN_ON", "")
    fds = (int(listen[3:]),) if listen.startswith("fd:") and listen[3:].isdigit() else ()
    return subprocess.run(["kitty", "@", *args], capture_output=True, text=True, check=True,
                          pass_fds=fds, timeout=10).stdout


def read_tabs():
    """(the tabs as tab-finder.py's rows, kitty @ ls's data), or ([], None) without remote control."""
    if not os.environ.get("KITTY_LISTEN_ON") or _finder is None:
        return [], None
    try:
        data = json.loads(kitty("ls"))
        return own_tab_state(_finder.rows(data), data), data
    except Exception:
        return [], None


def own_tab_state(rows, data):
    """The tab the helper runs in is described without it: run from a shell (`ninelives cat`), the
    helper is that shell's foreground program, which would make the tab count as working."""
    for osw in data or []:
        for t in osw.get("tabs", []):
            wins = t.get("windows", [])
            if not any(w.get("is_self") for w in wins):
                continue
            others = [w for w in wins if not w.get("is_self")]
            w = next((x for x in others if x.get("is_active")), others[-1] if others else {})
            state = _finder.tab_state(dict(t, windows=others), w)
            for r in rows:
                if r["id"] == t["id"]:
                    r["state"] = state
    return rows


SHELLS = {"bash", "sh", "zsh", "fish", "dash"}


def _is_helper(argv) -> bool:
    """argv is a helper's own command: `python3 …/cat-helper.py [panel]` (with kitty.conf next to
    it) or `sh -c 'exec python3 "${KITTY_CONFIG_DIRECTORY…}/cat-helper.py"'`. Not `say`."""
    if len(argv) >= 2 and os.path.basename(argv[0]).startswith("python"):
        for i, a in enumerate(argv[1:], 1):
            if os.path.basename(a) == "cat-helper.py":
                return argv[i + 1:] in ([], ["panel"]) and os.path.isfile(
                    os.path.join(os.path.dirname(a), "kitty.conf"))
        return False
    if len(argv) >= 3 and os.path.basename(argv[0]) in SHELLS and argv[1] == "-c":
        return "KITTY_CONFIG_DIRECTORY" in argv[2] and re.search(
            r'/cat-helper\.py"?(\s+panel)?\s*$', argv[2]) is not None
    return False


def other_helpers(data, here_only: bool = False) -> list:
    """Window ids of helpers already open (not this one); here_only: in this one's tab. Only a
    window's own command counts: a shell running `ninelives cat` must not be closed with it."""
    ids = []
    for osw in data or []:
        for t in osw.get("tabs", []):
            wins = t.get("windows", [])
            if here_only and not any(w.get("is_self") for w in wins):
                continue
            ids += [w["id"] for w in wins if not w.get("is_self") and _is_helper(w.get("cmdline") or [])]
    return ids


def toggle_off_others(data) -> bool:
    """The key (or a click on the sidebar's cat) toggles: a helper open in this tab is closed and
    this one goes away; one left open in another tab is closed. True: don't open."""
    if data is None:
        return False
    here = other_helpers(data, here_only=True)
    for wid in other_helpers(data):
        try:
            kitty("close-window", "--match", f"id:{wid}")
        except (OSError, subprocess.SubprocessError):
            pass
    return bool(here)


# ---- the picture: kitty's graphics protocol -------------------------------------------------------------
FRAMES = ("idle", "blink", "wink", "ear", "tail-left", "tail-right", "look-left", "look-right", "nod",
          "hop-low", "hop", "wave", "surprised", "happy", "sleepy")
SIZES = (96, 192)            # the shipped frames (px); the one nearest the box is shown, kitty scales it
PLACEMENT = 7                # our one placement: a new frame replaces the old one in place
CHUNK = 4096                 # base64 bytes per escape code (the protocol's limit)
# moves: (frame, ticks) in a row, then back to the resting frame
MOVES = {
    "blink": (("blink", 1),),
    "wink": (("wink", 5),),
    "ear": (("ear", 2), ("idle", 2), ("ear", 2)),
    "tail": (("tail-left", 2), ("tail-right", 2), ("tail-left", 2), ("tail-right", 2)),
    "look-left": (("look-left", 8),),
    "look-right": (("look-right", 8),),
    "nod": (("nod", 2),),
    "hop": (("hop-low", 1), ("hop", 2), ("hop-low", 1), ("wave", 3), ("happy", 1), ("wave", 3)),
    "surprise": (("surprised", 6),),
    "cheer": (("hop-low", 1), ("hop", 3), ("hop-low", 1), ("happy", 4)),
}
FIDGETS = ("wink", "ear", "tail", "look-left", "look-right")


def image_id(frame: str, size: int) -> int:
    return 1 + SIZES.index(size) * 100 + FRAMES.index(frame)


def graphics(control: str, data: bytes = b"") -> str:
    """One graphics command; data (a PNG) goes base64 in chunks of at most CHUNK bytes, m=1 on every
    chunk but the last. q=2: kitty answers nothing (an answer would arrive as keys)."""
    control = f"{control},q=2"
    if not data:
        return f"\x1b_G{control}\x1b\\"
    b64 = base64.standard_b64encode(data).decode("ascii")
    parts = [b64[i:i + CHUNK] for i in range(0, len(b64), CHUNK)]
    out = []
    for i, part in enumerate(parts):
        more = 1 if i < len(parts) - 1 else 0
        out.append(f"\x1b_G{control + ',' if i == 0 else ''}m={more};{part}\x1b\\")
    return "".join(out)


def transmit(frame: str, size: int, cat_dir: str = CAT_DIR) -> str:
    with open(os.path.join(cat_dir, str(size), frame + ".png"), "rb") as f:
        return graphics(f"a=t,f=100,i={image_id(frame, size)}", f.read())


def place(frame: str, size: int, rows: int) -> str:
    """At the cursor, `rows` tall (kitty works out the width), the cursor left where it is."""
    return graphics(f"a=p,i={image_id(frame, size)},p={PLACEMENT},r={rows},C=1")


def unplace(frame: str, size: int) -> str:
    """Take a frame off the screen, keeping its data (lower-case d) for the next time it shows."""
    return graphics(f"a=d,d=i,i={image_id(frame, size)},p={PLACEMENT}")


# ---- layout --------------------------------------------------------------------------------------------
BUBBLE_MAX = 54              # the bubble's width at most (cells, border included)
BUBBLE_MIN = 26
TEXT_LINES = 4


def layout(cols: int, lines: int, cell_w: int, cell_h: int) -> dict:
    """Where things go: the cat (top-left cell, rows, cols, which size of frames), the bubble (left
    column, width) and the footer line. Side by side when the window is wide enough, the cat above
    the bubble when it is tall enough, else the bubble alone. Lines and columns count from 1."""
    cell_w, cell_h = max(1, cell_w), max(1, cell_h)
    # 10 lines tall at the usual cell size (200 px); with big cells (a big font, a 2x screen) at
    # least 6, which kitty scales the 192 px frames up to (a little soft, not small)
    rows = max(4, min(10, (lines - 2) // 2, max(6, 200 // cell_h)))
    cat_cols = -(-rows * cell_h // cell_w)
    size = SIZES[0] if rows * cell_h <= 120 else SIZES[-1]
    out = {"cat": None, "size": size, "footer": lines}
    # the bubble starts in the picture's empty right edge (no pose reaches past 94 % of it: the
    # tail swung right is the farthest), so its tail reaches close to the cat's cheek
    tuck = int(cat_cols * 0.05)
    side = cols >= cat_cols - tuck + BUBBLE_MIN + 2 and lines >= rows + 2
    if side:
        width = min(BUBBLE_MAX, cols - (cat_cols - tuck) - 2)
        left = max(1, (cols - (cat_cols - tuck + width)) // 2 + 1)
        out.update(cat=(left, rows, cat_cols), bubble_col=left + cat_cols - tuck, width=width, mode="side")
    else:
        width = max(10, min(BUBBLE_MAX, cols - 2))
        out.update(bubble_col=max(1, (cols - width) // 2 + 1), width=width, mode="alone")
        rows = min(rows, (cols - 2) * cell_w // cell_h)          # as wide as the window at most
        cat_cols = -(-rows * cell_h // cell_w)
        if rows >= 4 and lines >= rows + 10:
            out.update(cat=(max(1, (cols - cat_cols) // 2 + 1), rows, cat_cols), mode="stacked",
                       size=SIZES[0] if rows * cell_h <= 120 else SIZES[-1])
    return out


def bubble(item, i: int, n: int, width: int, notice: str = "") -> tuple:
    """The bubble's lines (with colour) and its buttons: [(line index, first col, last col, command)]
    (cols counted from the bubble's left edge, 0-based)."""
    inner = width - 4
    kind = item["kind"]
    col = f"\x1b[3{KIND_COLOUR.get(kind, 4)}m"
    count = f" {i + 1}/{n} " if n > 1 else ""
    title = cut(item["title"], max(1, inner - cells(count) - 2))
    top = f"╭─ {B}{col}{title}{R}{MUTED} " + "─" * max(0, width - 5 - cells(title) - cells(count) - 1) \
        + f"{count}─╮{R}"
    top = f"{MUTED}{top}"
    body = wrap(item["text"], inner, TEXT_LINES)
    if notice:
        body += ["", *(f"{MUTED}{x}{R}" for x in wrap(notice, inner, 2))]
    out = [top] + [f"{MUTED}│{R} {x}{' ' * (inner - cells(ESC_RE.sub('', x)))} {MUTED}│{R}" for x in body]
    # buttons: the offered action (reverse video), next, close
    buttons = []
    if item.get("action"):
        buttons.append((f" {item.get('button', 'Go')} ⏎ ", "do", True))
    buttons.append(("Next ›" if n > 1 else "", "next", False))
    buttons.append(("Close ×", "quit", False))
    line, plain, at, regions = "", "", 2, []
    for words, cmd, primary in buttons:
        if not words:
            continue
        gap = 2 if plain else 0
        if cells(plain) + gap + cells(words) > inner:
            continue
        line += " " * gap + (f"\x1b[7m{words}\x1b[27m" if primary else words)
        regions.append((len(out) + 1, at + cells(plain) + gap, at + cells(plain) + gap + cells(words) - 1, cmd))
        plain += " " * gap + words
    out.append(f"{MUTED}│{R}{' ' * (inner + 2)}{MUTED}│{R}")
    out.append(f"{MUTED}│{R} {line}{' ' * (inner - cells(plain))} {MUTED}│{R}")
    out.append(f"{MUTED}╰{'─' * (width - 2)}╯{R}")
    return out, regions


FOOTERS = ("Enter do it · ←→ more · d don't suggest this one · Esc close",
           "Enter · ←→ more · d hide · Esc close", "←→ · Esc close")


def screen(items, sel: int, cols: int, lines: int, lay: dict, notice: str = "") -> tuple:
    """The text of every line (1-based dict), where the cat goes (col, row, rows), and the click
    regions: [(row, first col, last col, command)] on the screen (1-based)."""
    item = items[sel]
    width = lay["width"]
    bl, regions = bubble(item, sel, len(items), width, notice)
    canvas = {}
    regions_out = []
    cat = None
    tail_row = None
    if lay["mode"] == "side":
        left, rows, cat_cols = lay["cat"]
        h = max(rows, len(bl))
        top = max(1, (lines - 1 - h) // 2 + 1)
        cat_top = min(top + max(0, (len(bl) - rows) // 2), lines - rows)
        b_top = top + max(0, (rows - len(bl)) // 3)
        cat = (left, cat_top, rows, cat_cols)
        tail_row = min(b_top + len(bl) - 2, max(b_top + 1, cat_top + rows * 2 // 5))   # its cheek
    elif lay["mode"] == "stacked":
        left, rows, cat_cols = lay["cat"]
        top = max(1, (lines - 1 - rows - 1 - len(bl)) // 2 + 1)
        cat = (left, top, rows, cat_cols)
        b_top = top + rows + 1
    else:
        b_top = max(1, (lines - 1 - len(bl)) // 2 + 1)
    bcol = lay["bubble_col"]
    for i, text in enumerate(bl):
        row = b_top + i
        if row >= lines:
            break
        pre = " " * (bcol - 1)
        if row == tail_row:                 # the bubble's tail, pointing at the cat
            pre = " " * (bcol - 3) + f"{MUTED}◂─{R}"
            text = f"{MUTED}┤{R}" + text[len(f"{MUTED}│{R}"):]
        canvas[row] = pre + text
    for line_i, c0, c1, cmd in regions:
        regions_out.append((b_top + line_i, bcol + c0, bcol + c1, cmd))
    if cat:
        regions_out.append(("cat", cat))
    words = next((f for f in FOOTERS if cells(f) <= cols - 2), FOOTERS[-1])
    if item.get("hideable") is False:
        words = words.replace(" · d don't suggest this one", "").replace(" · d hide", "")
    if not item.get("action"):
        words = words.replace("Enter do it · ", "").replace("Enter · ", "")
    canvas[lines] = f" {MUTED}{cut(words, max(1, cols - 2))}{R}"
    return canvas, cat, regions_out


def hit(regions, x: int, y: int):
    """The command a click at column x, line y is on (or None)."""
    for r in regions:
        if r[0] == "cat":
            left, top, rows, cat_cols = r[1]
            if left <= x < left + cat_cols and top <= y < top + rows:
                return "pet"
        elif r[0] == y and r[1] <= x <= r[2]:
            return r[3]
    return None


# ---- keys -------------------------------------------------------------------------------------------------
UP, DOWN, RIGHT, LEFT = ("\x1b[A", "\x1bOA"), ("\x1b[B", "\x1bOB"), ("\x1b[C", "\x1bOC"), ("\x1b[D", "\x1bOD")
ARROWS = UP + DOWN + RIGHT + LEFT
MOUSE_RE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
APC_RE = re.compile(r"\x1b_.*?(?:\x1b\\|\Z)", re.S)      # a graphics answer: never a key
PARTIAL_RE = re.compile(r"\x1b(?:\[[0-9;<?]*|O|_[^\x1b]*)?\Z")


def keys(chunk: str):
    """Split one read into keys; mouse reports come out as ("mouse", button, x, y, pressed)."""
    chunk = APC_RE.sub("", chunk)
    i = 0
    while i < len(chunk):
        m = MOUSE_RE.match(chunk, i)
        if m:
            yield ("mouse", int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) == "M")
            i = m.end()
            continue
        k = next((k for k in ARROWS if chunk.startswith(k, i)), None)
        if k is None and chunk[i] == "\x1b" and i + 1 < len(chunk) and chunk[i + 1] in "[O":
            j = i + 2
            while j < len(chunk) and not chunk[j].isalpha() and chunk[j] != "~":
                j += 1
            yield ""
            i = j + 1
            continue
        k = k or chunk[i]
        yield k
        i += len(k)


def command(key, regions=()):
    """A key or click → "do", "next", "prev", "hide", "quit", "pet" or None."""
    if isinstance(key, tuple):
        _, button, x, y, pressed = key
        if button == 64:
            return "prev"
        if button == 65:
            return "next"
        if button == 0 and pressed:
            return hit(regions, x, y)
        return None
    if key in ("\r", "\n"):
        return "do"
    if key in RIGHT or key in DOWN or key in ("n", " ", "l", "j", "\t"):
        return "next"
    if key in LEFT or key in UP or key in ("p", "h", "k", "\x7f"):
        return "prev"
    if key == "d":
        return "hide"
    if key in ("\x1b", "q", "\x03", "\x07"):
        return "quit"
    return None


# ---- the helper ---------------------------------------------------------------------------------------------
class Helper:
    """The open helper: what it says, which frame shows, the moves playing. `out` is written to,
    `now` and `rng` can be pinned (tests)."""

    def __init__(self, out, conf: str, state: str, now=None, rng=None, cat_dir: str = CAT_DIR):
        self.out, self.conf, self.state, self.cat_dir = out, conf, state, cat_dir
        self.now = now or datetime.datetime.now
        self.rng = rng or random.Random()
        self.tabs, self.items, self.sel = [], [], 0
        self.seen = None             # (waiting ids, done ids, error ids) at the last look
        self.queue = []              # frames still to show: [(frame, ticks left)]
        self.shown = None            # (frame, size) on screen
        self.sent = set()            # image ids kitty has
        self.cat = None              # (col, row, rows, cols)
        self.regions = []
        self.notice = ""
        self.size = (80, 24, 10, 20)

    # what to say
    def refresh(self, tabs) -> bool:
        """New tab rows: rebuild what to say, keep showing the same thing (or jump to a tab that
        just started waiting), and react (surprise for a new waiting tab, a hop for a finish).
        True when the bubble changed."""
        self.tabs = tabs
        old = self.items[self.sel]["key"] if self.items else None
        before = [(s["key"], s["text"]) for s in self.items]
        self.items = suggestions(tabs, self.now(), self.state, self.conf, load_hidden(self.state))
        waiting = {t["id"] for t in tabs if t.get("state") == "blocked"}
        done = {t["id"] for t in tabs if t.get("state") == "done"}
        error = {t["id"] for t in tabs if t.get("state") == "error"}
        keys_now = [s["key"] for s in self.items]
        # stay on what it was saying (the list may have grown in front of it); only a tab that just
        # started waiting moves the bubble
        self.sel = keys_now.index(old) if old in keys_now else min(self.sel, len(self.items) - 1)
        if self.seen is not None and waiting - self.seen[0]:
            self.play("surprise")
            self.sel = next((i for i, s in enumerate(self.items) if s["kind"] == "waiting"), self.sel)
        elif self.seen is not None and done - self.seen[1]:
            self.play("hop")
        elif self.seen is not None and error - self.seen[2]:
            self.play("ear")
        if self.seen is None:                          # just opened: greet with the news
            kinds = [s["kind"] for s in self.items]
            self.play(next((m for k, m in (("waiting", "surprise"), ("error", "ear"), ("done", "hop"),
                                           ("badge", "cheer")) if k in kinds), "nod"))
        self.seen = (waiting, done, error)
        return before != [(s["key"], s["text"]) for s in self.items]

    def rest(self) -> str:
        """The frame between moves: asleep at night when nothing needs you, else sitting."""
        h = self.now().hour
        night = h >= NIGHT[0] or h < NIGHT[1]
        quiet = not any(t.get("state") in ("blocked", "error") for t in self.tabs)
        return "sleepy" if night and quiet else "idle"

    def play(self, move: str) -> None:
        self.queue = [list(step) for step in MOVES[move]]

    def roll(self) -> None:
        """Once a second: often a blink, now and then a fidget (never asleep, never over a move)."""
        if self.queue or self.rest() == "sleepy":
            return
        r = self.rng.random()
        if r < BLINK:
            self.play("blink")
        elif r < BLINK + FIDGET:
            self.play(self.rng.choice(FIDGETS))

    def frame(self) -> str:
        return self.queue[0][0] if self.queue else self.rest()

    def step(self) -> None:
        """One tick of the move playing."""
        if self.queue:
            self.queue[0][1] -= 1
            if self.queue[0][1] <= 0:
                self.queue.pop(0)

    # drawing
    def draw_cat(self, force: bool = False) -> None:
        """Show the current frame: the new one placed, then the old one taken off, in one write so
        kitty never draws the gap. Nothing is written when the frame is the one on screen."""
        if self.cat is None:
            if self.shown:
                self.out.write(unplace(*self.shown))
                self.shown = None
            return
        col, row, rows, _cols = self.cat
        size = self.lay["size"]
        want = (self.frame(), size)
        if want == self.shown and not force:
            return
        s = ""
        if image_id(*want) not in self.sent:
            try:
                s += transmit(*want, cat_dir=self.cat_dir)
            except OSError:
                return                                # a frame missing: the one on screen stays
            self.sent.add(image_id(*want))
        s += f"\x1b7\x1b[{row};{col}H" + place(want[0], size, rows) + "\x1b8"
        if self.shown and self.shown != want:
            s += unplace(*self.shown)
        self.shown = want
        self.out.write(s)

    def draw(self) -> None:
        """Everything: every line rewritten in place (never \x1b[2J: it would also free the cat's
        frames kitty keeps), then the cat."""
        cols, lines, cw, ch = self.size
        self.lay = layout(cols, lines, cw, ch)
        if self.lay["cat"] and not os.path.isfile(os.path.join(self.cat_dir, str(self.lay["size"]), "idle.png")):
            self.lay.update(cat=None, mode="alone")   # no frames (a partial install): the bubble alone
        if not self.items:
            self.items = [{"kind": "hello", "key": "hello", "title": "Hello", "action": None,
                           "text": greeting(self.now()), "hideable": False}]
        canvas, cat, self.regions = screen(self.items, self.sel, cols, lines, self.lay, self.notice)
        if cat != self.cat and self.shown:
            self.out.write(unplace(*self.shown))
            self.shown = None
        self.cat = cat
        self.out.write("".join(f"\x1b[{y};1H{canvas.get(y, '')}\x1b[K" for y in range(1, lines + 1)))
        self.draw_cat(force=True)
        self.note()

    def note(self) -> None:
        """cat-helper.txt in the state folder: where the cat is drawn and what the bubble is about
        (its kind and key, never the words), for check.sh."""
        try:
            cols, lines, cw, ch = self.size
            text = f"size: {cols} {lines} {cw} {ch}\nmode: {self.lay['mode']}\n"
            if self.cat:
                col, row, rows, cat_cols = self.cat
                text += f"cat: {col} {row} {cat_cols} {rows} {self.lay['size']}\n"
            item = self.items[self.sel]
            text += f"showing: {self.sel + 1}/{len(self.items)} {item['kind']} {item['key'] if item['kind'] in ('waiting', 'error', 'done', 'hello') else ''}\n"
            os.makedirs(self.state, exist_ok=True)
            path = os.path.join(self.state, "cat-helper.txt")
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(path + ".tmp", path)
        except Exception:
            pass

    # what a key does
    def act(self, cmd) -> str:
        """Run a command; returns "quit", "focus:<id>", "help" or "" (keep going)."""
        self.notice = ""
        if cmd == "quit":
            return "quit"
        n = len(self.items)
        if cmd in ("next", "pet"):
            self.sel = (self.sel + 1) % n
            self.play("wink" if cmd == "pet" else "nod")
        elif cmd == "prev":
            self.sel = (self.sel - 1) % n
            self.play("nod")
        elif cmd == "hide":
            item = self.items[self.sel]
            if not item.get("hideable"):
                self.notice = "This one is about your tabs, so it stays."
                return ""
            hide(self.state, item["key"])
            self.items = suggestions(self.tabs, self.now(), self.state, self.conf, load_hidden(self.state))
            self.sel = min(self.sel, len(self.items) - 1)
            self.notice = "Got it: I won't suggest that one again."
            self.play("nod")
        elif cmd == "do":
            action = self.items[self.sel].get("action")
            if not action:
                return self.act("next")
            if action[0] == "focus":
                return f"focus:{action[1]}"
            return "help"
        return ""


def _winsize(fd: int) -> tuple:
    """(columns, lines, cell width, cell height) in px from TIOCGWINSZ (kitty fills in the pixels)."""
    import fcntl
    import struct
    import termios
    try:
        rows, cols, xp, yp = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
    except OSError:
        size = os.get_terminal_size()
        return size.columns, size.lines, 10, 20
    return cols, rows, (xp // cols if xp and cols else 10), (yp // rows if yp and rows else 20)


def panel(conf: str, state: str) -> int:
    import select
    import signal
    import termios
    import tty
    tabs, data = read_tabs()
    if toggle_off_others(data):
        return 0
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setraw(fd)
    out = sys.stdout
    # the alternate screen (from a shell, the screen comes back as it was), no cursor, clicks
    out.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
    h = Helper(out, conf, state)
    resized = [True]
    wake_r, wake_w = os.pipe()                       # a resize wakes the wait at once
    os.set_blocking(wake_w, False)

    def on_resize(*_):
        resized[0] = True
        try:
            os.write(wake_w, b"x")
        except OSError:
            pass
    signal.signal(signal.SIGWINCH, on_resize)
    done = []

    def restore():
        if done:
            return
        done.append(1)
        out.write(graphics("a=d,d=A") + "\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[?1049l")
        out.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    result = ""
    try:
        h.refresh(tabs)
        next_poll = next_roll = time.monotonic() + POLL
        while True:
            if resized[0]:
                resized[0] = False
                h.size = _winsize(fd)
                h.draw()
            else:
                h.draw_cat()
            out.flush()
            now = time.monotonic()
            wait = min(next_poll, next_roll) - now
            if h.queue:
                wait = min(wait, TICK)
            ready = select.select([fd, wake_r], [], [], max(0.0, wait))[0]
            if wake_r in ready:
                os.read(wake_r, 64)
                continue
            if ready:
                chunk = os.read(fd, 4096).decode("utf-8", "ignore")
                while PARTIAL_RE.search(chunk) and select.select([fd], [], [], 0.05)[0]:
                    more = os.read(fd, 4096).decode("utf-8", "ignore")
                    if not more:
                        break
                    chunk += more
                for k in keys(chunk):
                    result = h.act(command(k, h.regions))
                    if result:
                        break
                    if k:
                        h.draw()
                if result:
                    break
                continue
            h.step()
            now = time.monotonic()
            if now >= next_roll:
                next_roll = now + 1.0
                h.roll()
            if now >= next_poll:
                next_poll = now + POLL
                new, _ = read_tabs()
                if new and h.refresh(new):
                    h.draw()
    finally:
        restore()
    if result.startswith("focus:"):
        try:
            kitty("focus-tab", "--match", f"id:{result[6:]}")
        except (OSError, subprocess.SubprocessError):
            pass
    elif result == "help":
        sheet = os.path.join(HERE, "shortcuts.sh")
        if os.path.isfile(sheet):
            os.execvp("bash", ["bash", sheet])
    return 0


def say(conf: str, state: str) -> str:
    tabs, _ = read_tabs()
    return "".join(f"{s['title']}: {s['text']}\n" for s in suggestions(tabs, datetime.datetime.now(), state, conf,
                                                                    load_hidden(state)))


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "panel"
    conf, state = conf_dir(), state_dir()
    if mode == "say" or (mode == "panel" and not (sys.stdin.isatty() and sys.stdout.isatty())):
        sys.stdout.write(say(conf, state))
        return 0
    if mode == "panel":
        return panel(conf, state)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
