#!/bin/bash
# check-macos.sh — the macOS checks, run by the Gauntlet's macOS lane on a GitHub macOS runner (it
# needs a Mac: it refuses to run elsewhere). It leaves your kitty config alone (everything goes in a
# temp folder), but it opens a kitty window of its own and restarts it, sends one test notification
# and plays one near-silent sound. It runs every step and counts failures, so one run reports
# everything. Mac users can run it too:
#   bash scripts/check-macos.sh [PATH/TO/kitty.app]      (default: /Applications or ~/Applications)
# It runs with what a Mac has out of the box, like a kitty started from the Dock: /bin/bash 3.2,
# /usr/bin/python3, BSD tools, zsh, and kitty.app's own folder on PATH (no Homebrew).
# Steps: the system's tools · unit tests (zsh and bash 3.2 included) · install and uninstall into a
# temp folder, with kitty's config check · the sounds (afplay's formats) · notifications (osascript)
# · tab_bar.py's agent lookup against real processes (kitty's Python, its macOS helpers) · last, the
# real kitty: does it start with NineLives' config, is its socket where ninelives-macos.conf says,
# does the sidebar find an agent, and does kitty-relaunch.sh bring every tab back. A runner where
# kitty can't open a window skips that last part with a warning.
set -uo pipefail
[ "$(uname -s)" = Darwin ] || { echo "check-macos.sh is for macOS (Linux: bash scripts/check.sh)"; exit 2; }
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 2
APP="${1:-}"
if [ -z "$APP" ]; then
  for a in /Applications/kitty.app "$HOME/Applications/kitty.app"; do [ -x "$a/Contents/MacOS/kitty" ] && APP="$a" && break; done
fi
[ -n "$APP" ] && [ -x "$APP/Contents/MacOS/kitty" ] || { echo "kitty.app not found (give its path)"; exit 2; }
KDIR="$APP/Contents/MacOS"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$KDIR"
export PYTHONDONTWRITEBYTECODE=1
TMP="$(mktemp -d)"
KPIDS=""
cleanup() {
  for p in $KPIDS; do kill "$p" 2>/dev/null; done
  rm -rf "$TMP"
}
trap cleanup EXIT
fails=0
ok()   { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }
warn() { printf '  warn  %s\n' "$1"; }
note() { printf '        %s\n' "$1"; }

echo "The system"
note "$(sw_vers -productName 2>/dev/null) $(sw_vers -productVersion 2>/dev/null) ($(uname -m))"
note "bash: $(command -v bash) $(bash -c 'echo $BASH_VERSION')"
note "zsh: $(command -v zsh) $(zsh -c 'echo $ZSH_VERSION' 2>/dev/null)"
note "python3: $(command -v python3) $(python3 -c 'import sys; print(sys.version.split()[0])')"
note "kitty: $(kitty --version)"
note "less: $(less --version 2>/dev/null | head -1)"
case "$(bash -c 'echo $BASH_VERSION')" in 3.2*) ok "bash is macOS's own 3.2";; *) fail "bash on PATH isn't macOS's 3.2";; esac
# what NineLives' scripts work around (informational: shows where BSD differs from GNU)
d="$(date +%s%N)"; case "$d" in *N) note "date has no %N (prints $d): kitty-relaunch.sh keeps the digits";; *) note "date +%s%N: $d";; esac
printf '0.9.0\n0.50.0\n' | sort -V >/dev/null 2>&1 && note "sort -V works" || note "sort -V doesn't (install.sh compares versions with awk)"
readlink -f / >/dev/null 2>&1 && note "readlink -f works" || note "no readlink -f (kitty-relaunch.sh falls back to python3)"
for t in setsid flock sha1sum timeout systemctl; do
  command -v "$t" >/dev/null && note "$t: present" || note "$t: missing (handled)"
done
if [ "$(printf 'a\033[1;33mb\033[0mc' | sed $'s/\e\\[[0-9;]*m//g')" = abc ]; then ok "BSD sed strips colour codes the way tips.sh and shortcuts.sh do it"
else fail "sed doesn't strip colour codes as tips.sh does"; fi
if less --mouse -V >/dev/null 2>&1; then note "less knows --mouse"; else note "less has no --mouse (the F1 sheet leaves it out)"; fi

