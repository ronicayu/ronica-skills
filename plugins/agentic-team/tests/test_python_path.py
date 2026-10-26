"""Tests for scripts/python-path.sh. Run: "$PY" -m unittest discover plugins/agentic-team/tests"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "python-path.sh")
BASH = shutil.which("bash") or "/bin/bash"


class PythonPathTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.bin = os.path.abspath(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def fake(self, name, new_enough):
        """A stand-in interpreter. One that is too old exits 1 for the version check."""
        path = os.path.join(self.bin, name)
        with open(path, "w") as fh:
            fh.write(f"#!/bin/sh\nexit {0 if new_enough else 1}\n")
        os.chmod(path, 0o755)
        return path

    def run_script(self, **env):
        # PATH holds only the fake directory, so no real interpreter can leak in.
        return subprocess.run([BASH, SCRIPT], capture_output=True, text=True,
                              env={"PATH": self.bin, **env})

    def test_honours_valid_agentic_team_python(self):
        out = self.run_script(AGENTIC_TEAM_PYTHON=sys.executable)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, sys.executable))

    def test_agentic_team_python_beats_path(self):
        self.fake("python3.13", True)
        out = self.run_script(AGENTIC_TEAM_PYTHON=sys.executable)
        self.assertEqual(out.stdout.strip(), sys.executable)

    def test_rejects_interpreter_below_3_11(self):
        for name in ("python3.13", "python3.12", "python3.11", "python3"):
            self.fake(name, False)
        out = self.run_script()
        self.assertEqual(out.returncode, 2)
        self.assertEqual(out.stdout, "")
        self.assertIn("3.11", out.stderr)
        self.assertIn("AGENTIC_TEAM_PYTHON", out.stderr)

    def test_invalid_override_is_reported_and_skipped(self):
        old = self.fake("python3.9", False)
        out = self.run_script(AGENTIC_TEAM_PYTHON=old)
        self.assertEqual(out.returncode, 2)
        self.assertIn("ignoring AGENTIC_TEAM_PYTHON", out.stderr)
        good = self.fake("python3", True)
        out = self.run_script(AGENTIC_TEAM_PYTHON=old)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, good))

    def test_prefers_newest_versioned_name_that_runs(self):
        self.fake("python3.13", False)
        wanted = self.fake("python3.12", True)
        self.fake("python3.11", True)
        self.fake("python3", True)
        out = self.run_script()
        self.assertEqual((out.returncode, out.stdout.strip()), (0, wanted))

    def test_falls_back_to_python3(self):
        wanted = self.fake("python3", True)
        out = self.run_script()
        self.assertEqual((out.returncode, out.stdout.strip()), (0, wanted))

    def test_exits_2_when_nothing_is_installed(self):
        out = self.run_script()
        self.assertEqual(out.returncode, 2)
        self.assertIn("Install Python 3.11", out.stderr)


if __name__ == "__main__":
    unittest.main()
