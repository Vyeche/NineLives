#!/usr/bin/env python3
"""Unit tests for config/tab-finder.py (search tabs, jump to the tab waiting for you). Fake
`kitty @ ls` data, no kitty needed:  python3 tests/test_tab_finder.py"""
import importlib.util
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tab_finder", os.path.join(HERE, "..", "config", "tab-finder.py"))
assert spec is not None and spec.loader is not None
tf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tf)


def win(title="t", cwd="/w/proj", state=None, procs=(("bash",),), active=True, me=False):
    return {"title": title, "cwd": cwd, "is_active": active, "is_self": me,
            "program_status": [{"state": state}] if state else [],
            "foreground_processes": [{"cmdline": list(p)} for p in procs]}


def tab(*windows, active=False, tid=[0]):
    tid[0] += 1
    return {"id": tid[0], "title": windows[0]["title"], "is_active": active, "windows": list(windows)}


def ls(*tabs):
    return [{"is_focused": True, "tabs": list(tabs)}]


class Rows(unittest.TestCase):
    def test_states_like_the_sidebar(self):
        r = tf.rows(ls(tab(win("✳ Ask", state="blocked")), tab(win("✳ Oops", state="error")),
                       tab(win("⠋ omp: x")), tab(win("make", procs=[("bash",), ("make",)])),
                       tab(win("✳ Done", state="done")), tab(win("~/w/proj"))))
        self.assertEqual([x["state"] for x in r], ["blocked", "error", "working", "working", "done", ""])
        self.assertEqual([x["name"] for x in r], ["Ask", "Oops", "omp: x", "make", "Done", "proj"])

    def test_finds_an_already_open_search_box(self):
        box = win("x", me=False)
        box["id"], box["cmdline"] = 77, ["sh", "-c", 'exec python3 "/c/kitty/tab-finder.py" search']
        me = win("x", me=True)
        me["id"], me["cmdline"] = 78, box["cmdline"]
        shell = win("bash")
        shell["id"] = 5
        self.assertEqual(tf.other_search_boxes(ls(tab(shell, box, me, active=True))), [77])
        self.assertEqual(tf.other_search_boxes(ls(tab(shell, me, active=True))), [])
        running = win("x", procs=[("python3", "/c/kitty/tab-finder.py", "search")])   # its process
        running["id"] = 79
        self.assertEqual(tf.other_search_boxes(ls(tab(running, me, active=True))), [79])

    def test_windows_that_only_mention_the_search_box_are_left_alone(self):
        me = win("x", me=True)
        me["id"] = 1
        others = []
        for i, argv in enumerate([("claude", "fix the search in tab-finder.py"),
                                  ("nvim", "/home/me/research/tab-finder.py"),
                                  ("grep", "-n", "search", "config/tab-finder.py"),
                                  ("python3", "tab-finder.py", "waiting"),
                                  ("bash", "-c", "grep search tab-finder.py | less")], 2):
            w = win("x", procs=[("bash",), argv])
            w["id"] = i
            others.append(w)
        self.assertEqual(tf.other_search_boxes(ls(tab(*others, me, active=True))), [])

    def test_a_box_left_open_in_another_tab_is_not_here(self):
        box = win("x", procs=[("python3", "/c/kitty/tab-finder.py", "search")])
        box["id"] = 7
        me = win("x", me=True)
        me["id"] = 8
        data = ls(tab(box), tab(me, active=True))
        self.assertEqual(tf.other_search_boxes(data), [7])               # closed (it's stale)
        self.assertEqual(tf.other_search_boxes(data, here_only=True), [])  # but this box still opens

    def test_the_search_box_itself_is_left_out(self):
        r = tf.rows(ls(tab(win("✳ Real work", active=False), win("search tabs", me=True), active=True)))
        self.assertEqual(r[0]["name"], "Real work")
        self.assertTrue(r[0]["active"])


