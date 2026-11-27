# Testing

## One command
```bash
bash scripts/check.sh           # everything, about 15 s
bash scripts/check.sh --quick   # without the test kitty
```
It checks:
- **Syntax:** the Python and shell scripts parse.
- **Unit tests:** `tests/`, which need no kitty, display or speakers (below).
- **Install:** into a temp folder, with kitty's config check, and every file arrives.
- **Sounds:** all eleven (the cat's meow, mrrp and purr too) are present and on their loudness targets.
- **The cat's frames:** all 87 frames (16 poses, the walk both ways and five mouths, in three sizes, 96, 192 and 384 px) are PNGs of the right size, each under 8 KB (16 KB at 384 px).
- **Links:** every wiki and README link resolves.
- **Live processes:** `tests/live_agent_lookup.py`, run with kitty's own Python (`kitty +launch`), starts bash in a terminal of its own with a fake agent (sleep under the name `claude`) below it, and checks `tab_bar.py` finds it, through its Linux branch (`/proc`) and its macOS branch (`kitty.child`, which reads `/proc` on Linux too).
- **A hidden test kitty:** no errors in its log, "needs you" plays, `kitty-relaunch.sh --status` sees working and waiting tabs, a shortcut earns its badge, the sidebar's buttons and the short-window list work, and with the search box open its tab's row keeps the folder, `✳` and branch of the window under it. Clicking `⚙` opens the settings list over the current tab and a second click closes it. Ctrl+Alt+C opens the helper cat about the waiting tab and closes it again, checked in full screenshots (no ginger fur right of the sidebar before, thousands of fur pixels while it's open, none after); a click on the sidebar's cat (`button cat:` in `sidebar.txt`) opens it, Enter goes to the waiting tab, and a second click closes it. In an 860 px window and at font size 20 (both make kitty's sidebar narrower) it checks the search row stays whole, that the button columns in `sidebar.txt` are where kitty drew `⚠`, `⚙`, `+` and `×`, and clicks them. It runs `API_KEY=… npm run deploy --token=…` and a bash builtin (`KEY=… read`) in new tabs and checks the sidebar (`drawn name:` in `sidebar.txt`), the search box and `--status` show `npm run deploy` and `read`, `--dry-run` doesn't mention the secret, and no file in the state or cache folder holds the made-up secret. Last, it splits three tabs (nested splits with a Claude pane, a renamed tab, a zoomed tab), restarts the test kitty with `kitty-relaunch.sh` and checks every tab comes back with the same panes, folders, layout, split sizes, active pane and name (one Claude tab sits in a folder named `$HOME x`); that `--dry-run`, the log and the session file list the same panes; that resumed omp and Claude tabs keep their sidebar marks (`agents:` in `sidebar.txt`), within 1.5 s of the new kitty's first sidebar (`sidebar.txt` is watched while the restart runs; its `kitty:` line names the writer); that the new kitty doesn't hold the restart's lock; that restored shells, and the shell a resumed agent leaves when it exits, have kitty's shell integration (the last command's output reads back); and that restored plain shells are named by their folder.

The test kitty also checks the drawn cat (driven by `tests/cat_ctl.py`, a kitten run over the test kitty's socket only): its fur is on the sidebar's floor, it walks, a click opens its bubble (a picture) and it goes to point at the waiting tab, Go there goes there, × closes it, a click on a tab still works, it speaks up by itself letter by letter with a meow (and how steady its talking clock is), and `kitty-cat off` takes it away.

It also saves a sidebar screenshot to `/tmp/ninelives-check.png`. Run it before every commit.

## Unit tests (no kitty needed)
```bash
python3 -m unittest discover -s tests -v
```
- **`tests/test_tab_bar.py`** loads `config/tab_bar.py` against a small fake kitty, with HOME and quest state in a temp folder. It covers:
  - drawing and text fitting, including wide characters
  - the search field, its buttons (`⚠`, `⚙`, `+`), **+ New tab** and the `×` at every sidebar width (a narrow window, a big font), the field and chip colours (at least 4.5:1, and set apart from the row, in both themes), a held button lighting up (and going out when its release is lost)
  - no line of ours cuts a word: the quest line (every quest, badges, ranks, mastery, the Alt+N hint) and **+ New tab** take a shorter wording at every width from 5 to 40 cells, and the cat stays in one column
  - the quiet colours of the number, the agent mark and the "new output" dot (just above 4.5:1 and 3:1 in both themes), and the cat's colour for each mood
  - elapsed times and the "done" burst frames
  - the cat's priorities
  - sounds: mute, volume, bursts, the watched-tab rule, classic mode
  - real state changes through the timer: done, needs you, the reminder, closed tabs
  - quests and rank-ups
  - loading cleanly when kitty internals are missing (as after a kitty update)
  - the agent mark for an agent below a shell or kitten in the same process group (a restored tab), with a fake `/proc`
  - a mark still starting when its tab was first drawn appears within a second without anything else redrawing, and an idle sidebar stays idle (fake time)
  - an overlay (the search box): the row keeps the folder, mark, branch and title of the window under it, and a command under it keeps running
  - the macOS paths (class `MacOS`): `afplay` and the `.wav` sounds at the Linux level, macOS's own sounds for classic, `osascript` with the text as arguments, and the agent marks from a fake `kitty.child` (one process scan for every tab, never `/proc`)
- **`tests/test_command_title.py`** covers `config/command_title.py`: the short form of many real command lines (chains, pipes, `VAR=value`, sudo/env/timeout, interpreters with `-m`, a script or `-c` code, here-documents, unparseable lines), that a made-up secret in any of them never shows; which titles count as the command line (bash's, zsh's, fish's, over ssh, cut short, the moment before bash reports the command, no reported command but its program running) and which stay (agents' titles, folders); the search box's names and matching (an overlay's copied title, a window title you set, the `full-commands` switch); and `kitty-relaunch.sh --status`'s lines. `tests/test_tab_bar.py`'s `CommandTitles` checks the sidebar's side: renamed tabs, overlays, the switch redrawing at once, and the fallback row.
- **`tests/test_kitty_tabs.py`** feeds fake `kitty @ ls` output to `scripts/kitty-tabs.py`. It checks:
  - what `kitty-relaunch.sh` reopens: Claude with and without a session id, Claude started through node, omp, renamed tabs, the active tab
  - how: shells with no command (kitty's own, with shell integration), agents under `--hold`, folders with a `$` through `kitten run-shell`, an agent in its own process's folder
  - that `--dry-run` (show) and the session file say the same, pane by pane, and kitty's pid found above a wrapped window
  - split tabs: the session file's layout state, every pane's folder and command, the active pane, overlays, zoomed tabs, and the one-pane fallback when kitty gives no layout state
  - which tabs `--when-idle` waits for
  - which kitty a restart picks: the one it runs in, then any other with a socket, never the test or dev kitty
  - macOS: kitty's pid and the running kittys from `ps` (fake listings, then the real `ps`), sockets in the temp folder
- **`tests/test_relaunch.py`** runs `kitty-relaunch.sh` the way you do (from a tab, no `NL_KITTY_SOCKET`) against a stub `kitty` and a throwaway "old kitty" process: it picks the kitty it runs in, goes into the background with a clean environment, and starts the new kitty on the same socket without handing on its own internals (its marker, its lock); `OldLockHeld` restarts while something holds the lock file older versions used, as a kitty they started does. `MacLike` does it as on macOS: `uname` says Darwin, `date` has no `%N`, and there is no `setsid`, `flock` or `systemctl` (python3 detaches and locks).
- **`tests/test_install.py`** runs `scripts/install.sh` and `scripts/uninstall.sh` on a temp folder: which backups are kept, and that uninstalling removes only NineLives' files and puts your own config back; on "macOS" (a stub `uname`) the `.wav` sounds come and go. With kitty installed, kitty's own parser reads `kitty.conf` as on Linux (the socket unchanged) and as on macOS (`ninelives-macos.conf`), and the macOS Ctrl+Alt+M runs with a stub `afplay`.
- **`tests/test_settings.py`** loads `config/settings.py` with a temp config and state folder and a stubbed player: each row reads and writes the same switch file as its `kitty-*` command, the volume steps and clamps (and ignores a bad file), the keys (↑/↓, j/k, Enter, Space, ←/→, Esc, q) and mouse clicks, the drawing at narrow and wide sizes (no line wider than the window, the chosen row's description shown), the "finished" chime played at the new volume (not when muted or under `NINELIVES_QUIET`, and with `afplay` on macOS), and the kitty.conf row (`kitty @ action edit_config_file` with remote control, your editor without).
- **`tests/test_nine.py`**: the cat's parts in `config/nine.py`: its routes and steps, which picture shows, the steady pace of its words and its mouth, the bubble picture (its parts and click regions, with a stand-in text renderer), that the bubble stays inside and points at the cat, buttons that go on a second row or shorten in a narrow bubble (every click region inside it), and its memory (no repeats across many polls or Next presses, the cooldowns, over a restart, and no words in its file, an older file's words hashed away).
- **`tests/test_sidebar_cat.py`**: the drawn cat in `tab_bar.py` against a fake sidebar Screen: only quiet graphics commands reach it, every frame is kept alive and the cat put back after a redraw, the floor / small / face / off choice, never scaled up, it stays inside, the night nap, what a click lands on (the bubble first, then ×, then the cat), the bubble readable in both themes, each event said once, a new wait noticed even when another ends in the same tick, the news about the tab it names (the one that just finished), Go there into another kitty window, the open bubble made again for new frames or a narrower sidebar and in cells for the face, and no `cat.txt` writes inside kitty's redraw.
- **`tests/test_cat_helper.py`** loads `config/cat-helper.py` with a temp config and state folder, a pinned date and scripted dice: what the cat says and in which order (waiting, error, finished, hello, badge, quest, then the day's tip, joke and word), the counts and names in it, the day's lines staying the same all day and changing the next, "don't suggest this again" (never again, any day; tab news can't be hidden), badges and the next quest read from a `quests.txt` written by `tab_bar.py`'s own code, `quests-off`, the tip pool read exactly as bash reads `tips.sh`, the graphics protocol's chunks (at most 4096 base64 bytes, `m=1` but the last, `q=2`), every shipped frame (a PNG of its size, under 8 KB, the same list as `make-cat.py`), each frame sent once and swapped new-then-old, no `\e[2J`, the dice and the night nap, reacting to a tab that starts waiting or finishes, keys, clicks on the bubble's buttons and the cat, the layout at many window and cell sizes (nothing past the edge), the toggle, and the bubble alone without its frames. `tests/test_tab_bar.py`'s `HelperCat` checks the click on the sidebar's cat (per kitty window, only its first line, none with `kitty-cat off`) and that the key and the click run the same command and earn no badge.
- **`tests/test_check_macos.py`** reads `scripts/check-macos.sh` (which only runs on a Mac) and checks what would otherwise break only there: the real kitty's environment is an array expanded quoted in both `env` calls, and its folder has a space in its name so every macOS run exercises that; the number of `.wav` sounds it expects follows `config/sounds` (and `make-sounds.py` makes each one). It also checks that `scripts/test-kitty.sh` grabs the whole hidden screen: without `-video_size`, the Gauntlet's ffmpeg 4 grabs only its top-left 640×480, below which the sidebar's cat sits.
- **`tests/test_desktop_mcp.py`** covers `tools/desktop-mcp/server.py` without starting anything: its folder is private (made 0700, a folder others can open or a link refused, a fresh `mkdtemp` one without `$XDG_RUNTIME_DIR`), and a panel's command comes after `--` so it can't set panel options, while options that would take the keyboard or outlive the timeout (`--focus-policy`, `--grab-keyboard`, `--single-instance`/`-1`, `--instance-group`, `--detach`) are refused.
- **`tests/test_tips.py`** sources `config/tips.sh` in bash with a temp config folder and a stub `paplay` (and `afplay` for the macOS path), and again in zsh where there is one. It covers:
  - `kitty-sounds`: volume, off/on, classic, and the preview playing each sound at the set volume
  - `kitty-cat`, `kitty-quests` and `kitty-tips` switches
  - `ninelives` output and its column alignment, and `ninelives settings`
  - `kitty-quests` wrapping to the window

## macOS
`scripts/check-macos.sh` runs on a Mac (the Gauntlet's `macos` lane runs it on GitHub's macOS 15 with
the official kitty `.dmg`). It uses what a Mac has out of the box: `/bin/bash` 3.2, `/usr/bin/python3`,
zsh, BSD tools and kitty.app's folder on `PATH`. It runs every unit test (no macOS test may be
skipped, the zsh ones included), installs and uninstalls into a temp folder with kitty's config check,
checks where the socket goes, that `afinfo` reads the `.wav` sounds and `osascript` gets the
notification text unchanged, runs `tests/live_agent_lookup.py` with kitty's macOS helpers, and last,
on a Mac with a display, starts the real kitty with NineLives' config: its socket, `kitty @ ls`,
`kitty-tabs.py sockets` and `kitty-pid`, the `✳` mark in `sidebar.txt`, and a restart that brings both
tabs back. **On the Gauntlet that last part never runs:** GitHub's macOS runners have no OpenGL 3.3
(kitty asks for a hardware renderer: "NSGL: Failed to find a suitable pixel format"), so it is skipped
with a warning, and a running kitty on a Mac is untested until someone runs this on a real Mac.
Only that no-OpenGL case is a skip: kitty exiting before its socket for any other reason is a failure.
Read the last lines before counting the real-kitty checks as passed: "All macOS checks passed, the
real kitty's included" means they ran; "the REAL-KITTY CHECKS WERE SKIPPED" means they didn't. It opens a kitty window of its own and restarts it, sends one test notification and plays
one near-silent sound (your kitty config is left alone). A CI machine is not a Mac on a desk: hearing
the sounds, seeing notifications, the look on a Mac's screen and dragging tabs are untested, and
nobody has run NineLives on a real Mac yet.
```bash
bash scripts/check-macos.sh [PATH/TO/kitty.app]
```

## A dev kitty you can see
`scripts/dev-kitty.sh` opens a visible "NineLives dev" kitty for trying changes by hand. It has its own config
folder (`~/.cache/ninelives-dev/config`, installed from the repo), its own quest state and remote-control socket.
It starts muted and sends no desktop notifications. Your other kitty windows and `~/.config/kitty` stay untouched,
and its shells load the dev `tips.sh`, so `kitty-sounds off` there flips the dev switch.
```bash
bash scripts/dev-kitty.sh start        # open it
bash scripts/dev-kitty.sh reload       # reinstall from the repo and reload in place (no new window, no focus change)
bash scripts/dev-kitty.sh restart      # reinstall and reopen (needed for changes to the kitty patches)
bash scripts/dev-kitty.sh sound on     # let it play sounds (off: mute again)
bash scripts/dev-kitty.sh k ls         # any kitty @ command
bash scripts/dev-kitty.sh stop
```

## A hidden test kitty
`scripts/test-kitty.sh` (needs Xvfb and ffmpeg) installs `config/` into a throwaway folder and starts
kitty on a hidden X display with one tab per status: working, title spinner, progress, Claude working,
done, needs you, error, new output, a long renamed title and wide characters. Sounds and notifications go
to stubs, and quests use their own state folder, so nothing reaches your real kitty, speakers or badges.
```bash
bash scripts/test-kitty.sh start light       # or dark; add a size, e.g. 1100x760, and a font size, e.g. 20
bash scripts/test-kitty.sh shot sidebar      # screenshot of the sidebar (2x); prints the PNG path
bash scripts/test-kitty.sh shot all "null"   # the whole window (any ffmpeg filter)
bash scripts/test-kitty.sh k focus-tab --match index:6   # any kitty @ command
bash scripts/test-kitty.sh k action toggle_layout stack  # earns a badge (test state only)
bash scripts/test-kitty.sh sounds            # which sounds it would have played, and at what volume
bash scripts/test-kitty.sh relaunch          # kitty-relaunch.sh on the test kitty only (--dry-run lists)
bash scripts/test-kitty.sh stop
```
`claude` and `omp` are stubs in the test kitty (they log to `agents.log` and sit like the real ones), so
a relaunch there never starts a real agent.
Inside a test tab, `st` fakes a status: `st title "⠋ busy"`, `st prog 42`, `st state blocked`,
`st done`. It runs on X11, so it doesn't exercise the Wayland tab drag or background blur.

**Motion.** One screenshot can't show an animation. Record a strip:
```bash
ffmpeg -f x11grab -framerate 16 -video_size 160x40 -i :97+0,660 -t 2.6 \
  -vf "fps=8,scale=iw*2:ih*2:flags=neighbor,tile=7x3" -frames:v 1 strip.png
```

`NL_TEST_SCENE=none bash scripts/test-kitty.sh start` starts the test kitty with one empty tab instead
of one tab per status, for building a scene of your own. `NL_TEST_CAT_DICE=SEED` gives its cat seeded
dice, and a move named in `state/cat-move` (`wink`, `look-left`, `tail`, …) plays at its next roll (it
stays cued while another move plays), so a recording shows the same cat every time. That cat also
ignores the clock: no nap from 23:00 to 06:00 (`_night` is off). Only the test kitty's copy of
`tab_bar.py` changes.

## Recording the GIFs
The GIFs in the README and the wiki (`docs/images/gifs/`) and the Getting started stills
(`docs/images/steps/`) come from `scripts/record.sh`. Each recording starts the hidden test kitty with
its own made-up tabs, drives it (states are written to the fake agents' terminals, clicks go through
`xclick.py`, the restart through `test-kitty.sh relaunch`), records the display with ffmpeg's x11grab
at 10 fps and turns that into a GIF with a palette made for it. Make them again after a UI change:
```bash
bash scripts/record.sh list              # getting-started status status-light search buttons streak restart
bash scripts/record.sh streak search     # some of them
bash scripts/record.sh all               # all of them (about 4 minutes: status waits a minute so times show)
```
Sidebar recordings are doubled in size (nearest-neighbour, so text stays crisp); whole-window ones are
1:1. The test window is 960 px wide: below about 950 px kitty makes the sidebar narrower (a third of
the window at most) and the search row shortens its words, which isn't the look the GIFs show. Look at
the result before committing, and keep each GIF small (they are
50–200 KB). Like the test kitty, it uses the hidden display only, so run it when no one else
(`check.sh` included) is using the test kitty.

## The YouTube Short
`tools/short/` makes the vertical Short the same way: `capture.sh` records three takes from the hidden
test kitty (real shortcuts pressed with `scripts/xkey.py`, states written to the fake agents, the
restart through `test-kitty.sh relaunch`) with a meta file of captions and event times, and
`compose_short.py` puts them together with the sounds the stubs logged, over a music bed
(`music.py`) synthesized with the same timbres as the sounds. See
[tools/short/README.md](https://github.com/Vyeche/NineLives/blob/main/tools/short/README.md).

**Checks before committing a tab_bar.py change** (beyond `check.sh`)
- A screenshot in both themes.
- The reload path: start with the old file, copy the new one in, `kitty @ load-config`. There should be no errors in the kitty log, and sounds should not play twice.
- An idle window should stop redrawing.

## Clicking and typing on the hidden test kitty
`scripts/xclick.py :97 X Y [button]` clicks at a pixel on the hidden test kitty's display (X11 XTest),
so your real pointer never moves. `check.sh` uses it to click the `⋯ hidden:` line of a short window.
`scripts/xkey.py :97 ctrl+alt+u` presses keys there the same way (`--type TEXT` types), so a recording
can use the real shortcuts.

## A virtual mouse
`scripts/vmouse.py` (needs python-evdev and write access to `/dev/uinput`) drives a real kitty window,
steering by the pointer positions in kitty's `--debug-input` log. It presses only while that log shows the
pointer inside the test window, and releases every button on exit. It moves your real pointer, so use it on
a window you've set aside.
```bash
kitty --debug-input --start-as fullscreen > /tmp/k.log 2>&1 &
python3 -I scripts/vmouse.py /tmp/k.log wiggle goto:100,25 down goto:100,170 up
```
Steps: `wiggle`, `goto:X,Y`, `down`/`up`, `mdown`/`mup`, `sleep:S`, `shot:DIR`, `key:ctrl+alt+z`.
Set `NINELIVES_STATE=<folder>` on a test kitty so its quests don't touch your real badges.
