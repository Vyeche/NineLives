#!/usr/bin/env python3
"""Unit tests for tools/desktop-mcp/server.py (the agents' desktop-test MCP server): its files go
only to a folder private to this user, and a panel it shows keeps its fixed limits (never the
keyboard, its own process, its own timeout) whatever options or command it is given. Nothing is
started: Popen is replaced.
    python3 -m unittest discover -s tests"""
import importlib.util
import os
import stat
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))


def load(env):
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location("nl_desktop_mcp", os.path.join(HERE, "..", "tools", "desktop-mcp", "server.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


class PrivateFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_made_private(self):
        d = os.path.join(self.tmp.name, "out")
        srv = load({"NL_DESKTOP_DIR": d})
        self.assertEqual(srv.out_dir(), d)
        self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700)

    def test_a_folder_others_can_open_is_refused(self):
        d = os.path.join(self.tmp.name, "made-before")
        os.mkdir(d)
        os.chmod(d, 0o777)                          # (as someone else could leave it in /tmp)
        srv = load({"NL_DESKTOP_DIR": d})
        with self.assertRaises(PermissionError):
            srv.out_dir()
        self.assertIn("refused", srv.screenshot({})[0]["text"])

    def test_a_link_is_refused(self):
        real = os.path.join(self.tmp.name, "real")
        os.mkdir(real, 0o700)
        link = os.path.join(self.tmp.name, "link")
        os.symlink(real, link)
        srv = load({"NL_DESKTOP_DIR": link})
        with self.assertRaises(PermissionError):
            srv.out_dir()

    def test_no_runtime_dir_a_fresh_one(self):
        srv = load({"NL_DESKTOP_DIR": "", "XDG_RUNTIME_DIR": ""})
        with mock.patch.object(tempfile, "tempdir", self.tmp.name):
            d = srv.out_dir()
        self.assertEqual(os.path.dirname(d), self.tmp.name)
        self.assertTrue(os.path.basename(d).startswith("ninelives-desktop-"))
        self.assertNotEqual(d, os.path.join(self.tmp.name, "ninelives-desktop"))   # never a fixed name
        self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700)
        self.assertEqual(srv.out_dir(), d)                                         # the same one after


class PanelLimits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.srv = load({"NL_DESKTOP_DIR": os.path.join(self.tmp.name, "out")})

    def tearDown(self):
        self.tmp.cleanup()

    def show(self, **args):
        with mock.patch.object(self.srv.subprocess, "Popen") as popen, mock.patch.object(self.srv.time, "sleep"):
            popen.return_value.poll.return_value = None
            popen.return_value.pid = 4242
            out = self.srv.panel_show(args)
        return (popen.call_args.args[0] if popen.called else None), out[0]["text"]

    def test_the_command_is_never_read_as_options(self):
        argv, _ = self.show(command=["--focus-policy=exclusive", "sh"])
        i = argv.index("--")
        self.assertEqual(argv[i + 1:], ["--focus-policy=exclusive", "sh"])
        self.assertEqual([a for a in argv[:i] if "focus-policy" in a], ["--focus-policy=not-allowed"])
        argv, _ = self.show(text="hello")
        self.assertEqual(argv[argv.index("--") + 1], "sh")

    def test_options_that_break_the_limits_are_refused(self):
        for bad in ("--focus-policy=exclusive", "--grab-keyboard", "--single-instance", "-1",
                    "--instance-group=probe", "--instance-group", "--detach", "--detached-log=/x", "--"):
            argv, text = self.show(extra=[bad])
            self.assertIsNone(argv, bad)                            # nothing started
            self.assertIn("refused", text)
        argv, _ = self.show(extra=["--hold", "--margin-left=-10", "-o", "font_size=20"])
        self.assertIsNotNone(argv)                                  # the harmless ones pass


if __name__ == "__main__":
    unittest.main()
