# How it works

Everything kitty-side is in `config/tab_bar.py`, which kitty loads for `{custom}` in
`tab_title_template`. It does four jobs.

## 1. Drawing each tab
`draw_title(data)` returns two lines per tab (number, status slot, name; then folder and time). Widths
come from kitty's `wcswidth`, so wide characters line up. Colours are palette colours (`fmt.fg.colorN`),
so both themes work without code changes. The quiet parts (the number, the agent mark, the "new
output" dot) and the search field and buttons take the theme's own colours from kitty's options as
they are drawn (`_theme`), so they follow a light/dark switch too: the quiet shades are the tab's
text colour moved toward its background until just above 4.5:1 (text) or 3:1 (marks), and every
pair in the search row is checked to stay above 4.5:1. If drawing ever fails, it returns a plain line instead of
raising, because kitty drops the whole title template on an exception.

## 2. A timer for status, sound and animation
kitty only redraws the tab bar when something changes, and templates have no clock. A timer (`TICK`,
8 times a second) does three things:
- **Watches states.** It reads each window's program status (OSC 7501, sent by Claude Code), plus "is a command running" for plain shells (the terminal's foreground process: from `/proc` on Linux, from kitty's own process helpers in `kitty.child` on macOS, which has no `/proc`).
- **Plays sounds.** It does this on changes (working → done, → blocked, → error), and fires the 3-minute reminder.
- **Redraws.** Only when a visible frame changes: spinner and pulse on every other tick, sparkles and waves on every tick, nothing when idle. It also wakes kitty's main loop, which otherwise may not paint (seen on X11 once the cursor stops blinking).

Animations count ticks (`_frame`), not the clock, so no frame is skipped or shown twice.

**Agent marks** (`✳`, `π`, …) name the program in each tab's foreground. When a shell or `kitten`
leads the foreground process group (a tab the restart reopened), the agent below it in the same group
counts: on Linux by reading the leader's children in `/proc`, on macOS from kitty's process-group map
(one scan of all processes, shared by every tab for a second). Marks are kept 3 seconds. A window
the timer first saw under 10 seconds ago that has no mark yet (a restart reopens every tab at once, and
an agent can still be starting) is looked at again twice a second, and the sidebar redraws only if a
mark turns up.

**Overlays.** While an overlay is open in a tab (the search box, the F1 sheet), kitty describes the
tab by the overlay: its folder is kitty's start folder and its program is no agent. The row, its
mark and the plain-command spinner use the window under it instead (`Tab.active_window_for_cwd`, the
main window of the overlay's group). The overlays aren't started with `--cwd=current`: from a window
running the ssh kitten, kitty would run them on the remote host.

**macOS** (new, untested on a real Mac): `IS_MACOS` picks `afplay` and the `.wav` sounds,
`osascript` notifications (the text as arguments, never in the script) and the process lookups above.
The Linux code paths are unchanged.

## 3. Patches to kitty
These are installed once per kitty process. Each checks that what it relies on exists, and skips itself
if not.
| Patch | Why |
| --- | --- |
| `TabManager.handle_tab_bar_mouse` | drag tabs inside the sidebar on Wayland (COSMIC ignores kitty's compositor drag); clicks on our buttons, the cat and its bubble; carrying the cat (a press on it tells kitty a drag started, so the mouse's moves come) |
| `TabBar.update_vertical` | the gap row under a tab belongs to that tab, for clicks and drags; after each sidebar layout, the drawn cat's place (the floor, small by "+ New tab", or its face) and its pictures put back |
| `TabManager.tab_bar_data` | the search field and buttons on top; "+ New tab" label, the cat (a click on it opens the helper cat), the quest line |
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
| `config/kitty.conf` | settings, key maps, theme include; at the end `globinclude ninelives-${KITTY_OS}.conf` |
| `config/ninelives-macos.conf` | read only by kitty on macOS: the socket in `$TMPDIR`, Ctrl+Alt+M with `afplay` |
| `config/cosmic-*.conf`, `*-theme.auto.conf` | colours; kitty picks an auto file by the desktop's light/dark setting |
| `config/shortcuts.sh` | the F1 sheet (wraps to the window) |
| `config/command_title.py` | which titles are a running command's command line (compared with the command the shell reported to kitty, `last_cmd_cmdline`) and their short form (`git push`); `tab_bar.py`, `tab-finder.py` and `scripts/kitty-tabs.py` all use it, and `full-commands` turns it off |
| `config/tab-finder.py` | the tab search box (Ctrl+Shift+Space) and the jump to the waiting tab (Ctrl+Alt+U) |
| `config/settings.py` | the settings list (Ctrl+Shift+F2, the sidebar's ⚙, `ninelives settings`): one row per setting, written to the same switch files the `kitty-*` commands use |
| `config/nine.py` | the cat's parts that don't need kitty: its moves and which picture shows, walking, talking at a steady pace, its speech bubble as a picture (text drawn by a function it's handed: kitty's own renderer in the sidebar), and its memory of what it said (`cat-said` in the state folder: keys and short hashes of the lines, never their words, which can name a tab after a whole command line) |
| `config/cat-helper.py`, `config/cat/` | the helper cat (Ctrl+Alt+C, a click on the sidebar's cat, `ninelives cat`): an overlay that shows the drawn cat with kitty's graphics protocol (each pose sent once as a PNG, then swapped in place; never `\e[2J`, which would free the poses kitty keeps) and a bubble drawn in cells. It reads the tabs as the search box does (`tab-finder.py`'s rows, `kitty @ ls` once a second while open) and quests from `quests.txt` |
| `config/tips.sh` | prompt tips and the `kitty-*` commands |
| `config/sounds/*.oga` | sounds, built by `scripts/make-sounds.py` |
| `scripts/install.sh` | install with backups and a config check |
| `scripts/uninstall.sh` | remove NineLives' files again and put your own config back |
| `scripts/kitty-relaunch.sh` | restart kitty and reopen every tab (finds kitty by its remote-control socket: the one it runs in, else the only one) |
| `scripts/kitty-tabs.py` | reads `kitty @ ls` for the relaunch: how to bring each tab back, which tabs are busy; and which kitty sockets there are |
| `scripts/make-sounds.py` | builds the sounds from scratch |
| `scripts/make-cat.py` | draws the cat's poses, its walk and its mouths (`config/cat/<size>/<pose>.png`) with pycairo, as small palette PNGs; `--sheet FILE` makes a contact sheet |
| `tests/` | unit tests, no kitty needed (see [Testing](Testing)) |
| `scripts/check.sh` | every check in one command, see [Testing](Testing) |
| `scripts/check-macos.sh`, `tests/live_agent_lookup.py` | the macOS checks (the Gauntlet's macOS lane), and the agent lookup against real processes with kitty's own Python |
| `scripts/dev-kitty.sh` | a visible dev kitty with its own config folder, see [Testing](Testing) |
| `scripts/test-kitty.sh`, `scripts/vmouse.py` | testing, see [Testing](Testing) |
| `scripts/publish-wiki.sh` | publish `docs/wiki/` to the repository's wiki (GitHub, Gitea, …) |

## The drawn cat in the sidebar

kitty draws the sidebar from a Screen of its own (`TabBar.screen`) with the same code as a terminal
window, pictures included, but makes that Screen without a window id, and a picture reaches the GPU
only for a Screen that has one. So the sidebar gets a new Screen tied to one of its kitty window's
windows (picked again if that window closes), and the cat's frames go in as graphics-protocol
commands fed to its parser (`Screen.restore_scrollback`) from inside kitty. Only our own quiet
(`q=2`) graphics commands may go through: tab_bar.py checks every byte (a reply would be typed into
the borrowed window's program, a BEL would ask the desktop for attention). Each sidebar redraw
erases the screen, so every picture also has a placement that is never drawn (it keeps the picture),
and the cat and its bubble are put back at the end of each redraw. It moves a pixel at a time (a cell
plus a pixel offset); a timer runs 15 times a second only while it walks and 30 times while it talks,
and neither redraws the sidebar's text. Its bubble is a picture too, drawn with kitty's own text
renderer, and the words are shown a little more at a time by cropping their picture. On a kitty
without these internals the cat face shows instead.