echo "Unit tests"
out="$(python3 -m unittest discover -s tests -v 2>&1)"; rc=$?
ran="$(grep -oE 'Ran [0-9]+ tests?' <<< "$out")"
if [ "$rc" = 0 ]; then ok "$ran with /usr/bin/python3 $(python3 -c 'import sys; print(sys.version.split()[0])')"
else fail "unit tests: $(grep -E '^(FAIL|ERROR):' <<< "$out" | head -8 | tr '\n' ' ')"; printf '%s\n' "$out" | tail -40; fi
# on a Mac nothing macOS-specific may be skipped: zsh, the kitty config, the restart without setsid
skipped="$(grep -E "skipped '(zsh not installed|no kitty|missing|no ps|no shasum)" <<< "$out")"
[ -z "$skipped" ] && ok "no macOS test was skipped (zsh, kitty's config parser, ps, shasum)" \
  || fail "skipped on a Mac: $(tr '\n' ' ' <<< "$skipped")"
grep -qE "^test_.*Zsh.* \.\.\. ok$" <<< "$out" && ok "tips.sh tests ran in zsh" || fail "no zsh tips.sh test ran"

echo "Install"
DEST="$TMP/kitty"
out="$(KITTY_CONFIG_DIRECTORY="$DEST" bash scripts/install.sh 2>&1)"; rc=$?
if [ "$rc" = 0 ] && grep -q "Config check: OK" <<< "$out"; then ok "install.sh into a temp folder; kitty's config check passes"
else fail "install.sh (exit $rc): $(tail -5 <<< "$out" | tr '\n' ' ')"; fi
n="$(find config -type f ! -path '*/__pycache__/*' | wc -l | tr -d ' ')"
m="$(find "$DEST" -type f ! -name '*.bak-*' ! -name '*.wav' | wc -l | tr -d ' ')"
w="$(find "$DEST/sounds" -name '*.wav' | wc -l | tr -d ' ')"
[ "$n" = "$m" ] && [ "$w" = 8 ] && ok "every config file installed ($n), and a .wav of each sound ($w)" \
  || fail "installed $m of $n files and $w of 8 .wav sounds"
# kitty reads the installed config as a Mac kitty does: ninelives-macos.conf included, no complaints
conf="$(kitty +runpy 'import sys; from kitty.config import load_config; o = load_config(sys.argv[-1]); print(o.listen_on)' "$DEST/kitty.conf" 2>&1)"
[ "$conf" = "unix:ninelives-kitty-{kitty_pid}" ] && ok "kitty reads ninelives-macos.conf: listen_on $conf" \
  || fail "kitty's listen_on on macOS: $conf"
sock="$(kitty +runpy 'import os; from kitty.main import expand_listen_on; print(expand_listen_on("unix:ninelives-kitty-{kitty_pid}", True, {}))' 2>&1)"
path="${sock#unix:}"
if [ "${#path}" -lt 104 ] && [ "$(dirname "$path")" = "$(python3 -c 'import tempfile; print(tempfile.gettempdir())')" ]; then
  ok "the socket goes in the temp folder, ${#path} of at most 103 characters ($path)"
else fail "socket path: $sock (${#path} characters)"; fi
out="$(KITTY_CONFIG_DIRECTORY="$DEST" bash scripts/uninstall.sh 2>&1)"; rc=$?
left="$(find "$DEST" -type f 2>/dev/null | sed "s|^$DEST/||" | tr '\n' ' ')"
[ "$rc" = 0 ] && [ -z "$left" ] && ok "uninstall.sh takes everything out again, the .wav sounds too" \
  || fail "uninstall.sh (exit $rc) left: $left"

