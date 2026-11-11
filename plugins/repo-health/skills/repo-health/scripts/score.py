#!/usr/bin/env python3
"""Levels, gaps and changes for the repo-health skill: the rules of references/dimensions.md as code.

    score.py --detect D.json --hotspots H.json [--ghfacts G.json] [--tier1 T.json]
             [--decisions decisions.json] [--previous OLD-score.json] [--now YYYY-MM-DD]
             -o score.json
    score.py decide GAP_ID (--dismiss | --later | --done) --reason TEXT [--file decisions.json] [--date YYYY-MM-DD]

The model never sets a tier 0 level. This script reads the JSON of detect.py,
hotspots.py and ghfacts.py (see their docstrings for the shapes) and applies every
rule of dimensions.md. The same inputs give the same bytes: keys are sorted, every
list is ordered, and the only date inside is `as_of` (--now, today by default),
which decides the 90-day lockfile age of deps.3. Standard library only; Python 3.9+.
A missing or unavailable ghfacts ({"available": false}) is the same as no ghfacts.

Tier 1 input (--tier1), written by the skill after it ran tools:

    {"counts":     {"lint:<subproject>": {"errors": 0}, "types:<subproject>": {"errors": 0}},
     "suite_runs": [{"subproject": ".", "passed": true, "duration_s": 95}],
     "audits":     [{"subproject": ".", "high": 0, "critical": 0}]}

Output (score.json)

    as_of, repo, commit, default_branch
    profile      {authors: solo|team, visibility: public|private|unknown,
                  kind: application|library|scripts, facts: {authors, visibility, kind: [...]}}
    dimensions[] {id, subproject, level 0-3 or null, status checked|unknown|not_applicable,
                  rule ("tests.1p"), partial null or {covered, total, missing, unit},
                  needs null or text, facts [short strings], summary (15 words at most),
                  summary_zh (the same sentence in Chinese, from ZH_SUMMARIES)}
                 Facts are "file:line (tool)" for the repository or a pointer such as
                 "ghfacts.json#/runs/overall/pass_rate" or "detect.json#/docs/run".
                 Repository-wide dimensions (static, secrets, ci, docs, deps) use subproject ".".
    hotspots[]   the top 15 of hotspots.json plus tests_in_ci (true, false or "unknown"),
                 suppressions (count when the file is among detect's top files, else null),
                 linted_in_ci, the owning test suite
    ci_health    from ghfacts: {available, default_branch_pass_rate, median_duration_s,
                 rerun_rate, last_failure, completed_runs, workflows, pull_requests, why}
    gaps[]       {id, dimension, subproject, rule, what, facts, hotspot_files,
                  effort enforce|add|large, priority, decision?}, sorted by priority
                 (high first), then dimension order, then id. id = dimension:subproject:slug,
                 where slug is the rule that set the level, or rule and a detail for
                 a specific cause (tests:.:missing-suite:plugins/x/tests).
    dismissed[], regressed[], deferred[], not_applicable[]   see "Decisions"
    changes      null, or {compared_with, dimensions: [{id, subproject, change, before, after}],
                 gaps: {closed: [{id, dimension, what}], new: [ids], still_open: [ids]}}
                 change is up, down, same, new or changed (a row without a level whose
                 summary or facts differ).

Profile heuristics
    authors     solo when hotspots.active_authors_12m is 1 or less, else team (also when the
                history is not usable: the lower reading).
    visibility  ghfacts.visibility: public, private (internal counts as private), else unknown.
    kind        per subproject, then for the repository (application beats library beats
                scripts). A subproject that detect calls publishable (package.json with a
                name and no "private": true, pyproject with [project] and [build-system],
                Cargo [package] without publish = false, maven-publish) and that has no
                Dockerfile or compose file inside it and no workflow file named like deploy
                is a library. Else a subproject with no third-party dependencies
                (dependencies.direct is 0) is scripts. Else application. Only application
                subprojects need a lockfile (setup); a library or scripts subproject does
                not, and the report says so.

Joins and approximations (each is the lower reading of dimensions.md)
    * A CI row counts for a subproject when its language is one of the subproject's
      languages (or "shared"); detect rows carry no subproject. A row is blocking when
      pull_request is true or "push-default" and it is not non_blocking.
    * A test suite is covered by a blocking CI test row of its language when one command
      names the suite folder, a folder above it, a file inside it, a workspace member
      (cargo -p, pnpm --filter, npm -w) on the path, or names no path at all and runs from
      the folder of its package.json (else the repository root). A path made of a shell
      variable covers nothing and the suite is reported as unknown for tests_in_ci.
    * A hotspot belongs to the test suite with the deepest scope that holds it and has
      its language; the scope of X/tests is X, the scope of any other suite folder is itself.
      A hotspot with a suite that CI misses is covered by the missing-suite gap; a hotspot
      with no suite at all gets its own gap (hotspots:<sub>:no-tests:<path>).
    * lint.3 suppressions per 1,000 lines use detect's per-language totals over the whole
      repository (detect has no per-subproject counts) and loc + test_loc.
    * tests.3 needs at least 10 completed default-branch runs in ghfacts.
    * static.3 needs open-alert counts that ghfacts does not emit: level 2 with `needs`.
      GitHub code scanning counts as on when security_and_analysis shows advanced_security
      or code_security enabled.
    * ci.3 needs lint at level 2 or more in every subproject that has source files.
    * setup toolchain pins and task runners under tests, test, fixtures or testdata do not
      count; a root-level pin or runner counts for every subproject below it; the task
      entry may also be a README command that detect found to exist.
    * setup.3: any locked install in CI (ci.locked_installs) or a devcontainer.
    * types.2c: any blocking CI row of the language (build, test or lint).
    * A CI-sourced strictness fact applies by language; a config fact by its subproject.
    * arch is per subproject: not_applicable for a scripts project or under 3,000 source
      lines. A tool that rides on the tests (ArchUnit, Spring Modulith, Konsist, pytestarch)
      counts when every suite of the subproject is covered by blocking CI (detect does not
      say which suite holds the architecture tests); a plugin on a linter needs a blocking
      row of that linter; a CLI tool needs its own blocking row; a Cargo workspace with two
      or more members counts. arch.3 needs an architecture doc, ADR or model whose
      last_commit is within 365 days of as_of (the README section counts with the README's date).

Priority = weight x hotspot factor x effort factor x moot, as in dimensions.md. Weights:
tests 10, ci 9, hotspots 8 (a hotspot gap), lint 7, types 6, secrets 6 (public) or 3
(otherwise), coverage 4, setup 4, deps 4, static 3, docs 3, arch 3. A wrong README command
counts as "enforce" (a quick fix), a missing one as "add".

Decisions
    .repo-health/decisions.json (in the scanned repository, or --decisions) maps a gap id to
    {"status": "dismissed" | "later" | "done", "reason": "...", "date": "YYYY-MM-DD"}.
    dismissed: the gap leaves `gaps` and appears under `dismissed`. later: it stays with
    priority x 0.5 and its id is listed under `deferred`. done: informational; a gap marked
    done that is detected again is listed under `regressed`. Gap ids are printed next to
    each recommendation of the report. Edit the file by hand or run:

        score.py decide tests:.:missing-suite:plugins/x/tests --dismiss --reason "run by make ci"

    which creates the file when it is missing, keeps the other entries and sorts the keys.
"""

import argparse
import datetime
import json
import os
import posixpath
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detect  # noqa: E402  (tool names, languages and manifests are one table)

DIMENSION_ORDER = ["lint", "types", "static", "secrets", "tests", "coverage", "ci", "setup", "docs", "deps",
                   "arch", "hotspots"]
WEIGHTS = {"tests": 10, "ci": 9, "hotspots": 8, "lint": 7, "types": 6, "secrets": 6, "coverage": 4, "setup": 4,
           "deps": 4, "static": 3, "docs": 3, "arch": 3}
EFFORT_FACTOR = {"enforce": 1.5, "add": 1.0, "large": 0.7}
LANGUAGES = list(detect.LANGUAGES)
TOOL_LANGUAGE = {row[1]: row[0] for row in detect.TOOLS}
TEST_DIR_NAMES = detect.TEST_DIR_NAMES
IGNORED_SETUP_DIRS = ("tests", "test", "fixtures", "testdata", "__tests__")
RECENT_DAYS = 90
ARCH_MIN_LOC = 3000
MIN_RUNS = 10
SUPPRESSIONS_PER_KLOC = 2.0
FAST_SUITE_SECONDS = 600
HOTSPOT_TOP = 15
STRICT_PYTHON = ("mypy-strict", "mypy-disallow-untyped-defs", "pyright-strict")
WARNING_FACTS = {"rust": ("clippy-deny-warnings", "rustflags-deny-warnings", "cargo-lints-deny-warnings"),
                 "java": ("javac-werror",), "kotlin": ("kotlin-all-warnings-as-errors", "javac-werror"),
                 "go": ("go-vet",)}
THRESHOLD_LANGUAGE = {"fail_under": "python", "cov-fail-under": "python", "jacoco-violation-rules": "java",
                      "kover-min-bound": "kotlin", "vitest-thresholds": "typescript",
                      "jest-coverage-threshold": "typescript", "codecov-patch-target": None}
ECOSYSTEM_OF_LANGUAGE = {"python": "python", "typescript": "typescript", "rust": "rust", "go": "go",
                         "java": "java", "kotlin": "java"}
