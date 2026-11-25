#!/usr/bin/env bash
# kitty-relaunch.sh — close a kitty window and reopen every tab in the newest kitty.
# Each tab comes back in its folder: Claude tabs resume their session (claude --resume <ID>, or
# claude --continue when it was started without one), omp tabs continue their last session, anything
# else becomes a plain shell there: kitty's own shell, with shell integration (an agent's tab gets one
# too once the agent exits). Split tabs come back with every pane, each in its own folder with
# its own command, in the same layout and sizes, with the pane you were in focused. Tab names you set
# come back, and so does the tab you were on. The new kitty starts from a kitty session file
# (scripts/kitty-tabs.py session), the format kitty's own save_as_session writes.
# It runs detached, so it finishes even if it was started from a tab inside that window.
#
#   bash scripts/kitty-relaunch.sh            reload now
#   bash scripts/kitty-relaunch.sh --when-idle   wait until no Claude/omp tab is busy, then reload
#   bash scripts/kitty-relaunch.sh --dry-run  just show what would be reopened (what the log lists)
#   bash scripts/kitty-relaunch.sh --status   which tabs --when-idle would wait for, and why
#
# Which kitty: the one you run it in (its remote-control socket, $KITTY_LISTEN_ON). Run from
# anywhere else, the only other kitty of yours with a socket (kitty.conf's listen_on, or a launcher's
# --listen-on); with several, it lists them and asks you to run it from a tab of the right one.
# NL_KITTY_SOCKET=ADDRESS picks one directly and keeps your environment (for the test kitty).
# Log and session files: ${XDG_CACHE_HOME:-~/.cache}/ninelives/kitty-relaunch.log
# macOS (new, not yet tried on a real Mac; the Gauntlet checks the parts it can on a macOS runner):
# no setsid, flock or systemd there, so python3 detaches and locks, and the new kitty starts with
# only the variables a Mac app gets from the system, plus your locale and PATH.
set -euo pipefail
NEW="$HOME/.local/kitty.app/bin/kitty"; [ -x "$NEW" ] || NEW="$(command -v kitty || true)"
# The detached copy (below) starts the kitty this run found (_KR_NEW): in its cleaner environment
# PATH or NL_APP_DIRS may point elsewhere
if [ -n "${_KR_NEW:-}" ] && [[ "${_KR_DETACHED:-}" =~ ^[0-9-]+$ ]]; then NEW="$_KR_NEW"; fi
unset _KR_NEW
# macOS: kitty.app isn't on PATH outside kitty's own tabs. NL_APP_DIRS: where to look, folders
# separated by ":" (default /Applications:~/Applications; the tests point it at a temp folder)
while IFS= read -r app; do
  [ -n "$NEW" ] || { [ -n "$app" ] && [ -x "$app/kitty.app/Contents/MacOS/kitty" ] && NEW="$app/kitty.app/Contents/MacOS/kitty"; } || true
done <<< "$(tr ':' '\n' <<< "${NL_APP_DIRS:-/Applications:$HOME/Applications}")"
[ -n "$NEW" ] || { echo "kitty not found (not on PATH, not in ~/.local/kitty.app or kitty.app)" >&2; exit 1; }
# The kitten that ships with that kitty: the session runs it for folders with a $ in their name,
# and kitten may not be on PATH (readlink -f: macOS 12.3 and newer; python3 for older ones)
KITTEN="$(dirname -- "$(readlink -f -- "$NEW" 2>/dev/null || python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$NEW")")/kitten"
[ -x "$KITTEN" ] || KITTEN="$(command -v kitten || true)"
MACOS=0; [ "$(uname -s)" = Darwin ] && MACOS=1
# Run a command in a new session, so it outlives the kitty window this was started from: setsid,
# or where there is none (macOS) python3 (forking first: setsid fails for a process group leader).
# python3 -c "$DETACH_PY" "NAMES" COMMAND…: the command gets only the variables named, the ones its
# caller has. macOS's /usr/bin/python3 is a shim that adds SDKROOT, CPATH, LIBRARY_PATH and
# MANPATH to the python it starts; they must not reach the new kitty and every tab in it.
DETACH_PY='import os, sys
keep = set(sys.argv[1].split())
for name in [n for n in os.environ if n not in keep]:
    del os.environ[name]