echo "Sounds"
python3 scripts/make-sounds.py --wav "$TMP/wav" >/dev/null
if afinfo "$TMP/wav/done.wav" >/dev/null 2>&1; then ok "afinfo reads the .wav sounds install.sh makes"; else fail "afinfo can't read done.wav"; fi
if afinfo config/sounds/done.oga >/dev/null 2>&1; then note "afinfo reads .oga here (the .wav copies would not be needed)"
else note "afinfo can't read .oga: hence the .wav copies"; fi
if afplay -v 0.0001 -t 0.2 "$TMP/wav/drop.wav" >/dev/null 2>&1; then ok "afplay plays a .wav (almost silently: -v 0.0001)"
else warn "afplay failed (no audio device on this runner?)"; fi

echo "Notifications"
title='Badge "x" \ & end tell'; body=$'two\nlines -x'
got="$(osascript -e 'on run argv' -e 'return (item 1 of argv) & "|" & (item 2 of argv)' -e 'end run' "$title" "$body" 2>&1)"
[ "$got" = "$title|$body" ] && ok "osascript gets the title and text as arguments, untouched (quotes, backslash, a newline)" \
  || fail "osascript argument passing: '$got'"
cmd="$(python3 - "$REPO/config/tab_bar.py" <<'EOF'
import ast, sys
src = open(sys.argv[1], encoding="utf-8").read()
# _notify_cmd's macOS list, read from tab_bar.py itself (it can't be imported without kitty)
fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_notify_cmd")
lst = fn.body[0].body[-1].value
print("\n".join(ast.literal_eval(e) for e in lst.elts[:-2]))
EOF
)"
args=(); while IFS= read -r a; do args+=("$a"); done <<< "$cmd"
if [ "${args[0]:-}" = osascript ] && "${args[@]}" "NineLives check" "a test notification from the Gauntlet" >/dev/null 2>&1; then
  ok "tab_bar.py's osascript notification runs"
else warn "the notification command failed here (${args[*]:-none}; no notification center on this runner?)"; fi

echo "Live processes"
out="$(NINELIVES_STATE="$TMP/live/state" KITTY_CONFIG_DIRECTORY="$TMP/live/conf" kitty +launch tests/live_agent_lookup.py 2>&1)"; rc=$?
printf '%s\n' "$out" | sed 's/^/        /'
[ "$rc" = 0 ] && grep -q "takes the macOS path" <<< "$out" && ok "tab_bar.py finds an agent below bash with kitty's macOS helpers" \
  || fail "live agent lookup (exit $rc)"

