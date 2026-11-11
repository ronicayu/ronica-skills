#!/usr/bin/env python3
"""Tier 0 detection for the repo-health skill.

    detect.py [REPO] [--max-subprojects 10] [--pretty]

Prints one JSON document on stdout: languages and LOC, subprojects (workspace
members under their root) with the lint/format/type/static/test/coverage
configuration found, CI files with the tools their commands run, pre-commit
hooks, strictness and coverage threshold facts, setup files, README commands, docs
and suppression markers. It reads manifests, configs, CI files and the first
200 KB of each source file. It never writes, never runs project code (git runs
with the repository's own fsmonitor, signature, pager, diff and hook commands
switched off; noxfile.py is read as text) and never needs the network. Standard
library only; runs on Python 3.9 and newer.

The TOOLS table below is the single list of tools. The reference files of the
skill name the same tools; tests/test_consistency.py keeps the two in step.

Evidence matches have the shape
    {"tool", "category", "file", "line", "how"}   how = config|ci|precommit|script
with extra keys where useful ("language", "inherited_from", "via", "strict").
TOML section headers are found with a line scanner on every Python version, so
that matches carry line numbers. tomllib (Python 3.11+) only decides whether a
manifest is well formed ("parse_errors").

Top-level keys
    repo, git, git_root, subpath   a folder inside a git repository keeps git: files
                                   come from `git ls-files` of the folder, paths are
                                   relative to it, and CI files and configs above it
                                   are read too ("../x" paths, "inherited_from")
    commit, default_branch
    languages, other_languages     per language {files, loc, test_files, test_loc}
    subprojects[]                  {path, manifest, manifests, languages, stats,
                                   categories, dependencies, workspace, members}.
                                   A workspace root (Cargo [workspace] members, Maven
                                   <modules>, Gradle include(), go.work use, npm and
                                   pnpm workspaces) is one subproject: workspace is
                                   {kind, manifest} and members[] are records of the
                                   same shape (own languages, categories, dependencies;
                                   members[].members is empty). The root's categories
                                   also list the rows of its members ("member": path).
                                   --max-subprojects counts roots only.
    more_subprojects[]             {path, manifest, languages, loc} beyond the cap
    shared[]                       tool rows found at the repo root
    ci                             see below
    precommit                      {config, hooks[], husky[], lefthook[], tools[]}
    strictness[]                   {kind, how: config|ci|script, file, line, subproject,
                                   value?, command?}; kinds: mypy-strict,
                                   mypy-disallow-untyped-defs, pyright-strict,
                                   pyright-strict-paths, tsconfig-strict (value is
                                   true or false), cargo-lints-deny-warnings,
                                   javac-werror, kotlin-all-warnings-as-errors,
                                   clippy-deny-warnings and rustflags-deny-warnings
                                   (CI), go-vet (CI)
    coverage_thresholds[]          same shape; kinds: fail_under, cov-fail-under,
                                   jacoco-violation-rules, kover-min-bound,
                                   vitest-thresholds, jest-coverage-threshold,
                                   codecov-patch-target
    setup                          lockfiles[] ({file, ecosystem, subproject,
                                   last_commit}: committer date of the file's last
                                   commit, ISO 8601, null when not committed, no git
                                   or beyond the first 20), requirements_files,
                                   toolchain_pins[] ({kind, file, line, value?,
                                   subproject}: .python-version, .nvmrc, .node-version,
                                   package.json engines, packageManager and volta,
                                   requires-python, rust-toolchain(.toml), rust-version,
                                   go directive, go toolchain, java.toolchain, wrappers,
                                   .tool-versions, mise.toml, .sdkmanrc, .java-version),
                                   task_runners, devcontainer, dockerfiles, compose
    docs                           readme, headings[], install/run/test ({found, via,
                                   line}), contributing, adr_dirs, architecture_docs,
                                   docs_dir, and commands[] (below)
    suppressions                   per language {total, markers, top_files[]}
    excluded                       {skipped_dirs: [{path, files}], generated, vendored,
                                   migrations (each {count, examples[5]}), symlinks_outside[]}
    parse_errors[]

Exclusions: node_modules, vendor, .venv, venv, __pycache__, .git and similar match at
any depth; build, dist, target, out, bin and obj only at the repo root or at a folder
with a manifest. Source files are left out of LOC, suppression counts and hotspots
(one rule, shared with hotspots.py) when their path says generated (_pb2.py, .min.js,
.d.ts, ...), their first 5 lines say `Code generated ... DO NOT EDIT`, `@generated` or
`auto-generated`, .gitattributes marks them linguist-generated or linguist-vendored, or
they sit in a migrations folder (db/migrate, alembic/versions). A symlink whose target
is outside the repository is never read; it is listed in excluded.symlinks_outside.

ci.files[]
    {file, provider, pull_request, trigger_note, events, tools[], jobs[], installs[],
     inherited_from?}
    pull_request is true, false or "push-default" (CircleCI, Travis, Buildkite, Azure
    Pipelines, Jenkins and Drone build branch pushes by default, as does GitLab with no
    merge request rule: trigger_note says so). For GitHub it comes from on: (pull_request,
    pull_request_target, merge_group) and each job's if: (`github.event_name !=
    'pull_request'`, `github.event_name == 'push'`, `github.ref == 'refs/heads/...'` and
    similar exclude pull requests); for GitLab from rules:, only: and workflow:rules;
    for Bitbucket from the pipelines section (pull-requests: true, default and branches:
    "push-default", custom and tags: false). The file value is the best of its jobs.
    events lists the GitHub triggers. jobs[] is {name, pull_request, rows[]}.
    installs[] is {line, command, manager, packages}: install commands are evidence of
    setup and never count as a run.
    tools[] rows (merged over jobs by tool, via and writes):
        {tool, category, language, file, line, how: "ci", lines[], commands[],
         non_blocking, pull_request, jobs[], via?, via_file?, via_line?, writes?}
    A tool counts only when a command runs it. Commands are split on && || ; | newlines
    and line continuations; env assignments, env, sudo, time, exec, command and nohup
    are stripped; `$(...)` and `bash -c` texts are read. Runners are looked through
    (npx, pnpm exec|dlx, yarn, bunx, uvx, uv run, poetry run, pdm run, pipx run, hatch
    run, python -m, go run module@version, java -jar). cargo, mvn, gradle, ruff, biome and
    go sub-commands decide the row (`ruff format` is ruff-format, `mvn -B verify` runs
    tests unless -DskipTests or -Dmaven.test.skip, `gradle check` also runs the
    verification plugins of the build). npm, pnpm, yarn, bun, make and just names are
    resolved in package.json, Makefile and justfile (pre<name> and post<name> too);
    pnpm --filter, -r, yarn workspaces foreach, npm --workspaces, turbo, nx and lerna
    resolve in every workspace member. Followed files give rows a `via` (the script,
    target, "pre-commit", "tox:<env>", "nox:<session>", "gradle check" or a shell
    script path), `via_file` and `via_line`: pre-commit run reads the hooks of
    .pre-commit-config.yaml (all, or the named one, minus SKIP), tox the commands of its
    envs in tox.ini or pyproject legacy_tox_ini, nox the session.run calls of noxfile.py
    (read as text), shell scripts up to depth 3.
    writes is true for a formatter run that rewrites files or only prints (prettier
    --write, black without --check, gofmt -w, cargo fmt without --check): not a check.
    non_blocking is true when every run of the tool is swallowed: continue-on-error
    (GitHub step or job), allow_failure (GitLab), continueOnError (Azure), soft_fail
    (Buildkite), `|| true`, `|| :`, `|| exit 0`, `|| echo ...`, `; true`, `; exit 0`, or a
    never-fail flag (--exit-zero, --no-fail, --exit-code 0, --issues-exit-code=0).
ci.tools                           {tool: [files]}
ci.locked_installs[]               {kind, file, line, command}: npm ci, pnpm install
                                   --frozen-lockfile, yarn install --immutable or
                                   --frozen-lockfile, bun install --frozen-lockfile, uv
                                   sync --locked or --frozen, poetry install --sync (or
                                   with poetry check --lock), pip install -r of a file
                                   that pins every requirement (== or --hash), cargo
                                   build|test --locked, go mod verify, -mod=readonly

docs.commands[]
    {line, command, kind: install|run|test|lint|build|other, check: ok|missing|unknown,
     why}: commands from README fenced blocks (sh, bash, shell, zsh, console and
     untagged blocks with `$ ` lines or known programs) and inline code that starts with a
     known program, checked without running them: the npm, pnpm, yarn or bun script exists
     in the right package.json (after `cd`), the make target or just recipe exists, the
     repository paths a command names exist, python -m names a module of the repository,
     and the cargo, go, mvn or gradle sub-command is real. unknown means the check needs a
     run or a download.
"""

import argparse
import difflib
import fnmatch
import json
import os
import posixpath
import re
import subprocess
import sys
from collections import defaultdict

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - depends on the interpreter
    tomllib = None

# --------------------------------------------------------------------------
# The tool table
# --------------------------------------------------------------------------
#
# One row per tool: language, tool, category, config evidence, CI words.
#
# Config evidence, each a string:
#   "ruff.toml"                   file glob relative to the subproject
#                                 (the repo root for shared tools); "*" and "?"
#                                 work, "{a,b}" expands, a trailing "/" means a
#                                 directory
#   "pyproject.toml::[tool.ruff]" section in a TOML or INI file; "[tool.ruff]"
#                                 also matches "[tool.ruff.lint]"; a name with
#                                 no closing bracket ("[tool.pylint") is a prefix
#   "package.json::eslintConfig"  key in package.json
#   ".editorconfig::~ktlint_"     file that contains the text
#   "build::checkstyle"           word in pom.xml, build.gradle(.kts),
#                                 settings.gradle(.kts), gradle/libs.versions.toml
# CI words name the program of a command ("ruff", "cargo fmt"), an action in a
# `uses:` line or a pre-commit hook id. They are matched case-insensitively and
# never against the arguments of a command. Some programs (ruff, biome, cargo,
# go, mvn, gradle, pytest, jest, vitest, coverage) are read by CommandReader.
# Words in WHOLE_WORD match as whole words only, so "toxic" is not "tox".

# Commands that run the tests of a Java or Kotlin build.
JVM_TEST_CI = [
    "mvn test", "mvnw test", "gradle test", "gradlew test", "mvn verify",
    "mvnw verify", "gradlew check", "gradle check", "gradlew build",
    "gradle build",
]

# A Kotlin project also gets these rows of the java language.
KOTLIN_FROM_JAVA = ("junit", "jacoco", "spotless", "dependency-check")

WHOLE_WORD = {"tsc", "pmd", "nox", "tox", "c8", "nyc", "jest", "black", "ruff", "knip"}

CATEGORIES = ("lint", "format", "types", "static", "secrets", "tests",
              "coverage", "deps_audit", "deps_bot", "deadcode", "hooks")

TOOLS = [
    # language    tool                  category      config evidence                                                                                                  CI words
    ("python",     "ruff",               "lint",       ["ruff.toml", ".ruff.toml", "pyproject.toml::[tool.ruff]"],                                                      ["ruff"]),
    ("python",     "ruff-format",        "format",     ["pyproject.toml::[tool.ruff.format]"],                                                                          ["ruff format"]),
    ("python",     "flake8",             "lint",       [".flake8", "setup.cfg::[flake8]", "tox.ini::[flake8]"],                                                         ["flake8"]),
    ("python",     "pylint",             "lint",       [".pylintrc", "pylintrc", "pyproject.toml::[tool.pylint"],                                                       ["pylint"]),
    ("python",     "black",              "format",     ["pyproject.toml::[tool.black]"],                                                                                ["black"]),
    ("python",     "isort",              "format",     [".isort.cfg", "pyproject.toml::[tool.isort]"],                                                                  ["isort"]),
    ("python",     "mypy",               "types",      ["mypy.ini", ".mypy.ini", "setup.cfg::[mypy]", "pyproject.toml::[tool.mypy]"],                                   ["mypy"]),
    ("python",     "pyright",            "types",      ["pyrightconfig.json", "pyproject.toml::[tool.pyright]"],                                                        ["pyright"]),
    ("python",     "bandit",             "static",     [".bandit", "pyproject.toml::[tool.bandit]"],                                                                    ["bandit"]),
    ("python",     "pytest",             "tests",      ["pytest.ini", "conftest.py", "pyproject.toml::[tool.pytest.ini_options]", "setup.cfg::[tool:pytest]", "tox.ini::[pytest]"], ["pytest"]),
    ("python",     "unittest",           "tests",      [],                                                                                                              ["unittest"]),
    ("python",     "tox",                "tests",      ["tox.ini"],                                                                                                     ["tox"]),
    ("python",     "nox",                "tests",      ["noxfile.py"],                                                                                                  ["nox"]),
    ("python",     "coverage.py",        "coverage",   [".coveragerc", "pyproject.toml::[tool.coverage", "setup.cfg::[coverage:"],                                      ["coverage", "--cov"]),
    ("python",     "pip-audit",          "deps_audit", [],                                                                                                              ["pip-audit"]),
    ("python",     "vulture",            "deadcode",   ["pyproject.toml::[tool.vulture]"],                                                                              ["vulture"]),

    ("typescript", "eslint",             "lint",       ["eslint.config.{js,mjs,cjs,ts,mts,cts}", ".eslintrc", ".eslintrc.{js,cjs,json,yml,yaml}", "package.json::eslintConfig"], ["eslint"]),
    ("typescript", "biome",              "lint",       ["biome.json", "biome.jsonc"],                                                                                   ["biome"]),
    ("typescript", "oxlint",             "lint",       [".oxlintrc.json"],                                                                                              ["oxlint"]),
    ("typescript", "prettier",           "format",     [".prettierrc", ".prettierrc.*", "prettier.config.*", "package.json::prettier"],                                 ["prettier"]),
    ("typescript", "dprint",             "format",     ["dprint.json", ".dprint.json"],                                                                                 ["dprint"]),
    ("typescript", "tsc",                "types",      ["tsconfig.json"],                                                                                               ["tsc", "typecheck", "type-check"]),
    ("typescript", "jest",               "tests",      ["jest.config.*", "package.json::jest"],                                                                         ["jest"]),
    ("typescript", "vitest",             "tests",      ["vitest.config.*", "vitest.workspace.*"],                                                                       ["vitest"]),
    ("typescript", "mocha",              "tests",      [".mocharc", ".mocharc.*"],                                                                                      ["mocha"]),
    ("typescript", "playwright",         "tests",      ["playwright.config.*"],                                                                                         ["playwright"]),
    ("typescript", "vitest-coverage",    "coverage",   ["vitest.config.{ts,mts,cts,js,mjs,cjs}::~coverage:", "vite.config.{ts,mts,cts,js,mjs,cjs}::~coverage:"],      []),
    ("typescript", "jest-coverage",      "coverage",   ["jest.config.{ts,js,mjs,cjs}::~collectCoverage: true", "jest.config.json::~\"collectCoverage\": true", "package.json::~\"collectCoverage\": true"], []),
    ("typescript", "biome-format",       "format",     ["biome.json::formatter", "biome.jsonc::formatter"],                                                             []),
    ("typescript", "c8",                 "coverage",   [".c8rc", ".c8rc.json"],                                                                                         ["c8"]),
    ("typescript", "nyc",                "coverage",   [".nycrc", ".nycrc.*"],                                                                                          ["nyc"]),
    ("typescript", "npm-audit",          "deps_audit", [],                                                                                                              ["npm audit", "pnpm audit", "yarn audit", "yarn npm audit"]),
    ("typescript", "knip",               "deadcode",   ["knip.json", "knip.jsonc", ".knip.json", "knip.config.*"],                                                      ["knip"]),

    ("rust",       "clippy",             "lint",       ["clippy.toml", ".clippy.toml", "Cargo.toml::[lints.clippy]", "Cargo.toml::[workspace.lints.clippy]"],           ["clippy"]),
    ("rust",       "rustfmt",            "format",     ["rustfmt.toml", ".rustfmt.toml"],                                                                               ["cargo fmt", "rustfmt"]),
    ("rust",       "cargo-test",         "tests",      [],                                                                                                              ["cargo test"]),
    ("rust",       "nextest",            "tests",      [".config/nextest.toml"],                                                                                        ["nextest"]),
    ("rust",       "cargo-llvm-cov",     "coverage",   [],                                                                                                              ["llvm-cov"]),
    ("rust",       "tarpaulin",          "coverage",   ["tarpaulin.toml", ".tarpaulin.toml"],                                                                           ["tarpaulin"]),
    ("rust",       "cargo-deny",         "static",     ["deny.toml"],                                                                                                   ["cargo deny", "cargo-deny"]),
    ("rust",       "cargo-audit",        "deps_audit", [".cargo/audit.toml"],                                                                                           ["cargo audit", "cargo-audit", "audit-check"]),
    ("rust",       "cargo-machete",      "deadcode",   [],                                                                                                              ["machete"]),
    ("rust",       "cargo-udeps",        "deadcode",   [],                                                                                                              ["udeps"]),

    ("java",       "checkstyle",         "lint",       ["checkstyle.xml", "config/checkstyle/*.xml", "build::checkstyle"],                                              ["checkstyle"]),
    ("java",       "pmd",                "lint",       ["build::pmd"],                                                                                                  ["pmd"]),
    ("java",       "spotless",           "format",     ["build::spotless"],                                                                                             ["spotless"]),
    ("java",       "google-java-format", "format",     ["build::google-java-format"],                                                                                   ["google-java-format"]),
    ("java",       "javac-strict",       "types",      ["build::-Werror", "build::-Xlint"],                                                                             []),
    ("java",       "spotbugs",           "static",     ["spotbugs-exclude.xml", "build::spotbugs"],                                                                     ["spotbugs"]),
    ("java",       "error-prone",        "static",     ["build::errorprone"],                                                                                           ["errorprone"]),
    ("java",       "junit",              "tests",      ["build::junit"],                                                                                                JVM_TEST_CI),
    ("java",       "testng",             "tests",      ["build::testng"],                                                                                               JVM_TEST_CI),
    ("java",       "jacoco",             "coverage",   ["build::jacoco"],                                                                                               ["jacoco"]),
    ("java",       "dependency-check",   "deps_audit", ["build::dependency-check"],                                                                                     ["dependency-check"]),

    ("go",         "golangci-lint",      "lint",       [".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json"],                                         ["golangci"]),
    ("go",         "staticcheck",        "lint",       ["staticcheck.conf"],                                                                                            ["staticcheck"]),
    ("go",         "go-vet",             "lint",       [],                                                                                                              ["go vet"]),
    ("go",         "gofmt",              "format",     [],                                                                                                              ["gofmt"]),
    ("go",         "goimports",          "format",     [],                                                                                                              ["goimports"]),
    ("go",         "gofumpt",            "format",     [],                                                                                                              ["gofumpt"]),
    ("go",         "gosec",              "static",     [],                                                                                                              ["gosec"]),
    ("go",         "govulncheck",        "deps_audit", [],                                                                                                              ["govulncheck"]),
    ("go",         "go-test",            "tests",      [],                                                                                                              ["go test"]),
    ("go",         "go-cover",           "coverage",   [],                                                                                                              ["-cover", "-coverprofile"]),
    ("go",         "deadcode",           "deadcode",   [],                                                                                                              ["deadcode"]),

    ("kotlin",     "detekt",             "lint",       ["detekt.yml", "detekt-config.yml", "config/detekt/*.yml", "build::detekt"],                                     ["detekt"]),
    ("kotlin",     "ktlint",             "lint",       [".editorconfig::~ktlint_", "build::ktlint"],                                                                    ["ktlint"]),
    ("kotlin",     "ktfmt",              "format",     ["build::ktfmt"],                                                                                                ["ktfmt"]),
    ("kotlin",     "kotlin-strict",      "types",      ["build::allWarningsAsErrors"],                                                                                  []),
    ("kotlin",     "kotest",             "tests",      ["build::kotest"],                                                                                               JVM_TEST_CI),
    ("kotlin",     "kover",              "coverage",   ["build::kover"],                                                                                                ["kover"]),

    ("shared",     "semgrep",            "static",     [".semgrep.yml", ".semgrep.yaml", ".semgrep/"],                                                                  ["semgrep"]),
    ("shared",     "codeql",             "static",     [".github/workflows/*codeql*"],                                                                                  ["codeql-action", "codeql"]),
    ("shared",     "sonarqube",          "static",     ["sonar-project.properties", "build::sonarqube"],                                                                ["sonar"]),
    ("shared",     "gitleaks",           "secrets",    [".gitleaks.toml", ".gitleaksignore"],                                                                           ["gitleaks"]),
    ("shared",     "trufflehog",         "secrets",    [],                                                                                                              ["trufflehog"]),
    ("shared",     "dependabot",         "deps_bot",   [".github/dependabot.yml", ".github/dependabot.yaml"],                                                           []),
    ("shared",     "renovate",           "deps_bot",   ["renovate.json", "renovate.json5", ".github/renovate.json", ".github/renovate.json5", ".renovaterc", ".renovaterc.json"], []),
    ("shared",     "pre-commit",         "hooks",      [".pre-commit-config.yaml"],                                                                                     ["pre-commit"]),
    ("shared",     "husky",              "hooks",      [".husky/"],                                                                                                     []),
    ("shared",     "lefthook",           "hooks",      ["lefthook.yml", "lefthook.yaml", ".lefthook.yml"],                                                              []),
]

# Suppression markers counted per language (a marker is a plain substring).
SUPPRESSIONS = {
    "python": ["# noqa", "# type: ignore", "# pylint: disable", "# pragma: no cover"],
    "typescript": ["eslint-disable", "@ts-ignore", "@ts-expect-error", "@ts-nocheck", "biome-ignore"],
    "rust": ["#[allow(", "#![allow("],
    "java": ["@SuppressWarnings", "@Suppress(", "NOPMD", "CHECKSTYLE:OFF"],
    "kotlin": ["@SuppressWarnings", "@Suppress(", "NOPMD", "CHECKSTYLE:OFF"],
    "go": ["//nolint", "#nosec"],
}

# --------------------------------------------------------------------------
# Constants for files and languages
# --------------------------------------------------------------------------

# Match at any depth.
SKIP_DIRS = {
    "node_modules", "vendor", ".venv", "venv", ".git",
    "third_party", "__pycache__", ".tox", ".nox", ".eggs", ".mypy_cache",
    ".ruff_cache", ".pytest_cache", ".gradle", ".idea", "site-packages",
    "generated", "__generated__", ".next", ".nuxt", ".repo-health",
}

# Build output folders: skipped only at the repo root or at a subproject root
# (a folder with a manifest), so "internal/build/" of a Go module stays.
ROOT_ONLY_SKIP_DIRS = {"build", "dist", "target", "out", "bin", "obj"}

# Source files that are generated, by name.
GENERATED_NAME = re.compile(
    r"(\.min\.js|\.d\.ts|\.pb\.go|_pb2\.py|_pb2_grpc\.py|\.generated\.[a-z]+|_generated\.[a-z]+)$")

EXT_LANG = {
    ".py": "python",
    ".ts": "typescript", ".tsx": "typescript", ".js": "typescript",
    ".jsx": "typescript", ".mjs": "typescript", ".cjs": "typescript",
    ".rs": "rust",
    ".java": "java",
    ".go": "go",
    ".kt": "kotlin", ".kts": "kotlin",
}

# Languages the skill does not cover; counted by extension and listed.
OTHER_EXT = {
    ".cs": "csharp", ".c": "c/c++", ".h": "c/c++", ".cc": "c/c++",
    ".cpp": "c/c++", ".cxx": "c/c++", ".hpp": "c/c++", ".rb": "ruby",
    ".php": "php", ".swift": "swift", ".scala": "scala",
}

LANGUAGES = ("python", "typescript", "rust", "java", "go", "kotlin")

MANIFESTS = {
    "pyproject.toml": "python", "setup.py": "python", "package.json": "typescript",
    "Cargo.toml": "rust", "pom.xml": "java", "build.gradle": "java",
    "build.gradle.kts": "java", "go.mod": "go", "go.work": "go",
}

BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
               "settings.gradle.kts", "gradle/libs.versions.toml")

READ_LIMIT = 200 * 1024
DEFAULT_MAX_SUBPROJECTS = 10

SECTION_RE = re.compile(r"^\s*\[\[?\s*([^\]\[]+?)\s*\]\]?\s*(#.*)?$")


# --------------------------------------------------------------------------
# Table helpers
# --------------------------------------------------------------------------

