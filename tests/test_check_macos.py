#!/usr/bin/env python3
"""Static checks of scripts/check-macos.sh, which only runs on a Mac: they run everywhere, so a
change that would only break on the macOS lane (or on a Mac user's machine) fails here first.
    python3 tests/test_check_macos.py"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "..", "scripts", "check-macos.sh"), encoding="utf-8") as f:
    SRC = f.read()
CODE = [l for l in SRC.splitlines() if not l.lstrip().startswith("#")]


class KittyEnvironment(unittest.TestCase):
    """The real kitty gets its folders through KENV. As a plain string, a path with a space split
    into two arguments and env ran part of the path instead of kitty."""

    def test_kenv_is_an_array(self):
        self.assertTrue(any(re.match(r"\s*KENV=\(", l) for l in CODE), "KENV=( … ) not found")

    def test_every_env_call_expands_it_quoted(self):
        calls = [l for l in CODE if re.search(r"\benv\b", l) and "KENV" in l]
        self.assertEqual(len(calls), 2, calls)           # the kitty launch and the relaunch
        for l in calls:
            self.assertIn('env "${KENV[@]}"', l, l)
        unquoted = [l for l in CODE if re.search(r'(?<!")\$\{?KENV(?!\[@\]\}")', l)]
        self.assertEqual(unquoted, [], "KENV used without \"${KENV[@]}\"")

    def test_the_real_kittys_folder_has_a_space(self):
        # so every macOS run passes those paths through env with a space in them
        self.assertTrue(any(re.match(r'\s*K="\$TMP/[^"]* [^"]*"', l) for l in CODE),
                        "the real kitty's folder (K) should have a space in its name")


class SoundCount(unittest.TestCase):
    """The .wav count follows the sounds NineLives ships (config/sounds/*.oga, one .wav each from
    make-sounds.py): a new sound must not need a number changed here (the cat's three did)."""

    def test_no_number_written_in(self):
        line = next(l for l in CODE if "$w" in l and "ok " in l)
        self.assertNotRegex(line, r'\$w"?\s*=\s*"?\d', line)
        self.assertTrue(any("config/sounds" in l and ".oga" in l for l in CODE))

    def test_every_sound_is_made(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("nl_make_sounds", os.path.join(HERE, "..", "scripts", "make-sounds.py"))
        ms = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ms)
        shipped = sorted(f[:-4] for f in os.listdir(os.path.join(HERE, "..", "config", "sounds")) if f.endswith(".oga"))
        self.assertEqual(sorted(ms.SOUNDS), shipped)


class TestKittyShots(unittest.TestCase):
    """test-kitty.sh's screenshots are the whole hidden screen: ffmpeg 4's x11grab (the Gauntlet's
    static build) grabs only the top-left 640x480 unless told the size, and the cat on the
    sidebar's floor sat below that (v1.4.0's kitty lane)."""

    def test_shot_says_the_size(self):
        with open(os.path.join(HERE, "..", "scripts", "test-kitty.sh"), encoding="utf-8") as f:
            src = f.read()
        grabs = [l for l in src.splitlines() if "-f x11grab" in l and not l.lstrip().startswith("#")]
        self.assertTrue(grabs)
        for l in grabs:
            self.assertIn("-video_size", l, l)


if __name__ == "__main__":
    unittest.main()
