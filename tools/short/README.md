# The NineLives YouTube Short

A vertical (1080x1920) Short of NineLives: captions on top, the kitty window in the middle at 1:1
(1080x384, font size 14 so it reads on a phone), and below it a close-up that follows what happens:
the whole sidebar with its pixels doubled (the cat sits at the end of **+ New tab**), the last two tabs
and the cat at 3x while the cat reacts, and the search box or the settings list while it's open (about
1.3x). Recorded live from the real program in the hidden test kitty, with the
real shortcuts pressed and NineLives' own sounds mixed in where they played, over an original music
bed made with the same synth as the sounds.

Two steps, both re-runnable:

| Step | What | Writes |
| --- | --- | --- |
| `capture.sh WORK_DIR [take1 take2 take3]` | starts the hidden test kitty (`scripts/test-kitty.sh`: display `:97`, its own socket, stubbed sounds), builds each take's made-up tabs with `scripts/record.sh`'s helpers, presses the shortcuts with `scripts/xkey.py`, and records the display losslessly. Exits non-zero if a take needs doing again (see the restart below) | per take: `NAME.mkv`, `NAME.meta.json` (captions, keys, state changes, close-up boxes and the stub-logged sounds, all in seconds since the first frame, and the sidebar's cell grid), `NAME.stub.log`, `NAME.text.txt` (every window's text, for the privacy check) |
| `compose_short.py WORK_DIR OUT.mp4 [--thumb PNG] [--no-music]` | cuts the takes together, draws captions, keycaps, the close-up and an end card, holds a dimmed frame over the restart's black, mixes the sounds over the music bed (`music.py`) and encodes | the MP4 (H.264 + AAC, 30 fps), a thumbnail, and in `WORK_DIR` the mix and its stems (`stem-sounds.wav`, `stem-music.wav`) |

```bash
W="$HOME/Videos/ninelives-short/work"              # anywhere outside the repo
bash tools/short/capture.sh "$W"                   # about a minute and a half; take1-3 (or name some)
python3 tools/short/compose_short.py "$W" --preview 4 24 43      # a few frames as PNGs in $W
python3 tools/short/compose_short.py "$W" "$W/../ninelives_short.mp4" \
    --thumb "$W/../ninelives_short_thumb.png"
```

Needs Xvfb, kitty, ffmpeg (libx264), numpy and pycairo (`python3-cairo`). Fonts: DejaVu Sans and
DejaVu Sans Mono.

## The story
- **take1** (a fresh test kitty): four sessions at work (Claude ✳, omp π). The close-up moves to the
  last two tabs and the cat (3x): one finishes (sparkle, ✓, the cat hops and waves, `=>ω<= ♪`,
  `=^ω^/`, `done.oga`), the other needs you (amber pulse, `~OoO~` then `=O.O= !`, `⚠1`,
  `needs-you.oga`). Ctrl+Alt+U goes there, Ctrl+Shift+Space finds a tab (typing narrows it, Tab
  cycles the filters, Enter goes).
- **take2** (another fresh kitty, so the done streak starts at one, in the light theme): three tabs
  finish in a row (`done`, `done-2`, `done-3`; ♪ ♪♪ ♪♪♪), then `test-kitty.sh relaunch` restarts it
  and every tab and split comes back, the resumed Claude tabs with their `✳` marks. The take checks
  that the new kitty has the same cell grid (font and size: `setup` writes them into the test
  kitty.conf, which is what the restarted kitty reads) and that all three marks are back by the time
  the relaunch is done; if not, `capture.sh` says so and exits 1: take it again
  (`capture.sh "$W" take2`). (A mark looked up while the agent was still starting used to stay off
  until the sidebar's next redraw, seconds later; since 2026-11-23 the sidebar looks again within
  half a second, so this guard should no longer fire.)
- **take3** (dark again, nothing working): the ginger idle cat up close winks (`=^ω-=`), blinks and
  glances (`=<.<=`); `npm run deploy --customer=acme-demo` typed in a shell names its tab only
  `npm run deploy`; Ctrl+Shift+F2 opens the settings list, the volume goes to 95 % and back (a chime
  at each level, `done.oga`), and The cat is hidden and shown again while the close-up watches it.
- an end card with the cat and the GitHub link.