def expand_braces(pattern):
    """'a.{js,ts}' -> ['a.js', 'a.ts']."""
    m = re.search(r"\{([^{}]*)\}", pattern)
    if not m:
        return [pattern]
    out = []
    for alt in m.group(1).split(","):
        out.extend(expand_braces(pattern[:m.start()] + alt + pattern[m.end():]))
    return out


def glob_to_regex(pattern):
    out = []
    for ch in pattern:
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
    return re.compile("^" + "".join(out) + "$")


def attr_pattern_regex(pattern):
    """Regex for a .gitattributes pattern, matched against a path relative to that file's folder."""
    anchored = "/" in pattern.rstrip("/")
    directory = pattern.endswith("/")
    pattern = pattern.strip("/")
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    body = "".join(out) + ("/.*" if directory else "")
    return re.compile(("^" if anchored else "^(?:.*/)?") + body + "$")


def word_regex(word, whole):
    """Regex for a CI or build word.

    Words made of word characters must not start inside another word, so
    "go test" is not found in "cargo test". Whole words must not end inside one
    either. A space in a word also matches a hyphen ("ruff format", "ruff-format").
    A word that starts with "-" is a flag and must not follow another "-" or a
    word character ("-cover" is not found in "--coverage").
    """
    body = r"[ \-]".join(re.escape(part) for part in word.split(" "))
    if word.startswith("-"):
        return r"(?<![\w-])" + body
    start = r"(?<![A-Za-z0-9_])"
    return start + body + (r"(?![A-Za-z0-9_])" if whole else "")


def build_ci_regex(words):
    parts = [word_regex(w.lower(), w.lower() in WHOLE_WORD) for w in words]
    return re.compile("|".join(parts)) if parts else None


class Tool(object):
    """One row of TOOLS, with its patterns prepared."""

    def __init__(self, row):
        self.language, self.name, self.category, specs, ci_words = row
        self.specs = []
        for spec in specs:
            self.specs.extend(expand_braces(spec))
        self.ci_words = list(ci_words)
        self.ci_regex = build_ci_regex(self.ci_words)

    def ci_match(self, text_lower):
        return bool(self.ci_regex and self.ci_regex.search(text_lower))


ALL_TOOLS = [Tool(row) for row in TOOLS]


def tools_for_language(language):
    """The tool rows that apply to a subproject of the given language."""
    out = []
    for tool in ALL_TOOLS:
        if tool.language == language:
            out.append(tool)
        elif language == "kotlin" and tool.language == "java" and tool.name in KOTLIN_FROM_JAVA:
            out.append(tool)
    return out


def tool_names_by_language():
    result = defaultdict(set)
    for tool in ALL_TOOLS:
        result[tool.language].add(tool.name)
    return dict(result)


# --------------------------------------------------------------------------
# Repository access
# --------------------------------------------------------------------------

# A repository's own config can name commands (core.fsmonitor, gpg.program with
# log.showSignature, diff.external, hooks). Never let a repository under review run one.
GIT_SAFE = ["-c", "core.fsmonitor=false", "-c", "log.showSignature=false", "-c", "core.pager=cat",
            "-c", "diff.external=", "-c", "core.hooksPath=/dev/null"]


def run_git(root, args):
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    env.pop("GIT_EXTERNAL_DIFF", None)
    try:
        proc = subprocess.run(["git"] + GIT_SAFE + args, cwd=root, env=env, timeout=120,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def git_toplevel(root):
    """Real path of the work tree that contains root, or None."""
    out = run_git(root, ["rev-parse", "--show-toplevel"])
    if not out:
        return None
    top = out.decode("utf-8", "replace").strip()
    return os.path.realpath(top) if top else None


def inside(path, fence):
    return path == fence or path.startswith(fence.rstrip(os.sep) + os.sep)


def dir_of(rel):
    return posixpath.dirname(rel) or "."


def join(d, name):
    return name if d == "." else d + "/" + name


def count_files(path, cap=200000):
    total = 0
    for _dirpath, _dirnames, filenames in os.walk(path):
        total += len(filenames)
        if total >= cap:
            return cap
    return total


# Folders above a scanned subfolder that still govern it: their CI files and configs.
ABOVE_CI_DIRS = (".github/workflows", ".gitlab", ".circleci", ".buildkite", "azure-pipelines",
                 ".azure-pipelines")


def ancestors(d):
    """['a/b', 'a', '.'] for 'a/b'."""
    chain = [d]
    while d != ".":
        d = dir_of(d)
        chain.append(d)
    return chain


class Repo(object):
    """The files of a repository or of a folder inside one.

    Paths are relative to the scanned folder. When the folder is inside a larger
    git repository, git still lists the files (git_root, subpath), and the CI files
    and the files directly in the folders above it are reachable as "../x" paths
    (self.above); they govern the folder but are not part of its sources.
    """

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.git_root = git_toplevel(self.root)
        self.is_git = self.git_root is not None
        real = os.path.realpath(self.root)
        self.subpath = "."
        if self.is_git:
            relative = os.path.relpath(real, self.git_root)
            self.subpath = "." if relative == "." else relative.replace(os.sep, "/")
        self.fence = self.git_root or real
        self.skipped = defaultdict(int)
        self.symlinks_outside = []
        self.above = []
        self.files = self._list_files()
        self.file_set = set(self.files) | set(self.above)
        self.by_dir = defaultdict(set)
        self.by_name = defaultdict(list)
        self.dirs = set()
        for rel in self.files + self.above:
            d = dir_of(rel)
            self.by_dir[d].add(posixpath.basename(rel))
            self.by_name[posixpath.basename(rel)].append(rel)
        for rel in self.files:
            d = dir_of(rel)
            while d not in self.dirs:
                self.dirs.add(d)
                if d == ".":
                    break
                d = dir_of(d)
        self.parse_errors = {}
        self._text = {}
        self._json = {}
        self._sections = {}
        self._attr_rules = None

    # -- listing --------------------------------------------------------

    def top_rel(self, rel):
        """The path of a file relative to the git root (or to the folder without git)."""
        return posixpath.normpath(posixpath.join(self.subpath, rel))

    def up_dirs(self):
        """['..', '../..', ...] up to the git root."""
        count = 0 if self.subpath == "." else len(self.subpath.split("/"))
        return ["/".join([".."] * (i + 1)) for i in range(count)]

    def ancestor_dirs(self, d):
        """Like ancestors(d), continuing above the folder up to the git root."""
        chain = ancestors(d)
        if chain[-1] == ".":
            chain.extend(self.up_dirs())
        return chain

    def _list_files(self):
        names = None
        if self.is_git:
            names = self._git_names()
        if names is None:
            names = self._walk_names()
        manifest_dirs = {"."} | {dir_of(n) for n in names
                                 if posixpath.basename(n) in MANIFESTS and self._skip_dir(n, {"."}) is None}
        seen = set()
        files = []
        for rel in names:
            if rel in seen:
                continue
            seen.add(rel)
            hit = self._skip_dir(rel, manifest_dirs)
            if hit is not None:
                self.skipped[hit] += 1
                continue
            if self._usable(rel):
                files.append(rel)
        return files

    @staticmethod
    def _skip_dir(rel, manifest_dirs):
        """The skipped folder that holds rel, or None."""
        parts = rel.split("/")[:-1]
        for i, part in enumerate(parts):
            if part in SKIP_DIRS or part.endswith(".egg-info"):
                return "/".join(parts[:i + 1])
            if part in ROOT_ONLY_SKIP_DIRS and ("/".join(parts[:i]) or ".") in manifest_dirs:
                return "/".join(parts[:i + 1])
        return None

    def _usable(self, rel):
        """True for a regular file; a symlink that leaves the repository is recorded and refused."""
        full = os.path.join(self.root, rel)
        if os.path.islink(full):
            if not inside(os.path.realpath(full), self.fence):
                self.symlinks_outside.append(rel)
                return False
        return os.path.isfile(full)

    def _git_names(self):
        sub = self.subpath
        spec = []
        if sub != ".":
            spec = ["--", sub]
            parent = sub
            while parent != ".":
                parent = dir_of(parent)
                spec.append(":(glob)*" if parent == "." else ":(glob)%s/*" % parent)
            spec.extend(":(glob)%s/**" % d for d in ABOVE_CI_DIRS)
        out = run_git(self.git_root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"] + spec)
        if out is None:
            return None
        names = []
        for name in out.decode("utf-8", "replace").split("\0"):
            if not name:
                continue
            if sub == ".":
                names.append(name)
            elif name.startswith(sub + "/"):
                names.append(name[len(sub) + 1:])
            else:
                self.above.append(self._relative_above(name))
        if sub != "." and not names:
            return None
        return names

    def _relative_above(self, top_name):
        """'../..' style path from the folder to a git-root-relative path."""
        up = len(self.subpath.split("/"))
        common = 0
        parts = top_name.split("/")
        sub_parts = self.subpath.split("/")
        while common < min(len(parts) - 1, len(sub_parts)) and parts[common] == sub_parts[common]:
            common += 1
        return "/".join([".."] * (up - common) + parts[common:])

    def _walk_names(self):
        names = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            relative = os.path.relpath(dirpath, self.root)
            rel_dir = "." if relative == "." else relative.replace(os.sep, "/")
            is_project = rel_dir == "." or any(f in MANIFESTS for f in filenames)
            keep = []
            for d in dirnames:
                child = join(rel_dir, d)
                full = os.path.join(dirpath, d)
                if os.path.islink(full):
                    if not inside(os.path.realpath(full), self.fence):
                        self.symlinks_outside.append(child)
                elif d in SKIP_DIRS or d.endswith(".egg-info") or (d in ROOT_ONLY_SKIP_DIRS and is_project):
                    count = count_files(full)
                    if count:
                        self.skipped[child] += count
                else:
                    keep.append(d)
            dirnames[:] = keep
            for name in filenames:
                names.append(join(rel_dir, name))
        return names

    # -- excluded files --------------------------------------------------

    def attr_rules(self):
        """[(directory, regex, attribute, value)] from every .gitattributes, outer folders first."""
        if self._attr_rules is None:
            rules = []
            found = sorted(self.by_name.get(".gitattributes", []), key=lambda r: (-r.count("../"), r))
            for rel in found:
                base = dir_of(self.top_rel(rel))
                base = "" if base == "." else base
                for line in self.text(rel).splitlines():
                    parts = line.split()
                    if len(parts) < 2 or parts[0].startswith("#"):
                        continue
                    for token in parts[1:]:
                        m = re.match(r"^([-!]?)(linguist-(?:generated|vendored))(?:=(\w+))?$", token)
                        if not m:
                            continue
                        value = not m.group(1) and (m.group(3) is None or m.group(3).lower() in ("true", "1"))
                        rules.append((base, attr_pattern_regex(parts[0]), m.group(2), value))
            self._attr_rules = rules
        return self._attr_rules

    def attribute(self, rel, name):
        top = self.top_rel(rel)
        value = False
        for base, regex, attr, flag in self.attr_rules():
            if attr != name:
                continue
            if base:
                if not top.startswith(base + "/"):
                    continue
                relative = top[len(base) + 1:]
            else:
                relative = top
            if regex.match(relative):
                value = flag
        return value

    def exclusion_kind(self, rel, head=b""):
        """'vendored', 'generated', 'migrations' or None for a source file.

        head is the start of the file; the generated markers are looked for in
        its first 5 lines. One rule for LOC, suppressions and hotspots.
        """
        if self.attribute(rel, "linguist-vendored"):
            return "vendored"
        if GENERATED_NAME.search(rel) or self.attribute(rel, "linguist-generated"):
            return "generated"
        text = "\n".join(head.decode("utf-8", "replace").splitlines()[:5])
        low = text.lower()
        if ("Code generated" in text and "DO NOT EDIT" in text) or "@generated" in low or "auto-generated" in low:
            return "generated"
        dirs = rel.split("/")[:-1]
        if "migrations" in dirs or dirs[-2:] == ["db", "migrate"] or dirs[-2:] == ["alembic", "versions"]:
            return "migrations"
        return None

    # -- file contents --------------------------------------------------

    def text(self, rel, limit=1024 * 1024):
        if rel not in self._text:
            try:
                with open(os.path.join(self.root, rel), "rb") as handle:
                    data = handle.read(limit)
                self._text[rel] = data.decode("utf-8", "replace")
            except OSError:
                self._text[rel] = ""
        return self._text[rel]

    def json_file(self, rel):
        """(object or None, error or None); records parse errors once."""
        if rel not in self._json:
            text = self.text(rel)
            try:
                self._json[rel] = (json.loads(text), None)
            except ValueError as exc:
                msg = str(exc)
                self._json[rel] = (None, msg)
                self.parse_errors[rel] = msg
        return self._json[rel]

    def check_toml(self, rel):
        if tomllib is None:
            return
        try:
            tomllib.loads(self.text(rel))
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            self.parse_errors[rel] = str(exc)

    def sections(self, rel):
        """[(normalised header name, line)] for a TOML or INI file."""
        if rel not in self._sections:
            found = []
            for number, line in enumerate(self.text(rel).splitlines(), 1):
                m = SECTION_RE.match(line)
                if m:
                    found.append((re.sub(r"\s+", "", m.group(1)), number))
            self._sections[rel] = found
        return self._sections[rel]

    # -- config evidence ------------------------------------------------

    def match_spec(self, spec, d):
        """Look for one evidence spec in directory d. -> (file, line) or None."""
        if spec.startswith("build::"):
            return self._match_build(spec[len("build::"):], d)
        if "::" in spec:
            fname, rest = spec.split("::", 1)
            rel = join(d, fname)
            if rel not in self.file_set:
                return None
            if rest.startswith("["):
                return self._match_section(rel, rest)
            if rest.startswith("~"):
                return self._match_contains(rel, rest[1:])
            return self._match_json_key(rel, rest)
        if spec.endswith("/"):
            target = join(d, spec.rstrip("/"))
            return (target + "/", 1) if target in self.dirs else None
        dir_part, base = posixpath.split(spec)
        target = join(d, dir_part) if dir_part else d
        names = self.by_dir.get(target)
        if not names:
            return None
        if "*" in base or "?" in base:
            regex = glob_to_regex(base)
            for name in sorted(names):
                if regex.match(name):
                    return (join(target, name), 1)
            return None
        return (join(target, base), 1) if base in names else None

    def _match_section(self, rel, spec):
        closed = spec.endswith("]")
        name = re.sub(r"\s+", "", spec[1:-1] if closed else spec[1:])
        for header, line in self.sections(rel):
            if closed and (header == name or header.startswith(name + ".")):
                return (rel, line)
            if not closed and header.startswith(name):
                return (rel, line)
        return None

    def _match_contains(self, rel, needle):
        for number, line in enumerate(self.text(rel).splitlines(), 1):
            if needle in line:
                return (rel, number)
        return None

    def _match_json_key(self, rel, key):
        obj, error = self.json_file(rel)
        pattern = re.compile(r'^\s*"' + re.escape(key) + r'"\s*:', re.M)
        if error is None:
            if not isinstance(obj, dict) or key not in obj:
                return None
        m = pattern.search(self.text(rel))
        if m:
            return (rel, self.text(rel).count("\n", 0, m.start()) + 1)
        return (rel, 1) if error is None else None

    def _match_build(self, word, d):
        whole = word.lower() in WHOLE_WORD or word == "pmd"
        regex = re.compile(word_regex(word, whole), re.I)
        for name in BUILD_FILES:
            rel = join(d, name)
            if rel not in self.file_set:
                continue
            for number, line in enumerate(self.text(rel).splitlines(), 1):
                if regex.search(line):
                    return (rel, number)
        return None


# --------------------------------------------------------------------------
# YAML and shell text: command lines
# --------------------------------------------------------------------------

CMD_KEYS = {
    "run", "uses", "script", "before_script", "after_script", "command",
    "commands", "cmd", "cmds", "bash", "powershell", "pwsh", "entrypoint",
}
KEY_RE = re.compile(r"^(?P<pre>\s*(?:-\s+)*)(?P<key>[A-Za-z_][\w-]*)\s*:(?:\s+(?P<val>.*))?$")


def yaml_commands(text, keys=CMD_KEYS):
    """[(line, command text)] taken from the command keys of a YAML file.

    A scalar value, a block scalar (run: |) and a list under script: all count.
    This is a line scanner, not a YAML parser.
    """
    out = []
    block_col = None
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        stripped = raw.lstrip(" ")
        indent = len(raw) - len(stripped)
        if block_col is not None:
            if indent > block_col or (indent == block_col and stripped.startswith("- ")):
                if not stripped.startswith("#"):
                    out.append((number, stripped.strip()))
                continue
            block_col = None
        if stripped.startswith("#"):
            continue
        m = KEY_RE.match(raw)
        if not m or m.group("key") not in keys:
            continue
        col = len(m.group("pre"))
        value = (m.group("val") or "").strip()
        if value and value[0] not in "|>":
            out.append((number, value))
        else:
            block_col = col
    return out


def shell_commands(text):
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "//")):
            out.append((number, stripped))
    return out


def make_recipes(text, is_just=False):
    """{target: (line, [command lines], [prerequisites])} for a Makefile or justfile."""
    targets = {}
    current = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            if current is not None:
                targets[current][1].append(line.strip())
            continue
        m = re.match(r"^([A-Za-z0-9_.\-/]+)(?:\s+[^:=]*)?:(?!=)\s*(.*)$", line)
        if m and not line.startswith("."):
            current = m.group(1)
            deps = [d for d in m.group(2).split() if re.match(r"^[A-Za-z0-9_.\-/]+$", d)]
            targets[current] = (number, [], deps)
        else:
            current = None
    return targets


# --------------------------------------------------------------------------
# A small YAML reader (CI files only)
# --------------------------------------------------------------------------

class YStr(str):
    """A scalar; .line is the line of its first character (of the first content line for | and >)."""
    line = 0


class YMap(dict):
    """A mapping; .lines[key] is the line of the key."""
    lines = {}  # type: dict


class YSeq(list):
    """A sequence; .lines[i] is the line of item i."""
    lines = []  # type: list


BLOCK_HEADER = re.compile(r"^[|>][+\-0-9]*\s*(#.*)?$")


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def split_key(content):
    """(key, rest) of a `key: rest` line, or None when the line is not a mapping entry."""
    if content[0] in "\"'":
        quote = content[0]
        i = 1
        while i < len(content):
            if content[i] == "\\" and quote == '"':
                i += 2
                continue
            if content[i] == quote:
                if quote == "'" and content[i + 1:i + 2] == "'":
                    i += 2
                    continue
                break
            i += 1
        else:
            return None
        m = re.match(r"^\s*:(?:\s+(.*))?$", content[i + 1:])
        return (content[1:i], m.group(1) or "") if m else None
    if content[0] in "[{&*!%@`|>#?-":
        return None
    m = re.search(r":(?:\s|$)", content)
    if not m:
        return None
    key = content[:m.start()].strip()
    if not key or " #" in key:
        return None
    return key, content[m.end():].strip()


def _unquote(text):
    """(value, rest after the closing quote) of text that starts with a quote, or None."""
    quote = text[0]
    out = []
    i = 1
    while i < len(text):
        ch = text[i]
        if quote == '"' and ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
            i += 2
            continue
        if ch == quote:
            if quote == "'" and text[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), text[i + 1:]
        out.append(ch)
        i += 1
    return None


class _YamlReader(object):
    def __init__(self, text):
        self.raw = text.replace("\r", "").split("\n")
        self.n = len(self.raw)
        self.i = 0

    def _skip(self):
        while self.i < self.n:
            stripped = self.raw[self.i].strip()
            if stripped == "" or stripped.startswith("#") or stripped in ("---", "...") or stripped.startswith("%"):
                self.i += 1
            else:
                return True
        return False

    def _scalar(self, text, line):
        node = YStr(text)
        node.line = line
        return node

    def parse(self):
        if not self._skip():
            return YMap()
        return self.block(_indent(self.raw[self.i]), -1)

    def block(self, ind, parent):
        line = self.raw[self.i]
        content = line.strip()
        if content.startswith("- ") or content == "-":
            return self.seq(ind)
        if split_key(content):
            return self.mapping(ind)
        lineno = self.i + 1
        self.i += 1
        return self.value(content, parent, lineno)

    def mapping(self, ind):
        node = YMap()
        node.lines = {}
        while self._skip():
            line = self.raw[self.i]
            current = _indent(line)
            if current < ind:
                break
            content = line.strip()
            if current > ind:
                self.i += 1
                continue
            if content.startswith("- ") or content == "-":
                break
            pair = split_key(content)
            if pair is None:
                self.i += 1
                continue
            lineno = self.i + 1
            self.i += 1
            node[pair[0]] = self.value(pair[1], ind, lineno)
            node.lines[pair[0]] = lineno
        return node

    def seq(self, ind):
        node = YSeq()
        node.lines = []
        while self._skip():
            line = self.raw[self.i]
            content = line.strip()
            if _indent(line) != ind or not (content.startswith("- ") or content == "-"):
                break
            lineno = self.i + 1
            body = content[1:]
            text = body.lstrip(" ")
            if text == "" or text.startswith("#"):
                self.i += 1
                if self._skip() and _indent(self.raw[self.i]) > ind:
                    item = self.block(_indent(self.raw[self.i]), ind)
                else:
                    item = self._scalar("", lineno)
            else:
                column = ind + 1 + len(body) - len(text)
                self.raw[self.i] = " " * column + text
                item = self.block(column, ind)
            node.append(item)
            node.lines.append(lineno)
        return node

    def value(self, rest, ind, lineno):
        """The value after `key:` (or a bare sequence item); the line has been consumed."""
        rest = re.sub(r"^(?:[&!]\S+\s*)+", "", rest)
        if rest == "" or rest.startswith("#"):
            if self._skip():
                following = self.raw[self.i]
                content = following.strip()
                if _indent(following) > ind:
                    return self.block(_indent(following), ind)
                if _indent(following) == ind and (content.startswith("- ") or content == "-"):
                    return self.seq(ind)
            return self._scalar("", lineno)
        if BLOCK_HEADER.match(rest):
            return self.block_scalar(rest[0], ind)
        if rest[0] in "[{":
            text = rest
            while self._unbalanced(text) and self.i < self.n:
                text += " " + self.raw[self.i].strip()
                self.i += 1
            return self._flow(text, 0, lineno)[0]
        if rest[0] in "\"'":
            text = rest
            parsed = _unquote(text)
            while parsed is None and self.i < self.n:
                text += " " + self.raw[self.i].strip()
                self.i += 1
                parsed = _unquote(text)
            return self._scalar(parsed[0] if parsed else text, lineno)
        text = re.sub(r"\s+#.*$", "", rest)
        while self.i < self.n and self.raw[self.i].strip() and _indent(self.raw[self.i]) > ind \
                and not self.raw[self.i].strip().startswith("#"):
            text += " " + re.sub(r"\s+#.*$", "", self.raw[self.i].strip())
            self.i += 1
        return self._scalar(text, lineno)

    @staticmethod
    def _unbalanced(text):
        depth = 0
        quote = None
        for ch in text:
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
        return depth > 0

    def _flow(self, text, i, lineno):
        while i < len(text) and text[i] == " ":
            i += 1
        if i >= len(text):
            return self._scalar("", lineno), i
        if text[i] == "[":
            node = YSeq()
            node.lines = []
            i += 1
            while i < len(text):
                while i < len(text) and text[i] in " ,":
                    i += 1
                if i >= len(text) or text[i] == "]":
                    i += 1
                    break
                before = i
                item, i = self._flow(text, i, lineno)
                if i == before:
                    i += 1
                    continue
                node.append(item)
                node.lines.append(lineno)
            return node, i
        if text[i] == "{":
            node = YMap()
            node.lines = {}
            i += 1
            while i < len(text):
                while i < len(text) and text[i] in " ,":
                    i += 1
                if i >= len(text) or text[i] == "}":
                    i += 1
                    break
                before = i
                key, i = self._flow_scalar(text, i, ":,}")
                while i < len(text) and text[i] == " ":
                    i += 1
                if i == before:
                    i += 1
                    continue
                if i < len(text) and text[i] == ":":
                    item, i = self._flow(text, i + 1, lineno)
                else:
                    item = self._scalar("", lineno)
                node[key] = item
                node.lines[key] = lineno
            return node, i
        value, i = self._flow_scalar(text, i, ",]}")
        return self._scalar(value, lineno), i

    @staticmethod
    def _flow_scalar(text, i, stops):
        if text[i] in "\"'":
            parsed = _unquote(text[i:])
            if parsed:
                return parsed[0], len(text) - len(parsed[1])
        start = i
        while i < len(text) and text[i] not in stops:
            i += 1
        return text[start:i].strip(), i

    def block_scalar(self, style, parent):
        start = self.i
        lines = []
        content_indent = None
        while self.i < self.n:
            line = self.raw[self.i]
            if line.strip() == "":
                lines.append("")
                self.i += 1
                continue
            current = _indent(line)
            if content_indent is None:
                if current <= parent:
                    break
                content_indent = current
            if current < content_indent:
                break
            lines.append(line[content_indent:])
            self.i += 1
        while lines and lines[-1] == "":
            lines.pop()
        if style == ">":
            parts = []
            words = []
            for item in lines:
                if item == "":
                    parts.append(" ".join(words))
                    words = []
                else:
                    words.append(item.strip())
            parts.append(" ".join(words))
            text = "\n".join(parts)
        else:
            text = "\n".join(lines)
        return self._scalar(text, start + 1)


