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


if __name__ == "__main__":
    unittest.main()
