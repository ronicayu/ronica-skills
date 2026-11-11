"""Tests for scripts/score.py. Detect, hotspots and ghfacts JSON are written inline.

Run: python -m unittest discover -s plugins/repo-health/tests
"""

import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "repo-health", "scripts")
SCRIPT = os.path.join(SCRIPTS, "score.py")
sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("repo_health_score", SCRIPT)
score = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score)
import detect  # noqa: E402

NOW = datetime.date(2026, 11, 10)
CATEGORIES = [c for c in detect.CATEGORIES if c != "hooks"]


def ci_row(tool, category, language, commands=None, pr=True, nb=False, **extra):
    row = {"tool": tool, "category": category, "language": language, "file": ".github/workflows/ci.yml",
           "line": 10, "how": "ci", "lines": [10], "commands": commands or [tool], "non_blocking": nb,
           "pull_request": pr, "jobs": ["a"]}
    row.update(extra)
    return row


def cfg_row(tool, category, file="cfg.toml", line=1, how="config", **extra):
    row = {"tool": tool, "category": category, "file": file, "line": line, "how": how}
    row.update(extra)
    return row


def sub(path=".", langs=("python",), cats=None, suites=None, loc=5000, test_files=1, direct=1, **extra):
    categories = {c: [] for c in CATEGORIES}
    categories.update(cats or {})
    record = {"path": path, "manifest": None, "manifests": [], "languages": list(langs),
              "stats": {l: dict({"files": 3, "loc": loc, "test_files": test_files, "test_loc": 10},
                                **({"ts_files": 3} if l == "typescript" else {})) for l in langs},
              "categories": categories, "dependencies": {"direct": direct, "dev": 0, "files": []},
              "workspace": None, "members": [], "test_suites": suites if suites is not None else (
                  [{"path": path, "language": langs[0], "files": 1, "loc": 10}] if test_files else []),
              "publishable": None}
    record.update(extra)
    return record


def det(subs=None, rows=(), ci=True, pr=True, **top):
    data = {"repo": "/r", "commit": "abc", "default_branch": "main", "languages": {}, "subprojects": subs or [sub()],
            "shared": [], "precommit": {"tools": []}, "strictness": [], "coverage_thresholds": [],
            "suppressions": {}, "architecture_docs": [],
            "ci": {"files": ([{"file": ".github/workflows/ci.yml", "provider": "github", "pull_request": pr,
                               "tools": list(rows), "jobs": [], "installs": []}] if ci else []),
                   "locked_installs": []},
            "setup": {"lockfiles": [], "toolchain_pins": [], "task_runners": [], "devcontainer": [],
                      "dockerfiles": [], "compose": [], "update_bots": [], "requirements_files": []},
            "docs": {"readme": "README.md", "headings": [], "commands": [], "install": {"found": True},
                     "run": {"found": True}, "test": {"found": True}, "contributing": None}}
    data.update(top)
    return data


def hot(files=(), authors=3):
    return {"files": list(files), "active_authors_12m": authors}


def hfile(path, language="python", score_=0.9, commits=10, share=0.5):
    return {"path": path, "language": language, "loc": 500, "commits": commits, "score": score_, "authors": 3,
            "top_author_share": share}


def run(detect_json=None, hotspots=None, gh=None, t1=None, **kw):
    kw.setdefault("now", NOW)
    result = score.build(detect_json or det(), hotspots or hot(), gh, t1, **kw)
    for item in result["dimensions"]:
        assert re.search("[\u4e00-\u9fff]", item["summary_zh"]), "no Chinese summary for: " + item["summary"]
    return result


def dim(result, dim_id, path="."):
    for row in result["dimensions"]:
        if row["id"] == dim_id and row["subproject"] == path:
            return row
    raise AssertionError("no %s row for %s" % (dim_id, path))


def gap_ids(result):
    return [g["id"] for g in result["gaps"]]


def gh(**kw):
    data = {"available": True, "visibility": "public", "runs": {"overall": {"completed": 50, "pass_rate": 0.97,
            "rerun_rate": 0.02, "median_duration_s": 100, "last_failure": None}, "workflows": {}},
            "branch_protection": {"state": "none", "required_status_checks": []},
            "security_and_analysis": "not_visible", "pull_requests": None}
    data.update(kw)
    return data


class Lint(unittest.TestCase):
    def test_lint_0(self):
        row = dim(run(), "lint")
        self.assertEqual((row["level"], row["rule"]), (0, "lint.0"))

    def test_lint_1_configured_not_in_ci(self):
        d = det([sub(cats={"lint": [cfg_row("ruff", "lint")]})])
        row = dim(run(d), "lint")
        self.assertEqual((row["level"], row["rule"], row["partial"]), (1, "lint.1", None))

    def test_lint_1_partial_when_a_language_has_no_linter(self):
        d = det([sub(langs=("python", "typescript"), cats={"lint": [cfg_row("ruff", "lint")]})])
        row = dim(run(d), "lint")
        self.assertEqual(row["partial"], {"covered": 1, "total": 2, "missing": ["typescript"], "unit": "languages"})
        self.assertIn("lint:.:missing-language:typescript", gap_ids(run(d)))

    def test_non_blocking_and_pull_request_false_do_not_count(self):
        for kwargs in ({"nb": True}, {"pr": False}):
            d = det([sub()], rows=[ci_row("ruff", "lint", "python", **kwargs)])
            self.assertEqual(dim(run(d), "lint")["rule"], "lint.1")

    def test_push_default_counts_as_blocking(self):
        d = det([sub()], rows=[ci_row("ruff", "lint", "python", pr="push-default")])
        self.assertEqual(dim(run(d), "lint")["level"], 2)

    def test_lint_2(self):
        d = det([sub()], rows=[ci_row("ruff", "lint", "python")])
        row = dim(run(d), "lint")
        self.assertEqual((row["level"], row["rule"]), (2, "lint.2"))
        self.assertIn("lint:.:lint.2:format-check", gap_ids(run(d)))

    def rows3(self):
        return [ci_row("ruff", "lint", "python"), ci_row("ruff-format", "format", "python", ["ruff format --check"])]

    def test_lint_3_needs_the_tier_1_count(self):
        d = det([sub()], rows=self.rows3(), languages={"python": {"loc": 5000, "test_loc": 0}})
        row = dim(run(d), "lint")
        self.assertEqual((row["level"], row["needs"]), (2, "tier 1 lint count"))
        row = dim(run(d, t1={"counts": {"lint:.": {"errors": 0}}}), "lint")
        self.assertEqual((row["level"], row["rule"], row["needs"]), (3, "lint.3", None))
        row = dim(run(d, t1={"counts": {"lint:.": {"errors": 4}}}), "lint")
        self.assertEqual((row["level"], row["needs"]), (2, None))

    def test_formatter_that_rewrites_is_not_a_check(self):
        rows = [ci_row("ruff", "lint", "python"), ci_row("black", "format", "python", ["black ."], writes=True)]
        d = det([sub()], rows=rows)
        self.assertEqual(dim(run(d, t1={"counts": {"lint:.": {"errors": 0}}}), "lint")["level"], 2)

    def test_many_suppressions_hold_level_3_back(self):
        d = det([sub()], rows=self.rows3(), languages={"python": {"loc": 1000, "test_loc": 0}},
                suppressions={"python": {"total": 5}})
        self.assertEqual(dim(run(d, t1={"counts": {"lint:.": {"errors": 0}}}), "lint")["level"], 2)
        self.assertIn("lint:.:lint.2:suppressions", gap_ids(run(d, t1={"counts": {"lint:.": {"errors": 0}}})))