if os.getpid() == os.getpgrp() and os.fork():
    os._exit(0)
os.setsid()
os.execvp(sys.argv[2], sys.argv[2:])'
# (the detached copy is handed the folder in _KR_CACHE: its clean environment may lack XDG_CACHE_HOME)
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}"
[ -n "${_KR_CACHE:-}" ] && [[ "${_KR_DETACHED:-}" =~ ^[0-9-]+$ ]] && CACHE="$_KR_CACHE"
LOG="$CACHE/ninelives/kitty-relaunch.log"; mkdir -p "$(dirname "$LOG")"
MODE="${1:-now}"

case "$MODE" in now|--when-idle|--dry-run|--status) ;;
  *) echo "usage: bash scripts/kitty-relaunch.sh [--when-idle | --dry-run | --status]" >&2; exit 2 ;; esac
# How to bring each tab back, which tabs are busy, which kitty: scripts/kitty-tabs.py.
TABS_PY="$(cd "$(dirname "$0")" && pwd)/kitty-tabs.py"
answers() { "$NEW" @ --to "$1" ls >/dev/null 2>&1; }

# Which kitty (see the top). The detached copy gets the answer in _KR_SOCK: the clean environment it
# starts from has no KITTY_LISTEN_ON.
if [ -n "${NL_KITTY_SOCKET:-}" ]; then
  SOCK="$NL_KITTY_SOCKET"
elif [ -n "${_KR_SOCK:-}" ] && [[ "${_KR_DETACHED:-}" =~ ^[0-9-]+$ ]]; then
  SOCK="$_KR_SOCK"
else
  SOCK=""; found=()
  while read -r where addr; do
    [ -n "$addr" ] && answers "$addr" || continue
    if [ "$where" = here ]; then SOCK="$addr"; break; fi
    found+=("$addr")
  done < <(python3 "$TABS_PY" sockets)
  if [ -z "$SOCK" ] && [ "${#found[@]}" = 1 ]; then SOCK="${found[0]}"; fi
  if [ -z "$SOCK" ] && [ "${#found[@]}" -gt 1 ]; then
    echo "$(date +%T) several kitty windows could be restarted:"; printf '  %s\n' "${found[@]}"
    echo "Run this from a tab of the one you mean (or NL_KITTY_SOCKET=<one of them> for a test kitty)."
    exit 1
  fi
  if [ -z "$SOCK" ]; then
    echo "$(date +%T) no kitty to restart: none has a remote-control socket that answers."
    echo "  NineLives' kitty.conf gives every kitty one (listen_on), but only from kitty's next start:"
    echo "  close kitty and open it again once after installing, then run this from one of its tabs."
    exit 1
  fi
fi
unset _KR_SOCK _KR_CACHE
kls() { "$NEW" @ --to "$SOCK" ls 2>/dev/null; }
kls >/dev/null || { echo "$(date +%T) the kitty at $SOCK doesn't answer (closed?)"; exit 1; }
busy() { kls | python3 "$TABS_PY" busy; }           # one line per busy tab; nothing when all idle
SESSION="$(dirname "$LOG")/kitty-relaunch.kitty-session"   # what the new kitty opens
# kitty's own save, for zoomed splits; each run has its own (a --dry-run beside a restart can't delete
# the restart's), named by this shell's PID
SAVED="$(dirname "$LOG")/kitty-relaunch-saved-$$.kitty-session"
# (kitty writes the command running in each window into that save, arguments and all: it is removed
# as soon as its layouts are read, and when this run ends whichever way)
trap 'rm -f "$SAVED"' EXIT

