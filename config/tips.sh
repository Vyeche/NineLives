# tips.sh — shows one kitty tip when a new shell starts in kitty (sourced from ~/.bashrc, or ~/.zshrc:
# it works in bash, 3.2 included, and zsh): half the time your next quest (from tab_bar.py), otherwise
# a random tip. Part of NineLives.
# Turn off: kitty-tips off   Show one now: kitty-tips   Quests and badges: kitty-quests
# Hear the sounds: kitty-sounds   (volume N / classic / ninelives / off / on)
_kitty_tips=(
  "Ctrl+Alt+→ splits this tab side by side; Ctrl+Alt+↓ splits top/bottom"
  "Ctrl+Alt+Z zooms the current pane to full size (press again to go back)"
  "Point the mouse at a pane to focus it, or move with Ctrl+Alt+arrows"
  "Drag a tab in the sidebar to reorder it; an orange line shows where it will land"
  "Middle-click a tab to close it; Ctrl+Shift+R renames the current tab"
  "Alt+1 … Alt+9 jumps straight to that tab"
  "Ctrl+Shift+Space searches your tabs: type part of a name or folder, Enter goes there"
  "Ctrl+Alt+U jumps to the tab waiting for you (press again for the next one)"
  "A git branch other than main shows after the folder in the sidebar: code/api ⌥ fix-parser"
  "Ctrl+Shift+T opens a new tab in the folder you're in"
  "Ctrl+Shift+Z / X jumps to the previous / next command you ran"
  "Ctrl+Shift+G shows the last command's output on its own, easy to scroll and search"
  "Ctrl+Shift+H opens the whole scrollback in a pager (/ to search, q to quit)"
  "Ctrl+Shift+E lets you open any link on screen by typing its hint letter"
  "Ctrl+Shift+P then F types a file path from the screen for you"
  "Ctrl+Shift+U lets you type any emoji or symbol by name"
  "Ctrl+Shift+= / - changes the text size; Ctrl+Shift+Backspace resets it"
  "Ctrl+Shift+A then M / L makes the window more / less see-through (1 = solid)"
  "kitten icat picture.png shows an image right here in the terminal"
  "kitten diff file1 file2 shows a side-by-side, colored diff"
  "kitten themes lets you browse and preview color themes"
  "A ◐ spinning on a tab = working, ✓ = finished, an amber ⚠ block = waiting for you"
  "The small 3m or 1h05 at the right of a tab is how long it has been working, waiting or finished"
  "Select text with the mouse to copy it; right-click pastes"
  "Ctrl+Alt+M mutes / unmutes the tab sounds; kitty-sounds plays each one so you know them"
  "Each tab sound has its own shape: up = finished, rising \"mrrp?\" = needs you, down = error"
  "Jobs that take 15 s+ in another tab send a desktop notification when they finish"
  "F1 shows every shortcut; this tip line can be turned off with: kitty-tips off"
  "kitty-quests lists the quests: use a shortcut once to earn its badge"
  "Ctrl+Shift+F2 (or ⚙ at the top of the sidebar) opens the NineLives settings: ↑/↓ choose, Enter changes"
  "ninelives shows every NineLives setting at a glance; ninelives settings opens the list to change them"
  "Click the cat in the sidebar: it says what needs you, today's quest and a tip (kitty-cat explains)"
  "Drag the cat in the sidebar to put it somewhere else; it walks home after a while"
  "kitty-cat talk events: the cat speaks up only about your tabs, no tips (off: only when clicked)"
  "Click the cat at the end of + New tab (or press Ctrl+Alt+C) and it tells you what needs you, plus a tip of the day"
  "Sounds too loud? kitty-sounds volume 40 turns the tab sounds down (5-100)"
  "A tab you're looking at doesn't chime when it finishes: you can already see it"
  "A running command's tab shows just its program (git push), not its arguments; kitty-commands full shows it all"
)
_nl_state="${NINELIVES_STATE:-$HOME/.local/state/ninelives}"
# macOS (new, not yet tried on a real Mac): afplay plays the .wav copies install.sh makes
_nl_mac=""; case "${OSTYPE:-}" in darwin*) _nl_mac=1;; esac
[ -n "$_nl_mac" ] && _kitty_tips+=("On a Mac, Alt is Option in kitty's shortcuts: Ctrl+Option+→ splits, Option+1 goes to tab 1")
_nl_play() {  # _nl_play VOLUME FILE: VOLUME on paplay's scale (65536 = full); afplay's is that cubed
  if [ -n "$_nl_mac" ]; then afplay -v "$(awk -v v="$1" 'BEGIN { printf "%.8f", (v / 65536) ^ 3 }')" "$2" 2>/dev/null
  else paplay --volume="$1" "$2" 2>/dev/null; fi
}
_nl_conf="${KITTY_CONFIG_DIRECTORY:-${XDG_CONFIG_HOME:-$HOME/.config}/kitty}"   # this kitty's config folder (switch files live here)
kitty-tips() {
  case "${1:-}" in
    off) touch "$_nl_conf"/tips-off && echo "kitty tips off (kitty-tips on to bring them back)";;
    on)  rm -f "$_nl_conf"/tips-off && echo "kitty tips on";;
    all) printf '  • %s\n' "${_kitty_tips[@]}";;
    *)   local q=""
         if [ ! -e "$_nl_conf"/quests-off ] && (( RANDOM % 2 )) && [ -s "$_nl_state/next-quest" ]; then
           IFS= read -r q < "$_nl_state/next-quest"
         fi
         if [ -n "$q" ]; then
           printf '\e[37m🎯 kitty quest: %s  (kitty-quests = all)\e[0m\n' "$q"
         else
           # (a slice counts from 0 in bash and zsh alike; zsh's [i] counts from 1. The $((…)): zsh would
           # read :RANDOM as a modifier)
           printf '\e[37m💡 kitty tip: %s  (F1 = all shortcuts)\e[0m\n' "${_kitty_tips[@]:$((RANDOM % ${#_kitty_tips[@]})):1}"
         fi;;
  esac
}
kitty-sounds() {
  local k="$_nl_conf"
  case "${1:-}" in
    off) touch "$k/sounds-off" && echo "sounds off (kitty-sounds on, or Ctrl+Alt+M)";;
    on)  rm -f "$k/sounds-off" && echo "sounds on";;
    classic)   touch "$k/sounds-classic" && echo "using the desktop's standard sounds (kitty-sounds ninelives switches back)";;
    ninelives) rm -f "$k/sounds-classic" && echo "using the NineLives sounds";;
    volume)
      # (a case pattern, not =~: zsh's =~ needs its regex module)
      if case "${2:-}" in ""|*[!0-9]*) false;; esac && (( $2 >= 5 && $2 <= 100 )); then
        echo "$2" > "$k/sounds-volume" && echo "tab sounds at $2% (kitty-sounds plays them at that volume)"
      else
        echo "tab sounds at $(cat "$k/sounds-volume" 2>/dev/null || echo 100)%   change: kitty-sounds volume 5-100"
      fi;;
    ""|play)
      local d=/usr/share/sounds/freedesktop/stereo ext=oga row name classic what f
      [ -n "$_nl_mac" ] && d=/System/Library/Sounds && ext=aiff
      local vol=$(( 40000 * $(cat "$k/sounds-volume" 2>/dev/null || echo 100) / 100 ))
      [ -e "$k/sounds-off" ] && echo "(sounds are muted in the tabs: kitty-sounds on, or Ctrl+Alt+M)"
      for row in "done:complete:finished, two notes up" \
                 "done-2:complete:another tab finished soon after: a step higher (then done-3)" \
                 "needs-you:window-question:waiting for you, a rising mrrp? (the loudest)" \
                 "error:dialog-error:something failed, two low notes down" \
                 "badge:complete:you earned a badge" "rank:complete:a new rank" \
                 "drop:-:a dragged tab landed"; do
        IFS=: read -r name classic what <<< "$row"
        f="$k/sounds/$name.oga"
        if [ -n "$_nl_mac" ]; then                 # macOS's own alert sounds for classic
          f="$k/sounds/$name.wav"
          case $classic in complete) classic=Glass;; window-question) classic=Ping;; dialog-error) classic=Basso;; esac
        fi
        if [ -e "$k/sounds-classic" ] || [ ! -e "$f" ]; then f="$d/$classic.$ext"; fi
        printf '  \e[1m%-10s\e[0m %s\n' "$name" "$what"
        [ -e "$f" ] && _nl_play "$vol" "$f"
        sleep 0.5
      done
      echo "kitty-sounds volume 5-100: quieter or louder   classic: the desktop's sounds   off: silence";;
    *) echo "usage: kitty-sounds [play | volume N | classic | ninelives | off | on]";;
  esac
}
kitty-cat() {
  case "${1:-} ${2:-}" in
    "off "*) touch "$_nl_conf"/cat-off && echo "the cat is hiding (kitty-cat on brings it back)";;
    "on "*)  rm -f "$_nl_conf"/cat-off && echo "=^.^=  the cat is back";;
    "talk on")     rm -f "$_nl_conf"/cat-talk && echo "the cat speaks up now and then (briefly; never while you type)";;
    "talk events") echo events > "$_nl_conf"/cat-talk && echo "the cat speaks up only about your tabs and badges (no tips)";;
    "talk off")    echo off > "$_nl_conf"/cat-talk && echo "the cat only talks when you click it";;
    "sounds off")  touch "$_nl_conf"/cat-sounds-off && echo "the cat is quiet (no meows; the tab sounds stay)";;
    "sounds on")   rm -f "$_nl_conf"/cat-sounds-off && echo "the cat meows again (soft, with the other sounds)";;
    "talk "*|"sounds "*) echo "usage: kitty-cat talk on|events|off   kitty-cat sounds on|off";;
    *)   printf '%s\n' "Nine, the cat in the sidebar, sits under your tabs and watches them for you:" \
           "  it walks up to a tab that needs you (or just finished) and points at it" \
           "  it hops when a tab finishes, looks startled when one starts waiting, naps at night" \
           "  click it: what needs you, today's quest, a tip, a joke (Go / Next / ×); drag it about" \
           "  now and then it says something by itself, briefly, with a soft meow" \
           "With no room for it (a full sidebar), it sits small at the end of \"+ New tab\", or its face:" \
           "  =O.O= !  a tab needs you   =^ω^= ♪  finished   =>.<=  failed   =-.-= zZ  napping" \
           "kitty-cat off | on                 hide it, or bring it back (Ctrl+Alt+C still calls it)" \
           "kitty-cat talk on | events | off   how much it says by itself (now: $(cat "$_nl_conf"/cat-talk 2>/dev/null || echo on))" \
           "kitty-cat sounds on | off          its meows (now: $([ -e "$_nl_conf"/cat-sounds-off ] && echo off || echo on))";;
  esac
}
kitty-buttons() {
  case "${1:-}" in
    off) touch "$_nl_conf"/buttons-off && echo "sidebar buttons hidden: no search row, no × (kitty-buttons on brings them back)";;
    on)  rm -f "$_nl_conf"/buttons-off && echo "sidebar buttons on";;
    *)   printf '%s\n' "The sidebar's buttons:" \
           "  Search tabs      the field: click to search your tabs (or Ctrl+Shift+Space)" \
           "  ⚠2               shown while tabs wait for you (2 = how many): click to go there (Ctrl+Alt+U)" \
           "  ⚙                the NineLives settings (or Ctrl+Shift+F2)" \
           "  +                a new tab in this folder" \
           "  ×                on the tab you're on: close it" \
           "kitty-buttons off hides them, kitty-buttons on brings them back.";;
  esac
}
kitty-commands() {
  case "${1:-}" in
    full|on)   touch "$_nl_conf"/full-commands && echo "tab names show whole command lines, arguments too (kitty-commands short hides them again)";;
    short|off) rm -f "$_nl_conf"/full-commands && echo "tab names show a command's program and subcommand only";;
    *)   printf '%s\n' "While a command runs, its tab is named after it. A command line can hold a password" \
           "or a token, so the sidebar and the search box show only the program and its subcommand:" \
           "  cd app && npm run build -- --token=…   →   npm run build" \
           "  git push origin main                  →   git push" \
           "  sudo -u db psql -c \"…\"                →   psql" \
           "  python3 scripts/check.py --key …      →   python3 check.py (a script's name shows)" \
           "Names that agents set (✳ Fix the login bug) and names you give a tab (Ctrl+Shift+R) stay." \
           "Now: $([ -e "$_nl_conf"/full-commands ] && echo "whole command lines" || echo "program and subcommand")." \
           "kitty-commands full shows whole command lines, kitty-commands short goes back." \
           "(kitty's own window title, in the taskbar and Alt+Tab, and its \"command finished\"" \
           " notification still show the whole line.)";;
  esac
}
_nl_quest_list() {  # print quests.txt, wrapping each description under itself to fit the window
  local cols=${COLUMNS:-$(tput cols 2>/dev/null || echo 80)} line pre style desc vis ind w part first
  while IFS= read -r line; do
    if [[ $line != *$'\x1f'* ]]; then printf '%s\n' "$line"; continue; fi
    IFS=$'\x1f' read -r pre style desc <<< "$line"
    vis=$(sed $'s/\e\\[[0-9;]*m//g' <<< "$pre"); ind=${#vis}; w=$((cols - ind - 1)); ((w < 20)) && w=20
    first=1
    while IFS= read -r part; do
      if ((first)); then printf '%s%s%s\e[0m\n' "$pre" "$style" "$part"; first=0
      else printf '%*s%s%s\e[0m\n' "$ind" "" "$style" "$part"; fi
    done < <(fold -s -w "$w" <<< "$desc")
  done < "$_nl_state/quests.txt"
}
kitty-quests() {
  case "${1:-}" in
    off) touch "$_nl_conf"/quests-off && echo "quests hidden (kitty-quests on brings them back; badges are kept)";;
    on)  rm -f "$_nl_conf"/quests-off && echo "quests on";;
    *)   if [ -r "$_nl_state/quests.txt" ]; then _nl_quest_list
         else echo "No quests yet: they start after kitty restarts with the NineLives tab_bar.py."; fi;;
  esac
}
ninelives() {  # every NineLives switch at a glance, and the command that changes it
  # ninelives settings: the settings list to change them in (Ctrl+Shift+F2 or ⚙ in the sidebar)
  # ninelives cat: the helper cat (Ctrl+Alt+C, or click the cat at the end of "+ New tab")
  case "${1:-}" in
    settings|set) python3 "$_nl_conf/settings.py"; return;;
    cat) python3 "$_nl_conf/cat-helper.py"; return;;
    "") ;;
    *) echo "usage: ninelives [settings | cat]"; return 2;;
  esac
  local c="$_nl_conf" B=$'\e[1m' D=$'\e[37m' R=$'\e[0m' n=0 rank next="" vol snd
  _nl_row() { local pad=$((44 - ${#2})); ((pad < 1)) && pad=1   # pad by characters: ★ is 3 bytes
          printf '  %-8s %s%*s%s%s%s\n' "$1" "$2" "$pad" "" "$D" "$3" "$R"; }
  [ -r "$_nl_state/badges" ] && n=$(grep -c . "$_nl_state/badges")
  # ranks as in tab_bar.py: Kitten 0, House Cat 4, Alley Cat 9, Nine Lives 16 (all)
  if ((n >= 16)); then rank="Nine Lives"; elif ((n >= 9)); then rank="Alley Cat"
  elif ((n >= 4)); then rank="House Cat"; else rank="Kitten"; fi
  [ -s "$_nl_state/next-quest" ] && IFS= read -r next < "$_nl_state/next-quest"
  vol=$(cat "$c/sounds-volume" 2>/dev/null || echo 100)
  if [ -e "$c/sounds-off" ]; then snd="muted"; else snd="on, ${vol}%"; fi
  [ -e "$c/sounds-classic" ] && snd="$snd, desktop sounds" || snd="$snd, NineLives sounds"
  local shown="$c"; case $c in "$HOME"/*) shown="~${c#"$HOME"}";; esac
  printf '%sNineLives%s  %skitty %s · config %s%s\n' "$B" "$R" "$D" \
    "$(kitty --version 2>/dev/null | cut -d' ' -f2)" "$shown" "$R"
  _nl_row sounds "$snd" "kitty-sounds [volume N|off|on|classic]"
  _nl_row cat "$([ -e "$c/cat-off" ] && echo hidden || echo "shown, talks: $(cat "$c/cat-talk" 2>/dev/null || echo on), sounds: $([ -e "$c/cat-sounds-off" ] && echo off || echo on)")" "kitty-cat [off|on|talk …|sounds …]"
  if [ -e "$c/quests-off" ]; then _nl_row quests "hidden (badges kept: $n/16)" "kitty-quests on"
  else local m=0
       [ -r "$_nl_state/uses" ] && m=$(awk -F'\t' '$2 >= 10' "$_nl_state/uses" | grep -c .)
       _nl_row quests "★$n/16, $rank$( ((m)) && echo ", ✪$m mastered")" "kitty-quests [off]"
       [ -n "$next" ] && printf '  %-8s %s\n' "" "${D}next: $next$R"; fi
  _nl_row buttons "$([ -e "$c/buttons-off" ] && echo hidden || echo shown)" "kitty-buttons [off|on]"
  _nl_row commands "$([ -e "$c/full-commands" ] && echo "whole command lines" || echo "program + subcommand")" "kitty-commands [full|short]"
  _nl_row tips "$([ -e "$c/tips-off" ] && echo off || echo on)" "kitty-tips [all|off|on]"
  # is kitty running the installed tab_bar.py? (it keeps the first-loaded one until a restart)
  local running="" installed=""
  [ -s "$_nl_state/tab_bar.running" ] && IFS= read -r running < "$_nl_state/tab_bar.running"
  # (macOS has shasum, which is SHA-1 too, instead of sha1sum)
  [ -r "$c/tab_bar.py" ] && installed=$({ sha1sum "$c/tab_bar.py" 2>/dev/null || shasum "$c/tab_bar.py" 2>/dev/null; } | cut -d' ' -f1)
  if [ -n "$running" ] && [ -n "$installed" ] && [ "$running" != "$installed" ]; then
    printf '  %s!%s %skitty is running an older tab_bar.py: restart kitty to load the installed one%s\n' \
      $'\e[33m' "$R" "$B" "$R"
    printf '    %s(bash scripts/kitty-relaunch.sh --when-idle keeps every tab)%s\n' "$D" "$R"
  fi
  printf '  %sChange them in a list: ninelives settings (or Ctrl+Shift+F2) · F1: every shortcut · ninelives cat: ask the cat%s\n' "$D" "$R"
}
# one tip per new shell (sourced twice, e.g. by the dev kitty's rcfile, it stays quiet the 2nd time)
[ -e "$_nl_conf"/tips-off ] || [ -n "${_NL_TIP_SHOWN:-}" ] || { kitty-tips; _NL_TIP_SHOWN=1; }
