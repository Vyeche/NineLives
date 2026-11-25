# Product

<!-- impeccable:product-schema 1 -->

## Platform

terminal (kitty 0.50+ on Linux; built on and tuned for Pop!_OS COSMIC, Wayland. macOS has its own code paths since 2026-11-23, checked by a CI runner but not yet used on a real Mac). Not web, iOS or Android: the "UI" is kitty's tab bar drawn by `config/tab_bar.py`, terminal cells, the palette colours of the theme, and small shell scripts.

## Users
People who run many Claude Code / omp / opencode sessions at once, each as a tab in one kitty window (often opened by a launcher), and glance at the sidebar while doing other things. It was built for one person, its maintainer, who was still learning kitty and the terminal and wanted the setup to teach them as they go; it is now public.

## Product Purpose
Make a window full of agent sessions easy to watch and fun to use: see at a glance which tab is working, finished, or waiting, move between and reorganise tabs with the mouse or keys, and pick up new kitty/terminal skills along the way. Success: you never miss a tab that needs you, and keeps learning shortcuts because it is enjoyable.

## Positioning
A kitty setup built around watching many AI coding sessions at once: live per-tab status with sound, a tab drag that works on COSMIC Wayland where kitty's own does not, one-command restart that brings every session back, and learning built in (tips, quests, badges).

## Operating Context
- One kitty OS window with a left sidebar of tabs, often 5–15 tabs; started from the desktop or by a launcher (which may give kitty its own `--listen-on` socket).
- Light and dark themes follow the desktop's light/dark setting where the desktop reports one through the desktop portal (COSMIC does); dark where none is reported.
- Changes are installed with `scripts/install.sh`; `tab_bar.py` changes need a kitty restart (`scripts/kitty-relaunch.sh --when-idle`).
- The sidebar is glanced at, not studied: status must read without reading words.

## Capabilities and Constraints
- Sidebar: two lines per tab (number, status icon, name; then the agent mark, the folder, a git branch other than main, and how long the tab has been in its state), drag to reorder, middle-click close, "+ New tab". A search row on top (❯ Search tabs…, ⚠ jump to the waiting tab, + new tab) and a × on the current tab; `kitty-buttons off` hides them. A running command's tab shows only its program and subcommand (`git push`), never its arguments (they can hold secrets); `kitty-commands full` shows whole lines. In a short window the tabs that matter stay in view and the rest are named on a "hidden:" line.
- Finding tabs: Ctrl+Shift+Space search box (filters All / Waiting / Working / Done), Ctrl+Alt+U jumps to the tab waiting for you (`config/tab-finder.py`).
- Status icons with colour: working, done, needs you (a filled amber block, the strongest mark in the sidebar), error, new output.
- Sounds: NineLives' own (`config/sounds/`, built by `scripts/make-sounds.py`), one per event with its own pitch shape; finishes in a row climb a step (done, done-2, done-3); needs you is the loudest; bursts play once; one soft reminder for a tab left waiting 3 min unseen. Mute: Ctrl+Alt+M; `kitty-sounds classic` for the desktop's sounds.
- The cat (`=^.^=`) at the end of "+ New tab" sums up the window (needs you, working, finished, error, badge, napping); `kitty-cat off` hides it. Idle it is ginger and has small moves (blink, wink, glance, whisker twitch, tail flick), and it reacts to what happens; it redraws only while a move plays and sleeps from 23:00 to 06:00 when nothing is going on. It stops redrawing once it is asleep.
- Learning: F1 cheat sheet, a random tip under each new shell prompt (`kitty-tips`).
- Quests and badges (built 2026-11-17): 16 shortcut quests (the next one rotates daily among the first three), ★/✓ marks in F1, an Alt+N hint when you click a tab, badges with their own sound, a notification, a sparkle and a gold wave down the sidebar, ranks with a fanfare; `kitty-quests` lists them.
- kitty has no hover tooltips on tabs; anything "tooltip"-like must be drawn in cells, shown in the prompt, or sent as a notification.
- Everything must survive a config reload and degrade safely if a kitty update renames internals.

## Brand Commitments
- Name: NineLives ("Nine lives, one cat").
- COSMIC look: colours from COSMIC Dark/Light, DejaVu Sans Mono, COSMIC orange accent (teal in light).
- Two lines per tab: name on top, folder underneath.
- Keep the status sounds and the spinner/sparkle/pulse animations.
- Voice: plain, friendly, short.

## Documentation
README.md is the overview and quick start; the details live in the wiki (`docs/wiki/`, published to the
repository's wiki with `scripts/publish-wiki.sh`). Keep README, the wiki, the F1 sheet (`shortcuts.sh`) and the
tips (`tips.sh`) in step when behaviour changes.

## Evidence on Hand
- Screenshots used in testing live only in session scratchpads; nothing committed. `scripts/test-kitty.sh` makes new ones.
- No usage numbers, testimonials or metrics; none should be invented.

## Product Principles
1. Status first: what each tab is doing must be readable in a glance, by icon and colour, before any text.
2. Readability is non-negotiable: text ≥ 4.5:1 and icons ≥ 3:1 in both themes.
3. Fun that teaches: delight (animation, sound, badges) should point at something worth learning, never just noise.
4. Never get in the way: no prompts or popups while an agent session is working; everything can be muted or turned off.
5. Survive kitty updates: patches check what they rely on and switch themselves off instead of breaking.

## Accessibility & Inclusion
Strong contrast in both themes (light theme especially). Status is never colour-only: each state has its own glyph. Sounds are optional.
