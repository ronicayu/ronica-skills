"""Tests for scripts/ghfacts.py with a fake `gh` on PATH that prints canned answers.

Run: python -m unittest discover -s plugins/repo-health/tests
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "repo-health", "scripts")
SCRIPT = os.path.join(SCRIPTS, "ghfacts.py")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("repo_health_ghfacts", SCRIPT)
ghfacts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ghfacts)

FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_GH_DIR/log"
printf '%s|%s|%s\\n' "$(pwd -P)" "$GH_PROMPT_DISABLED" "$NO_COLOR" >> "$FAKE_GH_DIR/env"
case "$1 $2" in
  "auth status") exit "$(cat "$FAKE_GH_DIR/auth.code" 2>/dev/null || echo 0)" ;;
  "repo view") name=repo_view ;;
  "run list") name=run_list ;;
  "pr list") name=pr_list ;;
  *)
    case "$2" in
      */rules/branches/*) name=rules ;;
      */branches/*/protection) name=protection ;;
      */actions/runs*) name=actions_runs ;;
      */code-scanning/analyses*) name=code_scanning ;;
      *) name=repo_api ;;
    esac ;;
esac
[ -f "$FAKE_GH_DIR/$name.out" ] && cat "$FAKE_GH_DIR/$name.out"
[ -f "$FAKE_GH_DIR/$name.err" ] && cat "$FAKE_GH_DIR/$name.err" >&2
exit "$(cat "$FAKE_GH_DIR/$name.code" 2>/dev/null || echo 0)"
"""

REPO_VIEW = {"visibility": "PUBLIC", "isFork": False, "defaultBranchRef": {"name": "main"}, "stargazerCount": 42}

RUNS = [
    {"conclusion": "success", "createdAt": "2025-01-05T10:00:00Z", "updatedAt": "2025-01-05T10:01:40Z",
     "attempt": 1, "workflowName": "CI", "event": "push"},
    {"conclusion": "failure", "createdAt": "2025-01-04T10:00:00Z", "updatedAt": "2025-01-04T10:03:20Z",
     "attempt": 2, "workflowName": "CI", "event": "push"},
    {"conclusion": "success", "createdAt": "2025-01-03T10:00:00Z", "updatedAt": "2025-01-03T10:05:00Z",
     "attempt": 1, "workflowName": "CI", "event": "push"},
    {"conclusion": "cancelled", "createdAt": "2025-01-02T10:00:00Z", "updatedAt": "2025-01-02T10:00:10Z",
     "attempt": 1, "workflowName": "CI", "event": "push"},
    {"conclusion": "", "createdAt": "2025-01-06T10:00:00Z", "updatedAt": "2025-01-06T10:00:10Z",
     "attempt": 1, "workflowName": "CI", "event": "push"},
    {"conclusion": "success", "createdAt": "2025-01-05T09:00:00Z", "updatedAt": "2025-01-05T09:00:30Z",
     "attempt": 1, "workflowName": "Lint", "event": "push"},
]

RULES = [
    {"type": "required_status_checks", "ruleset_id": 1,
     "parameters": {"required_status_checks": [{"context": "test", "integration_id": 1}]}},
    {"type": "pull_request", "ruleset_id": 1, "parameters": {"required_approving_review_count": 2}},
    {"type": "deletion", "ruleset_id": 1},
]

API_RUNS = {"workflow_runs": [
    {"name": "CI", "path": ".github/workflows/ci.yml", "conclusion": "success", "created_at": "2025-01-05T10:00:00Z"},
    {"name": "CI", "path": ".github/workflows/ci.yml", "conclusion": "success", "created_at": "2025-01-06T10:00:00Z"},
    {"name": "CI", "path": ".github/workflows/ci.yml", "conclusion": "cancelled", "created_at": "2025-01-07T10:00:00Z"},
    {"name": "CI", "path": ".github/workflows/ci.yml", "conclusion": None, "created_at": "2025-01-08T10:00:00Z"},
    {"name": "Lint", "path": ".github/workflows/lint.yml@refs/heads/main", "conclusion": "failure",
     "created_at": "2025-01-05T09:00:00Z"},
    {"name": "Nightly", "path": ".github/workflows/nightly.yml", "conclusion": "cancelled",
     "created_at": "2025-01-05T08:00:00Z"},
]}

