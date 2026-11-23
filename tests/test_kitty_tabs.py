#!/usr/bin/env python3
"""Unit tests for scripts/kitty-tabs.py (what kitty-relaunch.sh reopens, and when it waits).
Fake `kitty @ ls` data, no kitty needed:  python3 tests/test_kitty_tabs.py"""
import importlib.util
import os
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("kitty_tabs", os.path.join(HERE, "..", "scripts", "kitty-tabs.py"))
assert spec is not None and spec.loader is not None
kt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kt)


def win(cwd="/w", title="t", procs=(), status=(), active=True):
    return {"cwd": cwd, "title": title, "is_active": active,
            "foreground_processes": [{"cmdline": list(p)} for p in procs],
            "program_status": [{"state": s} for s in status]}


def tab(*windows, title=None, active=False):
    """title: a name you gave the tab (Ctrl+Shift+R), which kitty marks with title_overridden."""
    return {"title": title if title is not None else windows[0]["title"], "is_active": active,
            "title_overridden": title is not None, "windows": list(windows)}


def rows(tabs):
    return [r.split(kt.US) for r in kt.snapshot(tabs)]


class Snapshot(unittest.TestCase):
    def test_plain_shell_comes_back_as_a_shell_in_its_folder(self):
        self.assertEqual(rows([tab(win("/a", procs=[["bash"]]))]), [["/a", "exec bash", "", "0"]])

    def test_claude_with_a_session_id_resumes_it(self):
        cmd = rows([tab(win(procs=[["claude", "--resume", "abc-123"]]))])[0][1]
        self.assertTrue(cmd.startswith("claude --resume abc-123;"), cmd)

    def test_claude_started_through_node_is_still_claude(self):
        cmd = rows([tab(win(procs=[["node", "/usr/lib/node_modules/.bin/claude", "--resume", "s1"]]))])[0][1]
        self.assertTrue(cmd.startswith("claude --resume s1;"), cmd)

    def test_resume_without_an_id_does_not_crash_or_grab_a_flag(self):
        for c in (["claude", "--resume"], ["claude", "--resume", "--verbose"]):
            cmd = rows([tab(win(procs=[c]))])[0][1]
            self.assertTrue(cmd.startswith("claude --continue;"), (c, cmd))

    def test_other_session_id_forms(self):
        for c in (["claude", "--resume=abc"], ["claude", "-r", "abc"], ["claude", "--session-id", "abc"],
                  ["claude", "--session-id=abc", "--verbose"]):
            cmd = rows([tab(win(procs=[c]))])[0][1]
            self.assertTrue(cmd.startswith("claude --resume abc;"), (c, cmd))

    def test_fresh_claude_next_to_a_resumed_one_does_not_steal_its_session(self):
        r = rows([tab(win("/p", procs=[["claude", "--resume", "X"]])), tab(win("/p", procs=[["claude"]]))])
        self.assertTrue(r[0][1].startswith("claude --resume X;"))
        self.assertNotIn("--continue", r[1][1])

    def test_one_fresh_claude_in_a_folder_continues(self):
        cmd = rows([tab(win("/p", procs=[["claude"]]))])[0][1]
        self.assertTrue(cmd.startswith("claude --continue;"), cmd)

    def test_two_fresh_claudes_in_one_folder_come_back_as_shells(self):
        r = rows([tab(win("/p", procs=[["claude"]])), tab(win("/p", procs=[["claude"]])),
                  tab(win("/q", procs=[["claude"]]))])
        self.assertNotIn("claude --continue", r[0][1])
        self.assertIn("claude --resume to pick", r[0][1])
        self.assertTrue(r[2][1].startswith("claude --continue;"))

    def test_omp_continues(self):
        cmd = rows([tab(win(procs=[["omp", "-c", "--model", "x y"]]))])[0][1]
        self.assertEqual(cmd, "omp --model 'x y' --continue; exec bash")

    def test_renamed_tab_keeps_its_name_and_active_tab_is_marked(self):
        r = rows([tab(win(title="bash"), title="My build"), tab(win(title="vim x"), active=True)])
        self.assertEqual([x[2] for x in r], ["My build", ""])
        self.assertEqual([x[3] for x in r], ["0", "1"])

    def test_kitty_without_the_rename_flag_falls_back_to_comparing_titles(self):
        t = tab(win(title="bash"), title="My build")
        del t["title_overridden"]
        self.assertEqual(rows([t])[0][2], "My build")

    def test_node_with_flags_running_claude_is_claude(self):
        cmd = rows([tab(win(procs=[["node", "--no-warnings", "/usr/bin/claude", "--resume", "s9"]]))])[0][1]
        self.assertTrue(cmd.startswith("claude --resume s9;"), cmd)

    def test_a_title_that_merely_differs_is_not_a_name(self):
        t = tab(win(title="⠂ Claude Code"))
        t["title"] = "✳ Claude Code"                 # kitty's tab title lagging the window's
        self.assertEqual(rows([t])[0][2], "")

    def test_uses_the_active_window_of_a_split_tab(self):
        r = rows([tab(win("/left", active=False), win("/right", procs=[["omp"]], active=True))])
        self.assertEqual(r[0][0], "/right")
        self.assertTrue(r[0][1].startswith("omp "))

    def test_separator_in_a_name_cannot_split_the_row(self):
        r = rows([tab(win(title="x"), title="a\x1fb")])
        self.assertEqual(len(r[0]), 4)


