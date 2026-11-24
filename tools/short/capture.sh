#!/usr/bin/env bash
# capture.sh — record the YouTube Short's takes live from the hidden test kitty (Xvfb display :97,
# its own socket, stubbed sounds; see scripts/test-kitty.sh). Nothing reaches your real kitty,
# desktop or speakers. Reuses the helpers in scripts/record.sh (fake agents, escape-code states,
# the neutral prompt) and presses the real shortcuts with scripts/xkey.py.
#   bash tools/short/capture.sh WORK_DIR [take1 take2]
# For each take, WORK_DIR gets:
#   NAME.mkv        the whole test display, lossless (ffv1), FPS frames a second
#   NAME.meta.json  when the first frame was grabbed, the captions, keys, state changes and close-up
#                   boxes (seconds into the take), the sounds the stubs logged (same clock) and the
#                   sidebar's cell grid
#   NAME.stub.log   the raw stub log (paplay / gdbus calls with their times of day)
#   NAME.text.txt   every window's text at the end of the take, for the privacy check
# Then: python3 tools/short/compose_short.py WORK_DIR OUT.mp4
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/record.sh
source "$HERE/../../scripts/record.sh"      # REPO T DISP SOCK W CONF; start agent_tab shell_tab state say k tk home
WORK="$(mkdir -p "${1:?usage: capture.sh WORK_DIR [take1 take2]}" && cd "$1" && pwd)"; shift
FPS=30
FONT=14                                      # bigger than kitty's 12, for phones: 11x24 px cells
SIZE=1080x384                                # the app window in the Short, 1:1 (no scaling): 16 rows,
                                             # so four tabs and + New tab (15 rows) fit the close-up at 2x
TAKES="${*:-take1 take2}"
FAILED=""