VALUE_FLAGS = {"-k", "-m", "-n", "-c", "-p", "-W", "-o", "--ignore", "--deselect", "--maxfail", "--cov",
               "--cov-report", "--cov-config", "--durations", "--junitxml", "--backend", "-j", "--features",
               "--rootdir", "--config", "-t", "--top-level-directory"}
PATH_FLAGS = {"-s", "--start-directory", "-C", "--prefix", "--manifest-path"}
NAME_FLAGS = {"cargo": {"-p", "--package"}, "npm": {"-w", "--workspace"}, "pnpm": {"-F", "--filter"},
              "yarn": {"--filter"}, "turbo": {"--filter"}, "nx": {"-p", "--projects"}, "lerna": {"--scope"}}


# --------------------------------------------------------------------------
# Chinese summaries
# --------------------------------------------------------------------------

ZH_WORDS = {"lockfile": "锁文件", "toolchain pin": "工具链版本固定", "task entry": "任务入口", "install": "安装",
            "run": "运行", "test": "测试", "python": "Python", "typescript": "TypeScript"}

# (regex over the English summary, Chinese template); \1 and the like are the captured parts.
ZH_SUMMARIES = [
    (r"^No source files\.$", "没有源码文件。"),
    (r"^No linter for (.*)\.$", "没有 \\1 的 linter。"),
    (r"^Linter configured, not blocking in CI\.$", "已配置 linter，CI 中不阻塞。"),
    (r"^Blocking linter and formatter check; zero errors\.$", "linter 与格式检查阻塞合并，错误为零。"),
    (r"^Blocking linter and formatter check in CI\.$", "CI 中 linter 与格式检查阻塞合并。"),
    (r"^Linter blocks in CI, but (\d+) errors remain\.$", "CI 中 linter 阻塞合并，但仍有 \\1 个错误。"),
    (r"^Linter blocks in CI\.$", "CI 中 linter 阻塞合并。"),
    (r"^No type checker for (.*)\.$", "没有 \\1 的类型检查。"),
    (r"^Type checker configured, not blocking in CI\.$", "已配置类型检查，CI 中不阻塞。"),
    (r"^Type checker blocks in CI\.$", "CI 中类型检查阻塞合并。"),
    (r"^Strict type checker blocks, zero errors\.$", "严格类型检查阻塞合并，错误为零。"),
    (r"^CI does not build the code\.$", "CI 不构建代码。"),
    (r"^CI builds the code\.$", "CI 构建代码。"),
    (r"^CI builds with warnings as errors\.$", "CI 构建时把警告当作错误。"),
    (r"^Security analysis blocks; no open serious alerts\.$", "安全分析阻塞合并，没有未处理的严重告警。"),
    (r"^Security analysis blocks in CI\.$", "CI 中安全分析阻塞合并。"),
    (r"^Security analysis configured, not blocking in CI\.$", "已配置安全分析，CI 中不阻塞。"),
    (r"^No static security analysis\.$", "没有静态安全分析。"),
    (r"^Push protection and a blocking CI scanner\.$", "已开启推送保护，且 CI 中有阻塞的扫描器。"),
    (r"^GitHub secret scanning and push protection on\.$", "GitHub 密钥扫描和推送保护已开启。"),
    (r"^A secret scanner blocks in CI\.$", "CI 中密钥扫描器阻塞合并。"),
    (r"^Secret scanning present, not blocking\.$", "有密钥扫描，但不阻塞。"),
    (r"^Secret scanning setting not visible\.$", "看不到密钥扫描设置。"),
    (r"^No secret scanning\.$", "没有密钥扫描。"),
    (r"^No test files\.$", "没有测试文件。"),
    (r"^Tests exist; no blocking CI step runs them\.$", "有测试，但没有阻塞的 CI 步骤运行它们。"),
    (r"^Blocking CI test steps do not reach any suite\.$", "阻塞的 CI 测试步骤没有覆盖任何测试套件。"),
    (r"^CI runs (\d+) of (\d+) test suites\.$", "CI 只运行了 \\2 个测试套件中的 \\1 个。"),
    (r"^Blocking CI runs every suite, and it passes\.$", "阻塞的 CI 运行全部套件，且通过。"),
    (r"^Blocking CI runs every suite\.$", "阻塞的 CI 运行全部套件。"),
    (r"^Blocking CI runs every suite; results are weak\.$", "阻塞的 CI 运行全部套件，但结果不理想。"),
    (r"^No tests to measure\.$", "没有可度量的测试。"),
    (r"^A coverage threshold fails the build\.$", "覆盖率阈值会让构建失败。"),
    (r"^Blocking CI measures coverage\.$", "阻塞的 CI 度量覆盖率。"),
    (r"^Coverage configured, not measured in CI\.$", "已配置覆盖率，CI 中未度量。"),
    (r"^No coverage measurement\.$", "没有覆盖率度量。"),
    (r"^No CI configuration\.$", "没有 CI 配置。"),
    (r"^CI exists; nothing runs on pull requests\.$", "有 CI，但拉取请求上不运行任何东西。"),
    (r"^CI runs on pull requests; tests do not run there\.$", "CI 在拉取请求上运行，但不跑测试。"),
    (r"^Pull requests run the tests; lint is not enforced\.$", "拉取请求会跑测试，但 lint 不强制。"),
    (r"^Pull requests run tests and lint; checks are required\.$", "拉取请求跑测试和 lint，且检查为必需。"),
    (r"^Solo repository; tests and lint run, main passes\.$", "单人仓库，测试和 lint 在跑，主分支通过。"),
    (r"^Tests and lint run on pull requests; required checks unknown\.$", "拉取请求跑测试和 lint，必需检查未知。"),
    (r"^Tests and lint run on pull requests; no required checks\.$", "拉取请求跑测试和 lint，没有必需检查。"),
    (r"^No lockfile, toolchain pin or task entry\.$", "没有锁文件、工具链版本固定和任务入口。"),
    (r"^No toolchain pin or task entry\.$", "没有工具链版本固定和任务入口。"),
    (r"^Missing: (.*)\.$", "缺少：\\1。"),
    (r"^Pin, task entry, lockfile present\.$", "有版本固定、任务入口和锁文件。"),
    (r"^Pin, task entry present\.$", "有版本固定和任务入口。"),
    (r"^Reproducible setup; CI installs from the lockfile\.$", "环境可复现，CI 按锁文件安装。"),
    (r"^No README\.$", "没有 README。"),
    (r"^(\d+) README commands do not exist\.$", "README 中有 \\1 条命令不存在。"),
    (r"^README lacks (.*) commands\.$", "README 缺少 \\1 命令。"),
    (r"^README commands work; a guide gives the lint command\.$", "README 命令可用，且有指南给出 lint 命令。"),
    (r"^README has install, run and test commands; all exist\.$", "README 有安装、运行、测试命令，且都存在。"),
    (r"^No dependencies to keep current\.$", "没有需要保持更新的依赖。"),
    (r"^Update bot misses (.*)\.$", "更新机器人漏了 \\1。"),
    (r"^Lockfile present; no update bot or audit\.$", "有锁文件，但没有更新机器人或审计。"),
    (r"^No lockfile, update bot or audit\.$", "没有锁文件、更新机器人或审计。"),
    (r"^Dependencies are covered and current\.$", "依赖有覆盖且保持最新。"),
    (r"^Update bot or CI audit covers the dependencies\.$", "更新机器人或 CI 审计覆盖了依赖。"),
    (r"^Scripts project\.$", "脚本类项目，不适用。"),
    (r"^Under 3,000 source lines\.$", "源码不足 3,000 行，不适用。"),
    (r"^Architecture rules block in CI; docs are current\.$", "CI 中架构规则阻塞合并，文档是最新的。"),
    (r"^Architecture rules run in blocking CI\.$", "架构规则在阻塞的 CI 中运行。"),
    (r"^Architecture documented, rules not enforced in CI\.$", "有架构文档，但规则未在 CI 中强制。"),
    (r"^Architecture tool configured, rules not enforced in CI\.$", "已配置架构规则工具，但未在 CI 中强制。"),
    (r"^No architecture doc or rule tool\.$", "没有架构文档或规则工具。"),
]


def zh_summary(text):
    """The Chinese summary for an English one; the English text when no template matches."""
    for pattern, template in ZH_SUMMARIES:
        found = re.match(pattern, text)
        if found:
            out = found.expand(template)
            if text.startswith(("Missing:", "README lacks")):
                for word, zh in ZH_WORDS.items():
                    out = re.sub(r"\b%s\b" % word, zh, out)
            return out
    return text


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def blocking(row):
    """A CI row that runs on pull requests and is not swallowed."""
    return row.get("pull_request") in (True, "push-default") and not row.get("non_blocking")


def lang_ok(language, languages):
    return language == "shared" or language in languages


def evidence(row):
    return "%s:%s (%s)" % (row.get("file"), row.get("line"), row.get("tool", row.get("kind", "")))


def words(text):
    return len(text.split())


def slug(text):
    return re.sub(r"[^A-Za-z0-9._/\-]+", "-", text.strip()).strip("-")[:60]


def norm(path):
    path = posixpath.normpath(path)
    return "" if path == "." else path


def under(path, folder):
    """path is folder or inside it ("" and "." are the repository root)."""
    folder = norm(folder)
    path = norm(path)
    return folder == "" or path == folder or path.startswith(folder + "/")


