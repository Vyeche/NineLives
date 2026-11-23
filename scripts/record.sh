#!/usr/bin/env bash
# record.sh — the GIFs in the README and the wiki, recorded from the hidden test kitty
# (scripts/test-kitty.sh: display :97, its own socket, stubbed sounds), so they can be made again
# after a UI change. Nothing reaches your real kitty, desktop or speakers. Needs Xvfb, ffmpeg, kitty.
#   bash scripts/record.sh list            what it can record
#   bash scripts/record.sh all             every recording
#   bash scripts/record.sh NAME [NAME…]    some of them, e.g. bash scripts/record.sh streak search
# Writes docs/images/gifs/NAME.gif (and the walkthrough's stills to docs/images/steps/). Each one
# restarts the test kitty with its own made-up tabs, and the last one stops it. Only one user of
# the test kitty at a time (check.sh uses it too). The window is 960 px wide: narrower, kitty makes
# the sidebar narrower too and the search row shortens its words.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
T="${NL_TEST_DIR:-${TMPDIR:-/tmp}/ninelives-test}"
DISP="${NL_TEST_DISPLAY:-:97}"            # always the hidden display, never $DISPLAY
SOCK="unix:@ninelives-test-kitty"
OUT="$REPO/docs/images/gifs"; STEPS="$REPO/docs/images/steps"; RAW="$T/rec"
W="$T/code"; CONF="$T/home/.config/kitty"
FPS=10
SCENES="getting-started status status-light search buttons streak restart"

tk() { bash "$REPO/scripts/test-kitty.sh" "$@"; }
k() { kitty @ --to "$SOCK" "$@"; }
start() {  # start THEME SIZE: a test kitty with one empty tab (code/webapp)
  NL_TEST_SCENE=none tk start "$1" "$2" >/dev/null
  # Shells that read a bashrc (the ones a restart reopens) get a short prompt with no user or host
  # name in it, no sudo hint from the system bashrc, and the folder as their title (as kitty's
  # shell integration does). (A shell that sets no title is named by its folder in the sidebar anyway.)
  cat > "$T/home/.bashrc" <<'RC'
PS1='\W \$ '
PROMPT_COMMAND='printf "\e]2;%s\a" "$PWD"'
RC
  : > "$T/home/.hushlogin"
  sleep 1.5
}
shell_tab() {  # shell_tab FOLDER [command]: prints the window id
  local id; id="$(k launch --type=tab --cwd "$1" bash --norc)"; sleep 0.3
  [ -z "${2:-}" ] || k send-text --match "id:$id" "$2"$'\n'
  echo "$id"
}
agent_tab() {  # agent_tab FOLDER TITLE [claude|omp]: an idle fake agent (looks like one to the sidebar)
  shell_tab "$1" "NOWAIT=1 st title '✳ $2'; AGENT=${3:-claude} st idle"
}
pty() {  # pty WINDOW_ID: the window's terminal device
  local pid
  pid="$(k ls | python3 -c 'import json, sys
for o in json.load(sys.stdin):
    for t in o["tabs"]:
        for w in t["windows"]:
            if w["id"] == int(sys.argv[1]): print(w["pid"])' "$1")"
  readlink "/proc/$pid/fd/0"
}
state() {  # state WINDOW_ID working|done|blocked|error: what Claude Code reports to kitty
  printf '\e]7501;id=a:state=%s\a' "$2" > "$(pty "$1")"
}
say() { printf '%s\r\n' "$2" > "$(pty "$1")"; }    # say WINDOW_ID TEXT: output in that tab
btn() { grep "^button $1: " "$T/state/sidebar.txt" | cut -d' ' -f3-; }   # btn new → "X Y"
click() { python3 "$REPO/scripts/xclick.py" "$DISP" "$1" "$2" >/dev/null; }
tab_y() { echo $((40 + ($1 - 1) * 60 + 10)); }       # the first line of tab N (default font)
home() { k focus-tab --match index:0; sleep 0.5; }

