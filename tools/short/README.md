# The NineLives YouTube Short

A vertical (1080x1920) Short of NineLives: captions on top, the kitty window in the middle at 1:1,
and below it a close-up of the sidebar with its pixels doubled, following what happens (the cat sits
at the end of **+ New tab**). Recorded live from the real program in the hidden test kitty, with the
real shortcuts pressed and NineLives' own sounds mixed in where they played, over an original music
bed made with the same synth as the sounds.

Two steps, both re-runnable:

| Step | What | Writes |
| --- | --- | --- |
| `capture.sh WORK_DIR` | starts the hidden test kitty (`scripts/test-kitty.sh`: display `:97`, its own socket, stubbed sounds), builds each take's made-up tabs with `scripts/record.sh`'s helpers, presses the shortcuts with `scripts/xkey.py`, and records the display losslessly | per take: `NAME.mkv`, `NAME.meta.json` (captions, keys, state changes, close-up targets and the stub-logged sounds, all in seconds since the first frame), `NAME.stub.log`, `NAME.text.txt` (every window's text, for the privacy check) |
| `compose_short.py WORK_DIR OUT.mp4 [--thumb PNG] [--no-music]` | cuts the takes together, draws captions, keycaps, the close-up and an end card, mixes the sounds over the music bed (`music.py`) and encodes | the MP4 (H.264 + AAC, 30 fps), a thumbnail, and in `WORK_DIR` the mix and its stems (`stem-sounds.wav`, `stem-music.wav`) |

```bash
W="$HOME/Videos/ninelives-short/work"              # anywhere outside the repo
bash tools/short/capture.sh "$W"                   # about a minute; take1 and take2 (or name one)
python3 tools/short/compose_short.py "$W" --preview 5 14 30      # a few frames as PNGs in $W
python3 tools/short/compose_short.py "$W" "$W/../ninelives_short.mp4" \
    --thumb "$W/../ninelives_short_thumb.png"
```

Needs Xvfb, kitty, ffmpeg (libx264), numpy and pycairo (`python3-cairo`). Fonts: DejaVu Sans and
DejaVu Sans Mono.

## The story
- **take1** (a fresh test kitty): four sessions at work (Claude ✳, omp π). One finishes (sparkle, ✓,
  `=^ω^= ♪`, `done.oga`), one needs you (amber pulse, `=O.O= !`, `⚠1`, `needs-you.oga`), Ctrl+Alt+U
  goes there, Ctrl+Shift+Space finds a tab (typing narrows it, Tab cycles the filters, Enter goes).
- **take2** (another fresh kitty, so the done streak starts at one): three tabs finish in a row
  (`done`, `done-2`, `done-3`; ♪ ♪♪ ♪♪♪), then `test-kitty.sh relaunch` restarts it and every tab and
  split comes back.
- an end card with the cat and the GitHub link.

Captions are written in `capture.sh` (`beat "First line|second line" "Ctrl+Alt+U"`), next to the
actions they describe; the cut (`EDIT`), layout and colours are at the top of `compose_short.py`.

## How it lines up
- ffmpeg's x11grab stamps frames with the wall clock; `capture.sh` keeps the first frame's time from
  ffmpeg's `start:` line, and logs every action with `date +%s.%N`. The test kitty's `paplay` stub logs
  each sound it would have played (time of day, volume, file). Both are turned into seconds since the
  first frame in `NAME.meta.json`. A state change shows on screen within about two frames of its log
  line, and its sound is logged about 0.1 s later.
- Audio: each sound scaled by the `--volume` NineLives passed to `paplay` (taken as a linear factor
  out of 65536; every sound in the story uses the same value), then one static gain for the whole mix
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