class Types(unittest.TestCase):
    def test_python_levels(self):
        self.assertEqual(dim(run(), "types")["rule"], "types.0")
        d = det([sub(cats={"types": [cfg_row("mypy", "types")]})])
        self.assertEqual(dim(run(d), "types")["rule"], "types.1")
        d = det([sub()], rows=[ci_row("mypy", "types", "python")])
        self.assertEqual(dim(run(d), "types")["rule"], "types.2")

    def test_types_3_needs_strictness_and_a_zero_count(self):
        strict = [{"kind": "mypy-strict", "how": "config", "file": "pyproject.toml", "line": 3, "subproject": ".",
                   "value": True}]
        d = det([sub()], rows=[ci_row("mypy", "types", "python")], strictness=strict)
        row = dim(run(d), "types")
        self.assertEqual((row["level"], row["needs"]), (2, "tier 1 type-check count"))
        row = dim(run(d, t1={"counts": {"types:.": {"errors": 0}}}), "types")
        self.assertEqual((row["level"], row["rule"]), (3, "types.3"))

    def test_typescript_tsc_config_only_is_level_1(self):
        d = det([sub(langs=("typescript",), cats={"types": [cfg_row("tsc", "types", "tsconfig.json")]})])
        self.assertEqual(dim(run(d), "types")["rule"], "types.1")

    def test_typescript_non_strict_tsconfig_is_not_strict(self):
        strict = [{"kind": "tsconfig-strict", "how": "config", "file": "tsconfig.json", "line": 1, "subproject": ".",
                   "value": False}]
        d = det([sub(langs=("typescript",))], rows=[ci_row("tsc", "types", "typescript")], strictness=strict)
        self.assertEqual(dim(run(d, t1={"counts": {"types:.": {"errors": 0}}}), "types")["rule"], "types.2")

    def test_compiled_languages(self):
        s = sub(langs=("rust",))
        self.assertEqual(dim(run(det([s])), "types")["rule"], "types.1c")
        d = det([s], rows=[ci_row("cargo-test", "tests", "rust", ["cargo test"])])
        self.assertEqual(dim(run(d), "types")["rule"], "types.2c")
        fact = [{"kind": "clippy-deny-warnings", "how": "ci", "file": ".github/workflows/ci.yml", "line": 12,
                 "subproject": "."}]
        d = det([s], rows=[ci_row("cargo-test", "tests", "rust", ["cargo test"])], strictness=fact)
        self.assertEqual(dim(run(d), "types")["rule"], "types.3c")

    def test_go_vet_row_counts_as_3c(self):
        d = det([sub(langs=("go",))], rows=[ci_row("go-vet", "lint", "go", ["go vet ./..."])])
        self.assertEqual(dim(run(d), "types")["rule"], "types.3c")

    def test_mixed_languages_take_the_lower_level(self):
        d = det([sub(langs=("python", "typescript"))], rows=[ci_row("mypy", "types", "python")])
        row = dim(run(d), "types")
        self.assertEqual((row["level"], row["rule"]), (0, "types.0"))
        self.assertEqual(row["partial"]["missing"], ["typescript"])
        self.assertIn("types:.:types.0:typescript", gap_ids(run(d)))


class CiRowsJoinByFolder(unittest.TestCase):
    def two_subs(self):
        return [sub(langs=("typescript",), test_files=0), sub(path="web", langs=("typescript",), loc=100, test_files=0)]

    def types_rule(self, rows, path):
        return dim(run(det(self.two_subs(), rows=rows)), "types", path)["rule"]

    def test_working_directory_puts_the_row_in_the_subproject_that_holds_it(self):
        row = ci_row("tsc", "types", "typescript", ["tsc --noEmit"], dir="web")
        self.assertEqual(self.types_rule([row], "web"), "types.2")
        self.assertEqual(self.types_rule([row], "."), "types.0")

    def test_cd_prefix_flags_and_followed_scripts(self):
        for extra in ({"dir": "web"}, {"commands": ["tsc -p web/tsconfig.json"]}, {"commands": ["npm --prefix web run tc"]},
                      {"commands": ["make -C web tc"]}, {"commands": ["tsc"], "via": "tc", "via_file": "web/package.json"}):
            row = ci_row("tsc", "types", "typescript", **extra)
            self.assertEqual(self.types_rule([row], "web"), "types.2", extra)
            self.assertEqual(self.types_rule([row], "."), "types.0", extra)

    def test_no_known_folder_falls_back_to_language(self):
        row = ci_row("tsc", "types", "typescript", ["tsc --noEmit"])
        self.assertEqual(self.types_rule([row], "web"), "types.2")
        self.assertEqual(self.types_rule([row], "."), "types.2")

    def test_a_folder_inside_the_root_subproject_belongs_to_the_root(self):
        row = ci_row("tsc", "types", "typescript", ["tsc"], dir="tools/x")
        self.assertEqual(self.types_rule([row], "."), "types.2")
        self.assertEqual(self.types_rule([row], "web"), "types.0")

    def test_test_rows_are_scoped_too(self):
        suites = [{"path": "web/tests", "language": "typescript", "files": 1, "loc": 1}]
        subs = [sub(langs=("typescript",), test_files=0), sub(path="web", langs=("typescript",), suites=suites)]
        elsewhere = ci_row("jest", "tests", "typescript", ["jest"], dir="other")
        self.assertEqual(dim(run(det(subs, rows=[elsewhere])), "tests", "web")["rule"], "tests.1")
        here = ci_row("jest", "tests", "typescript", ["jest"], dir="web")
        self.assertEqual(dim(run(det(subs, rows=[here])), "tests", "web")["rule"], "tests.2")


class TestScripts(unittest.TestCase):
    def test_a_script_inside_a_suite_folder_runs_that_suite(self):
        suites = [{"path": "plugins/a/tests", "language": "python", "files": 2, "loc": 10},
                  {"path": "plugins/b/tests", "language": "python", "files": 1, "loc": 5}]
        row = ci_row("test-script", "tests", "shared", ["python plugins/a/tests/run_all.py"],
                     via="plugins/a/tests/run_all.py", via_file="plugins/a/tests/run_all.py")
        d = det([sub(suites=suites)], rows=[row])
        result = run(d, hot([hfile("plugins/a/scripts/x.py"), hfile("plugins/b/scripts/y.py")]))
        self.assertEqual(dim(result, "tests")["partial"]["missing"], ["plugins/b/tests"])
        self.assertNotIn("tests:.:missing-suite:plugins/a/tests", gap_ids(result))
        self.assertEqual([h["tests_in_ci"] for h in result["hotspots"]], [True, False])


