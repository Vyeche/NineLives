#!/usr/bin/env python3
"""Unit tests for config/command_title.py: a running command's tab shows its program and subcommand,
never its arguments, while titles agents and people set stay. Also how the search box (tab-finder.py)
and kitty-relaunch's --status (kitty-tabs.py busy) use it; the sidebar's side is in test_tab_bar.py.
No kitty needed:  python3 -m unittest discover -s tests          (or: python3 tests/test_command_title.py)
The secrets below are made up; MARK stands in for a password or token that must never be shown."""
import importlib.util
import os
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, *path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "..", *path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ct = load("nl_command_title", "config", "command_title.py")
tf = load("nl_tab_finder_ct", "config", "tab-finder.py")
kt = load("nl_kitty_tabs_ct", "scripts", "kitty-tabs.py")

MARK = "zq7PRIVzq"
# (command line, what the tab shows)
SHORT = [
    ("npm run build", "npm run build"),
    ("npm run build -- --token=" + MARK, "npm run build"),
    ("npm run build:prod", "npm run"),                     # a : is not a subcommand's
    ("git push origin main", "git push"),
    ("git commit -m 'wip " + MARK + "'", "git commit"),
    ("git -C /w/proj status", "git"),                       # an option first: the program only
    ("make test", "make test"),
    ("make -j8 test", "make"),
    ("docker compose up -d", "docker compose up"),
    ("docker run --rm -e KEY=" + MARK + " alpine", "docker run"),
    ("cargo test --release", "cargo test"),
    ("uv run pytest -k " + MARK, "uv run pytest"),
    ("kubectl get pods", "kubectl get"),
    ("gh auth login --with-token", "gh auth"),
    ("python3 -m pytest -k " + MARK, "python3 -m pytest"),
    ("python3 -mpytest", "python3 -m pytest"),
    ("python3 -m pip install requests", "python3 -m pip install"),
    ("python3 manage.py migrate", "python3 manage.py migrate"),
    ("python3 scripts/check.py --token " + MARK, "python3 check.py"),
    ("python3 -c 'print(\"" + MARK + "\")'", "python3"),  # code is never shown
    ("node -e 'fetch(\"" + MARK + "\")'", "node"),
    ("node --require ./hook.js server.js", "node server.js"),
    ("perl -ne 'print if /" + MARK + "/' f", "perl"),
    ("bash -lc 'curl " + MARK + "'", "bash"),
    ("bash deploy.sh " + MARK, "bash deploy.sh"),
    # chains name their last command, pipes their first
    ("cd x && make test", "make test"),
    ("a; b", "b"),
    ("a || b", "b"),
    ("make 2>&1 | tee log", "make"),
    ("cat notes.txt | grep " + MARK, "cat"),
    ("echo " + MARK + " | docker login --password-stdin -u me", "echo"),
    ("(cd sub && make)", "make"),
    ("for f in *; do make $f; done", "make"),
    ("if grep -q x f; then make build; fi", "make build"),
    ("echo $(cat " + MARK + ".txt) > /dev/null", "echo"),
    ("nohup ./server &", "server"),
    ("first --x\nsecond --key " + MARK, "first"),          # more lines: the first one only
    ("cat <<EOF > key.txt\n" + MARK + "\nEOF", "cat"),         # a here-document's text is data
    # assignments are dropped, wrappers passed over
    ("API_KEY=" + MARK + " npm run dev", "npm run dev"),
    ("API_KEY=" + MARK, ""),                                # nothing to show: the folder instead
    ("export API_KEY=" + MARK, "export"),
    ("sudo -u postgres psql -c \"ALTER ROLE x PASSWORD '" + MARK + "'\"", "psql"),
    ("sudo -E make install", "make install"),
    ("env -i PATH=/bin KEY=" + MARK + " make deploy", "make deploy"),
    ("time make -j8", "make"),
    ("timeout 30 ./deploy.sh --key=" + MARK, "deploy.sh"),
    ("watch -n 1 kubectl get pods", "kubectl get"),
    ("sudo -i", "sudo"),
    # programs whose next word could be anything: the program alone
    ("mysql -u root -p" + MARK + " db", "mysql"),
    ("mysql " + MARK, "mysql"),
    ("curl -H 'X-Auth: " + MARK + "' https://x.test/api", "curl"),
    ("/usr/bin/curl -u me:" + MARK + " https://x.test", "curl"),
    ("ssh me@host.test", "ssh"),
    ("ssh " + MARK, "ssh"),
    ("openssl passwd " + MARK, "openssl"),
    ("./run.sh " + MARK, "run.sh"),
    ("sleep 30 --" + MARK, "sleep"),
    ("API_KEY=x read -t 30 v", "read"),
    ("git commit -m \"open quote " + MARK, "git"),          # can't be parsed: the program only
]