class Busy(unittest.TestCase):
    def test_reasons(self):
        out = kt.busy([
            tab(win(procs=[["bash"]])),                                  # idle shell
            tab(win(title="✳ Fix", status=["working"])),                 # Claude working
            tab(win(title="✳ Ask", status=["blocked"])),                 # waiting for you
            tab(win(title="⠋ omp")),                                     # spinner
            tab(win(procs=[["bash"], ["make", "-j8"]])),                 # a build
            tab(win(procs=[["nvim", "x"]])),                             # an editor: fine to restart
            tab(win(title="✳ Done", status=["done"])),                   # finished
        ])
        whys = {int(l.split()[0]): l.split(None, 2)[1] for l in out}
        self.assertEqual(whys, {2: "working", 3: "needs", 4: "spinner", 5: "command"})

    def test_node_with_flags_running_claude_is_not_busy(self):
        self.assertEqual(kt.busy([tab(win(procs=[["node", "--no-warnings", "/usr/bin/claude"]]))]), [])

    def test_node_running_a_script_is_busy_but_node_running_claude_is_not(self):
        out = kt.busy([tab(win(procs=[["bash"], ["node", "migrate.js"]])),
                       tab(win(procs=[["node", "/usr/bin/claude"]]))])
        self.assertEqual(len(out), 1)
        self.assertIn("command", out[0])

    def test_all_idle_prints_nothing(self):
        self.assertEqual(kt.busy([tab(win()), tab(win(procs=[["less"]]))]), [])


class SeveralWindows(unittest.TestCase):
    def test_only_the_focused_windows_active_tab_is_active(self):
        data = [{"is_focused": False, "last_focused": False, "tabs": [tab(win("/a"), active=True)]},
                {"is_focused": True, "tabs": [tab(win("/b")), tab(win("/c"), active=True)]}]
        self.assertEqual([r[3] for r in rows(kt.all_tabs(data))], ["0", "0", "1"])

    def test_no_focused_window_uses_the_last_focused(self):
        data = [{"tabs": [tab(win("/a"), active=True)]},
                {"last_focused": True, "tabs": [tab(win("/b"), active=True)]}]
        self.assertEqual([r[3] for r in rows(kt.all_tabs(data))], ["0", "1"])


def split_tab(*windows, pairs, layout="splits", title=None, active=False, groups=None, extra=None):
    """A tab with kitty's layout_state, as `kitty @ ls` shows it (kitty 0.43+). Windows need ids;
    groups default to one per window (group id = window id, as kitty numbers them)."""
    t = tab(*windows, title=title, active=active)
    groups = groups or [[w["id"]] for w in windows]
    state = {"class": "Splits", "opts": {"split_axis": "horizontal"},
             "all_windows": {"active_group_idx": 0, "active_group_history": [],
                             "window_groups": [{"id": g[0], "window_ids": list(g)} for g in groups]}}
    if pairs is not None:
        state["pairs"] = pairs
    state.update(extra or {})
    t.update(layout=layout, enabled_layouts=["splits", "stack"], layout_state=state)
    return t


def wid(i, cwd, **kw):
    w = win(cwd, **kw)
    w["id"] = i
    return w


def session(tabs, saved=None, missing=()):
    """The session file's lines, with every folder existing except `missing`."""
    return kt.session(tabs, saved, isdir=lambda p: p not in missing, home="/home/me")


