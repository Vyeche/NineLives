#!/usr/bin/env bash
# kitty shortcut help, opened with F1 (or Ctrl+Shift+/) over the current tab. Scroll with the
# mouse or arrows; q or Esc closes it.
# Headings in palette gold (follows the theme): 5.3:1 on light, 8.7:1 on dark. Orange 208 was 2.2:1 on light.
B=$'\e[1m'; D=$'\e[37m'; A=$'\e[33m'; R=$'\e[0m'
h() { printf '\n %s%s%s\n' "$A$B" "$1" "$R"; }
# Descriptions wrap inside their own column (28 cells in), so a narrow window or a split pane
# doesn't break them at the left edge.
W=$(tput cols 2>/dev/null) || W=80; DW=$((W - 29)); ((DW < 20)) && DW=20
d() { local line first=1
  while IFS= read -r line; do
    if ((first)); then printf '%s\n' "$line"; first=0; else printf '%28s%s\n' "" "$line"; fi
  done < <(fold -s -w "$DW" <<< "$1"); }
# Quests: a shortcut that is a quest gets ★ (not done yet), a green ✓ (badge earned) or a gold ✪
# (mastered: used 10 times) in front.
STATE="${NINELIVES_STATE:-$HOME/.local/state/ninelives}"
CONF="${KITTY_CONFIG_DIRECTORY:-${XDG_CONFIG_HOME:-$HOME/.config}/kitty}"
EARNED=" "; MASTERED=" "
if [ ! -e "$CONF/quests-off" ]; then
  QUESTS=1
  [ -r "$STATE/badges" ] && while IFS=$'\t' read -r q _; do EARNED+="$q "; done < "$STATE/badges"
  [ -r "$STATE/uses" ] && while IFS=$'\t' read -r q n; do
    [[ $n =~ ^[0-9]+$ ]] && ((n >= 10)) && MASTERED+="$q "; done < "$STATE/uses"
fi
# the count and total as kitty-quests shows them (tab_bar.py writes quests.txt: "… ★★·· 2/16 …")
PROGRESS="$(head -1 "$STATE/quests.txt" 2>/dev/null | sed $'s/\e\\[[0-9;]*m//g' | grep -oE '[0-9]+/[0-9]+' | head -1)"
[ -n "$PROGRESS" ] || PROGRESS="$(wc -w <<< "$EARNED" | tr -d ' ') so far"
mark() {  # mark QUEST-ID: the 2-cell marker in front of a shortcut
  if [ -z "${QUESTS:-}" ] || [ -z "${1:-}" ]; then printf '  '
  elif [[ $MASTERED == *" $1 "* ]]; then printf '%s✪%s ' "$A" "$R"
  elif [[ $EARNED == *" $1 "* ]]; then printf '\e[32m✓%s ' "$R"
  else printf '%s★%s ' "$A" "$R"; fi; }