PROTECTION = {"required_status_checks": {"strict": True, "contexts": ["lint"], "checks": [{"context": "test"}]},
              "required_pull_request_reviews": {"required_approving_review_count": 1},
              "enforce_admins": {"enabled": True}}

SECURITY = {"secret_scanning": {"status": "enabled"}, "secret_scanning_push_protection": {"status": "disabled"},
            "advanced_security": {"status": "enabled"}}

PRS = [
    {"createdAt": "2025-01-01T00:00:00Z", "mergedAt": "2025-01-01T02:00:00Z", "reviews": [{"state": "APPROVED"}]},
    {"createdAt": "2025-01-02T00:00:00Z", "mergedAt": "2025-01-02T06:00:00Z", "reviews": []},
    {"createdAt": "2025-01-03T00:00:00Z", "mergedAt": "2025-01-03T04:00:00Z", "reviews": []},
    {"createdAt": "2025-01-04T00:00:00Z", "mergedAt": "2025-01-04T10:00:00Z", "reviews": [{"state": "COMMENTED"}]},
]


def git(root, *args):
    env = dict(os.environ)
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    subprocess.run(["git", "-c", "init.defaultBranch=main"] + list(args), cwd=root, env=env, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class FakeGh(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="repo-health-gh-repo-")
        self.fake = tempfile.mkdtemp(prefix="repo-health-gh-fake-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.fake, ignore_errors=True)
        git(self.root, "init", "-q")
        git(self.root, "remote", "add", "origin", "git@github.com:acme/widgets.git")
        self.bin = os.path.join(self.fake, "bin")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "gh"), "w") as handle:
            handle.write(FAKE_GH)
        os.chmod(os.path.join(self.bin, "gh"), 0o755)
        self.data = os.path.join(self.fake, "data")
        os.makedirs(self.data)
        saved = dict(os.environ)
        os.environ["PATH"] = self.bin + os.pathsep + os.environ.get("PATH", "")
        os.environ["FAKE_GH_DIR"] = self.data
        self.addCleanup(self.restore, saved)
        self.answer("repo_view", out=REPO_VIEW)
        self.answer("run_list", out=RUNS)
        self.answer("rules", out=RULES)
        self.answer("protection", out=PROTECTION)
        self.answer("repo_api", out=SECURITY)
        self.answer("pr_list", out=PRS)
        self.answer("actions_runs", out=API_RUNS)
        self.answer("code_scanning", out=[{"created_at": "2025-01-09T12:00:00Z"}])

    @staticmethod
    def restore(saved):
        os.environ.clear()
        os.environ.update(saved)

    def answer(self, name, out=None, err=None, code=0):
        for suffix, value in (("out", out), ("err", err), ("code", code)):
            path = os.path.join(self.data, "%s.%s" % (name, suffix))
            if value is None:
                if os.path.exists(path):
                    os.remove(path)
                continue
            with open(path, "w") as handle:
                handle.write(value if isinstance(value, str) else json.dumps(value))

    def calls(self):
        path = os.path.join(self.data, "log")
        if not os.path.exists(path):
            return []
        with open(path) as handle:
            return [line.strip() for line in handle if line.strip()]

    def collect(self, **kwargs):
        return ghfacts.collect(self.root, **kwargs)