def launches(lines):
    """Each launch line as (unserialize id or None, cwd or None, bash -lc command)."""
    import json, shlex
    out = []
    for line in lines:
        if not line.startswith("launch "):
            continue
        args = shlex.split(line)[1:]
        sid = None
        if args[0].startswith("kitty-unserialize-data="):
            sid = json.loads(args.pop(0).split("=", 1)[1])["id"]
        cwd = args.pop(0)[len("--cwd="):] if args[0].startswith("--cwd=") else None
        if args[0].startswith("--var="):
            args.pop(0)
        assert args[:2] == ["bash", "-lc"], line
        out.append((sid, cwd, args[2]))
    return out


# a tab split left | right, and the right half split top / bottom (Ctrl+Alt+→ then Ctrl+Alt+↓)
NESTED = {"bias": 0.6, "one": 1, "two": {"horizontal": False, "one": 2, "two": 3}}


class Splits(unittest.TestCase):
    def test_every_pane_comes_back_in_its_folder_in_the_same_layout(self):
        t = split_tab(wid(1, "/l", active=False), wid(2, "/tr", active=True), wid(3, "/br", active=False),
                      pairs=NESTED, active=True)
        lines = session([t])
        self.assertEqual([l for l in lines if l.startswith(("new_tab", "layout", "enabled"))],
                         ["new_tab", "layout splits", "enabled_layouts splits,stack"])
        import json
        state = json.loads(next(l for l in lines if l.startswith("set_layout_state "))[17:])
        self.assertEqual(state["pairs"], NESTED)                    # tree, axes and sizes as they were
        self.assertEqual([(i, c) for i, c, _ in launches(lines)], [(1, "/l"), (2, "/tr"), (3, "/br")])
        self.assertTrue(all(cmd == "exec bash" for *_, cmd in launches(lines)))
        self.assertEqual(lines[-1], "focus_tab 0")

    def test_the_pane_you_were_in_gets_the_focus(self):
        t = split_tab(wid(1, "/l", active=False), wid(2, "/tr", active=False), wid(3, "/br", active=True),
                      pairs=NESTED)
        lines = session([t])
        self.assertEqual(lines.count("focus"), 1)
        self.assertIn("/br", lines[lines.index("focus") - 1])

    def test_a_claude_pane_among_shells_resumes_its_session(self):
        t = split_tab(wid(1, "/p", procs=[["bash"]]), wid(2, "/p", procs=[["bash"], ["claude", "--resume", "S1"]]),
                      wid(3, "/q", procs=[["bash"], ["vim", "x"]]), pairs=NESTED)
        cmds = [cmd for *_, cmd in launches(session([t]))]
        self.assertEqual(cmds[0], "exec bash")
        self.assertTrue(cmds[1].startswith("claude --resume S1;"), cmds[1])
        self.assertEqual(cmds[2], "exec bash")

    def test_two_fresh_claude_panes_in_one_folder_do_not_both_continue(self):
        t = split_tab(wid(1, "/p", procs=[["claude"]]), wid(2, "/p", procs=[["claude"]]),
                      pairs={"one": 1, "two": 2})
        cmds = [cmd for *_, cmd in launches(session([t]))]
        self.assertFalse(any("--continue" in c for c in cmds), cmds)
        self.assertTrue(all("claude --resume to pick" in c for c in cmds), cmds)

    def test_a_fresh_claude_pane_next_to_a_claude_tab_in_the_same_folder_does_not_continue(self):
        t1 = tab(win("/p", procs=[["claude", "--resume", "X"]]))
        t2 = split_tab(wid(1, "/p", procs=[["claude"]]), wid(2, "/q"), pairs={"one": 1, "two": 2})
        cmds = [cmd for *_, cmd in launches(session([t1, t2]))]
        self.assertTrue(cmds[0].startswith("claude --resume X;"))
        self.assertNotIn("--continue", cmds[1])

    def test_single_pane_tabs_are_unchanged(self):
        r = rows([tab(win("/a", procs=[["omp"]]), active=True)])
        self.assertEqual(r, [["/a", "omp --continue; exec bash", "", "1"]])
        lines = session([tab(win("/a", procs=[["omp"]]), title="Mine", active=True)])
        self.assertEqual(lines, ["new_tab Mine", "launch --cwd=/a bash -lc 'omp --continue; exec bash'",
                                 "focus", "", "focus_tab 0"])

    def test_without_layout_state_a_split_tab_comes_back_as_its_active_pane(self):
        t = tab(wid(1, "/l", active=False), wid(2, "/r", procs=[["omp"]], active=True))   # an older kitty
        lines = session([t])
        self.assertFalse(any(l.startswith("set_layout_state") for l in lines))
        self.assertEqual(launches(lines), [(None, "/r", "omp --continue; exec bash")])

    def test_a_layout_state_that_does_not_match_the_windows_falls_back_to_one_pane(self):
        t = split_tab(wid(1, "/l", active=True), wid(2, "/r", active=False), pairs={"one": 1, "two": 99})
        self.assertEqual(launches(session([t])), [(None, "/l", "exec bash")])
        t = split_tab(wid(1, "/l"), pairs={"one": 1}, groups=[[1], [77]])        # a group with no window
        self.assertEqual(launches(session([t])), [(None, "/l", "exec bash")])

    def test_snapshot_still_gives_each_tabs_active_pane(self):
        t = split_tab(wid(1, "/l", active=False), wid(2, "/r", procs=[["omp"]], active=True),
                      pairs={"one": 1, "two": 2}, title="Work", active=True)
        self.assertEqual(rows([t]), [["/r", "omp --continue; exec bash", "Work", "1"]])

    def test_the_window_under_an_overlay_comes_back_not_the_overlay(self):
        overlay = wid(5, "/r", procs=[["python3", "tab-finder.py"]], active=True)    # the search box
        t = split_tab(wid(1, "/l", active=False), wid(2, "/r", procs=[["claude", "--resume", "Z"]], active=False),
                      overlay, pairs={"one": 1, "two": 2}, groups=[[1], [2, 5]])
        lines = session([t])
        self.assertEqual([(i, c) for i, c, _ in launches(lines)], [(1, "/l"), (2, "/r")])
        self.assertIn("/r", lines[lines.index("focus") - 1])                # its group was the active one
        import json
        state = json.loads(next(l for l in lines if l.startswith("set_layout_state "))[17:])
        self.assertEqual(state["all_windows"]["window_groups"][1]["window_ids"], [2])

    def test_a_zoomed_tab_keeps_its_splits_from_kittys_own_save(self):
        # Ctrl+Alt+Z: `kitty @ ls` shows only the stack layout; kitty's save_as_session keeps the splits
        t = split_tab(wid(1, "/l", active=False), wid(2, "/r", active=True), pairs=None, layout="stack",
                      extra={"class": "Stack", "opts": {}})
        saved_text = ("new_tab\nlayout stack\nset_layout_state " + __import__("json").dumps({
            "class": "Stack", "opts": {}, "last_used_layout": "splits",
            "all_windows": {"active_group_idx": 1, "window_groups": [{"id": 1, "window_ids": [1]}, {"id": 2, "window_ids": [2]}]},
            "other_layouts": {"splits": {"class": "Splits", "pairs": {"bias": 0.3, "one": 1, "two": 2},
                                         "all_windows": {"active_group_idx": 1, "window_groups": [
                                             {"id": 1, "window_ids": [1]}, {"id": 2, "window_ids": [2]}]}}}}) +
            "\nlaunch 'kitty-unserialize-data={\"id\": 1}' bash\n")
        saved = kt.saved_layout_states(saved_text)
        lines = session([t], saved)
        import json
        state = json.loads(next(l for l in lines if l.startswith("set_layout_state "))[17:])
        self.assertEqual(state["other_layouts"]["splits"]["pairs"], {"bias": 0.3, "one": 1, "two": 2})
        self.assertIn("layout stack", lines)
        self.assertEqual(len(launches(lines)), 2)
        # without kitty's save the zoomed tab still has both panes, just no splits to unzoom to
        state = json.loads(next(l for l in session([t]) if l.startswith("set_layout_state "))[17:])
        self.assertNotIn("other_layouts", state)

    def test_a_saved_state_for_other_windows_is_ignored(self):
        t = split_tab(wid(1, "/l"), wid(2, "/r", active=False), pairs={"one": 1, "two": 2})
        saved = {frozenset({7, 8}): {"all_windows": {"window_groups": [{"id": 7, "window_ids": [7]}]}}}
        self.assertEqual(len(launches(session([t], saved))), 2)

    def test_a_missing_folder_becomes_home_and_dollar_signs_stay_literal(self):
        t = split_tab(wid(1, "/gone"), wid(2, "/x/$HOME y", active=False), pairs={"one": 1, "two": 2})
        got = launches(session([t], missing={"/gone"}))
        self.assertEqual(got[0][1], "/home/me")
        self.assertIsNone(got[1][1])                     # kitty would expand $HOME in --cwd=
        self.assertTrue(got[1][2].startswith("cd -- '/x/$HOME y' 2>/dev/null; exec bash"), got[1][2])

    def test_a_fresh_claude_in_a_missing_folder_does_not_continue_homes_session(self):
        t1 = split_tab(wid(1, "/gone", procs=[["claude"]]), wid(2, "/also-gone", procs=[["claude"]], active=False),
                       pairs={"one": 1, "two": 2})
        got = launches(session([t1], missing={"/gone", "/also-gone"}))
        self.assertEqual([c for _, c, _ in got], ["/home/me", "/home/me"])
        self.assertFalse(any("--continue" in cmd for *_, cmd in got), got)     # both would open one session
        self.assertTrue(all("claude --resume" in cmd for *_, cmd in got), got)

    def test_every_line_stays_one_line_for_kitty(self):
        """kitty splits a session file with str.splitlines(): a name, folder or command with a line
        break in it would split its line, and kitty would open only an error window."""
        nasty = "a\nb\rc\x0bd\x0ce\x1cf\x1dg\x1eh\x85i j k"
        t = split_tab(wid(1, "/p/" + nasty, procs=[["omp", "fix\nthis"]]), wid(2, "/q", active=False),
                      pairs={"one": 1, "two": 2}, title="name " + nasty, active=True)
        lines = session([t, tab(win("/r", procs=[["claude", "--resume", "x y"]]))])
        self.assertEqual("\n".join(lines).splitlines(), lines)
        got = launches(lines)
        self.assertEqual(got[0][1], "/home/me")                   # the folder can't be named: home
        self.assertNotIn("omp", got[0][2])
        self.assertTrue(lines[0].startswith("new_tab name a b c"), lines[0])

    def test_dollar_signs_in_a_name_stay_literal(self):
        lines = session([tab(win("/a"), title="cost $5 ${HOME} $$")])
        self.assertEqual(lines[0], "new_tab cost $$5 $${HOME} $$$$")      # kitty reads $$ as $
        self.assertEqual(kt.show([tab(win("/a"), title="cost $5")])[1], '       shell  name "cost $5"')

    def test_names_and_the_active_tab_across_kitty_windows(self):
        data = [{"tabs": [tab(win("/a"), active=True)]},
                {"is_focused": True, "tabs": [tab(win("/b"), title="Docs"),
                                              split_tab(wid(1, "/c"), wid(2, "/d", active=False),
                                                        pairs={"one": 1, "two": 2}, active=True)]}]
        lines = session(kt.all_tabs(data))
        self.assertEqual([l for l in lines if l.startswith("new_tab")], ["new_tab", "new_tab Docs", "new_tab"])
        self.assertEqual(lines[-1], "focus_tab 2")

    def test_the_pane_to_focus_is_marked_for_refocus_in_split_tabs_only(self):
        t = split_tab(wid(1, "/l", active=False), wid(2, "/r", active=True), pairs={"one": 1, "two": 2})
        lines = session([t, tab(win("/s"))])
        marked = [l for l in lines if "--var=ninelives_focus=1" in l]
        self.assertEqual(len(marked), 1)
        self.assertIn("--cwd=/r", marked[0])
        self.assertEqual(launches(lines)[1][2], "exec bash")          # the var doesn't reach the command

    def test_refocus_fixes_panes_the_mouse_took_and_ends_on_the_active_tab(self):
        def w(i, active, mark=False):
            x = wid(i, "/x", active=active)
            x["user_vars"] = {"ninelives_focus": "1"} if mark else {}
            return x
        ok_tab = tab(w(1, True, mark=True), w(2, False))
        moved = tab(w(3, True), w(4, False, mark=True))                 # the mouse took pane 3
        current = tab(w(5, True), w(6, False), active=True)
        self.assertEqual(kt.refocus([ok_tab, moved, current]), ["4", "5"])
        moved_active = tab(w(3, True), w(4, False, mark=True), active=True)
        self.assertEqual(kt.refocus([ok_tab, moved_active]), ["4"])
        self.assertEqual(kt.refocus([ok_tab, tab(w(7, True), active=True)]), [])   # all right: nothing

    def test_show_lists_every_pane(self):
        t = split_tab(wid(1, "/l", active=False), wid(2, "/r", procs=[["omp"]], active=True),
                      pairs={"one": 1, "two": 2}, active=True)
        out = "\n".join(kt.show([t]))
        self.assertIn("[splits: 2 panes]", out)
        self.assertIn("+ /r", out)
        self.assertIn("omp --continue  (active pane)", out)


