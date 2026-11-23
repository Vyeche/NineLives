#!/usr/bin/env bash
# test-kitty.sh — a hidden test kitty for looking at the sidebar. Installs config/ into a throwaway
# folder, starts kitty on a hidden X display (Xvfb) with one tab per status, and takes screenshots
# with ffmpeg. Sounds and notifications go to stubs and quests get their own state folder, so
# nothing reaches your real kitty, speakers or badges. X11 only: the Wayland tab drag and the
# background blur are not exercised.
#   bash scripts/test-kitty.sh start [dark|light] [WIDTHxHEIGHT] [FONT_SIZE]   start it and fill the sidebar
#   bash scripts/test-kitty.sh shot NAME [ffmpeg filter]           screenshot (default: sidebar, 2x)
#   bash scripts/test-kitty.sh k <kitty @ arguments>               drive it, e.g. k focus-tab --match index:6
#   bash scripts/test-kitty.sh sounds                              which sounds it would have played
#   bash scripts/test-kitty.sh relaunch [--dry-run]                kitty-relaunch.sh on this kitty only
#   bash scripts/test-kitty.sh stop
# NL_TEST_SCENE=none starts it with one empty tab instead of one tab per status (scripts/record.sh
# builds its own scenes).
# Files (config copy, screenshots, logs): $NL_TEST_DIR, default ${TMPDIR:-/tmp}/ninelives-test
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
T="${NL_TEST_DIR:-${TMPDIR:-/tmp}/ninelives-test}"
DISP="${NL_TEST_DISPLAY:-:97}"
SOCK="unix:@ninelives-test-kitty"       # never your own kitty's socket
CONF="$T/home/.config/kitty"
k() { kitty @ --to "$SOCK" "$@"; }
tenv() {  # run a command with the test kitty's environment: hidden display, test HOME, stubbed sounds
  env -u WAYLAND_DISPLAY -u KITTY_WINDOW_ID -u KITTY_LISTEN_ON -u KITTY_PID -u KITTY_PUBLIC_KEY \
    -u KITTY_INSTALLATION_DIR -u DBUS_SESSION_BUS_ADDRESS \
    HOME="$T/home" XDG_CACHE_HOME="$T/home/.cache" DISPLAY="$DISP" LIBGL_ALWAYS_SOFTWARE=1 PATH="$T/bin:$PATH" \
    NINELIVES_STATE="$T/state" KITTY_CONFIG_DIRECTORY="$CONF" "$@"
}
stop() {
  for p in kitty xvfb; do
    if [ -f "$T/$p.pid" ]; then kill "$(cat "$T/$p.pid")" 2>/dev/null || true; rm -f "$T/$p.pid"; fi
  done
  # Strays whose pid files are gone (a deleted test folder): only kitties on this test socket and
  # Xvfb on this display. "[-]" keeps the pattern from matching the shell that runs pkill.
  pkill -f -- "[-]-listen-on ${SOCK}" 2>/dev/null || true
  pkill -f "^[X]vfb ${DISP} " 2>/dev/null || true
  sleep 0.3
}
tab() {  # tab FOLDER [command typed into it]
  # Type into the window this launch created (launch prints its id), not "the active window":
  # focus doesn't always follow a new tab on the hidden display, and typing then went to another tab.
  local id
  id="$(k launch --type=tab --cwd "$1" bash --norc)"; sleep 0.3
  if [ -n "${2:-}" ]; then k send-text --match "id:$id" "$2"$'\n'; fi
}

cmd="${1:-}"; [ $# -gt 0 ] && shift
case "$cmd" in
start)
  theme="${1:-dark}"; size="${2:-1100x760}"; font="${3:-}"
  [[ -z "$font" || "$font" =~ ^[0-9]+(\.[0-9]+)?$ ]] || { echo "font size: a number, e.g. 20" >&2; exit 2; }
  case "$theme" in dark|light) ;; *) echo "theme: dark or light" >&2; exit 2 ;; esac
  for need in Xvfb ffmpeg kitty; do command -v "$need" >/dev/null || { echo "needs $need" >&2; exit 1; }; done
  stop
  if k ls >/dev/null 2>&1; then echo "another test kitty still answers on $SOCK; stop it first" >&2; exit 1; fi
  rm -rf "$T/home" "$T/state" "$T/stub.log" "$T/agents.log"
  W="$T/code"                                  # made-up projects: the sidebar shows the last two folders
  mkdir -p "$T/home/.config" "$T/state" "$T/bin" "$T/shots" "$W/webapp" "$W/api" "$W/notes" \
           "$W/ml-pipeline/training" "$W/a-very-long-client-name/inner-project"
  mkdir -p "$W/api/.git" && echo "ref: refs/heads/fix-parser" > "$W/api/.git/HEAD"   # a branch to show
  for c in paplay gdbus notify-send; do     # stubs: no sound, no desktop notification
    printf '#!/bin/sh\necho "$(date +%%T.%%N | cut -c1-12) %s $*" >> "%s/stub.log"\n' "$c" "$T" > "$T/bin/$c"
    chmod +x "$T/bin/$c"
  done
  cat > "$T/bin/st" <<'ST'
