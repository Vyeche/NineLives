#!/usr/bin/env bash
# uninstall.sh — take NineLives out of ~/.config/kitty again. It only touches the files install.sh
# puts there (the names in config/) and their backups (<file>.bak-<date-time>):
#   - an installed file that is a NineLives version (this repo's file, or any version in its git
#     history) is removed; one you changed is kept and listed;
#   - backups that are NineLives versions are removed; the oldest other backup of a file (your own
#     file from before NineLives) is put back in its place; any other backups are kept.
# On macOS, the .wav sounds install.sh made go too, unless you changed them.
# Your switches (sounds-off, …), quest progress (~/.local/state/ninelives), the restart's cache
# (~/.cache/ninelives) and the tips line in ~/.bashrc (or ~/.zshrc) stay; it says where they are.
#   bash scripts/uninstall.sh --dry-run   only show what would happen
#   bash scripts/uninstall.sh             uninstall
# Another folder: KITTY_CONFIG_DIRECTORY=/path bash scripts/uninstall.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/config"
DEST="${KITTY_CONFIG_DIRECTORY:-${XDG_CONFIG_HOME:-$HOME/.config}/kitty}"
DRY=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  "") ;;
  *) echo "usage: bash scripts/uninstall.sh [--dry-run]" >&2; exit 2 ;;
esac
GIT=0; command -v git >/dev/null && git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 && GIT=1

ours() {  # ours NAME FILE: is FILE a NineLives version of config/NAME?
  [ -e "$SRC/$1" ] && cmp -s "$SRC/$1" "$2" && return 0
  [ "$GIT" = 1 ] || return 1
  local h; h="$(git hash-object -- "$2")"
  git -C "$REPO" log --all --format= --raw --no-abbrev -- "config/$1" | awk '{print $4}' | grep -xF "$h" >/dev/null
}
act() {  # act WHAT ARGS…: say it, and do it unless this is a dry run
  echo "  $1"; shift
  [ "$DRY" = 1 ] || "$@"
}

[ -d "$DEST" ] || { echo "Nothing to do: $DEST doesn't exist."; exit 0; }
echo "Uninstalling NineLives from $DEST"
removed=0; kept=0; restored=0
while IFS= read -r f; do
  name="${f#"$SRC"/}"; dest="$DEST/$name"
  if [ -e "$dest" ]; then
    if ours "$name" "$dest"; then act "remove  $name" rm -f -- "$dest"; removed=$((removed + 1))
    else echo "  keep    $name   (changed since it was installed: yours now)"; kept=$((kept + 1)); fi
  fi
  oldest_own=""
  while IFS= read -r b; do                       # oldest first
    [ -n "$b" ] || continue
    if ours "$name" "$b"; then act "remove  ${b#"$DEST"/}" rm -f -- "$b"
    elif [ -z "$oldest_own" ]; then oldest_own="$b"; fi
  done < <(find "$(dirname "$dest")" -maxdepth 1 -type f -name "$(basename "$dest").bak-[0-9]*" 2>/dev/null \
           | grep -E '\.bak-[0-9]{8}-[0-9]{6}$' | sort)
  if [ -n "$oldest_own" ]; then
    if [ -e "$dest" ] && ! { [ "$DRY" = 1 ] && ours "$name" "$dest"; }; then
      echo "  note    ${oldest_own#"$DEST"/} is your older $name (not put back: $name is still there)"
    else
      act "restore $name   (from ${oldest_own#"$DEST"/})" mv -- "$oldest_own" "$dest"; restored=$((restored + 1))
    fi
  fi
done < <(find "$SRC" -type f ! -path '*/__pycache__/*' ! -name '*.pyc' | sort)
# macOS: the .wav of each sound that install.sh made (afplay can't play .oga). One is ours if it is
# what make-sounds.py makes now; one you changed is kept.
wavs=""
for f in "$SRC"/sounds/*.oga; do
  w="$DEST/sounds/$(basename "$f" .oga).wav"
  if [ -e "$w" ]; then wavs="$wavs$w"$'\n'; fi
done
if [ -n "$wavs" ]; then
  WAVS="$(mktemp -d)"; trap 'rm -rf "$WAVS"' EXIT
  python3 "$REPO/scripts/make-sounds.py" --wav "$WAVS" >/dev/null 2>&1 || true
  while IFS= read -r w; do
    [ -n "$w" ] || continue
    if cmp -s "$WAVS/$(basename "$w")" "$w"; then act "remove  sounds/$(basename "$w")" rm -f -- "$w"; removed=$((removed + 1))
    else echo "  keep    sounds/$(basename "$w")   (changed since it was installed: yours now)"; kept=$((kept + 1)); fi
  done <<< "$wavs"
fi
[ "$DRY" = 1 ] || rmdir "$DEST/sounds" 2>/dev/null || true

if [ "$DRY" = 1 ]; then
  echo "Dry run: $removed file(s) would be removed, $restored put back from a backup, $kept kept. Nothing was touched."
  exit 0
fi
echo "$removed file(s) removed, $restored put back from a backup, $kept kept."
echo "Left alone (delete them if you like):"
echo "  switches in $DEST (sounds-off, sounds-volume, sounds-classic, cat-off, quests-off, tips-off, buttons-off)"
echo "  quest progress: ${NINELIVES_STATE:-$HOME/.local/state/ninelives}"
echo "  restart log and session: ${XDG_CACHE_HOME:-$HOME/.cache}/ninelives"
echo "  the tips.sh line in ~/.bashrc or ~/.zshrc (harmless once tips.sh is gone)"
echo "Restart kitty to finish (the running one keeps the old sidebar until it closes)."
