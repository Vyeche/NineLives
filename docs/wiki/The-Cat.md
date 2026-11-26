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

## Ask the cat

Click the cat (or press **Ctrl+Alt+C**, or type `ninelives cat` in a shell) and it comes out over
the current tab, drawn, with a speech bubble. It says what needs you first, then something for the day:

| It says | When | Enter |
| --- | --- | --- |
| *Tab 7 "Migrate database schema to v2" is waiting for you. Go there?* | a tab waits for you (*Two tabs are waiting…* for more) | goes there (like Ctrl+Alt+U) |
| *Tab 8 "Deploy to staging" stopped with an error. Go there?* | a tab failed | goes there |
| *Two tabs finished: tab 6 "Write release notes" and 9. Go to tab 6?* | tabs finished and you haven't looked yet | goes to the first |
| *Good afternoon! It's Thursday, November 26. Nothing needs you right now. Two tabs are working.* | nothing waits, failed or finished | the next line |
| *You earned the Zoom Lens badge today: ★ 5 of 16, rank House Cat.* | you earned a badge today | the F1 sheet |
| *Ctrl+Alt+Z zooms one pane to full size (again to go back). Use it once to earn the Zoom Lens badge.* | today's quest | the F1 sheet |
| a **tip**, a **joke** and a **word of the day** | always, last | the next line |

The tip comes from the same pool as the tips under your shell prompt; the joke and the word (a
terminal word explained plainly, like *socket* or *scrollback*) are the cat's own. Each is picked by the
date, so it stays the same all day and changes tomorrow.

| Key | Does |
| --- | --- |
| **Enter** | what the bubble offers (go to the tab, open the F1 sheet), else the next line |
| **→**, **n**, **Space** | the next line (the bubble's top right says which, `2/6`) |
| **←**, **p** | the one before |
| **d** | don't suggest this one again (tips, jokes, words, the quest, a badge; not news about your tabs). Kept in `~/.local/state/ninelives/cat-helper-hidden`: delete a line there to get it back |
| **Esc**, **q** | close (so does Ctrl+Alt+C or a click on the sidebar's cat) |

The buttons in the bubble work with a click, and clicking the drawn cat gets the next line (it winks).

While it's open it keeps an eye on your tabs (once a second): a tab that starts waiting makes it jump
(and the bubble switches to it), a finished one makes it hop and wave. In between it blinks and now and
then winks, twitches an ear, flicks its tail or glances, like the sidebar's cat; from 23:00 to 06:00 it
dozes when nothing needs you. It makes no sound (the tabs' own sounds already tell you), and it only
appears when you ask: it never pops up by itself.

The drawing is shown with kitty's graphics protocol, from small pictures that come with NineLives
(`cat/`, 15 poses in two sizes, built by `scripts/make-cat.py`), so nothing extra needs installing.
In a narrow window the cat sits above its bubble, and in a very small one the bubble shows alone.
`kitty-cat off` hides the sidebar's cat, so there is nothing to click; Ctrl+Alt+C still calls it.

```bash
kitty-cat          # show this list
kitty-cat off      # hide the cat (or: The cat, in the settings list, Ctrl+Shift+F2)
kitty-cat on       # bring it back
```
