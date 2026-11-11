#!/usr/bin/env python3
"""CI outcomes and repository settings from GitHub, for the repo-health skill.

    ghfacts.py [REPO] [--runs 50] [--solo] [--pretty]

Prints one JSON document on stdout and exits 0. It needs the `gh` CLI, a
successful `gh auth status` and an `origin` remote on github.com; otherwise it
prints {"available": false, "why": "..."}. Every call is read-only (`gh auth
status`, `repo view`, `run list`, `pr list` and GET requests of `gh api`), has a
timeout, and runs with GH_PROMPT_DISABLED=1, NO_COLOR=1 and no pager. gh never
runs inside the scanned repository: the repository is named with -R or in the
API path, and the only command that runs there is `git remote get-url origin`
(through detect.run_git, which switches off the repository's own git commands).
Standard library only; Python 3.9+.

--solo says the repository has one active author (hotspots.py gives
active_authors_12m); pull request review facts are then skipped.

Output when available:

  repo                  "owner/name"
  visibility            "public", "private" or "internal" (decides the advice)
  is_fork, default_branch, stars
  runs                  CI runs of the default branch, the last --runs of them:
                        {"branch", "limit", "overall": S, "workflows": {name: S}}
                        where S = {"runs", "completed", "pass_rate",
                        "median_duration_s", "rerun_rate", "last_failure"}.
                        completed counts runs that ended in success, failure,
                        timed_out or startup_failure (cancelled and skipped runs
                        did not judge the code); pass_rate is success over
                        completed (null when none); median_duration_s is the
                        median of updatedAt - createdAt over completed runs;
                        rerun_rate is the share of runs with attempt > 1;
                        last_failure is the createdAt of the latest failed run.
                        {"error": "..."} when the call failed.
  branch_protection     {"state": "protected" | "none" | "not_visible",
                        "required_status_checks": [names],
                        "required_approving_reviews": int or null,
                        "enforce_admins": bool or null,
                        "sources": {"rulesets": X, "classic": X}} with X one of
                        "ok", "none" (HTTP 404 "Branch not protected", or no
                        ruleset applies) and "not_visible" (HTTP 403 or any
                        other error: the token cannot see it). The state is
                        "protected" when a source is ok, "none" when both say
                        none, else "not_visible".
  security_and_analysis {"secret_scanning": "enabled", ...} (every setting that
                        has a status), or "not_visible" when GitHub does not
                        show the block to this token
  pull_requests         the last 30 merged: {"prs", "median_time_to_merge_s",
                        "no_review_share"}; {"skipped": "..."} with --solo;
                        {"error": "..."} when the call failed
"""

import argparse
import datetime
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detect  # noqa: E402  (git runs with the repository's own commands switched off)

TIMEOUT = 60
READ_ONLY = {("auth", "status"), ("repo", "view"), ("run", "list"), ("pr", "list")}
WRITING_API_FLAGS = {"-X", "--method", "-f", "--raw-field", "-F", "--field", "--input"}
JUDGED = ("success", "failure", "timed_out", "startup_failure")
FAILED = ("failure", "timed_out", "startup_failure")


class Result(object):
    def __init__(self, code, out="", err=""):
        self.code = code
        self.out = out
        self.err = err


def gh_env():
    env = dict(os.environ)
    env.update({"GH_PROMPT_DISABLED": "1", "NO_COLOR": "1", "GH_PAGER": "cat", "PAGER": "cat",
                "GH_NO_UPDATE_NOTIFIER": "1", "GH_NO_EXTENSION_UPDATE_NOTIFIER": "1", "GIT_TERMINAL_PROMPT": "0"})
    env.pop("GH_FORCE_TTY", None)
    return env