def parse_yaml(text):
    """A tolerant reading of the YAML subset CI files use: nested maps and lists, scalars,
    block scalars and one-line flow lists. Never raises; anchors and tags are ignored."""
    try:
        return _YamlReader(text).parse()
    except (IndexError, RecursionError, ValueError):
        return YMap()


# --------------------------------------------------------------------------
# Shell text: simple commands
# --------------------------------------------------------------------------

SHELL_KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "for", "case", "esac",
                  "{", "}", "(", ")", "!", "select", "function"}
REDIRECT_RE = re.compile(r"^\d*(?:>>?|<|&>>?|>&)(?:&?\d+|-)?$|^\d*(?:>>?|<|&>>?)&?\S+$")
REDIRECT_TAKES_NEXT = re.compile(r"^\d*(?:>>?|<|&>>?|>&)$")


class Unit(object):
    """One simple command: its words, its line offset in the text, whether its failure is swallowed."""

    def __init__(self, argv, line, swallowed):
        self.argv = argv
        self.line = line
        self.swallowed = swallowed


def _balanced_end(text, i):
    """Index after the ")" that closes the "(" at text[i], or len(text)."""
    depth = 0
    quote = None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def shell_tokens(text):
    """[(kind, text, line)] with kind "w" (a word) or "op" (&&, ||, |, ; or a newline)."""
    tokens = []
    word = []
    word_line = 0
    line = 0
    i = 0
    n = len(text)
    heredocs = []
    state = {"delimiter": False}

    def flush():
        if not word:
            return
        value = "".join(word)
        del word[:]
        if state["delimiter"]:
            heredocs.append(value.strip("'\""))
            state["delimiter"] = False
            return
        m = re.match(r"^\d*<<-?(?!<)(.*)$", value)
        if m:
            if m.group(1):
                heredocs.append(m.group(1).strip("'\""))
            else:
                state["delimiter"] = True
            return
        tokens.append(("w", value, word_line))

    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            if text[i + 1] == "\n":
                i += 2
                line += 1
                continue
            if not word:
                word_line = line
            word.append(text[i + 1])
            i += 2
            continue
        if ch in " \t":
            flush()
            i += 1
            continue
        if ch == "#" and not word:
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "\n":
            flush()
            tokens.append(("op", "\n", line))
            line += 1
            i += 1
            for delimiter in heredocs:
                while i < n:
                    end = text.find("\n", i)
                    end = n if end < 0 else end
                    current = text[i:end]
                    i = end + 1
                    line += 1
                    if current.strip() == delimiter:
                        break
            del heredocs[:]
            continue
        if ch in ";&|":
            previous = text[i - 1] if i else ""
            if ch == "&" and ((previous and previous in "<>") or text[i + 1:i + 2] == ">"):
                if not word:
                    word_line = line
                word.append(ch)
                i += 1
                continue
            flush()
            pair = text[i:i + 2]
            if pair in ("&&", "||"):
                tokens.append(("op", pair, line))
                i += 2
            elif pair in ("|&", ";;"):
                tokens.append(("op", pair[0], line))
                i += 2
            else:
                tokens.append(("op", "|" if ch == "|" else ";", line))
                i += 1
            continue
        if not word:
            word_line = line
        if ch == "'":
            end = text.find("'", i + 1)
            end = n if end < 0 else end
            word.append(text[i + 1:end])
            line += text.count("\n", i, end)
            i = end + 1
        elif ch == '"':
            j = i + 1
            chunk = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    chunk.append(text[j:j + 2] if text[j + 1] in "$`" else text[j + 1])
                    j += 2
                elif text[j] == "$" and text[j + 1:j + 2] == "(":
                    end = _balanced_end(text, j + 1)
                    chunk.append(text[j:end])
                    j = end
                else:
                    chunk.append(text[j])
                    j += 1
            word.append("".join(chunk))
            line += text.count("\n", i, j)
            i = j + 1
        elif ch == "$" and text[i + 1:i + 2] == "(":
            end = _balanced_end(text, i + 1)
            word.append(text[i:end])
            line += text.count("\n", i, end)
            i = end
        elif ch == "`":
            end = text.find("`", i + 1)
            end = n if end < 0 else end + 1
            word.append(text[i:end])
            i = end
        else:
            word.append(ch)
            i += 1
    flush()
    return tokens


def _clean_words(words):
    """Drop redirections, shell keywords and grouping parentheses from the words of one command."""
    out = []
    skip = False
    for word in words:
        if skip:
            skip = False
            continue
        if REDIRECT_RE.match(word):
            skip = bool(REDIRECT_TAKES_NEXT.match(word))
            continue
        out.append(word)
    while out and out[0] in SHELL_KEYWORDS:
        out.pop(0)
    if out and out[0].startswith("(") and not out[0].startswith("$("):
        out[0] = out[0].lstrip("(")
        if not out[0]:
            out.pop(0)
    if out and out[-1].endswith(")") and "(" not in out[-1]:
        out[-1] = out[-1].rstrip(")")
        if not out[-1]:
            out.pop()
    while out and out[-1] in ("}", "fi", "done"):
        out.pop()
    return out


def _is_benign(argv, after_or):
    head = argv[0]
    if head in ("true", ":"):
        return True
    if head == "exit":
        return len(argv) > 1 and argv[1] == "0"
    return after_or and head in ("echo", "printf")


def split_commands(text):
    """The simple commands of a shell text, as Unit objects.

    A command is swallowed when `|| true`, `|| :`, `|| echo ...` or `|| exit 0`
    follows it in its list, or when `; true`, `; :` or `; exit 0` follows the list.
    """
    lists = []  # [(separator before the list, [[argv, line, operator before]])]
    state = {"current": [], "segment": [], "line": 0, "op": "", "separator": ""}

    def end_segment():
        argv = _clean_words(state["segment"])
        if argv:
            state["current"].append([argv, state["line"], state["op"]])
        state["segment"] = []

    for kind, value, line in shell_tokens(text):
        if kind == "w":
            if not state["segment"]:
                state["line"] = line
            state["segment"].append(value)
            continue
        end_segment()
        if value in ("&&", "||", "|"):
            state["op"] = value
        else:
            if state["current"]:
                lists.append((state["separator"], state["current"]))
            state["current"] = []
            state["separator"] = value
            state["op"] = ""
    end_segment()
    if state["current"]:
        lists.append((state["separator"], state["current"]))
    units = []
    for index, (_separator, entries) in enumerate(lists):
        after = lists[index + 1] if index + 1 < len(lists) else None
        swallowed_list = bool(after and after[0] == ";" and len(after[1]) == 1
                              and _is_benign(after[1][0][0], False))
        for position, (argv, line, _before) in enumerate(entries):
            swallowed = swallowed_list or any(
                later[2] == "||" and _is_benign(later[0], True) for later in entries[position + 1:])
            units.append(Unit(argv, line, swallowed))
    return units


def substitutions(word):
    """The texts inside $( ... ) and backticks of one word."""
    out = []
    i = 0
    while i < len(word):
        if word.startswith("$(", i):
            end = _balanced_end(word, i + 1)
            out.append(word[i + 2:end - 1])
            i = end
        elif word[i] == "`":
            end = word.find("`", i + 1)
            if end < 0:
                break
            out.append(word[i + 1:end])
            i = end + 1
        else:
            i += 1
    return out


# --------------------------------------------------------------------------
# Reading commands: which tool does a command run?
# --------------------------------------------------------------------------

JVM_TEST_TOOLS = ("junit", "testng", "kotest")

# Facts a command can show that are coverage thresholds, not strictness.
COVERAGE_FACT_KINDS = {"fail_under", "cov-fail-under", "jest-coverage-threshold", "vitest-thresholds"}
MAX_FOLLOW_DEPTH = 3

# Flags after which a tool does not fail the build.
NEVER_FAIL_FLAGS = {"--exit-zero", "--no-fail", "--exit-code=0", "--issues-exit-code=0"}

# Formatters: the flags that turn a run into a check. Without one the command
# rewrites files (or only prints), so it enforces nothing.
FORMAT_CHECK_FLAGS = {
    "black": {"--check", "--diff"}, "isort": {"--check", "--check-only", "-c", "--diff"},
    "ruff-format": {"--check", "--diff"}, "prettier": {"--check", "-c", "--list-different", "-l"},
    "gofmt": {"-l", "-d"}, "goimports": {"-l", "-d"}, "gofumpt": {"-l", "-d"},
    "rustfmt": {"--check"}, "ktfmt": {"--dry-run", "--set-exit-if-changed"},
    "google-java-format": {"--dry-run", "-n", "--set-exit-if-changed"},
}

INSTALL_SUBS = {"install", "i", "ci", "add", "isntall", "it", "install-test", "install-ci-test", "cit"}
NPM_VALUE_FLAGS = {"--prefix", "--userconfig", "--registry", "--cache", "--tag", "--otp", "--loglevel", "-C"}
PNPM_VALUE_FLAGS = {"--dir", "-C", "--workspace-concurrency", "--reporter", "--loglevel", "--filter-prod",
                    "--changed-files-ignore-pattern", "--test-pattern"}
YARN_VALUE_FLAGS = {"--cwd", "--mutex", "--registry", "--use-yarnrc"}
BUN_VALUE_FLAGS = {"--cwd", "--filter", "-c", "--config"}
YARN_FOREACH_VALUE_FLAGS = {"--include", "--exclude", "-j", "--jobs", "--since", "--worktree"}
PNPM_BUILTINS = {
    "add", "install", "i", "update", "up", "upgrade", "remove", "rm", "link", "unlink", "import", "rebuild",
    "prune", "fetch", "install-test", "it", "audit", "outdated", "list", "ls", "why", "licenses", "publish", "pack",
    "env", "setup", "store", "root", "bin", "config", "c", "doctor", "init", "create", "dlx", "exec", "run", "test",
    "t", "start", "deploy", "patch", "patch-commit", "self-update", "cache", "help", "version", "recursive", "m",
    "multi", "server",
}
YARN_BUILTINS = {
    "add", "install", "remove", "up", "upgrade", "link", "unlink", "set", "config", "info", "init", "pack",
    "publish", "cache", "constraints", "dedupe", "explain", "node", "plugin", "rebuild", "version", "why", "dlx",
    "exec", "run", "workspace", "workspaces", "npm", "audit", "help", "list", "outdated", "global", "bin",
}
BUN_BUILTINS = {"install", "i", "add", "remove", "rm", "update", "link", "unlink", "pm", "init", "create", "x", "run",
                "test", "build", "upgrade", "repl", "dev", "help", "publish", "outdated", "audit"}
MVN_VALUE_FLAGS = {"-pl", "--projects", "-f", "--file", "-P", "--activate-profiles", "-T", "--threads", "-s",
                   "--settings", "-gs", "--global-settings", "-rf", "--resume-from", "-l", "--log-file", "-t",
                   "--toolchains", "-b", "--builder", "-e"}
MVN_TEST_PHASES = {"test", "verify", "install", "package", "deploy", "integration-test", "post-integration-test"}
MVN_PHASES = MVN_TEST_PHASES | {
    "validate", "initialize", "generate-sources", "process-sources", "generate-resources", "process-resources",
    "compile", "process-classes", "generate-test-sources", "process-test-sources", "generate-test-resources",
    "process-test-resources", "test-compile", "process-test-classes", "prepare-package", "pre-integration-test",
    "clean", "site", "pre-site", "post-site", "site-deploy", "pre-clean", "post-clean",
}
MVN_PLUGIN_TOOLS = {"checkstyle": "checkstyle", "spotbugs": "spotbugs", "pmd": "pmd", "spotless": "spotless",
                    "jacoco": "jacoco", "dependency-check": "dependency-check", "sonar": "sonarqube"}
GRADLE_VALUE_FLAGS = {"-p", "--project-dir", "-b", "--build-file", "-c", "--settings-file", "-g", "--gradle-user-home",
                      "-I", "--init-script", "--include-build", "--max-workers", "--tests", "--console",
                      "--project-cache-dir", "--warning-mode", "--configuration-cache-problems"}
GRADLE_TASK_TOOLS = [
    (re.compile(r"^checkstyle"), "checkstyle"), (re.compile(r"^pmd"), "pmd"), (re.compile(r"^spotbugs"), "spotbugs"),
    (re.compile(r"^detekt"), "detekt"), (re.compile(r"^ktlint"), "ktlint"), (re.compile(r"^spotless"), "spotless"),
    (re.compile(r"^jacoco"), "jacoco"), (re.compile(r"^kover"), "kover"),
    (re.compile(r"^dependencyCheck"), "dependency-check"), (re.compile(r"^sonar"), "sonarqube"),
]
GRADLE_VERIFICATION_WORDS = ("checkstyle", "pmd", "spotbugs", "detekt", "ktlint", "spotless")
RUFF_OTHER_SUBS = {"clean", "server", "rule", "config", "linter", "version", "help", "analyze", "completion",
                   "generate-shell-completion"}
PIP_VALUE_FLAGS = {"-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url",
                   "--extra-index-url", "-f", "--find-links", "-t", "--target", "--prefix", "--root", "--python",
                   "--platform", "--python-version", "--implementation", "--abi", "--src", "--upgrade-strategy"}
UV_RUN_VALUE_FLAGS = {"--with", "--with-requirements", "--with-editable", "-p", "--python", "--group", "--extra",
                      "--package", "--project", "--directory", "--env-file", "--index", "--default-index",
                      "--index-url", "--no-install-package", "--only-group", "--no-group", "--isolated-from"}
UVX_VALUE_FLAGS = UV_RUN_VALUE_FLAGS | {"--from"}
NPX_VALUE_FLAGS = {"-p", "--package", "-c", "--call", "--registry", "--cache"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}


class Hit(object):
    """A tool that a command runs."""

    def __init__(self, tool, line, writes, non_blocking, command, via=None, via_file=None, via_line=None):
        self.tool = tool
        self.line = line
        self.writes = writes
        self.non_blocking = non_blocking
        self.command = command
        self.via = via
        self.via_file = via_file
        self.via_line = via_line


class Outcome(object):
    def __init__(self):
        self.hits = []
        self.installs = []   # {"line", "command", "manager", "packages"}
        self.facts = []      # {"kind", "line", "command", ...} strictness and threshold facts seen in commands
        self.locks = []      # {"kind", "line", "command"}


class Ctx(object):
    """Where a command is read: following depth, the script it came from, and the caller's line."""

    def __init__(self, follow=True, depth=0, stack=(), via=None, nb=False, command="", base_line=None, env=None,
                 probe=None):
        self.probe = probe        # a list: script and target references are recorded there, not followed
        self.follow = follow
        self.depth = depth
        self.stack = stack
        self.via = via            # (name, file, line)
        self.nb = nb
        self.command = command
        self.base_line = base_line
        self.env = env or {}

    def but(self, **changes):
        copy = Ctx(self.follow, self.depth, self.stack, self.via, self.nb, self.command, self.base_line, self.env,
                   self.probe)
        for key, value in changes.items():
            setattr(copy, key, value)
        return copy


def first_positional(args, value_flags=()):
    """The first argument that is not a flag (or the value of a flag that takes one)."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return args[i + 1] if i + 1 < len(args) else None
        if a.startswith("-"):
            if a in value_flags:
                i += 1
        else:
            return a
        i += 1
    return None


def drop_flags(args, value_flags=()):
    """args from the first non-flag argument on (the program a runner starts)."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return args[i + 1:]
        if a.startswith("-"):
            name = a.split("=", 1)[0]
            if name in value_flags and "=" not in a:
                i += 1
        else:
            return args[i:]
        i += 1
    return []


def has_flag(args, *names):
    return any(a.split("=", 1)[0] in names for a in args)


def flag_value(args, *names):
    for i, a in enumerate(args):
        name, eq, value = a.partition("=")
        if name in names:
            if eq:
                return value
            if i + 1 < len(args):
                return args[i + 1]
    return None


def flag_on(args, *names):
    """True when a boolean flag is given and not set to false."""
    for a in args:
        name, eq, value = a.partition("=")
        if name in names and (not eq or value.lower() not in ("false", "0")):
            return True
    return False


def format_writes(name, args):
    """True when a formatter run rewrites files, or only prints, instead of checking."""
    if name == "dprint":
        return "check" not in args
    flags = FORMAT_CHECK_FLAGS.get(name)
    if flags is None:
        return False
    if name in ("gofmt", "goimports", "gofumpt") and "-w" in args:
        return True
    return not any(a.split("=", 1)[0] in flags for a in args)


def never_fails(args):
    if any(a in NEVER_FAIL_FLAGS for a in args):
        return True
    return any(a == "--exit-code" and i + 1 < len(args) and args[i + 1] == "0" for i, a in enumerate(args))


def maven_plugin(goal):
    """(plugin, goal) of a Maven goal such as checkstyle:check or org.x:maven-pmd-plugin:check."""
    parts = goal.split(":")
    if len(parts) < 2:
        return None, None
    plugin = parts[-2]
    plugin = re.sub(r"^maven-|-maven-plugin$|-maven$|-plugin$", "", plugin)
    return plugin, parts[-1]