# Pad by characters, not bytes, so rows with ◐ ✓ ⚠ line up too.
#   k KEYS DESCRIPTION [QUEST-ID]
k() { local pad=$((25 - ${#1})); ((pad < 1)) && pad=1; printf ' %s%s%s%s%*s' "$(mark "${3:-}")" "$B" "$1" "$R" "$pad" ""; d "$2"; }
# Status row: the icon in its sidebar colour (palette, follows the theme), then bold words.
#   s COLOUR ICONS WORDS DESCRIPTION      COLOUR: 1 red, 2 green, 3 amber, 4 blue
s() { local vis="$2 $3" pad; pad=$((25 - ${#vis})); printf '   \e[3%sm%s%s %s%s%s%*s' "$1" "$2" "$R" "$B" "$3" "$R" "$pad" ""; d "$4"; }
sheet() {
printf ' %skitty shortcuts%s  %s(F1 or Ctrl+Shift+/ shows this; scroll, q closes)%s\n' "$B" "$R" "$D" "$R"
[ -n "${QUESTS:-}" ] && printf ' %s★%s %squest: use it once for its badge   %s\e[32m✓%s %searned (%s)   %s✪%s %s10 uses: mastered%s\n' \
  "$A" "$R" "$D" "$R" "$R" "$D" "$PROGRESS" "$R" "$A" "$R" "$D" "$R"
h "Tabs"
k "Ctrl+Shift+T"            "New tab in the current folder"
k "Ctrl+Shift+W"            "Close tab (asks if something is running)"
k "Middle-click a tab"      "Close that tab"
k "Ctrl+PageUp / PageDown"  "Previous / next tab"
k "Alt+1 to Alt+9"           "Jump to tab 1 to 9" jump
k "Ctrl+Shift+Left/Right"   "Move tab up / down the list" drag
k "Drag a tab"              "Reorder (an orange line shows where it lands)" drag
k "Ctrl+Shift+R"            "Rename tab" rename
k "Ctrl+Shift+Space"        "Search tabs: a name, folder or number (Tab: waiting / working / done)" search
k "Ctrl+Alt+U"              "Go to the tab waiting for you (⚠; then ✗ failed ones)" waiting
k "Search tabs  ⚠2 ⚙ +"     "Top of the sidebar: the field searches; ⚠2 goes to the tabs waiting for you, ⚙ settings, + a new tab"
k "×"                       "Right end of the current tab: close it (kitty-buttons off hides these)"
k "+ New tab"               "End of the sidebar: new tab (the line under it is your next quest)"
h "Splits (several panes in one tab)"
k "Ctrl+Alt+Right / Down"   "Split side-by-side / top-bottom (same folder)" split
k "Ctrl+Shift+Enter"        "New pane in the current folder"
k "Ctrl+Alt+arrows/HJKL"   "Move between panes (or just point the mouse)" panes
k "Ctrl+Alt+Z"              "Zoom the pane full-size and back" zoom
k "Ctrl+Shift+L"            "Cycle layouts (splits, stack, tall, grid)"
h "Text"
k "Ctrl+Shift+C / V"        "Copy / paste"
k "Select with mouse"       "Copies it; right-click pastes"
k "Ctrl+Shift+= / -"        "Bigger / smaller text" fontsize
k "Ctrl+Shift+Backspace"    "Normal text size"
k "Ctrl+Shift+H"            "Open the whole scrollback in a pager" scrollback
k "Ctrl+Shift+E"            "Pick a link/path on screen to open" hints
h "Window"
k "Ctrl+Shift+N"            "New kitty window"
k "Ctrl+Shift+F11"          "Full screen"
k "Ctrl+Shift+F5"           "Reload settings (kitty.conf)"
k "Ctrl+Shift+F2"           "NineLives settings: ↑/↓ choose, Enter changes (last row: kitty.conf in your editor)"
h "Handy extras"
k "Ctrl+Shift+Z / X"        "Jump to previous / next command prompt" prompts
k "Ctrl+Shift+G"            "Show the last command's output in a pager" output
k "Ctrl+Shift+U"            "Type any Unicode character or emoji" unicode
k "Ctrl+Shift+P then F"     "Pick a file path on screen and type it"
k "Ctrl+Shift+A then M / L" "More / less see-through (1 = solid)"
k "Ctrl+Shift+Delete"       "Clear the screen and scrollback"
h "Tab icons and sounds"
s 4 "◐◓◑◒" "spinning"         "Working: Claude, omp, opencode, or any command running"
s 2 "✦✧ ✓" "finished"         "Just finished (chime); ✓ stays until you look"
s 3 "⚠" "needs you"           "Permission prompt or question: amber block, pulses (soft sound)"
s 1 "✗" "error"               "Something failed"
k "‖  /  •"                 "Paused  /  new output in a background tab"
k "3m  /  1h05"             "Right of the folder: how long it has been working / waiting / done"
k "=^.^=  =O.O= !"           "The cat by + New tab: the whole window at a glance, its colour too: amber needs you, blue working, green done (kitty-cat)"
k "Ctrl+Alt+M"              "Mute / unmute the sounds (kitty-sounds plays each one)" mute
h "Learn as you go"
k "ninelives"               "Every NineLives setting at a glance (ninelives settings: change them in a list)"
k "kitty-quests"            "Quests + badges: use a shortcut once to earn it (off / on)"
k "kitty-tips"              "Show a random tip (kitty-tips all / off / on)"
k "kitty-sounds"            "Hear each sound (volume 5-100 / classic / off / on)"
k "kitty-cat"               "What the cat's faces mean (off / on)"
k "kitty-buttons"           "The sidebar's search field, buttons and × (off / on)"
h "Kittens (type in any tab)"
k "kitten icat pic.png"     "Show an image right in the terminal"
k "kitten diff a b"         "Side-by-side diff of two files or folders"
k "kitten themes"           "Browse and try color themes"
k "kitten ssh host"         "SSH that keeps kitty features on the server"
FOOT="Theme follows your desktop's light/dark setting. Long jobs (15 s+) in other tabs notify you when done."
# on a Mac: kitty reads Option as Alt in its shortcuts, and laptop F-keys need Fn
case "${OSTYPE:-}" in darwin*) FOOT="$FOOT On a Mac, Alt is Option (Ctrl+Alt+→ = Ctrl+Option+→, Alt+1 = Option+1); F1 may need Fn: Ctrl+Shift+/ also opens this.";; esac
printf '\n'; fold -s -w $((W - 2)) <<< "$FOOT" | while IFS= read -r line; do printf ' %s%s%s\n' "$D" "$line" "$R"; done
}
# (an older less, as on some Macs, has no --mouse and would show nothing at all with it)
MOUSE=--mouse; less --mouse -V >/dev/null 2>&1 || MOUSE=
if [ -t 1 ]; then sheet | less -R $MOUSE --prompt='q closes' -+F; else sheet; fi
