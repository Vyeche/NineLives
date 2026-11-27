#!/usr/bin/env python3
"""make-sounds.py — build NineLives' sounds (config/sounds/*.oga) from scratch. Plain Python
synthesis, no samples or downloads, so a sound can be tuned here and rebuilt. Needs ffmpeg for .oga.

    python3 scripts/make-sounds.py              write config/sounds/*.oga
    python3 scripts/make-sounds.py --wav DIR    write .wav files to DIR instead (no ffmpeg needed)

Every sound has its own pitch shape, so you can tell them apart without looking:
    done       two soft marimba notes going up           a tab finished
    done-2/-3  the same, a step and two steps higher      more tabs finishing one after another
(all quiet on purpose: about 7 dB under the desktop's own chime; needs-you is a little louder)
    needs-you  a little rising "mrrp?" that ends high     a tab is waiting for you (the loudest)
    error      two low notes going down                   something failed
    badge      a quick glockenspiel run up                you earned a badge
    rank       a short run up that ends on a chord        you reached a new rank
    drop       one tiny wooden tick                       a dragged tab landed
The cat's own voice (it says something: kitty-cat sounds off silences just these):
    meow       a soft little "mi-aow", up then down        the cat speaks up (a tab needs you, news)
    mrrp       a short rolling trill going up             a friendly hello, a tip
    purr       a low, very quiet purr                     petted (a click on the cat)
"""
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave

SR = 48000

# Timbres: (frequency ratio, loudness, how long it rings compared to the note)
# Kept soft on purpose: weak, quickly fading overtones (a felt mallet, not a hard one).
MARIMBA = ((1.0, 1.0, 1.0), (3.93, 0.10, 0.18))
GLOCK = ((1.0, 1.0, 1.0), (2.76, 0.16, 0.35), (5.40, 0.04, 0.2))
WARM = ((1.0, 1.0, 1.0), (2.0, 0.12, 0.7), (3.0, 0.03, 0.4))
WOOD = ((1.0, 1.0, 1.0), (2.57, 0.30, 0.5))

C4, E4 = 261.63, 329.63
C5, E5, G5, A5, B5 = 523.25, 659.25, 783.99, 880.00, 987.77
C6, D6, E6, G6, C7 = 1046.50, 1174.66, 1318.51, 1567.98, 2093.00


def note(buf, start, freq, length, timbre, ring, amp=1.0, slide_to=None, slide=0.0, attack=0.010):
    """Add one note to buf. ring: seconds for the note to fall to ~37%. slide_to: glide the pitch
    to that frequency over `slide` seconds (eased), for the question sound."""
    n0, n = int(start * SR), int(length * SR)
    if len(buf) < n0 + n:
        buf.extend([0.0] * (n0 + n - len(buf)))
    phase = [0.0] * len(timbre)
    tail = int(0.02 * SR)                      # last 20 ms fade to zero: no click at the end
    for i in range(n):
        t = i / SR
        f = freq
        if slide_to and slide:
            k = min(1.0, t / slide)
            f = freq + (slide_to - freq) * (k * k * (3 - 2 * k))
        env = 0.5 - 0.5 * math.cos(math.pi * min(1.0, t / attack))       # soft mallet attack
        if i > n - tail:
            env *= (n - i) / tail
        s = 0.0
        for j, (ratio, a, r) in enumerate(timbre):
            if f * ratio > 12000:              # nothing piercing up top
                continue
            phase[j] += 2 * math.pi * f * ratio / SR
            s += a * math.exp(-t / (ring * r)) * math.sin(phase[j])
        buf[n0 + i] += amp * env * s


def done(low=G5, high=C6):
    b = []
    note(b, 0.00, low, 0.55, MARIMBA, 0.20, 0.80)
    note(b, 0.11, high, 0.75, MARIMBA, 0.28, 1.00)
    return b


def done_2():          # a second tab finished soon after the first: one step up the scale
    return done(A5, D6)


def done_3():          # a third (and every one after it): up again, ending on the high E
    return done(C6, E6)


def needs_you():
    b = []
    note(b, 0.00, E5 * 0.94, 0.20, WARM, 0.10, 0.75, slide_to=E5, slide=0.03)
    note(b, 0.13, A5, 0.65, WARM, 0.30, 1.00, slide_to=B5, slide=0.20)
    return b


def error():
    b = []
    note(b, 0.00, E4, 0.40, MARIMBA, 0.16, 0.90)
    note(b, 0.17, C4, 0.70, MARIMBA, 0.28, 1.00)
    return b


def badge():
    b = []
    for i, f in enumerate((C6, E6, G6)):
        note(b, i * 0.07, f, 0.6, GLOCK, 0.30, 0.75)
    note(b, 0.21, C7, 1.0, GLOCK, 0.50, 0.60)
    return b