class CommandReader(object):
    """Reads a shell text and says which of the TOOLS rows its commands run.

    A tool counts only when the command runs it: install commands do not, and
    `ruff format` is not `ruff`. Runners (npx, uv run, poetry run, python -m, ...)
    are looked through; npm scripts, make targets, workspace runners, pre-commit,
    tox, nox and repository shell scripts are followed with a depth limit.
    """

    HANDLERS = {}  # type: dict

    def __init__(self, detector):
        self.detector = detector
        self.repo = detector.repo
        self.tools = {tool.name: tool for tool in ALL_TOOLS}

    # -- entry points ----------------------------------------------------

    def read(self, text, line=1, follow=True, nb=False):
        out = Outcome()
        self.read_into(out, text, line, Ctx(follow=follow, nb=nb))
        return out

    def read_uses(self, text, line, nb=False):
        """A GitHub `uses:` value: an action, matched by name."""
        out = Outcome()
        ctx = Ctx(nb=nb, command=text[:200])
        if re.search(r"(^|/)pre-commit/action", text):
            self.precommit(out, ["run", "--all-files"], line, ctx)
        else:
            self.by_words(out, text, line, ctx)
            out.hits = [h for h in out.hits if h.tool.name not in JVM_TEST_TOOLS]   # "gradle-build-action" runs nothing
        return out

    def read_into(self, out, text, line, ctx):
        for unit in split_commands(text):
            where = line + unit.line
            here = ctx.but(nb=ctx.nb or unit.swallowed, command=" ".join(unit.argv)[:200])
            self.command(out, unit.argv, where, here)
            for word in unit.argv:
                if "$(" in word or "`" in word:
                    for inner in substitutions(word):
                        self.read_into(out, inner, where, here)

    # -- recording --------------------------------------------------------

    def hit(self, out, name, line, ctx, args=(), writes=None, via=None):
        tool = self.tools.get(name)
        if tool is None:
            return
        if writes is None:
            writes = format_writes(name, args)
        via_name, via_file, via_line = via or ctx.via or (None, None, None)
        if ctx.base_line is not None:
            via_line = via_line or line
            line = ctx.base_line
        out.hits.append(Hit(tool, line, writes, ctx.nb or never_fails(args), ctx.command,
                            via_name, via_file, via_line))

    def where(self, line, ctx):
        return ctx.base_line if ctx.base_line is not None else line

    def install(self, out, manager, packages, line, ctx):
        out.installs.append({"line": self.where(line, ctx), "command": ctx.command, "manager": manager,
                             "packages": packages})

    def lock(self, out, kind, line, ctx):
        out.locks.append({"kind": kind, "line": self.where(line, ctx), "command": ctx.command})

    def fact(self, out, kind, line, ctx, **extra):
        item = {"kind": kind, "line": self.where(line, ctx), "command": ctx.command}
        item.update(extra)
        out.facts.append(item)

    # -- one command ------------------------------------------------------

    def command(self, out, argv, line, ctx):
        env = {}
        argv = self.strip_wrappers(argv, env)
        if not argv:
            return
        if env:
            merged = dict(ctx.env)
            merged.update(env)
            ctx = ctx.but(env=merged)
            self.env_facts(out, env, line, ctx)
        prog = re.sub(r"@[^@/]*$", "", posixpath.basename(argv[0]))
        args = argv[1:]
        handler = self.HANDLERS.get(prog)
        if handler is None and re.match(r"^python[0-9.]*$", prog):
            handler = CommandReader.python
        if handler is None and re.match(r"^pip[0-9.]*$", prog):
            handler = CommandReader.pip
        if handler is not None:
            handler(self, out, args, line, ctx)
            return
        if "/" in argv[0] and self.follow_script(out, argv[0], args, line, ctx):
            return
        self.tool_command(out, prog, args, line, ctx)

    def env_facts(self, out, env, line, ctx):
        if re.search(r"-D\s?warnings|--deny[ =]warnings", env.get("RUSTFLAGS", "")):
            self.fact(out, "rustflags-deny-warnings", line, ctx)
        if "-mod=readonly" in env.get("GOFLAGS", ""):
            self.lock(out, "go -mod=readonly", line, ctx)

    def export(self, out, args, line, ctx):
        env = dict(a.split("=", 1) for a in args if re.match(r"^[A-Za-z_]\w*=", a))
        self.env_facts(out, env, line, ctx)

    @staticmethod
    def strip_wrappers(argv, env):
        argv = list(argv)
        while argv:
            m = re.match(r"^([A-Za-z_]\w*)=(.*)$", argv[0])
            if m:
                env[m.group(1)] = m.group(2)
                argv.pop(0)
            elif argv[0] == "env":
                argv.pop(0)
                while argv and (argv[0].startswith("-") or re.match(r"^[A-Za-z_]\w*=", argv[0])):
                    m = re.match(r"^([A-Za-z_]\w*)=(.*)$", argv[0])
                    if m:
                        env[m.group(1)] = m.group(2)
                    argv.pop(0)
            elif argv[0] == "sudo":
                argv.pop(0)
                while argv and argv[0].startswith("-"):
                    flag = argv.pop(0)
                    if flag in ("-u", "-g", "-h", "-p", "-C") and argv:
                        argv.pop(0)
            elif argv[0] in ("time", "exec", "command", "nohup"):
                argv.pop(0)
            else:
                break
        return argv

    # -- tools with no special reading -------------------------------------

    def tool_command(self, out, prog, args, line, ctx):
        heads = [prog]
        if args and re.match(r"^[A-Za-z][\w\-]*$", args[0]):
            heads.append(prog + " " + args[0])
        names = []
        for tool in ALL_TOOLS:
            if any(tool.ci_match(head.lower()) for head in heads):
                names.append(tool.name)
        for name in names:
            self.hit(out, name, line, ctx, args)

    def by_words(self, out, text, line, ctx, via=None):
        low = text.lower()
        for tool in ALL_TOOLS:
            if tool.ci_match(low):
                self.hit(out, tool.name, line, ctx, via=via)

    # -- tools whose flags or sub-commands decide what they do ------------------

    def ruff(self, out, args, line, ctx):
        sub = first_positional(args)
        if has_flag(args, "--version", "--help", "-h") or sub in RUFF_OTHER_SUBS:
            return
        self.hit(out, "ruff-format" if sub == "format" else "ruff", line, ctx, args)

    def biome(self, out, args, line, ctx):
        sub = first_positional(args)
        writes = has_flag(args, "--write", "--fix", "--apply")
        if sub == "format":
            self.hit(out, "biome-format", line, ctx, args, writes=writes)
        elif sub == "lint":
            self.hit(out, "biome", line, ctx, args)
        elif sub == "check":
            self.hit(out, "biome", line, ctx, args)
            self.hit(out, "biome-format", line, ctx, args, writes=writes)
        elif sub == "ci":
            self.hit(out, "biome", line, ctx, args)
            self.hit(out, "biome-format", line, ctx, args, writes=False)

    def pytest(self, out, args, line, ctx):
        self.hit(out, "pytest", line, ctx, args)
        if any(re.match(r"^--cov($|=|-)", a) for a in args):
            self.hit(out, "coverage.py", line, ctx, args)
        threshold = flag_value(args, "--cov-fail-under")
        if threshold:
            self.fact(out, "cov-fail-under", line, ctx, value=threshold)

    def coverage(self, out, args, line, ctx):
        self.hit(out, "coverage.py", line, ctx, args)
        sub = first_positional(args)
        if sub == "run":
            rest = args[args.index("run") + 1:]
            if "-m" in rest:
                self.command(out, rest[rest.index("-m") + 1:], line, ctx)
        elif sub in ("report", "xml", "html", "json", "lcov"):
            threshold = flag_value(args, "--fail-under")
            if threshold:
                self.fact(out, "fail_under", line, ctx, value=threshold)

    def jest(self, out, args, line, ctx):
        self.hit(out, "jest", line, ctx, args)
        if flag_on(args, "--coverage", "--collectCoverage", "--collect-coverage"):
            self.hit(out, "jest-coverage", line, ctx, args)
        if has_flag(args, "--coverageThreshold"):
            self.fact(out, "jest-coverage-threshold", line, ctx)

    def vitest(self, out, args, line, ctx):
        self.hit(out, "vitest", line, ctx, args)
        if flag_on(args, "--coverage") or any(a.startswith("--coverage.") for a in args):
            self.hit(out, "vitest-coverage", line, ctx, args)
        if any(a.startswith("--coverage.thresholds") for a in args):
            self.fact(out, "vitest-thresholds", line, ctx)

    def coverage_wrapper(self, out, prog, args, line, ctx):
        self.hit(out, prog, line, ctx, args)
        self.command(out, drop_flags(args, {"-r", "--reporter", "--reports-dir", "-n", "--include", "-x", "--exclude",
                                            "--temp-directory", "-t", "--lines", "--functions", "--branches",
                                            "--statements"}), line, ctx)

    def c8(self, out, args, line, ctx):
        self.coverage_wrapper(out, "c8", args, line, ctx)

    def nyc(self, out, args, line, ctx):
        self.coverage_wrapper(out, "nyc", args, line, ctx)

    def java(self, out, args, line, ctx):
        if "-jar" in args and args.index("-jar") + 1 < len(args):
            jar = posixpath.basename(args[args.index("-jar") + 1])
            self.tool_command(out, jar, args[args.index("-jar") + 2:], line, ctx)

    def system_install(self, out, manager, args, line, ctx):
        if "install" in args:
            packages = [a for a in args[args.index("install") + 1:] if not a.startswith("-")]
            self.install(out, manager, packages, line, ctx)

    # -- python ------------------------------------------------------------

    def python(self, out, args, line, ctx):
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-m" and i + 1 < len(args):
                self.command(out, args[i + 1:], line, ctx)
                return
            if a in ("-W", "-X"):
                i += 1
            elif a == "-c":
                return
            elif not a.startswith("-"):
                return
            i += 1

    def pip(self, out, args, line, ctx):
        if first_positional(args, PIP_VALUE_FLAGS) != "install":
            return
        self.record_pip_install(out, "pip", args[args.index("install") + 1:], line, ctx)

    def record_pip_install(self, out, manager, args, line, ctx):
        packages = []
        requirements = []
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("-r", "--requirement") and i + 1 < len(args):
                requirements.append(args[i + 1])
                i += 1
            elif a.startswith("--requirement="):
                requirements.append(a.split("=", 1)[1])
            elif a.startswith("-r") and len(a) > 2 and not a.startswith("--"):
                requirements.append(a[2:])
            elif a.startswith("-"):
                if a in PIP_VALUE_FLAGS:
                    i += 1
            else:
                packages.append(a)
            i += 1
        self.install(out, manager, packages, line, ctx)
        if requirements and not packages and (has_flag(args, "--require-hashes")
                                              or all(self.detector.pinned_requirements(r) for r in requirements)):
            self.lock(out, "pip install -r pinned", line, ctx)

    # -- uv, poetry, pipx and the other runners ------------------------------

    def uv(self, out, args, line, ctx):
        sub = first_positional(args, UV_RUN_VALUE_FLAGS)
        rest = args[args.index(sub) + 1:] if sub in args else []
        if sub == "run":
            self.command(out, drop_flags(rest, UV_RUN_VALUE_FLAGS), line, ctx)
        elif sub == "pip":
            if first_positional(rest) == "install":
                self.record_pip_install(out, "uv pip", rest[rest.index("install") + 1:], line, ctx)
        elif sub == "sync":
            self.install(out, "uv", [], line, ctx)
            if has_flag(args, "--locked", "--frozen"):
                self.lock(out, "uv sync --locked", line, ctx)
        elif sub == "add":
            self.install(out, "uv", [a for a in rest if not a.startswith("-")], line, ctx)
        elif sub == "tool":
            action = first_positional(rest, UV_RUN_VALUE_FLAGS)
            if action == "run":
                self.command(out, drop_flags(rest[rest.index("run") + 1:], UVX_VALUE_FLAGS), line, ctx)
            elif action == "install":
                self.install(out, "uv tool", [a for a in rest[rest.index("install") + 1:] if not a.startswith("-")],
                             line, ctx)

    def uvx(self, out, args, line, ctx):
        self.command(out, drop_flags(args, UVX_VALUE_FLAGS), line, ctx)

    def npx(self, out, args, line, ctx):
        self.command(out, drop_flags(args, NPX_VALUE_FLAGS), line, ctx)

    def poetry(self, out, args, line, ctx):
        sub = first_positional(args)
        rest = args[args.index(sub) + 1:] if sub in args else []
        if sub == "run":
            self.command(out, rest, line, ctx)
        elif sub == "install":
            self.install(out, "poetry", [], line, ctx)
            if has_flag(args, "--sync"):
                self.lock(out, "poetry install --sync", line, ctx)
        elif sub == "check" and has_flag(rest, "--lock"):
            self.fact(out, "poetry-check-lock", line, ctx)
        elif sub == "lock" and has_flag(rest, "--check"):
            self.fact(out, "poetry-check-lock", line, ctx)

    def pdm(self, out, args, line, ctx):
        sub = first_positional(args)
        rest = args[args.index(sub) + 1:] if sub in args else []
        if sub == "run":
            self.command(out, rest, line, ctx)
        elif sub in ("install", "sync"):
            self.install(out, "pdm", [], line, ctx)

    def pipx(self, out, args, line, ctx):
        sub = first_positional(args, {"--spec", "--python"})
        rest = args[args.index(sub) + 1:] if sub in args else []
        if sub == "run":
            self.command(out, drop_flags(rest, {"--spec", "--python", "--index-url", "--pip-args"}), line, ctx)
        elif sub == "install":
            self.install(out, "pipx", [a for a in rest if not a.startswith("-")], line, ctx)

    def hatch(self, out, args, line, ctx):
        if first_positional(args) == "run":
            rest = args[args.index("run") + 1:]
            self.command(out, drop_flags(rest, {"-e", "--env"}), line, ctx)

    # -- go ----------------------------------------------------------------

    def go(self, out, args, line, ctx):
        sub = first_positional(args, {"-C"})
        rest = args[args.index(sub) + 1:] if sub in args else []
        readonly = has_flag(args, "-mod") and flag_value(args, "-mod") == "readonly"
        if sub == "run":
            target = drop_flags(rest, {"-exec", "-tags", "-ldflags", "-gcflags", "-p"})
            if target and not target[0].startswith((".", "/")):
                program = re.sub(r"@.*$", "", target[0]).rstrip("/").split("/")[-1]
                self.command(out, [program] + target[1:], line, ctx)
        elif sub == "vet":
            self.hit(out, "go-vet", line, ctx, args)
            self.fact(out, "go-vet", line, ctx)
        elif sub == "test":
            self.hit(out, "go-test", line, ctx, args)
            if any(re.match(r"^-{1,2}cover(profile|mode|pkg)?(=|$)", a) for a in args):
                self.hit(out, "go-cover", line, ctx, args)
        elif sub == "mod":
            action = first_positional(rest)
            if action == "verify":
                self.lock(out, "go mod verify", line, ctx)
        elif sub in ("install", "get"):
            self.install(out, "go", [a for a in rest if not a.startswith("-")], line, ctx)
            return
        if readonly and sub in ("build", "test", "vet", "run", "list"):
            self.lock(out, "go -mod=readonly", line, ctx)

    # -- cargo -------------------------------------------------------------

    def cargo(self, out, args, line, ctx):
        i = 0
        while i < len(args) and args[i].startswith(("+", "-")):
            if args[i] in ("--manifest-path", "-C", "--config", "-Z"):
                i += 1
            i += 1
        sub = args[i] if i < len(args) else None
        rest = args[i + 1:] if sub else []
        locked = has_flag(args, "--locked", "--frozen")
        if sub == "clippy":
            self.hit(out, "clippy", line, ctx, args)
            after = rest[rest.index("--") + 1:] if "--" in rest else []
            denied = any(a in ("-Dwarnings", "--deny=warnings") for a in after) or any(
                a in ("-D", "--deny") and j + 1 < len(after) and after[j + 1] == "warnings"
                for j, a in enumerate(after))
            if denied:
                self.fact(out, "clippy-deny-warnings", line, ctx)
        elif sub == "fmt":
            self.hit(out, "rustfmt", line, ctx, rest)
        elif sub in ("test", "t"):
            self.hit(out, "cargo-test", line, ctx, rest)
        elif sub == "nextest":
            self.hit(out, "nextest", line, ctx, rest)
        elif sub == "llvm-cov":
            self.hit(out, "cargo-llvm-cov", line, ctx, rest)
            if first_positional(rest) == "nextest":
                self.hit(out, "nextest", line, ctx, rest)
        elif sub == "tarpaulin":
            self.hit(out, "tarpaulin", line, ctx, rest)
        elif sub == "deny":
            self.hit(out, "cargo-deny", line, ctx, rest)
        elif sub == "audit":
            self.hit(out, "cargo-audit", line, ctx, rest)
        elif sub == "machete":
            self.hit(out, "cargo-machete", line, ctx, rest)
        elif sub == "udeps":
            self.hit(out, "cargo-udeps", line, ctx, rest)
        elif sub == "install":
            self.install(out, "cargo", [a for a in rest if not a.startswith("-")], line, ctx)
            return
        if locked and sub in ("build", "b", "test", "t", "check", "c", "clippy", "nextest", "run", "r"):
            self.lock(out, "cargo --locked", line, ctx)

    # -- maven and gradle ----------------------------------------------------

    def maven(self, out, args, line, ctx):
        goals = []
        skip_tests = False
        i = 0
        while i < len(args):
            a = args[i]
            if a.startswith("-D"):
                key, _eq, value = a[2:].partition("=")
                if key in ("skipTests", "maven.test.skip"):
                    skip_tests = value.lower() != "false"
            elif a in MVN_VALUE_FLAGS:
                i += 1
            elif not a.startswith("-"):
                goals.append(a)
            i += 1
        runs_tests = False
        for goal in goals:
            if goal in MVN_TEST_PHASES:
                runs_tests = True
            elif ":" in goal:
                plugin, action = maven_plugin(goal)
                if plugin in ("surefire", "failsafe") and action in ("test", "integration-test"):
                    runs_tests = True
                elif plugin in MVN_PLUGIN_TOOLS:
                    name = MVN_PLUGIN_TOOLS[plugin]
                    if plugin == "spotless":
                        self.hit(out, name, line, ctx, writes=(action == "apply"))
                    elif action in ("check", "report", "sonar", "cpd-check"):
                        self.hit(out, name, line, ctx, writes=False)
        if runs_tests and not skip_tests:
            for name in JVM_TEST_TOOLS:
                self.hit(out, name, line, ctx, writes=False)

    def gradle(self, out, args, line, ctx):
        tasks = []
        excluded = set()
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("-x", "--exclude-task") and i + 1 < len(args):
                excluded.add(args[i + 1].split(":")[-1])
                i += 1
            elif a in GRADLE_VALUE_FLAGS:
                i += 1
            elif not a.startswith("-"):
                tasks.append(a.split(":")[-1])
            i += 1
        tasks = [t for t in tasks if t not in excluded]
        runs_tests = False
        verifies = False
        for task in tasks:
            if task in ("test", "check", "build"):
                if "test" not in excluded:
                    runs_tests = True
                if task in ("check", "build"):
                    verifies = True
            else:
                for regex, name in GRADLE_TASK_TOOLS:
                    if regex.match(task):
                        self.hit(out, name, line, ctx, writes=bool(re.search(r"(Format|Apply)$", task)))
                        break
        if runs_tests:
            for name in JVM_TEST_TOOLS:
                self.hit(out, name, line, ctx, writes=False)
        if verifies:
            for name, build_file, build_line in self.detector.gradle_verification():
                self.hit(out, name, line, ctx, writes=False, via=("gradle check", build_file, build_line))

    # -- package managers and workspace runners ------------------------------

    def package_manager(self, out, prog, args, line, ctx):
        value_flags = {"npm": NPM_VALUE_FLAGS, "pnpm": PNPM_VALUE_FLAGS, "yarn": YARN_VALUE_FLAGS,
                       "bun": BUN_VALUE_FLAGS}[prog]
        workspace = False
        filters = []
        positional = []
        i = 0
        while i < len(args):
            a = args[i]
            if a == "--":
                break
            if a.startswith("-"):
                name, eq, value = a.partition("=")
                if prog in ("pnpm", "bun") and name in ("--filter", "-F"):
                    filters.append(value if eq else (args[i + 1] if i + 1 < len(args) else ""))
                    workspace = True
                    i += 0 if eq else 1
                elif name in ("-r", "--recursive", "--workspaces", "-ws") or (name in ("-w", "--workspace")
                                                                              and prog == "npm"):
                    workspace = True
                    if name in ("-w", "--workspace") and prog == "npm":
                        filters.append(value if eq else (args[i + 1] if i + 1 < len(args) else ""))
                        i += 0 if eq else 1
                elif name in value_flags and not eq:
                    i += 1
            else:
                positional.append((a, i))
            i += 1
        scope = {"workspace": workspace, "filters": filters}
        if not positional:
            if prog in ("yarn",):
                self.install(out, "yarn", [], line, ctx)
            return
        sub, sub_index = positional[0]
        rest = args[sub_index + 1:]
        names = [p[0] for p in positional]
        if sub in INSTALL_SUBS and prog != "yarn" or (prog == "yarn" and sub in ("install", "add")):
            self.package_install(out, prog, sub, args, line, ctx)
            return
        if prog == "npm":
            if sub in ("run", "run-script", "rum", "urn") and len(names) > 1:
                self.run_script(out, "npm", names[1], scope, line, ctx)
            elif sub in ("test", "t", "tst"):
                self.run_script(out, "npm", "test", scope, line, ctx)
            elif sub in ("start", "stop", "restart"):
                self.run_script(out, "npm", sub, scope, line, ctx)
            elif sub == "audit":
                self.hit(out, "npm-audit", line, ctx, args)
            elif sub in ("exec", "x"):
                self.command(out, drop_flags(rest, NPX_VALUE_FLAGS), line, ctx)
            return
        if prog == "pnpm":
            if sub in ("run", "run-script") and len(names) > 1:
                self.run_script(out, "npm", names[1], scope, line, ctx)
            elif sub in ("test", "t"):
                self.run_script(out, "npm", "test", scope, line, ctx)
            elif sub == "start":
                self.run_script(out, "npm", "start", scope, line, ctx)
            elif sub == "audit":
                self.hit(out, "npm-audit", line, ctx, args)
            elif sub in ("exec", "dlx"):
                self.command(out, drop_flags(rest, NPX_VALUE_FLAGS), line, ctx)
            elif sub in ("recursive", "multi", "m") and len(names) > 1:
                scope = {"workspace": True, "filters": filters}
                self.run_script(out, "npm", names[2] if names[1] == "run" and len(names) > 2 else names[1],
                                scope, line, ctx)
            elif sub not in PNPM_BUILTINS:
                self.run_script(out, "npm", sub, scope, line, ctx, explicit=False)
            return
        if prog == "yarn":
            if sub == "run" and len(names) > 1:
                self.run_script(out, "npm", names[1], scope, line, ctx)
            elif sub == "workspace" and len(names) > 2:
                inner = names[3] if names[2] == "run" and len(names) > 3 else names[2]
                self.run_script(out, "npm", inner, {"workspace": True, "filters": [names[1]]}, line, ctx)
            elif sub == "workspaces":
                self.yarn_workspaces(out, rest, line, ctx)
            elif sub == "npm" and len(names) > 1 and names[1] == "audit" or sub == "audit":
                self.hit(out, "npm-audit", line, ctx, args)
            elif sub in ("dlx", "exec"):
                self.command(out, drop_flags(rest, NPX_VALUE_FLAGS), line, ctx)
            elif sub not in YARN_BUILTINS:
                self.run_script(out, "npm", sub, scope, line, ctx, explicit=False)
            return
        if prog == "bun":
            if sub == "run" and len(names) > 1:
                self.run_script(out, "npm", names[1], scope, line, ctx)
            elif sub == "x":
                self.command(out, drop_flags(rest, NPX_VALUE_FLAGS), line, ctx)
            elif sub not in BUN_BUILTINS:
                self.run_script(out, "npm", sub, scope, line, ctx, explicit=False)

    def yarn_workspaces(self, out, rest, line, ctx):
        action = first_positional(rest)
        filters = []
        if action == "run":
            tail = rest[rest.index("run") + 1:]
            script = first_positional(tail)
        elif action == "foreach":
            tail = rest[rest.index("foreach") + 1:]
            filters = [a.split("=", 1)[1] if "=" in a else tail[i + 1] for i, a in enumerate(tail)
                       if a.split("=", 1)[0] == "--include" and ("=" in a or i + 1 < len(tail))]
            tail = drop_flags(tail, YARN_FOREACH_VALUE_FLAGS)
            if tail and tail[0] == "run":
                tail = drop_flags(tail[1:], YARN_FOREACH_VALUE_FLAGS)
            script = tail[0] if tail else None
        else:
            return
        if script:
            self.run_script(out, "npm", script, {"workspace": True, "filters": filters}, line, ctx)

    def package_install(self, out, prog, sub, args, line, ctx):
        packages = [a for a in args[args.index(sub) + 1:] if not a.startswith("-")]
        self.install(out, prog, packages if sub in ("add",) else [], line, ctx)
        if prog == "npm" and sub in ("ci", "cit", "install-ci-test"):
            self.lock(out, "npm ci", line, ctx)
        elif prog == "pnpm" and has_flag(args, "--frozen-lockfile"):
            self.lock(out, "pnpm install --frozen-lockfile", line, ctx)
        elif prog == "yarn" and has_flag(args, "--immutable", "--frozen-lockfile"):
            self.lock(out, "yarn install --immutable", line, ctx)
        elif prog == "bun" and has_flag(args, "--frozen-lockfile"):
            self.lock(out, "bun install --frozen-lockfile", line, ctx)

    def turbo(self, out, args, line, ctx):
        tasks = []
        sub = first_positional(args, {"--filter", "--cache-dir", "--concurrency", "--token", "--team"})
        tail = args[args.index(sub) + 1:] if sub in args else []
        if sub == "run":
            candidates = tail
        else:
            candidates = [sub] + tail if sub else []
        i = 0
        while i < len(candidates):
            a = candidates[i]
            if a == "--":
                break
            if a.startswith("-"):
                if a in ("--filter", "--cache-dir", "--concurrency", "--token", "--team"):
                    i += 1
            else:
                tasks.append(a)
            i += 1
        for task in tasks:
            self.run_script(out, "npm", task, {"workspace": True, "filters": []}, line, ctx)

    def nx(self, out, args, line, ctx):
        sub = first_positional(args)
        targets = []
        if sub == "run":
            spec = args[args.index("run") + 1:]
            if spec and ":" in spec[0]:
                targets.append(spec[0].split(":")[1])
        elif sub in ("run-many", "affected", "run-many"):
            i = 0
            while i < len(args):
                a = args[i]
                name, eq, value = a.partition("=")
                if name in ("-t", "--target", "--targets"):
                    values = [value] if eq else []
                    j = i + 1
                    while not eq and j < len(args) and not args[j].startswith("-"):
                        values.append(args[j])
                        j += 1
                    for chunk in values:
                        targets.extend(t for t in chunk.split(",") if t)
                    i = j - 1 if not eq else i
                i += 1
        for target in targets:
            self.run_script(out, "npm", target, {"workspace": True, "filters": []}, line, ctx)

    def lerna(self, out, args, line, ctx):
        if first_positional(args) == "run":
            script = first_positional(args[args.index("run") + 1:], {"--scope", "--ignore", "--concurrency"})
            if script:
                self.run_script(out, "npm", script, {"workspace": True, "filters": []}, line, ctx)

    def run_npm_all(self, out, args, line, ctx):
        names = [a for a in args if not a.startswith("-")]
        for pattern in names:
            regex = glob_to_regex(pattern.replace(":*", ":*"))
            matches = [n for n in self.detector.scripts.get("npm", {}) if regex.match(n)] or [pattern]
            for name in matches:
                self.run_script(out, "npm", name, {"workspace": False, "filters": []}, line, ctx)

    # -- make, just --------------------------------------------------------

    def make(self, out, args, line, ctx):
        directory = flag_value(args, "-C", "--directory")
        targets = []
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("-C", "--directory", "-f", "--file", "--makefile", "-I", "-o", "-W", "-l"):
                i += 1
            elif not a.startswith("-") and "=" not in a:
                targets.append(a)
            i += 1
        for target in targets:
            self.run_script(out, "make", target, {"directory": directory}, line, ctx)

    def just(self, out, args, line, ctx):
        recipe = first_positional(args, {"--justfile", "-f", "--working-directory", "-d", "--set"})
        if recipe and "=" not in recipe:
            self.run_script(out, "just", recipe, {"directory": None}, line, ctx)

    # -- following -----------------------------------------------------------

    def run_script(self, out, kind, name, scope, line, ctx, explicit=True):
        if ctx.probe is not None:
            ctx.probe.append((kind, name, scope, explicit))
            return
        if not ctx.follow:
            return
        entries = self.detector.scripts_for(kind, name, scope)
        if kind == "npm" and not name.startswith(("pre", "post")):
            entries = (self.detector.scripts_for(kind, "pre" + name, scope) + entries
                       + self.detector.scripts_for(kind, "post" + name, scope))
        if not entries:
            if kind == "npm":
                self.by_words(out, name, line, ctx)
            return
        for entry in entries:
            key = (kind, entry["file"], entry["name"])
            if key in ctx.stack or ctx.depth >= MAX_FOLLOW_DEPTH:
                continue
            inner = ctx.but(depth=ctx.depth + 1, stack=ctx.stack + (key,),
                            via=(entry["name"], entry["file"], entry["line"]),
                            base_line=self.where(line, ctx))
            self.read_into(out, entry["body"], 1, inner)

    def follow_text(self, out, text, line, ctx, via):
        """Read the commands of a followed file (tox env, nox session, shell script)."""
        key = ("text", via[1], via[0])
        if key in ctx.stack or ctx.depth >= MAX_FOLLOW_DEPTH:
            return
        inner = ctx.but(depth=ctx.depth + 1, stack=ctx.stack + (key,), via=via,
                        base_line=self.where(line, ctx))
        self.read_into(out, text, 1, inner)

    def follow_argv(self, out, argv, line, ctx, via):
        """Read one command of a followed file (a nox session.run call)."""
        key = ("argv", via[1], via[0], via[2])
        if key in ctx.stack or ctx.depth >= MAX_FOLLOW_DEPTH:
            return
        inner = ctx.but(depth=ctx.depth + 1, stack=ctx.stack + (key,), via=via, base_line=self.where(line, ctx),
                        command=" ".join(argv)[:200])
        self.command(out, argv, via[2] or 1, inner)

    def follow_script(self, out, path, args, line, ctx):
        if not ctx.follow:
            return False
        rel = self.detector.repo_path(path)
        if rel is None or rel not in self.repo.file_set:
            return False
        text = self.repo.text(rel)
        first = text.splitlines()[0] if text else ""
        if not (rel.endswith((".sh", ".bash")) or re.match(r"^#!.*\b(ba|z|da|k)?sh\b", first)):
            return False
        self.follow_text(out, text, line, ctx, (rel, rel, None))
        return True

    def shell(self, out, args, line, ctx):
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-c" and i + 1 < len(args):
                self.read_into(out, args[i + 1], line, ctx)
                return
            if a.startswith("-"):
                i += 1
                continue
            self.follow_script(out, a, args[i + 1:], line, ctx)
            return

    def tox(self, out, args, line, ctx):
        self.hit(out, "tox", line, ctx)
        if ctx.follow:
            self.detector.follow_tox(self, out, args, line, ctx)

    def nox(self, out, args, line, ctx):
        self.hit(out, "nox", line, ctx)
        if ctx.follow:
            self.detector.follow_nox(self, out, args, line, ctx)

    def precommit(self, out, args, line, ctx):
        self.hit(out, "pre-commit", line, ctx)
        if not ctx.follow:
            return
        sub = first_positional(args, {"-c", "--config"})
        if sub == "run":
            rest = args[args.index("run") + 1:]
            hook = first_positional(rest, {"--from-ref", "--to-ref", "--files", "--hook-stage", "-c", "--config",
                                           "-s", "--source", "-o", "--origin", "--commit-msg-filename",
                                           "--remote-name", "--remote-url", "--checkout-type", "--is-squash-merge",
                                           "--rewrite-command", "--prepare-commit-message-source", "--color"})
            self.detector.follow_precommit(self, out, hook, ctx.env.get("SKIP", ""), line, ctx)