class ShortCommand(unittest.TestCase):
    def test_program_and_subcommand(self):
        for line, want in SHORT:
            self.assertEqual(ct.short_command(line), want, line)

    def test_no_argument_is_ever_shown(self):
        for line, _ in SHORT:
            self.assertNotIn(MARK, ct.short_command(line), line)
            self.assertNotIn(MARK, ct.shown_title(line, line), line)

    def test_odd_input_is_safe(self):
        for line in ("", "   ", ";;", "&&", "|", "()", "$(x)", ")", "'", "\\", "x\x00y " + MARK, "a" * 300):
            out = ct.short_command(line)
            self.assertIsInstance(out, str)
            self.assertNotIn(MARK, out)
            self.assertLessEqual(len(out), 120)


class WhichTitles(unittest.TestCase):
    """Titles that are the command line the shell reported, and titles that aren't."""
    CMD = "curl -H 'X-Auth: " + MARK + "' https://x.test"

    def test_the_title_bash_sets(self):
        self.assertEqual(ct.shown_title(self.CMD, self.CMD), "curl")
        # kitty collapses whitespace and drops control characters (sanitize_title)
        self.assertEqual(ct.shown_title("make   test", "make   test\x07"), "make test")
        self.assertEqual(ct.shown_title("echo ab" + MARK, "echo a\nb" + MARK), "echo")

    def test_over_ssh_the_host_stays_in_front(self):
        self.assertEqual(ct.shown_title("box: " + self.CMD, self.CMD), "box: curl")
        self.assertEqual(ct.shown_title("[box] " + self.CMD, self.CMD), "[box] curl")

    def test_zsh_shows_a_newline_as_backslash_n(self):
        self.assertEqual(ct.shown_title("make a\\nmake " + MARK, "make a\nmake " + MARK), "make a")

    def test_fish_shows_20_characters_and_the_folder(self):
        title = self.CMD[:20] + " ~/w/proj"
        self.assertEqual(ct.shown_title(title, self.CMD), "curl")
        self.assertEqual(ct.shown_title("make test ~/w/proj", "make test"), "make test")

    def test_a_title_cut_short(self):
        self.assertEqual(ct.shown_title(self.CMD[:30] + "…", self.CMD), "curl")

    def test_titles_programs_set_stay(self):
        for title, cmd in (("✳ Fix the login bug", "claude"), ("⠋ omp: refactor the parser", "omp"),
                           ("omp: refactor the parser", "omp"), ("Downloading weights", "./fetch.sh"),
                           ("✳ Fix the login bug", "claude --resume abc-123"), ("htop", "")):
            self.assertEqual(ct.shown_title(title, cmd), title, title)

    def test_folders_stay(self):
        for title in ("~/w/proj", "/w/proj", "…/a/b/c", "box: ~/w", "me@box:~/w"):
            self.assertEqual(ct.shown_title(title, "cd " + title), title)
            self.assertEqual(ct.shown_title(title, "", at_prompt=True), title)
        # the last command's long folder-like start is not mistaken for a cut title
        self.assertEqual(ct.shown_title("~/code/a-long-folder-name/x", "~/code/a-long-folder-name/x/run.sh --k"),
                         "~/code/a-long-folder-name/x")

    def test_between_the_title_and_the_reported_command(self):
        # bash sets the title first, then reports the command (kitty.bash): for that moment kitty
        # still has the last command, and the window is at its prompt
        new = "API_KEY=" + MARK + " read -t 30 v"
        self.assertEqual(ct.shown_title(new, "ls", at_prompt=True), "read")
        self.assertEqual(ct.shown_title(new, "ls", at_prompt=False), new)    # not known as a command

    def test_another_title_format_for_the_same_program(self):
        # a shell or theme that writes the title its own way: the program matches, so it's the command
        self.assertEqual(ct.shown_title("me@box: time mysql -u root -p" + MARK, "mysql -u root -p" + MARK),
                         "me@box: mysql")
        self.assertEqual(ct.shown_title("omp: refactor the parser", "omp"), "omp: refactor the parser")

    def test_no_reported_command_but_the_program_runs(self):
        title = "sleep 300 " + MARK
        self.assertEqual(ct.shown_title(title, "", foreground=["sleep"]), "sleep")
        self.assertEqual(ct.shown_title(title, "", foreground=lambda: ["/bin/sleep"]), "sleep")
        self.assertEqual(ct.shown_title("sudo apt upgrade " + MARK, "", foreground=["sudo"]), "apt upgrade")
        self.assertEqual(ct.shown_title(title, "", foreground=["vim"]), title)
        asked = []
        ct.shown_title("✳ Fix", "claude", foreground=lambda: asked.append(1) or ["claude"])
        self.assertEqual(asked, [])                              # a reported command: nothing to look up

    def test_only_assignments_give_no_name(self):
        self.assertEqual(ct.shown_title("API_KEY=" + MARK, "API_KEY=" + MARK), "")

    def test_full_commands_shows_it_all(self):
        self.assertEqual(ct.shown_title(self.CMD, self.CMD, full=True), self.CMD)