#!/usr/bin/env bash
# st title TEXT | st prog PERCENT | st state NAME | st done ; then waits, unless NOWAIT=1
case $1 in
  title) printf '\e]2;%s\a' "$2" ;;
  prog)  ( while :; do printf '\e]9;4;1;%s\a' "$2"; sleep 5; done ) & ;;   # kitty drops stale progress
  state) printf '\e]7501;id=a:state=%s\a' "$2" ;;
  done)  printf '\e]7501;id=a:state=working\a'; sleep 1.5; printf '\e]7501;id=a:state=done\a' ;;
esac
clear
[ -n "${NOWAIT:-}" ] || exec -a "${AGENT:-cat}" cat    # AGENT=claude: looks like claude to the sidebar
ST
  chmod +x "$T/bin/st"
  printf '#!/bin/sh\nexec sleep 600\n' > "$T/bin/npm"; chmod +x "$T/bin/npm"   # "npm run build": a long command
  for c in claude omp; do   # what a relaunch reopens: never the real agents; they log and sit, looking like them
    printf '#!/bin/bash\necho "$(date +%%T) %s $*" >> "%s/agents.log"\nexec -a %s cat -- - "$@"\n' "$c" "$T" "$c" > "$T/bin/$c"
    chmod +x "$T/bin/$c"
  done
  HOME="$T/home" KITTY_CONFIG_DIRECTORY="$CONF" bash "$REPO/scripts/install.sh" >/dev/null
  sed -i "s/^include cosmic-dark.conf/include cosmic-$theme.conf/" "$CONF/kitty.conf"
  rm -f "$CONF"/*-theme.auto.conf           # keep the chosen theme
  Xvfb "$DISP" -screen 0 "${size}x24" >/dev/null 2>&1 & echo $! > "$T/xvfb.pid"
  sleep 1
  tenv setsid kitty -o allow_remote_control=socket-only -o remember_window_size=no \
      -o initial_window_width="${size%x*}" -o initial_window_height="${size#*x}" \
      -o confirm_os_window_close=0 ${font:+-o font_size="$font"} --listen-on "$SOCK" --directory "$W/webapp" \
      bash --norc > "$T/kitty.log" 2>&1 &
  echo $! > "$T/kitty.pid"
  for _ in $(seq 1 40); do k ls >/dev/null 2>&1 && break; sleep 0.25; done
  k ls >/dev/null 2>&1 || { echo "kitty did not start:" >&2; tail -5 "$T/kitty.log" >&2; exit 1; }
  if [ "${NL_TEST_SCENE:-}" = none ]; then echo "Test kitty running ($theme, $size${font:+, font $font}), one empty tab."; exit 0; fi
  # one tab per status
  # one tab per status (status, then where the sidebar gets it from)
  tab "$W/webapp" "npm run build"                                         # plain command running
  tab "$W/api" "AGENT=omp st title '⠋ omp: refactor the parser'"          # spinner in the title
  tab "$W/ml-pipeline/training" "NOWAIT=1 st title 'Downloading model weights'; st prog 42"  # progress
  tab "$W/webapp" "NOWAIT=1 st title '✳ Fix the login bug'; AGENT=claude st state working"            # Claude working
  tab "$W/api" "NOWAIT=1 st title '✳ Write release notes'; AGENT=claude st done"                      # done
  tab "$W/api" "NOWAIT=1 st title '✳ Migrate database schema to v2'; AGENT=claude st state blocked"   # needs you
  tab "$W/webapp" "NOWAIT=1 st title '✳ Deploy to staging'; AGENT=claude st state error"              # error
  tab "$W/notes" "sleep 2; echo new output"                               # ● new output
  tab "$W/a-very-long-client-name/inner-project"
  k set-tab-title --match "index:9" "A renamed tab with quite a long title here"
  tab "$W/notes" "st title '日本語のメモ 🚀 wide characters'"
  k focus-tab --match index:0
  echo "Test kitty running ($theme, $size${font:+, font $font}). Screenshot: bash scripts/test-kitty.sh shot NAME"
  ;;
shot)
  name="${1:?shot NAME}"; vf="${2:-crop=330:ih:0:0,scale=iw*2:ih*2:flags=neighbor}"
  ffmpeg -loglevel error -y -f x11grab -i "$DISP" -frames:v 1 -vf "$vf" "$T/shots/$name.png"
  echo "$T/shots/$name.png"
  ;;
k) k "$@" ;;
relaunch)
  # The real restart script, pointed at this kitty (NL_KITTY_SOCKET) with this kitty's environment,
  # so the new kitty opens on the hidden display with the test config. Waits until it's done.
  log="$T/home/.cache/ninelives/kitty-relaunch.log"
  mkdir -p "$(dirname "$log")"; : > "$log"
  tenv NL_KITTY_SOCKET="$SOCK" bash "$REPO/scripts/kitty-relaunch.sh" "$@"
  case "${1:-}" in --dry-run|--status) exit 0 ;; esac
  for _ in $(seq 1 150); do grep -qE "done: |FAILED" "$log" && break; sleep 0.2; done
  cat "$log"
  pgrep -f -- "[-]-listen-on ${SOCK}" | head -1 > "$T/kitty.pid" || true   # the new kitty
  grep -q "done: " "$log"
  ;;
sounds) sed "s|$T/home/.config/kitty/sounds/||; s|/usr/share/sounds/freedesktop/stereo/|classic:|" "$T/stub.log" 2>/dev/null ;;
stop) stop ;;
*) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
