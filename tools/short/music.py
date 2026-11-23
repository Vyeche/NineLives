#!/usr/bin/env python3
"""music.py — the Short's music bed, synthesized from scratch with the same soft mallet timbres as
NineLives' own sounds (scripts/make-sounds.py: MARIMBA, GLOCK, WARM, WOOD and its felt-mallet
attack). No samples, no third-party audio. Deterministic: the same arguments give the same samples.

    python3 tools/short/music.py OUT.wav DURATION END_CARD_AT     write it alone (to look at, not to play here)

compose_short.py calls render() and ducks it under the sounds.

Key: C major pentatonic (C D E G A), the notes the chimes use (done G5→C6, done-2 A5→D6, done-3
C6→E6, needs-you rising to B5). Chords: C, Am, Fmaj9 (A C E G over F) and G6sus (G D G A over G),
so nothing but the bass ever plays F or B. The tune stays at D5 and below, under the chimes.
Tempo: about 104 BPM, nudged so that a whole number of 4/4 bars ends exactly where the end card
starts. Structure:
    bars 1-2     intro: a warm pad swells in (C, Am); the marimba arpeggio fades in
    bars 3-14    C Am Fmaj9 G6sus three times: marimba eighths, a soft bass, tiny wooden ticks
                 off the beat; from the second time round a glockenspiel note on each downbeat
    last 3 bars  Fmaj9, Am, G6sus: the lead-in
    end card     a rolled C major chord (bass, marimba, glock, pad) rings out and fades to silence
"""
import importlib.util
import math
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("make_sounds", os.path.join(REPO, "scripts", "make-sounds.py"))
_ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ms)
MARIMBA, GLOCK, WARM, WOOD = _ms.MARIMBA, _ms.GLOCK, _ms.WARM, _ms.WOOD
SR = _ms.SR

# chord: (bass MIDI note, arpeggio notes, pad notes)
# (bass C3 and up and a C4-D5 arpeggio: low enough to stay under the chimes at G5-E6, high
# enough for a phone speaker)
CHORDS = {
    "C": (48, (60, 64, 67, 69, 72), (60, 64, 67)),
    "Am": (45, (57, 60, 64, 69, 72), (57, 60, 64)),
    "F": (41, (57, 60, 64, 67, 69), (57, 60, 64, 67)),     # Fmaj9 without the F: A C E G
    "G": (43, (55, 62, 67, 69, 74), (55, 62, 67)),          # G6sus: G D G A, no B
}
ARP = (0, 2, 1, 3, 2, 4, 3, 1)       # which arpeggio note on each eighth of a bar
ACCENT = (1.0, 0.55, 0.75, 0.55, 0.9, 0.55, 0.75, 0.6)


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def note(buf, start, freq, length, timbre, ring, amp=1.0, attack=0.010, pan=0.0):
    """make-sounds.py's note() (soft raised-cosine attack, each partial fading at its own rate,
    a 20 ms tail), vectorized, with an equal-power pan (-1 left … 1 right)."""
    n0 = int(round(start * SR))
    if n0 >= len(buf):
        return
    n = min(int(length * SR), len(buf) - n0)
    t = np.arange(n) / SR
    env = 0.5 - 0.5 * np.cos(np.pi * np.minimum(1.0, t / attack))
    tail = int(0.02 * SR)
    if n > tail:
        env[-tail:] *= np.linspace(1, 0, tail)
    s = np.zeros(n)
    for ratio, a, r in timbre:
        if freq * ratio > 12000:
            continue
        s += a * np.exp(-t / (ring * r)) * np.sin(2 * np.pi * freq * ratio * t)
    s *= amp * env
    ang = (pan + 1) * math.pi / 4
    buf[n0:n0 + n, 0] += s * math.cos(ang)
    buf[n0:n0 + n, 1] += s * math.sin(ang)


