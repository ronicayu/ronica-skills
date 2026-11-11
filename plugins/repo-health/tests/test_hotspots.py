"""Tests for scripts/hotspots.py. Fixture git repos are built in temporary directories.

Run: python -m unittest discover -s plugins/repo-health/tests
"""

import datetime
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "repo-health", "scripts")
SCRIPT = os.path.join(SCRIPTS, "hotspots.py")

sys.path.insert(0, SCRIPTS)  # hotspots.py imports detect.py from its own directory
_spec = importlib.util.spec_from_file_location("repo_health_hotspots", SCRIPT)
hotspots = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hotspots)


def git_env(when=None):
    env = dict(os.environ)
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    })
    if when:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    return env


def git(root, *args, **kwargs):
    cmd = ["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false",
           "-c", "user.name=Test", "-c", "user.email=test@example.com"] + list(args)
    return subprocess.run(cmd, cwd=root, env=git_env(kwargs.get("when")), check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()


NESTED = (
    "def f(x):\n"
    "    if x:\n"
    "        for i in x:\n"
    "            while i:\n"
    "                if i > 1:\n"
    "                    i -= 1\n"
    "    return x\n"
)  # indent levels 0 1 2 3 4 5 1 = 16
FLAT = "def g():\n    return 1\n"  # complexity 1
SMALL = "def h():\n    if 1:\n        return 1\n"  # complexity 3


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="repo-health-hotspots-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def commit(self, files, days_ago, message="c"):
        """Write files (path -> text), commit them dated days_ago days back."""
        for rel, text in files.items():
            self.write(rel, text)
        when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
        stamp = when.strftime("%Y-%m-%dT%H:%M:%S +0000")
        git(self.root, "add", "--", *sorted(files))
        git(self.root, "commit", "-q", "-m", message, when=stamp)

    def build_history(self):
        git(self.root, "init", "-q")
        big = {"big250.py": "x = 1\n" * 250, "big600.py": "x = 1\n" * 600, "big1000.py": "x = 1\n" * 1000}
        first = {"a.py": NESTED, "old.py": "o = 1\n"}
        first.update(big)
        self.commit(first, 400)                                                        # outside the window
        self.commit({"a.py": NESTED + "# 2\n", "b.py": FLAT, "tests/test_a.py": "def test_a():\n    pass\n"}, 300)
        self.commit({"a.py": NESTED + "# 3\n", "b.py": FLAT + "# 3\n"}, 200)
        self.commit({"a.py": NESTED + "# 4\n", "b.py": FLAT + "# 4\n", "c.py": SMALL}, 100)
        self.commit({"a.py": NESTED + "# 5\n", "tests/test_a.py": "def test_a():\n    assert 1\n"}, 50)
        self.commit({"b.py": FLAT + "# 6\n"}, 20)
        bulk = {"bulk/f%d.py" % i: "v = %d\n" % i for i in range(31)}                 # a 33-file commit
        bulk["a.py"] = NESTED + "# 7\n"
        bulk["b.py"] = FLAT + "# 7\n"
        self.commit(bulk, 10)

    def analyse(self, **kwargs):
        return hotspots.analyse(self.root, **kwargs)


class GitHistory(Fixture):
    def setUp(self):
        super(GitHistory, self).setUp()
        self.build_history()
        self.result = self.analyse()

    def test_hotspot_order_and_counts(self):
        files = self.result["files"]
        self.assertEqual([f["path"] for f in files[:3]], ["a.py", "b.py", "c.py"])
        a, b, c = files[:3]
        self.assertEqual((a["commits"], b["commits"], c["commits"]), (5, 5, 1))
        self.assertEqual((a["indent_complexity"], b["indent_complexity"], c["indent_complexity"]), (16, 1, 3))
        self.assertEqual(a["score"], 1.0)
        self.assertAlmostEqual(b["score"], 1.0 / 16, places=3)
        self.assertAlmostEqual(c["score"], (1.0 / 5) * (3.0 / 16), places=3)
        self.assertEqual(a["loc"], 8)

    def test_history_outside_the_window_and_tests_are_not_counted(self):
        paths = [f["path"] for f in self.result["files"]]
        self.assertNotIn("old.py", paths)                 # last changed 400 days ago
        self.assertFalse([p for p in paths if p.startswith("tests/")])
        self.assertTrue(self.result["history"]["available"])
        self.assertEqual(self.result["history"]["commits_in_window"], 6)
        self.assertEqual(self.result["history"]["total_commits"], 7)
        wide = self.analyse(months=24, top=100)
        a = [f for f in wide["files"] if f["path"] == "a.py"][0]
        self.assertEqual(a["commits"], 6)                 # the old commit counts in a longer window
        self.assertIn("old.py", [f["path"] for f in wide["files"]])

    def test_cochange_pairs(self):
        self.assertEqual(self.result["cochange"], [{"a": "a.py", "b": "b.py", "commits": 3, "ratio": 0.6}])

    def test_commits_with_more_than_30_files_do_not_make_pairs(self):
        pairs = [(p["a"], p["b"]) for p in self.result["cochange"]]
        self.assertFalse([p for p in pairs if any(x.startswith("bulk/") for x in p)])
        # the bulk commit still counts as a commit of a.py and b.py
        self.assertEqual(self.result["files"][0]["commits"], 5)

    def test_size_buckets_and_largest(self):
        self.assertEqual(self.result["size_buckets"], {"<200": 35, "200-499": 1, "500-999": 1, ">=1000": 1})
        self.assertEqual([f["path"] for f in self.result["largest"][:3]], ["big1000.py", "big600.py", "big250.py"])
        self.assertEqual(self.result["source_files"], 38)

    def test_top_limits_the_lists(self):
        result = self.analyse(top=2)
        self.assertEqual(len(result["files"]), 2)
        self.assertEqual(len(result["largest"]), 2)

    def test_deepest_indent(self):
        self.assertEqual(self.result["deepest_indent"][0]["path"], "a.py")
        self.assertEqual(self.result["deepest_indent"][0]["max_indent"], 5.0)

    def test_untracked_and_generated_files(self):
        self.write("fresh.py", NESTED)
        self.write("vendor/x.py", NESTED)
        self.write("bundle.min.js", "var a = 1;\n")
        result = self.analyse()
        paths = {f["path"] for f in result["largest"]}
        self.assertNotIn("vendor/x.py", paths)
        self.assertNotIn("bundle.min.js", paths)
        self.assertEqual(self.analyse(top=100)["source_files"], 39)  # fresh.py is on disk, so it counts

    def test_cli_prints_json(self):
        out = subprocess.run([sys.executable, SCRIPT, self.root, "--top", "1", "--months", "12"],
                             stdout=subprocess.PIPE, check=True).stdout
        data = json.loads(out.decode())
        self.assertEqual(len(data["files"]), 1)
        self.assertEqual(data["files"][0]["path"], "a.py")


class NoUsableHistory(Fixture):
    def test_no_git(self):
        self.write("a.py", NESTED)
        self.write("b.py", FLAT)
        result = self.analyse()
        self.assertFalse(result["history"]["available"])
        self.assertIn("not a git repository", result["history"]["reason"])
        self.assertEqual([f["path"] for f in result["files"]], ["a.py", "b.py"])  # by indent complexity
        self.assertTrue(all(f["commits"] is None and f["score"] is None for f in result["files"]))
        self.assertEqual(result["cochange"], [])
        self.assertEqual(result["size_buckets"]["<200"], 2)

    def test_git_repo_without_commits(self):
        git(self.root, "init", "-q")
        self.write("a.py", NESTED)
        result = self.analyse()
        self.assertFalse(result["history"]["available"])
        self.assertIn("no commits", result["history"]["reason"])
        self.assertIsNone(result["files"][0]["commits"])

    def test_shallow_clone_with_few_commits(self):
        self.build_history()
        clone = tempfile.mkdtemp(prefix="repo-health-clone-")
        self.addCleanup(shutil.rmtree, clone, ignore_errors=True)
        target = os.path.join(clone, "c")
        git(clone, "clone", "-q", "--depth", "2", "file://" + self.root, target)
        result = hotspots.analyse(target)
        self.assertTrue(result["history"]["shallow"])
        self.assertFalse(result["history"]["available"])
        self.assertIn("shallow clone", result["history"]["reason"])
        self.assertTrue(all(f["commits"] is None for f in result["files"]))

    def test_subdirectory_of_a_repo_without_commits_has_no_history(self):
        git(self.root, "init", "-q")
        self.write("sub/a.py", NESTED)
        result = hotspots.analyse(os.path.join(self.root, "sub"))
        self.assertFalse(result["history"]["available"])
        self.assertEqual([f["path"] for f in result["files"]], ["a.py"])


class Subfolder(Fixture):
    def test_history_of_a_folder_inside_a_repo(self):
        git(self.root, "init", "-q")
        self.commit({"svc/a.py": NESTED, "svc/b.py": FLAT, "other/c.py": NESTED}, 30)
        self.commit({"svc/a.py": NESTED + "# 2\n", "other/c.py": NESTED + "# 2\n"}, 20)
        self.commit({"svc/a.py": NESTED + "# 3\n"}, 10)
        result = hotspots.analyse(os.path.join(self.root, "svc"))
        self.assertTrue(result["history"]["available"])
        self.assertEqual(result["history"]["subpath"], "svc")
        self.assertEqual(result["history"]["commits_in_window"], 3)
        self.assertEqual([(f["path"], f["commits"]) for f in result["files"]], [("a.py", 3), ("b.py", 1)])
        self.assertEqual(result["active_authors_12m"], 1)


def commit_as(fixture, files, days_ago, name, email, message="c"):
    for rel, text in files.items():
        fixture.write(rel, text)
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    env = git_env(when.strftime("%Y-%m-%dT%H:%M:%S +0000"))
    env.update({"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": name,
                "GIT_COMMITTER_EMAIL": email})
    cmd = ["git", "-c", "commit.gpgsign=false", "add", "--"] + sorted(files)
    subprocess.run(cmd, cwd=fixture.root, env=env, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message], cwd=fixture.root,
                   env=env, check=True, stdout=subprocess.PIPE)