ev() { printf '%s\t%s\n' "$(date +%s.%N)" "$*" >> "$WORK/$TAKE.events"; }   # ev KIND ARGS…
beat() { ev beat "$1"$'\x1f'"${2:-}"; }   # beat "Caption|second line" ["Ctrl+Alt+U"]: a new caption from now
focus() { ev focus "$@"; }                   # focus X Y WIDTH HEIGHT: the close-up's source box from now (display px)
key() { ev key "$*"; python3 "$REPO/scripts/xkey.py" "$DISP" "$@"; }        # a real key press
type_text() { ev type "$1"; for ((i = 0; i < ${#1}; i++)); do python3 "$REPO/scripts/xkey.py" "$DISP" --type "${1:i:1}"; sleep 0.28; done; }
set_state() { ev state "$1" "$2"; state "$1" "$2"; }
first_window() { k ls | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["tabs"][0]["windows"][0]["id"])'; }

setup() {  # setup [dark|light]: a test kitty for the Short, quests off (no badge interrupts the story)
  start "${1:-dark}" "$SIZE" "$FONT"
  touch "$CONF/quests-off"
  # The restart (take2) starts a new kitty that reads kitty.conf, not start's -o options: give it the
  # same font and window size, or it comes back at font 12 and another size.
  sed -i -e "s/^font_size .*/font_size $FONT/" -e "s/^remember_window_size .*/remember_window_size no/" \
    -e "s/^initial_window_width .*/initial_window_width ${SIZE%x*}/" \
    -e "s/^initial_window_height .*/initial_window_height ${SIZE#*x}/" "$CONF/kitty.conf"
  move_pointer
}
geometry() {  # geometry: the sidebar's cell grid from sidebar.txt → GEOM="LEFT TOP CELL_W CELL_H COLUMNS"
  GEOM=""
  for _ in $(seq 1 30); do
    GEOM="$(sed -n 's/^cells: //p' "$T/state/sidebar.txt" 2>/dev/null)" || true   # (not written yet: try again)
    [ -n "$GEOM" ] && break; sleep 0.2
  done
  [ -n "$GEOM" ] || { echo "${TAKE:-capture.sh}: no cell grid in sidebar.txt" >&2; exit 1; }
  read -r _ _ CW CH COLS <<< "$GEOM"
}
# Close-up boxes (display px, "X Y WIDTH HEIGHT"), from the cell grid so they follow the font size.
# compose_short.py shows a box as big as fits (2x at most).
sidebar_box() {  # sidebar_box N: the whole sidebar with N tabs: the search row, 3 rows a tab, + New tab
  echo "0 0 $((COLS * CW)) $(((3 * $1 + 3) * CH))"
}
search_box() {  # the search box over the pane: from its prompt to the folder column's end, and its key hints
  local w="${SIZE%x*}" h="${SIZE#*x}" x=$(((COLS + 1) * CW)) y=$((CH * 3 / 2))
  echo "$x $y $((w - 2 * CW - x)) $((h - y))"
}
move_pointer() {  # move_pointer [X Y]: keys go to the window under the pointer (no window manager);
  # park it on the pane (bottom right unless told)
  python3 - "$DISP" "${1:-$((${SIZE%x*} - 10))}" "${2:-$((${SIZE#*x} - 10))}" <<'PY'
import ctypes, sys
x11 = ctypes.CDLL("libX11.so.6"); xtst = ctypes.CDLL("libXtst.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
d = ctypes.c_void_p(x11.XOpenDisplay(sys.argv[1].encode()))
xtst.XTestFakeMotionEvent(d, -1, int(sys.argv[2]), int(sys.argv[3]), 0); x11.XFlush(d); x11.XCloseDisplay(d)
PY
}
roll() {  # roll NAME: start recording the whole display; waits for the first frame
  TAKE="$1"; : > "$WORK/$TAKE.events"
  ffmpeg -hide_banner -y -f x11grab -draw_mouse 0 -framerate "$FPS" -video_size "$SIZE" -i "$DISP+0,0" \
    -t 90 -c:v ffv1 "$WORK/$TAKE.mkv" > "$WORK/$TAKE.ffmpeg.log" 2>&1 &
  ROLL_PID=$!
  for _ in $(seq 1 50); do grep -q " start: " "$WORK/$TAKE.ffmpeg.log" && break; sleep 0.1; done
  ev roll "$(sed -n 's/.* start: \([0-9.]*\).*/\1/p' "$WORK/$TAKE.ffmpeg.log" | head -1)"
}
cut_() {  # cut: stop recording, keep the stub log and the windows' text, write NAME.meta.json
  ev end; sleep 0.3
  kill -INT "$ROLL_PID" 2>/dev/null || true; wait "$ROLL_PID" 2>/dev/null || true
  cp "$T/stub.log" "$WORK/$TAKE.stub.log" 2>/dev/null || : > "$WORK/$TAKE.stub.log"
  k ls | python3 -c 'import json,sys
print(" ".join(str(w["id"]) for o in json.load(sys.stdin) for t in o["tabs"] for w in t["windows"]))' \
    | tr ' ' '\n' | while read -r id; do
        echo "=== window $id"; k get-text --match "id:$id" --extent all 2>/dev/null || true
      done > "$WORK/$TAKE.text.txt"
  k ls > "$WORK/$TAKE.ls.json" 2>/dev/null || true
  python3 - "$WORK" "$TAKE" "$FPS" "$SIZE" "$GEOM" <<'PY'
import datetime, json, os, re, sys
work, take, fps, size, geom = sys.argv[1:6]
rows = [l.rstrip("\n").split("\t", 1) for l in open(os.path.join(work, take + ".events"), encoding="utf-8")]
rolls = [a[5:].strip() for t, a in rows if a.startswith("roll ")]
roll = float(rolls[0]) if rolls and rolls[0] else float(rows[0][0])   # ffmpeg's first frame, else the start
day = datetime.datetime.fromtimestamp(roll).date()
events = []
for t, a in rows:
    kind, _, rest = a.partition(" ")
    if kind == "roll":
        continue
    e = {"t": round(float(t) - roll, 3), "kind": kind}
    if kind == "beat":
        parts = rest.split("\x1f")
        e["text"] = parts[0]
        e["keys"] = parts[1] if len(parts) > 1 else ""
    elif kind == "focus":
        e["x"], e["y"], e["w"], e["h"] = (int(n) for n in rest.split())
    else:
        e["args"] = rest
    events.append(e)
sounds = []
for line in open(os.path.join(work, take + ".stub.log"), encoding="utf-8"):
    m = re.match(r"(\d\d):(\d\d):(\d\d\.\d+) paplay --volume=(\d+) (\S+)", line)
    if not m:
        continue
    h, mi, s = int(m[1]), int(m[2]), float(m[3])
    when = datetime.datetime.combine(day, datetime.time(h, mi)) .timestamp() + s
    sounds.append({"t": round(when - roll, 3), "file": os.path.basename(m[5]), "volume": int(m[4]) / 65536})
w, h = (int(v) for v in size.split("x"))
left, top, cw, ch, cols = (int(v) for v in geom.split())
meta = {"take": take, "video": take + ".mkv", "roll_epoch": roll, "fps": int(fps), "size": [w, h],
        "cells": {"left": left, "top": top, "w": cw, "h": ch, "cols": cols}, "events": events, "sounds": sounds}
json.dump(meta, open(os.path.join(work, take + ".meta.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(f"{take}: {events[-1]['t']:.1f} s, {len(sounds)} sound(s): " + ", ".join(f"{s['file']}@{s['t']:.2f}" for s in sounds))
PY
}

# Take 1: four sessions at work; one finishes, one needs you, Ctrl+Alt+U goes there, and
# Ctrl+Shift+Space finds a tab.
take_take1() {
  setup
  a="$(first_window)"                                         # tab 1, the one on screen
  k send-text --match "id:$a" "NOWAIT=1 st title '✳ Fix the login bug'; AGENT=claude st idle"$'\n'; sleep 0.4
  shell_tab "$W/api" "AGENT=omp st title '⠋ omp: refactor the parser'" >/dev/null
  b="$(agent_tab "$W/api" "Migrate database schema")"
  c="$(agent_tab "$W/api" "Write release notes")"
  sleep 0.5
  say "$a" "  ● Reading src/auth/login.ts"; say "$a" "  ● The session cookie expires before the redirect."
  say "$a" "  ● Editing src/auth/session.ts …"
  say "$b" "  ● Planned 3 changes to db/schema.sql"
  say "$b" ""; say "$b" "  Edit db/schema.sql (add column users.last_seen)?"
  say "$b" "    1. Yes   2. Yes, and don't ask again   3. No"
  home
  state "$a" working; state "$b" working; state "$c" working; sleep 2
  geometry
  roll take1
  focus $(sidebar_box 4)
  beat "Many AI coding sessions.|One window."
  sleep 3.6
  beat "Finished? A sparkle|and a quiet chime."
  sleep 0.5; set_state "$c" done; sleep 4.1
  beat "Needs you?|You can't miss it."
  sleep 0.5; set_state "$b" blocked; sleep 3.6
  beat "Ctrl+Alt+U jumps there." "Ctrl+Alt+U"
  sleep 0.9; key ctrl+alt+u; sleep 2.6
  beat "Find any tab, fast." "Ctrl+Shift+Space"
  sleep 0.5; key ctrl+shift+space; sleep 0.5
  focus $(search_box)
  sleep 0.3; type_text api; sleep 0.7
  key Tab; sleep 0.75; key Tab; sleep 0.75; key Tab; sleep 1.0
  key Return; sleep 0.3
  focus $(sidebar_box 4)
  sleep 1.8
  cut_
}

# Take 2 (a fresh kitty, so the streak starts at one; in the light theme): three tabs finish in a
# row, then the restart brings every tab and split back, Claude's ✳ marks included.
take_take2() {
  setup light                                 # the light theme for this take: a clean cut between takes
  sp="$W/split"; mkdir -p "$sp/frontend" "$sp/tests"
  one="$(first_window)"
  k send-text --match "id:$one" $'cd '"$sp/frontend"$' && exec bash\n'; sleep 0.6   # the prompt reopened shells get
  k send-text --match "id:$one" $'clear\n'
  r="$(k launch --match "id:$one" --location=vsplit --cwd "$sp/tests" bash)"
  k set-tab-title --match "id:$one" "frontend + tests"
  ids=()
  for spec in "api|Write release notes|7c1e-made-up" "webapp|Fix the login bug|3b9d-made-up" \
              "notes|Summarise the meeting|a51f-made-up"; do
    IFS='|' read -r dir name sid <<< "$spec"
    id="$(shell_tab "$W/$dir")"
    k send-text --match "id:$id" "claude --resume $sid"$'\n'
    k set-tab-title --match "id:$id" "$name"
    ids+=("$id")
  done
  sleep 0.6
  home; k focus-window --match "id:$one"
  for id in "${ids[@]}"; do state "$id" working; done; sleep 2
  geometry
  # the pointer on the focused (left) pane: kitty's focus_follows_mouse would otherwise hand the
  # focus to the pane under it as the restarted window opens, until the relaunch focuses it back
  move_pointer $(((COLS + 2) * CW)) $((${SIZE#*x} - 10))
  local before; before="$GEOM"
  roll take2
  focus $(sidebar_box 4)
  beat "Finishes in a row|climb a tune."
  sleep 0.8; set_state "${ids[0]}" done; sleep 2.1; set_state "${ids[1]}" done; sleep 2.1
  set_state "${ids[2]}" done; sleep 3.4
  beat "Restart kitty,|keep every tab and split."
  sleep 1.2
  ev relaunch start
  local oldk; oldk="$(sed -n 's/^kitty: //p' "$T/state/sidebar.txt" 2>/dev/null)" || true   # who wrote it so far
  tk relaunch > "$WORK/take2.relaunch.log" 2>&1 || fail "the relaunch failed (see $WORK/take2.relaunch.log)"
  ev relaunch done
  # the restored Claude tabs get their ✳ marks back (v1.0.2), as the new window opens: the take is
  # only good if all three show by the time the relaunch is done (a mark checked while its agent
  # was still starting stayed off until the next redraw, seconds later; tab_bar.py now looks again
  # within half a second, so this is a guard: take again if it fires)
  local marks=0 done_at lay newk; done_at="$(date +%s.%N)"
  for _ in $(seq 1 100); do
    lay="$(cat "$T/state/sidebar.txt" 2>/dev/null)" || lay=""
    newk="$(sed -n 's/^kitty: //p' <<< "$lay")"
    if [ -n "$newk" ] && [ "$newk" != "$oldk" ]; then      # written by the new kitty (its pid), not the old one
      marks="$(sed -n 's/^agents: //p' <<< "$lay" | grep -o '✳' | wc -l)" || true   # no ✳ yet: 0, look again
      [ "${marks:-0}" -ge 3 ] && break
    fi
    sleep 0.1
  done
  if [ "$marks" -ge 3 ]; then
    ev marks back
    local late; late="$(awk -v a="$done_at" -v b="$(date +%s.%N)" 'BEGIN { printf "%.1f", b - a }')"
    awk -v l="$late" 'BEGIN { exit !(l < 0.5) }' \
      || fail "the ✳ marks came back $late s after the relaunch was done (take it again)"
  else fail "only $marks ✳ mark(s) 10 s after the restart"; fi
  geometry
  [ "$GEOM" = "$before" ] || fail "the restarted kitty's cell grid is $GEOM, not $before (font or size changed)"
  sleep 2.2
  cut_
}

fail() { echo "$TAKE: $*" >&2; FAILED="$FAILED $TAKE"; }

trap 'tk stop' EXIT                          # the test kitty goes away however this ends
for t in $TAKES; do
  case "$t" in take1|take2) "take_$t" ;; *) echo "unknown take: $t (take1 take2)" >&2; exit 2 ;; esac
done
[ -z "$FAILED" ] || { echo "capture.sh: check the takes:$FAILED" >&2; exit 1; }
