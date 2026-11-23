#!/usr/bin/env python3
"""Unit tests for scripts/sync-public.sh: copying a workshop repo's HEAD into a separate public clone.
Both repos are made up in a temp folder.
    python3 tests/test_sync_public.py"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SYNC = os.path.join(HERE, "..", "scripts", "sync-public.sh")


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout


class SyncPublic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.work, self.pub = os.path.join(t, "work"), os.path.join(t, "pub")
        for d, name in ((self.work, "Workshop Bot"), (self.pub, "Public Me")):
            os.makedirs(os.path.join(d, "scripts"))
            git(d, "init", "-q", "-b", "main")
            git(d, "config", "user.name", name)
            git(d, "config", "user.email", name.split()[0].lower() + "@example.invalid")
        shutil.copy(SYNC, os.path.join(self.work, "scripts", "sync-public.sh"))
        self.write(self.work, "README.md", "hello\n")
        self.write(self.work, "old.txt", "going away\n")
        self.write(self.work, ".gitignore", ".private-words\n")
        self.commit(self.work, "first")
        self.write(self.pub, "placeholder", "")
        self.commit(self.pub, "start")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, d, name, text):
        with open(os.path.join(d, name), "w") as f:
            f.write(text)

    def commit(self, d, msg):
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", msg)

    def sync(self, *args):
        return subprocess.run(["bash", os.path.join(self.work, "scripts", "sync-public.sh"), self.pub, *args],
                              capture_output=True, text=True, timeout=60)

    def test_copies_head_mirrors_deletions_and_commits_as_the_public_identity(self):
        self.assertEqual(self.sync("-m", "release 1").returncode, 0)
        os.remove(os.path.join(self.work, "old.txt"))
        self.commit(self.work, "drop old.txt")
        self.write(self.work, "notes.txt", "uncommitted extras are not copied\n")    # untracked
        r = self.sync("-m", "release 2")
        self.assertEqual(r.returncode, 0, r.stderr)
        files = sorted(git(self.pub, "ls-files").split())
        self.assertIn("README.md", files)
        self.assertNotIn("old.txt", files)
        self.assertNotIn("notes.txt", files)
        self.assertEqual(git(self.pub, "log", "-1", "--format=%an|%s").strip(), "Public Me|release 2")
        self.assertNotIn("Workshop", git(self.pub, "log", "--format=%an %ae"))     # no workshop identity

    def test_private_words_stop_the_copy(self):
        self.write(self.work, ".private-words", "# mine\nsecret-host\n")
        self.write(self.work, "README.md", "see secret-host.example for details\n")
        self.commit(self.work, "oops")
        r = self.sync("-m", "release")
        self.assertEqual(r.returncode, 1)
        self.assertIn("README.md", r.stderr)
        self.assertNotIn("README.md", git(self.pub, "ls-files"))                  # nothing copied

    def test_uncommitted_changes_are_refused(self):
        self.write(self.work, "README.md", "changed but not committed\n")
        self.assertEqual(self.sync().returncode, 1)


if __name__ == "__main__":
    unittest.main()