The cat's idle moves are dice rolls. capture.sh sets `NL_TEST_CAT_DICE` (see `scripts/test-kitty.sh`):
the test kitty's copy of `tab_bar.py` gets seeded dice, and `cat_move wink` makes the cat play that
move at its next roll (within a second; it waits while another move plays), so a take shows the
same moves every time. The test kitty's cat also ignores the clock: it doesn't nap from 23:00 to
06:00, so a take recorded at night still shows its idle moves.

Captions are written in `capture.sh` (`beat "First line|second line" "Ctrl+Alt+U"`), next to the
actions they describe, and so are the close-up's boxes (`focus X Y WIDTH HEIGHT`, worked out from the
sidebar's cell grid in `sidebar.txt` by `sidebar_box N`, `cat_box N`, `search_box` and `settings_box`,
so they follow the font size; `focus X Y W H 3` lets a box show at 3x). The cut (`EDIT`), layout and colours are at the top of `compose_short.py`.

## The close-up and the restart
- A box shows as big as fits under the window: 2x at most unless the box asks for more (the cat's,
  3x), every pixel repeated at a whole-number zoom (crisp), smoothly scaled otherwise (a wide box); centred, or moved left so it stays clear of YouTube's buttons (x ≤ 952)
  and above its title (y ≤ 1536). With font 14 the sidebar with four tabs is 341x360 px, so 2x fills
  the space (y 800-1520); the search box (706x348) shows at about 1.3x, prompt, filters and folder column whole.
  It eases 0.45 s from one box to the next.
- While kitty restarts the display is black for about 0.7 s. `compose_short.py` finds that (only
  around the take's `relaunch` events), holds the last frame before it, dimming to `HOLD_DIM`, keeps
  holding `HOLD_SETTLE` after (the new window takes a few frames to draw all of itself), then fades
  into the new window over `HOLD_FADE`. Nothing is cut, so the sounds and music stay in time.
- In take2 the pointer sits on the focused pane: kitty's `focus_follows_mouse` would otherwise hand
  the focus to the pane under it as the restarted window opens, and the tab's folder would flicker.

## How it lines up
- ffmpeg's x11grab stamps frames with the wall clock; `capture.sh` keeps the first frame's time from
  ffmpeg's `start:` line, and logs every action with `date +%s.%N`. The test kitty's `paplay` stub logs
  each sound it would have played (time of day, volume, file). Both are turned into seconds since the
  first frame in `NAME.meta.json`. A state change shows on screen within about two frames of its log
  line, and its sound is logged about 0.1 s later.
- Audio: each sound scaled by the `--volume` NineLives passed to `paplay` (taken as a linear factor
  out of 65536; the same for every sound but take3's 95 % chime), then one static gain for the whole mix
  (sounds and music) to -14 LUFS. A limiter is added only if that would push the true peak over -1.5 dBTP (the chimes'
  levels against each other stay as they are). The finished MP4 is measured again and printed.
- Music (`music.py`): original, synthesized in Python with `scripts/make-sounds.py`'s own timbres
  (marimba, glockenspiel, warm, wood) and felt-mallet attack; no samples. C major pentatonic, the
  notes the chimes use, with chords C, Am, Fmaj9 and G6sus so only the bass plays F or B; the tune
  stays at D5 and below, under the chimes. About 104 BPM, nudged so a whole number of bars ends
  where the end card starts: a two-bar intro swell, C Am F G three times (marimba eighths, a soft
  bass, tiny wooden ticks, a glockenspiel note per bar from the second time), a three-bar lead-in,
  and a rolled C major chord that rings out on the end card. Deterministic.
  `python3 tools/short/music.py OUT.wav DURATION END_CARD_AT` writes it alone.
- The bed sits 6 dB under the sounds (`MUSIC_UNDER`) and ducks 8 dB more around each one (`DUCK`,
  a sidechain-style envelope from the logged times), so every chime stands out; the end of a render
  prints, per sound, how far it rises over the bed just before it. `--no-music` leaves the bed out.
- Quests are switched off in the test kitty (`quests-off`), so no badge pops up mid-story.

## Rules (from AGENTS.md)
Only the hidden test kitty is used: every `kitty @` goes `--to unix:@ninelives-test-kitty`, the restart
goes through `test-kitty.sh relaunch`, keys and the pointer only go to display `:97`, and sounds are
mixed into the file, never played. Only one user of the test kitty at a time (`check.sh` uses it too).
Before publishing, look at full-size frames and grep `NAME.text.txt` for user names, host names and
paths.
