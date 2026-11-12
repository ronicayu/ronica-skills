"""A repository under review must not run code through the scripts.

The fixture repository has a commit with a `gpgsig` header, `log.showSignature=true`
and `gpg.program` pointing at a marker script. A plain `git log` runs that script;
the scripts must not.

Run: python -m unittest discover -s plugins/repo-health/tests
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "repo-health", "scripts")
sys.path.insert(0, SCRIPTS)


def load(name):
    spec = importlib.util.spec_from_file_location("repo_health_safety_" + name, os.path.join(SCRIPTS, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect = load("detect")
hotspots = load("hotspots")
ghfacts = load("ghfacts")


def git_env():
    env = dict(os.environ)
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"})
    return env


def git(root, *args, **kwargs):
    cmd = ["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false"] + list(args)
    return subprocess.run(cmd, cwd=root, env=git_env(), check=True, input=kwargs.get("input"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()


class SignedCommitRepo(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="repo-health-safety-")
        self.outside = tempfile.mkdtemp(prefix="repo-health-safety-out-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.outside, ignore_errors=True)
        self.marker = os.path.join(self.outside, "ran")
        program = os.path.join(self.outside, "gpg.sh")
        with open(program, "w") as handle:
            handle.write("#!/bin/sh\ntouch '%s'\nexit 1\n" % self.marker)
        os.chmod(program, 0o755)
        git(self.root, "init", "-q")
        with open(os.path.join(self.root, "a.py"), "w") as handle:
            handle.write("def f():\n    return 1\n")
        git(self.root, "add", "a.py")
        git(self.root, "commit", "-q", "-m", "init")
        tree = git(self.root, "rev-parse", "HEAD^{tree}")
        now = int(time.time())
        body = ("tree %s\nauthor T <t@example.com> %d +0000\ncommitter T <t@example.com> %d +0000\n"
                "gpgsig -----BEGIN PGP SIGNATURE-----\n \n iQEzBAABCAAdFiEE\n -----END PGP SIGNATURE-----\n\nsigned\n"
                % (tree, now, now))
        sha = git(self.root, "hash-object", "-t", "commit", "-w", "--stdin", input=body.encode())
        git(self.root, "update-ref", "refs/heads/main", sha)
        git(self.root, "config", "log.showSignature", "true")
        git(self.root, "config", "gpg.program", program)

    def test_the_fixture_is_dangerous_for_a_plain_git_log(self):
        subprocess.run(["git", "log", "-1"], cwd=self.root, env=git_env(),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not os.path.exists(self.marker):
            self.skipTest("this git does not run gpg.program for log.showSignature")
        os.remove(self.marker)

    def test_detect_does_not_run_gpg_program(self):
        detect.Detector(self.root, 10).run()
        self.assertFalse(os.path.exists(self.marker), "detect.py ran the repo's gpg.program")

    def test_hotspots_does_not_run_gpg_program(self):
        result = hotspots.analyse(self.root)
        self.assertTrue(result["history"]["available"])
        self.assertFalse(os.path.exists(self.marker), "hotspots.py ran the repo's gpg.program")

    def test_ghfacts_does_not_run_gpg_program(self):
        git(self.root, "remote", "add", "origin", "https://github.com/acme/widgets.git")
        with mock.patch.object(ghfacts.shutil, "which", return_value=None):   # never reach a real gh
            result = ghfacts.collect(self.root)
        self.assertIn("not installed", result["why"])
        self.assertFalse(os.path.exists(self.marker), "ghfacts.py ran the repo's gpg.program")


if __name__ == "__main__":
    unittest.main()