class NoTestsAtAll(unittest.TestCase):
    def test_hotspot_no_tests_gap_folds_into_tests_0(self):
        d = det([sub(test_files=0)])
        result = run(d, hot([hfile("a/x.py")]))
        ids = gap_ids(result)
        self.assertIn("tests:.:tests.0", ids)
        self.assertFalse([i for i in ids if i.startswith("hotspots:") and "no-tests" in i])
        gap = [g for g in result["gaps"] if g["id"] == "tests:.:tests.0"][0]
        self.assertEqual(gap["hotspot_files"], ["a/x.py"])
        self.assertEqual(gap["priority"], 20.0)


class JavaScriptOnly(unittest.TestCase):
    def js_only(self, record):
        record["stats"]["typescript"]["ts_files"] = 0
        return record

    def test_javascript_files_do_not_demand_a_type_checker(self):
        mixed = self.js_only(sub(langs=("python", "typescript")))
        d = det([mixed], rows=[ci_row("mypy", "types", "python")])
        row = dim(run(d), "types")
        self.assertEqual((row["level"], row["rule"], row["partial"]), (2, "types.2", None))
        self.assertTrue(any("JavaScript only" in f for f in row["facts"]))
        self.assertFalse([g for g in gap_ids(run(d)) if g.startswith("types:") and "typescript" in g])

    def test_typescript_files_bring_the_rules_back(self):
        d = det([sub(langs=("python", "typescript"))], rows=[ci_row("mypy", "types", "python")])
        row = dim(run(d), "types")
        self.assertEqual((row["level"], row["rule"]), (0, "types.0"))

    def test_a_javascript_only_subproject_is_not_applicable(self):
        row = dim(run(det([self.js_only(sub(langs=("typescript",)))])), "types")
        self.assertEqual((row["status"], row["level"], row["rule"]), ("not_applicable", None, "types.na"))
        self.assertIn("JavaScript only", row["summary"])
        self.assertTrue(any("JavaScript only" in f for f in row["facts"]))

    def test_lint_still_applies_to_javascript(self):
        self.assertEqual(dim(run(det([self.js_only(sub(langs=("typescript",)))])), "lint")["rule"], "lint.0")


class ChineseLists(unittest.TestCase):
    def test_list_items_are_joined_with_the_enumeration_comma(self):
        self.assertEqual(score.zh_summary("Missing: lockfile, toolchain pin."), "缺少：锁文件、工具链版本固定。")
        self.assertEqual(score.zh_summary("No linter for python, typescript."), "没有 python、typescript 的 linter。")


