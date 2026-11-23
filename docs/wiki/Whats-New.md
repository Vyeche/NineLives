# What's new

Changes you'd notice, newest first. To get them: `bash scripts/install.sh`, then restart kitty with
`bash scripts/kitty-relaunch.sh --when-idle` (see [Installing](Installing)).

## 2026-11-23
- **Restored tabs work like new ones:** after `kitty-relaunch.sh`, plain shells are kitty's own shell with kitty's shell integration, so Ctrl+Shift+Z/X (jump between prompts), Ctrl+Shift+G (last command's output) and opening new tabs in the shell's folder work right away. When a resumed Claude or omp exits, the shell that takes its place has it too. Resumed Claude and omp tabs keep their `✳`/`π` mark in the sidebar. `--dry-run` and the log now list exactly what reopens (a pane whose folder is gone shows as home, with its note), and a folder with a `$` in its name comes back as that folder.

## 2026-11-22
- **Social preview:** sharing the repository link now shows a NineLives card with a real sidebar (`tools/social_preview.py` makes it from a recorded still).
- **A YouTube Short:** [watch it](https://youtube.com/shorts/hra1NPQsbwk). `tools/short/` records a vertical Short of NineLives from the hidden test kitty (the real shortcuts, NineLives' own sounds where they played over an original music bed made with the same synth, a close-up of the sidebar and the cat) and can render it again after a UI change. `scripts/xkey.py` presses keys on the test display, and `scripts/record.sh` can be sourced for its scene helpers.
- **Narrow windows and big fonts:** below about 950 px (or with a bigger font) kitty narrows the sidebar, and the search row lost its buttons to an `…` while clicks landed beside them. The row now fits the sidebar's real width: the words shorten (`Search…`, `Find…`, `❯`) and `⚠1` and `+` stay whole and clickable, with `+` above the current tab's `×`. **+ New tab** and the quest line fit too.
- **Fix: tabs named "bash" after a restart.** A plain shell reopened by `kitty-relaunch.sh` sets no title, so kitty called it `bash`; the sidebar and the tab search now show its folder, as before the restart. A tab you renamed `bash` keeps that name.
- **Pictures:** the README and the wiki show NineLives moving: short GIFs of the sidebar's states (dark and light), the tab search, the buttons, the climbing done chime and a restart bringing split tabs back, and a new [Getting started](Getting-Started) page that walks from install to your first "needs you". They are recorded from the hidden test kitty with made-up tabs, so `bash scripts/record.sh` makes them again after a UI change.
- **Public on GitHub:** NineLives is MIT licensed, with a security policy, a code of conduct and an uninstaller (`bash scripts/uninstall.sh --dry-run`, then without `--dry-run`: removes only NineLives' files and puts your own `kitty.conf` back). The restart now works with any kitty: `kitty.conf` gives each kitty a private remote-control socket (`$XDG_RUNTIME_DIR/ninelives-kitty-<pid>`, from kitty's next start), and `kitty-relaunch.sh` restarts the kitty you run it in (a kitty started with `--listen-on` keeps working as before). Its log and session file moved to `~/.cache/ninelives/`; the old `~/.cache/claude-launcher/` folder is no longer used and can be deleted. `publish-wiki.sh` publishes to the GitHub wiki (or any `WIKI_URL`). Fix: on a system without a systemd user manager (or without `XDG_RUNTIME_DIR`), `kitty-relaunch.sh` stopped silently instead of restarting.
- **Fixes from a review:** a restart keeps tab names with `$` in them as typed (kitty expanded `$HOME` in a session file), and a name, folder or command with a line break can no longer make the new kitty open just an error window (kitty now checks the session file before the old kitty closes). A Claude pane without a session id whose folder is gone no longer resumes your home folder's newest session. The search key closes only a search box in the tab you're in (one left open in another tab no longer swallows the key), and never a window that merely mentions `tab-finder.py search`. Search results fit narrow split panes again, and `kitty-quests` shows each badge's `n/10` as you go, not only after the next badge.
- **Tidy backups:** `install.sh` keeps the newest 3 backups of each file it replaces, plus the very oldest one (most likely your config from before NineLives); `NL_KEEP_BACKUPS=N` or `all` changes it.
- **Safer restarts:** two restarts started at once no longer both run (the second stops); if the old kitty doesn't close (a question on screen), the restart stops instead of opening a second kitty; and it stops cleanly if it can't find kitty's process.
- **Fix: a second restart from a tab could leave kitty closed.** The restart passed its internal "already in the background" marker on to the new kitty, so the next `kitty-relaunch.sh` started from one of its tabs skipped going into the background and died with the old kitty. It now uses a one-time token that is never handed on.
- **Mastery:** use a learned shortcut 10 times to master it (`✪`), with a sparkle under **+ New tab**. `kitty-quests` shows each badge's progress (`3/10`); F1 and `ninelives` show what you've mastered.
- **Search toggles:** pressing Ctrl+Shift+Space (or clicking the search row) while the search box is open in that tab closes it, instead of opening a second one on top.
- **No ⚠ without a reason:** the search row shows `⚠2` only while tabs are waiting for you; otherwise it's just the search and `+`.
- **Search shows agents and branches:** results in the tab search carry the sidebar's agent mark and a branch other than main, and the branch is searchable. When no tab contains your words, letters in order still match (`mdb` finds "Migrate database").
- **Restarting kitty keeps your splits:** `kitty-relaunch.sh` brings back every pane of a split tab, each in its own folder with its own command (Claude resumes its session, omp continues, shells come back as shells), in the same layout and split sizes, with the pane you were in. A zoomed tab (Ctrl+Alt+Z) still unzooms to its splits. Two fresh Claude panes in one folder no longer both get `claude --continue`. `--dry-run` lists every pane.
- **Polish (with impeccable):** the search row uses `❯` (the search box's own prompt) with `⚠` and `+` lined up with the current tab's `×`; the search box puts the input on top, the filters as plain words (the current one underlined), a `❯` pointer instead of a white bar, and the keys in a footer; the branch mark is `⌥` (crisp in DejaVu Sans Mono). Secondary text in the search box, F1 sheet, tips and quest list uses palette colour 7 instead of dim, which was too faint on the light theme.
- **Search row and buttons** on top of the sidebar (like Warp): `❯ Search tabs…` opens the tab search, `⚠` goes to the tab waiting for you, `+` opens a tab, and the tab you're on has a `×` that closes it. `kitty-buttons off` hides them.
- **Which agent is in each tab** (like Warp's tab icons): a small grey mark under the status icon, `✳` for Claude, `π` for omp, two letters for other agents.
- **Search tabs:** **Ctrl+Shift+Space** opens a search box over the current tab. Type part of a tab's name, folder or number, then Enter goes there. It shows the same status icons as the sidebar, and **Tab** switches between All, Waiting, Working and Done (with counts). Your tab keeps its name in the sidebar while it's open (the F1 sheet too).
- **Jump to the tab waiting for you:** **Ctrl+Alt+U** goes to the next tab with ⚠ (or ✗ when none is waiting).
- **Git branch in the sidebar:** a branch other than `main`/`master` shows after the folder (`code/api ⌥ fix-parser`).
- Two new quests for them: **Seeker** and **First Responder** (16 in all now).
- **A quest of the day:** the quest under **+ New tab** rotates daily among your next three, instead of waiting on one forever.
- **Finishes climb a tune:** when tabs finish one after another (within 90 s), each done chime is a step higher than the last. Just as quiet. The cat sings along: `♪`, `♪♪`, `♪♪♪`.
- **F1 shows your progress:** quest shortcuts are marked `★` (not done yet) or `✓` (badge earned).
- **Learning by clicking:** click a tab with the mouse and the line under **+ New tab** shows its key for a moment (`Alt+3 also gets here`), until you've earned Jumper.
- **No more focus stealing:** a tab that needs you no longer asks COSMIC for attention. COSMIC answered by pulling kitty to the front, which could make you type into the wrong window.
- **Short window, many tabs:** a tab waiting for you, the tab you're on and the cat no longer drop off the bottom of the sidebar. The tabs that don't fit are listed on the last line (`⋯ hidden: 1–2`), and every tab keeps its number. Click that line to go to the first hidden tab.

## 2026-11-21
- **Works on kitty 0.51** (tested; every kitty internal NineLives relies on is still there).
- **`ninelives`** shows every setting at a glance (sounds, volume, the cat, quests, tips, and how to change each), and warns when kitty needs a restart to load the installed `tab_bar.py`.
- **`--when-idle`** says which tabs it is waiting for, when you start it and in its log.
- **Restarting kitty keeps more:**
  - tab names you set with Ctrl+Shift+R come back
  - kitty lands on the tab you were on
  - Claude tabs started without a session id come back with `claude --continue`, unless another Claude tab shares the folder
- **`--when-idle` waits for real work:**
  - a Claude tab that is working or waiting for you counts as busy (before, it could look idle)
  - so does a running build or test, including `node script.js`
  - `kitty-relaunch.sh --status` shows what it's waiting for
- The F1 sheet lists `ninelives`, `kitty-sounds` and `kitty-cat`.
- Fixes:
  - a crash on `claude --resume` without an id
  - `install.sh` printing a traceback on old kitty
  - a crash if a kitty update renames an internal the quest patch uses
- For working on NineLives:
  - unit tests that need no kitty (`tests/`)
  - a visible, isolated dev kitty (`scripts/dev-kitty.sh`)
  - a picture of the sidebar in the README

## 2026-11-18
- **Sounds:** NineLives' own set, quiet on purpose. Each has its own shape:
  - done: two notes up
  - needs you: a rising "mrrp?"
  - error: two low notes down
  - badge and rank-up sounds, plus a tiny tick when a dragged tab lands

  Other sound changes:
  - silent for the tab you're watching
  - bursts play once
  - one soft reminder for a tab left waiting 3 minutes
  - `kitty-sounds` to hear them and set the volume, `kitty-sounds classic` for the desktop's sounds
- **The cat** at the end of **+ New tab** sums up every tab: needs you, working, finished, error, badge, napping. See [The cat](The-Cat).
- **Animations:**
  - a finished tab bursts `· ✧ ✦ ✶` and lands on ✓
  - smoother spinner
  - badges send a gold wave down the tab numbers; rank-ups get a fanfare and a crown
- **Sidebar:**
  - how long each tab has been working, waiting or finished (`3m`)
  - "needs you" is a filled amber block
  - Claude's `✳` prefix is dropped from names
- **Fixes:**
  - the spinner could freeze after 15 s without typing
  - "+ New tab" could show as a bare "+" at startup
- **Wiki** (this), a shorter README, and `scripts/check.sh`.
- Docs for the soft "dusty" terminal colours and the shell colour setup.

## 2026-11-17
- First version:
  - tabs in a left sidebar with live status icons and sounds
  - tab dragging that works on COSMIC
  - `kitty-relaunch.sh`, `install.sh`, the F1 sheet and prompt tips
- **Quests and badges:** learn 14 kitty shortcuts by using them. See [Quests and badges](Quests-and-Badges).