class Finder(unittest.TestCase):
    """The search box shows and matches the same short name."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"KITTY_CONFIG_DIRECTORY": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def win(title, cmdline="", procs=(("bash",),), at_prompt=False, overridden=False, me=False, active=True):
        return {"title": title, "cwd": "/w/proj", "is_active": active, "is_self": me, "program_status": [],
                "title_overridden": overridden, "last_reported_cmdline": cmdline, "at_prompt": at_prompt,
                "foreground_processes": [{"cmdline": list(p)} for p in procs]}

    @staticmethod
    def ls(*tabs):
        out = []
        for i, (wins, renamed) in enumerate(tabs, 1):
            out.append({"id": i, "title": renamed or wins[-1]["title"], "is_active": i == 1,
                        "title_overridden": bool(renamed), "windows": wins})
        return [{"is_focused": True, "tabs": out}]

    def test_names_and_matching(self):
        cmd = "mysql -u root -p" + MARK + " customers"
        data = self.ls(([self.win(cmd, cmd, procs=[("bash",), ("mysql",)])], ""),
                       ([self.win("✳ Fix the login bug", "claude", procs=[("claude",)])], ""),
                       ([self.win(cmd, cmd)], "my " + MARK + " tab"))          # renamed: yours, kept
        rows = tf.rows(data)
        self.assertEqual([r["name"] for r in rows], ["mysql", "Fix the login bug", "my " + MARK + " tab"])
        self.assertEqual([r["id"] for r in tf.matches(rows, MARK)], [3])          # only the name you gave
        self.assertEqual(tf.matches(rows, "customers"), [])
        self.assertEqual([r["id"] for r in tf.matches(rows, "mysql")], [1])
        drawn = tf.draw(rows, "", 0, 80, 20)
        self.assertEqual(drawn.count(MARK), 1)

    def test_an_overlay_with_a_copy_of_the_title(self):
        # the F1 sheet opens with --title current: its title is the covered window's command line
        cmd = "psql postgres://me:" + MARK + "@db.test/app"
        base = self.win(cmd, cmd, active=False)
        sheet = self.win(cmd, "", procs=[("sh",)], overridden=True)
        self.assertEqual(tf.rows(self.ls(([base, sheet], "")))[0]["name"], "psql")

    def test_a_split_tab_is_named_by_its_active_pane(self):
        # an agent pane active, a shell pane next to it at its prompt: the agent's title stays
        agent = self.win("✳ Fix the login bug", "claude", procs=[("claude",)])
        shell = self.win("~/w/proj", "make deploy", at_prompt=True, active=False)
        rows = tf.rows(self.ls(([shell, agent], "")))
        self.assertEqual(rows[0]["name"], "Fix the login bug")
        self.assertEqual([r["id"] for r in tf.matches(rows, "login")], [1])

    def test_a_window_title_you_set_stays(self):
        mine = self.win("deploy notes", "make deploy", at_prompt=True, overridden=True)
        self.assertEqual(tf.rows(self.ls(([mine], "")))[0]["name"], "deploy notes")

    def test_full_commands_switch(self):
        cmd = "make deploy KEY=" + MARK
        open(os.path.join(self.tmp.name, "full-commands"), "w").close()
        self.assertEqual(tf.rows(self.ls(([self.win(cmd, cmd)], "")))[0]["name"], cmd)


class RelaunchStatus(unittest.TestCase):
    def test_busy_lines_never_hold_arguments(self):
        cmd = "make deploy KEY=" + MARK
        w = {"cwd": "/w", "title": cmd, "is_active": True, "last_reported_cmdline": cmd,
             "foreground_processes": [{"cmdline": ["bash"]}, {"cmdline": ["make", "deploy"]}],
             "program_status": []}
        out = kt.busy([{"title": cmd, "is_active": True, "title_overridden": False, "windows": [w]}])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].endswith("make deploy"), out)
        self.assertNotIn(MARK, out[0])


if __name__ == "__main__":
    unittest.main()
