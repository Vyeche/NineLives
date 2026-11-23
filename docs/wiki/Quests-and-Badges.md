# Quests and badges

Sixteen kitty shortcuts worth knowing. Use one for the first time and you earn its badge: a bell sound,
a desktop notification, a sparkle under **+ New tab** and a gold wave down the tab numbers.

The line under **+ New tab** is your next quest, for example `★4  Ctrl+Alt+Z  zoom pane` (★ = badges so
far). It changes each day among your next three quests not done yet, so one you don't care for
doesn't sit there forever. Half of the tips under a new shell prompt are your next quest too.

- **F1** marks every quest shortcut: `★` = not done yet, a green `✓` = badge earned.
- **Clicking a tab with the mouse** shows which key does the same, e.g. `→  Alt+3 also gets here`, for
  6 seconds (at most every 90 seconds, and only until you've earned Jumper).

| Badge | Do this once |
| --- | --- |
| Splitter | **Ctrl+Alt+→** splits a tab side by side (**Ctrl+Alt+↓** top/bottom) |
| Pathfinder | **Ctrl+Alt+arrows** move between split panes |
| Zoom Lens | **Ctrl+Alt+Z** zooms one pane to full size (again to go back) |
| Jumper | **Alt+1…9** jumps to that tab |
| Shuffler | drag a tab to reorder it (or **Ctrl+Shift+←/→**) |
| Name Tag | **Ctrl+Shift+R** renames the tab |
| Time Traveller | **Ctrl+Shift+Z / X** jumps to the previous / next command |
| Replay | **Ctrl+Shift+G** shows the last command's output on its own |
| Deep Diver | **Ctrl+Shift+H** opens the scrollback in a pager |
| Link Hunter | **Ctrl+Shift+E** opens a link on screen by its hint letter |
| Glyph Finder | **Ctrl+Shift+U** types any emoji or symbol by name |
| Big Print | **Ctrl+Shift+= / -** changes the text size |
| Map Reader | **F1** shows every shortcut |
| Hush | **Ctrl+Alt+M** mutes / unmutes the tab sounds |
| Seeker | **Ctrl+Shift+Space** searches your tabs by name, folder or number |
| First Responder | **Ctrl+Alt+U** jumps to the tab waiting for you |

## Ranks
Kitten (0) → House Cat (4 badges) → Alley Cat (9) → Nine Lives (all 16). A new rank gets its own
fanfare and the cat wears a crown (`♛`) for a moment.

## Mastery
A badge only proves you tried a shortcut once. Use it **10 times** and you've mastered it: the line
under **+ New tab** sparkles `mastered: Zoom Lens!`, the gold wave runs and the badge sound plays (no
notification). `kitty-quests` shows how far along each badge is (`3/10`) and marks mastered ones `✪`;
the F1 sheet marks them `✪` too, and `ninelives` counts them. Clicking a sidebar button doesn't count:
it's the keys that are being learned. Counts live in `~/.local/state/ninelives/uses`.

## Commands
```bash
kitty-quests        # every quest, which you've earned and when, and your rank
kitty-quests off    # hide quests (badges are kept, and none are earned while off)
kitty-quests on
```
kitty only sees shortcuts, not shell commands, so every quest is a shortcut.

## Where progress lives
`~/.local/state/ninelives/`: `badges` (one `id<TAB>date` line per badge), plus `quests.txt` and
`next-quest`, which kitty rewrites for `kitty-quests` and the prompt tip. `install.sh` never touches this
folder. Set `NINELIVES_STATE=<folder>` on a kitty to keep its progress somewhere else (the test kitty does).