class Authors(Fixture):
    def test_authors_share_and_active_authors(self):
        git(self.root, "init", "-q")
        commit_as(self, {"a.py": NESTED, "b.py": FLAT}, 50, "Ann", "ann@example.com")
        commit_as(self, {"a.py": NESTED + "# 2\n"}, 40, "Ann", "ann@example.com")
        commit_as(self, {"a.py": NESTED + "# 3\n"}, 30, "Ann Q", "ANN@example.com")   # same person, other spelling
        commit_as(self, {"a.py": NESTED + "# 4\n", "b.py": FLAT + "# 4\n"}, 20, "Bob", "bob@example.com")
        commit_as(self, {"c.py": FLAT}, 10, "Cy", "cy@example.com")
        result = hotspots.analyse(self.root)
        files = {f["path"]: f for f in result["files"]}
        self.assertEqual((files["a.py"]["commits"], files["a.py"]["authors"]), (4, 2))
        self.assertEqual(files["a.py"]["top_author_share"], 0.75)
        self.assertIn(files["a.py"]["top_author"], ("Ann", "Ann Q"))
        self.assertEqual((files["b.py"]["authors"], files["b.py"]["top_author_share"]), (2, 0.5))
        self.assertEqual((files["c.py"]["authors"], files["c.py"]["top_author"], files["c.py"]["top_author_share"]),
                         (1, "Cy", 1.0))
        self.assertEqual(result["active_authors_12m"], 3)

    def test_authors_outside_the_window_are_not_active(self):
        git(self.root, "init", "-q")
        commit_as(self, {"a.py": NESTED}, 400, "Old", "old@example.com")
        commit_as(self, {"a.py": NESTED + "# 2\n"}, 10, "New", "new@example.com")
        result = hotspots.analyse(self.root)
        self.assertEqual(result["active_authors_12m"], 1)
        self.assertEqual(result["files"][0]["top_author"], "New")

    def test_no_history_has_no_author_facts(self):
        self.write("a.py", NESTED)
        result = hotspots.analyse(self.root)
        self.assertIsNone(result["active_authors_12m"])
        self.assertEqual(result["files"][0]["authors"], None)


