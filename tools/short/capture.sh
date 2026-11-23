#!/usr/bin/env bash
# capture.sh — record the YouTube Short's takes live from the hidden test kitty (Xvfb display :97,
# its own socket, stubbed sounds; see scripts/test-kitty.sh). Nothing reaches your real kitty,
# desktop or speakers. Reuses the helpers in scripts/record.sh (fake agents, escape-code states,
# the neutral prompt) and presses the real shortcuts with scripts/xkey.py.
#   bash tools/short/capture.sh WORK_DIR [take1 take2]
# For each take, WORK_DIR gets:
#   NAME.mkv        the whole test display, lossless (ffv1), FPS frames a second
#   NAME.meta.json  when the first frame was grabbed, the captions, keys, state changes and close-up
#                   targets (seconds into the take), and the sounds the stubs logged (same clock)
#   NAME.stub.log   the raw stub log (paplay / gdbus calls with their times of day)
#   NAME.text.txt   every window's text at the end of the take, for the privacy check
# Then: python3 tools/short/compose_short.py WORK_DIR OUT.mp4
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/record.sh
source "$HERE/../../scripts/record.sh"      # REPO T DISP SOCK W CONF; start agent_tab shell_tab state say k tk home
WORK="$(mkdir -p "${1:?usage: capture.sh WORK_DIR [take1 take2]}" && cd "$1" && pwd)"; shift
FPS=30
SIZE=1080x480                                # the app window in the Short, 1:1 (no scaling)
FONT=12                                      # kitty's default: the sidebar is 310 px wide
CROP="400 300"                               # the close-up's largest source box (shown at 2x)
TAKES="${*:-take1 take2}"

ev() { printf '%s\t%s\n' "$(date +%s.%N)" "$*" >> "$WORK/$TAKE.events"; }   # ev KIND ARGS…
beat() { ev beat "$1"$'\x1f'"${2:-}"; }   # beat "Caption|second line" ["Ctrl+Alt+U"]: a new caption from now
focus() { ev focus "$@"; }                   # focus X Y [WIDTH]: the close-up's source box from now (display px)
key() { ev key "$*"; python3 "$REPO/scripts/xkey.py" "$DISP" "$@"; }        # a real key press
type_text() { ev type "$1"; for ((i = 0; i < ${#1}; i++)); do python3 "$REPO/scripts/xkey.py" "$DISP" --type "${1:i:1}"; sleep 0.28; done; }
set_state() { ev state "$1" "$2"; state "$1" "$2"; }
first_window() { k ls | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["tabs"][0]["windows"][0]["id"])'; }

setup() {  # setup: a test kitty for the Short, quests off (no badge interrupts the story)
  start dark "$SIZE" "$FONT"
  touch "$CONF/quests-off"
  move_pointer
}
move_pointer() {  # keys go to the window under the pointer (no window manager); park it on the pane
  python3 - "$DISP" <<'PY'
import ctypes, sys
x11 = ctypes.CDLL("libX11.so.6"); xtst = ctypes.CDLL("libXtst.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
d = ctypes.c_void_p(x11.XOpenDisplay(sys.argv[1].encode()))
xtst.XTestFakeMotionEvent(d, -1, 1070, 470, 0); x11.XFlush(d); x11.XCloseDisplay(d)
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
  python3 - "$WORK" "$TAKE" "$FPS" "$SIZE" "$CROP" <<'PY'
import datetime, json, os, re, sys
work, take, fps, size, crop = sys.argv[1:6]
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
        v = [int(n) for n in rest.split()]
        e["x"], e["y"] = v[0], v[1]
        if len(v) > 2:
            e["w"] = v[2]
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
cw, ch = (int(v) for v in crop.split())
meta = {"take": take, "video": take + ".mkv", "roll_epoch": roll, "fps": int(fps), "size": [w, h],
        "crop": [cw, ch], "events": events, "sounds": sounds}
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
  roll take1
  focus 0 0 310
  beat "Many AI coding sessions.|One window."
  sleep 3.6
  beat "Finished? A sparkle|and a quiet chime."
  sleep 0.5; set_state "$c" done; sleep 4.1
  beat "Needs you?|You can't miss it."
  sleep 0.5; set_state "$b" blocked; sleep 3.6
  beat "Ctrl+Alt+U jumps there." "Ctrl+Alt+U"
  sleep 0.9; key ctrl+alt+u; sleep 2.6
  beat "Find any tab, fast." "Ctrl+Shift+Space"
  sleep 0.6; key ctrl+shift+space; sleep 0.8
  focus 320 30 400
  sleep 0.4; type_text api; sleep 0.9
  key Tab; sleep 0.9; key Tab; sleep 0.9; key Tab; sleep 1.2
  key Return; sleep 0.3
  focus 0 0 310
  sleep 2
  cut_
}

# Take 2 (a fresh kitty, so the streak starts at one): three tabs finish in a row, then the
# restart brings every tab and split back.
take_take2() {
  setup
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
  roll take2
  focus 0 0 310
  beat "Finishes in a row|climb a tune."
  sleep 0.8; set_state "${ids[0]}" done; sleep 2.1; set_state "${ids[1]}" done; sleep 2.1
  set_state "${ids[2]}" done; sleep 3.4
  beat "Restart kitty,|keep every tab and split."
  sleep 1.2
  ev relaunch start
  tk relaunch > "$WORK/take2.relaunch.log" 2>&1 || echo "take2: the relaunch failed (see $WORK/take2.relaunch.log)" >&2
  ev relaunch done
  move_pointer
  sleep 3
  cut_
}

for t in $TAKES; do
  case "$t" in take1|take2) "take_$t" ;; *) echo "unknown take: $t (take1 take2)" >&2; exit 2 ;; esac
done
tk stop