class Static(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(dim(run(), "static")["rule"], "static.0")
        d = det([sub(cats={"static": [cfg_row("bandit", "static")]})])
        self.assertEqual(dim(run(d), "static")["rule"], "static.1")
        d = det(rows=[ci_row("codeql", "static", "shared")])
        row = dim(run(d), "static")
        self.assertEqual((row["rule"], row["status"]), ("static.2", "checked"))
        self.assertTrue(row["needs"])

    def test_github_code_scanning_counts(self):
        g = gh(security_and_analysis={"advanced_security": "enabled"})
        self.assertEqual(dim(run(gh=g), "static")["rule"], "static.2")

    def test_static_3_needs_alert_counts(self):
        g = gh(security_and_analysis={"code_security": "enabled"}, code_scanning_alerts={"high": 0, "critical": 0})
        self.assertEqual(dim(run(gh=g), "static")["rule"], "static.3")
        g["code_scanning_alerts"] = {"high": 2, "critical": 0}
        self.assertEqual(dim(run(gh=g), "static")["rule"], "static.2")


class Secrets(unittest.TestCase):
    def test_unknown_is_not_zero(self):
        row = dim(run(), "secrets")
        self.assertEqual((row["level"], row["status"]), (None, "unknown"))
        self.assertTrue(row["needs"])
        self.assertEqual(dim(run(gh={"available": False, "why": "no gh"}), "secrets")["status"], "unknown")

    def test_zero_when_the_setting_is_visibly_off(self):
        row = dim(run(gh=gh(security_and_analysis={"dependabot_security_updates": "enabled"})), "secrets")
        self.assertEqual((row["level"], row["rule"]), (0, "secrets.0"))

    def test_local_only_then_ci_then_github(self):
        shared = [cfg_row("gitleaks", "secrets", ".gitleaks.toml")]
        self.assertEqual(dim(run(det(shared=shared)), "secrets")["rule"], "secrets.1")
        d = det(rows=[ci_row("gitleaks", "secrets", "shared")])
        self.assertEqual(dim(run(d), "secrets")["rule"], "secrets.2")
        on = {"secret_scanning": "enabled", "secret_scanning_push_protection": "enabled"}
        self.assertEqual(dim(run(gh=gh(security_and_analysis=on)), "secrets")["rule"], "secrets.2g")
        self.assertEqual(dim(run(d, gh=gh(security_and_analysis=on)), "secrets")["rule"], "secrets.3")


class Tests(unittest.TestCase):
    def test_tests_0(self):
        row = dim(run(det([sub(test_files=0)])), "tests")
        self.assertEqual((row["level"], row["rule"]), (0, "tests.0"))

    def test_tests_1_without_a_blocking_row(self):
        row = dim(run(), "tests")
        self.assertEqual((row["level"], row["rule"]), (1, "tests.1"))
        d = det(rows=[ci_row("pytest", "tests", "python", ["pytest"], nb=True)])
        self.assertEqual(dim(run(d), "tests")["rule"], "tests.1")

    def two_suites(self, command):
        suites = [{"path": "a/tests", "language": "python", "files": 2, "loc": 10},
                  {"path": "b/tests", "language": "python", "files": 1, "loc": 5}]
        return det([sub(suites=suites)], rows=[ci_row("pytest", "tests", "python", [command])])

    def test_tests_1p_lists_the_missing_suite_hottest_first(self):
        d = det([sub(suites=[{"path": "a/tests", "language": "python", "files": 1, "loc": 1},
                             {"path": "b/tests", "language": "python", "files": 1, "loc": 1},
                             {"path": "c/tests", "language": "python", "files": 1, "loc": 1}])],
                rows=[ci_row("pytest", "tests", "python", ["pytest a/tests"])])
        result = run(d, hot([hfile("c/x.py", score_=0.9), hfile("b/y.py", score_=0.2)]))
        row = dim(result, "tests")
        self.assertEqual((row["level"], row["rule"]), (1, "tests.1p"))
        self.assertEqual(row["partial"], {"covered": 1, "total": 3, "missing": ["c/tests", "b/tests"],
                                          "unit": "test suites"})
        self.assertEqual(row["summary"], "CI runs 1 of 3 test suites.")
        self.assertIn("tests:.:missing-suite:c/tests", gap_ids(result))

    def test_whole_project_command_covers_every_suite(self):
        d = self.two_suites("pytest")
        self.assertEqual(dim(run(d), "tests")["rule"], "tests.2")

    def test_path_names_a_folder_above_or_a_file_inside(self):
        self.assertEqual(dim(run(self.two_suites("pytest a b")), "tests")["rule"], "tests.2")
        self.assertEqual(dim(run(self.two_suites("pytest a/tests/test_x.py b/tests")), "tests")["rule"], "tests.2")
        self.assertEqual(dim(run(self.two_suites("python -m unittest discover -s a/tests")), "tests")["rule"],
                         "tests.1p")

    def test_flag_values_are_not_paths(self):
        self.assertEqual(dim(run(self.two_suites("pytest -q -p no:cacheprovider --backend=x")), "tests")["rule"],
                         "tests.2")

    def test_variable_path_is_unknown_not_covered(self):
        result = run(self.two_suites("pytest $DIR"))
        self.assertEqual(dim(result, "tests")["rule"], "tests.1")
        self.assertEqual(result["hotspots"], [])
        result = run(self.two_suites("pytest $DIR"), hot([hfile("a/x.py")]))
        self.assertEqual(result["hotspots"][0]["tests_in_ci"], "unknown")

    def test_followed_npm_script_runs_from_its_package(self):
        suites = [{"path": "web/tests", "language": "typescript", "files": 1, "loc": 1},
                  {"path": "api/tests", "language": "typescript", "files": 1, "loc": 1}]
        row = ci_row("jest", "tests", "typescript", ["jest"], via="test", via_file="web/package.json", via_line=3)
        d = det([sub(langs=("typescript",), suites=suites)], rows=[row])
        self.assertEqual(dim(run(d), "tests")["partial"]["missing"], ["api/tests"])

    def test_cargo_package_flag_names_a_member(self):
        suites = [{"path": "crates/a/tests", "language": "rust", "files": 1, "loc": 1},
                  {"path": "crates/b/tests", "language": "rust", "files": 1, "loc": 1}]
        d = det([sub(langs=("rust",), suites=suites)],
                rows=[ci_row("cargo-test", "tests", "rust", ["cargo test -p a"])])
        self.assertEqual(dim(run(d), "tests")["partial"]["missing"], ["crates/b/tests"])
        d = det([sub(langs=("rust",), suites=suites)],
                rows=[ci_row("cargo-test", "tests", "rust", ["cargo test --workspace"])])
        self.assertEqual(dim(run(d), "tests")["rule"], "tests.2")

    def test_jvm_framework_rows_count_only_for_the_subprojects_languages(self):
        kotest = ci_row("kotest", "tests", "kotlin", ["mvn -B verify"])
        junit = ci_row("junit", "tests", "java", ["mvn -B verify"])
        java = sub(langs=("java",))
        self.assertEqual(dim(run(det([java], rows=[kotest])), "tests")["rule"], "tests.1")
        self.assertEqual(dim(run(det([java], rows=[kotest, junit])), "tests")["rule"], "tests.2")

    def test_tests_3_from_run_history(self):
        d = det(rows=[ci_row("pytest", "tests", "python", ["pytest"])])
        self.assertEqual((dim(run(d, gh=gh()), "tests")["level"], dim(run(d, gh=gh()), "tests")["rule"]),
                         (3, "tests.3"))
        bad = gh()
        bad["runs"]["overall"]["pass_rate"] = 0.7
        row = dim(run(d, gh=bad), "tests")
        self.assertEqual((row["level"], row["needs"]), (2, None))
        few = gh()
        few["runs"]["overall"]["completed"] = 3
        self.assertEqual(dim(run(d, gh=few), "tests")["needs"], "ghfacts run history or a tier 1 test run")

    def test_tests_2_needs_history_or_a_run(self):
        d = det(rows=[ci_row("pytest", "tests", "python", ["pytest"])])
        row = dim(run(d), "tests")
        self.assertEqual((row["level"], row["rule"], row["needs"] is not None), (2, "tests.2", True))
        fast = {"suite_runs": [{"subproject": ".", "passed": True, "duration_s": 90}]}
        self.assertEqual(dim(run(d, t1=fast), "tests")["level"], 3)
        slow = {"suite_runs": [{"subproject": ".", "passed": True, "duration_s": 900}]}
        self.assertEqual(dim(run(d, t1=slow), "tests")["level"], 2)


class Coverage(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(dim(run(), "coverage")["rule"], "coverage.0")
        d = det([sub(cats={"coverage": [cfg_row("coverage.py", "coverage", ".coveragerc")]})])
        self.assertEqual(dim(run(d), "coverage")["rule"], "coverage.1")
        rows = [ci_row("coverage.py", "coverage", "python", ["pytest --cov"])]
        self.assertEqual(dim(run(det(rows=rows)), "coverage")["rule"], "coverage.2")
        fact = [{"kind": "fail_under", "how": "config", "file": "pyproject.toml", "line": 4, "subproject": ".",
                 "value": "80"}]
        self.assertEqual(dim(run(det(rows=rows, coverage_thresholds=fact)), "coverage")["rule"], "coverage.3")

    def test_threshold_in_a_ci_command_counts_as_measured(self):
        fact = [{"kind": "cov-fail-under", "how": "ci", "file": ".github/workflows/ci.yml", "line": 9,
                 "subproject": ".", "value": "80"}]
        self.assertEqual(dim(run(det(coverage_thresholds=fact)), "coverage")["rule"], "coverage.3")

    def test_not_applicable_without_tests(self):
        row = dim(run(det([sub(test_files=0)])), "coverage")
        self.assertEqual((row["status"], row["level"]), ("not_applicable", None))


class CI(unittest.TestCase):
    def good_rows(self):
        return [ci_row("pytest", "tests", "python", ["pytest"]), ci_row("ruff", "lint", "python"),
                ci_row("ruff-format", "format", "python", ["ruff format --check"])]

    def test_ci_0_and_1(self):
        self.assertEqual(dim(run(det(ci=False)), "ci")["rule"], "ci.0")
        self.assertEqual(dim(run(det(pr=False, rows=self.good_rows())), "ci")["rule"], "ci.1")

    def test_ci_1_when_pull_requests_do_not_run_tests(self):
        d = det(rows=[ci_row("ruff", "lint", "python")])
        self.assertEqual(dim(run(d), "ci")["rule"], "ci.1")

    def test_ci_2_when_lint_is_missing(self):
        d = det(rows=[ci_row("pytest", "tests", "python", ["pytest"])])
        self.assertEqual(dim(run(d), "ci")["rule"], "ci.2")

    def test_ci_3a_with_required_checks(self):
        g = gh(branch_protection={"state": "protected", "required_status_checks": ["test"]})
        row = dim(run(det(rows=self.good_rows()), gh=g), "ci")
        self.assertEqual((row["level"], row["rule"]), (3, "ci.3a"))

    def test_protection_not_visible_keeps_level_2_with_needs(self):
        g = gh(branch_protection={"state": "not_visible", "required_status_checks": []})
        row = dim(run(det(rows=self.good_rows()), gh=g), "ci")
        self.assertEqual((row["level"], row["rule"]), (2, "ci.2"))
        self.assertTrue(row["needs"])
        self.assertEqual(dim(run(det(rows=self.good_rows())), "ci")["level"], 2)

    def test_ci_3s_for_a_solo_repository_with_a_green_main(self):
        row = dim(run(det(rows=self.good_rows()), hot(authors=1), gh=gh()), "ci")
        self.assertEqual((row["level"], row["rule"]), (3, "ci.3s"))
        row = dim(run(det(rows=self.good_rows()), hot(authors=4), gh=gh()), "ci")
        self.assertEqual((row["level"], row["needs"]), (2, None))

    def test_red_main_is_a_gap_and_reviews_are_not_applicable_when_solo(self):
        bad = gh()
        bad["runs"]["overall"]["pass_rate"] = 0.6
        result = run(det(rows=self.good_rows()), hot(authors=1), gh=bad)
        self.assertIn("ci:.:red-main", gap_ids(result))
        self.assertIn("ci:.:required-reviews", [n["id"] for n in result["not_applicable"]])
        self.assertTrue(result["ci_health"]["available"])
        self.assertFalse(run()["ci_health"]["available"])


class Setup(unittest.TestCase):
    def app(self, **kw):
        record = sub(manifest="pyproject.toml", manifests=[{"file": "pyproject.toml", "parse_error": None}], **kw)
        return record

    def test_levels_for_an_application(self):
        self.assertEqual(dim(run(det([self.app()])), "setup")["rule"], "setup.0")
        setup = {"lockfiles": [{"file": "uv.lock", "ecosystem": "python", "subproject": ".", "last_commit": None}],
                 "toolchain_pins": [], "task_runners": [], "devcontainer": [], "dockerfiles": [], "compose": [],
                 "update_bots": [], "requirements_files": []}
        row = dim(run(det([self.app()], setup=setup)), "setup")
        self.assertEqual((row["level"], row["rule"]), (1, "setup.1"))
        setup["toolchain_pins"] = [{"kind": ".python-version", "file": ".python-version", "line": 1,
                                    "subproject": "."}]
        setup["task_runners"] = [{"kind": "make", "file": "Makefile", "targets": [], "subproject": "."}]
        self.assertEqual(dim(run(det([self.app()], setup=setup)), "setup")["rule"], "setup.2")
        d = det([self.app()], setup=setup)
        d["ci"]["locked_installs"] = [{"kind": "uv sync --locked", "file": "x", "line": 1, "command": "uv sync"}]
        self.assertEqual(dim(run(d), "setup")["rule"], "setup.3")

    def test_devcontainer_gives_level_3(self):
        setup = {"lockfiles": [{"file": "uv.lock", "ecosystem": "python", "subproject": ".", "last_commit": None}],
                 "toolchain_pins": [{"kind": "x", "file": ".nvmrc", "line": 1, "subproject": "."}],
                 "task_runners": [{"kind": "make", "file": "Makefile", "targets": [], "subproject": "."}],
                 "devcontainer": [".devcontainer.json"], "dockerfiles": [], "compose": [], "update_bots": [],
                 "requirements_files": []}
        self.assertEqual(dim(run(det([self.app()], setup=setup)), "setup")["level"], 3)

    def test_a_library_needs_no_lockfile(self):
        lib = self.app(publishable={"kind": "pypi", "file": "pyproject.toml"})
        setup = {"lockfiles": [], "toolchain_pins": [{"kind": "x", "file": ".python-version", "line": 1,
                                                       "subproject": "."}],
                 "task_runners": [{"kind": "make", "file": "Makefile", "targets": [], "subproject": "."}],
                 "devcontainer": [], "dockerfiles": [], "compose": [], "update_bots": [], "requirements_files": []}
        result = run(det([lib], setup=setup))
        self.assertEqual(dim(result, "setup")["rule"], "setup.2")
        self.assertEqual(result["profile"]["kind"], "library")
        self.assertIn("setup:.:lockfile", [n["id"] for n in result["not_applicable"]])

    def test_fixture_runners_do_not_count(self):
        setup = {"lockfiles": [], "toolchain_pins": [], "devcontainer": [], "dockerfiles": [], "compose": [],
                 "update_bots": [], "requirements_files": [],
                 "task_runners": [{"kind": "tox", "file": "tests/fixtures/tox.ini", "targets": [], "subproject": "."}]}
        self.assertEqual(dim(run(det(setup=setup)), "setup")["rule"], "setup.0")

    def test_readme_command_is_a_task_entry(self):
        docs = det()["docs"]
        docs["commands"] = [{"command": "make test", "kind": "test", "check": "ok", "why": "", "line": 3}]
        self.assertEqual(dim(run(det(docs=docs)), "setup")["level"], 1)


class Deps(unittest.TestCase):
    def setup_with(self, **kw):
        setup = {"lockfiles": [], "toolchain_pins": [], "task_runners": [], "devcontainer": [], "dockerfiles": [],
                 "compose": [], "update_bots": [], "requirements_files": ["requirements.txt"]}
        setup.update(kw)
        return setup

    def test_not_applicable_when_nothing_depends_on_anything(self):
        d = det(ci=False)
        row = dim(run(d), "deps")
        self.assertEqual((row["status"], row["rule"]), ("not_applicable", "deps.na"))

    def test_deps_0_and_1(self):
        self.assertEqual(dim(run(det(setup=self.setup_with())), "deps")["rule"], "deps.0")
        lock = [{"file": "uv.lock", "ecosystem": "python", "subproject": ".", "last_commit": None}]
        self.assertEqual(dim(run(det(setup=self.setup_with(lockfiles=lock))), "deps")["rule"], "deps.1")

    def test_deps_1p_when_the_bot_misses_an_ecosystem(self):
        bots = [{"tool": "dependabot", "file": ".github/dependabot.yml", "line": 3, "ecosystems": ["python"]}]
        result = run(det(setup=self.setup_with(update_bots=bots)))
        row = dim(result, "deps")
        self.assertEqual((row["rule"], row["partial"]["missing"]), ("deps.1p", ["actions"]))
        self.assertIn("deps:.:missing-ecosystem:actions", gap_ids(result))

    def test_deps_2_by_bot_or_audit(self):
        bots = [{"tool": "dependabot", "file": "d.yml", "line": 3, "ecosystems": ["python", "actions"]}]
        self.assertEqual(dim(run(det(setup=self.setup_with(update_bots=bots))), "deps")["rule"], "deps.2")
        renovate = [{"tool": "renovate", "file": "renovate.json", "line": 1, "ecosystems": ["*"]}]
        self.assertEqual(dim(run(det(setup=self.setup_with(update_bots=renovate))), "deps")["level"], 2)
        d = det(rows=[ci_row("pip-audit", "deps_audit", "python")], setup=self.setup_with())
        self.assertEqual(dim(run(d), "deps")["rule"], "deps.2")

    def test_deps_3_needs_fresh_lockfiles_or_an_audit(self):
        bots = [{"tool": "renovate", "file": "renovate.json", "line": 1, "ecosystems": ["*"]}]
        fresh = [{"file": "uv.lock", "ecosystem": "python", "subproject": ".", "last_commit": "2026-10-20T10:00:00Z"}]
        self.assertEqual(dim(run(det(setup=self.setup_with(update_bots=bots, lockfiles=fresh))), "deps")["level"], 3)
        old = [{"file": "uv.lock", "ecosystem": "python", "subproject": ".", "last_commit": "2026-01-20T10:00:00Z"}]
        row = dim(run(det(setup=self.setup_with(update_bots=bots, lockfiles=old))), "deps")
        self.assertEqual((row["level"], row["needs"]), (2, None))
        row = dim(run(det(setup=self.setup_with(update_bots=bots))), "deps")
        self.assertTrue(row["needs"])
        audit = {"audits": [{"subproject": ".", "high": 0, "critical": 0}]}
        self.assertEqual(dim(run(det(setup=self.setup_with(update_bots=bots, lockfiles=old)), t1=audit),
                             "deps")["level"], 3)
        dirty = {"audits": [{"subproject": ".", "high": 1, "critical": 0}]}
        self.assertEqual(dim(run(det(setup=self.setup_with(update_bots=bots, lockfiles=old)), t1=dirty),
                             "deps")["level"], 2)


class Docs(unittest.TestCase):
    def docs(self, **kw):
        base = {"readme": "README.md", "headings": [], "commands": [], "install": {"found": True},
                "run": {"found": True}, "test": {"found": True}, "contributing": None}
        base.update(kw)
        return base

    def test_docs_0(self):
        self.assertEqual(dim(run(det(docs=self.docs(readme=None))), "docs")["rule"], "docs.0")

    def test_docs_1_for_missing_commands_and_wrong_ones(self):
        row = dim(run(det(docs=self.docs(test={"found": False}))), "docs")
        self.assertEqual(row["rule"], "docs.1")
        wrong = [{"command": "make lint", "kind": "lint", "check": "missing", "why": "no target lint", "line": 7}]
        result = run(det(docs=self.docs(commands=wrong)))
        self.assertIn("docs:.:wrong-command:make-lint", gap_ids(result))
        self.assertEqual(dim(result, "docs")["summary"], "1 README commands do not exist.")

    def test_wrong_command_ranks_above_a_missing_one(self):
        wrong = [{"command": "make lint", "kind": "lint", "check": "missing", "why": "no target", "line": 7}]
        result = run(det(docs=self.docs(commands=wrong, test={"found": False})))
        self.assertEqual([g for g in gap_ids(result) if g.startswith("docs:")],
                         ["docs:.:wrong-command:make-lint", "docs:.:docs.1"])

    def test_docs_2_and_3(self):
        self.assertEqual(dim(run(det(docs=self.docs())), "docs")["rule"], "docs.2")
        lint = [{"command": "ruff check .", "kind": "lint", "check": "ok", "why": "", "line": 5}]
        row = dim(run(det(docs=self.docs(commands=lint, contributing="CONTRIBUTING.md"))), "docs")
        self.assertEqual((row["level"], row["rule"]), (3, "docs.3"))
        heads = [{"level": 2, "text": "Development", "line": 9}]
        self.assertEqual(dim(run(det(docs=self.docs(commands=lint, headings=heads))), "docs")["level"], 3)


class Arch(unittest.TestCase):
    def big(self, **kw):
        return sub(**kw)

    def test_not_applicable_for_scripts_and_small_subprojects(self):
        row = dim(run(det([sub(direct=0)])), "arch")
        self.assertEqual((row["status"], row["rule"], row["level"]), ("not_applicable", "arch.na", None))
        self.assertIn("Scripts", row["summary"])
        row = dim(run(det([sub(loc=2999)])), "arch")
        self.assertEqual(row["rule"], "arch.na")
        self.assertIn("3,000", row["summary"])

    def test_arch_0(self):
        row = dim(run(det([self.big()])), "arch")
        self.assertEqual((row["level"], row["rule"]), (0, "arch.0"))

    def test_arch_1_with_a_doc_and_with_an_unenforced_tool(self):
        doc = [{"kind": "architecture", "path": "ARCHITECTURE.md", "last_commit": "2020-01-01T00:00:00Z"}]
        result = run(det([self.big()], architecture_docs=doc))
        self.assertEqual(dim(result, "arch")["rule"], "arch.1")
        self.assertIn("arch:.:arch.1:rules", gap_ids(result))
        cfg = {"arch": [cfg_row("import-linter", "arch", ".importlinter")]}
        result = run(det([self.big(cats=cfg)]))
        self.assertEqual(dim(result, "arch")["rule"], "arch.1")
        gap = [g for g in result["gaps"] if g["id"] == "arch:.:arch.1:enforce"][0]
        self.assertEqual((gap["effort"], gap["priority"]), ("enforce", 4.5))

    def test_arch_2_cli_tool_needs_its_own_blocking_row(self):
        cfg = {"arch": [cfg_row("import-linter", "arch", ".importlinter")]}
        d = det([self.big(cats=cfg)], rows=[ci_row("import-linter", "arch", "python", ["lint-imports"])])
        row = dim(run(d), "arch")
        self.assertEqual((row["level"], row["rule"]), (2, "arch.2"))
        d = det([self.big(cats=cfg)], rows=[ci_row("import-linter", "arch", "python", ["lint-imports"], nb=True)])
        self.assertEqual(dim(run(d), "arch")["level"], 1)

    def test_arch_2_in_test_tool_counts_when_ci_runs_the_suite(self):
        cfg = {"arch": [cfg_row("pytestarch", "arch", "pyproject.toml", rides_on="tests")]}
        self.assertEqual(dim(run(det([self.big(cats=cfg)])), "arch")["level"], 1)
        d = det([self.big(cats=cfg)], rows=[ci_row("pytest", "tests", "python", ["pytest"])])
        self.assertEqual(dim(run(d), "arch")["rule"], "arch.2")

    def test_arch_2_linter_plugin_needs_its_host_blocking(self):
        cfg = {"arch": [cfg_row("eslint-plugin-boundaries", "arch", "eslint.config.js", rides_on="eslint")]}
        s = self.big(langs=("typescript",), cats=cfg)
        self.assertEqual(dim(run(det([s])), "arch")["level"], 1)
        d = det([s], rows=[ci_row("eslint", "lint", "typescript")])
        self.assertEqual(dim(run(d), "arch")["rule"], "arch.2")

    def test_rust_workspace_counts(self):
        members = [sub(path="crates/a", langs=("rust",)), sub(path="crates/b", langs=("rust",))]
        ws = self.big(langs=("rust",), members=members, workspace={"kind": "cargo", "manifest": "Cargo.toml"})
        self.assertEqual(dim(run(det([ws])), "arch")["rule"], "arch.2")
        single = self.big(langs=("rust",), members=members[:1], workspace={"kind": "cargo", "manifest": "Cargo.toml"})
        self.assertEqual(dim(run(det([single])), "arch")["level"], 0)

    def test_arch_3_needs_a_recent_doc(self):
        cfg = {"arch": [cfg_row("tach", "arch", "tach.toml")]}
        rows = [ci_row("tach", "arch", "python", ["tach check"])]
        fresh = [{"kind": "architecture", "path": "ARCHITECTURE.md", "last_commit": "2026-06-01T00:00:00Z"}]
        stale = [{"kind": "architecture", "path": "ARCHITECTURE.md", "last_commit": "2024-06-01T00:00:00Z"}]
        self.assertEqual(dim(run(det([self.big(cats=cfg)], rows=rows, architecture_docs=fresh)), "arch")["rule"],
                         "arch.3")
        result = run(det([self.big(cats=cfg)], rows=rows, architecture_docs=stale))
        self.assertEqual(dim(result, "arch")["rule"], "arch.2")
        self.assertIn("arch:.:arch.2", gap_ids(result))


class Profile(unittest.TestCase):
    def test_authors_and_visibility(self):
        self.assertEqual(run(hotspots=hot(authors=1))["profile"]["authors"], "solo")
        self.assertEqual(run(hotspots=hot(authors=2))["profile"]["authors"], "team")
        self.assertEqual(run(hotspots=hot(authors=None))["profile"]["authors"], "team")
        self.assertEqual(run(gh=gh(visibility="private"))["profile"]["visibility"], "private")
        self.assertEqual(run(gh=gh(visibility="internal"))["profile"]["visibility"], "private")
        self.assertEqual(run()["profile"]["visibility"], "unknown")

    def test_kind(self):
        self.assertEqual(run(det([sub(direct=2)]))["profile"]["kind"], "application")
        self.assertEqual(run(det([sub(direct=0)]))["profile"]["kind"], "scripts")
        lib = sub(publishable={"kind": "npm", "file": "package.json"})
        self.assertEqual(run(det([lib]))["profile"]["kind"], "library")
        docker = det([lib], setup={"lockfiles": [], "toolchain_pins": [], "task_runners": [], "devcontainer": [],
                                   "dockerfiles": ["Dockerfile"], "compose": [], "update_bots": [],
                                   "requirements_files": []})
        self.assertEqual(run(docker)["profile"]["kind"], "application")


class Priority(unittest.TestCase):
    def gap(self, result, gap_id):
        return [g for g in result["gaps"] if g["id"] == gap_id][0]

    def test_weight_times_factors(self):
        result = run(det([sub(test_files=0)]))
        self.assertEqual(self.gap(result, "lint:.:lint.0")["priority"], 7.0)
        self.assertEqual(self.gap(result, "tests:.:tests.0")["priority"], 10.0)

    def test_hotspot_factor(self):
        files = [hfile("a/x.py")] + [hfile("a/y%d.py" % i, score_=0.5) for i in range(5)] + [hfile("a/z.py", score_=0.1)]
        result = run(det([sub(test_files=0)]), hot(files))
        self.assertEqual(self.gap(result, "lint:.:lint.0")["priority"], 14.0)
        self.assertEqual(self.gap(result, "lint:.:lint.0")["hotspot_files"][0], "a/x.py")

    def test_hotspot_outside_the_top_5_is_worth_1_5(self):
        files = [hfile("q/%d.go" % i, "go") for i in range(5)] + [hfile("a/z.py")]
        result = run(det([sub(test_files=0)]), hot(files))
        self.assertEqual(self.gap(result, "lint:.:lint.0")["priority"], 10.5)

    def test_enforce_factor(self):
        d = det([sub(cats={"lint": [cfg_row("ruff", "lint")]})])
        self.assertEqual(self.gap(run(d), "lint:.:lint.1:python")["priority"], 10.5)

    def test_secrets_weight_depends_on_visibility(self):
        private = run(gh=gh(visibility="private", security_and_analysis={"x": "y"}))
        public = run(gh=gh(visibility="public", security_and_analysis={"x": "y"}))
        self.assertEqual(self.gap(private, "secrets:.:secrets.0")["priority"], 3.0)
        self.assertEqual(self.gap(public, "secrets:.:secrets.0")["priority"], 6.0)

    def test_profile_zero_moves_the_gap_to_not_applicable(self):
        result = run(det([sub()]), hot(authors=1), gh=gh())
        self.assertNotIn("ci:.:required-reviews", gap_ids(result))
        self.assertIn("ci:.:required-reviews", [n["id"] for n in result["not_applicable"]])

    def test_order_is_priority_then_dimension_then_id(self):
        result = run(det([sub(test_files=0)]))
        keys = [(-g["priority"], score.DIMENSION_ORDER.index(g["dimension"]), g["id"]) for g in result["gaps"]]
        self.assertEqual(keys, sorted(keys))

    def test_hotspot_gaps(self):
        files = [hfile("a/x.py", share=0.95), hfile("a/y.py", share=0.2)]
        d = det([sub(suites=[{"path": "b/tests", "language": "python", "files": 1, "loc": 1}])],
                rows=[ci_row("pytest", "tests", "python", ["pytest"])])
        result = run(d, hot(files, authors=3))
        self.assertIn("hotspots:.:no-tests:a/x.py", gap_ids(result))
        self.assertIn("hotspots:.:single-author:a/x.py", gap_ids(result))
        self.assertNotIn("hotspots:.:single-author:a/y.py", gap_ids(result))
        solo = run(d, hot(files, authors=1))
        self.assertNotIn("hotspots:.:single-author:a/x.py", gap_ids(solo))

    def test_hotspot_table_joins_guardrails(self):
        suites = [{"path": "a/tests", "language": "python", "files": 1, "loc": 1}]
        d = det([sub(suites=suites)], rows=[ci_row("pytest", "tests", "python", ["pytest a/tests"]),
                                            ci_row("ruff", "lint", "python")],
                suppressions={"python": {"total": 3, "top_files": [{"file": "a/x.py", "count": 3}]}})
        table = run(d, hot([hfile("a/x.py"), hfile("b/y.py")]))["hotspots"]
        self.assertEqual((table[0]["tests_in_ci"], table[0]["suppressions"], table[0]["linted_in_ci"]),
                         (True, 3, True))
        self.assertEqual((table[1]["tests_in_ci"], table[1]["suppressions"]), (False, None))


class Decisions(unittest.TestCase):
    def base(self):
        return det([sub(test_files=0)])

    def test_dismissed_leaves_the_ranking(self):
        decisions = {"lint:.:lint.0": {"status": "dismissed", "reason": "vendored", "date": "2026-11-01"}}
        result = run(self.base(), decisions=decisions)
        self.assertNotIn("lint:.:lint.0", gap_ids(result))
        self.assertEqual(result["dismissed"][0]["reason"], "vendored")

    def test_later_halves_the_priority(self):
        result = run(self.base(), decisions={"lint:.:lint.0": {"status": "later", "reason": "x", "date": "d"}})
        gap = [g for g in result["gaps"] if g["id"] == "lint:.:lint.0"][0]
        self.assertEqual(gap["priority"], 3.5)
        self.assertEqual(result["deferred"], ["lint:.:lint.0"])

    def test_done_but_detected_is_a_regression(self):
        result = run(self.base(), decisions={"lint:.:lint.0": {"status": "done", "reason": "r", "date": "d"},
                                             "gone:.:x": {"status": "done", "reason": "r", "date": "d"}})
        self.assertEqual([r["id"] for r in result["regressed"]], ["lint:.:lint.0"])
        self.assertIn("lint:.:lint.0", gap_ids(result))


class Changes(unittest.TestCase):
    def test_dimension_changes_and_gap_churn(self):
        before = run(det([sub(test_files=0)]))
        d = det([sub(test_files=0, cats={"lint": [cfg_row("ruff", "lint")]})], rows=[ci_row("mypy", "types", "python")])
        after = run(d, previous=before, compared_with="score-old.json")
        changes = after["changes"]
        by = {(c["id"], c["subproject"]): c["change"] for c in changes["dimensions"]}
        self.assertEqual(by[("lint", ".")], "up")
        self.assertEqual(by[("types", ".")], "up")
        self.assertEqual(by[("setup", ".")], "same")
        self.assertEqual(changes["compared_with"], "score-old.json")
        self.assertIn("lint:.:lint.0", [g["id"] for g in changes["gaps"]["closed"]])
        self.assertIn("lint:.:lint.1:python", changes["gaps"]["new"])
        self.assertIn("tests:.:tests.0", changes["gaps"]["still_open"])

    def test_down_new_and_changed(self):
        good = run(det(rows=[ci_row("ruff", "lint", "python")]))
        worse = run(det(), previous=good)
        self.assertEqual({(c["id"]): c["change"] for c in worse["changes"]["dimensions"]}["lint"], "down")
        old = {"dimensions": [r for r in good["dimensions"] if r["id"] != "ci"], "gaps": [], "dismissed": []}
        self.assertIn(("ci", "new"), [(c["id"], c["change"]) for c in changes_of(good, old)])
        unknown_then = run(det())
        unknown_then["dimensions"] = [dict(r) for r in unknown_then["dimensions"]]
        row = [r for r in unknown_then["dimensions"] if r["id"] == "secrets"][0]
        old_row = dict(row, summary="Other text.")
        old = {"dimensions": [old_row], "gaps": [], "dismissed": []}
        got = {c["id"]: c["change"] for c in changes_of(unknown_then, old)}
        self.assertEqual(got["secrets"], "changed")

    def test_dismissed_gap_is_not_closed(self):
        before = run(det([sub(test_files=0)]))
        decisions = {"lint:.:lint.0": {"status": "dismissed", "reason": "x", "date": "d"}}
        after = run(det([sub(test_files=0)]), decisions=decisions, previous=before)
        self.assertNotIn("lint:.:lint.0", [g["id"] for g in after["changes"]["gaps"]["closed"]])


def changes_of(current, previous):
    return score.changes_between(current, previous)["dimensions"]


class Output(unittest.TestCase):
    def test_summaries_are_short(self):
        result = run(det([sub(langs=("python", "typescript"))]), hot([hfile("a.py")]))
        for row in result["dimensions"]:
            self.assertLessEqual(len(row["summary"].split()), 15, row["summary"])

    def test_same_inputs_give_the_same_bytes(self):
        args = (det([sub(langs=("python", "typescript"))], rows=[ci_row("pytest", "tests", "python", ["pytest"])]),
                hot([hfile("a.py"), hfile("b.py", share=0.95)]), gh())
        first = json.dumps(score.build(*args, now=NOW), sort_keys=True, indent=2)
        second = json.dumps(score.build(*args, now=NOW), sort_keys=True, indent=2)
        self.assertEqual(first, second)

    def test_ghfacts_unavailable_equals_none(self):
        a = json.dumps(run(gh={"available": False, "why": "x"}), sort_keys=True)
        b = json.dumps(run(gh=None), sort_keys=True)
        self.assertEqual(a, b)

    def test_row_shape(self):
        for row in run()["dimensions"]:
            self.assertEqual(sorted(row), ["facts", "id", "level", "needs", "partial", "rule", "status", "subproject",
                                           "summary", "summary_zh"])
        for gap in run()["gaps"]:
            self.assertEqual(sorted(gap), ["dimension", "effort", "facts", "hotspot_files", "id", "priority", "rule",
                                           "subproject", "what"])


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="rh-score-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, data):
        with open(self.path(name), "w") as handle:
            json.dump(data, handle)

    def call(self, *args):
        return subprocess.run([sys.executable, SCRIPT] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, cwd=self.dir)

    def test_cli_output_is_byte_identical_and_reads_decisions(self):
        data = det()
        data["repo"] = self.dir
        self.write("d.json", data)
        self.write("h.json", hot([hfile("a.py")]))
        outs = []
        for name in ("one.json", "two.json"):
            done = self.call("--detect", self.path("d.json"), "--hotspots", self.path("h.json"), "--now",
                             "2026-11-10", "-o", self.path(name))
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(self.path(name), "rb") as handle:
                outs.append(handle.read())
        self.assertEqual(outs[0], outs[1])
        gap_id = json.loads(outs[0])["gaps"][0]["id"]
        done = self.call("decide", gap_id, "--dismiss", "--reason", "not for us", "--date", "2026-11-10")
        self.assertEqual(done.returncode, 0, done.stderr)
        done = self.call("--detect", self.path("d.json"), "--hotspots", self.path("h.json"), "--now", "2026-11-10",
                         "-o", self.path("three.json"))
        with open(self.path("three.json")) as handle:
            result = json.load(handle)
        self.assertNotIn(gap_id, gap_ids(result))
        self.assertEqual(result["dismissed"][0]["id"], gap_id)

    def test_decide_creates_and_edits_the_file_keeping_other_entries(self):
        target = os.path.join(self.dir, "sub", "decisions.json")
        self.assertEqual(self.call("decide", "b:.:x", "--later", "--reason", "q3", "--file", target,
                                   "--date", "2026-01-02").returncode, 0)
        self.assertEqual(self.call("decide", "a:.:y", "--done", "--reason", "merged", "--file", target,
                                   "--date", "2026-01-03").returncode, 0)
        self.assertEqual(self.call("decide", "b:.:x", "--dismiss", "--reason", "no", "--file", target,
                                   "--date", "2026-01-04").returncode, 0)
        with open(target) as handle:
            text = handle.read()
        data = json.loads(text)
        self.assertEqual(list(data), ["a:.:y", "b:.:x"])
        self.assertEqual(data["b:.:x"], {"status": "dismissed", "reason": "no", "date": "2026-01-04"})
        self.assertEqual(data["a:.:y"]["status"], "done")

    def test_decide_needs_exactly_one_status_and_a_reason(self):
        self.assertNotEqual(self.call("decide", "x", "--reason", "r").returncode, 0)
        self.assertNotEqual(self.call("decide", "x", "--dismiss").returncode, 0)

    def test_help_documents_the_decisions_file(self):
        out = self.call("--help").stdout
        self.assertIn("decisions.json", out)
        self.assertIn("dismissed", out)

    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))


if __name__ == "__main__":
    unittest.main()