def tempo(end_card_at: float, target=104.0) -> tuple:
    """(bpm, bars): the whole number of bars before the end card whose tempo is nearest target."""
    best = None
    for bars in range(4, 64):
        bpm = 4 * 60 * bars / end_card_at
        if 96 <= bpm <= 112 and (best is None or abs(bpm - target) < abs(best[0] - target)):
            best = (bpm, bars)
    return best or (target, max(4, round(end_card_at * target / 240)))


def progression(bars: int) -> list:
    intro, outro = ["C", "Am"], ["F", "Am", "G"]
    middle = bars - len(intro) - len(outro)
    loop = ["C", "Am", "F", "G"]
    return intro + [loop[i % 4] for i in range(max(0, middle))] + outro


def render(duration: float, end_card_at: float) -> np.ndarray:
    """The bed as float stereo at SR (peak about 0.5): `duration` seconds, resolving on C at
    `end_card_at`."""
    bpm, bars = tempo(end_card_at)
    beat = 60.0 / bpm
    bar = 4 * beat
    buf = np.zeros((int(math.ceil(duration * SR)) + SR, 2))
    chords = progression(bars)
    for b, name in enumerate(chords):
        t0 = b * bar
        bass, arp, pad = CHORDS[name]
        intro = b < 2
        # pad: swells in during the intro, then sits quietly underneath
        for m in pad:
            note(buf, t0, hz(m), bar + 0.4, WARM, 2.2, 0.10 if intro else 0.055,
                 attack=bar * 0.8 if b == 0 else 0.25, pan=0.0)
        # marimba arpeggio in eighths (fading in over the second intro bar)
        if b >= 1:
            for i, k in enumerate(ARP):
                fade = (i + 1) / 8 if b == 1 else 1.0
                note(buf, t0 + i * beat / 2, hz(arp[k]), 0.5, MARIMBA, 0.22, 0.22 * ACCENT[i] * fade,
                     pan=-0.35 if i % 2 == 0 else 0.35)
        # bass: beat 1, the "and" of 2, beat 3
        if not intro:
            for at, a in ((0.0, 0.55), (1.5, 0.30), (2.0, 0.42)):
                note(buf, t0 + at * beat, hz(bass), beat * 1.4, WARM, 0.45, a, attack=0.012)
            # tiny wooden ticks off the beat
            for i in range(4):
                note(buf, t0 + (i + 0.5) * beat, 1400.0, 0.06, WOOD, 0.012, 0.06, attack=0.002, pan=0.5)
        # from the second time round: one glockenspiel note on the downbeat
        if b >= 6 and b < bars:
            note(buf, t0, hz(arp[3]), 0.9, GLOCK, 0.35, 0.07, pan=-0.2)
    # the end: a rolled C major chord that rings out, then a fade to silence
    t0 = bars * bar
    note(buf, t0, hz(48), 3.4, WARM, 1.2, 0.55)
    for i, m in enumerate((60, 64, 67, 72, 76)):
        note(buf, t0 + i * 0.035, hz(m), 3.4, MARIMBA, 0.9, 0.2, pan=-0.3 + 0.15 * i)
    note(buf, t0 + 0.18, hz(72), 3.2, GLOCK, 0.9, 0.08)
    for m in (60, 64, 67):
        note(buf, t0, hz(m), 3.6, WARM, 2.5, 0.07, attack=0.05)
    buf = buf[: int(round(duration * SR))]
    end = len(buf)
    fade = int(0.6 * SR)
    buf[end - fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    peak = np.abs(buf).max() or 1.0
    return buf * (0.5 / peak)


def describe(duration: float, end_card_at: float) -> str:
    bpm, bars = tempo(end_card_at)
    return f"{bpm:.1f} BPM, C major pentatonic, {bars} bars + the end chord: " + " ".join(progression(bars)) + " | C"


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    import subprocess
    out, duration, end_card_at = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    x = render(duration, end_card_at).astype(np.float32)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-",
                    "-c:a", "pcm_s16le", out], input=x.tobytes(), check=True)
    print(f"wrote {out}: {describe(duration, end_card_at)}")


if __name__ == "__main__":
    main()