rec() {  # rec NAME W H SECONDS [mouse]: start recording the top-left W×H of the display
  mkdir -p "$RAW"; REC_NAME="$1"
  ffmpeg -loglevel error -y -f x11grab -draw_mouse "$([ "${5:-}" = mouse ] && echo 1 || echo 0)" \
    -framerate "$FPS" -video_size "$2x$3" -i "$DISP+0,0" -t "$4" -c:v ffv1 "$RAW/$1.mkv" &
  REC_PID=$!; sleep 0.8
}
finish() {  # finish SCALE: wait for the recording, then make the GIF (SCALE 2 = sidebar, pixels doubled)
  wait "$REC_PID" || true                  # (ffmpeg stopped early exits non-zero)
  local vf="fps=$FPS"; [ "${1:-1}" = 1 ] || vf="$vf,scale=iw*$1:ih*$1:flags=neighbor"
  mkdir -p "$OUT"
  ffmpeg -loglevel error -y -i "$RAW/$REC_NAME.mkv" -vf "$vf,palettegen=max_colors=256:stats_mode=full" "$RAW/$REC_NAME.png"
  ffmpeg -loglevel error -y -i "$RAW/$REC_NAME.mkv" -i "$RAW/$REC_NAME.png" \
    -lavfi "$vf[v];[v][1:v]paletteuse=dither=none:diff_mode=rectangle" "$OUT/$REC_NAME.gif"
  printf '%-22s %4s KB\n' "$REC_NAME.gif" "$(( $(stat -c %s "$OUT/$REC_NAME.gif") / 1024 ))"
}
still() {  # still SECONDS NAME: a 2x PNG of the sidebar at that moment of the last recording
  mkdir -p "$STEPS"
  ffmpeg -loglevel error -y -ss "$1" -i "$RAW/$REC_NAME.mkv" -frames:v 1 \
    -vf "scale=iw*2:ih*2:flags=neighbor" "$STEPS/$2.png"
}
side_h() { echo $((40 + $1 * 60 + 50)); }        # sidebar height for N tabs (+ New tab and the quest)

# A fresh tab list: two tabs start working, one finishes (sparkle, ✓, the cat sings), another
# needs you (amber pulse, =O.O= !, ⚠1 in the search row), and Ctrl+Alt+U goes there.
scene_getting-started() {
  start dark 960x600
  a="$(agent_tab "$W/api" "Write release notes")"
  b="$(agent_tab "$W/webapp" "Fix the login bug")"
  c="$(agent_tab "$W/api" "Migrate database schema")"
  home; sleep 1.5
  rec getting-started 310 "$(side_h 4)" 13.5
  sleep 0.7
  state "$a" working; sleep 0.4; state "$b" working; sleep 0.4; state "$c" working; sleep 1.5
  state "$a" done; sleep 4.2                 # the burst lands on ✓; the cat sings ♪ for 4 s
  state "$c" blocked; sleep 3                # pulses for 6 s; ⚠1 in the search row
  k action launch --type=background --allow-remote-control python3 "$CONF/tab-finder.py" waiting
  finish 2
  still 0.5 1-fresh; still 2.5 2-working; still 4.2 3-done; still 8.2 4-needs-you; still 12.8 5-jumped
}

# Every state at once, aged a minute so the times show; then one finishes, one needs you, one
# gets new output.
scene_status() { status_in dark status; }
scene_status-light() { status_in light status-light; }
status_in() {
  start "$1" 960x700
  shell_tab "$W/webapp" "npm run build" >/dev/null
  shell_tab "$W/api" "AGENT=omp st title '⠋ omp: refactor the parser'" >/dev/null
  w="$(agent_tab "$W/ml-pipeline/training" "Fix the login bug")"
  d="$(agent_tab "$W/api" "Write release notes")"
  b="$(agent_tab "$W/webapp" "Migrate database schema")"
  e="$(agent_tab "$W/webapp" "Deploy to staging")"
  n="$(shell_tab "$W/notes")"
  home; sleep 1
  state "$w" working; state "$d" working; state "$e" error
  echo "  ($2: waiting a minute so the elapsed times show)"
  sleep 62
  rec "$2" 310 "$(side_h 8)" 11
  sleep 1; state "$d" done; sleep 2.5; say "$n" "new output"; sleep 1.5; state "$b" blocked
  finish 2
}

