"""Tests for run_parallel.py: it reports every kind of outcome as unittest does, and its exit code is 0 only when
every test passed. Each test writes a small test folder and runs the runner on it with --start-dir."""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_parallel.py")

MIXED = '''
import os, time, unittest

class Mixed(unittest.TestCase):
    def test_passes(self):
        pass

    def test_fails(self):
        self.assertEqual(1, 2)

    def test_raises(self):
        raise RuntimeError("boom")

    def test_kills_its_worker(self):
        os._exit(3)

    def test_hangs(self):
        time.sleep(60)

    @unittest.skip("not here")
    def test_skipped(self):
        pass
'''

ERRORS_ONLY = '''
import os, unittest

class Broken(unittest.TestCase):
    def test_raises(self):
        raise RuntimeError("boom")

    def test_kills_its_worker(self):
        os._exit(3)
'''

PASSING = '''
import unittest

class Fine(unittest.TestCase):
    def test_one(self):
        pass

    def test_two(self):
        self.assertTrue(True)
'''


class RunParallelTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def run_on(self, source, *args):
        with open(os.path.join(self.dir, "test_sample.py"), "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(source))
        return subprocess.run([sys.executable, RUNNER, "--start-dir", self.dir, *args],
                              capture_output=True, text=True, timeout=120)

    def test_every_outcome_is_reported_and_the_exit_code_is_1(self):
        out = self.run_on(MIXED, "-j", "3", "--timeout", "5")
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("Ran 6 tests", out.stderr)
        self.assertIn("FAILED (failures=1, errors=3, skipped=1)", out.stderr)
        self.assertIn("FAIL: test_fails", out.stderr)
        self.assertIn("RuntimeError: boom", out.stderr)
        self.assertIn("the worker process died (exit code 3)", out.stderr)
        self.assertIn("the test ran longer than 5 s and was stopped", out.stderr)

    def test_errors_alone_make_the_run_fail(self):
        out = self.run_on(ERRORS_ONLY, "-j", "2")
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("FAILED (errors=2)", out.stderr)

    def test_a_run_where_every_test_passes_exits_0(self):
        out = self.run_on(PASSING, "-j", "2")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Ran 2 tests", out.stderr)
        self.assertIn("\nOK\n", out.stderr)

    def test_k_selects_like_unittest(self):
        out = self.run_on(PASSING, "-j", "1", "-k", "two")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Ran 1 test in", out.stderr)


if __name__ == "__main__":
    unittest.main()
