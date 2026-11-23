#!/usr/bin/env bash
# dev-kitty.sh — a visible "NineLives dev" kitty for trying changes, separate from every other kitty:
# its own config folder (installed from this repo), quest state and remote-control socket. It starts
# muted and sends no desktop notifications; your other kitty windows and ~/.config/kitty are untouched.
#   bash scripts/dev-kitty.sh start      install config/ into the dev folder and open the window
#   bash scripts/dev-kitty.sh reload     reinstall and reload its config in place: no new window, focus
#                                        stays where it is (enough for most tab_bar.py changes)
#   bash scripts/dev-kitty.sh restart    reinstall and reopen it (for changes to the kitty patches;
#                                        the new window takes focus on COSMIC)
#   bash scripts/dev-kitty.sh sound on   let it play sounds (off: mute again)
#   bash scripts/dev-kitty.sh k <kitty @ arguments>    drive it, e.g. k ls
#   bash scripts/dev-kitty.sh stop
# Folder: $NL_DEV_DIR, default ~/.cache/ninelives-dev
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEV="${NL_DEV_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/ninelives-dev}"
CONF="$DEV/config"
SOCK="unix:@ninelives-dev-kitty"
NEW="$HOME/.local/kitty.app/bin/kitty"; [ -x "$NEW" ] || NEW="$(command -v kitty)"
k() { "$NEW" @ --to "$SOCK" "$@"; }

stop() {
  if [ -f "$DEV/kitty.pid" ]; then kill "$(cat "$DEV/kitty.pid")" 2>/dev/null || true; rm -f "$DEV/kitty.pid"; fi
  pkill -f -- "[-]-listen-on ${SOCK}" 2>/dev/null || true      # only the dev kitty's socket
  for _ in $(seq 1 25); do k ls >/dev/null 2>&1 || break; sleep 0.2; done
}

start() {
  mkdir -p "$DEV/state"
  KITTY_CONFIG_DIRECTORY="$CONF" bash "$REPO/scripts/install.sh" >/dev/null
  [ -e "$DEV/sound-on" ] || touch "$CONF/sounds-off"
  # its shells: your ~/.bashrc, then the dev tips.sh (so kitty-sounds etc. use the dev folder)
  printf '[ -r ~/.bashrc ] && . ~/.bashrc\n. "%s/tips.sh"\n' "$CONF" > "$DEV/bashrc"
  # Not this shell's Claude/kitty internals (e.g. CLAUDE_CODE_CHILD_SESSION, KITTY_WINDOW_ID): the
  # dev kitty and its tabs start like one opened from the desktop.
  for v in $(compgen -e | grep -E '^(CLAUDE|KITTY_|NINELIVES_)' || true); do unset "$v"; done
  KITTY_CONFIG_DIRECTORY="$CONF" NINELIVES_STATE="$DEV/state" NINELIVES_QUIET=1 \
    setsid "$NEW" -o allow_remote_control=socket-only --listen-on "$SOCK" \
      -o "shell=bash --rcfile '$DEV/bashrc'" -o confirm_os_window_close=0 \
      --title "NineLives dev" --class ninelives-dev --directory "$REPO" \
      > "$DEV/kitty.log" 2>&1 < /dev/null &
  echo $! > "$DEV/kitty.pid"
  for _ in $(seq 1 40); do k ls >/dev/null 2>&1 && break; sleep 0.25; done
  k ls >/dev/null 2>&1 || { echo "the dev kitty did not start; see $DEV/kitty.log" >&2; exit 1; }
  echo "NineLives dev kitty is open ($("$NEW" --version | cut -d' ' -f2); config: $CONF; $([ -e "$CONF/sounds-off" ] && echo muted || echo 'sound on'))."
}

cmd="${1:-}"; [ $# -gt 0 ] && shift
case "$cmd" in
  start)   if k ls >/dev/null 2>&1; then echo "already open (restart to reload it)"; else start; fi ;;
  reload)  k ls >/dev/null 2>&1 || { echo "not open: bash scripts/dev-kitty.sh start" >&2; exit 1; }
           KITTY_CONFIG_DIRECTORY="$CONF" bash "$REPO/scripts/install.sh" >/dev/null
           [ -e "$DEV/sound-on" ] || touch "$CONF/sounds-off"
           k load-config && echo "dev kitty reloaded (no new window)" ;;
  restart) stop; start ;;
  stop)    stop; echo "dev kitty closed" ;;
  sound)   case "${1:-}" in
             on)  touch "$DEV/sound-on"; rm -f "$CONF/sounds-off"; echo "dev kitty: sound on" ;;
             off) rm -f "$DEV/sound-on"; touch "$CONF/sounds-off"; echo "dev kitty: muted" ;;
             *)   echo "usage: dev-kitty.sh sound on|off" >&2; exit 2 ;;
           esac ;;
  k)       k "$@" ;;
  *)       sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