class Main(unittest.TestCase):
    def test_every_kitty_window_is_read(self):
        import io, json, contextlib
        data = [{"tabs": [tab(win("/a"))]}, {"tabs": [tab(win("/b", procs=[["make"]]))]}]
        out = io.StringIO()
        with mock_stdin(json.dumps(data)), contextlib.redirect_stdout(out), mock_argv("busy"):
            kt.main()
        self.assertIn("command", out.getvalue())        # the build in the second window counts

    def test_session_reads_kittys_own_save_when_given(self):
        import io, json, contextlib, tempfile
        data = [{"tabs": [split_tab(wid(1, "/l"), wid(2, "/r", active=False), pairs={"one": 1, "two": 2})]}]
        with tempfile.NamedTemporaryFile("w", suffix=".kitty-session", delete=False) as f:
            f.write("set_layout_state " + json.dumps({"pairs": {"bias": 0.2, "one": 1, "two": 2},
                    "all_windows": {"window_groups": [{"id": 1, "window_ids": [1]}, {"id": 2, "window_ids": [2]}]}}) + "\n")
        try:
            for args, bias in (([f.name], 0.2), (["/nonexistent/file"], None), ([], None)):
                out = io.StringIO()
                with mock_stdin(json.dumps(data)), contextlib.redirect_stdout(out), \
                        mock.patch("sys.argv", ["kitty-tabs.py", "session", *args]):
                    kt.main()
                st = json.loads(next(l for l in out.getvalue().splitlines() if l.startswith("set_layout_state "))[17:])
                self.assertEqual(st["pairs"].get("bias"), bias, args)
        finally:
            os.unlink(f.name)