class Happy(FakeGh):
    def test_everything_is_read(self):
        result = self.collect()
        self.assertEqual((result["available"], result["repo"], result["visibility"], result["is_fork"],
                          result["default_branch"], result["stars"]),
                         (True, "acme/widgets", "public", False, "main", 42))
        runs = result["runs"]
        self.assertEqual((runs["branch"], runs["limit"]), ("main", 50))
        ci = runs["workflows"]["CI"]
        self.assertEqual(ci, {"runs": 5, "completed": 3, "pass_rate": 0.667, "median_duration_s": 200.0,
                              "rerun_rate": 0.2, "last_failure": "2025-01-04T10:00:00Z",
                              "path": ".github/workflows/ci.yml", "last_run": "2025-01-06T10:00:00Z"})
        self.assertEqual(runs["workflows"]["Lint"]["pass_rate"], 1.0)
        self.assertIsNone(runs["workflows"]["Lint"]["last_failure"])
        overall = runs["overall"]
        self.assertEqual((overall["runs"], overall["completed"], overall["pass_rate"]), (6, 4, 0.75))
        self.assertEqual(overall["median_duration_s"], 150.0)
        self.assertEqual(result["branch_protection"], {
            "state": "protected", "required_status_checks": ["lint", "test"], "required_approving_reviews": 2,
            "enforce_admins": True, "sources": {"rulesets": "ok", "classic": "ok"}})
        self.assertEqual(result["security_and_analysis"], {
            "advanced_security": "enabled", "secret_scanning": "enabled", "secret_scanning_push_protection": "disabled"})
        self.assertEqual(result["pull_requests"], {"prs": 4, "median_time_to_merge_s": 18000.0,
                                                   "no_review_share": 0.5})
        self.assertEqual(result["code_scanning"], {"last_analysis": "2025-01-09T12:00:00Z"})

    def test_run_limit_is_passed_and_repo_is_named_with_r(self):
        self.collect(runs=7)
        calls = self.calls()
        run_list = [c for c in calls if c.startswith("run list")][0]
        self.assertIn("-R acme/widgets", run_list)
        self.assertIn("--branch main", run_list)
        self.assertIn("--limit 7", run_list)
        self.assertIn("--json conclusion,createdAt,updatedAt,attempt,workflowName,event", run_list)
        self.assertIn("-R acme/widgets", [c for c in calls if c.startswith("pr list")][0])
        self.assertIn("repo view acme/widgets --json visibility,isFork,defaultBranchRef,stargazerCount", calls)
        self.assertIn("api repos/acme/widgets/rules/branches/main", calls)
        self.assertIn("api repos/acme/widgets/branches/main/protection", calls)
        self.assertIn("api repos/acme/widgets --jq .security_and_analysis", calls)

    def test_workflow_path_and_last_run_come_from_the_actions_api(self):
        self.collect(runs=7)
        self.assertIn("api repos/acme/widgets/actions/runs?branch=main&per_page=7", self.calls())
        self.assertIn("api repos/acme/widgets/code-scanning/analyses?per_page=1", self.calls())
        workflows = self.collect()["runs"]["workflows"]
        self.assertEqual((workflows["Lint"]["path"], workflows["Lint"]["last_run"]),
                         (".github/workflows/lint.yml", "2025-01-05T09:00:00Z"))

    def test_a_workflow_the_api_does_not_show_has_no_path_and_no_date(self):
        self.answer("actions_runs", out={"workflow_runs": []})
        lint = self.collect()["runs"]["workflows"]["Lint"]
        self.assertEqual((lint["path"], lint["last_run"]), (None, None))
        self.answer("actions_runs", out="", err="gh: boom (HTTP 500)\n", code=1)
        result = self.collect()
        self.assertEqual(result["runs"]["workflows"]["CI"]["path"], None)
        self.assertEqual(result["runs"]["overall"]["runs"], 6)

    def test_a_workflow_with_only_cancelled_runs_has_a_path_and_no_date(self):
        self.answer("actions_runs", out=API_RUNS)
        self.answer("run_list", out=RUNS + [{"conclusion": "cancelled", "createdAt": "2025-01-05T08:00:00Z",
                                             "updatedAt": "2025-01-05T08:00:10Z", "attempt": 1,
                                             "workflowName": "Nightly", "event": "schedule"}])
        nightly = self.collect()["runs"]["workflows"]["Nightly"]
        self.assertEqual((nightly["path"], nightly["last_run"]), (".github/workflows/nightly.yml", None))

    def test_the_actions_page_size_is_at_most_100(self):
        self.collect(runs=500)
        self.assertIn("api repos/acme/widgets/actions/runs?branch=main&per_page=100", self.calls())

    def test_every_call_is_read_only(self):
        self.collect()
        for call in self.calls():
            words = call.split()
            self.assertTrue(words[:2] in (["auth", "status"], ["repo", "view"], ["run", "list"], ["pr", "list"])
                            or words[0] == "api", call)
            if words[0] == "api":
                self.assertFalse({"-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"} & set(words), call)

    def test_gh_never_runs_in_the_scanned_repository_and_never_prompts(self):
        self.collect()
        with open(os.path.join(self.data, "env")) as handle:
            lines = [line.strip().split("|") for line in handle if line.strip()]
        self.assertTrue(lines)
        for cwd, prompt, color in lines:
            self.assertNotEqual(os.path.realpath(cwd), os.path.realpath(self.root))
            self.assertEqual((prompt, color), ("1", "1"))

    def test_the_scratch_directory_is_removed(self):
        before = {n for n in os.listdir(tempfile.gettempdir()) if n.startswith("repo-health-gh-") and "repo-" not in n[15:]}
        self.collect()
        after = {n for n in os.listdir(tempfile.gettempdir()) if n.startswith("repo-health-gh-") and "repo-" not in n[15:]}
        self.assertEqual(before, after)

    def test_solo_skips_pull_request_facts(self):
        result = self.collect(solo=True)
        self.assertEqual(result["pull_requests"], {"skipped": "solo repository"})
        self.assertFalse([c for c in self.calls() if c.startswith("pr list")])

    def test_private_repository_and_internal_forks(self):
        self.answer("repo_view", out={"visibility": "PRIVATE", "isFork": True, "defaultBranchRef": {"name": "trunk"},
                                      "stargazerCount": 0})
        result = self.collect()
        self.assertEqual((result["visibility"], result["is_fork"], result["default_branch"]), ("private", True, "trunk"))
        self.assertIn("api repos/acme/widgets/rules/branches/trunk", self.calls())

    def test_branch_names_with_slashes_are_encoded(self):
        self.answer("repo_view", out={"visibility": "PUBLIC", "isFork": False,
                                      "defaultBranchRef": {"name": "release/1"}, "stargazerCount": 1})
        self.collect()
        self.assertIn("api repos/acme/widgets/branches/release%2F1/protection", self.calls())

    def test_the_cli_prints_json_and_exits_zero(self):
        proc = subprocess.run([sys.executable, SCRIPT, self.root, "--runs", "10", "--solo"], stdout=subprocess.PIPE,
                              check=True)
        data = json.loads(proc.stdout.decode())
        self.assertTrue(data["available"])
        self.assertEqual(data["runs"]["limit"], 10)