def rank():
    b = []
    for i, f in enumerate((C5, E5, G5)):
        note(b, i * 0.10, f, 0.4, MARIMBA, 0.18, 0.70)
    for f, a in ((C5, 0.40), (E5, 0.34), (G5, 0.34), (C6, 0.45)):    # the chord
        note(b, 0.30, f, 1.3, MARIMBA, 0.45, a)
        note(b, 0.30, f * 2, 1.3, GLOCK, 0.35, a * 0.25)
    return b


def drop():
    b = []
    note(b, 0.0, 700.0, 0.12, WOOD, 0.030, 1.0, attack=0.002)
    return b


def voice(buf, start, length, pitch, vowel, amp=1.0, trill=0.0, rate=26.0):
    """A small cat voice: a buzz of harmonics shaped by two moving formants (the "i" to "ao" of a
    meow). pitch(f) and vowel(f) give the pitch (Hz) and the formants (F1, F2) at fraction f of the
    sound; trill rolls it (amplitude wobble at `rate` Hz, for mrrp and purr)."""
    n0, n = int(start * SR), int(length * SR)
    if len(buf) < n0 + n:
        buf.extend([0.0] * (n0 + n - len(buf)))
    phase = 0.0
    for i in range(n):
        f = i / n
        t = i / SR
        hz = pitch(f)
        phase += 2 * math.pi * hz / SR
        f1, f2 = vowel(f)
        s = 0.0
        for k in range(1, 12):
            h = k * hz
            if h > 9000:
                break
            w = math.exp(-((h - f1) / 320) ** 2) + 0.55 * math.exp(-((h - f2) / 480) ** 2) + 0.08 / k
            s += w * math.sin(k * phase)
        env = min(1.0, t / 0.035) * min(1.0, (length - t) / 0.09)
        if trill:
            env *= 1 - trill * 0.5 * (1 + math.cos(2 * math.pi * rate * t))
        buf[n0 + i] += amp * env * s


def meow():
    b = []
    voice(b, 0.0, 0.46, lambda f: 640 + 330 * math.sin(math.pi * min(1.0, f * 1.25)) - 120 * f,
          lambda f: (700 + 500 * min(1.0, f * 2), 2300 - 1100 * f))
    return b


def mrrp():
    b = []
    voice(b, 0.0, 0.30, lambda f: 430 + 260 * f * f, lambda f: (600 + 200 * f, 1500), trill=0.85, rate=28.0)
    return b


def purr():
    b = []
    voice(b, 0.0, 0.75, lambda f: 120 + 8 * math.sin(f * 9), lambda f: (360, 900), trill=0.9, rate=24.0)
    return b


SOUNDS = {"done": done, "done-2": done_2, "done-3": done_3, "needs-you": needs_you, "error": error, "badge": badge, "rank": rank,
          "drop": drop, "meow": meow, "mrrp": mrrp, "purr": purr}
# Peak level of each file in dBFS, set by measuring loudness (ffmpeg ebur128). Targets: subtle,
# about 7 dB under the desktop's "complete" chime (-17.7 LUFS): done/error/badge ~-25, rank ~-24,
# needs-you ~-22 (the one you must not miss stays a little louder), drop ~-36 (barely there); the
# cat's voice under the chimes: meow ~-27, mrrp ~-28, purr ~-32.
PEAK_DB = {"done": -12.0, "done-2": -12.3, "done-3": -12.6, "needs-you": -10.5, "error": -12.2, "badge": -12.3, "rank": -10.0, "drop": -16.0,
           "meow": -18.4, "mrrp": -12.4, "purr": -16.0}


def write_wav(path, samples, peak_db):
    peak = max(abs(s) for s in samples) or 1.0
    gain = 10 ** (peak_db / 20) / peak
    samples = samples + [0.0] * int(0.05 * SR)          # a little silence after
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(round(s * gain * 32767))) for s in samples))


def main():
    args = sys.argv[1:]
    if args[:1] == ["--wav"] and len(args) == 2:
        out, wav_only = args[1], True
    elif not args:
        out, wav_only = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "sounds"), False
    else:
        sys.exit(__doc__)
    os.makedirs(out, exist_ok=True)
    if not wav_only and not shutil.which("ffmpeg"):
        sys.exit("needs ffmpeg to write .oga (or use --wav DIR)")
    with tempfile.TemporaryDirectory() as tmp:
        for name, make in SOUNDS.items():
            wav = os.path.join(out if wav_only else tmp, name + ".wav")
            write_wav(wav, make(), PEAK_DB[name])
            result = wav
            if not wav_only:
                result = os.path.join(out, name + ".oga")
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav, "-map_metadata", "-1",
                                "-fflags", "+bitexact", "-c:a", "libvorbis", "-q:a", "5", result], check=True)
            print("wrote", os.path.normpath(result))


if __name__ == "__main__":
    main()
