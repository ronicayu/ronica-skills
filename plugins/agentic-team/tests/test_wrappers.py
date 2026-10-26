"""Tests for the wrapper scripts scripts/run, scripts/config and scripts/tg.

Run: uv run --python 3.11 --with pytest python -m pytest plugins/agentic-team/tests -q
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
PLUGINS = os.path.dirname(os.path.dirname(HERE))
TG_PY = os.path.join(PLUGINS, "taskgraph", "skills", "taskgraph", "scripts", "tg.py")
BASH = shutil.which("bash") or "/bin/bash"
WRAPPERS = ("run", "config", "tg")


class WrapperTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        self.cwd = os.path.join(self.tmp, "elsewhere")
        os.mkdir(self.cwd)

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, **extra):
        env = dict(os.environ)
        env.update(AGENTIC_TEAM_PYTHON=sys.executable, TASKGRAPH_TG=TG_PY)
        env.update(extra)
        return env

    def call(self, path, *args, **extra):
        return subprocess.run([path, *args], capture_output=True, text=True,
                              cwd=self.cwd, env=self.env(**extra))

    def fake_python(self, name, exit_code):
        """A stand-in interpreter. It passes the version check (`-c`), prints
        its arguments, then exits with `exit_code`."""
        path = os.path.join(self.tmp, name)
        with open(path, "w") as fh:
            fh.write('#!/bin/sh\n[ "$1" = "-c" ] && exit 0\n'
                     f'for a in "$@"; do echo "$a"; done\nexit {exit_code}\n')
        os.chmod(path, 0o755)
        return path

    def test_wrappers_are_executable(self):
        for name in WRAPPERS:
            self.assertTrue(os.access(os.path.join(SCRIPTS, name), os.X_OK), name)

    def test_help_from_another_directory(self):
        for name, usage in (("run", "run.py"), ("config", "config.py"), ("tg", "tg")):
            out = self.call(os.path.join(SCRIPTS, name), "--help")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("usage: " + usage, out.stdout)

    def test_runs_through_a_symlink(self):
        for name, usage in (("run", "run.py"), ("config", "config.py"), ("tg", "tg")):
            link = os.path.join(self.tmp, "link-" + name)
            os.symlink(os.path.join(SCRIPTS, name), link)
            out = self.call(link, "--help")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("usage: " + usage, out.stdout)

    def test_runs_through_a_chain_of_relative_symlinks(self):
        sub = os.path.join(self.tmp, "sub")
        os.mkdir(sub)
        os.symlink(os.path.join(SCRIPTS, "run"), os.path.join(sub, "first"))
        os.symlink(os.path.join("sub", "first"), os.path.join(self.tmp, "second"))
        out = self.call(os.path.join(self.tmp, "second"), "--help")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("usage: run.py", out.stdout)

    def test_runs_when_bash_is_given_a_bare_name(self):
        out = subprocess.run([BASH, "run", "--help"], capture_output=True, text=True,
                             cwd=SCRIPTS, env=self.env())
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("usage: run.py", out.stdout)

    def test_exits_2_with_the_message_when_no_python_qualifies(self):
        empty = os.path.join(self.tmp, "empty-bin")
        os.mkdir(empty)
        # python-path.sh starts with `env bash`, so bash must be on PATH.
        os.symlink(BASH, os.path.join(empty, "bash"))
        for name in WRAPPERS:
            out = subprocess.run([BASH, os.path.join(SCRIPTS, name), "--help"],
                                 capture_output=True, text=True, cwd=self.cwd,
                                 env={"PATH": empty})
            self.assertEqual(out.returncode, 2, name)
            self.assertEqual(out.stdout, "")
            self.assertIn("Install Python 3.11", out.stderr)
            self.assertIn("AGENTIC_TEAM_PYTHON", out.stderr)

    def test_ignores_cdpath_and_runs_from_a_relative_path(self):
        # A CDPATH entry holding a decoy "scripts" directory must not win.
        decoy = os.path.join(self.tmp, "cdpath", "scripts")
        os.makedirs(decoy)
        base = os.path.dirname(SCRIPTS)
        for name in WRAPPERS:
            out = subprocess.run(["bash", os.path.join("scripts", name), "--help"],
                                 capture_output=True, text=True, cwd=base,
                                 env=self.env(CDPATH=os.path.join(self.tmp, "cdpath")))
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stderr, "")
            self.assertIn("usage:", out.stdout)

    def test_tg_exits_1_with_the_message_when_taskgraph_is_not_found(self):
        # A copy of the scripts with no sibling taskgraph plugin next to it.
        scripts = os.path.join(self.tmp, "plugins", "agentic-team", "scripts")
        os.makedirs(scripts)
        for name in ("tg", "tg-path.sh", "python-path.sh"):
            shutil.copy2(os.path.join(SCRIPTS, name), scripts)
        out = self.call(os.path.join(scripts, "tg"), "projects",
                        TASKGRAPH_TG=os.path.join(self.tmp, "none.py"),
                        CLAUDE_CONFIG_DIR=os.path.join(self.tmp, "no-config"))
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stdout, "")
        self.assertIn("taskgraph plugin not found", out.stderr)
        self.assertIn("TASKGRAPH_TG", out.stderr)

    def test_passes_arguments_and_exit_code_through(self):
        fake = self.fake_python("fake-python", 7)
        for name, target in (("run", os.path.join(SCRIPTS, "run.py")),
                             ("config", os.path.join(SCRIPTS, "config.py")),
                             ("tg", TG_PY)):
            out = self.call(os.path.join(SCRIPTS, name), "--project", "p",
                            "two words", "-x", AGENTIC_TEAM_PYTHON=fake)
            self.assertEqual(out.returncode, 7, name)
            self.assertEqual(out.stdout.splitlines(),
                             [target, "--project", "p", "two words", "-x"], name)

    def test_tg_runs_a_real_command_with_the_given_database(self):
        db = os.path.join(self.tmp, "tasks.db")
        out = self.call(os.path.join(SCRIPTS, "tg"), "--db", db, "--project", "demo",
                        "add", "First task")
        self.assertEqual(out.returncode, 0, out.stderr)
        out = self.call(os.path.join(SCRIPTS, "tg"), "--db", db, "--project", "demo", "ls")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("First task", out.stdout)

    def test_config_check_exit_code_passes_through(self):
        out = self.call(os.path.join(SCRIPTS, "config"), "--root", self.cwd, "check")
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("Install Python", out.stderr)


if __name__ == "__main__":
    unittest.main()
