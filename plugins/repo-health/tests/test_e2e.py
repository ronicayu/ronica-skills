"""End to end: detect, hotspots, score and render on a small temporary git repository (no gh).

Run: python -m unittest discover -s plugins/repo-health/tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "repo-health", "scripts")

ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="T",
           GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com")

WORKFLOW = """name: ci
on:
  pull_request:
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python -m unittest discover -s app/tests
"""


class TempRepo(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="rh-e2e-")
        self.out = tempfile.mkdtemp(prefix="rh-e2e-out-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.out, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def git(self, *args):
        subprocess.run(["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false"] + list(args),
                       cwd=self.root, env=ENV, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def script(self, name, *args, **kw):
        done = subprocess.run([sys.executable, os.path.join(SCRIPTS, name)] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, cwd=self.out, **kw)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout


class EndToEnd(TempRepo):
    def test_whole_pipeline(self):
        self.write("app/main.py", "def f(x):\n    if x:\n        return 1\n    return 2\n")
        self.write("app/tests/test_main.py", "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n")
        self.write("other/tests/test_other.py", "def test_b():\n    pass\n")
        self.write("README.md", "# demo\n\n## Install\n\n    pip install x\n")
        self.write(".github/workflows/ci.yml", WORKFLOW)
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "first")
        stamp = "2026-11-10T0930"
        names = {key: "%s-%s.json" % (key, stamp) for key in ("detect", "hotspots", "score", "findings")}
        paths = {key: os.path.join(self.out, name) for key, name in names.items()}
        for key, script in (("detect", "detect.py"), ("hotspots", "hotspots.py")):
            text = self.script(script, self.root)
            with open(paths[key], "w") as handle:
                handle.write(text)
        self.script("score.py", "--detect", paths["detect"], "--hotspots", paths["hotspots"], "-o", paths["score"],
                    "--now", "2026-11-10")
        with open(paths["score"]) as handle:
            score = json.load(handle)
        tests = [r for r in score["dimensions"] if r["id"] == "tests"][0]
        self.assertEqual(tests["rule"], "tests.1p")
        self.assertEqual(tests["partial"]["missing"], ["other/tests"])
        self.assertEqual([r for r in score["dimensions"] if r["id"] == "ci"][0]["level"], 2)
        self.assertFalse(score["ci_health"]["available"])
        self.assertEqual([r for r in score["dimensions"] if r["id"] == "secrets"][0]["status"], "unknown")
        top = score["gaps"][0]
        self.assertEqual(top["id"], "tests:.:missing-suite:other/tests")
        findings = {
            "schema": 2, "lang": "en", "repo": "demo", "stamp": stamp, "headline": "Run the other suite in CI first.",
            "score": names["score"], "inputs": {"detect": names["detect"], "hotspots": names["hotspots"]},
            "overrides": [],
            "recommendations": [{
                "gap": top["id"], "title": "Run the other suite in CI", "why": "CI misses one suite.",
                "impact": "high", "effort": "small",
                "first_step": {"file": ".github/workflows/ci.yml", "snippet": None,
                              "command": "python -m unittest discover -s other/tests",
                              "verify": "python -m unittest discover -s other/tests"},
                "reorder_reason": None}],
            "reviews": {}, "not_checked": [{"what": "tier 1", "why": "needs consent"}]}
        with open(paths["findings"], "w") as handle:
            json.dump(findings, handle)
        out = self.script("render.py", paths["findings"])
        self.assertIn("Run the other suite in CI", out)
        self.assertIn("Report: " + os.path.join(os.path.realpath(self.out), "report-%s.md" % stamp), out.replace(
            "Report: " + self.out, "Report: " + os.path.realpath(self.out)))
        with open(os.path.join(self.out, "report-%s.md" % stamp)) as handle:
            report = handle.read()
        self.assertIn("| Tests | 1 present (partial: 1 of 2 test suites) |", report)
        self.assertIn("`tests:.:missing-suite:other/tests`", report)
        self.assertIn("python -m unittest discover -s other/tests", report)
        self.assertIn("| Secret scanning | unknown", report)
        self.assertNotIn("## Since last run", report)
        self.assertTrue(os.path.exists(os.path.join(self.out, "share-%s.md" % stamp)))


SHAPE_WORKFLOW = """name: ci
on:
  pull_request:
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python -m mypy pkg
      - run: python pkg/tests/run_parallel.py
"""

PEOPLE = (("Yu Rong", "yu@home.example"), ("Ronica", "yu@home.example"), ("Yu Rong", "yu@work.example"),
          ("ronica", "yu@home.example"), ("Claude", "noreply@anthropic.com"))


class OnePersonScriptRunner(TempRepo):
    """A repository shaped like the one this plugin was first tried on: one person under several names and
    e-mails plus an agent, a suite CI runs through a script, Python type-checked in CI, and a few .mjs files."""

    def commit_as(self, name, email, message):
        env = dict(ENV, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email)
        subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", message],
                       cwd=self.root, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_no_false_gaps(self):
        self.write("pkg/scripts/run.py", "def run(x):\n    if x:\n        return 1\n    return 2\n")
        self.write("pkg/tests/test_run.py", "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n")
        self.write("pkg/tests/run_parallel.py", "import unittest\nunittest.main(module=None, argv=['x', 'discover'])\n")
        for n in range(5):
            self.write("tools/t%d.mjs" % n, "export const a = %d;\n" % n)
        self.write(".github/workflows/ci.yml", SHAPE_WORKFLOW)
        self.git("init", "-q")
        self.git("add", ".")
        for n, (name, email) in enumerate(PEOPLE):
            with open(os.path.join(self.root, "pkg", "scripts", "run.py"), "a") as handle:
                handle.write("# %d\n" % n)
            self.git("add", ".")
            self.commit_as(name, email, "change %d" % n)
        paths = {key: os.path.join(self.out, key + ".json") for key in ("d", "h", "s")}
        for key, script in (("d", "detect.py"), ("h", "hotspots.py")):
            with open(paths[key], "w") as handle:
                handle.write(self.script(script, self.root))
        self.script("score.py", "--detect", paths["d"], "--hotspots", paths["h"], "-o", paths["s"], "--now", "2026-11-10")
        with open(paths["s"]) as handle:
            result = json.load(handle)
        ids = [g["id"] for g in result["gaps"]]
        self.assertFalse([i for i in ids if ":missing-suite:" in i], ids[:5])
        self.assertEqual(result["profile"]["authors"], "solo")
        self.assertFalse([i for i in ids if ":single-author:" in i], ids[:5])
        types = [r for r in result["dimensions"] if r["id"] == "types" and r["subproject"] == "."][0]
        self.assertEqual((types["level"], types["rule"]), (2, "types.2"))
        run = [h for h in result["hotspots"] if h["path"] == "pkg/scripts/run.py"]
        self.assertEqual([h["tests_in_ci"] for h in run], [True])


if __name__ == "__main__":
    unittest.main()