echo "The real kitty"
# a config folder of its own, muted, no notifications; its socket from ninelives-macos.conf
K="$TMP/real"; mkdir -p "$K/state" "$K/cache"
KITTY_CONFIG_DIRECTORY="$K/conf" bash scripts/install.sh >/dev/null 2>&1
touch "$K/conf/sounds-off"
mkdir -p "$K/work/code/webapp"; ln -s "$(command -v sleep)" "$K/work/claude"
KENV="KITTY_CONFIG_DIRECTORY=$K/conf NINELIVES_STATE=$K/state NINELIVES_QUIET=1 XDG_CACHE_HOME=$K/cache"
# (kitty is this script's child: once it exits it stays a zombie until reaped, and kill -0 still works)
alive() { ps -o stat= -p "$1" 2>/dev/null | grep -q '^[^Z]'; }
# (env, not a shell function: env execs kitty, so $! is kitty's pid. $KENV holds no spaces: $TMPDIR has none)
# shellcheck disable=SC2086
env $KENV "$KDIR/kitty" --directory "$K/work/code/webapp" >"$K/kitty.log" 2>&1 &
KPID=$!; KPIDS="$KPID"
S="${TMPDIR:-/tmp}"; S="${S%/}/ninelives-kitty-$KPID"
for _ in $(seq 1 60); do [ -S "$S" ] && break; alive "$KPID" || break; sleep 0.5; done
if ! [ -S "$S" ] && alive "$KPID"; then
  fail "kitty runs but has no socket at $S (there: $(cd "${S%/*}" && echo ninelives-kitty-*))"
  sed 's/^/        /' "$K/kitty.log" | tail -15
elif ! [ -S "$S" ]; then
  warn "kitty didn't come up here (it exited: no window on this runner?): skipping the real-kitty checks"
  sed 's/^/        /' "$K/kitty.log" | tail -15
else
  SOCK="unix:$S"
  ok "kitty started with NineLives' config; its socket is where ninelives-macos.conf puts it ($S)"
  k() { kitty @ --to "$SOCK" "$@"; }
  ls1="$(k ls 2>&1)"
  ntabs() { k ls | python3 -c 'import json, sys; print(sum(len(o["tabs"]) for o in json.load(sys.stdin)))'; }
  [ "$(ntabs 2>/dev/null)" = 1 ] && ok "kitty @ --to that socket answers (kitty @ ls)" || fail "kitty @ ls: $(head -3 <<< "$ls1")"
  socks="$(TMPDIR="${TMPDIR:-}" python3 scripts/kitty-tabs.py sockets)"
  grep -qx "found $SOCK" <<< "$socks" && ok "kitty-tabs.py finds that socket from outside kitty" || fail "kitty-tabs.py sockets: $socks"
  got="$(k ls | python3 scripts/kitty-tabs.py kitty-pid)"
  [ "$got" = "$KPID" ] && ok "kitty-tabs.py finds kitty's pid with ps ($got)" || fail "kitty-pid: '$got', kitty is $KPID"
  # a tab like one the restart reopens: bash leading, the agent below it in the same group
  k launch --type=tab --cwd "$K/work/code/webapp" bash -c "'$K/work/claude' 300; :" >/dev/null
  mark=""
  for _ in $(seq 1 20); do
    sleep 0.5; k focus-tab --match index:0 >/dev/null 2>&1; sleep 0.5; k focus-tab --match index:1 >/dev/null 2>&1
    mark="$(sed -n 's/^agents: //p' "$K/state/sidebar.txt" 2>/dev/null)"
    grep -qw "2:✳" <<< "$mark" && break
  done
  grep -qw "2:✳" <<< "$mark" && ok "the sidebar marks the agent tab ✳ (sidebar.txt: agents: $mark)" \
    || fail "agent mark in the sidebar: '${mark:-no sidebar.txt}'"
  # kitty-relaunch.sh on it: detached with python3 (no setsid), kitty's pid from ps, a new kitty on
  # the same socket with both tabs back
  # shellcheck disable=SC2086
  out="$(env $KENV NL_KITTY_SOCKET="$SOCK" bash scripts/kitty-relaunch.sh 2>&1)"
  log="$K/cache/ninelives/kitty-relaunch.log"
  for _ in $(seq 1 60); do grep -qE "done: |FAILED" "$log" 2>/dev/null && break; sleep 0.5; done
  if grep -q "done: " "$log" 2>/dev/null && [ "$(ntabs 2>/dev/null)" = 2 ]; then
    ok "kitty-relaunch.sh restarts kitty on the same socket with both tabs back"
  else fail "kitty-relaunch.sh: $out / $(tail -5 "$log" 2>/dev/null | tr '\n' ' ')"; fi
  NEWPID="$(k ls 2>/dev/null | python3 scripts/kitty-tabs.py kitty-pid)"
  KPIDS="$KPIDS $NEWPID"
  [ -n "$NEWPID" ] && [ "$NEWPID" != "$KPID" ] && ! alive "$KPID" && ok "the old kitty is gone, the new one runs (pid $NEWPID)" \
    || fail "after the restart: old $KPID, new '${NEWPID:-none}'"
  errs="$(grep -iE 'traceback|invalid tab title|invalid listen_on|tab_bar\.py' "$K/kitty.log" || true)"
  [ -z "$errs" ] && ok "no tab_bar.py or listen_on errors in the kitty log" || fail "kitty log: $(head -5 <<< "$errs" | tr '\n' ' ')"
  grep -q "falling back to Menlo" "$K/kitty.log" && note "(DejaVu Sans Mono isn't installed here: kitty used Menlo, as it says)"
  note "kitty's log:"; sed 's/^/          /' "$K/kitty.log" | tail -20
  k close-window --match all >/dev/null 2>&1 || true
fi

echo
if [ "$fails" = 0 ]; then echo "All macOS checks passed."; else echo "$fails macOS check(s) failed."; exit 1; fi
