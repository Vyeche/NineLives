# How it works

Everything kitty-side is in `config/tab_bar.py`, which kitty loads for `{custom}` in
`tab_title_template`. It does four jobs.

## 1. Drawing each tab
`draw_title(data)` returns two lines per tab (number, status slot, name; then folder and time). Widths
come from kitty's `wcswidth`, so wide characters line up. Colours are palette colours (`fmt.fg.colorN`),
so both themes work without code changes. If drawing ever fails, it returns a plain line instead of
raising, because kitty drops the whole title template on an exception.

## 2. A timer for status, sound and animation
kitty only redraws the tab bar when something changes, and templates have no clock. A timer (`TICK`,
8 times a second) does three things:
- **Watches states.** It reads each window's program status (OSC 7501, sent by Claude Code), plus "is a command running" for plain shells (the terminal's foreground process).
- **Plays sounds.** It does this on changes (working → done, → blocked, → error), and fires the 3-minute reminder.
- **Redraws.** Only when a visible frame changes: spinner and pulse on every other tick, sparkles and waves on every tick, nothing when idle. It also wakes kitty's main loop, which otherwise may not paint (seen on X11 once the cursor stops blinking).

Animations count ticks (`_frame`), not the clock, so no frame is skipped or shown twice.

## 3. Patches to kitty
These are installed once per kitty process. Each checks that what it relies on exists, and skips itself
if not.
| Patch | Why |
| --- | --- |
| `TabManager.handle_tab_bar_mouse` | drag tabs inside the sidebar on Wayland (COSMIC ignores kitty's compositor drag) |
| `TabBar.update_vertical` | the gap row under a tab belongs to that tab, for clicks and drags |
| `TabManager.tab_bar_data` | "+ New tab" label, the cat, the quest line |
| `Boss.dispatch_action` | notice shortcuts for quests |
| drag image functions | the high-contrast drag card (X11) |

**Reload safety.** Ctrl+Shift+F5 runs the file again, but a patch stays the version first installed. So
patches call the current load's code through attributes on `kitty.tab_bar` (`_vye_quest_action`,
`_vye_new_tab_label`, `_vye_hooks`). The timer is replaced on every reload, so sounds never double.

## 4. Quests
`dispatch_action` reports every shortcut. `ACTION_QUEST` maps action names to quests. Progress is
written atomically to `~/.local/state/ninelives/`.

## Other files
| File | Does |
| --- | --- |
| `config/kitty.conf` | settings, key maps, theme include |
| `config/cosmic-*.conf`, `*-theme.auto.conf` | colours; kitty picks an auto file by the desktop's light/dark setting |
| `config/shortcuts.sh` | the F1 sheet (wraps to the window) |
| `config/tips.sh` | prompt tips and the `kitty-*` commands |
| `config/sounds/*.oga` | sounds, built by `scripts/make-sounds.py` |
| `scripts/install.sh` | install with backups and a config check |
| `scripts/uninstall.sh` | remove NineLives' files again and put your own config back |
| `scripts/kitty-relaunch.sh` | restart kitty and reopen every tab (finds kitty by its remote-control socket: the one it runs in, else the only one) |
| `scripts/kitty-tabs.py` | reads `kitty @ ls` for the relaunch: how to bring each tab back, which tabs are busy; and which kitty sockets there are |
| `scripts/make-sounds.py` | builds the sounds from scratch |
| `tests/` | unit tests, no kitty needed (see [Testing](Testing)) |
| `scripts/check.sh` | every check in one command, see [Testing](Testing) |
| `scripts/dev-kitty.sh` | a visible dev kitty with its own config folder, see [Testing](Testing) |
| `scripts/test-kitty.sh`, `scripts/vmouse.py` | testing, see [Testing](Testing) |
| `scripts/publish-wiki.sh` | publish `docs/wiki/` to the repository's wiki (GitHub, Gitea, …) |
