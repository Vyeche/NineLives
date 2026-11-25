"""command_title.py — keep a running command's arguments out of the tab names. Part of NineLives.

While a command runs, kitty's shell integration sets the window title to the whole command line,
and the sidebar (tab_bar.py), the search box (tab-finder.py) and kitty-relaunch's --status
(scripts/kitty-tabs.py) show that title as the tab's name. A command line can hold a password or
a token (`mysql -pSECRET`, `curl -H "Authorization: Bearer …"`, `export TOKEN=…`), so those show
only the program and its subcommand instead: `git push`, `npm run build`, `python3 -m pytest`.
The `full-commands` switch file in kitty's config folder (kitty-commands full, or the settings
list) shows whole command lines again. Plain Python, no kitty: the three users load this file.

Which titles are command lines (shown_title):
  - kitty keeps the command line the shell reported when the command started (OSC 133;C;
    Window.last_cmd_cmdline in kitty/window.py, "last_reported_cmdline" in `kitty @ ls`). bash
    sets the title to the same text without control characters (kitty.bash), zsh with them made
    visible, both behind "host: " over ssh; fish's title is its first 20 characters and the
    folder; kitty collapses whitespace (sanitize_title in kitty/utils.py). A title that is one of
    those is the command line. The short name is made from the reported command, not the title.
  - bash sets the title just before it reports the command: in between, the window is still "at
    the prompt" (kitty's prompt marks), and a title there that isn't a folder is the new command.
  - A title that names the same program as the reported command counts too (another shell's or
    theme's title format), and so, with no reported command (a shell without kitty's prompt
    marks that sets titles itself), does a title whose program is the one running in the window.
  Anything else stays as it is: titles programs set themselves (Claude Code's "✳ Fix the login
  bug", omp's "⠋ omp: refactor the parser"), the folder kitty shows for an idle shell, and names
  you gave a tab (Ctrl+Shift+R; the callers check that before they get here).

The short form (short_command), from the command line:
  - only the first line counts (what follows is a here-document's text or pasted lines); in it
    a chain (`cd x && make test`, `a; b`, `a || b`) names its last command, a pipe
    (`cat f | grep x`) its first; ( ) and $( ) are looked into or left out; `if`/`do`/`then` and
    `done`/`fi` are skipped
  - VAR=value assignments in front are dropped (never shown); so are sudo, env, time, nohup,
    nice, timeout, watch, … with their options: the program after them is the one named
  - the program's name (its basename), and only for programs that have subcommands (SUBCOMMANDS:
    git, npm, docker, make, …) the next word, if it looks like one: lowercase letters, digits,
    - and _, starting with a letter. After `run` and `compose` one more such word (npm run build,
    docker compose up)
  - interpreters (python3, node, bash, …): `-m module` (python3 -m pytest), or the script's file
    name (python3 check.py); code given with -c / -e is never shown, nor anything after it
  - a line that can't be parsed (an open quote): just the program
"""
import functools
import os
import re
import shlex

# kitty's sanitize_title (kitty/utils.py): control characters out, runs of whitespace to one space
_CONTROL_RE = re.compile(r"[\0-\x19\x80-\x9f]")
_SPACES_RE = re.compile(r"\s+")
_CMD_CONTROL_RE = re.compile(r"[\0-\x08\x0b-\x1f\x7f-\x9f]")   # in a command line: all but tab and newline
# what's left out when comparing loosely: whitespace, control characters, and zsh's visible forms
# of them (its title shows a newline as \n, other control characters as ^X)
_LOOSE_RE = re.compile(r"\\[ntrabefv]|\^[@-_?]|[\s\0-\x1f\x7f-\x9f]")
# a host in front of the command: "host: " (bash and zsh over ssh) or "[host] " (fish)
HOST_RE = re.compile(r"^(?:\[[^\]\s]{1,64}\] |[^\s:/\[]{1,64}: )")
FISH_CUT = 20               # fish's default title holds this many characters of the command
CUT_MIN = 20                # a title cut short (… or not) is the command if this much of it matches

