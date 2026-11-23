#!/usr/bin/env bash
# install.sh — copy NineLives' kitty config (config/, with sounds/) into ~/.config/kitty. Any file it would
# overwrite is backed up first (<file>.bak-<date-time>); files that are already the same are left
# alone. Of each file's backups, the newest 3 and the very oldest (likely your config from before
# NineLives) are kept. Then the result is checked with kitty's own config parser.
#   bash scripts/install.sh            install
#   bash scripts/install.sh --dry-run  only show what would change
# Another target folder: KITTY_CONFIG_DIRECTORY=/path bash scripts/install.sh
# Keep more or fewer backups: NL_KEEP_BACKUPS=5 (or all) bash scripts/install.sh
# macOS (new, not yet tried on a real Mac): it also makes a .wav of each sound (macOS's afplay can't
# play .oga), with scripts/make-sounds.py; and finds kitty in kitty.app when it isn't on PATH.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/../config" && pwd)"
REPO="$(dirname "$SRC")"
DEST="${KITTY_CONFIG_DIRECTORY:-${XDG_CONFIG_HOME:-$HOME/.config}/kitty}"
DRY=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  "") ;;
  *) echo "usage: bash scripts/install.sh [--dry-run]" >&2; exit 2 ;;
esac
STAMP="$(date +%Y%m%d-%H%M%S)"
OLD_KITTY=""
KEEP="${NL_KEEP_BACKUPS:-3}"
case "$KEEP" in all) ;; *[!0-9]*|""|0) echo "NL_KEEP_BACKUPS: a number from 1, or all" >&2; exit 2 ;; esac
pruned=0
prune() {  # prune DEST-FILE [PENDING]: delete its own backups (<file>.bak-YYYYMMDD-HHMMSS) except the
  # newest $KEEP and the very oldest (likely your config from before NineLives). PENDING=1 in a dry
  # run counts the backup this update would make.
  [ "$KEEP" = all ] && return 0
  local all old b n
  all="$(find "$(dirname "$1")" -maxdepth 1 -type f -name "$(basename "$1").bak-[0-9]*" 2>/dev/null \
         | grep -E '\.bak-[0-9]{8}-[0-9]{6}$' | sort -r)" || true
  n=$((KEEP - ${2:-0}))                                   # the pending one takes a "newest" slot
  old="$(printf '%s\n' "$all" | sed '$d' | tail -n +$((n + 1)))"   # sed '$d': spare the oldest
  while IFS= read -r b; do
    [ -n "$b" ] || continue
    pruned=$((pruned + 1))
    if [ "$DRY" = 1 ]; then echo "  prune   ${b#"$DEST"/}"; else rm -f -- "$b"; fi
  done <<< "$old"
}

KITTY="$(command -v kitty || true)"
for app in /Applications "$HOME/Applications"; do     # macOS: kitty.app isn't on PATH outside kitty
  [ -n "$KITTY" ] || { [ -x "$app/kitty.app/Contents/MacOS/kitty" ] && KITTY="$app/kitty.app/Contents/MacOS/kitty"; } || true
done
# (the version compared with awk: macOS's older sort has no -V)
if [ -n "$KITTY" ] && ver="$("$KITTY" --version 2>/dev/null | awk '{print $2}')" && [ -n "$ver" ]; then
  if ! awk -v v="$ver" 'BEGIN { split(v, a, "."); exit !(a[1] + 0 > 0 || a[2] + 0 >= 50) }'; then
    echo "Warning: kitty $ver found; NineLives needs 0.50 or newer (sidebar, tab dragging)." >&2
    OLD_KITTY="$ver"
  fi
else
  echo "Warning: kitty not found on PATH." >&2
fi

echo "Installing into $DEST"
[ "$DRY" = 1 ] || mkdir -p "$DEST"
changed=0
while IFS= read -r f; do          # every file, sounds/ included (not __pycache__)
  name="${f#"$SRC"/}"
  dest="$DEST/$name"
  if [ -e "$dest" ] && cmp -s "$f" "$dest"; then
    echo "  same    $name"
    prune "$dest"
    continue
  fi
  changed=$((changed + 1))
  pending=0
  if [ -e "$dest" ]; then
    echo "  update  $name   (old one saved as $name.bak-$STAMP)"
    if [ "$DRY" = 1 ]; then pending=1; else cp -p "$dest" "$dest.bak-$STAMP"; fi
  else
    echo "  new     $name"
  fi
  [ "$DRY" = 1 ] || { mkdir -p "$(dirname "$dest")"; cp -p "$f" "$dest"; }
  prune "$dest" "$pending"
done < <(find "$SRC" -type f ! -path '*/__pycache__/*' ! -name '*.pyc' | sort)

# macOS: older ones can't play .oga (macOS 15 can), so every sound also gets a .wav, made from scratch by
# make-sounds.py (no backup: it is NineLives' own, made the same way every time)
if [ "$(uname -s)" = Darwin ]; then
  WAVS="$(mktemp -d)"; trap 'rm -rf "$WAVS"' EXIT
  if python3 "$REPO/scripts/make-sounds.py" --wav "$WAVS" >/dev/null; then
    for f in "$WAVS"/*.wav; do
      name="sounds/$(basename "$f")"; dest="$DEST/$name"
      if [ -e "$dest" ] && cmp -s "$f" "$dest"; then echo "  same    $name"; continue; fi
      changed=$((changed + 1))
      if [ -e "$dest" ]; then echo "  update  $name"; else echo "  new     $name   (for macOS's afplay)"; fi
      [ "$DRY" = 1 ] || { mkdir -p "$DEST/sounds"; cp "$f" "$dest"; }
    done
  else
    echo "Warning: couldn't make the .wav sounds macOS plays (python3 scripts/make-sounds.py --wav); the tabs will use macOS's own sounds." >&2
  fi
fi

if [ "$DRY" = 1 ]; then
  echo "Dry run: $changed file(s) would change, $pruned old backup(s) would be removed. Nothing was touched."
  exit 0
fi
echo "$changed file(s) changed.$( ((pruned)) && echo " Removed $pruned old backup(s) (keeping the newest $KEEP of each).")"

if [ -n "$OLD_KITTY" ]; then
  # an older kitty's parser doesn't know 0.50 settings (e.g. cursor_blink_interval with easing)
  echo "Config check skipped: kitty $OLD_KITTY can't read kitty 0.50 settings."
elif [ -n "$KITTY" ]; then
  if out="$(NL_CONF="$DEST/kitty.conf" "$KITTY" +runpy \
      'import os; from kitty.config import load_config; load_config(os.environ["NL_CONF"])' 2>&1)" && [ -z "$out" ]; then
    echo "Config check: OK"
  else
    echo "Config check found problems:" >&2
    echo "$out" >&2
    exit 1
  fi
fi

if [ "$changed" -gt 0 ]; then
  echo "Next: press Ctrl+Shift+F5 in kitty for kitty.conf changes; restart kitty for tab_bar.py"
  echo "      (bash scripts/kitty-relaunch.sh --when-idle keeps every tab)."
fi