CommandReader.HANDLERS.update({
    "npx": CommandReader.npx, "bunx": CommandReader.npx, "pnpx": CommandReader.npx,
    "uvx": CommandReader.uvx, "uv": CommandReader.uv,
    "poetry": CommandReader.poetry, "pdm": CommandReader.pdm, "pipx": CommandReader.pipx,
    "hatch": CommandReader.hatch,
    "go": CommandReader.go, "cargo": CommandReader.cargo,
    "mvn": CommandReader.maven, "mvnw": CommandReader.maven, "mvnd": CommandReader.maven,
    "gradle": CommandReader.gradle, "gradlew": CommandReader.gradle,
    "turbo": CommandReader.turbo, "nx": CommandReader.nx, "lerna": CommandReader.lerna,
    "run-s": CommandReader.run_npm_all, "run-p": CommandReader.run_npm_all,
    "npm-run-all": CommandReader.run_npm_all, "npm-run-all2": CommandReader.run_npm_all,
    "make": CommandReader.make, "gmake": CommandReader.make, "just": CommandReader.just,
    "tox": CommandReader.tox, "nox": CommandReader.nox,
    "ruff": CommandReader.ruff, "biome": CommandReader.biome,
    "pytest": CommandReader.pytest, "py.test": CommandReader.pytest, "coverage": CommandReader.coverage,
    "jest": CommandReader.jest, "vitest": CommandReader.vitest, "c8": CommandReader.c8, "nyc": CommandReader.nyc,
    "java": CommandReader.java, "export": CommandReader.export,
    "pre-commit": CommandReader.precommit, "prek": CommandReader.precommit,
})
for _shell in SHELLS:
    CommandReader.HANDLERS[_shell] = CommandReader.shell
for _installer in ("apt-get", "apt", "brew", "gem"):
    CommandReader.HANDLERS[_installer] = (lambda manager: lambda self, out, args, line, ctx:
                                          self.system_install(out, manager, args, line, ctx))(_installer)
for _manager in ("npm", "pnpm", "yarn", "bun"):
    CommandReader.HANDLERS[_manager] = (lambda manager: lambda self, out, args, line, ctx:
                                        self.package_manager(out, manager, args, line, ctx))(_manager)


# --------------------------------------------------------------------------
# CI files: jobs, steps, triggers
# --------------------------------------------------------------------------

CI_CMD_KEYS = {
    "run", "uses", "script", "before_script", "after_script", "command", "commands", "cmd", "cmds", "bash",
    "powershell", "pwsh", "entrypoint", "install", "before_install",
}
NON_BLOCKING_KEYS = ("continue-on-error", "allow_failure", "continueOnError", "soft_fail")
PR_EVENTS = ("pull_request", "pull_request_target", "merge_group")
PR_RANK = {False: 0, "push-default": 1, True: 2}
PUSH_DEFAULT_NOTE = {
    "circleci": "CircleCI runs on every branch push by default; a pull request is checked when its branch is pushed.",
    "travis": "Travis CI builds every branch push by default and reports the build on the pull request.",
    "buildkite": "Buildkite builds on branch pushes by default; pull request builds depend on the pipeline settings.",
    "azure": "Azure Pipelines run on branch pushes by default; a `pr:` trigger is not read.",
    "jenkins": "Jenkins multibranch pipelines build pushed branches; pull request builds depend on the job settings.",
    "drone": "Drone builds branch pushes by default; pull request builds depend on the repository settings.",
    "gitlab": "Branch pipelines run on push and show on the merge request; no job names merge requests.",
    "bitbucket": "Only branch pipelines (default, branches) run; there is no pull-requests pipeline.",
}
GITLAB_RESERVED = {"stages", "variables", "default", "include", "workflow", "image", "services", "cache",
                   "before_script", "after_script"}


def better(a, b):
    """The stronger of two pull_request values (True > "push-default" > False)."""
    return a if PR_RANK[a] >= PR_RANK[b] else b


def truthy(node):
    return isinstance(node, str) and node.strip().lower() in ("true", "yes", "on")


def flat_strings(node):
    """Every scalar of a YAML node, as plain strings."""
    if isinstance(node, str):
        return [str(node)]
    if isinstance(node, dict):
        out = []
        for key, value in node.items():
            out.append(str(key))
            out.extend(flat_strings(value))
        return out
    if isinstance(node, list):
        return [s for item in node for s in flat_strings(item)]
    return []


def walk_yaml(node):
    """(key, value) of every mapping entry, depth first."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            for pair in walk_yaml(value):
                yield pair
    elif isinstance(node, list):
        for item in node:
            for pair in walk_yaml(item):
                yield pair


def excludes_pull_request(expr):
    """True when a GitHub `if:` expression keeps a job or step from running on a pull request."""
    low = " ".join(str(expr).lower().split())
    if re.search(r"event_name\s*==\s*['\"](pull_request|pull_request_target|merge_group)", low):
        return False
    if re.search(r"event_name\s*!=\s*['\"]pull_request", low):
        return True
    if "pull_request" in low and "||" in low:
        return False
    if re.search(r"event_name\s*==\s*['\"](push|schedule|workflow_dispatch|release|workflow_run|create|delete)['\"]",
                 low):
        return True
    return bool(re.search(r"github\.ref\s*==\s*['\"]refs/(heads|tags)/|startswith\(\s*github\.ref\s*,\s*"
                          r"['\"]refs/(heads|tags)/|github\.ref_name\s*==", low))


class CIStep(object):
    def __init__(self, line, text, kind, pull_request, non_blocking):
        self.line = line
        self.text = text
        self.kind = kind                # "run" or "uses"
        self.pull_request = pull_request
        self.non_blocking = non_blocking
        self.outcome = None
        self.job = None


def collect_steps(node, pull_request, non_blocking, steps, github=False):
    if isinstance(node, dict):
        local_nb = non_blocking or any(truthy(node.get(key)) for key in NON_BLOCKING_KEYS)
        local_pr = pull_request
        condition = node.get("if")
        if github and isinstance(condition, str) and excludes_pull_request(condition):
            local_pr = False
        for key, value in node.items():
            if key in CI_CMD_KEYS:
                emit_steps(key, value, local_pr, local_nb, steps)
            elif isinstance(value, (dict, list)):
                collect_steps(value, local_pr, local_nb, steps, github)
    elif isinstance(node, list):
        for item in node:
            collect_steps(item, pull_request, non_blocking, steps, github)


def emit_steps(key, value, pull_request, non_blocking, steps):
    if isinstance(value, str):
        if str(value).strip():
            steps.append(CIStep(value.line, str(value), "uses" if key == "uses" else "run", pull_request,
                                non_blocking))
    elif isinstance(value, list):
        for item in value:
            emit_steps(key, item, pull_request, non_blocking, steps)
    elif isinstance(value, dict):
        collect_steps(value, pull_request, non_blocking, steps)


def gitlab_pull_request(job, workflow_merge_requests):
    rules = job.get("rules")
    if isinstance(rules, list):
        conditions = [str(r.get("if")) for r in rules if isinstance(r, dict) and r.get("if") is not None]
        if any(re.search(r"merge_request_event|CI_MERGE_REQUEST", c) for c in conditions):
            return True
        pinned = re.compile(r"CI_COMMIT_TAG|CI_DEFAULT_BRANCH|CI_COMMIT_(BRANCH|REF_NAME)\s*==|"
                            r"CI_PIPELINE_SOURCE\s*==\s*[\"']?(schedule|web|api|trigger)")
        if conditions and all(pinned.search(c) for c in conditions):
            return False
        return "push-default"
    if "only" in job or "except" in job:
        only = flat_strings(job.get("only"))
        if any("merge_request" in s for s in only):
            return True
        if any("merge_request" in s for s in flat_strings(job.get("except"))):
            return "push-default"
        if only and all(s in ("tags", "main", "master", "schedules", "web", "api", "triggers", "refs") for s in only):
            return False
        return "push-default"
    return True if workflow_merge_requests else "push-default"


def jenkins_steps(text):
    """sh and bat steps of a Jenkinsfile, with the line of each."""
    steps = []
    pattern = re.compile(r"\b(?:sh|bat|powershell|pwsh)\s*\(?\s*(?:script\s*:\s*)?('''|\"\"\"|'|\")(.*?)\1", re.S)
    for m in pattern.finditer(text):
        body = m.group(2)
        first = text.count("\n", 0, m.start(2)) + 1
        steps.append(CIStep(first, body, "run", "push-default", False))
    return steps


def ci_structure(provider, text):
    """What a CI file runs and when: {"events", "pull_request", "jobs": [(name, pull_request, steps)], "tree"}."""
    if provider == "jenkins":
        steps = jenkins_steps(text)
        return {"events": [], "pull_request": "push-default", "jobs": [(None, "push-default", steps)], "tree": None}
    tree = parse_yaml(text)
    if not isinstance(tree, dict):
        return {"events": [], "pull_request": False, "jobs": [], "tree": None}
    jobs = []
    events = []
    if provider == "github":
        on = tree.get("on")
        if isinstance(on, str):
            events = [str(on)]
        elif isinstance(on, list):
            events = [str(e) for e in on]
        elif isinstance(on, dict):
            events = [str(e) for e in on]
        file_pr = any(e in PR_EVENTS for e in events)
        section = tree.get("jobs")
        for name, job in (section.items() if isinstance(section, dict) else []):
            if not isinstance(job, dict):
                continue
            pr = file_pr and not (isinstance(job.get("if"), str) and excludes_pull_request(job.get("if")))
            steps = []
            collect_steps(job, pr, False, steps, github=True)
            jobs.append((str(name), pr, steps))
        if not jobs:
            return {"events": events, "pull_request": file_pr, "jobs": [], "tree": tree}
    elif provider == "gitlab":
        workflow = tree.get("workflow")
        wf_rules = workflow.get("rules") if isinstance(workflow, dict) else None
        wf_mr = any(re.search(r"merge_request_event|CI_MERGE_REQUEST", s) for s in flat_strings(wf_rules))
        for name, job in tree.items():
            if name in GITLAB_RESERVED or str(name).startswith(".") or not isinstance(job, dict):
                continue
            if not any(k in job for k in ("script", "trigger", "extends")):
                continue
            pr = gitlab_pull_request(job, wf_mr)
            steps = []
            collect_steps(job, pr, False, steps)
            extends = job.get("extends")
            for template in ([str(extends)] if isinstance(extends, str) else [str(t) for t in extends or []]):
                base = tree.get(template)
                if isinstance(base, dict) and "script" not in job:
                    collect_steps(base, pr, False, steps)
            jobs.append((str(name), pr, steps))
    elif provider == "bitbucket":
        pipelines = tree.get("pipelines")
        for section, body in (pipelines.items() if isinstance(pipelines, dict) else []):
            pr = True if section == "pull-requests" else "push-default" if section in ("default", "branches") \
                else False
            groups = body.items() if isinstance(body, dict) else [(None, body)]
            for pattern, items in groups:
                steps = []
                collect_steps(items, pr, False, steps)
                jobs.append((str(section) + (":" + str(pattern) if pattern else ""), pr, steps))
    elif provider == "circleci":
        section = tree.get("jobs")
        for name, job in (section.items() if isinstance(section, dict) else []):
            steps = []
            collect_steps(job, "push-default", False, steps)
            jobs.append((str(name), "push-default", steps))
    elif provider == "azure" and isinstance(tree.get("jobs"), list):
        for index, job in enumerate(tree["jobs"]):
            name = str(job.get("job") or job.get("deployment") or index) if isinstance(job, dict) else str(index)
            steps = []
            collect_steps(job, "push-default", False, steps)
            jobs.append((name, "push-default", steps))
    if not jobs:
        steps = []
        pr = "push-default"
        collect_steps(tree, pr, False, steps)
        jobs.append((None, pr, steps))
    file_pr = False
    for name, pr, steps in jobs:
        file_pr = better(file_pr, pr)
        for step in steps:
            step.job = name
    return {"events": events, "pull_request": file_pr, "jobs": jobs, "tree": tree}


# --------------------------------------------------------------------------
# Files a CI command points at: tox.ini, noxfile.py
# --------------------------------------------------------------------------

def parse_ini(text, base_line=1):
    """{section: {key: [(line, text)]}} of an INI text; the first piece of a value may be empty."""
    sections = {}
    current = None
    key = None
    for number, raw in enumerate(text.splitlines(), base_line):
        if not raw.strip() or raw.lstrip().startswith(("#", ";")):
            continue
        m = re.match(r"^\[(.+?)\]\s*$", raw)
        if m and raw[0] not in " \t":
            current = m.group(1).strip()
            sections.setdefault(current, {})
            key = None
            continue
        if current is None:
            continue
        if raw[0] in " \t" and key is not None:
            sections[current][key].append((number, raw.strip()))
            continue
        m = re.match(r"^([^\s=:][^=:]*?)\s*[=:]\s*(.*)$", raw)
        if m:
            key = m.group(1)
            sections[current][key] = [(number, m.group(2))]
    return sections


def expand_env_list(names):
    out = []
    for name in re.split(r",(?![^{]*\})|\n", names):
        name = name.strip()
        if name:
            out.extend(expand_braces(name))
    return out


TOX_SUBSTITUTIONS = [
    (re.compile(r"\{envpython\}"), "python"), (re.compile(r"\{envbindir\}/?"), ""),
    (re.compile(r"\{toxinidir\}/?"), "./"), (re.compile(r"\{posargs[^}]*\}"), ""),
    (re.compile(r"\{(?:envdir|envtmpdir|envsitepackagesdir|homedir)\}/?"), ""),
]


def tox_commands(sections, env):
    """[(line, command)] of an environment: commands_pre, commands, commands_post."""
    section = sections.get("testenv:" + env)
    if section is None:
        for name, body in sections.items():
            if name.startswith("testenv:") and env in expand_braces(name[len("testenv:"):]):
                section = body
                break
    base = sections.get("testenv", {})
    section = section if section is not None else {}
    factors = env.split("-")
    out = []
    for key in ("commands_pre", "commands", "commands_post"):
        pieces = section.get(key) or base.get(key) or []
        merged = []
        for number, text in pieces:
            m = re.match(r"^\{\[([^\]]+)\]([\w]+)\}$", text.strip())
            if m:
                merged.extend(sections.get(m.group(1), {}).get(m.group(2), []))
            else:
                merged.append((number, text))
        pending = None
        for number, text in merged:
            for pattern, replacement in TOX_SUBSTITUTIONS:
                text = pattern.sub(replacement, text)
            text = text.strip()
            if not text:
                continue
            if pending is not None:
                number, text = pending[0], pending[1] + " " + text
                pending = None
            if text.endswith("\\"):
                pending = (number, text[:-1].strip())
                continue
            m = re.match(r"^([!\w.,\-]+):\s+(.+)$", text)
            if m:
                tokens = m.group(1).split(",")
                include = any((t[1:] not in factors) if t.startswith("!") else (t in factors) for t in tokens)
                if not include:
                    continue
                text = m.group(2)
            if text.startswith("-"):
                text = text[1:].strip() + " || true"
            elif text.startswith("!"):
                text = text[1:].strip()
            out.append((number, text))
    return out


def nox_arguments(text):
    """Positional arguments of a session.run(...) call; a name or expression becomes "$VAR"."""
    parts = []
    depth = 0
    quote = None
    current = []
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    parts.append("".join(current).strip())
    argv = []
    for part in parts:
        if not part:
            continue
        if re.match(r"^[A-Za-z_]\w*\s*=(?!=)", part):
            break
        m = re.match(r"""^[fFrRbB]*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")$""", part)
        argv.append((m.group(1) if m.group(1) is not None else m.group(2)) if m else "$VAR")
    return argv


def parse_nox(text):
    """[{"name", "line", "runs": [(line, argv)]}] of the sessions of a noxfile, read as text only."""
    lines = text.splitlines()
    sessions = []
    decorator = None
    i = 0
    while i < len(lines):
        raw = lines[i]
        if re.match(r"^@(?:nox\.)?session\b", raw):
            end = _balanced_end("\n".join(lines[i:]), raw.find("(")) if "(" in raw else 0
            decorator = "\n".join(lines[i:])[:end] if end else raw
            i += max(1, decorator.count("\n") + 1)
            continue
        m = re.match(r"^def\s+(\w+)\s*\(", raw)
        if m and decorator is not None:
            name = m.group(1)
            named = re.search(r"""\bname\s*=\s*['"]([^'"]+)['"]""", decorator)
            if named:
                name = named.group(1)
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j][0] in " \t" or lines[j].startswith("#")):
                j += 1
            body = "\n".join(lines[i + 1:j])
            runs = []
            for call in re.finditer(r"\bsession\.run(?:_always)?\(", body):
                end = _balanced_end(body, call.end() - 1)
                argv = nox_arguments(body[call.end():end - 1])
                if argv:
                    runs.append((i + 2 + body.count("\n", 0, call.start()), argv))
            sessions.append({"name": name, "line": i + 1, "runs": runs})
            decorator = None
            i = j
            continue
        if raw.strip() and not raw.startswith(("@", " ", "\t", "#")):
            decorator = None
        i += 1
    return sessions


# --------------------------------------------------------------------------
# Languages, test files, suppressions
# --------------------------------------------------------------------------

def language_of(rel):
    base = posixpath.basename(rel)
    if base.endswith(".gradle.kts"):
        return None
    ext = posixpath.splitext(base)[1].lower()
    return EXT_LANG.get(ext)