# programs whose next word is a subcommand worth showing (git push, make test); for any other
# program the next word could be anything (echo hunter2, ssh prodbox, mysql customers): not shown
SUBCOMMANDS = frozenset("""
    git hg svn jj gh glab tea npm pnpm yarn bun deno npx pnpx bunx corepack cargo rustup go zig
    make gmake just task mise asdf cmake ctest ninja meson bazel buck2 gradle gradlew mvn mvnw sbt
    lein mix dotnet flutter dart swift xcodebuild nix nix-env home-manager docker docker-compose
    podman buildah kubectl k3d kind minikube helm kustomize skaffold tilt terraform tofu pulumi
    packer vagrant ansible-galaxy aws gcloud az doctl flyctl fly heroku vercel netlify wrangler
    firebase supabase prisma systemctl journalctl loginctl apt apt-get dnf yum zypper pacman
    paru yay apk brew port snap flatpak pip pip3 pipx uv poetry pdm hatch pipenv conda mamba
    micromamba pixi rye tox nox pre-commit pytest composer bundle rake rails gem rbenv pyenv
    nvm volta fnm turbo nx lerna ng ollama tmux code hugo manage.py
""".split())
NESTED = frozenset({"run", "compose"})      # npm run build, docker compose up: one more word
WORD_RE = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")
MODULE_RE = re.compile(r"^[A-Za-z_][\w.]{0,39}$")
SCRIPT_RE = re.compile(r"^[\w.+-]{1,40}$")
ASSIGN_RE = re.compile(r"^[A-Za-z_]\w*(?:\[[^\]]*\])?\+?=")

INTERPRETER_RE = re.compile(r"^(?:python[\d.]*|pypy[\d.]*|node|nodejs|ruby|perl|php|lua|luajit|"
                            r"Rscript|tsx|ts-node|bash|sh|zsh|fish|dash|ksh|osascript)$")
INTERPRETER_ARG_FLAGS = {"-W", "-X", "-I", "-o", "-O", "-d", "-C", "--require", "--import",
                         "--loader", "--experimental-loader", "--conditions", "--rcfile",
                         "--init-file"}
# programs that run another program: (options that take an argument, positionals before it)
WRAPPERS = {
    "sudo": ({"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T", "-R", "--user",
              "--group", "--host", "--prompt", "--chdir"}, 0),
    "doas": ({"-u", "-C"}, 0), "run0": ({"-u", "--user"}, 0), "pkexec": ({"--user"}, 0),
    "env": ({"-u", "-C", "-S", "--unset", "--chdir", "--split-string"}, 0),
    "time": ({"-f", "-o", "--format", "--output"}, 0),
    "nohup": (set(), 0), "exec": ({"-a"}, 0), "command": (set(), 0), "builtin": (set(), 0),
    "nice": ({"-n", "--adjustment"}, 0), "ionice": ({"-c", "-n", "-p", "-P", "-u"}, 0),
    "stdbuf": ({"-i", "-o", "-e"}, 0), "setsid": (set(), 0), "unbuffer": (set(), 0),
    "caffeinate": ({"-t", "-w"}, 0), "systemd-inhibit": ({"--what", "--who", "--why", "--mode"}, 0),
    "timeout": ({"-s", "-k", "--signal", "--kill-after"}, 1), "chrt": ({"-T", "-P", "-D"}, 1),
    "taskset": (set(), 1), "flock": ({"-w", "-E", "--timeout", "--conflict-exit-code"}, 1),
    "watch": ({"-n", "-d", "--interval", "--differences"}, 0),
    "strace": ({"-o", "-e", "-p", "-s", "-u", "-E", "-P", "-I", "-a", "-b", "-O", "-S", "-X"}, 0),
    "ltrace": ({"-o", "-e", "-p", "-s", "-u", "-E", "-n", "-a"}, 0), "valgrind": (set(), 0),
    "xargs": ({"-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a", "--delimiter", "--max-args",
               "--max-procs", "--arg-file", "--replace"}, 0),
    "torsocks": (set(), 0), "proxychains": ({"-f"}, 0), "proxychains4": ({"-f"}, 0),
    "firejail": (set(), 0), "noglob": (set(), 0), "nocorrect": (set(), 0),
}
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "coproc"}
CLOSERS = {"done", "fi", "esac", "}", "then", "do", "else"}


def sanitize(s: str) -> str:
    """A title as kitty keeps it (sanitize_title in kitty/utils.py), and stripped."""
    return _SPACES_RE.sub(" ", _CONTROL_RE.sub("", s or "")).strip()


def _loose(s: str) -> str:
    return _LOOSE_RE.sub("", s or "")


def folder_like(title: str) -> bool:
    """A title that names a folder: what shells with kitty's integration show at their prompt
    (~/x, /x, …/x for zsh, "host: ~/x" over ssh, user@host:~/x from many bashrc files)."""
    t = title.strip()
    m = HOST_RE.match(t)
    if m:
        t = t[m.end():]
    return t[:1] in ("", "~", "/", "…") or re.match(r"^[\w.-]+@[\w.-]+:", t) is not None


# ---- the short form ---------------------------------------------------------------------------
def _tokens(line: str):
    """Shell words and operators ((, ), ;, &&, |, >, …), or None if it can't be parsed."""
    line = line.replace("\\\r\n", " ").replace("\\\n", " ").split("\n", 1)[0]
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError:
        return None