def mock_stdin(text):
    import io
    from unittest import mock
    return mock.patch("sys.stdin", io.StringIO(text))


def mock_argv(mode):
    from unittest import mock
    return mock.patch("sys.argv", ["kitty-tabs.py", mode])


class WhichKitty(unittest.TestCase):
    """kitty-relaunch.sh restarts the kitty it runs in, else the only other kitty with a socket."""
    def c(self, env=None, procs=(), files=()):
        return kt.socket_candidates(env or {}, procs, files)

    def test_the_kitty_you_are_in_comes_first(self):
        got = self.c({"KITTY_LISTEN_ON": "unix:/run/user/1/ninelives-kitty-5"},
                     [["kitty", "--listen-on", "unix:@launcher"]], ["/run/user/1/ninelives-kitty-5"])
        self.assertEqual(got, [("here", "unix:/run/user/1/ninelives-kitty-5"), ("found", "unix:@launcher")])

    def test_a_one_off_connection_is_not_a_socket(self):
        self.assertEqual(self.c({"KITTY_LISTEN_ON": "fd:3"}), [])     # launch --allow-remote-control

    def test_finds_launcher_sockets_and_kitty_conf_sockets(self):
        got = self.c({}, [["/opt/kitty.app/bin/kitty", "--listen-on=unix:@a", "--session", "x"],
                          ["kitty", "-o", "x=y"]], ["/run/user/1/ninelives-kitty-9"])
        self.assertEqual(got, [("found", "unix:@a"), ("found", "unix:/run/user/1/ninelives-kitty-9")])

    def test_never_offers_the_test_or_dev_kitty(self):
        got = self.c({"KITTY_LISTEN_ON": "unix:@ninelives-dev-kitty"},
                     [["kitty", "--listen-on", "unix:@ninelives-test-kitty"], ["kitty", "--listen-on", "unix:@x"]])
        self.assertEqual(got, [("found", "unix:@x")])

    def test_the_command_line_parser_reads_both_spellings(self):
        self.assertEqual(kt._listen_on(["kitty", "--listen-on", "unix:@a"]), "unix:@a")
        self.assertEqual(kt._listen_on(["kitty", "--listen-on=tcp:localhost:5"]), "tcp:localhost:5")
        self.assertIsNone(kt._listen_on(["kitty", "--listen-on"]))


if __name__ == "__main__":
    unittest.main()
