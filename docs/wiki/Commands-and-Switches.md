# Commands and switches

These shell commands come from `~/.config/kitty/tips.sh` (see [Installing](Installing#prompt-tips)).
Each switch is just a file in kitty's config folder (`~/.config/kitty/`, or `$KITTY_CONFIG_DIRECTORY` for a kitty
started with one), so you can also create or delete it by hand.
`install.sh` never creates or removes them.

## The settings list
**Ctrl+Shift+F2**, the **⚙** at the top of the sidebar, or `ninelives settings` in a shell opens
NineLives' settings as a list over the current tab, one row per setting with its value on the right:
```
 NineLives settings   kitty 0.51.0 · ~/.config/kitty

 ❯ Sounds                         ‹ on ›
   Volume                ■■■■■■■■□□  80%
   Sound set                   NineLives
   The cat                         shown
   Quests                     on · ★3/16
   Sidebar buttons                 shown
   Prompt tips                        on

   Edit kitty.conf in your editor…
```
**↑/↓** (or **j/k**) choose, **Enter**, **Space** or **←/→** change (the volume moves 5 % a step and
plays the "finished" chime at the new level), **Esc** or **q** closes; a click on a row changes it too.
The line at the bottom says what the chosen setting does. Changes apply at once: each row writes the
same file as the command below, so the sidebar, the commands and the list always agree. The last row
opens `kitty.conf` in your editor, which is what Ctrl+Shift+F2 does in plain kitty (Ctrl+Shift+F5 then
reloads it). Pressing Ctrl+Shift+F2 (or ⚙) again closes the list.

## At a glance
`ninelives` prints them all at once: sounds (on/muted, volume, which set), the cat, quests (badges,
rank, next quest) and tips, each with the command that changes it. It also warns when kitty is still
running an older `tab_bar.py` than the installed one, which means a restart is due.

## The commands

| Command | Does | File |
| --- | --- | --- |
| `ninelives` | every setting below at a glance | |
| `ninelives settings`, **Ctrl+Shift+F2**, **⚙** | the settings list: change them with the arrow keys | |
| `kitty-sounds` | play each sound with its meaning | |
| `kitty-sounds volume N` | tab sound volume, 5–100 % | `sounds-volume` |
| `kitty-sounds off` / `on`, **Ctrl+Alt+M** | mute / unmute | `sounds-off` |
| `kitty-sounds classic` / `ninelives` | desktop sounds / NineLives sounds | `sounds-classic` |
| `kitty-buttons` / `off` / `on` | explain / hide / show the sidebar's search field and buttons and the × on the current tab | `buttons-off` |
| `kitty-cat` / `off` / `on` | explain / hide / show the cat | `cat-off` |
| `kitty-quests` / `off` / `on` | list / hide / show quests | `quests-off` |
| `kitty-tips` / `all` / `off` / `on` | one tip / every tip / prompt tips off / on | `tips-off` |

Changes show up within a moment; nothing needs a restart.

## Environment
| Variable | Does |
| --- | --- |
| `NINELIVES_STATE` | where quest progress lives (default `~/.local/state/ninelives`) |
| `NINELIVES_QUIET` | set: no desktop notifications (the dev and test kittys use it) |
| `KITTY_CONFIG_DIRECTORY` | where `install.sh` installs (default `~/.config/kitty`) |
| `NL_KEEP_BACKUPS` | how many backups of each file `install.sh` keeps (default 3, or `all`) |
| `XDG_CACHE_HOME` | the restart's log and session file go to `$XDG_CACHE_HOME/ninelives` (default `~/.cache/ninelives`) |
| `NL_KITTY_SOCKET` | point `kitty-relaunch.sh` at one kitty's socket and keep your environment (for the test kitty; normally it picks the kitty it runs in) |
| `NL_TEST_DIR`, `NL_TEST_DISPLAY` | folder and X display for `scripts/test-kitty.sh` |
| `NL_DEV_DIR` | folder for `scripts/dev-kitty.sh` (default `~/.cache/ninelives-dev`) |
| `WIKI_URL`, `WIKI_REMOTE`, `WIKI_BRANCH` | where `scripts/publish-wiki.sh` publishes (default: the `origin` remote's wiki, on its default branch) |