def _group(tokens):
    """Fold ( … ) and $( … ) into one item each: ("(", [tokens inside]). Unbalanced: None."""
    out, stack = [], []
    for tok in tokens:
        if set(tok) <= set("()") and tok:
            for ch in tok:
                if ch == "(":
                    stack.append(out)
                    out = []
                elif stack:
                    inner, out = out, stack.pop()
                    if out and isinstance(out[-1], str) and out[-1].endswith("$"):
                        out[-1] = ("$", inner)              # $( … ): a value, not a command here
                    else:
                        out.append(("(", inner))
                else:
                    return None
        else:
            out.append(tok)
    return None if stack else out


def _is_op(tok) -> bool:
    return isinstance(tok, str) and tok != "" and set(tok) <= set(";&|<>")


def _segments(items):
    """Split at ; & && || and newlines: the commands of a chain, each a list of its pipes."""
    chain, pipes, cur = [], [], []
    for tok in items:
        if _is_op(tok) and "<" not in tok and ">" not in tok:
            if tok in ("|", "|&"):
                pipes.append(cur)
            else:
                pipes.append(cur)
                chain.append(pipes)
                pipes = []
            cur = []
        else:
            cur.append(tok)
    pipes.append(cur)
    chain.append(pipes)
    return chain


def _words(cmd) -> list:
    """A simple command's words, redirections (2>&1, > file, << EOF) and their targets left out."""
    out, skip = [], False
    for tok in cmd:
        if skip:
            skip = False
        elif _is_op(tok):
            if out and isinstance(out[-1], str) and out[-1].isdigit():
                out.pop()                                   # the 2 of 2>&1
            skip = True
        else:
            out.append(tok)
    return out


def _pick(items, depth: int = 0) -> list:
    """The words of the command a line is named after: the last command of a chain, the first of
    its pipe; a lone ( … ) is looked into."""
    for pipes in reversed(_segments(items)):
        words = _words(pipes[0]) if pipes else []
        while words and isinstance(words[0], str) and words[0] in KEYWORDS:
            words = words[1:]
        if not words or (isinstance(words[0], str) and words[0] in CLOSERS):
            continue
        if isinstance(words[0], tuple) and words[0][0] == "(":
            if depth < 8:
                inner = _pick(words[0][1], depth + 1)
                if inner:
                    return inner
            continue
        return words
    return []


def _skip_options(words, i: int, arg_flags) -> int:
    while i < len(words) and isinstance(words[i], str) and words[i].startswith("-") and words[i] != "-":
        if words[i] == "--":
            return i + 1
        if words[i] in arg_flags and "=" not in words[i]:
            i += 1
        i += 1
    return i


def _base(word) -> str:
    if not isinstance(word, str):
        return ""
    return os.path.basename(word.rstrip("/")) or word


def _program_at(words):
    """(index of the program in a command's words, the last wrapper before it): VAR=value
    assignments and wrappers (sudo, env, timeout 30, …) with their options are passed over."""
    i, wrapper = 0, ""
    while True:
        while i < len(words) and isinstance(words[i], str) and ASSIGN_RE.match(words[i]):
            i += 1                                          # VAR=value: never shown
        if i >= len(words) or _base(words[i]) not in WRAPPERS:
            return i, wrapper
        wrapper = _base(words[i])
        flags, positionals = WRAPPERS[wrapper]
        i = _skip_options(words, i + 1, flags) + positionals


def _code_flag(flag: str) -> bool:
    """An interpreter option after which code follows (python -c, node -e/-p, perl -ne, bash -lc)."""
    if flag in ("--eval", "--print", "--command", "--exec"):
        return True
    return flag[:1] == "-" and flag[1:2] != "-" and flag[1:].isalpha() and any(c in flag for c in "ceEpr")


@functools.lru_cache(maxsize=256)          # the sidebar asks for every tab on every frame
def short_command(line: str) -> str:
    """The program (and subcommand) a command line runs, without its arguments: "git push" for
    `git push origin main`, "make test" for `cd x && make test`, "" for `FOO=bar` alone."""
    line = _CMD_CONTROL_RE.sub("", line or "")
    tokens = _tokens(line)
    items = _group(tokens) if tokens is not None else None
    if items is None:                                       # an open quote or bracket: the program only
        words = [w.strip("\"'()$`;&|") for w in (line or "").split()]
        words = [w for w in words if w and w not in KEYWORDS]
        i, wrapper = _program_at(words)
        return _base(words[i])[:40] if i < len(words) else wrapper
    words = _pick(items)
    i, wrapper = _program_at(words)
    if i >= len(words):
        return wrapper
    if not isinstance(words[i], str):
        return ""                                           # a $( … ) as the command
    prog = _base(words[i])[:40]
    rest = words[i + 1:]
    if not INTERPRETER_RE.match(prog):
        return prog + _subcommand(prog, rest)
    j = 0
    while j < len(rest) and isinstance(rest[j], str) and rest[j].startswith("-") and rest[j] != "-":
        flag = rest[j]
        if flag == "--":
            j += 1
            break
        module = rest[j + 1] if flag == "-m" and j + 1 < len(rest) else flag[2:] if flag.startswith("-m") else ""
        if isinstance(module, str) and module and MODULE_RE.match(module):
            after = rest[j + 2:] if flag == "-m" else rest[j + 1:]
            return f"{prog} -m {module}{_subcommand(module, after)}"
        if _code_flag(flag):
            return prog                                     # code follows: never shown
        j += 2 if flag in INTERPRETER_ARG_FLAGS else 1
    if j < len(rest) and isinstance(rest[j], str) and ("/" in rest[j] or "." in rest[j]):
        script = _base(rest[j])
        if SCRIPT_RE.match(script):
            return f"{prog} {script}{_subcommand(script, rest[j + 1:])}"
    return prog