class Protection(FakeGh):
    def not_protected(self):
        self.answer("protection", out='{"message":"Branch not protected","status":"404"}',
                    err="gh: Branch not protected (HTTP 404)\n", code=1)

    def test_404_branch_not_protected_is_none(self):
        self.not_protected()
        self.answer("rules", out=[])
        protection = self.collect()["branch_protection"]
        self.assertEqual(protection["state"], "none")
        self.assertEqual(protection["sources"], {"rulesets": "none", "classic": "none"})
        self.assertEqual(protection["required_status_checks"], [])

    def test_the_message_can_come_from_stderr_only(self):
        self.answer("protection", err="gh: Branch not protected (HTTP 404)\n", code=1)
        self.answer("rules", out=[])
        self.assertEqual(self.collect()["branch_protection"]["state"], "none")

    def test_403_is_not_visible(self):
        self.answer("protection", out='{"message":"Upgrade to GitHub Pro","status":"403"}',
                    err="gh: Upgrade to GitHub Pro or make this repository public to enable this feature. (HTTP 403)\n",
                    code=1)
        self.answer("rules", out='{"message":"Forbidden","status":"403"}', err="gh: Forbidden (HTTP 403)\n", code=1)
        protection = self.collect()["branch_protection"]
        self.assertEqual(protection["state"], "not_visible")
        self.assertEqual(protection["sources"], {"rulesets": "not_visible", "classic": "not_visible"})

    def test_other_404_is_not_visible(self):
        self.answer("protection", out='{"message":"Not Found","status":"404"}', err="gh: Not Found (HTTP 404)\n",
                    code=1)
        self.answer("rules", out=[])
        protection = self.collect()["branch_protection"]
        self.assertEqual(protection["sources"], {"rulesets": "none", "classic": "not_visible"})
        self.assertEqual(protection["state"], "not_visible")

    def test_a_ruleset_alone_protects(self):
        self.not_protected()
        protection = self.collect()["branch_protection"]
        self.assertEqual((protection["state"], protection["required_status_checks"],
                          protection["required_approving_reviews"], protection["enforce_admins"]),
                         ("protected", ["test"], 2, None))

    def test_classic_protection_alone_protects(self):
        self.answer("rules", out=[])
        protection = self.collect()["branch_protection"]
        self.assertEqual((protection["state"], protection["required_status_checks"],
                          protection["required_approving_reviews"], protection["enforce_admins"]),
                         ("protected", ["lint", "test"], 1, True))

    def test_protected_without_required_checks(self):
        self.answer("protection", out={"required_pull_request_reviews": {"required_approving_review_count": 0}})
        self.answer("rules", out=[])
        protection = self.collect()["branch_protection"]
        self.assertEqual((protection["state"], protection["required_status_checks"]), ("protected", []))