class Renames(Fixture):
    def test_a_moved_file_keeps_its_history(self):
        git(self.root, "init", "-q")
        body = "".join("line %d\n" % i for i in range(40)) + NESTED
        self.commit({"old/mod.py": body}, 100)
        self.commit({"old/mod.py": body + "# 2\n"}, 90)
        git(self.root, "mv", "old", "pkg")                       # a directory rename
        self.commit({"pkg/mod.py": body + "# 2\n"}, 80)
        self.commit({"pkg/mod.py": body + "# 3\n"}, 70)
        git(self.root, "mv", "pkg/mod.py", "pkg/renamed.py")
        self.commit({"pkg/renamed.py": body + "# 3\n"}, 60)
        self.commit({"pkg/renamed.py": body + "# 4\n"}, 50)
        result = hotspots.analyse(self.root)
        files = {f["path"]: f for f in result["files"]}
        self.assertEqual(list(files), ["pkg/renamed.py"])
        self.assertEqual(files["pkg/renamed.py"]["commits"], 6)

    def test_a_new_file_at_an_old_name_is_not_the_moved_file(self):
        git(self.root, "init", "-q")
        body = "".join("line %d\n" % i for i in range(40))
        self.commit({"a.py": body}, 100)
        git(self.root, "mv", "a.py", "b.py")
        self.commit({"b.py": body}, 90)
        self.commit({"a.py": "other = 1\n"}, 80)                  # a.py is a different file now
        result = hotspots.analyse(self.root)
        files = {f["path"]: f["commits"] for f in result["files"]}
        self.assertEqual(files, {"b.py": 2, "a.py": 1})

    def test_cochange_follows_renames(self):
        git(self.root, "init", "-q")
        body = "".join("line %d\n" % i for i in range(40))
        self.commit({"a.py": body, "x.py": body + "y\n"}, 100)
        self.commit({"a.py": body + "1\n", "x.py": body + "y1\n"}, 90)
        git(self.root, "mv", "a.py", "z.py")
        self.commit({"z.py": body + "1\n"}, 80)
        self.commit({"z.py": body + "2\n", "x.py": body + "y2\n"}, 70)
        pairs = hotspots.analyse(self.root)["cochange"]
        self.assertEqual(pairs, [{"a": "x.py", "b": "z.py", "commits": 3, "ratio": 1.0}])