# Ctrl+Shift+Space: typing narrows the list, Tab cycles the filters, Enter goes there.
scene_search() {
  start dark 960x520
  shell_tab "$W/webapp" "npm run build" >/dev/null
  w="$(agent_tab "$W/webapp" "Fix the login bug")"
  d="$(agent_tab "$W/api" "Write release notes")"
  b="$(agent_tab "$W/api" "Migrate database schema")"
  e="$(agent_tab "$W/webapp" "Deploy to staging")"
  shell_tab "$W/notes" >/dev/null
  home; sleep 1
  state "$w" working; state "$d" working; sleep 1; state "$d" done; state "$b" blocked; state "$e" error
  say "$b" "  Edit db/schema.sql (add column users.last_seen)?"; say "$b" "  1. Yes   2. Yes, and don't ask again   3. No"
  sleep 6.5                                  # past the pulse
  rec search 960 520 15
  sleep 0.5
  box="$(k launch --type=overlay --allow-remote-control --title current python3 "$CONF/tab-finder.py" search)"
  sleep 1.2
  for ch in a p i; do k send-text --match "id:$box" "$ch"; sleep 0.35; done
  sleep 1.2
  for _ in 1 2 3; do k send-text --match "id:$box" $'\x7f'; sleep 0.15; done
  sleep 0.6
  for _ in 1 2 3 4; do k send-text --match "id:$box" $'\t'; sleep 1.1; done
  for ch in m i g r; do k send-text --match "id:$box" "$ch"; sleep 0.4; done
  sleep 1.2; k send-text --match "id:$box" $'\r'
  finish 1
}

# The search row's + opens a tab, the × closes the tab you're on, a click goes to a tab.
scene_buttons() {
  start dark 960x600
  a="$(agent_tab "$W/api" "Write release notes")"
  b="$(agent_tab "$W/webapp" "Fix the login bug")"
  shell_tab "$W/notes" >/dev/null
  home; state "$b" working; sleep 1.5
  rec buttons 310 "$(side_h 5)" 11 mouse
  click 150 "$(tab_y 1)"; sleep 0.8          # (the pointer starts in view, on the tab you're on)
  read -r x y <<< "$(btn new)"; click "$x" "$y"; sleep 2
  read -r x y <<< "$(btn close)"; click "$x" "$y"; sleep 2
  click 150 "$(tab_y 3)"; sleep 2.5
  click 150 "$(tab_y 2)"
  finish 2
}

# Three tabs finish one after another: the chime climbs and the cat sings ♪, ♪♪, ♪♪♪.
scene_streak() {
  start dark 960x600
  a="$(agent_tab "$W/api" "Write release notes")"
  b="$(agent_tab "$W/webapp" "Fix the login bug")"
  c="$(agent_tab "$W/notes" "Summarise the meeting")"
  home; sleep 1
  state "$a" working; state "$b" working; state "$c" working; sleep 1.5
  rec streak 310 "$(side_h 4)" 11.5
  sleep 1.2; state "$a" done; sleep 2.5; state "$b" done; sleep 2.5; state "$c" done
  finish 2
}

# Split tabs before a restart, the window closing, and the same tabs and splits back.
scene_restart() {
  start dark 960x520
  sp="$W/split"; mkdir -p "$sp/frontend" "$sp/tests" "$sp/docs"
  one="$(k ls | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["tabs"][0]["windows"][0]["id"])')"
  k send-text --match "id:$one" $'exec bash\n'; sleep 0.5    # the prompt the reopened shells get
  k send-text --match "id:$one" $'clear\n'
  r="$(k launch --match "id:$one" --location=vsplit --cwd "$sp/tests" bash)"
  k launch --match "id:$r" --location=hsplit --cwd "$sp/docs" bash >/dev/null
  k set-tab-title --match "id:$one" "frontend + tests"
  t2="$(k launch --type=tab --cwd "$W/api" bash)"
  k launch --match "id:$t2" --location=hsplit --cwd "$W/api" bash >/dev/null; sleep 0.3
  k send-text --match "id:$t2" $'claude --resume 4f2a-made-up\n'
  k set-tab-title --match "id:$t2" "api with Claude"
  k launch --type=tab --cwd "$W/notes" bash >/dev/null
  home; k focus-window --match "id:$one"; sleep 1.5
  rec restart 960 520 30
  sleep 2.5
  tk relaunch >/dev/null 2>&1 || { echo "restart: the relaunch failed" >&2; }
  sleep 3; kill -INT "$REC_PID" 2>/dev/null || true
  finish 1
}

cmd="${1:-}"
case "$cmd" in
list) echo "$SCENES" | tr ' ' '\n' ;;
all|"") [ -n "$cmd" ] || { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
  for s in $SCENES; do "scene_$s"; done; tk stop ;;
*) for s in "$@"; do
     case " $SCENES " in *" $s "*) ;; *) echo "unknown: $s (bash scripts/record.sh list)" >&2; exit 2 ;; esac
   done
   for s in "$@"; do "scene_$s"; done; tk stop ;;
esac
