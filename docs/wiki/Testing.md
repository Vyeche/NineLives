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
- **Sounds:** all six are present and on their loudness targets.
- **Links:** every wiki and README link resolves.
- **A hidden test kitty:** no errors in its log, "needs you" plays, `kitty-relaunch.sh --status` sees working and waiting tabs, a shortcut earns its badge. Last, it splits three tabs (nested splits with a Claude pane, a renamed tab, a zoomed tab), restarts the test kitty with `kitty-relaunch.sh` and checks every tab comes back with the same panes, folders, layout, split sizes, active pane and name.

It also saves a sidebar screenshot to `/tmp/ninelives-check.png`. Run it before every commit.

## Unit tests (no kitty needed)
```bash
python3 -m unittest discover -s tests -v
```
- **`tests/test_tab_bar.py`** loads `config/tab_bar.py` against a small fake kitty, with HOME and quest state in a temp folder. It covers:
  - drawing and text fitting, including wide characters
  - elapsed times and the "done" burst frames
  - the cat's priorities
  - sounds: mute, volume, bursts, the watched-tab rule, classic mode
  - real state changes through the timer: done, needs you, the reminder, closed tabs
  - quests and rank-ups
  - loading cleanly when kitty internals are missing (as after a kitty update)
- **`tests/test_kitty_tabs.py`** feeds fake `kitty @ ls` output to `scripts/kitty-tabs.py`. It checks:
  - what `kitty-relaunch.sh` reopens: Claude with and without a session id, Claude started through node, omp, renamed tabs, the active tab
  - split tabs: the session file's layout state, every pane's folder and command, the active pane, overlays, zoomed tabs, and the one-pane fallback when kitty gives no layout state
  - which tabs `--when-idle` waits for
  - which kitty a restart picks: the one it runs in, then any other with a socket, never the test or dev kitty
- **`tests/test_relaunch.py`** runs `kitty-relaunch.sh` the way you do (from a tab, no `NL_KITTY_SOCKET`) against a stub `kitty` and a throwaway "old kitty" process: it picks the kitty it runs in, goes into the background with a clean environment, and starts the new kitty on the same socket without handing on its own internals.
- **`tests/test_install.py`** runs `scripts/install.sh` and `scripts/uninstall.sh` on a temp folder: which backups are kept, and that uninstalling removes only NineLives' files and puts your own config back.
- **`tests/test_tips.py`** sources `config/tips.sh` in bash with a temp config folder and a stub `paplay`. It covers:
  - `kitty-sounds`: volume, off/on, classic, and the preview playing each sound at the set volume
  - `kitty-cat`, `kitty-quests` and `kitty-tips` switches
  - `ninelives` output and its column alignment
  - `kitty-quests` wrapping to the window

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
bash scripts/test-kitty.sh start light       # or dark; add a size, e.g. 1100x760
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
of one tab per status, for building a scene of your own.

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
1:1. The test window is 960 px wide: below about 950 px kitty makes the sidebar narrower and the end of
the search row is cut off (`…+`). Look at the result before committing, and keep each GIF small (they are
50–200 KB). Like the test kitty, it uses the hidden display only, so run it when no one else
(`check.sh` included) is using the test kitty.

**Checks before committing a tab_bar.py change** (beyond `check.sh`)
- A screenshot in both themes.
- The reload path: start with the old file, copy the new one in, `kitty @ load-config`. There should be no errors in the kitty log, and sounds should not play twice.
- An idle window should stop redrawing.

## Clicking the hidden test kitty
`scripts/xclick.py :97 X Y [button]` clicks at a pixel on the hidden test kitty's display (X11 XTest),
so your real pointer never moves. `check.sh` uses it to click the `⋯ hidden:` line of a short window.

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