def is_test_path(language, rel):
    parts = rel.split("/")
    base = parts[-1]
    dirs = parts[:-1]
    if language == "python":
        return (base.startswith("test_") and base.endswith(".py")) or base.endswith("_test.py") \
            or base == "conftest.py" or "tests" in dirs or "test" in dirs
    if language == "typescript":
        return bool(re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", base)) \
            or "__tests__" in dirs or "tests" in dirs or "test" in dirs
    if language == "rust":
        return "tests" in dirs
    if language in ("java", "kotlin"):
        return bool(re.search(r"(^|/)src/[A-Za-z]*[Tt]est/", rel))
    if language == "go":
        return base.endswith("_test.go")
    return False


def count_loc(data, file_size):
    """Non-blank lines; scaled up when only the start of the file was read."""
    loc = sum(1 for line in data.split(b"\n") if line.strip())
    if file_size > len(data) and len(data) > 0:
        loc = int(loc * (file_size / float(len(data))))
    return loc


def new_stats():
    return {"files": 0, "loc": 0, "test_files": 0, "test_loc": 0}


# --------------------------------------------------------------------------
# Subprojects
# --------------------------------------------------------------------------

def workspace_globs(repo, d):
    """Workspace member globs declared in directory d (package.json or pnpm-workspace.yaml)."""
    globs = []
    pkg = join(d, "package.json")
    if pkg in repo.file_set:
        obj, error = repo.json_file(pkg)
        if error is None and isinstance(obj, dict):
            ws = obj.get("workspaces")
            if isinstance(ws, dict):
                ws = ws.get("packages")
            if isinstance(ws, list):
                globs.extend(str(g) for g in ws if isinstance(g, str))
    pnpm = join(d, "pnpm-workspace.yaml")
    if pnpm in repo.file_set:
        in_packages = False
        for line in repo.text(pnpm).splitlines():
            if re.match(r"^packages\s*:", line):
                in_packages = True
            elif in_packages:
                m = re.match(r"^\s*-\s*['\"]?([^'\"#]+?)['\"]?\s*(#.*)?$", line)
                if m:
                    globs.append(m.group(1))
                elif line.strip() and not line.startswith((" ", "\t")):
                    in_packages = False
    return globs


def workspace_glob_regex(glob):
    glob = glob.strip()
    while glob.startswith("./"):
        glob = glob[2:]
    glob = glob.rstrip("/")
    out = []
    i = 0
    while i < len(glob):
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def npm_workspaces(repo):
    """{root dir: [member dirs]} of the package.json and pnpm workspaces."""
    package_dirs = [dir_of(rel) for rel in repo.by_name.get("package.json", []) if not rel.startswith("../")]
    result = {}
    for d in package_dirs:
        members = set()
        for glob in workspace_globs(repo, d):
            if glob.startswith("!"):
                continue
            regex = workspace_glob_regex(glob)
            for other in package_dirs:
                if other == d or (d != "." and not other.startswith(d + "/")):
                    continue
                if regex.match(other if d == "." else other[len(d) + 1:]):
                    members.add(other)
        if members:
            result[d] = sorted(members)
    return result


def toml_array_strings(text, section, key):
    """The quoted items of `key = [...]` inside [section]; None when the key is absent."""
    in_section = False
    collecting = False
    items = []
    found = False
    for line in text.splitlines():
        line = re.sub(r"\s#.*$", "", line)
        if not collecting:
            m = SECTION_RE.match(line)
            if m:
                in_section = m.group(1).strip() == section
                continue
            if not in_section:
                continue
            m = re.match(r"^\s*" + re.escape(key) + r"\s*=\s*\[(.*)$", line)
            if not m:
                continue
            found = True
            collecting = True
            line = m.group(1)
        items.extend(a or b for a, b in re.findall(r"\"([^\"]+)\"|'([^']+)'", line))
        bare = re.sub(r"\"[^\"]*\"|'[^']*'", "", line)
        if "]" in bare:
            collecting = False
    return items if found else None


def declared_members(repo, d, found):
    """(kind, manifest, [member dirs]) of the workspace rooted at d, or None.

    Cargo [workspace] members, Maven <modules>, Gradle include() in settings,
    Go go.work use, and package.json or pnpm workspaces.
    """
    def under(path):
        return path if d == "." else d + "/" + path

    cargo = join(d, "Cargo.toml")
    if cargo in repo.file_set:
        text = repo.text(cargo)
        members = toml_array_strings(text, "workspace", "members")
        if members is not None:
            excluded = [workspace_glob_regex(g) for g in toml_array_strings(text, "workspace", "exclude") or []]
            result = []
            for glob in members:
                regex = workspace_glob_regex(glob)
                for other, entry in found.items():
                    relative = other if d == "." else other[len(d) + 1:]
                    if other != d and (d == "." or other.startswith(d + "/")) and regex.match(relative) \
                            and join(other, "Cargo.toml") in entry["manifests"] \
                            and not any(e.match(relative) for e in excluded):
                        result.append(other)
            return "cargo", cargo, result
    pom = join(d, "pom.xml")
    if pom in repo.file_set:
        modules = re.findall(r"<module>\s*([^<\s]+)\s*</module>", repo.text(pom))
        if modules:
            result = []
            for module in modules:
                module = posixpath.normpath(under(posixpath.dirname(module) if module.endswith(".xml") else module))
                if module in repo.dirs and module != d:
                    result.append(module)
            return "maven", pom, result
    for name in ("settings.gradle", "settings.gradle.kts"):
        settings = join(d, name)
        if settings in repo.file_set:
            result = []
            for call in re.finditer(r"\binclude\s*\(?\s*((?:['\"][^'\"]+['\"]\s*,?\s*)+)", repo.text(settings)):
                for name_ in re.findall(r"['\"]([^'\"]+)['\"]", call.group(1)):
                    member = posixpath.normpath(under(name_.strip(":").replace(":", "/")))
                    if member in repo.dirs and member != d:
                        result.append(member)
            if result:
                return "gradle", settings, result
    work = join(d, "go.work")
    if work in repo.file_set:
        text = repo.text(work)
        used = re.findall(r"^\s*use\s+(\S+)\s*$", text, re.M)
        for block in re.findall(r"^\s*use\s*\(([^)]*)\)", text, re.M | re.S):
            used.extend(re.sub(r"\s*//.*$", "", l).strip() for l in block.splitlines()
                        if re.sub(r"\s*//.*$", "", l).strip())
        result = [posixpath.normpath(under(u.strip("\"'"))) for u in used]
        result = [m for m in result if m in repo.dirs and m != d]
        if result:
            return "go", work, result
    members = set()
    for glob in workspace_globs(repo, d):
        if glob.startswith("!"):
            continue
        regex = workspace_glob_regex(glob)
        for other in found:
            relative = other if d == "." else other[len(d) + 1:]
            if other != d and (d == "." or other.startswith(d + "/")) and regex.match(relative):
                members.add(other)
    if members:
        kind = "pnpm" if join(d, "pnpm-workspace.yaml") in repo.file_set else "npm"
        return kind, join(d, "package.json"), sorted(members)
    return None


def find_subprojects(repo):
    """({dir: {"manifests": [rel...], "languages": set}}, {root: workspace}) from the manifest files.

    A workspace root is one subproject; its members are listed in the workspace
    ({"kind", "manifest", "members": [dirs], "entries": {dir: entry}}) and are not
    subprojects of their own.
    """
    found = {}
    for name, language in MANIFESTS.items():
        for rel in repo.by_name.get(name, []):
            if rel.startswith("../"):
                continue
            d = dir_of(rel)
            entry = found.setdefault(d, {"manifests": [], "languages": set()})
            entry["manifests"].append(rel)
            entry["languages"].add(language)
            if name in ("build.gradle", "build.gradle.kts", "pom.xml"):
                entry["languages"].discard("java")
                text = repo.text(rel)
                entry["languages"].add("kotlin" if re.search(r"kotlin", text, re.I) else "java")
    workspaces = {}
    for d in sorted(found, key=lambda x: (x.count("/"), x)) + sorted(
            {dir_of(r) for n in ("settings.gradle", "settings.gradle.kts") for r in repo.by_name.get(n, [])
             if not r.startswith("../") and dir_of(r) not in found}):
        declared = declared_members(repo, d, found)
        if declared is None:
            continue
        kind, manifest, members = declared
        workspaces[d] = {"kind": kind, "manifest": manifest, "members": sorted(set(members))}
        if d not in found:
            found[d] = {"manifests": [manifest], "languages": set()}
    claimed = {}
    for root in sorted(workspaces, key=lambda x: (x.count("/"), x)):
        if root in claimed:
            outer = claimed[root]
            workspaces[outer]["members"] = sorted(set(workspaces[outer]["members"]) | set(workspaces[root]["members"]))
            for member in workspaces[root]["members"]:
                claimed[member] = outer
            continue
        for member in workspaces[root]["members"]:
            claimed.setdefault(member, root)
    for root in [r for r in workspaces if r in claimed]:
        del workspaces[root]
    for root, workspace in workspaces.items():
        workspace["members"] = [m for m in workspace["members"] if claimed.get(m) == root and m != root]
        workspace["entries"] = {m: found.get(m, {"manifests": [], "languages": set()}) for m in workspace["members"]}
    for member in claimed:
        found.pop(member, None)
    return found, workspaces


README_KNOWN_PROGRAMS = {
    "npm", "pnpm", "yarn", "bun", "npx", "pnpx", "bunx", "pip", "pip3", "python", "python3", "pytest", "uv", "uvx",
    "poetry", "pdm", "pipx", "hatch", "tox", "nox", "make", "gmake", "just", "cargo", "go", "mvn", "mvnw", "gradle",
    "gradlew", "pre-commit", "ruff", "black", "isort", "mypy", "pyright", "flake8", "pylint", "eslint", "prettier",
    "biome", "tsc", "jest", "vitest", "docker", "docker-compose", "node", "deno", "golangci-lint", "gofmt", "bundle",
    "rake",
}
README_IGNORED = {"echo", "export", "source", ".", "true", "false", ":", "exit", "set", "unset", "alias", "read",
                  "printf", "test", "[", "ls", "cat", "mkdir", "cp", "mv", "rm", "touch", "chmod", "sleep", "pwd",
                  "open", "tee", "grep", "sed", "head", "tail"}
README_PLACEHOLDER = re.compile(r"<[A-Za-z][\w\- ]*>|(?<![\w./])\.\.\.(?![\w./])|…")
README_STANDALONE = {"pytest", "tox", "nox", "make", "pre-commit", "mypy", "ruff", "eslint", "prettier", "tsc", "jest",
                     "vitest"}
CARGO_BUILTIN = {
    "add", "bench", "build", "b", "check", "c", "clean", "clippy", "doc", "d", "fetch", "fix", "fmt",
    "generate-lockfile", "help", "init", "install", "locate-project", "login", "logout", "metadata", "miri", "new",
    "owner", "package", "pkgid", "publish", "read-manifest", "remove", "report", "run", "r", "rustc", "rustdoc",
    "search", "test", "t", "tree", "uninstall", "update", "vendor", "verify-project", "version", "yank",
}
CARGO_PLUGINS = {
    "nextest", "llvm-cov", "tarpaulin", "deny", "audit", "machete", "udeps", "expand", "watch", "make", "outdated",
    "bloat", "fuzz", "insta", "release", "edit", "hack", "geiger", "vet", "careful", "semver-checks", "binstall",
    "zigbuild", "leptos", "tauri", "component", "generate", "xtask", "mutants", "shear", "dist", "sqlx", "diesel",
}
GO_SUBCOMMANDS = {"bug", "build", "clean", "doc", "env", "fix", "fmt", "generate", "get", "install", "list", "mod",
                  "work", "run", "telemetry", "test", "tool", "version", "vet", "help"}
GRADLE_STANDARD_TASKS = {
    "assemble", "build", "check", "clean", "test", "jar", "javadoc", "run", "bootRun", "tasks", "help", "dependencies",
    "projects", "properties", "wrapper", "init", "classes", "testClasses", "compileJava", "compileKotlin", "bootJar",
    "publish", "publishToMavenLocal", "installDist", "distZip", "dependencyInsight", "buildEnvironment", "components",
    "outgoingVariants", "resolvableConfigurations",
}
PYTHON_STDLIB_MODULES = {
    "pip", "venv", "http", "unittest", "json", "timeit", "cProfile", "profile", "pdb", "doctest", "zipapp", "ensurepip",
    "compileall", "py_compile", "site", "this", "sqlite3", "tarfile", "zipfile", "tokenize", "trace", "calendar",
    "uuid", "base64", "webbrowser", "pydoc", "pickle", "platform", "sysconfig", "wsgiref", "xml", "asyncio", "ast",
    "dis", "gzip", "glob", "shlex", "tkinter", "turtle", "cmd", "code", "codecs", "csv",
}

# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------

def toml_array_count(text, section, key):
    """Quoted items in `key = [...]` inside [section]; None when the key is absent."""
    in_section = False
    collecting = False
    count = 0
    found = False
    for line in text.splitlines():
        line = re.sub(r"\s#.*$", "", line)
        if not collecting:
            m = SECTION_RE.match(line)
            if m:
                in_section = m.group(1).strip() == section
                continue
            if not in_section:
                continue
            m = re.match(r"^\s*" + re.escape(key) + r"\s*=\s*\[(.*)$", line)
            if not m:
                continue
            found = True
            collecting = True
            line = m.group(1)
        count += len(re.findall(r"\"[^\"]+\"|'[^']+'", line))
        bare = re.sub(r"\"[^\"]*\"|'[^']*'", "", line)
        if "]" in bare:
            collecting = False
    return count if found else None


def toml_section_entries(text, section_prefix):
    """Number of `name = ...` lines in [section] plus [section.name] tables."""
    count = 0
    in_section = False
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            header = m.group(1).strip()
            if header == section_prefix:
                in_section = True
            elif header.startswith(section_prefix + "."):
                in_section = False
                count += 1
            else:
                in_section = False
            continue
        if in_section and re.match(r"^\s*[A-Za-z0-9_\-]+\s*=", line):
            count += 1
    return count


def count_dependencies(repo, d, manifests):
    direct = 0
    dev = 0
    files = []
    for rel in manifests:
        base = posixpath.basename(rel)
        text = repo.text(rel)
        if base == "pyproject.toml":
            n = toml_array_count(text, "project", "dependencies")
            if n is not None:
                direct += n
                files.append(rel)
        elif base == "package.json":
            obj, error = repo.json_file(rel)
            if error is None and isinstance(obj, dict):
                direct += len(obj.get("dependencies") or {})
                dev += len(obj.get("devDependencies") or {})
                files.append(rel)
        elif base == "Cargo.toml":
            direct += toml_section_entries(text, "dependencies")
            dev += toml_section_entries(text, "dev-dependencies")
            files.append(rel)
        elif base == "go.mod":
            block = False
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("require ("):
                    block = True
                elif block and stripped == ")":
                    block = False
                elif (block or stripped.startswith("require ")) and stripped and \
                        not stripped.startswith("//") and "// indirect" not in stripped:
                    direct += 1
            files.append(rel)
        elif base == "pom.xml":
            body = re.sub(r"<dependencyManagement>.*?</dependencyManagement>", "", text, flags=re.S)
            deps = re.findall(r"<dependency>.*?</dependency>", body, flags=re.S)
            for dep in deps:
                if re.search(r"<scope>\s*test\s*</scope>", dep):
                    dev += 1
                else:
                    direct += 1
            files.append(rel)
        elif base in ("build.gradle", "build.gradle.kts"):
            for line in text.splitlines():
                m = re.match(r"^\s*(implementation|api|compileOnly|runtimeOnly|kapt|annotationProcessor"
                             r"|testImplementation|testRuntimeOnly|testCompileOnly)\b", line)
                if m:
                    if m.group(1).startswith("test"):
                        dev += 1
                    else:
                        direct += 1
            files.append(rel)
    reqs = [r for r in sorted(repo.by_dir.get(d, [])) if re.match(r"^requirements[\w.\-]*\.txt$", r)]
    for name in reqs:
        rel = join(d, name)
        n = sum(1 for line in repo.text(rel).splitlines()
                if line.strip() and not line.strip().startswith(("#", "-")))
        if "dev" in name or "test" in name:
            dev += n
        else:
            direct += n
        files.append(rel)
    return {"direct": direct, "dev": dev, "files": files}


# --------------------------------------------------------------------------
# The detection pass
# --------------------------------------------------------------------------

def strip_jsonc(text):
    """Remove // and /* */ comments and trailing commas outside strings."""
    out = []
    i = 0
    n = len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            out.append(ch)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 1
        else:
            out.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def tsconfig_info(repo, rel):
    text = repo.text(rel)
    info = {"strict": None, "extends": None}
    try:
        obj = json.loads(strip_jsonc(text))
        if isinstance(obj, dict):
            options = obj.get("compilerOptions")
            if isinstance(options, dict) and isinstance(options.get("strict"), bool):
                info["strict"] = options["strict"]
            ext = obj.get("extends")
            if isinstance(ext, (str, list)):
                info["extends"] = ext
        return info
    except ValueError:
        if re.search(r'"strict"\s*:\s*true', text):
            info["strict"] = True
        return info


class Detector(object):
    def __init__(self, root, max_subprojects):
        self.repo = Repo(root)
        self.max_subprojects = max_subprojects
        self.scripts = {}
        self.script_commands = []                # (file, line, text)
        self.script_hits = []                    # (file, line, owner, [tool names])
        self.package_names = {}
        self.npm_workspaces = {}
        self.hook_defs = []
        self.ci_facts = []
        self.script_facts = []
        self._gradle_verification = None
        self.reader = CommandReader(self)

    # ---- languages, suppressions, per-subproject stats ----------------

    def scan_sources(self, subproject_dirs):
        repo = self.repo
        languages = {lang: new_stats() for lang in LANGUAGES}
        for lang in languages:
            if lang == "rust":
                languages[lang]["inline_test_files"] = 0
        other = defaultdict(int)
        excluded = defaultdict(list)
        supp = {lang: {"total": 0, "markers": defaultdict(int), "files": defaultdict(int)}
                for lang in SUPPRESSIONS}
        per_sub = defaultdict(lambda: {lang: new_stats() for lang in LANGUAGES})
        cache = {}
        for rel in repo.files:
            ext = posixpath.splitext(rel)[1].lower()
            lang = language_of(rel)
            if lang is None:
                if ext in OTHER_EXT:
                    other[OTHER_EXT[ext]] += 1
                continue
            path = os.path.join(repo.root, rel)
            try:
                size = os.path.getsize(path)
                with open(path, "rb") as handle:
                    data = handle.read(READ_LIMIT)
            except OSError:
                continue
            kind = repo.exclusion_kind(rel, data[:2048])
            if kind:
                excluded[kind].append(rel)
                continue
            loc = count_loc(data, size)
            test = is_test_path(lang, rel)
            sub = self.owner(dir_of(rel), subproject_dirs, cache)
            for stats in (languages[lang], per_sub[sub][lang] if sub is not None else None):
                if stats is None:
                    continue
                if test:
                    stats["test_files"] += 1
                    stats["test_loc"] += loc
                else:
                    stats["files"] += 1
                    stats["loc"] += loc
            if lang == "rust" and not test and b"#[cfg(test)]" in data:
                languages["rust"]["inline_test_files"] += 1
            for marker in SUPPRESSIONS[lang]:
                n = data.count(marker.encode("utf-8"))
                if n:
                    supp[lang]["total"] += n
                    supp[lang]["markers"][marker] += n
                    supp[lang]["files"][rel] += n
        suppressions = {}
        for lang, info in supp.items():
            if not info["total"]:
                continue
            top = sorted(info["files"].items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            suppressions[lang] = {
                "total": info["total"],
                "markers": dict(sorted(info["markers"].items())),
                "top_files": [{"file": f, "count": c} for f, c in top],
            }
        return languages, dict(other), suppressions, per_sub, excluded

    @staticmethod
    def owner(d, subproject_dirs, cache):
        if d in cache:
            return cache[d]
        result = None
        for candidate in ([] if d.startswith("..") else ancestors(d)):
            if candidate in subproject_dirs:
                result = candidate
                break
        cache[d] = result
        return result

    # ---- scripts, runners and followed files ---------------------------

    def collect_scripts(self):
        """package.json scripts, Makefile and justfile recipes, Taskfile commands."""
        repo = self.repo
        self.scripts = {"npm": defaultdict(list), "make": defaultdict(list), "just": defaultdict(list)}
        self.script_commands = []                # (file, line, text)
        self.package_names = {}
        for rel in repo.by_name.get("package.json", []):
            obj, error = repo.json_file(rel)
            if error is not None or not isinstance(obj, dict):
                continue
            if isinstance(obj.get("name"), str):
                self.package_names[dir_of(rel)] = obj["name"]
            if not isinstance(obj.get("scripts"), dict):
                continue
            text = repo.text(rel)
            start = text.find('"scripts"')
            for name, command in obj["scripts"].items():
                if not isinstance(command, str):
                    continue
                m = re.compile(r'^\s*"' + re.escape(name) + r'"\s*:', re.M).search(text, max(start, 0))
                line = text.count("\n", 0, m.start()) + 1 if m else 1
                self.scripts["npm"][name].append({"name": name, "file": rel, "line": line, "body": command,
                                                  "dir": dir_of(rel)})
                self.script_commands.append((rel, line, command))
        for names, kind in ((("Makefile", "GNUmakefile", "makefile"), "make"),
                            (("justfile", "Justfile", ".justfile"), "just")):
            for name in names:
                for rel in repo.by_name.get(name, []):
                    for target, (line, commands, deps) in make_recipes(repo.text(rel)).items():
                        commands = [c.lstrip("@-+ ") for c in commands]
                        body = "\n".join(commands + [kind + " " + dep for dep in deps])
                        self.scripts[kind][target].append({"name": target, "file": rel, "line": line, "body": body,
                                                           "dir": dir_of(rel)})
                        for offset, command in enumerate(commands):
                            self.script_commands.append((rel, line + offset + 1, command))
        for name in ("Taskfile.yml", "Taskfile.yaml"):
            for rel in repo.by_name.get(name, []):
                for line, command in yaml_commands(repo.text(rel)):
                    self.script_commands.append((rel, line, command))

    def scripts_for(self, kind, name, scope):
        entries = list(self.scripts.get(kind, {}).get(name, []))
        if kind == "npm" and scope.get("workspace"):
            members = self.workspace_dirs_for(scope.get("filters") or [])
            if members is not None:
                entries = [e for e in entries if e["dir"] in members]
        elif scope.get("directory"):
            directory = posixpath.normpath(scope["directory"])
            entries = [e for e in entries if e["dir"] == directory]
        return entries

    def workspace_dirs_for(self, filters):
        """Directories a workspace runner reaches: every member, or the ones a filter names."""
        everything = set()
        for root, members in self.npm_workspaces.items():
            everything.add(root)
            everything.update(members)
        if not everything:
            return None
        patterns = [re.sub(r"^\.\.\.|\.\.\.$", "", f.strip("{}'\"")).lstrip("!") for f in filters if f]
        if not patterns:
            return everything
        matched = set()
        for d in everything:
            name = self.package_names.get(d, "")
            for pattern in patterns:
                path = pattern[2:] if pattern.startswith("./") else pattern
                if fnmatch.fnmatchcase(name, pattern) or fnmatch.fnmatchcase(d, path):
                    matched.add(d)
        return matched or everything

    def repo_path(self, path):
        """A path named in a CI command, as a path of the scanned folder; None when it leaves the repository."""
        if not path or "$" in path or path.startswith(("/", "~")):
            return None
        norm = posixpath.normpath(path)
        if norm.startswith(".."):
            return None
        repo = self.repo
        if repo.subpath == ".":
            return norm
        if norm.startswith(repo.subpath + "/"):
            return norm[len(repo.subpath) + 1:]
        return repo._relative_above(norm)

    def pinned_requirements(self, path):
        """True when every requirement of a requirements file is pinned with == or a hash."""
        rel = self.repo_path(path)
        if rel is None or rel not in self.repo.file_set:
            return False
        for line in self.repo.text(rel).replace("\\\n", " ").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("-e", "--editable")):
                return False
            if line.startswith("-"):
                continue
            if "==" not in line and "--hash" not in line:
                return False
        return True

    def gradle_verification(self):
        """[(tool, build file, line)] of the verification plugins a Gradle `check` or `build` runs."""
        if self._gradle_verification is None:
            repo = self.repo
            files = [f for f in repo.files if f.endswith((".gradle", ".gradle.kts", "libs.versions.toml"))][:200]
            texts = [(f, repo.text(f)) for f in files]
            found = []
            for name in GRADLE_VERIFICATION_WORDS:
                regex = re.compile(word_regex(name, name == "pmd"), re.I)
                for f, text in texts:
                    hit = next((n for n, line in enumerate(text.splitlines(), 1) if regex.search(line)), None)
                    if hit:
                        found.append((name, f, hit))
                        break
            for name, marker in (("jacoco", "violationRules"), ("kover", "minBound")):
                for f, text in texts:
                    if name in text.lower() and marker in text:
                        found.append((name, f, text.count("\n", 0, text.index(marker)) + 1))
                        break
            self._gradle_verification = found
        return self._gradle_verification

    def follow_precommit(self, reader, out, hook, skip, line, ctx):
        skipped = set(skip.split(","))
        for definition in self.hook_defs:
            if (hook and definition["id"] != hook) or definition["id"] in skipped:
                continue
            for name in definition["tools"]:
                reader.hit(out, name, line, ctx, writes=False,
                           via=("pre-commit", definition["file"], definition["line"]))

    def follow_tox(self, reader, out, args, line, ctx):
        environments = []
        config = "tox.ini"
        i = 0
        while i < len(args):
            a = args[i]
            name, eq, value = a.partition("=")
            if name in ("-e", "--env"):
                environments.extend(expand_env_list(value if eq else (args[i + 1] if i + 1 < len(args) else "")))
                i += 0 if eq else 1
            elif name in ("-c", "--conf"):
                config = value if eq else (args[i + 1] if i + 1 < len(args) else config)
                i += 0 if eq else 1
            elif name in ("-f", "--factor", "--skip-env", "-x", "--override", "--workdir", "--root"):
                i += 0 if eq else 1
            i += 1
        rel = self.repo_path(config)
        sections = None
        if rel and rel in self.repo.file_set:
            sections = parse_ini(self.repo.text(rel))
        elif "pyproject.toml" in self.repo.file_set:
            text = self.repo.text("pyproject.toml")
            m = re.search(r'legacy_tox_ini\s*=\s*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', text, re.S)
            if m:
                rel = "pyproject.toml"
                sections = parse_ini(m.group(1), text.count("\n", 0, m.start(1)) + 1)
        if not sections:
            return
        if not environments:
            environments = expand_env_list(",".join(p[1] for p in sections.get("tox", {}).get("envlist", []))) or [""]
        for env in environments:
            for number, command in tox_commands(sections, env):
                reader.follow_text(out, command, line, ctx, ("tox:" + (env or "testenv"), rel, number))

    def follow_nox(self, reader, out, args, line, ctx):
        path = "noxfile.py"
        selected = []
        i = 0
        while i < len(args):
            a = args[i]
            name, eq, value = a.partition("=")
            if name in ("-s", "-e", "--session", "--sessions", "--session-name"):
                if eq:
                    selected.append(value)
                while not eq and i + 1 < len(args) and not args[i + 1].startswith("-"):
                    selected.append(args[i + 1])
                    i += 1
            elif name in ("-f", "--noxfile"):
                path = value if eq else (args[i + 1] if i + 1 < len(args) else path)
                i += 0 if eq else 1
            elif name in ("-p", "--python", "-t", "--tags", "-k", "--keywords", "--force-python", "--extra-python"):
                i += 0 if eq else 1
            i += 1
        rel = self.repo_path(path)
        if rel is None or rel not in self.repo.file_set:
            return
        text = self.repo.text(rel)
        sessions = parse_nox(text)
        if not selected:
            m = re.search(r"nox\.options\.sessions\s*=\s*\[([^\]]*)\]", text)
            if m:
                selected = re.findall(r"""['"]([^'"]+)['"]""", m.group(1))
        for session in sessions:
            if selected and not any(session["name"] == s or session["name"].startswith(s + "-")
                                    or s.startswith(session["name"] + "-") for s in selected):
                continue
            for run_line, argv in session["runs"]:
                reader.follow_argv(out, argv, line, ctx, ("nox:" + session["name"], rel, run_line))

    # ---- CI -------------------------------------------------------------

    CI_FILE_RES = [
        ("github", re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")),
        ("gitlab", re.compile(r"^(\.gitlab-ci\.yml|\.gitlab/ci/[^/]+\.ya?ml)$")),
        ("jenkins", re.compile(r"(^|/)Jenkinsfile[^/]*$")),
        ("circleci", re.compile(r"^\.circleci/[^/]+\.ya?ml$")),
        ("azure", re.compile(r"^(azure-pipelines\.ya?ml|\.?azure-pipelines/[^/]+\.ya?ml)$")),
        ("buildkite", re.compile(r"^\.buildkite/[^/]+\.ya?ml$|^buildkite\.ya?ml$")),
        ("bitbucket", re.compile(r"^bitbucket-pipelines\.yml$")),
        ("travis", re.compile(r"^\.travis\.yml$")),
        ("drone", re.compile(r"^\.drone\.yml$")),
    ]

    def ci_rows(self, rel, steps):
        """Tool rows of a list of CI steps, merged by (tool, via, writes)."""
        merged = {}
        for step in steps:
            for hit in step.outcome.hits:
                key = (hit.tool.name, hit.via, hit.writes)
                row = merged.get(key)
                if row is None:
                    row = merged[key] = {
                        "tool": hit.tool.name, "category": hit.tool.category, "language": hit.tool.language,
                        "file": rel, "line": hit.line, "how": "ci", "lines": [], "commands": [],
                        "non_blocking": True, "pull_request": False, "jobs": [], "_seen": set()}
                    if hit.via:
                        row["via"] = hit.via
                        row["via_file"] = hit.via_file
                        row["via_line"] = hit.via_line
                    if hit.writes:
                        row["writes"] = True
                if (hit.line, hit.command) not in row["_seen"]:
                    row["_seen"].add((hit.line, hit.command))
                    row["lines"].append(hit.line)
                    row["commands"].append(hit.command.strip()[:200])
                row["non_blocking"] = row["non_blocking"] and hit.non_blocking
                row["pull_request"] = better(row["pull_request"], step.pull_request)
                if step.job is not None and step.job not in row["jobs"]:
                    row["jobs"].append(step.job)
        rows = []
        for row in merged.values():
            del row["_seen"]
            rows.append(row)
        rows.sort(key=lambda r: (r["line"], r["tool"]))
        return rows

    def detect_ci(self):
        repo = self.repo
        reader = self.reader
        files = []
        by_tool = defaultdict(list)
        locked = []
        facts = []
        for rel in repo.files + repo.above:
            provider = None
            top = re.sub(r"^(\.\./)+", "", rel)
            for name, regex in self.CI_FILE_RES:
                if regex.search(top):
                    provider = name
                    break
            if provider is None:
                continue
            structure = ci_structure(provider, repo.text(rel))
            all_steps = [step for _name, _pr, steps in structure["jobs"] for step in steps]
            installs = []
            file_locks = []
            for step in all_steps:
                if step.kind == "uses":
                    step.outcome = reader.read_uses(step.text, step.line, step.non_blocking)
                else:
                    step.outcome = reader.read(step.text, step.line, nb=step.non_blocking)
                installs.extend(step.outcome.installs)
                file_locks.extend(step.outcome.locks)
                for fact in step.outcome.facts:
                    if not fact["kind"].startswith("poetry-"):
                        facts.append(dict(fact, how="ci", file=rel))
            if any(f["kind"] == "poetry-check-lock" for step in all_steps for f in step.outcome.facts):
                file_locks.extend({"kind": "poetry install + poetry check --lock", "line": i["line"],
                                   "command": i["command"]} for i in installs if i["manager"] == "poetry")
            if structure["tree"] is not None:
                for key, value in walk_yaml(structure["tree"]):
                    if key == "RUSTFLAGS" and isinstance(value, str) and re.search(r"-D\s?warnings|--deny[ =]warnings",
                                                                                   value):
                        facts.append({"kind": "rustflags-deny-warnings", "how": "ci", "file": rel,
                                      "line": value.line, "command": str(value)[:200]})
            locked.extend(dict(lock, file=rel) for lock in file_locks)
            rows = self.ci_rows(rel, all_steps)
            pull_request = structure["pull_request"]
            entry = {"file": rel, "provider": provider, "pull_request": pull_request,
                     "trigger_note": PUSH_DEFAULT_NOTE.get(provider) if pull_request == "push-default" else None,
                     "events": structure["events"], "tools": rows,
                     "jobs": [{"name": name, "pull_request": pr, "rows": self.ci_rows(rel, steps)}
                              for name, pr, steps in structure["jobs"]],
                     "installs": installs}
            if rel.startswith("../"):
                entry["inherited_from"] = dir_of(rel)
            files.append(entry)
            for row in rows:
                if rel not in by_tool[row["tool"]]:
                    by_tool[row["tool"]].append(rel)
        self.ci_facts = facts
        return {"files": files, "tools": {k: v for k, v in sorted(by_tool.items())}, "locked_installs": locked}

    def match_tools(self, text, tools):
        low = text.lower()
        return [t for t in tools if t.ci_match(low)]

    # ---- pre-commit, husky, lefthook ------------------------------------

    def detect_precommit(self):
        repo = self.repo
        hooks = []
        rows = {}
        config = None
        self.hook_defs = []
        for rel in repo.by_name.get(".pre-commit-config.yaml", []):
            config = config or rel
            repo_url = None
            rev = None
            current = None
            text = repo.text(rel)
            for number, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                m = re.match(r"^\s*-?\s*repo\s*:\s*(\S+)", line)
                if m:
                    repo_url, rev = m.group(1), None
                    continue
                m = re.match(r"^\s*rev\s*:\s*(\S+)", line)
                if m:
                    rev = m.group(1).strip("'\"")
                    continue
                m = re.match(r"^\s*-?\s*id\s*:\s*(\S+)", line)
                if m:
                    hooks.append({"id": m.group(1), "repo": repo_url, "rev": rev, "line": number})
                    current = {"id": m.group(1), "file": rel, "line": number, "tools": []}
                    self.hook_defs.append(current)
                    matched = self.match_tools(m.group(1), ALL_TOOLS)
                    for tool in matched:
                        rows.setdefault((tool.name, rel), self.precommit_row(tool, rel, number))
                        if not (tool.name == "ruff" and any(t.name == "ruff-format" for t in matched)):
                            current["tools"].append(tool.name)
                    continue
                m = re.match(r"^\s*entry\s*:\s*(.+)$", line)
                if m:
                    for hit in self.reader.read(m.group(1), follow=False).hits:
                        rows.setdefault((hit.tool.name, rel), self.precommit_row(hit.tool, rel, number))
                        if current is not None and hit.tool.name not in current["tools"]:
                            current["tools"].append(hit.tool.name)
        husky = sorted(f for f in repo.files if f.startswith(".husky/") and "/_/" not in f
                       and not f.startswith(".husky/_"))
        lefthook = [f for name in ("lefthook.yml", "lefthook.yaml", ".lefthook.yml")
                    for f in repo.by_name.get(name, [])]
        for rel in husky:
            for number, command in shell_commands(repo.text(rel)):
                for hit in self.reader.read(command, follow=False).hits:
                    rows.setdefault((hit.tool.name, rel), self.precommit_row(hit.tool, rel, number))
        for rel in lefthook:
            for number, command in yaml_commands(repo.text(rel)):
                for hit in self.reader.read(command, follow=False).hits:
                    rows.setdefault((hit.tool.name, rel), self.precommit_row(hit.tool, rel, number))
        return {"config": config, "hooks": hooks[:200], "husky": husky, "lefthook": lefthook,
                "tools": sorted(rows.values(), key=lambda r: (r["file"], r["line"], r["tool"]))}

    @staticmethod
    def precommit_row(tool, rel, line):
        return {"tool": tool.name, "category": tool.category, "language": tool.language,
                "file": rel, "line": line, "how": "precommit"}

    # ---- setup ----------------------------------------------------------

    LOCKFILES = {
        "uv.lock": "python", "poetry.lock": "python", "Pipfile.lock": "python", "pdm.lock": "python",
        "package-lock.json": "typescript", "npm-shrinkwrap.json": "typescript",
        "yarn.lock": "typescript", "pnpm-lock.yaml": "typescript", "bun.lockb": "typescript",
        "bun.lock": "typescript", "Cargo.lock": "rust", "go.sum": "go", "gradle.lockfile": "java",
    }
    PINS = (".python-version", ".nvmrc", ".node-version", "rust-toolchain", "rust-toolchain.toml",
            ".tool-versions", "mise.toml", ".mise.toml", ".sdkmanrc", ".java-version", "gradlew",
            "mvnw", "runtime.txt")
    RUNNERS = {"Makefile": "make", "GNUmakefile": "make", "makefile": "make", "justfile": "just",
               "Justfile": "just", "Taskfile.yml": "task", "Taskfile.yaml": "task",
               "noxfile.py": "nox", "tox.ini": "tox"}

    @staticmethod
    def pin_value(name, text):
        """The version a one-value pin file names."""
        if name in (".python-version", ".nvmrc", ".node-version", ".java-version", "rust-toolchain", "runtime.txt"):
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
        if name == "rust-toolchain.toml":
            m = re.search(r"^channel\s*=\s*[\"']([^\"']+)", text, re.M)
            return m.group(1) if m else None
        return None

    def lockfile_age(self, lockfiles):
        """Add last_commit (the committer date of the file's last commit) to up to 20 lockfiles."""
        repo = self.repo
        for index, lock in enumerate(lockfiles):
            lock["last_commit"] = None
            if not repo.is_git or index >= 20:
                continue
            out = run_git(repo.git_root, ["log", "-1", "--no-show-signature", "--format=%cI", "--",
                                          repo.top_rel(lock["file"])])
            if out:
                lock["last_commit"] = out.decode("utf-8", "replace").strip() or None

    def detect_setup(self, subproject_dirs):
        repo = self.repo
        cache = {}

        def sub_of(rel):
            return self.owner(dir_of(rel), subproject_dirs, cache)

        lockfiles = []
        for name, eco in self.LOCKFILES.items():
            for rel in repo.by_name.get(name, []):
                lockfiles.append({"file": rel, "ecosystem": eco, "subproject": sub_of(rel)})
        requirements = sorted(f for f in repo.files if re.match(r"^requirements[\w.\-]*\.txt$", posixpath.basename(f)))
        pins = []
        for name in self.PINS:
            for rel in repo.by_name.get(name, []):
                pin = {"kind": name, "file": rel, "line": 1, "subproject": sub_of(rel)}
                value = self.pin_value(name, repo.text(rel))
                if value:
                    pin["value"] = value
                pins.append(pin)
        for rel in ("gradle/wrapper/gradle-wrapper.properties", ".mvn/wrapper/maven-wrapper.properties"):
            for f in repo.files:
                if f == rel or f.endswith("/" + rel):
                    pins.append({"kind": posixpath.basename(f), "file": f, "line": 1, "subproject": sub_of(f)})
        for rel in repo.by_name.get("go.mod", []):
            m = re.search(r"^go\s+(\S+)", repo.text(rel), re.M)
            if m:
                line = repo.text(rel).count("\n", 0, m.start()) + 1
                pins.append({"kind": "go directive", "file": rel, "line": line, "value": m.group(1),
                             "subproject": sub_of(rel)})
        for rel in repo.by_name.get("go.mod", []):
            m = re.search(r"^toolchain\s+(\S+)", repo.text(rel), re.M)
            if m:
                line = repo.text(rel).count("\n", 0, m.start()) + 1
                pins.append({"kind": "go toolchain", "file": rel, "line": line, "value": m.group(1),
                             "subproject": sub_of(rel)})
        for rel in repo.by_name.get("package.json", []):
            obj, error = repo.json_file(rel)
            if error is not None or not isinstance(obj, dict) or rel.startswith("../"):
                continue
            engines = obj.get("engines")
            if isinstance(engines, dict):
                hit = repo.match_spec("package.json::engines", dir_of(rel))
                pin = {"kind": "package.json engines", "file": rel, "line": hit[1] if hit else 1,
                       "subproject": sub_of(rel)}
                if isinstance(engines.get("node"), str):
                    pin["value"] = engines["node"]
                pins.append(pin)
            for key in ("packageManager", "volta"):
                hit = repo.match_spec("package.json::" + key, dir_of(rel))
                if hit:
                    value = obj[key] if isinstance(obj[key], str) else (obj[key].get("node")
                                                                       if isinstance(obj[key], dict) else None)
                    pin = {"kind": "package.json " + key, "file": rel, "line": hit[1], "subproject": sub_of(rel)}
                    if isinstance(value, str):
                        pin["value"] = value
                    pins.append(pin)
        for rel in repo.by_name.get("Cargo.toml", []):
            m = re.search(r"^rust-version\s*=\s*[\"']([^\"']+)", repo.text(rel), re.M)
            if m:
                line = repo.text(rel).count("\n", 0, m.start()) + 1
                pins.append({"kind": "rust-version", "file": rel, "line": line, "value": m.group(1),
                             "subproject": sub_of(rel)})
        for rel in repo.files:
            if rel.endswith((".gradle", ".gradle.kts")):
                m = re.search(r"jvmToolchain\s*\(\s*(\d+)|JavaLanguageVersion\.of\(\s*(\d+)|\btoolchain\s*\{", repo.text(rel))
                if m:
                    line = repo.text(rel).count("\n", 0, m.start()) + 1
                    pin = {"kind": "java.toolchain", "file": rel, "line": line, "subproject": sub_of(rel)}
                    version = re.search(r"jvmToolchain\s*\(\s*(\d+)|JavaLanguageVersion\.of\(\s*(\d+)", repo.text(rel))
                    if version:
                        pin["value"] = version.group(1) or version.group(2)
                    pins.append(pin)
        for rel in repo.by_name.get("pyproject.toml", []):
            m = re.search(r"^requires-python\s*=\s*(.+)$", repo.text(rel), re.M)
            if m:
                line = repo.text(rel).count("\n", 0, m.start()) + 1
                pins.append({"kind": "requires-python", "file": rel, "line": line,
                             "value": m.group(1).strip().strip("\"'"), "subproject": sub_of(rel)})
        runners = []
        for name, kind in self.RUNNERS.items():
            for rel in repo.by_name.get(name, []):
                targets = []
                if kind in ("make", "just"):
                    targets = list(make_recipes(repo.text(rel)))
                runners.append({"kind": kind, "file": rel, "targets": targets[:40], "subproject": sub_of(rel)})
        for rel in repo.by_name.get("package.json", []):
            obj, error = repo.json_file(rel)
            if error is None and isinstance(obj, dict) and isinstance(obj.get("scripts"), dict):
                runners.append({"kind": "npm scripts", "file": rel, "targets": list(obj["scripts"])[:40],
                                "subproject": sub_of(rel)})
        devcontainer = sorted(f for f in repo.files if f == ".devcontainer.json"
                              or re.match(r"^\.devcontainer/(.+/)?devcontainer\.json$", f))
        dockerfiles = sorted(f for f in repo.files if re.match(r"^(Dockerfile(\..+)?|.+\.Dockerfile)$", posixpath.basename(f)))
        compose = sorted(f for f in repo.files
                         if re.match(r"^(docker-compose.*|compose)\.ya?ml$", posixpath.basename(f)))
        lockfiles.sort(key=lambda r: r["file"])
        self.lockfile_age(lockfiles)
        return {"lockfiles": lockfiles,
                "requirements_files": requirements,
                "toolchain_pins": sorted(pins, key=lambda r: (r["file"], r["kind"])),
                "task_runners": sorted(runners, key=lambda r: r["file"]),
                "devcontainer": devcontainer, "dockerfiles": dockerfiles[:20], "compose": compose[:20]}

    # ---- strictness and coverage thresholds --------------------------------

    def section_lines(self, rel, headers):
        """(line number, text) of the lines under the section headers of a TOML or INI file."""
        current = None
        for number, raw in enumerate(self.repo.text(rel).splitlines(), 1):
            m = SECTION_RE.match(raw)
            if m:
                current = re.sub(r"\s+", "", m.group(1))
            elif current in headers:
                yield number, raw

    def line_of(self, rel, regex, flags=0):
        """(line, match) of the first match of regex in a file, or None."""
        text = self.repo.text(rel)
        m = re.search(regex, text, flags)
        return (text.count("\n", 0, m.start()) + 1, m) if m else None

    def detect_facts(self, subproject_dirs):
        """(strictness, coverage_thresholds) read from configuration files, CI and scripts."""
        repo = self.repo
        cache = {}
        strictness = []
        thresholds = []

        def add(target, kind, rel, line, **extra):
            item = {"kind": kind, "how": "config", "file": rel, "line": line,
                    "subproject": self.owner(dir_of(rel), subproject_dirs, cache)}
            item.update(extra)
            target.append(item)

        def on(value):
            return bool(re.match(r"^\s*(true|yes|on|1)\b", value, re.I))

        for name, headers in (("mypy.ini", {"mypy"}), (".mypy.ini", {"mypy"}), ("setup.cfg", {"mypy"}),
                              ("pyproject.toml", {"tool.mypy"})):
            for rel in repo.by_name.get(name, []):
                for number, raw in self.section_lines(rel, headers):
                    m = re.match(r"^\s*(strict|disallow_untyped_defs)\s*[=:]\s*(.*)$", raw)
                    if m and on(m.group(2)):
                        add(strictness, "mypy-" + m.group(1).replace("_", "-"), rel, number, value=True)
        for rel in repo.by_name.get("pyrightconfig.json", []):
            try:
                obj = json.loads(strip_jsonc(repo.text(rel)))
            except ValueError:
                obj = None
            if isinstance(obj, dict):
                if obj.get("typeCheckingMode") == "strict":
                    hit = self.line_of(rel, r'"typeCheckingMode"')
                    add(strictness, "pyright-strict", rel, hit[0] if hit else 1, value="strict")
                if isinstance(obj.get("strict"), list) and obj["strict"]:
                    hit = self.line_of(rel, r'"strict"\s*:')
                    add(strictness, "pyright-strict-paths", rel, hit[0] if hit else 1, value=obj["strict"])
        for rel in repo.by_name.get("pyproject.toml", []):
            for number, raw in self.section_lines(rel, {"tool.pyright"}):
                if re.match(r"^\s*typeCheckingMode\s*=\s*[\"']strict[\"']", raw):
                    add(strictness, "pyright-strict", rel, number, value="strict")
                elif re.match(r"^\s*strict\s*=\s*\[\s*[\"']", raw):
                    add(strictness, "pyright-strict-paths", rel, number)
        for rel in repo.files + repo.above:
            base = posixpath.basename(rel)
            if re.match(r"^tsconfig[\w.\-]*\.json$", base):
                info = tsconfig_info(repo, rel)
                if info["strict"] is not None:
                    hit = self.line_of(rel, r'"strict"\s*:')
                    add(strictness, "tsconfig-strict", rel, hit[0] if hit else 1, value=info["strict"])
        for rel in repo.by_name.get("Cargo.toml", []):
            for number, raw in self.section_lines(rel, {"lints.rust", "workspace.lints.rust"}):
                if re.match(r"^\s*warnings\s*=\s*[\"']deny[\"']", raw):
                    add(strictness, "cargo-lints-deny-warnings", rel, number, value="deny")
        for rel in repo.files:
            if posixpath.basename(rel) in ("pom.xml", "build.gradle", "build.gradle.kts"):
                hit = self.line_of(rel, r"-Werror\b|<failOnWarning>\s*true")
                if hit:
                    add(strictness, "javac-werror", rel, hit[0])
                hit = self.line_of(rel, r"allWarningsAsErrors\s*(=\s*true|\.set\(\s*true\s*\))")
                if hit:
                    add(strictness, "kotlin-all-warnings-as-errors", rel, hit[0])
        for fact in self.ci_facts + self.script_facts:
            strictness.append(dict(fact, subproject=self.owner(dir_of(fact["file"]), subproject_dirs, cache)))
        strictness = [f for f in strictness if f["kind"] not in COVERAGE_FACT_KINDS]

        for name in (".coveragerc", "setup.cfg", "tox.ini", "pyproject.toml"):
            for rel in repo.by_name.get(name, []):
                hit = self.line_of(rel, r"^\s*fail_under\s*[=:]\s*([\d.]+)", re.M)
                if hit:
                    add(thresholds, "fail_under", rel, hit[0], value=hit[1].group(1))
        for name in ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"):
            for rel in repo.by_name.get(name, []):
                hit = self.line_of(rel, r"--cov-fail-under[= ]\s*([\d.]+)")
                if hit:
                    add(thresholds, "cov-fail-under", rel, hit[0], value=hit[1].group(1))
        for rel in repo.files:
            base = posixpath.basename(rel)
            if base in ("pom.xml", "build.gradle", "build.gradle.kts"):
                text = repo.text(rel)
                if "jacoco" in text.lower():
                    hit = self.line_of(rel, r"<minimum>\s*([\d.]+)|violationRules")
                    if hit:
                        add(thresholds, "jacoco-violation-rules", rel, hit[0], value=hit[1].group(1))
                hit = self.line_of(rel, r"minBound\s*\(?\s*(\d+)?")
                if hit:
                    add(thresholds, "kover-min-bound", rel, hit[0], value=hit[1].group(1))
            elif re.match(r"^(vitest|vite)\.config\.[mc]?[jt]s$", base):
                hit = self.line_of(rel, r"\bthresholds\b")
                if hit:
                    add(thresholds, "vitest-thresholds", rel, hit[0])
            elif re.match(r"^jest\.config\.(json|[mc]?[jt]s)$", base) or base == "package.json":
                hit = self.line_of(rel, r"\bcoverageThreshold\b")
                if hit:
                    add(thresholds, "jest-coverage-threshold", rel, hit[0])
            elif base in ("codecov.yml", ".codecov.yml", "codecov.yaml", ".codecov.yaml"):
                tree = parse_yaml(repo.text(rel))
                for key, value in walk_yaml(tree):
                    if key == "patch":
                        for inner_key, inner in walk_yaml(value):
                            if inner_key == "target":
                                add(thresholds, "codecov-patch-target", rel, getattr(inner, "line", 1),
                                    value=str(inner))
                                break
        for fact in self.ci_facts + self.script_facts:
            if fact["kind"] in COVERAGE_FACT_KINDS:
                thresholds.append(dict(fact, subproject=self.owner(dir_of(fact["file"]), subproject_dirs, cache)))
        key = lambda r: (r["file"], r["line"], r["kind"])
        return sorted(strictness, key=key), sorted(thresholds, key=key)

    # ---- docs -----------------------------------------------------------

    INSTALL_HEAD = re.compile(r"\b(install(ation)?|set ?up|getting started|quick ?start)\b", re.I)
    RUN_HEAD = re.compile(r"\b(usage|run(ning)?|start(ing)?|quick ?start|getting started)\b", re.I)
    TEST_HEAD = re.compile(r"\b(tests?|testing)\b", re.I)
    INSTALL_CMD = re.compile(
        r"\b(pip3? install|uv (sync|pip install|add)|poetry install|(npm|pnpm|yarn|bun) (install|ci)|"
        r"cargo (build|install)|go (install|get|mod download)|mvn (install|package|compile)|"
        r"\./?gradlew? (build|assemble)|gradle build|brew install|conda install|bundle install)\b")
    RUN_CMD = re.compile(
        r"\b(python3? (-m )?\S+|node \S+|(npm|pnpm|yarn|bun) (start|dev|run)|cargo run|go run|"
        r"\./?gradlew? run|mvn exec|java -jar|uv run|docker (compose )?up|make run)\b")
    TEST_CMD = re.compile(
        r"\b(pytest|python3? -m (unittest|pytest)|unittest|tox|nox|(npm|pnpm|yarn|bun) (run )?test|"
        r"jest|vitest|cargo (test|nextest)|go test|mvn (test|verify)|\./?gradlew? (test|check)|"
        r"gradle (test|check)|make test|just test)\b")

    def detect_docs(self):
        repo = self.repo
        readme = None
        for rel in sorted(repo.by_dir.get(".", [])):
            if re.match(r"^readme(\.[a-z]+)?$", rel, re.I):
                readme = rel
                break
        docs = {"readme": readme, "headings": [], "commands": [], "install": None, "run": None, "test": None,
                "contributing": None, "adr_dirs": [], "architecture_docs": [], "docs_dir": None}
        if readme:
            text = repo.text(readme)
            headings = self.headings(text, readme)
            docs["headings"] = headings[:80]
            docs["commands"] = self.readme_commands(text, readme)
            lines = text.splitlines()
            for key, head_re, cmd_re in (("install", self.INSTALL_HEAD, self.INSTALL_CMD),
                                         ("run", self.RUN_HEAD, self.RUN_CMD),
                                         ("test", self.TEST_HEAD, self.TEST_CMD)):
                docs[key] = self.find_section(headings, lines, head_re, cmd_re)
        for rel in repo.files:
            low = rel.lower()
            if docs["contributing"] is None and re.match(r"^((\.github|docs?)/)?contributing(\.[a-z]+)?$", low):
                docs["contributing"] = rel
            base = posixpath.basename(low)
            if re.match(r"^(architecture|design)(\.[a-z]+)?$", base) and len(docs["architecture_docs"]) < 10:
                docs["architecture_docs"].append(rel)
        for d in sorted(repo.dirs):
            low = d.lower()
            if posixpath.basename(low) in ("adr", "adrs", "decisions", "architecture-decisions") \
                    and len(docs["adr_dirs"]) < 10:
                docs["adr_dirs"].append(d)
            if posixpath.basename(low) in ("architecture",) and len(docs["architecture_docs"]) < 10:
                docs["architecture_docs"].append(d + "/")
        for name in ("docs", "doc"):
            if name in repo.dirs:
                docs["docs_dir"] = name
                break
        return docs

    @staticmethod
    def headings(text, rel):
        out = []
        lines = text.splitlines()
        in_fence = False
        for number, line in enumerate(lines, 1):
            if line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
            if m:
                out.append({"level": len(m.group(1)), "text": m.group(2), "line": number})
            elif rel.lower().endswith(".rst") and number < len(lines) and line.strip() \
                    and re.match(r"^([=\-~^])\1{2,}\s*$", lines[number]):
                out.append({"level": 1, "text": line.strip(), "line": number})
        return out

    @staticmethod
    def find_section(headings, lines, head_re, cmd_re):
        for h in headings:
            if head_re.search(h["text"]):
                return {"found": True, "via": "heading", "line": h["line"]}
        for number, line in enumerate(lines, 1):
            if cmd_re.search(line):
                return {"found": True, "via": "command", "line": number}
        return {"found": False, "via": None, "line": None}

    # ---- README commands --------------------------------------------------

    README_SHELL = {"sh", "bash", "shell", "zsh", "console", "shell-session", "terminal", "shellsession"}

    @staticmethod
    def readme_blocks(text):
        """([(language, [(line, text)])] fenced blocks, [(line, text)] inline code spans)."""
        blocks = []
        inline = []
        fence = None
        for number, raw in enumerate(text.splitlines(), 1):
            m = re.match(r"^\s{0,3}(`{3,}|~{3,})\s*([\w+\-.]*)", raw)
            if fence is None:
                if m:
                    fence = (m.group(1), m.group(2).lower(), [])
                    blocks.append(fence)
                    continue
                for span in re.finditer(r"(`+)([^`\n]+?)\1", raw):
                    inline.append((number, span.group(2).strip()))
            elif m and m.group(1)[0] == fence[0][0] and len(m.group(1)) >= len(fence[0]) and not m.group(2):
                fence = None
            else:
                fence[2].append((number, raw))
        return [(b[1], b[2]) for b in blocks], inline

    def readme_commands(self, text, readme):
        """Shell commands of the README with what can be checked without running them."""
        base = dir_of(readme)
        blocks, inline = self.readme_blocks(text)
        found = []
        seen = set()

        def add(number, argv, cwd):
            record = self.check_command(argv, cwd)
            key = (number, record["command"])
            if key not in seen and len(found) < 200:
                seen.add(key)
                record["line"] = number
                found.append(record)

        for language, lines in blocks:
            cwd = [base]
            if language in self.README_SHELL and language not in ("console", "shell-session", "shellsession"):
                body = "\n".join("" if README_PLACEHOLDER.search(text_) else re.sub(r"^(\s*)[$>] ", r"\1", text_)
                                 for _n, text_ in lines)
                self.readme_units(body, lines[0][0] if lines else 1, cwd, add)
            elif language in self.README_SHELL or language == "":
                for number, raw in lines:
                    stripped = raw.strip()
                    if README_PLACEHOLDER.search(stripped):
                        continue
                    if stripped.startswith("$ "):
                        self.readme_units(stripped[2:], number, cwd, add)
                    elif language == "" and posixpath.basename(stripped.split(" ")[0]) in README_KNOWN_PROGRAMS:
                        self.readme_units(stripped, number, cwd, add)
        for number, span in inline:
            words = span.split()
            if README_PLACEHOLDER.search(span) or not words or posixpath.basename(words[0]) not in README_KNOWN_PROGRAMS:
                continue
            if len(words) == 1 and words[0] not in README_STANDALONE:
                continue
            self.readme_units(span, number, [base], add)
        found.sort(key=lambda r: r["line"])
        return found

    def readme_units(self, body, first_line, cwd, add):
        for unit in split_commands(body):
            argv = unit.argv
            if not argv or argv[0].startswith(("<", "{", "[")) or posixpath.basename(argv[0]) in README_IGNORED:
                continue
            if argv[0] in ("sh", "bash", "zsh") and len(argv) == 1:
                continue
            if argv[0] == "cd":
                target = argv[1] if len(argv) > 1 else "."
                joined = posixpath.normpath(posixpath.join(cwd[0], target)) if cwd[0] is not None and \
                    not target.startswith(("/", "~", "$")) else None
                cwd[0] = joined if joined is not None and not joined.startswith("..") else None
                continue
            add(first_line + unit.line, argv, cwd[0])

    def check_command(self, argv, cwd):
        """{"command", "kind", "check", "why"} of one README command."""
        probe = []
        out = Outcome()
        self.reader.command(out, argv, 0, Ctx(follow=False, probe=probe))
        env = {}
        stripped = self.reader.strip_wrappers(argv, env)
        command = " ".join(argv)[:200]
        if not stripped:
            return {"command": command, "kind": "other", "check": "unknown", "why": "nothing to check"}
        prog = re.sub(r"@[^@/]*$", "", posixpath.basename(stripped[0]))
        args = stripped[1:]
        results = []
        if cwd is None:
            results.append(("unknown", "the directory is not known after `cd`"))
        else:
            for kind, name, scope, explicit in probe:
                results.append(self.check_script(kind, name, scope, explicit, cwd))
            if prog in ("make", "gmake", "just") and not probe:
                results.append(self.check_bare_runner(prog, args, cwd))
            results.extend(self.check_paths(stripped, prog, args, cwd))
            results.extend(self.check_tool_command(prog, args, cwd))
        missing = [r for r in results if r[0] == "missing"]
        ok = [r for r in results if r[0] == "ok"]
        unknown = [r for r in results if r[0] == "unknown"]
        if missing:
            check, why = missing[0]
        elif unknown:
            check, why = unknown[0]
        elif ok:
            check, why = ok[0]
        else:
            check, why = "unknown", "not checkable without running it"
        return {"command": command, "kind": self.readme_kind(prog, args, out, probe), "check": check, "why": why}

    def find_up(self, cwd, names):
        """First existing file of names in cwd or a folder above it (inside the scanned folder)."""
        for d in ancestors(cwd):
            for name in names:
                if join(d, name) in self.repo.file_set:
                    return join(d, name)
        return None

    def check_script(self, kind, name, scope, explicit, cwd):
        if kind == "npm":
            if scope.get("workspace"):
                dirs = self.workspace_dirs_for(scope.get("filters") or [])
                if dirs is None:
                    return "unknown", "no workspace found"
                dirs = set(dirs)
            else:
                package = self.find_up(cwd, ["package.json"])
                if package is None:
                    return "missing", "no package.json in %s or above" % cwd
                dirs = {dir_of(package)}
            if any(e["dir"] in dirs for e in self.scripts["npm"].get(name, [])):
                return "ok", "script `%s` exists in package.json" % name
            if name == "start" and join(cwd, "server.js") in self.repo.file_set:
                return "ok", "`npm start` runs server.js"
            if not explicit:
                return "unknown", "`%s` is not a script; it may be a binary or a built-in command" % name
            return "missing", "package.json has no script `%s`" % name
        label = "Makefile" if kind == "make" else "justfile"
        directory = posixpath.normpath(posixpath.join(cwd, scope["directory"])) if scope.get("directory") else cwd
        files = [f for f in (self.repo.by_dir.get(directory) or []) if f in
                 (("Makefile", "GNUmakefile", "makefile") if kind == "make" else ("justfile", "Justfile", ".justfile"))]
        if not files:
            return "missing", "no %s in %s" % (label, directory)
        if any(e["dir"] == directory for e in self.scripts[kind].get(name, [])):
            return "ok", "%s has the %s `%s`" % (label, "target" if kind == "make" else "recipe", name)
        if kind == "make" and re.search(r"^-?include\b", self.repo.text(join(directory, files[0])), re.M):
            return "unknown", "target `%s` may come from an included makefile" % name
        return "missing", "%s has no %s `%s`" % (label, "target" if kind == "make" else "recipe", name)

    def check_bare_runner(self, prog, args, cwd):
        kind = "just" if prog == "just" else "make"
        names = ("justfile", "Justfile", ".justfile") if kind == "just" else ("Makefile", "GNUmakefile", "makefile")
        if any(join(cwd, n) in self.repo.file_set for n in names):
            return "ok", "%s exists" % (names[0])
        return "missing", "no %s in %s" % (names[0], cwd)

    PATH_FLAGS = {"-f": {"make", "gmake", "docker", "docker-compose", "mvn", "mvnw"}, "--file": {"make", "docker",
                  "docker-compose", "mvn", "mvnw"}, "-r": {"pip", "pip3", "uv"}, "--requirement": {"pip", "pip3", "uv"},
                  "-c": {"pip", "pip3"}, "--constraint": {"pip", "pip3"}, "--manifest-path": {"cargo"},
                  "-b": {"gradle", "gradlew"}}
    INTERPRETERS = {"bash", "sh", "zsh", "python", "python3", "node", "deno", "ruby", "perl", "ts-node", "tsx"}

    def check_paths(self, argv, prog, args, cwd):
        """Existence of the repository paths a command names."""
        results = []

        def look(path):
            if (not path or path.startswith(("-", "/", "~", "http")) or re.search(r"[*?\[\]{}<>$|;=]|\.\.\.|://", path)
                    or path in (".", "..")):
                return
            rel = posixpath.normpath(posixpath.join(cwd, path))
            if rel.startswith(".."):
                return
            if rel in self.repo.file_set or rel in self.repo.dirs:
                results.append(("ok", "%s exists" % path))
            else:
                results.append(("missing", "%s does not exist" % path))

        if "/" in argv[0]:
            look(argv[0])
        base = re.sub(r"[0-9.]+$", "", prog) if prog.startswith("python") else prog
        if base in self.INTERPRETERS or prog in self.INTERPRETERS:
            i = 0
            while i < len(args):
                a = args[i]
                if a == "-m" or a == "-c" or a == "-e":
                    break
                if not a.startswith("-"):
                    if "/" in a or re.search(r"\.(sh|py|js|mjs|cjs|ts|rb|pl)$", a):
                        look(a)
                    break
                i += 1
        previous_flag = False
        for index, a in enumerate(args):
            if a == "--":
                break
            if a.startswith("-"):
                flag, eq, value = a.partition("=")
                if prog in self.PATH_FLAGS.get(flag, ()):
                    target = value if eq else (args[index + 1] if index + 1 < len(args) else "")
                    look(target)
                previous_flag = not eq
                continue
            if previous_flag:
                previous_flag = False
                continue
            if "/" in a and re.search(r"\.[A-Za-z0-9]{1,5}$", a) and prog in README_KNOWN_PROGRAMS \
                    and prog not in self.INTERPRETERS:
                look(a)
        return results

    def check_tool_command(self, prog, args, cwd):
        results = []
        sub = first_positional(args)
        if prog.startswith("python") and "-m" in args and args.index("-m") + 1 < len(args):
            results.append(self.check_python_module(args[args.index("-m") + 1], cwd))
        elif prog == "cargo":
            sub = next((a for a in args if not a.startswith(("+", "-"))), None)
            if sub:
                if sub in CARGO_BUILTIN:
                    results.append(("ok", "`cargo %s` is a cargo command" % sub))
                elif sub in CARGO_PLUGINS:
                    results.append(("ok", "`cargo %s` is a common cargo plugin" % sub))
                else:
                    close = difflib.get_close_matches(sub, sorted(CARGO_BUILTIN), 1, 0.75)
                    results.append(("missing", "`cargo %s` is not a cargo command (did you mean `%s`?)" % (sub, close[0]))
                                   if close else ("unknown", "`cargo %s` is not built in; it may be a plugin" % sub))
        elif prog == "go":
            if sub:
                if sub in GO_SUBCOMMANDS:
                    results.append(("ok", "`go %s` is a go command" % sub))
                else:
                    results.append(("missing", "`go %s` is not a go command" % sub))
        elif prog in ("mvn", "mvnw", "mvnd"):
            goals = [a for a in args if not a.startswith("-")]
            for goal in goals:
                if ":" in goal:
                    results.append(("unknown", "`%s` is a plugin goal" % goal))
                elif goal in MVN_PHASES:
                    results.append(("ok", "`%s` is a Maven phase" % goal))
                else:
                    results.append(("missing", "`%s` is not a Maven phase" % goal))
        elif prog in ("gradle", "gradlew"):
            for task in [a for a in args if not a.startswith("-")]:
                name = task.split(":")[-1]
                if name in GRADLE_STANDARD_TASKS:
                    results.append(("ok", "`%s` is a standard Gradle task" % name))
                elif any(re.search(r"\b" + re.escape(name) + r"\b", self.repo.text(f)) for f in self.repo.files
                         if f.endswith((".gradle", ".gradle.kts"))):
                    results.append(("ok", "`%s` appears in the build files" % name))
                else:
                    results.append(("unknown", "`%s` is not a standard task and is not in the build files" % name))
        return results

    def check_python_module(self, module, cwd):
        module = module.split(" ")[0]
        path = module.replace(".", "/")
        roots = [cwd, posixpath.join(cwd, "src")] if cwd != "." else [".", "src"]
        for root in roots:
            for candidate in (join(root, path + ".py"), join(root, path + "/__init__.py"),
                              join(root, path + "/__main__.py")):
                if candidate in self.repo.file_set:
                    return "ok", "module `%s` is in the repository" % module
        top = module.split(".")[0]
        if top in PYTHON_STDLIB_MODULES:
            return "ok", "`%s` is in the standard library" % module
        for rel in self.repo.by_name.get("pyproject.toml", []):
            m = re.search(r"^name\s*=\s*[\"']([^\"']+)", "\n".join(t for _n, t in self.section_lines(rel, {"project"})), re.M)
            if m and m.group(1).replace("-", "_").lower() == top.lower():
                return "missing", "the project `%s` has no module `%s` in the repository" % (m.group(1), module)
        return "unknown", "`%s` is not in the repository; it may be an installed package" % module

    @staticmethod
    def kind_from_name(name):
        low = name.lower()
        if re.search(r"(^|[:\-_])(test|tests|spec|e2e|unit|integration|coverage|cov)($|[:\-_])", low):
            return "test"
        if re.search(r"lint|format|fmt|typecheck|type-check|check|style|prettier|eslint|mypy|types", low):
            return "lint"
        if re.search(r"build|compile|dist|bundle|package|release", low):
            return "build"
        if re.search(r"^(dev|start|serve|watch|run|preview|up|storybook)($|[:\-_])", low):
            return "run"
        if re.search(r"install|^ci$|setup|bootstrap|sync|^deps", low):
            return "install"
        return "other"

    def readme_kind(self, prog, args, out, probe):
        if out.installs:
            return "install"
        if probe:
            return self.kind_from_name(probe[0][1])
        kind = self.build_tool_kind(prog, args)
        if kind:
            return kind
        categories = {hit.tool.category for hit in out.hits}
        if categories & {"tests", "coverage"}:
            return "test"
        if categories & {"lint", "format", "types", "static", "deps_audit", "secrets", "hooks"}:
            return "lint"
        if prog in ("make", "gmake", "just"):
            return "run" if not args else "other"
        if prog == "docker" or prog == "docker-compose":
            return "run" if "up" in args or "run" in args else "build" if "build" in args else "other"
        if prog.startswith("python") or prog in ("node", "deno", "uvicorn", "gunicorn", "flask", "ruby"):
            return "run"
        return "other"

    @staticmethod
    def build_tool_kind(prog, args):
        """The kind of a cargo, go, Maven or Gradle command, or None for another program."""
        sub = first_positional(args)
        if prog == "cargo":
            sub = next((a for a in args if not a.startswith(("+", "-"))), None)
            return {"test": "test", "t": "test", "nextest": "test", "build": "build", "b": "build", "run": "run",
                    "r": "run", "clippy": "lint", "fmt": "lint", "check": "lint", "fetch": "install",
                    "install": "install"}.get(sub or "")
        if prog == "go":
            return {"test": "test", "build": "build", "run": "run", "vet": "lint", "fmt": "lint", "get": "install",
                    "install": "install"}.get(sub or "")
        goals = [a for a in args if not a.startswith("-")]
        if prog in ("mvn", "mvnw", "mvnd"):
            if any(g in ("test", "verify") for g in goals):
                return "test"
            if any(g in ("package", "compile", "install", "clean", "deploy") for g in goals):
                return "build"
            return "run" if any(g.startswith(("exec:", "spring-boot:run")) for g in goals) else None
        if prog in ("gradle", "gradlew"):
            if any(g in ("build", "assemble", "clean", "jar") for g in goals):
                return "build"
            if any(g in ("test", "check") for g in goals):
                return "test"
            return "run" if any(g in ("run", "bootRun") for g in goals) else None
        return None

    # ---- assembly -------------------------------------------------------

    def run(self):
        repo = self.repo
        subs, workspaces = find_subprojects(repo)
        member_dirs = {m for w in workspaces.values() for m in w["members"]}
        for rel in repo.files:
            if posixpath.basename(rel) in ("pyproject.toml", "Cargo.toml"):
                repo.check_toml(rel)
        # Source files outside every manifest directory belong to an implicit root project.
        cache = {}
        orphans = any(language_of(rel) and self.owner(dir_of(rel), set(subs) | member_dirs, cache) is None
                      for rel in repo.files)
        if "." not in subs and (orphans or not subs):
            subs["."] = {"manifests": [], "languages": set()}
        subproject_dirs = set(subs) | member_dirs
        languages, other, suppressions, per_sub, excluded = self.scan_sources(subproject_dirs)
        self.collect_scripts()
        self.npm_workspaces = npm_workspaces(repo)
        owner_cache = {}
        self.script_hits = []
        self.script_facts = []
        for rel, line, command in self.script_commands:
            outcome = self.reader.read(command, follow=False)
            self.script_hits.append((rel, line, self.owner(dir_of(rel), subproject_dirs, owner_cache),
                                     {hit.tool.name for hit in outcome.hits}))
            self.script_facts.extend(dict(fact, how="script", file=rel, line=line) for fact in outcome.facts
                                     if not fact["kind"].startswith("poetry-"))
        precommit = self.detect_precommit()
        ci = self.detect_ci()

        # shared tools, relative to the repo root
        shared = []
        for tool in ALL_TOOLS:
            if tool.language != "shared":
                continue
            found = None
            for spec in tool.specs:
                for candidate in repo.ancestor_dirs("."):
                    hit = repo.match_spec(spec, candidate)
                    if hit:
                        extra = {"inherited_from": candidate} if candidate != "." else {}
                        found = self.row(tool, hit, "config", **extra)
                        break
                if found:
                    break
            if found:
                shared.append(found)

        records = []
        for d, entry in subs.items():
            stats = per_sub.get(d, {lang: new_stats() for lang in LANGUAGES})
            members = workspaces.get(d, {}).get("members", [])
            if members:
                stats = {lang: dict(stat) for lang, stat in stats.items()}
                for member in members:
                    for lang, stat in per_sub.get(member, {}).items():
                        for key, value in stat.items():
                            stats[lang][key] += value
            langs = set(entry["languages"])
            for member in members:
                langs |= workspaces[d]["entries"][member]["languages"]
            for lang, s in stats.items():
                if s["files"] or s["test_files"]:
                    langs.add(lang)
            ordered = [lang for lang in LANGUAGES if lang in langs]
            loc = sum(s["loc"] for s in stats.values())
            records.append((d, entry, ordered, stats, loc))
        records.sort(key=lambda r: (-r[4], r[0]))
        kept, more = records[:self.max_subprojects], records[self.max_subprojects:]
        kept.sort(key=lambda r: r[0])

        subprojects = []
        for d, entry, langs, stats, loc in kept:
            subprojects.append(self.subproject_record(d, entry, langs, stats, shared,
                                                      self.member_records(workspaces.get(d), per_sub),
                                                      workspaces.get(d)))
        more_subprojects = [{"path": d, "manifest": (entry["manifests"] or [None])[0],
                             "languages": langs, "loc": loc} for d, entry, langs, stats, loc in more]

        has_git = repo.is_git
        commit = None
        branch = None
        if has_git:
            out = run_git(repo.git_root, ["rev-parse", "HEAD"])
            commit = out.decode().strip() if out else None
            out = run_git(repo.root, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
            if out:
                branch = out.decode().strip().split("/", 1)[-1]
            else:
                for name in ("main", "master"):
                    if run_git(repo.root, ["rev-parse", "--verify", "--quiet", "refs/heads/" + name]):
                        branch = name
                        break
        strictness, thresholds = self.detect_facts(subproject_dirs)
        return {
            "repo": repo.root,
            "git": has_git,
            "git_root": repo.git_root,
            "subpath": repo.subpath if has_git else None,
            "commit": commit,
            "default_branch": branch,
            "languages": languages,
            "other_languages": other,
            "subprojects": subprojects,
            "more_subprojects": more_subprojects,
            "shared": shared,
            "ci": ci,
            "precommit": precommit,
            "setup": self.detect_setup(subproject_dirs),
            "docs": self.detect_docs(),
            "suppressions": suppressions,
            "strictness": strictness,
            "coverage_thresholds": thresholds,
            "excluded": self.excluded_summary(excluded),
            "parse_errors": [{"file": f, "parse_error": e} for f, e in sorted(repo.parse_errors.items())],
        }

    def excluded_summary(self, excluded):
        repo = self.repo
        skipped = sorted(({"path": path, "files": files} for path, files in repo.skipped.items()),
                         key=lambda r: (-r["files"], r["path"]))[:30]
        summary = {"skipped_dirs": skipped}
        for kind in ("generated", "vendored", "migrations"):
            files = sorted(excluded.get(kind, []))
            summary[kind] = {"count": len(files), "examples": files[:5]}
        summary["symlinks_outside"] = sorted(repo.symlinks_outside)
        return summary

    @staticmethod
    def row(tool, hit, how, **extra):
        row = {"tool": tool.name, "category": tool.category, "file": hit[0], "line": hit[1], "how": how}
        row.update(extra)
        return row

    def member_records(self, workspace, per_sub):
        """Records of the members of a workspace: their own languages, tool rows and dependencies."""
        if not workspace:
            return []
        records = []
        for member in workspace["members"]:
            entry = workspace["entries"][member]
            stats = per_sub.get(member, {lang: new_stats() for lang in LANGUAGES})
            langs = set(entry["languages"])
            for lang, stat in stats.items():
                if stat["files"] or stat["test_files"]:
                    langs.add(lang)
            ordered = [lang for lang in LANGUAGES if lang in langs]
            records.append(self.subproject_record(member, entry, ordered, stats, []))
        return records

    def subproject_record(self, d, entry, langs, stats, shared, members=(), workspace=None):
        repo = self.repo
        categories = {c: [] for c in CATEGORIES if c != "hooks"}
        tool_rows = []
        seen = set()
        for lang in langs:
            for tool in tools_for_language(lang):
                if tool.name in seen:
                    continue
                seen.add(tool.name)
                tool_rows.append(tool)
        for tool in tool_rows:
            found = None
            for spec in tool.specs:
                for candidate in repo.ancestor_dirs(d):
                    hit = repo.match_spec(spec, candidate)
                    if hit:
                        extra = {}
                        if candidate != d:
                            extra["inherited_from"] = candidate
                        if tool.name == "tsc" and hit[0].endswith("tsconfig.json"):
                            extra.update(tsconfig_info(repo, hit[0]))
                        found = self.row(tool, hit, "config", **extra)
                        break
                if found:
                    break
            if found:
                categories[tool.category].append(found)
        # package.json scripts and Makefile or justfile recipes that belong to this subproject
        owned = {}
        for rel, line, owner, names in self.script_hits:
            if owner != d:
                continue
            for tool in tool_rows:
                if tool.name in names and (tool.name, rel) not in owned:
                    owned[(tool.name, rel)] = self.row(tool, (rel, line), "script")
        for row in owned.values():
            categories[row["category"]].append(row)
        for row in shared:
            if row["category"] in categories:
                categories[row["category"]].append(row)
        dependencies = count_dependencies(repo, d, entry["manifests"])
        for member in members:
            for category, rows in member["categories"].items():
                have = {(r["tool"], r["file"], r["line"], r["how"]) for r in categories[category]}
                for row in rows:
                    if (row["tool"], row["file"], row["line"], row["how"]) not in have:
                        categories[category].append(dict(row, member=member["path"]))
            for key in ("direct", "dev"):
                dependencies[key] += member["dependencies"][key]
            dependencies["files"].extend(member["dependencies"]["files"])
        record = {
            "path": d,
            "manifest": (entry["manifests"] or [None])[0],
            "manifests": [{"file": m, "parse_error": repo.parse_errors.get(m)} for m in entry["manifests"]],
            "languages": langs,
            "stats": {lang: stats[lang] for lang in langs},
            "categories": categories,
            "dependencies": dependencies,
            "workspace": {"kind": workspace["kind"], "manifest": workspace["manifest"]} if workspace else None,
            "members": list(members),
        }
        return record


def main(argv=None):
    parser = argparse.ArgumentParser(description="Detect languages, tools, CI and setup of a repository.")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--max-subprojects", type=int, default=DEFAULT_MAX_SUBPROJECTS)
    parser.add_argument("--pretty", action="store_true", help="indent the JSON")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.repo):
        sys.stderr.write("detect.py: not a directory: %s\n" % args.repo)
        return 2
    result = Detector(args.repo, args.max_subprojects).run()
    if args.pretty:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