class CodeScanning(FakeGh):
    def test_no_analysis_is_none(self):
        self.answer("code_scanning", out=[])
        self.assertEqual(self.collect()["code_scanning"], {"last_analysis": "none"})
        self.answer("code_scanning", out='{"message":"No analysis found","status":"404"}',
                    err="gh: No analysis found (HTTP 404)\n", code=1)
        self.assertEqual(self.collect()["code_scanning"], {"last_analysis": "none"})

    def test_other_errors_are_not_visible(self):
        self.answer("code_scanning", out='{"message":"Forbidden","status":"403"}', err="gh: Forbidden (HTTP 403)\n",
                    code=1)
        self.assertEqual(self.collect()["code_scanning"], {"last_analysis": "not_visible"})
        self.answer("code_scanning", out='{"message":"Not Found","status":"404"}', err="gh: Not Found (HTTP 404)\n",
                    code=1)
        self.assertEqual(self.collect()["code_scanning"], {"last_analysis": "not_visible"})
        self.answer("code_scanning", out=[{"created_at": "yesterday"}])
        self.assertEqual(self.collect()["code_scanning"], {"last_analysis": "none"})


class SecurityAndOthers(FakeGh):
    def test_security_block_absent_is_not_visible(self):
        self.answer("repo_api", out="null\n")
        self.assertEqual(self.collect()["security_and_analysis"], "not_visible")
        self.answer("repo_api", out="", err="gh: boom (HTTP 500)\n", code=1)
        self.assertEqual(self.collect()["security_and_analysis"], "not_visible")

    def test_a_failed_run_list_is_an_error_not_a_crash(self):
        self.answer("run_list", out="", err="gh: HTTP 502\n", code=1)
        result = self.collect()
        self.assertEqual(result["runs"], {"error": "gh: HTTP 502"})
        self.assertTrue(result["available"])

    def test_no_runs(self):
        self.answer("run_list", out=[])
        overall = self.collect()["runs"]["overall"]
        self.assertEqual(overall, {"runs": 0, "completed": 0, "pass_rate": None, "median_duration_s": None,
                                   "rerun_rate": None, "last_failure": None})

    def test_a_failed_pr_list_is_an_error(self):
        self.answer("pr_list", out="", err="gh: nope\n", code=1)
        self.assertEqual(self.collect()["pull_requests"], {"error": "gh: nope"})

    def test_no_merged_prs(self):
        self.answer("pr_list", out=[])
        self.assertEqual(self.collect()["pull_requests"],
                         {"prs": 0, "median_time_to_merge_s": None, "no_review_share": None})