def run_gh(args, cwd):
    """Run one read-only gh command outside the scanned repository."""
    if args[0] == "api":
        if any(a in WRITING_API_FLAGS or a.startswith(("--method=", "--field=", "--raw-field=")) for a in args[1:]):
            raise ValueError("ghfacts.py only reads: %r" % (args,))
    elif tuple(args[:2]) not in READ_ONLY:
        raise ValueError("ghfacts.py only reads: %r" % (args,))
    try:
        proc = subprocess.run(["gh"] + args, cwd=cwd, env=gh_env(), timeout=TIMEOUT,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired:
        return Result(None, err="timed out after %d s" % TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return Result(None, err=str(exc))
    return Result(proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace"))


def parse_origin(url):
    """(host, owner, repo) of a git remote URL; owner and repo are None when the shape is not known."""
    url = url.strip()
    m = re.match(r"^(?:[\w+.\-]+://)?(?:[^@/]+@)?([^:/]+)(?::\d+)?[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not m:
        return None, None, None
    return m.group(1).lower(), m.group(2), m.group(3)


def parse_time(text):
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def seconds_between(start, end):
    a, b = parse_time(start), parse_time(end)
    return (b - a).total_seconds() if a and b and b >= a else None


def first_line(text):
    return (text.strip().splitlines() or [""])[0][:200]


def json_of(result):
    try:
        return json.loads(result.out)
    except ValueError:
        return None


def run_stats(runs):
    judged = [r for r in runs if r.get("conclusion") in JUDGED]
    durations = [d for d in (seconds_between(r.get("createdAt"), r.get("updatedAt")) for r in judged)
                 if d is not None]
    failures = sorted(r["createdAt"] for r in judged if r["conclusion"] in FAILED and r.get("createdAt"))
    return {
        "runs": len(runs),
        "completed": len(judged),
        "pass_rate": round(sum(1 for r in judged if r["conclusion"] == "success") / float(len(judged)), 3)
        if judged else None,
        "median_duration_s": statistics.median(durations) if durations else None,
        "rerun_rate": round(sum(1 for r in runs if (r.get("attempt") or 1) > 1) / float(len(runs)), 3)
        if runs else None,
        "last_failure": failures[-1] if failures else None,
    }


def api_state(path, cwd):
    """("ok", data), ("none", None) or ("not_visible", None) for one GET request."""
    result = run_gh(["api", path], cwd)
    if result.code == 0:
        data = json_of(result)
        return ("ok", data) if data is not None else ("not_visible", None)
    body = json_of(result)
    message = (body.get("message", "") if isinstance(body, dict) else "") + " " + result.err
    status = re.search(r"\(HTTP (\d{3})\)", result.err)
    code = status.group(1) if status else str(body.get("status", "")) if isinstance(body, dict) else ""
    if code == "404" and "branch not protected" in message.lower():
        return "none", None
    return "not_visible", None


def rulesets(branch_path, cwd):
    state, data = api_state("%s/rules/branches/%s" % branch_path, cwd)
    if state != "ok":
        return state, [], None
    rules = [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    if not rules:
        return "none", [], None
    checks = []
    reviews = None
    for rule in rules:
        parameters = rule.get("parameters") or {}
        if rule.get("type") == "required_status_checks":
            checks.extend(c.get("context") for c in parameters.get("required_status_checks") or []
                          if isinstance(c, dict) and c.get("context"))
        elif rule.get("type") == "pull_request":
            count = parameters.get("required_approving_review_count")
            if isinstance(count, int):
                reviews = max(reviews or 0, count)
    return "ok", checks, reviews


def classic(branch_path, cwd):
    state, data = api_state("%s/branches/%s/protection" % branch_path, cwd)
    if state != "ok" or not isinstance(data, dict):
        return state, [], None, None
    status = data.get("required_status_checks") or {}
    checks = [c.get("context") for c in status.get("checks") or [] if isinstance(c, dict) and c.get("context")]
    checks.extend(c for c in status.get("contexts") or [] if isinstance(c, str))
    reviews = (data.get("required_pull_request_reviews") or {}).get("required_approving_review_count")
    admins = (data.get("enforce_admins") or {}).get("enabled")
    return "ok", checks, reviews if isinstance(reviews, int) else None, admins if isinstance(admins, bool) else None


def branch_protection(slug, branch, cwd):
    base = "repos/" + slug
    encoded = quote(branch, safe="")
    rule_state, rule_checks, rule_reviews = rulesets((base, encoded), cwd)
    classic_state, classic_checks, classic_reviews, admins = classic((base, encoded), cwd)
    if "ok" in (rule_state, classic_state):
        state = "protected"
    elif rule_state == classic_state == "none":
        state = "none"
    else:
        state = "not_visible"
    reviews = [r for r in (rule_reviews, classic_reviews) if r is not None]
    return {"state": state,
            "required_status_checks": sorted(set(rule_checks + classic_checks)),
            "required_approving_reviews": max(reviews) if reviews else None,
            "enforce_admins": admins,
            "sources": {"rulesets": rule_state, "classic": classic_state}}


def security(slug, cwd):
    result = run_gh(["api", "repos/" + slug, "--jq", ".security_and_analysis"], cwd)
    data = json_of(result) if result.code == 0 else None
    if not isinstance(data, dict):
        return "not_visible"
    values = {key: value.get("status") for key, value in sorted(data.items())
              if isinstance(value, dict) and value.get("status")}
    return values or "not_visible"


def pull_requests(slug, cwd):
    result = run_gh(["pr", "list", "-R", slug, "--state", "merged", "--limit", "30",
                     "--json", "createdAt,mergedAt,reviews"], cwd)
    data = json_of(result) if result.code == 0 else None
    if not isinstance(data, list):
        return {"error": first_line(result.err) or "gh pr list failed"}
    times = [t for t in (seconds_between(p.get("createdAt"), p.get("mergedAt")) for p in data) if t is not None]
    return {"prs": len(data),
            "median_time_to_merge_s": statistics.median(times) if times else None,
            "no_review_share": round(sum(1 for p in data if not p.get("reviews")) / float(len(data)), 3)
            if data else None}


def collect(repo, runs=50, solo=False):
    url = detect.run_git(repo, ["remote", "get-url", "origin"])
    if not url:
        return {"available": False, "why": "the repository has no origin remote"}
    host, owner, name = parse_origin(url.decode("utf-8", "replace"))
    if host not in ("github.com", "ssh.github.com", "www.github.com") or not owner:
        return {"available": False, "why": "origin is not a GitHub remote (host: %s)" % (host or "unknown")}
    if shutil.which("gh") is None:
        return {"available": False, "why": "the gh CLI is not installed"}
    cwd = tempfile.mkdtemp(prefix="repo-health-gh-")
    try:
        auth = run_gh(["auth", "status"], cwd)
        if auth.code != 0:
            return {"available": False, "why": "gh is not authenticated (gh auth status failed)"}
        slug = "%s/%s" % (owner, name)
        view = run_gh(["repo", "view", slug, "--json", "visibility,isFork,defaultBranchRef,stargazerCount"], cwd)
        info = json_of(view) if view.code == 0 else None
        if not isinstance(info, dict):
            return {"available": False, "why": "gh repo view failed: %s" % (first_line(view.err) or "no answer")}
        branch = (info.get("defaultBranchRef") or {}).get("name")
        result = {"available": True, "repo": slug,
                  "visibility": str(info.get("visibility", "")).lower() or None,
                  "is_fork": info.get("isFork"), "default_branch": branch, "stars": info.get("stargazerCount")}
        if not branch:
            result["why"] = "the repository has no default branch yet"
            return result
        listing = run_gh(["run", "list", "-R", slug, "--branch", branch, "--limit", str(runs), "--json",
                          "conclusion,createdAt,updatedAt,attempt,workflowName,event"], cwd)
        data = json_of(listing) if listing.code == 0 else None
        if isinstance(data, list):
            names = sorted({str(r.get("workflowName") or "") for r in data})
            result["runs"] = {"branch": branch, "limit": runs, "overall": run_stats(data),
                              "workflows": {n: run_stats([r for r in data if str(r.get("workflowName") or "") == n])
                                            for n in names}}
        else:
            result["runs"] = {"error": first_line(listing.err) or "gh run list failed"}
        result["branch_protection"] = branch_protection(slug, branch, cwd)
        result["security_and_analysis"] = security(slug, cwd)
        result["pull_requests"] = {"skipped": "solo repository"} if solo else pull_requests(slug, cwd)
        return result
    finally:
        shutil.rmtree(cwd, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="CI outcomes and settings of a GitHub repository, read-only.")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--solo", action="store_true", help="skip pull request review facts")
    parser.add_argument("--pretty", action="store_true", help="indent the JSON")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.repo):
        sys.stderr.write("ghfacts.py: not a directory: %s\n" % args.repo)
        return 2
    result = collect(os.path.abspath(args.repo), args.runs, args.solo)
    if args.pretty:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
