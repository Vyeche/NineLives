# Commands and switches

These shell commands come from `~/.config/kitty/tips.sh` (see [Installing](Installing#prompt-tips)).
Each switch is just a file in kitty's config folder (`~/.config/kitty/`, or `$KITTY_CONFIG_DIRECTORY` for a kitty
started with one), so you can also create or delete it by hand.
`install.sh` never creates or removes them.

`ninelives` shows them all at once: sounds (on/muted, volume, which set), the cat, quests (badges,
rank, next quest) and tips, each with the command that changes it. It also warns when kitty is still
running an older `tab_bar.py` than the installed one, which means a restart is due.

| Command | Does | File |
| --- | --- | --- |
| `ninelives` | every setting below at a glance | |
| `kitty-sounds` | play each sound with its meaning | |
| `kitty-sounds volume N` | tab sound volume, 5–100 % | `sounds-volume` |
| `kitty-sounds off` / `on`, **Ctrl+Alt+M** | mute / unmute | `sounds-off` |
| `kitty-sounds classic` / `ninelives` | desktop sounds / NineLives sounds | `sounds-classic` |
| `kitty-buttons` / `off` / `on` | explain / hide / show the sidebar's search row and the × on the current tab | `buttons-off` |
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