# The detached copy of this script knows itself by a one-time token (in the environment and in a
# file it deletes at once). A plain _KR_DETACHED=1 leaked into the new kitty and every tab in it, so
# the next run from a tab skipped detaching, and closing kitty killed it before kitty reopened.
# Each run marks itself with its own file (named by the value), so two runs started at once can't take
# each other's mark; a lock then lets only one background copy restart kitty at a time.
MARK_DIR="$(dirname "$LOG")"
detached=0
if [[ "${_KR_DETACHED:-}" =~ ^[0-9-]+$ ]] && [ -e "$MARK_DIR/kitty-relaunch-$_KR_DETACHED.run" ]; then
  detached=1; rm -f "$MARK_DIR/kitty-relaunch-$_KR_DETACHED.run"
  # (not kitty-relaunch.lock: a kitty started by an older version of this script kept that file's
  # lock open for its whole life, and restarting it would stop here)
  exec 9>"$MARK_DIR/kitty-relaunch-run.lock"
  if command -v flock >/dev/null && ! flock -n 9; then
    echo "$(date +%T) another restart is already running; this one stops"; exit 0
  fi
  # no flock(1) (macOS): the same lock on fd 9 through python3 (it stays with this shell's fd)
  if ! command -v flock >/dev/null && ! python3 -c 'import fcntl; fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)' 2>/dev/null; then
    echo "$(date +%T) another restart is already running; this one stops"; exit 0
  fi
fi
unset _KR_DETACHED                     # never hand it on (to the new kitty and its tabs)
if [ $detached != 1 ] && [ "$MODE" != --dry-run ] && [ "$MODE" != --status ]; then
  if [ "$MODE" = --when-idle ] && b="$(busy)" && [ -n "$b" ]; then
    echo "Waiting for these tabs to go idle first (bash scripts/kitty-relaunch.sh --status to check again):"
    printf '%s\n' "$b"
  fi
  # Start from the desktop's clean environment: drop every variable the desktop session doesn't
  # have. Otherwise, when this runs from inside a Claude/agent shell, kitty and every tab inherit
  # that agent's internals (e.g. CLAUDE_CODE_CHILD_SESSION, which turns off transcript saving).
  # (Not for a test kitty, NL_KITTY_SOCKET: it keeps the caller's hidden display and test HOME.)
  # (no systemd user manager, or no XDG_RUNTIME_DIR to reach it: keep the environment as it is)
  MGR_KEYS="$({ systemctl --user show-environment 2>/dev/null || true; } | cut -d= -f1)"
  # macOS has no systemd: keep what a Mac app gets from the system (launchd) when it starts, and
  # your locale and PATH
  if [ -z "$MGR_KEYS" ] && [ "$MACOS" = 1 ]; then
    MGR_KEYS="$(printf '%s\n' HOME USER LOGNAME SHELL PATH TMPDIR LANG SSH_AUTH_SOCK __CF_USER_TEXT_ENCODING \
      __CFBundleIdentifier COMMAND_MODE SECURITYSESSIONID XPC_FLAGS XPC_SERVICE_NAME LaunchInstanceID; compgen -e | grep '^LC_' || true)"
  fi
  # Which config folder kitty reads stays as it was: a kitty started with its own config folder
  # would otherwise come back with the default one
  [ -z "$MGR_KEYS" ] || MGR_KEYS="$MGR_KEYS"$'\n'"KITTY_CONFIG_DIRECTORY"$'\n'"XDG_CONFIG_HOME"
  if [ -n "$MGR_KEYS" ] && [ -z "${NL_KITTY_SOCKET:-}" ]; then
    for v in $(compgen -e); do grep -qxF "$v" <<< "$MGR_KEYS" || unset "$v" 2>/dev/null || true; done
  fi
  # (digits only: an older BSD date (macOS) has no %N and prints an N, which the check above would
  # reject; macOS 15's prints digits)
  run_id="$$-$RANDOM-$(date +%s%N | tr -cd '0-9')"; : > "$MARK_DIR/kitty-relaunch-$run_id.run"
  if command -v setsid >/dev/null; then
    _KR_DETACHED="$run_id" _KR_SOCK="$SOCK" _KR_CACHE="$CACHE" _KR_NEW="$NEW" setsid nohup bash "$0" "$@" >>"$LOG" 2>&1 < /dev/null &
  else
    _KR_DETACHED="$run_id" _KR_SOCK="$SOCK" _KR_CACHE="$CACHE" _KR_NEW="$NEW" python3 -c "$DETACH_PY" \
      "$(compgen -e | tr '\n' ' ') _KR_DETACHED _KR_SOCK _KR_CACHE _KR_NEW" nohup bash "$0" "$@" >>"$LOG" 2>&1 < /dev/null &
  fi
  echo "Reload running in the background (log: $LOG). The kitty window will close and reopen."
  exit 0