class GeneratedFiles(Fixture):
    def test_generated_vendored_and_migration_files_are_not_hotspots(self):
        git(self.root, "init", "-q")
        files = {"app/core.py": NESTED,
                 "app/api_pb2.py": NESTED,
                 "gen/schema.go": "// Code generated by x. DO NOT EDIT.\n" + NESTED,
                 "gen/types.ts": "// @generated\n" + NESTED,
                 "gen/auto.ts": "/* auto-generated */\n" + NESTED,
                 "app/migrations/0001_initial.py": NESTED,
                 "third/lib.py": NESTED,
                 ".gitattributes": "third/ linguist-vendored\ngen/forced.py linguist-generated\n",
                 "gen/forced.py": NESTED}
        self.commit(files, 30)
        self.commit({"app/core.py": NESTED + "# 2\n", "app/api_pb2.py": NESTED + "# 2\n",
                     "gen/schema.go": "// Code generated by x. DO NOT EDIT.\n" + NESTED + "// 2\n",
                     "gen/types.ts": "// @generated\n" + NESTED + "// 2\n"}, 20)
        result = hotspots.analyse(self.root)
        self.assertEqual([f["path"] for f in result["files"]], ["app/core.py"])
        self.assertEqual(result["source_files"], 1)
        self.assertEqual(result["excluded"], {"generated": 5, "vendored": 1, "migrations": 1})
        self.assertNotIn("app/api_pb2.py", [f["path"] for f in result["largest"]])


class OneLogCall(Fixture):
    def test_git_log_runs_once(self):
        self.build_history()
        calls = []
        real = hotspots.detect.run_git

        def counting(root, args):
            calls.append(list(args))
            return real(root, args)

        hotspots.detect.run_git = counting
        try:
            hotspots.analyse(self.root)
        finally:
            hotspots.detect.run_git = real
        self.assertEqual(len([c for c in calls if "log" in c]), 1)
        log = [c for c in calls if "log" in c][0]
        self.assertIn("--no-show-signature", log)
        self.assertIn("-M", log)
        self.assertNotIn("--no-renames", log)


class Measure(unittest.TestCase):
    def test_two_space_indent_unit_is_inferred(self):
        loc, complexity, deepest = hotspots.measure("a:\n  b:\n    c:\n      d\n")
        self.assertEqual((loc, complexity, deepest), (4, 6, 3))

    def test_four_space_indent(self):
        self.assertEqual(hotspots.measure("a\n    b\n        c\n")[1:], (3, 2))

    def test_tabs_count_as_four_spaces(self):
        self.assertEqual(hotspots.measure("a\n\tb\n\t\tc\n")[1:], (3, 2))

    def test_blank_lines_are_ignored(self):
        self.assertEqual(hotspots.measure("a\n\n    \n    b\n")[0:2], (2, 1))

    def test_empty_text(self):
        self.assertEqual(hotspots.measure(""), (0, 0, 0))

    def test_buckets(self):
        self.assertEqual([hotspots.bucket(n) for n in (0, 199, 200, 499, 500, 999, 1000)],
                         ["<200", "<200", "200-499", "200-499", "500-999", "500-999", ">=1000"])

    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        with open(SCRIPT) as handle:
            self.assertEqual(handle.readline().strip(), "#!/usr/bin/env python3")


if __name__ == "__main__":
    unittest.main()