def dir_of(rel):
    return posixpath.dirname(rel) or "."


def suite_scope(path):
    return posixpath.dirname(path) or "." if posixpath.basename(path) in TEST_DIR_NAMES else path


def in_ignored_dir(rel):
    return any(part in IGNORED_SETUP_DIRS for part in rel.split("/")[:-1])


def days_between(later, earlier_iso):
    try:
        then = datetime.datetime.strptime(earlier_iso[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (later - then).days


# --------------------------------------------------------------------------
# Test commands and suites
# --------------------------------------------------------------------------

DIR_FLAGS = {"--prefix", "-C", "--project", "--cwd", "--directory", "--manifest-path"}


def row_dir(row):
    """The folder a CI row ran in, relative to the repository root, or None when no path is known.

    From detect's `dir` (working-directory or a `cd` prefix), a `--prefix`, `-C`, `--project`
    (and `tsc -p`) path of its command, or the folder of the package.json of a followed npm script.
    """
    base = row.get("dir")
    base = norm(base) if base else None
    tokens = []
    for command in (row.get("commands") or [])[:1]:
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
    flags = DIR_FLAGS | ({"-p"} if row.get("tool") == "tsc" else set())
    for index, token in enumerate(tokens):
        flag, _eq, value = token.partition("=")
        if flag in flags and "$" not in token and "{{" not in token:
            if not _eq and index + 1 < len(tokens):
                value = tokens[index + 1]
            if value and "$" not in value:
                if value.endswith(".json") or value.endswith(".toml"):
                    value = posixpath.dirname(value)
                return norm(posixpath.join(base or "", value))
    if base:
        return base
    via = row.get("via_file")
    if via and posixpath.basename(via) == "package.json":
        return norm(dir_of(via))
    return None


def command_reach(row, command, known_dirs):
    """What a test command runs: (paths, names, unresolved) with paths relative to the repository root.

    Empty paths and names with no unresolved variable mean "everything below the
    folder the command runs from" (the folder of package.json for a followed npm
    script, else the repository root); `paths` then holds that folder.
    """
    base = ""
    via = row.get("via_file")
    if via and posixpath.basename(via) == "package.json":
        base = norm(dir_of(via))
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    program = posixpath.basename(tokens[0]) if tokens else ""
    name_flags = NAME_FLAGS.get(program, set())
    paths, names, unresolved = [], [], False
    skip = False
    for index, token in enumerate(tokens[1:], 1):
        if skip:
            skip = False
            continue
        flag, _eq, value = token.partition("=")
        if token.startswith("-"):
            has_value = bool(_eq)
            if flag in name_flags or flag in PATH_FLAGS or flag in VALUE_FLAGS:
                if not has_value and index + 1 < len(tokens):
                    value = tokens[index + 1]
                    skip = True
                    has_value = True
                if not has_value:
                    continue
                if "$" in value or "{{" in value:
                    unresolved = True
                elif flag in name_flags:
                    names.append(value)
                elif flag in PATH_FLAGS:
                    if flag == "--manifest-path":
                        value = dir_of(value)
                    paths.append(norm(posixpath.join(base, value)))
            continue
        if "$" in token or "{{" in token:
            unresolved = True
            continue
        candidate = norm(posixpath.join(base, token))
        looks_like_path = "/" in token or token in (".", "..") or token.endswith((".py", ".ts", ".js", ".rs", ".go"))
        if looks_like_path or any(under(d, candidate) or under(candidate, d) for d in known_dirs if d):
            paths.append(candidate)
    if not paths and not names and not unresolved:
        paths.append(base)
    return paths, names, unresolved


def suite_covered(suite, rows, known_dirs):
    """True, False or "unknown": do the blocking test rows of the suite's language run it."""
    unknown = False
    path = norm(suite["path"])
    for row in rows:
        if not lang_ok(row.get("language"), [suite["language"]]):
            continue
        for command in row.get("commands") or [""]:
            paths, names, unresolved = command_reach(row, command, known_dirs)
            if unresolved and not paths and not names:
                unknown = True
                continue
            if any(under(path, p) or under(p, path) for p in paths):
                return True
            parts = path.split("/")
            if any(n in parts for n in names):
                return True
    return "unknown" if unknown else False


# --------------------------------------------------------------------------
# The scorer
# --------------------------------------------------------------------------

class Scorer(object):
    def __init__(self, det, hot, gh=None, tier1=None, now=None):
        self.det = det
        self.hot = hot or {}
        self.gh = gh if isinstance(gh, dict) and gh.get("available") else None
        self.t1 = tier1 or {}
        self.now = now or datetime.date.today()
        self.subs = sorted(det.get("subprojects") or [], key=lambda s: s["path"])
        self.rows = []
        self.gaps = []
        self.not_applicable = []
        self.sub_index = {s["path"]: i for i, s in enumerate(det.get("subprojects") or [])}
        ci = det.get("ci") or {}
        self.ci_files = ci.get("files") or []
        self.ci_rows_all = [dict(r, ci_file=f["file"]) for f in self.ci_files for r in f.get("tools") or []]
        self.precommit_rows = (det.get("precommit") or {}).get("tools") or []
        self.hot_files = (self.hot.get("files") or [])[:HOTSPOT_TOP]
        self.kinds = {}
        self.suites = {}
        for sub in self.subs:
            self.suites[sub["path"]] = self.suites_of(sub)
        self.known_dirs = sorted({norm(s["path"]) for sub in self.subs for s in self.suites[sub["path"]]} |
                                 {norm(sub["path"]) for sub in self.subs})
        self.test_rows = [r for r in self.ci_rows_all if r.get("category") == "tests" and blocking(r)]
        self.coverage_cache = {}
        for sub in self.subs:
            self.kinds[sub["path"]] = self.sub_kind(sub)
        self.profile = self.make_profile()

    # ---- general helpers ---------------------------------------------

    def langs(self, sub):
        return [lang for lang in LANGUAGES if lang in (sub.get("languages") or [])]

    def owned(self, sub):
        return {sub["path"]} | {m["path"] for m in sub.get("members") or []}

    def scope_match(self, sub, fact_sub, file=None):
        """The fact belongs to the subproject (or sits in a folder above it)."""
        if fact_sub is not None and fact_sub in self.owned(sub):
            return True
        if file is not None and not file.startswith("..") and under(sub["path"], dir_of(file)):
            return True
        return False

    def cfg_rows(self, sub, category):
        rows = list(sub["categories"].get(category) or [])
        rows += [r for r in self.precommit_rows if r.get("category") == category]
        for row in rows:
            row.setdefault("language", TOOL_LANGUAGE.get(row.get("tool"), "shared"))
        return rows

    def in_sub(self, row, sub):
        """A CI row that ran in a folder belongs to the subproject that holds the folder; no known folder: yes."""
        where = row_dir(row)
        if where is None:
            return True
        owner = self.owner_of(where if where else ".")
        return owner is None or owner == sub["path"]

    def ci_of(self, category, languages=None, only_blocking=False, sub=None):
        out = []
        for row in self.ci_rows_all:
            if row.get("category") != category:
                continue
            if sub is not None and not self.in_sub(row, sub):
                continue
            if languages is not None and not lang_ok(row.get("language"), languages):
                continue
            if only_blocking and not blocking(row):
                continue
            out.append(row)
        return out

    def pointer(self, file, *parts):
        return "%s.json#/%s" % (file, "/".join(str(p) for p in parts))

    def gh_get(self, *keys):
        node = self.gh
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node

    def sub_kind(self, sub):
        path = sub["path"]
        under_sub = lambda f: under(f, path)
        docker = [f for f in (self.det.get("setup") or {}).get("dockerfiles") or [] if under_sub(f)]
        docker += [f for f in (self.det.get("setup") or {}).get("compose") or [] if under_sub(f)]
        deploy = [f["file"] for f in self.ci_files if re.search(r"deploy", f["file"], re.I)]
        if sub.get("publishable") and not docker and not deploy:
            return "library"
        if (sub.get("dependencies") or {}).get("direct", 0) == 0:
            return "scripts"
        return "application"

    def make_profile(self):
        count = self.hot.get("active_authors_12m")
        authors = "solo" if isinstance(count, int) and count <= 1 else "team"
        visibility = (self.gh or {}).get("visibility")
        visibility = "public" if visibility == "public" else (
            "private" if visibility in ("private", "internal") else "unknown")
        kinds = set(self.kinds.values())
        kind = "application" if "application" in kinds else ("library" if "library" in kinds else "scripts")
        return {
            "authors": authors, "visibility": visibility, "kind": kind,
            "facts": {
                "authors": ["hotspots.json#/active_authors_12m = %s" % count],
                "visibility": ["ghfacts.json#/visibility = %s" % (self.gh or {}).get("visibility")
                               if self.gh else "ghfacts unavailable"],
                "kind": ["%s: %s" % (s["path"], self.kinds[s["path"]]) for s in self.subs],
            }}

    # ---- rows and gaps ---------------------------------------------------

    def add(self, dim, sub, level, rule, summary, facts, status="checked", partial=None, needs=None):
        if words(summary) > 15:
            raise ValueError("summary too long: " + summary)
        self.rows.append({"id": dim, "subproject": sub, "level": level, "status": status, "rule": rule,
                          "partial": partial, "needs": needs, "facts": list(facts)[:8], "summary": summary,
                          "summary_zh": zh_summary(summary)})

    def gap(self, dim, sub, rule, detail, what, facts, effort, hotspots=(), moot=None):
        gap_id = "%s:%s:%s" % (dim, sub, rule if detail is None else "%s:%s" % (rule, detail))
        if any(g["id"] == gap_id for g in self.gaps):
            return
        if moot:
            self.not_applicable.append({"id": gap_id, "dimension": dim, "subproject": sub, "what": what,
                                        "reason": moot})
            return
        self.gaps.append({"id": gap_id, "dimension": dim, "subproject": sub, "rule": rule, "what": what,
                          "facts": list(facts)[:6], "hotspot_files": list(hotspots), "effort": effort,
                          "priority": 0.0})

    def hot_in(self, sub, languages):
        """Paths of the top hotspots in the subproject with one of the languages, hottest first."""
        out = []
        for item in self.hot_files:
            if self.owner_of(item["path"]) == sub["path"] and item.get("language") in languages:
                out.append(item["path"])
        return out

    def owner_of(self, path):
        best = None
        for sub in self.subs:
            owned = self.owned(sub)
            for candidate in owned:
                if under(path, candidate) and (best is None or len(norm(candidate)) > len(norm(best[1]))):
                    best = (sub["path"], candidate)
        return best[0] if best else None

    # ---- test suites -------------------------------------------------------

    def suites_of(self, sub):
        suites = [dict(s) for s in sub.get("test_suites") or []]
        if suites:
            return suites
        for lang, stats in sorted((sub.get("stats") or {}).items()):
            if stats.get("test_files"):
                suites.append({"path": sub["path"], "language": lang, "files": stats["test_files"],
                               "loc": stats.get("test_loc", 0)})
        return suites

    def suite_state(self, sub, suite):
        key = (sub["path"], suite["path"], suite["language"])
        if key not in self.coverage_cache:
            rows = [r for r in self.test_rows if lang_ok(r.get("language"), self.langs(sub)) and self.in_sub(r, sub)]
            self.coverage_cache[key] = suite_covered(suite, rows, self.known_dirs)
        return self.coverage_cache[key]

    def hotspot_suite(self, item):
        best = None
        for sub in self.subs:
            for suite in self.suites[sub["path"]]:
                if suite["language"] != item.get("language"):
                    continue
                scope = norm(suite_scope(suite["path"]))
                if under(item["path"], scope) and (best is None or len(scope) > len(best[2])):
                    best = (sub, suite, scope)
        return best

    # ---- lint --------------------------------------------------------------

    def lint(self, sub):
        path = sub["path"]
        langs = self.langs(sub)
        if not langs:
            return self.add("lint", path, None, "lint.na", "No source files.", [], status="not_applicable")
        has, block, facts = {}, {}, []
        for lang in langs:
            cfg = [r for r in self.cfg_rows(sub, "lint") if r["language"] == lang]
            ci = self.ci_of("lint", [lang], sub=sub)
            has[lang] = bool(cfg or ci)
            block[lang] = any(blocking(r) for r in ci)
            for row in (cfg + ci)[:1]:
                facts.append(evidence(row))
        have = [l for l in langs if has[l]]
        missing = [l for l in langs if not has[l]]
        partial = None
        if have and missing:
            partial = {"covered": len(have), "total": len(langs), "missing": missing, "unit": "languages"}
        hot = self.hot_in(sub, langs)
        if not have:
            self.add("lint", path, 0, "lint.0", "No linter for %s." % ", ".join(langs), facts)
            self.gap("lint", path, "lint.0", None, "Add a linter for %s and run it in CI" % ", ".join(langs),
                     facts, "add", hot)
            return
        if not all(block[l] for l in langs):
            self.add("lint", path, 1, "lint.1", "Linter configured, not blocking in CI.", facts, partial=partial)
            if missing:
                for lang in missing:
                    self.gap("lint", path, "missing-language", lang, "Add a linter for %s" % lang, facts, "add",
                             self.hot_in(sub, [lang]))
            for lang in have:
                if not block[lang]:
                    self.gap("lint", path, "lint.1", lang, "Run the %s linter as a blocking CI step" % lang, facts,
                             "enforce", self.hot_in(sub, [lang]))
            return
        formats_ok = all(any(blocking(r) and not r.get("writes") for r in self.ci_of("format", [lang], sub=sub))
                         for lang in langs)
        kloc, supp = self.suppression_density(langs)
        notes = ["detect.json#/suppressions: %.1f per 1,000 lines" % supp] if kloc else []
        errors = (self.t1.get("counts") or {}).get("lint:%s" % path, {}).get("errors")
        if formats_ok and supp < SUPPRESSIONS_PER_KLOC:
            if errors == 0:
                return self.add("lint", path, 3, "lint.3", "Blocking linter and formatter check; zero errors.",
                                facts + notes)
            if errors is None:
                self.add("lint", path, 2, "lint.2", "Blocking linter and formatter check in CI.", facts + notes,
                         needs="tier 1 lint count")
                return self.gap("lint", path, "lint.2", None, "Run the tier 1 lint count and fix its errors",
                                facts, "add", hot)
            self.add("lint", path, 2, "lint.2", "Linter blocks in CI, but %d errors remain." % errors,
                     facts + ["tier1: %d lint errors" % errors])
            return self.gap("lint", path, "lint.2", None, "Fix the %d lint errors" % errors, facts, "add", hot)
        self.add("lint", path, 2, "lint.2", "Linter blocks in CI.", facts + notes)
        if not formats_ok:
            self.gap("lint", path, "lint.2", "format-check", "Add a formatter check (no rewrite) to blocking CI",
                     facts, "add", hot)
        else:
            self.gap("lint", path, "lint.2", "suppressions", "Cut lint suppressions under 2 per 1,000 lines",
                     facts + notes, "large", hot)

    def suppression_density(self, langs):
        total = 0
        loc = 0
        for lang in langs:
            total += ((self.det.get("suppressions") or {}).get(lang) or {}).get("total", 0)
            stats = (self.det.get("languages") or {}).get(lang) or {}
            loc += stats.get("loc", 0) + stats.get("test_loc", 0)
        return loc, (total * 1000.0 / loc if loc else 0.0)

    # ---- types -------------------------------------------------------------

    def types(self, sub):
        path = sub["path"]
        langs = self.langs(sub)
        if not langs:
            return self.add("types", path, None, "types.na", "No source files.", [], status="not_applicable")
        per = {}
        for lang in langs:
            per[lang] = self.types_language(sub, lang)
        low = min(per[l][0] for l in langs)
        first = [l for l in langs if per[l][0] == low][0]
        level, rule, facts, needs = per[first]
        covered = [l for l in langs if per[l][0] >= 2]
        partial = None
        if len(langs) > 1 and covered and len(covered) < len(langs):
            partial = {"covered": len(covered), "total": len(langs), "missing": [l for l in langs if l not in covered],
                       "unit": "languages"}
        summary = {"types.0": "No type checker for %s.", "types.1": "Type checker configured, not blocking in CI.",
                   "types.2": "Type checker blocks in CI.", "types.3": "Strict type checker blocks, zero errors.",
                   "types.1c": "CI does not build the code.", "types.2c": "CI builds the code.",
                   "types.3c": "CI builds with warnings as errors."}[rule]
        if "%s" in summary:
            summary = summary % first
        self.add("types", path, level, rule, summary, facts, partial=partial, needs=needs)
        multi = len(langs) > 1
        for lang in langs:
            lvl, lrule, lfacts, lneeds = per[lang]
            if lvl >= 3:
                continue
            detail = lang if multi else None
            hot = self.hot_in(sub, [lang])
            what = {"types.0": "Add a type checker config for %s" % lang,
                    "types.1": "Run the %s type checker as a blocking CI step" % lang,
                    "types.2": "Turn on strict type checking for %s and keep the error count at zero" % lang,
                    "types.1c": "Build the %s code in CI" % lang,
                    "types.2c": "Fail the %s build on warnings in CI" % lang}[lrule]
            effort = "enforce" if lrule in ("types.1", "types.1c") else "add"
            self.gap("types", path, lrule, detail, what, lfacts, effort, hot)

    def types_language(self, sub, lang):
        """(level, rule, facts, needs) of the type rules for one language of a subproject."""
        path = sub["path"]
        if lang in ("python", "typescript"):
            names = ("mypy", "pyright") if lang == "python" else ("tsc",)
            cfg = [r for r in self.cfg_rows(sub, "types") if r["tool"] in names]
            ci = [r for r in self.ci_of("types", [lang], sub=sub) if r["tool"] in names]
            facts = [evidence(r) for r in (cfg + ci)[:2]]
            if not cfg and not ci:
                return 0, "types.0", facts, None
            if not any(blocking(r) for r in ci):
                return 1, "types.1", facts, None
            kinds = STRICT_PYTHON if lang == "python" else ("tsconfig-strict",)
            strict = [f for f in self.det.get("strictness") or []
                      if f["kind"] in kinds and f.get("how") == "config" and f.get("value") is not False
                      and self.scope_match(sub, f.get("subproject"))]
            if not strict:
                return 2, "types.2", facts, None
            facts.append(evidence(strict[0]))
            errors = (self.t1.get("counts") or {}).get("types:%s" % path, {}).get("errors")
            if errors == 0:
                return 3, "types.3", facts, None
            if errors is None:
                return 2, "types.2", facts, "tier 1 type-check count"
            return 2, "types.2", facts + ["tier1: %d type errors" % errors], None
        rows = [r for r in self.ci_rows_all if blocking(r) and r.get("language") == lang and self.in_sub(r, sub)]
        if not rows:
            return 1, "types.1c", [], None
        facts = [evidence(rows[0])]
        strict = [f for f in self.det.get("strictness") or [] if f["kind"] in WARNING_FACTS.get(lang, ())
                  and (f.get("how") in ("ci", "script") or self.scope_match(sub, f.get("subproject")))]
        vet = [r for r in rows if r["tool"] == "go-vet"] if lang == "go" else []
        if strict or vet:
            facts.append(evidence((strict or vet)[0]))
            return 3, "types.3c", facts, None
        return 2, "types.2c", facts, None

    # ---- static, secrets ------------------------------------------------------

    def static(self):
        rows = []
        for sub in self.subs:
            rows += self.cfg_rows(sub, "static")
        rows += [r for r in (self.det.get("shared") or []) if r.get("category") == "static"]
        rows += [r for r in self.precommit_rows if r.get("category") == "static"]
        seen = set()
        local = []
        for row in rows:
            key = (row["tool"], row["file"], row["line"])
            if key not in seen:
                seen.add(key)
                local.append(row)
        ci = self.ci_of("static")
        facts = [evidence(r) for r in (local + ci)[:3]]
        gh_on = [k for k in ("advanced_security", "code_security", "code_scanning_default_setup")
                 if self.gh_get("security_and_analysis", k) == "enabled"] if isinstance(
            self.gh_get("security_and_analysis"), dict) else []
        if gh_on:
            facts.append("ghfacts.json#/security_and_analysis/%s = enabled" % gh_on[0])
        if any(blocking(r) for r in ci) or gh_on:
            alerts = self.gh_get("code_scanning_alerts")
            if isinstance(alerts, dict) and not (alerts.get("high") or alerts.get("critical")):
                return self.add("static", ".", 3, "static.3", "Security analysis blocks; no open serious alerts.",
                                facts)
            self.add("static", ".", 2, "static.2", "Security analysis blocks in CI.", facts,
                     needs=None if isinstance(alerts, dict) else "open code-scanning alert counts (ghfacts has none)")
            return self.gap("static", ".", "static.2", None,
                            "Fix open high and critical code-scanning alerts (check the count first)", facts, "add")
        if local or ci:
            self.add("static", ".", 1, "static.1", "Security analysis configured, not blocking in CI.", facts)
            return self.gap("static", ".", "static.1", None, "Run the security analysis as a blocking CI step",
                            facts, "enforce")
        self.add("static", ".", 0, "static.0", "No static security analysis.", [])
        self.gap("static", ".", "static.0", None, "Add CodeQL or semgrep to pull request CI", [], "add")

    def secrets(self):
        names = ("gitleaks", "trufflehog")
        local = [r for r in (self.det.get("shared") or []) if r.get("tool") in names]
        local += [r for r in self.precommit_rows if r.get("tool") in names]
        ci = [r for r in self.ci_of("secrets") if r["tool"] in names]
        block = [r for r in ci if blocking(r)]
        sa = self.gh_get("security_and_analysis")
        visible = isinstance(sa, dict)
        scanning = visible and sa.get("secret_scanning") == "enabled"
        push = visible and sa.get("secret_scanning_push_protection") == "enabled"
        facts = [evidence(r) for r in (local + ci)[:2]]
        if visible:
            facts.append("ghfacts.json#/security_and_analysis: secret_scanning=%s, push_protection=%s" % (
                sa.get("secret_scanning"), sa.get("secret_scanning_push_protection")))
        if push and block:
            return self.add("secrets", ".", 3, "secrets.3", "Push protection and a blocking CI scanner.", facts)
        if scanning and push:
            self.add("secrets", ".", 2, "secrets.2g", "GitHub secret scanning and push protection on.", facts)
            return self.gap("secrets", ".", "secrets.2g", None, "Add a scanner (gitleaks) to blocking CI", facts, "add")
        if block:
            self.add("secrets", ".", 2, "secrets.2", "A secret scanner blocks in CI.", facts)
            return self.gap("secrets", ".", "secrets.2", None, "Turn on GitHub push protection", facts, "enforce")
        if local or ci or scanning:
            self.add("secrets", ".", 1, "secrets.1", "Secret scanning present, not blocking.", facts)
            return self.gap("secrets", ".", "secrets.1", None, "Run a secret scanner in blocking CI", facts, "enforce")
        if not visible:
            return self.add("secrets", ".", None, "secrets.unknown", "Secret scanning setting not visible.", facts,
                            status="unknown",
                            needs="GitHub secret-scanning setting (needs admin access) or a gitleaks run")
        self.add("secrets", ".", 0, "secrets.0", "No secret scanning.", facts)
        self.gap("secrets", ".", "secrets.0", None, "Add gitleaks to CI and turn on GitHub push protection", facts,
                 "add")

    # ---- tests, coverage ------------------------------------------------------

    def hot_score(self, scope):
        scores = [item.get("score") or 0 for item in self.hot_files if under(item["path"], scope)]
        return max(scores) if scores else 0

    def tests(self, sub):
        path = sub["path"]
        langs = self.langs(sub)
        suites = self.suites[path]
        test_files = sum((s or {}).get("test_files", 0) for s in (sub.get("stats") or {}).values())
        hot = self.hot_in(sub, langs)
        if not suites and not test_files:
            self.add("tests", path, 0, "tests.0", "No test files.", [])
            return self.gap("tests", path, "tests.0", None, "Add tests for the most changed files and run them in CI",
                            [], "add", hot)
        rows = [r for r in self.test_rows if lang_ok(r.get("language"), langs) and self.in_sub(r, sub)]
        state = [(s, self.suite_state(sub, s)) for s in suites]
        covered = [s for s, v in state if v is True]
        missing = sorted([s for s, v in state if v is not True],
                         key=lambda s: (-self.hot_score(suite_scope(s["path"])), s["path"]))
        facts = [evidence(r) for r in rows[:2]]
        if not rows:
            self.add("tests", path, 1, "tests.1", "Tests exist; no blocking CI step runs them.", facts)
            return self.gap("tests", path, "tests.1", None, "Run the tests in pull request CI", facts, "enforce", hot)
        if not covered:
            self.add("tests", path, 1, "tests.1", "Blocking CI test steps do not reach any suite.", facts)
            return self.gap("tests", path, "tests.1", None, "Point a blocking CI test step at the suites", facts,
                            "enforce", hot)
        if missing:
            miss = [s["path"] for s in missing]
            partial = {"covered": len(covered), "total": len(suites), "missing": miss, "unit": "test suites"}
            self.add("tests", path, 1, "tests.1p", "CI runs %d of %d test suites." % (len(covered), len(suites)),
                     facts, partial=partial)
            for suite in missing:
                unknown = self.suite_state(sub, suite) == "unknown"
                scope = norm(suite_scope(suite["path"]))
                held = [p for p in hot if self.hotspot_suite({"path": p, "language": suite["language"]}) and
                        self.hotspot_suite({"path": p, "language": suite["language"]})[1] is not None and
                        norm(suite_scope(self.hotspot_suite({"path": p, "language": suite["language"]})[1]["path"]))
                        == scope]
                self.gap("tests", path, "missing-suite", suite["path"],
                         "Run the %s suite in blocking CI%s" % (suite["path"],
                                                                " (its command uses a variable path)" if unknown else ""),
                         facts + ["detect.json#/subprojects/%s/test_suites: %d files" % (
                             self.sub_index.get(path, 0), suite.get("files", 0))], "enforce", held)
            return
        run = self.tests_health(path)
        if run is True:
            return self.add("tests", path, 3, "tests.3", "Blocking CI runs every suite, and it passes.", facts +
                            self.health_facts())
        if run is None:
            self.add("tests", path, 2, "tests.2", "Blocking CI runs every suite.", facts,
                     needs="ghfacts run history or a tier 1 test run")
        else:
            self.add("tests", path, 2, "tests.2", "Blocking CI runs every suite; results are weak.",
                     facts + self.health_facts())
        self.gap("tests", path, "tests.2", None,
                 "Show the suites pass 90% of runs (tier 1 run or ghfacts)" if run is None else
                 "Fix failing or re-run tests until 90% of runs pass", facts, "add", [])

    def health_facts(self):
        overall = self.gh_get("runs", "overall") or {}
        return ["ghfacts.json#/runs/overall/pass_rate = %s" % overall.get("pass_rate"),
                "ghfacts.json#/runs/overall/rerun_rate = %s" % overall.get("rerun_rate")]

    def tests_health(self, path):
        """True when the history or a tier 1 run is good, False when bad, None when neither exists."""
        overall = self.gh_get("runs", "overall")
        verdicts = []
        if isinstance(overall, dict) and (overall.get("completed") or 0) >= MIN_RUNS and \
                overall.get("pass_rate") is not None:
            rerun = overall.get("rerun_rate")
            verdicts.append(overall["pass_rate"] >= 0.9 and rerun is not None and rerun <= 0.1)
        for run in self.t1.get("suite_runs") or []:
            if run.get("subproject") == path:
                verdicts.append(bool(run.get("passed")) and (run.get("duration_s") or 1e9) < FAST_SUITE_SECONDS)
        if not verdicts:
            return None
        return any(verdicts)

    def coverage(self, sub):
        path = sub["path"]
        langs = self.langs(sub)
        test_files = sum((s or {}).get("test_files", 0) for s in (sub.get("stats") or {}).values())
        if not test_files:
            return self.add("coverage", path, None, "coverage.na", "No tests to measure.", [],
                            status="not_applicable")
        cfg = self.cfg_rows(sub, "coverage")
        ci = [r for r in self.ci_of("coverage", langs, sub=sub) if blocking(r)]
        thresholds = [t for t in self.det.get("coverage_thresholds") or []
                      if THRESHOLD_LANGUAGE.get(t["kind"], "x") in (None, *langs) and
                      (t.get("how") == "ci" or self.scope_match(sub, t.get("subproject")))]
        facts = [evidence(r) for r in (cfg + ci)[:2]] + [evidence(t) for t in thresholds[:1]]
        hot = self.hot_in(sub, langs)
        measured = bool(ci) or any(t.get("how") == "ci" for t in thresholds)
        if thresholds and measured:
            return self.add("coverage", path, 3, "coverage.3", "A coverage threshold fails the build.", facts)
        if measured:
            self.add("coverage", path, 2, "coverage.2", "Blocking CI measures coverage.", facts)
            return self.gap("coverage", path, "coverage.2", None, "Set a coverage threshold that fails the build",
                            facts, "add", hot)
        if cfg or thresholds:
            self.add("coverage", path, 1, "coverage.1", "Coverage configured, not measured in CI.", facts)
            return self.gap("coverage", path, "coverage.1", None, "Measure coverage in blocking CI", facts,
                            "enforce", hot)
        self.add("coverage", path, 0, "coverage.0", "No coverage measurement.", [])
        self.gap("coverage", path, "coverage.0", None, "Measure coverage in CI", [], "add", hot)

    # ---- ci -------------------------------------------------------------------

    def ci(self):
        files = self.ci_files
        facts = ["%s (%s)" % (f["file"], f["provider"]) for f in files[:3]]
        if not files:
            self.add("ci", ".", 0, "ci.0", "No CI configuration.", [])
            return self.gap("ci", ".", "ci.0", None, "Add CI that runs on pull requests", [], "add")
        if not any(f.get("pull_request") in (True, "push-default") for f in files):
            self.add("ci", ".", 1, "ci.1", "CI exists; nothing runs on pull requests.", facts)
            return self.gap("ci", ".", "ci.1", None, "Trigger CI on pull requests", facts, "enforce")
        tested = [r for r in self.rows if r["id"] == "tests" and r["status"] == "checked" and r["level"] is not None]
        with_tests = [r for r in tested if r["rule"] != "tests.0"]
        if not with_tests or any(r["rule"] in ("tests.1",) for r in with_tests):
            self.add("ci", ".", 1, "ci.1", "CI runs on pull requests; tests do not run there.", facts)
            return self.gap("ci", ".", "ci.1", None, "Run the tests on pull requests", facts, "enforce")
        lints = [r for r in self.rows if r["id"] == "lint" and r["status"] == "checked"]
        lint_ok = bool(lints) and all((r["level"] or 0) >= 2 for r in lints)
        if not lint_ok:
            self.add("ci", ".", 2, "ci.2", "Pull requests run the tests; lint is not enforced.", facts)
            return self.gap("ci", ".", "ci.2", None, "Run lint on pull requests", facts, "enforce")
        protection = self.gh_get("branch_protection") or {}
        state = protection.get("state")
        checks = protection.get("required_status_checks") or []
        pointer = "ghfacts.json#/branch_protection/state = %s" % state
        if state == "protected" and checks:
            return self.add("ci", ".", 3, "ci.3a", "Pull requests run tests and lint; checks are required.",
                            facts + [pointer])
        overall = self.gh_get("runs", "overall") or {}
        if self.profile["authors"] == "solo" and (overall.get("completed") or 0) >= MIN_RUNS and \
                (overall.get("pass_rate") or 0) >= 0.9:
            return self.add("ci", ".", 3, "ci.3s", "Solo repository; tests and lint run, main passes.",
                            facts + ["ghfacts.json#/runs/overall/pass_rate = %s" % overall.get("pass_rate")])
        needs = "branch protection (ghfacts; needs admin access)" if state in (None, "not_visible") else None
        self.add("ci", ".", 2, "ci.2", "Tests and lint run on pull requests; required checks unknown."
                 if needs else "Tests and lint run on pull requests; no required checks.", facts + [pointer],
                 needs=needs)
        if not needs:
            self.gap("ci", ".", "ci.2", None, "Require the CI checks on the default branch", facts + [pointer],
                     "enforce")

    def ci_health(self):
        if not self.gh:
            return {"available": False, "why": "ghfacts unavailable"}
        runs = self.gh.get("runs") or {}
        overall = runs.get("overall") or {}
        return {
            "available": True, "completed_runs": overall.get("completed"),
            "default_branch_pass_rate": overall.get("pass_rate"),
            "median_duration_s": overall.get("median_duration_s"), "rerun_rate": overall.get("rerun_rate"),
            "last_failure": overall.get("last_failure"), "workflows": runs.get("workflows") or {},
            "pull_requests": self.gh.get("pull_requests"), "why": None}

    def ci_health_gaps(self):
        health = self.ci_health()
        if not health["available"]:
            return
        rate = health["default_branch_pass_rate"]
        if rate is not None and (health["completed_runs"] or 0) >= MIN_RUNS and rate < 0.8:
            self.gap("ci", ".", "red-main", None,
                     "Fix the failing default branch (pass rate %d%%): a red main teaches people to ignore CI"
                     % round(rate * 100), ["ghfacts.json#/runs/overall/pass_rate = %s" % rate], "add")
        prs = health.get("pull_requests") or {}
        share = prs.get("no_review_share") if isinstance(prs, dict) else None
        if self.profile["authors"] == "solo":
            self.not_applicable.append({"id": "ci:.:required-reviews", "dimension": "ci", "subproject": ".",
                                        "what": "Require reviews before merging",
                                        "reason": "solo repository: one active author"})
        elif share is not None and share >= 0.5:
            self.gap("ci", ".", "unreviewed-merges", None, "Require a review before merging (%d%% merge with none)"
                     % round(share * 100), ["ghfacts.json#/pull_requests/no_review_share = %s" % share], "enforce")

    # ---- setup ----------------------------------------------------------------

    def setup(self, sub):
        path = sub["path"]
        setup = self.det.get("setup") or {}
        kind = self.kinds[path]
        manifests = [m["file"] for m in sub.get("manifests") or []]
        eco = sorted({detect.MANIFESTS.get(posixpath.basename(m)) for m in manifests} - {None})
        needed = kind == "application" and bool(manifests)
        locks = [l for l in setup.get("lockfiles") or [] if self.scope_match(sub, l.get("subproject"), l["file"])]
        lock_ok = {e: any(l["ecosystem"] == e for l in locks) for e in eco}
        pins = [p for p in setup.get("toolchain_pins") or []
                if not in_ignored_dir(p["file"]) and self.scope_match(sub, p.get("subproject"), p["file"])]
        runners = [r for r in setup.get("task_runners") or []
                   if not in_ignored_dir(r["file"]) and self.scope_match(sub, r.get("subproject"), r["file"])]
        commands = [c for c in ((self.det.get("docs") or {}).get("commands") or []) if c.get("check") == "ok"]
        task = bool(runners) or (path == "." and bool(commands))
        facts = []
        conditions = []
        if needed:
            conditions.append(("lockfile", all(lock_ok.values()) if lock_ok else False))
            if locks:
                facts.append("%s (lockfile)" % locks[0]["file"])
        conditions += [("toolchain pin", bool(pins)), ("task entry", task)]
        facts += ["%s:%s (%s)" % (p["file"], p["line"], p["kind"]) for p in pins[:1]]
        facts += ["%s (%s)" % (r["file"], r["kind"]) for r in runners[:1]]
        if not needed:
            facts.append("lockfile not required: %s" % kind)
            self.not_applicable.append({"id": "setup:%s:lockfile" % path, "dimension": "setup", "subproject": path,
                                        "what": "Commit a lockfile", "reason": "%s: no lockfile needed" % kind})
        got = [name for name, ok in conditions if ok]
        lack = [name for name, ok in conditions if not ok]
        if not got:
            level, rule = 0, "setup.0"
        elif lack:
            level, rule = 1, "setup.1"
        else:
            level, rule = 2, "setup.2"
        locked = bool(((self.det.get("ci") or {}).get("locked_installs"))) or bool(setup.get("devcontainer"))
        if rule == "setup.2" and locked:
            level, rule = 3, "setup.3"
        summary = {"setup.0": "No lockfile, toolchain pin or task entry." if needed else "No toolchain pin or task entry.",
                   "setup.1": "Missing: %s." % ", ".join(lack), "setup.2": "Pin, task entry%s present." % (
                       ", lockfile" if needed else ""),
                   "setup.3": "Reproducible setup; CI installs from the lockfile."}[rule]
        self.add("setup", path, level, rule, summary, facts)
        if level < 3:
            what = ("Add " + " and ".join(lack)) if lack else "Install from the lockfile in CI or add a devcontainer"
            self.gap("setup", path, rule, None, what, facts, "add")

    # ---- docs -----------------------------------------------------------------

    def docs(self):
        docs = self.det.get("docs") or {}
        if not docs.get("readme"):
            self.add("docs", ".", 0, "docs.0", "No README.", [])
            return self.gap("docs", ".", "docs.0", None, "Add a README with install, run and test commands", [], "add")
        commands = docs.get("commands") or []
        wrong = [c for c in commands if c.get("check") == "missing"]
        found = {k: (docs.get(k) or {}).get("found") for k in ("install", "run", "test")}
        facts = ["%s:%s (%s)" % (docs["readme"], c["line"], c["why"]) for c in wrong[:3]]
        facts += ["detect.json#/docs/%s/found = %s" % (k, v) for k, v in found.items() if not v]
        if wrong or not all(found.values()):
            lack = [k for k, v in found.items() if not v]
            self.add("docs", ".", 1, "docs.1", ("%d README commands do not exist." % len(wrong)) if wrong
                     else "README lacks %s commands." % ", ".join(lack), facts)
            for command in wrong:
                self.gap("docs", ".", "wrong-command", slug(command["command"]),
                         "Fix the README command `%s` (%s)" % (command["command"], command["why"]),
                         ["%s:%s" % (docs["readme"], command["line"])], "enforce")
            if lack:
                self.gap("docs", ".", "docs.1", None, "Add %s commands to the README" % ", ".join(lack), facts, "add")
            return
        has_lint = any(c.get("kind") == "lint" for c in commands)
        guide = bool(docs.get("contributing")) or any(
            re.search(r"develop|contribut", h.get("text", ""), re.I) for h in docs.get("headings") or [])
        if has_lint and guide:
            return self.add("docs", ".", 3, "docs.3", "README commands work; a guide gives the lint command.", facts)
        self.add("docs", ".", 2, "docs.2", "README has install, run and test commands; all exist.", facts)
        self.gap("docs", ".", "docs.2", None, "Add a CONTRIBUTING file or development section with the lint command",
                 facts, "add")

    # ---- deps -----------------------------------------------------------------

    def ecosystems(self):
        present = set()
        setup = self.det.get("setup") or {}
        for sub in self.subs:
            for manifest in sub.get("manifests") or []:
                lang = detect.MANIFESTS.get(posixpath.basename(manifest["file"]))
                if lang:
                    present.add(ECOSYSTEM_OF_LANGUAGE.get(lang, lang))
        for lock in setup.get("lockfiles") or []:
            present.add(ECOSYSTEM_OF_LANGUAGE.get(lock["ecosystem"], lock["ecosystem"]))
        if setup.get("requirements_files"):
            present.add("python")
        if any(f.get("provider") == "github" for f in self.ci_files):
            present.add("actions")
        return sorted(present)

    def deps(self):
        setup = self.det.get("setup") or {}
        present = self.ecosystems()
        bots = setup.get("update_bots") or []
        locks = setup.get("lockfiles") or []
        audits = [r for r in self.ci_of("deps_audit") if blocking(r)]
        covered = set()
        for bot in bots:
            covered |= set(present) if "*" in bot["ecosystems"] else set(bot["ecosystems"])
        missing = [e for e in present if e not in covered]
        facts = ["%s:%s (%s)" % (b["file"], b["line"], b["tool"]) for b in bots[:2]]
        facts += [evidence(r) for r in audits[:1]]
        facts += ["%s (lockfile)" % l["file"] for l in locks[:1]]
        if not present and not locks and not bots:
            return self.add("deps", ".", None, "deps.na", "No dependencies to keep current.", [],
                            status="not_applicable")
        bot_ok = bool(bots) and not missing
        if bot_ok or audits:
            return self.deps_two(setup, locks, facts)
        if bots and missing:
            partial = {"covered": len(present) - len(missing), "total": len(present), "missing": missing,
                       "unit": "ecosystems"}
            self.add("deps", ".", 1, "deps.1p", "Update bot misses %s." % ", ".join(missing), facts, partial=partial)
            for eco in missing:
                self.gap("deps", ".", "missing-ecosystem", eco, "Add the %s ecosystem to the update bot" % eco, facts,
                         "enforce")
            return
        if locks:
            self.add("deps", ".", 1, "deps.1", "Lockfile present; no update bot or audit.", facts)
            return self.gap("deps", ".", "deps.1", None, "Add dependabot or renovate for %s" % ", ".join(present),
                            facts, "add")
        self.add("deps", ".", 0, "deps.0", "No lockfile, update bot or audit.", facts)
        self.gap("deps", ".", "deps.0", None, "Add dependabot or renovate for %s" % ", ".join(present), facts, "add")

    def deps_two(self, setup, locks, facts):
        recent = bool(locks)
        for lock in locks:
            age = days_between(self.now, lock.get("last_commit") or "")
            if age is None or age > RECENT_DAYS:
                recent = False
        clean = None
        for audit in self.t1.get("audits") or []:
            bad = (audit.get("high") or 0) + (audit.get("critical") or 0)
            clean = bad == 0 if clean is None else (clean and bad == 0)
        if recent or clean:
            return self.add("deps", ".", 3, "deps.3", "Dependencies are covered and current.", facts)
        known = bool(locks) and all(l.get("last_commit") for l in locks)
        needs = None if (known or clean is False) else "lockfile commit dates or a tier 1 audit"
        self.add("deps", ".", 2, "deps.2", "Update bot or CI audit covers the dependencies.", facts, needs=needs)
        self.gap("deps", ".", "deps.2", None, "Refresh the lockfiles and run a dependency audit", facts, "add")

    # ---- arch ---------------------------------------------------------------

    def arch(self, sub):
        path = sub["path"]
        loc = sum((v or {}).get("loc", 0) for v in (sub.get("stats") or {}).values())
        if self.kinds[path] == "scripts" or loc < ARCH_MIN_LOC:
            why = "Scripts project." if self.kinds[path] == "scripts" else "Under 3,000 source lines."
            return self.add("arch", path, None, "arch.na", why, [], status="not_applicable")
        langs = self.langs(sub)
        docs = self.det.get("architecture_docs") or []
        cfg = self.cfg_rows(sub, "arch")
        ci_all = self.ci_of("arch", langs, sub=sub)
        names = sorted({r["tool"] for r in cfg + ci_all})
        facts = ["%s %s%s" % (d["kind"], d["path"], ":%s" % d["line"] if d.get("line") else "") for d in docs[:3]]
        facts += [evidence(r) for r in (cfg + ci_all)[:2]]
        enforced = []
        for name in names:
            row = ([r for r in cfg if r["tool"] == name] + [r for r in ci_all if r["tool"] == name])[0]
            host = row.get("rides_on") or next((r.get("rides_on") for r in cfg if r["tool"] == name), None)
            if host is None:
                ok = any(r["tool"] == name and blocking(r) for r in ci_all)
            elif host == "tests":
                suites = [s for s in self.suites[path] if s["language"] == TOOL_LANGUAGE.get(name, s["language"])
                          or name in ("archunit",)]
                ok = bool(suites) and all(self.suite_state(sub, s) is True for s in suites)
            else:
                ok = any(blocking(r) and r["tool"] == host for r in self.ci_of("lint", langs, sub=sub))
            if ok:
                enforced.append(name)
        members = sub.get("members") or []
        if "rust" in langs and len(members) >= 2 and (sub.get("workspace") or {}).get("kind") == "cargo":
            enforced.append("cargo workspace")
            facts.append("detect.json#/subprojects/%d/members: %d crates" % (self.sub_index.get(path, 0), len(members)))
        if enforced:
            fresh = [d for d in docs if (days_between(self.now, d.get("last_commit") or "") or 1e9) <= 365]
            if fresh:
                return self.add("arch", path, 3, "arch.3", "Architecture rules block in CI; docs are current.", facts)
            self.add("arch", path, 2, "arch.2", "Architecture rules run in blocking CI.", facts)
            return self.gap("arch", path, "arch.2", None, "Update the architecture doc or add an ADR (none changed in 12 months)"
                            if docs else "Write down the architecture: ARCHITECTURE.md or an ADR folder", facts, "add")
        if docs or names:
            self.add("arch", path, 1, "arch.1", "Architecture %s, rules not enforced in CI." % (
                "documented" if docs else "tool configured"), facts)
            if names:
                return self.gap("arch", path, "arch.1", "enforce", "Run %s in blocking CI" % ", ".join(names), facts,
                                "enforce")
            return self.gap("arch", path, "arch.1", "rules", "Add architecture rules to CI (import-linter, ArchUnit, "
                            "dependency-cruiser or similar)", facts, "add")
        self.add("arch", path, 0, "arch.0", "No architecture doc or rule tool.", [])
        self.gap("arch", path, "arch.0", None, "Write ARCHITECTURE.md and add one enforced architecture rule", [], "add")

    # ---- hotspots --------------------------------------------------------------

    def hotspot_table(self):
        out = []
        supp = {}
        for lang_info in (self.det.get("suppressions") or {}).values():
            for item in lang_info.get("top_files") or []:
                supp[item["file"]] = item["count"]
        for index, item in enumerate(self.hot_files):
            match = self.hotspot_suite(item)
            state = False
            suite_path = None
            if match:
                sub, suite, _scope = match
                suite_path = suite["path"]
                state = self.suite_state(sub, suite)
            owner = self.owner_of(item["path"])
            record = [x for x in self.subs if x["path"] == owner]
            linted = any(blocking(r) for r in self.ci_of("lint", [item.get("language")],
                                                         sub=record[0] if record else None))
            out.append({"path": item["path"], "language": item.get("language"), "score": item.get("score"),
                        "loc": item.get("loc"), "commits": item.get("commits"), "authors": item.get("authors"),
                        "top_author_share": item.get("top_author_share"), "tests_in_ci": state,
                        "test_suite": suite_path, "suppressions": supp.get(item["path"]),
                        "linted_in_ci": linted, "rank": index + 1})
        return out

    def hotspot_gaps(self, table):
        for row in table:
            owner = self.owner_of(row["path"]) or "."
            no_tests_at_all = any(r["id"] == "tests" and r["subproject"] == owner and r["rule"] == "tests.0"
                                  for r in self.rows)
            if row["test_suite"] is None and not no_tests_at_all:
                self.gap("hotspots", owner, "no-tests", row["path"],
                         "Add tests for the hotspot %s (no test suite covers it)" % row["path"],
                         ["hotspots.json#/files/%d: %s commits" % (row["rank"] - 1, row["commits"])], "add",
                         [row["path"]])
            share = row.get("top_author_share")
            if self.profile["authors"] == "team" and share is not None and share >= 0.9:
                self.gap("hotspots", owner, "single-author", row["path"],
                         "Spread knowledge of %s: one author wrote %d%% of its changes" % (row["path"], round(share * 100)),
                         ["hotspots.json#/files/%d/top_author_share = %s" % (row["rank"] - 1, share)], "large",
                         [row["path"]])

    # ---- priority -----------------------------------------------------------------

    def prioritise(self):
        top5 = {item["path"] for item in self.hot_files[:5]}
        top15 = {item["path"] for item in self.hot_files}
        for gap in self.gaps:
            weight = WEIGHTS[gap["dimension"]]
            if gap["dimension"] == "secrets" and self.profile["visibility"] != "public":
                weight = 3
            files = gap["hotspot_files"]
            factor = 2.0 if any(f in top5 for f in files) else (1.5 if any(f in top15 for f in files) else 1.0)
            gap["priority"] = round(weight * factor * EFFORT_FACTOR[gap["effort"]], 3)


def build(det, hot, gh=None, tier1=None, decisions=None, previous=None, now=None, compared_with=None,
          input_names=None):
    """score.json as a dict."""
    scorer = Scorer(det, hot, gh, tier1, now)
    for sub in scorer.subs:
        scorer.lint(sub)
        scorer.types(sub)
        scorer.tests(sub)
        scorer.coverage(sub)
        scorer.setup(sub)
        scorer.arch(sub)
    scorer.static()
    scorer.secrets()
    scorer.ci()
    scorer.docs()
    scorer.deps()
    table = scorer.hotspot_table()
    scorer.hotspot_gaps(table)
    scorer.ci_health_gaps()
    scorer.prioritise()
    order = {d: i for i, d in enumerate(DIMENSION_ORDER)}
    scorer.rows.sort(key=lambda r: (order[r["id"]], r["subproject"]))
    dismissed, regressed, deferred = [], [], []
    ranking = []
    for gap in scorer.gaps:
        decision = (decisions or {}).get(gap["id"]) or {}
        status = decision.get("status")
        if status == "dismissed":
            dismissed.append({"id": gap["id"], "what": gap["what"], "reason": decision.get("reason", ""),
                              "date": decision.get("date", "")})
            continue
        if status == "later":
            gap["priority"] = round(gap["priority"] * 0.5, 3)
            gap["decision"] = "later"
            deferred.append(gap["id"])
        if status == "done":
            regressed.append({"id": gap["id"], "what": gap["what"], "reason": decision.get("reason", ""),
                              "date": decision.get("date", "")})
        ranking.append(gap)
    ranking.sort(key=lambda g: (-g["priority"], order[g["dimension"]], g["id"]))
    scorer.not_applicable.sort(key=lambda n: n["id"])
    result = {
        "as_of": scorer.now.isoformat(), "repo": det.get("repo"), "commit": det.get("commit"),
        "default_branch": det.get("default_branch"), "profile": scorer.profile, "dimensions": scorer.rows,
        "hotspots": table, "ci_health": scorer.ci_health(), "gaps": ranking,
        "dismissed": sorted(dismissed, key=lambda d: d["id"]), "regressed": sorted(regressed, key=lambda d: d["id"]),
        "deferred": sorted(deferred), "not_applicable": scorer.not_applicable,
        "tier1": bool(tier1), "inputs": input_names or {}, "changes": None,
    }
    if previous is not None:
        result["changes"] = changes_between(result, previous, compared_with)
    return result


def changes_between(current, previous, compared_with=None):
    """Per-dimension change and gap churn of a score dict against an earlier one."""
    before = {(r["id"], r["subproject"]): r for r in previous.get("dimensions") or []}
    rows = []
    for row in current["dimensions"]:
        old = before.get((row["id"], row["subproject"]))
        if old is None:
            change = "new"
        elif row["level"] is not None and old.get("level") is not None:
            change = "up" if row["level"] > old["level"] else ("down" if row["level"] < old["level"] else "same")
        elif row["level"] == old.get("level") and row["summary"] == old.get("summary") and \
                row["facts"] == old.get("facts"):
            change = "same"
        else:
            change = "changed"
        rows.append({"id": row["id"], "subproject": row["subproject"], "change": change,
                     "before": old.get("level") if old else None, "after": row["level"]})
    now_ids = {g["id"] for g in current["gaps"]}
    handled = now_ids | {d["id"] for d in current["dismissed"]} | {n["id"] for n in current["not_applicable"]}
    old_gaps = {g["id"]: g for g in previous.get("gaps") or []}
    old_ids = set(old_gaps) | {d["id"] for d in previous.get("dismissed") or []}
    closed = [{"id": i, "dimension": old_gaps[i]["dimension"], "what": old_gaps[i]["what"]}
              for i in sorted(set(old_gaps) - handled)]
    return {"compared_with": compared_with, "dimensions": rows,
            "gaps": {"closed": closed, "new": sorted(now_ids - old_ids), "still_open": sorted(now_ids & old_ids)}}


# --------------------------------------------------------------------------
# Decisions and the command line
# --------------------------------------------------------------------------

def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise SystemExit("score.py: cannot read %s %s: %s" % (what, path, exc))


def decide(argv):
    parser = argparse.ArgumentParser(prog="score.py decide", description="Record a decision about a gap.")
    parser.add_argument("gap_id")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dismiss", action="store_const", const="dismissed", dest="status")
    group.add_argument("--later", action="store_const", const="later", dest="status")
    group.add_argument("--done", action="store_const", const="done", dest="status")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--file", default=os.path.join(".repo-health", "decisions.json"))
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    args = parser.parse_args(argv)
    data = {}
    if os.path.exists(args.file):
        data = load_json(args.file, "decisions")
        if not isinstance(data, dict):
            raise SystemExit("score.py: %s must hold a JSON object" % args.file)
    data[args.gap_id] = {"status": args.status, "reason": args.reason, "date": args.date}
    folder = os.path.dirname(os.path.abspath(args.file))
    os.makedirs(folder, exist_ok=True)
    with open(args.file, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    sys.stdout.write("%s: %s\n" % (args.gap_id, args.status))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "decide":
        return decide(argv[1:])
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0] + " See the module docstring for the output.",
        epilog="Decisions: .repo-health/decisions.json maps a gap id to "
               '{"status": "dismissed"|"later"|"done", "reason": "...", "date": "YYYY-MM-DD"}. '
               "A dismissed gap leaves the ranking; later halves its priority; done is informational "
               "(listed under regressed when the gap is detected again). Gap ids are printed in the report "
               'next to each recommendation. `score.py decide ID --dismiss --reason "..."` edits the file.')
    parser.add_argument("--detect", required=True)
    parser.add_argument("--hotspots", required=True)
    parser.add_argument("--ghfacts")
    parser.add_argument("--tier1")
    parser.add_argument("--decisions", help="default: .repo-health/decisions.json in the scanned repository")
    parser.add_argument("--previous", help="an earlier score.json to compare with")
    parser.add_argument("--now", help="YYYY-MM-DD for the lockfile age (default: today)")
    parser.add_argument("-o", "--output")
    args = parser.parse_args(argv)
    det = load_json(args.detect, "detect")
    hot = load_json(args.hotspots, "hotspots")
    gh = load_json(args.ghfacts, "ghfacts") if args.ghfacts else None
    tier1 = load_json(args.tier1, "tier1") if args.tier1 else None
    decisions_path = args.decisions
    if decisions_path is None and det.get("repo"):
        candidate = os.path.join(det["repo"], ".repo-health", "decisions.json")
        decisions_path = candidate if os.path.exists(candidate) else None
    decisions = load_json(decisions_path, "decisions") if decisions_path else None
    previous = load_json(args.previous, "previous score") if args.previous else None
    try:
        now = datetime.date.fromisoformat(args.now) if args.now else None
    except ValueError:
        raise SystemExit("score.py: --now must be YYYY-MM-DD")
    names = {"detect": os.path.basename(args.detect), "hotspots": os.path.basename(args.hotspots)}
    if args.ghfacts:
        names["ghfacts"] = os.path.basename(args.ghfacts)
    result = build(det, hot, gh, tier1, decisions, previous, now,
                   os.path.basename(args.previous) if args.previous else None, names)
    text = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        folder = os.path.dirname(os.path.abspath(args.output))
        os.makedirs(folder, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