fi

# kitty's own save keeps the splits of a zoomed tab (Ctrl+Alt+Z), which `kitty @ ls` doesn't show.
# Optional: without it (an older kitty, an error) zoomed tabs come back zoomed, other splits as usual.
# (--dry-run reads it too, so it shows what the restart would open.)
save_layouts() {
  rm -f "$SAVED"
  "$NEW" @ --to "$SOCK" action save_as_session --save-only "$SAVED" >/dev/null 2>&1 || true
  for _ in $(seq 1 10); do [ -s "$SAVED" ] && break; sleep 0.2; done
}

if [ "$MODE" = --dry-run ]; then save_layouts; kls | python3 "$TABS_PY" show "$SAVED"; rm -f "$SAVED"; exit 0; fi
if [ "$MODE" = --status ]; then
  b="$(busy)"
  if [ -n "$b" ]; then echo "--when-idle would wait for:"; printf '%s\n' "$b"; else echo "All tabs idle: --when-idle would restart now."; fi
  exit 0
fi
if [ "$MODE" = --when-idle ]; then
  echo "$(date +%T) waiting until no tab is busy..."
  idle=0; last=""
  while :; do
    if ! b="$(busy)"; then             # kitty didn't answer: gone (nothing to restart) or just slow
      kls >/dev/null || { echo "$(date +%T) that kitty is gone: nothing to restart"; exit 1; }
      b="(kitty didn't answer)"
    fi
    if [ "$b" != "$last" ] && [ -n "$b" ]; then   # say what it's waiting for, whenever that changes
      echo "$(date +%T) waiting for:"; printf '%s\n' "$b"
    fi
    last="$b"
    if [ -z "$b" ]; then idle=$((idle + 1)); else idle=0; fi
    [ $idle -ge 3 ] && break          # idle for 3 checks in a row (~30 s)
    sleep 10
  done
fi

save_layouts
DATA="$(kls)"
NL_KITTEN="$KITTEN" python3 "$TABS_PY" session "$SAVED" <<< "$DATA" > "$SESSION.tmp" && [ -s "$SESSION.tmp" ] \
  || { rm -f "$SAVED"; echo "$(date +%T) FAILED: could not work out what to reopen; kitty left running"; exit 1; }
WHAT="$(python3 "$TABS_PY" show "$SAVED" <<< "$DATA")"
rm -f "$SAVED"
# Let the new kitty's own parser read the file first: a session it can't read opens just an error
# window, and every tab would be gone. (A kitty whose internals differ skips this check.)
if ! why="$("$NEW" +runpy 'import sys
try:
    from kitty.cli import create_default_opts
    from kitty.session import parse_session
    sessions = parse_session(open(sys.argv[-1], encoding="utf-8").read(), create_default_opts())
except Exception:
    sys.exit(0)