class Waiting(unittest.TestCase):
    def tabs(self, states, active):
        return [{"n": i + 1, "id": i + 1, "name": "", "folder": "", "state": s, "active": i == active}
                for i, s in enumerate(states)]

    def test_next_waiting_after_the_active_tab_wrapping(self):
        t = self.tabs(["blocked", "", "", "blocked", ""], active=1)
        self.assertEqual(tf.next_waiting(t)["n"], 4)
        t = self.tabs(["blocked", "", "", "blocked", ""], active=3)
        self.assertEqual(tf.next_waiting(t)["n"], 1)

    def test_errors_when_nothing_is_waiting_and_none_otherwise(self):
        self.assertEqual(tf.next_waiting(self.tabs(["", "error", "done"], active=0))["n"], 2)
        self.assertIsNone(tf.next_waiting(self.tabs(["", "done", "working"], active=0)))


class Search(unittest.TestCase):
    T = [{"n": 1, "name": "Fix the login bug", "folder": "code/webapp"},
         {"n": 2, "name": "notes", "folder": "code/login-service"},
         {"n": 12, "name": "Deploy", "folder": "code/api"}]

    def test_every_word_must_match_and_names_come_first(self):
        self.assertEqual([t["n"] for t in tf.matches(self.T, "login")], [1, 2])
        self.assertEqual([t["n"] for t in tf.matches(self.T, "LOGIN webapp")], [1])
        self.assertEqual([t["n"] for t in tf.matches(self.T, "12")], [12])
        self.assertEqual(len(tf.matches(self.T, "")), 3)

    def test_modes_show_only_their_states(self):
        T = [dict(t, state=s) for t, s in zip(self.T, ("blocked", "working", "done"))]
        self.assertEqual([t["n"] for t in tf.matches(T, "", 1)], [1])          # Waiting
        self.assertEqual([t["n"] for t in tf.matches(T, "", 2)], [2])          # Working
        self.assertEqual([t["n"] for t in tf.matches(T, "login", 3)], [])      # Done + no match
        bar = re.sub("\x1b\\[[0-9;]*m", "", tf.mode_bar(T, 1, 80))
        self.assertIn("All 3", bar)
        self.assertIn("Waiting 1", bar)
        self.assertNotIn("\x1b[7m", tf.mode_bar(T, 1, 80))                  # no heavy reversed bar

    def test_letters_in_order_when_no_word_matches(self):
        self.assertEqual([t["n"] for t in tf.matches(self.T, "ftlb")], [1])        # Fix the login bug
        self.assertEqual([t["n"] for t in tf.matches(self.T, "login")], [1, 2])    # words still win

    def test_branch_is_searchable(self):
        T = [dict(t, branch=b) for t, b in zip(self.T, ("", "fix-parser", ""))]
        self.assertEqual([t["n"] for t in tf.matches(T, "parser")], [2])

    def test_agent_marks(self):
        self.assertEqual(tf.agent_mark(win(procs=[("claude", "--resume", "x")])), "✳")
        self.assertEqual(tf.agent_mark(win(procs=[("node", "--require", "h.js",
                                                   "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js")])), "✳")
        self.assertEqual(tf.agent_mark(win(procs=[("omp",)])), "π")
        self.assertEqual(tf.agent_mark(win(procs=[("bash",)])), "")

    def test_narrow_pane_never_wraps(self):
        T = [dict(t, state="", active=False, agent="✳", branch="a-very-long-feature-branch-name")
             for t in self.T]
        for query in ("a long query that keeps going on", ""):
            for cols in range(23, 101):
                lines = tf.draw(T, query, 0, cols, 15).split("\r\n")
                if not query:
                    self.assertTrue(any("⌥" in l for l in lines) or cols < 40, cols)   # rows were drawn
                for line in lines:
                    self.assertLessEqual(tf.cells(re.sub("\x1b\\[[0-9;]*m", "", line)), cols, (cols, line))

    def test_keys_split_a_burst(self):
        self.assertEqual(list(tf.keys("\x1b[B\x1b[Bab\x1b[Z\x1b")), ["\x1b[B", "\x1b[B", "a", "b", "\x1b[Z", "\x1b"])

    def test_rows_fit_the_width(self):
        tabs = [{"n": 1, "name": "日本語 " * 20, "folder": "a-very-long-client-name/inner", "state": "done",
                 "active": True}]
        lines = tf.draw(tabs, "", 0, 60, 20).split("\r\n")[5:]
        import re
        self.assertTrue(all(tf.cells(re.sub("\x1b\\[[0-9;]*m", "", l)) <= 60 for l in lines), lines)


if __name__ == "__main__":
    unittest.main()