def _subcommand(prog: str, rest) -> str:
    """ " push" for git's `push origin main`; "" when prog has no subcommands or the word doesn't
    look like one."""
    if prog not in SUBCOMMANDS:
        return ""
    out = ""
    for _ in range(2):
        if not rest or not isinstance(rest[0], str) or not WORD_RE.match(rest[0]):
            break
        out += " " + rest[0]
        if rest[0] not in NESTED:
            break
        rest = rest[1:]
    return out


# ---- which titles are command lines -----------------------------------------------------------
def _matches(rest: str, raw_cmd: str, cmd: str) -> bool:
    """True if `rest` (a title, its host taken off) is what a shell sets for the command line."""
    if rest == cmd or (_loose(rest) and _loose(rest) == _loose(cmd)):
        return True
    # fish: the command's first 20 characters, a space and the folder ("make test ~/w/proj")
    for head in {sanitize(raw_cmd[:FISH_CUT]), cmd[:FISH_CUT].strip()}:
        if head and rest.startswith(head) and (len(rest) == len(head) or (
                rest[len(head)] == " " and folder_like(rest[len(head) + 1:]))):
            return True
    # a title cut short (some shell themes): what's left of it is how the command starts
    cut = rest.rstrip(".… ")
    return len(cut) >= CUT_MIN and cmd.startswith(cut) and not folder_like(cut)


def command_prefix(title: str, cmdline: str):
    """If the title is the command line the shell reported (cmdline): what's in front of it ("" or
    "host: "), else None."""
    t, c = sanitize(title), sanitize(cmdline)
    if not t or not c:
        return None
    m = HOST_RE.match(t)
    for prefix in ((m.group(), "") if m else ("",)):
        if _matches(t[len(prefix):], cmdline or "", c):
            return prefix
    return None


def _programs(title: str) -> set:
    """The programs a title would run as a command line: its first word and the one named."""
    t = sanitize(title)
    m = HOST_RE.match(t)
    if m:
        t = t[m.end():]
    first = next((w for w in t.split() if not ASSIGN_RE.match(w)), "")
    short = short_command(t)
    return {p for p in (_base(first.strip("\"'")), short.split(" ", 1)[0]) if p}


def shown_title(title: str, cmdline: str = "", at_prompt: bool = False, foreground=None,
                full: bool = False) -> str:
    """The name to show for a window's title: a command line its shell set, cut to its program
    and subcommand (see the top of this file); any other title as it is. "" when the command was
    only VAR=value (the caller then shows the folder).
    cmdline: the command the shell reported (kitty's last_cmd_cmdline); at_prompt: the window is
    at its shell prompt (kitty's prompt marks); foreground: the names of the programs running in
    the window, or a function that returns them (asked only when needed); full: the full-commands
    switch is on."""
    if full or not title:
        return title or ""
    prefix = command_prefix(title, cmdline)
    if prefix is not None:
        s = short_command(cmdline)
        return prefix + s if s else ""
    t = sanitize(title)
    m = HOST_RE.match(t)
    host = m.group() if m else ""
    if at_prompt and not folder_like(t):
        # bash sets the title a moment before it reports the command (kitty.bash): the window is
        # still at its prompt, and a title that isn't a folder is the new command line
        s = short_command(t[len(host):])
        return host + s if s else ""
    if cmdline and not folder_like(t) and _programs(t) & _programs(cmdline):
        # the same program as the reported command, in a form not matched above (another shell's
        # title format): shown short too, from the reported command
        s = short_command(cmdline)
        return host + s if s else ""
    if not cmdline and foreground is not None and (t[:1].isalnum() or t[:1] in "._$(") \
            and not folder_like(t):        # (agents' ✳ / spinner titles and folders: no lookup)
        names = foreground() if callable(foreground) else foreground
        names = {os.path.basename(n) for n in (names or ()) if n}
        if names and _programs(t) & names:
            s = short_command(t[len(host):])
            return host + s if s else ""
    return title