try:
    list(sessions)
except ValueError as e:
    print(e)
    sys.exit(3)
except Exception:
    pass' "$SESSION.tmp" 2>&1)"; then
  echo "$(date +%T) FAILED: kitty can't read the session file ($why); kitty left running"; exit 1
fi
mv "$SESSION.tmp" "$SESSION"
echo "$(date +%T) reopening $(grep -c '^new_tab' "$SESSION") tabs ($(grep -c '^launch' "$SESSION") windows):"
printf '%s\n' "$WHAT"                                       # log exactly what will be reopened
# kitty's pid: up from a window's process to kitty (not just its parent: under launch --hold a
# window's pid is its command, which kitten run-shell started)
KPID="$(python3 "$TABS_PY" kitty-pid <<< "$DATA" 2>/dev/null || true)"
if ! [[ "$KPID" =~ ^[0-9]+$ ]] || [ "$KPID" -le 1 ]; then
  echo "$(date +%T) FAILED: could not find the old kitty's process; kitty left running"; exit 1
fi
echo "$(date +%T) closing old kitty (pid $KPID)"
kill -TERM "$KPID"
for _ in $(seq 1 50); do kls >/dev/null || break; sleep 0.2; done
if kls >/dev/null; then       # it didn't close (a question on screen?): don't start a second one
  echo "$(date +%T) FAILED: the old kitty is still open after 10 s; not starting another"; exit 1
fi
sleep 0.5
# A socket file left behind (kitty removes its own when it closes cleanly) would stop the new kitty
# from listening on it
if [[ "$SOCK" == unix:/* ]] && [ -S "${SOCK#unix:}" ]; then rm -f -- "${SOCK#unix:}"; fi

# The new kitty listens on the old one's address (as given on the command line, kitty adds no pid
# to it), so a launcher that started kitty with --listen-on still finds it.
# The session file reopens every tab and pane, sets the layouts and split sizes, names the tabs and
# focuses the pane and tab you were on, all inside kitty (one failed window can't shift a name or
# the focus onto another tab, so there are no window ids to track).
# (9>&-: the restart's lock stays here. A kitty that kept fd 9 held the lock for its whole life, and
# every later restart of it stopped with "another restart is already running".)
if command -v setsid >/dev/null; then
  setsid "$NEW" -o allow_remote_control=socket-only --listen-on "$SOCK" --session "$SESSION" >/dev/null 2>&1 < /dev/null 9>&- &
else
  python3 -c "$DETACH_PY" "$(compgen -e | tr '\n' ' ')" \
    "$NEW" -o allow_remote_control=socket-only --listen-on "$SOCK" --session "$SESSION" >/dev/null 2>&1 < /dev/null 9>&- &
fi
for _ in $(seq 1 50); do kls >/dev/null && break; sleep 0.2; done
if ! kls >/dev/null; then
  echo "$(date +%T) FAILED: the new kitty did not start ($NEW). Start kitty by hand"
  echo "  ($NEW --session $SESSION reopens everything); tabs to reopen:"
  printf '%s\n' "$WHAT"
  exit 1
fi
sleep 1
# focus_follows_mouse can hand a split tab's focus to the pane under the mouse as the window opens:
# focus the pane you were in again (the session marked it), the tab you were on last.
for id in $(kls | python3 "$TABS_PY" refocus 2>/dev/null); do
  "$NEW" @ --to "$SOCK" focus-window --match "id:$id" >/dev/null 2>&1 || true
done
got="$(kls | python3 -c 'import json,sys; print(sum(len(t["windows"]) for o in json.load(sys.stdin) for t in o["tabs"]))' 2>/dev/null || echo "?")"
[ "$got" = "$(grep -c '^launch' "$SESSION")" ] || echo "$(date +%T) note: $got windows open, the session asked for $(grep -c '^launch' "$SESSION")"
echo "$(date +%T) done: $("$NEW" --version)"