class NotAvailable(FakeGh):
    def test_not_authenticated(self):
        self.answer("auth", out=None)
        with open(os.path.join(self.data, "auth.code"), "w") as handle:
            handle.write("1")
        result = self.collect()
        self.assertFalse(result["available"])
        self.assertIn("not authenticated", result["why"])
        self.assertEqual(self.calls(), ["auth status"])

    def test_origin_is_not_github(self):
        git(self.root, "remote", "set-url", "origin", "https://gitlab.com/acme/widgets.git")
        result = self.collect()
        self.assertFalse(result["available"])
        self.assertIn("not a GitHub remote", result["why"])
        self.assertIn("gitlab.com", result["why"])
        self.assertEqual(self.calls(), [])

    def test_credentials_in_the_url_are_not_echoed(self):
        git(self.root, "remote", "set-url", "origin", "https://user:s3cret@example.com/acme/widgets.git")
        self.assertNotIn("s3cret", json.dumps(self.collect()))

    def test_no_origin(self):
        git(self.root, "remote", "remove", "origin")
        result = self.collect()
        self.assertEqual(result["available"], False)
        self.assertIn("origin", result["why"])
        self.assertEqual(self.calls(), [])

    def test_gh_is_not_installed(self):
        with mock.patch.object(ghfacts.shutil, "which", return_value=None):
            result = self.collect()
        self.assertFalse(result["available"])
        self.assertIn("not installed", result["why"])
        self.assertEqual(self.calls(), [])

    def test_not_a_git_repository(self):
        plain = tempfile.mkdtemp(prefix="repo-health-plain-")
        self.addCleanup(shutil.rmtree, plain, ignore_errors=True)
        result = ghfacts.collect(plain)
        self.assertFalse(result["available"])

    def test_repo_view_failure(self):
        self.answer("repo_view", out="", err="gh: Could not resolve to a Repository (HTTP 404)\n", code=1)
        result = self.collect()
        self.assertFalse(result["available"])
        self.assertIn("repo view", result["why"])

    def test_the_cli_exits_zero_when_unavailable(self):
        git(self.root, "remote", "set-url", "origin", "https://example.com/a/b.git")
        proc = subprocess.run([sys.executable, SCRIPT, self.root], stdout=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(json.loads(proc.stdout.decode())["available"])

    def test_a_missing_directory_exits_two(self):
        proc = subprocess.run([sys.executable, SCRIPT, os.path.join(self.root, "nope")], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 2)


class Helpers(unittest.TestCase):
    def test_parse_origin(self):
        for url, expected in [
            ("https://github.com/acme/widgets.git", ("github.com", "acme", "widgets")),
            ("https://github.com/acme/widgets", ("github.com", "acme", "widgets")),
            ("https://user:tok@github.com/acme/widgets.git\n", ("github.com", "acme", "widgets")),
            ("git@github.com:acme/widgets.git", ("github.com", "acme", "widgets")),
            ("ssh://git@github.com/acme/widgets.git", ("github.com", "acme", "widgets")),
            ("ssh://git@ssh.github.com:443/acme/widgets.git", ("ssh.github.com", "acme", "widgets")),
            ("git://github.com/acme/widgets", ("github.com", "acme", "widgets")),
            ("https://github.com/acme/my.repo.git", ("github.com", "acme", "my.repo")),
            ("git@gitlab.com:acme/widgets.git", ("gitlab.com", "acme", "widgets")),
            ("/srv/git/widgets.git", (None, None, None)),
        ]:
            self.assertEqual(ghfacts.parse_origin(url), expected, url)

    def test_writing_calls_are_refused(self):
        for args in (["api", "repos/a/b", "-X", "DELETE"], ["api", "repos/a/b", "-f", "x=1"],
                     ["api", "--method=POST", "repos/a/b"], ["repo", "delete", "a/b"], ["pr", "merge", "1"],
                     ["run", "rerun", "1"], ["issue", "create"]):
            with self.assertRaises(ValueError):
                ghfacts.run_gh(args, tempfile.gettempdir())

    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        with open(SCRIPT) as handle:
            self.assertEqual(handle.readline().strip(), "#!/usr/bin/env python3")


if __name__ == "__main__":
    unittest.main()
