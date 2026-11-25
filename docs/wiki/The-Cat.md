# The cat

A small cat sits at the right end of the **+ New tab** line. It sums up every tab at once, so a glance at
one spot tells you whether anything wants you. The most important mood wins:

| Face | Colour | Means |
| --- | --- | --- |
| `=O.O= !` | amber, like ⚠ | a tab needs you (`2!` = two tabs). The `!` blinks at first, then stays |
| `=^▽^=✦` | gold | you just earned a badge (`♛` = a new rank) |
| `=^ω^= ♪` | green, like ✓ | a tab just finished (`♪♪`, `♪♪♪`: two or three in a row, each within 90 s) |
| `=>.<=` | red, like ✗ | something just failed |
| `=^.^= ~` | blue, like the spinner | tabs are working (the tail swishes) |
| `=^.^=` | ginger | nothing going on (it blinks, and now and then winks, glances or flicks its tail) |
| `=-.-= zZ` | lavender | nothing has worked or waited for 3 minutes: it naps |

The mood colours are the theme's palette colours, at least 3.9:1 on the sidebar in both themes. The
palette has no orange, so the idle ginger is colour 130 of the 256 (`#af5f00`, the same in both
themes): 3.3:1 on the dark sidebar and 3.6:1 on the light one. The face stays in one place while its
extras (`~`, `zZz`, `♪♪♪`) come and go.

"Needs you" always wins, even over a celebration.

## It moves

The cat moves: short moves on top of its mood's face.
Each move changes only its part of the face (the eyes, the mouth, a whisker, the tail), so two can
play at once, like a blink in the middle of a tail flick. Moves last a few frames of 1/8 s.

| Move | Looks like | How long | When |
| --- | --- | --- | --- |
| blink | `=-.-=` | 1/8 s | about once every 5 s: idle, working, happy or cheering |
| wink | `=^ω-=` | 0.6 s | now and then, idle or working |
| glance | `=<.<=`, `=>.>=` | 1 s | now and then, idle or working |
| whisker twitch | `~^.^=`, `=^.^~` | 1 s (twice) | now and then, idle or working |
| tail flick | `=^.^= ~` `-` | 1 s | now and then, idle (working, the tail swishes anyway) |
| surprise | `~OoO~ !` | 0.5 s | a tab starts waiting for you |
| hop, then a wave | `=>ω<= ♪`, `=^ω^/ ♪` | 0.5 s + 1.1 s | a tab finishes |
| cheer | `\^▽^/✦` | 1.1 s | you earn a badge |
| flinch | `~>.<~` | 0.75 s | something fails |

"Now and then" is a roll of the dice once a second: about 1 in 5 for a blink and 3 in 100 for one of the
others, when nothing else is playing. A move belongs to its mood: a hop is skipped if a tab needs you at
the same moment. While a tab needs you the cat only stares (`=O.O= !`), however long the wait, so a
waiting kitty stays as still as before.

The sidebar is redrawn only when the face changes: never between moves (a blink costs two redraws,
on and off), and not at all once the cat is fully asleep, so an idle kitty doesn't redraw at all.

## At night

From 23:00 to 06:00 (your local time) the idle cat doesn't wait the 3 minutes: as soon as nothing works
or waits it dozes off (`z` … `zZz`), and a minute later it holds still. Anything more important wakes
it: a tab that needs you, finishes, fails or works, or a badge.

```bash
kitty-cat          # show this list
kitty-cat off      # hide the cat (or: The cat, in the settings list, Ctrl+Shift+F2)
kitty-cat on       # bring it back
```
