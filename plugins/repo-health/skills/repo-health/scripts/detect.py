#!/usr/bin/env python3
"""Tier 0 detection for the repo-health skill.

    detect.py [REPO] [--max-subprojects 10] [--pretty]

Prints one JSON document on stdout: languages and LOC, subprojects with the
lint/format/type/static/test/coverage configuration found, CI files and the
tools they run, pre-commit hooks, setup files, docs and suppression markers.
It reads manifests, configs, CI files and the first 200 KB of each source file.
It never writes, never runs project code, and never needs the network.
Standard library only; runs on Python 3.9 and newer.

The TOOLS table below is the single list of tools. The reference files of the
skill name the same tools; tests/test_consistency.py keeps the two in step.

Evidence matches have the shape
    {"tool", "category", "file", "line", "how"}   how = config|ci|precommit|script
with extra keys where useful ("language", "inherited_from", "via", "strict").
TOML section headers are found with a line scanner on every Python version, so
that matches carry line numbers. tomllib (Python 3.11+) only decides whether a
manifest is well formed ("parse_errors").
"""

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
from collections import defaultdict

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - depends on the interpreter
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
# CI words are matched, case-insensitively, in CI run and uses lines, pre-commit
# hook ids, package.json scripts and Makefile or justfile recipes. Words in
# WHOLE_WORD match as whole words only, so "toxic" is not "tox".

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

SKIP_DIRS = {
    "node_modules", "vendor", "target", "build", "dist", ".venv", "venv", ".git",
    "third_party", "__pycache__", ".tox", ".nox", ".eggs", ".mypy_cache",
    ".ruff_cache", ".pytest_cache", ".gradle", ".idea", "site-packages",
    "generated", "__generated__", ".next", ".nuxt", ".repo-health",
}

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
    "build.gradle.kts": "java", "go.mod": "go",
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

def run_git(root, args):
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        proc = subprocess.run(["git"] + args, cwd=root, env=env, timeout=120,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def is_git_root(root):
    out = run_git(root, ["rev-parse", "--show-toplevel"])
    if not out:
        return False
    top = out.decode("utf-8", "replace").strip()
    return os.path.realpath(top) == os.path.realpath(root)


def skipped(rel):
    for part in rel.split("/")[:-1]:
        if part in SKIP_DIRS or part.endswith(".egg-info"):
            return True
    return False


def list_files(root, use_git):
    """Relative posix paths of the files to look at, skip list applied."""
    names = None
    if use_git:
        out = run_git(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
        if out is not None:
            names = [n for n in out.decode("utf-8", "replace").split("\0") if n]
    if names is None:
        names = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")]
            rel_dir = os.path.relpath(dirpath, root)
            for name in filenames:
                names.append(name if rel_dir == "." else posixpath.join(rel_dir.replace(os.sep, "/"), name))
    seen = set()
    files = []
    for rel in names:
        if rel in seen or skipped(rel):
            continue
        seen.add(rel)
        if os.path.isfile(os.path.join(root, rel)):
            files.append(rel)
    return files


def dir_of(rel):
    return posixpath.dirname(rel) or "."


def join(d, name):
    return name if d == "." else d + "/" + name


def ancestors(d):
    """['a/b', 'a', '.'] for 'a/b'."""
    chain = [d]
    while d != ".":
        d = dir_of(d)
        chain.append(d)
    return chain


class Repo(object):
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.is_git = is_git_root(self.root)
        self.files = list_files(self.root, self.is_git)
        self.file_set = set(self.files)
        self.by_dir = defaultdict(set)
        self.by_name = defaultdict(list)
        self.dirs = set()
        for rel in self.files:
            d = dir_of(rel)
            self.by_dir[d].add(posixpath.basename(rel))
            self.by_name[posixpath.basename(rel)].append(rel)
            while d not in self.dirs:
                self.dirs.add(d)
                if d == ".":
                    break
                d = dir_of(d)
        self.parse_errors = {}
        self._text = {}
        self._json = {}
        self._sections = {}

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


def find_subprojects(repo):
    """{dir: {"manifests": [rel...], "languages": set}} from the manifest files."""
    found = {}
    for name, language in MANIFESTS.items():
        for rel in repo.by_name.get(name, []):
            d = dir_of(rel)
            entry = found.setdefault(d, {"manifests": [], "languages": set()})
            entry["manifests"].append(rel)
            entry["languages"].add(language)
            if name in ("build.gradle", "build.gradle.kts", "pom.xml"):
                entry["languages"].discard("java")
                text = repo.text(rel)
                entry["languages"].add("kotlin" if re.search(r"kotlin", text, re.I) else "java")
    # package.json projects that a parent workspace lists are members, not subprojects
    members = set()
    for d in found:
        for glob in workspace_globs(repo, d):
            regex = workspace_glob_regex(glob)
            for other, other_entry in found.items():
                if other == d or (d != "." and not other.startswith(d + "/")):
                    continue
                relative = other if d == "." else other[len(d) + 1:]
                if other_entry["manifests"] == [join(other, "package.json")] and regex.match(relative):
                    members.add(other)
    for d in members:
        del found[d]
    return found


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
        self.script_index = defaultdict(list)   # script or target name -> [text]
        self.script_commands = []                # (file, line, text)

    # ---- languages, suppressions, per-subproject stats ----------------

    def scan_sources(self, subproject_dirs):
        repo = self.repo
        languages = {lang: new_stats() for lang in LANGUAGES}
        for lang in languages:
            if lang == "rust":
                languages[lang]["inline_test_files"] = 0
        other = defaultdict(int)
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
        return languages, dict(other), suppressions, per_sub

    @staticmethod
    def owner(d, subproject_dirs, cache):
        if d in cache:
            return cache[d]
        result = None
        for candidate in ancestors(d):
            if candidate in subproject_dirs:
                result = candidate
                break
        cache[d] = result
        return result

    # ---- tool matching -------------------------------------------------

    def collect_scripts(self):
        """Command lines of package.json scripts, Makefiles, justfiles, Taskfiles."""
        repo = self.repo
        for rel in repo.by_name.get("package.json", []):
            obj, error = repo.json_file(rel)
            if error is not None or not isinstance(obj, dict) or not isinstance(obj.get("scripts"), dict):
                continue
            text = repo.text(rel)
            start = text.find('"scripts"')
            for name, command in obj["scripts"].items():
                if not isinstance(command, str):
                    continue
                m = re.compile(r'^\s*"' + re.escape(name) + r'"\s*:', re.M).search(text, max(start, 0))
                line = text.count("\n", 0, m.start()) + 1 if m else 1
                self.script_index[name].append(command)
                self.script_commands.append((rel, line, command))
        for name in ("Makefile", "GNUmakefile", "makefile", "justfile", "Justfile"):
            for rel in repo.by_name.get(name, []):
                recipes = make_recipes(repo.text(rel))
                for target, (line, commands, deps) in recipes.items():
                    text = "\n".join(commands + ["make " + dep for dep in deps])
                    self.script_index[target].append(text)
                    for offset, command in enumerate(commands):
                        self.script_commands.append((rel, line + offset + 1, command))
        for name in ("Taskfile.yml", "Taskfile.yaml"):
            for rel in repo.by_name.get(name, []):
                for line, command in yaml_commands(repo.text(rel)):
                    self.script_commands.append((rel, line, command))

    INVOKE_RE = re.compile(r"\b(?:npm|pnpm|yarn|bun)\s+(?:run(?:-script)?\s+)?([A-Za-z0-9:_\-]+)"
                           r"|\b(?:make|gmake|just|task)\b([^&;|]*)")

    def invocations(self, command):
        names = []
        for m in self.INVOKE_RE.finditer(command):
            if m.group(1):
                names.append(m.group(1))
            else:
                names.extend(t for t in m.group(2).split()
                             if not t.startswith("-") and "=" not in t)
        return names

    def match_tools(self, text, tools):
        low = text.lower()
        return [t for t in tools if t.ci_match(low)]

    def resolve(self, command, tools, depth=3, seen=None):
        """Tools run through npm scripts or make targets that a command calls."""
        seen = seen if seen is not None else set()
        found = []
        if depth <= 0:
            return found
        for name in self.invocations(command):
            if name in seen:
                continue
            seen.add(name)
            for body in self.script_index.get(name, []):
                for tool in self.match_tools(body, tools):
                    found.append((tool, "%s" % name))
                for line in body.splitlines():
                    found.extend(self.resolve(line, tools, depth - 1, seen))
        return found

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

    def detect_ci(self):
        repo = self.repo
        files = []
        by_tool = defaultdict(list)
        for rel in repo.files:
            provider = None
            for name, regex in self.CI_FILE_RES:
                if regex.search(rel):
                    provider = name
                    break
            if provider is None:
                continue
            text = repo.text(rel)
            commands = shell_commands(text) if provider == "jenkins" else yaml_commands(text)
            matches = {}
            for line, command in commands:
                for tool in self.match_tools(command, ALL_TOOLS):
                    matches.setdefault((tool.name, None), (tool, line, None))
                for tool, via in self.resolve(command, ALL_TOOLS):
                    matches.setdefault((tool.name, via), (tool, line, via))
            tool_rows = []
            for (name, via), (tool, line, via_name) in matches.items():
                row = {"tool": tool.name, "category": tool.category, "language": tool.language,
                       "file": rel, "line": line, "how": "ci"}
                if via_name:
                    row["via"] = via_name
                tool_rows.append(row)
            tool_rows.sort(key=lambda r: (r["line"], r["tool"]))
            pull_request = any(
                re.search(r"\b(pull_request(_target)?|merge_requests?(_event)?)\b", line)
                for line in text.splitlines() if not line.lstrip().startswith("#"))
            files.append({"file": rel, "provider": provider, "pull_request": pull_request,
                          "tools": tool_rows})
            for row in tool_rows:
                if rel not in by_tool[row["tool"]]:
                    by_tool[row["tool"]].append(rel)
        return {"files": files, "tools": {k: v for k, v in sorted(by_tool.items())}}

    # ---- pre-commit, husky, lefthook ------------------------------------

    def detect_precommit(self):
        repo = self.repo
        hooks = []
        rows = {}
        config = None
        for rel in repo.by_name.get(".pre-commit-config.yaml", []):
            config = config or rel
            repo_url = None
            rev = None
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
                    for tool in self.match_tools(m.group(1), ALL_TOOLS):
                        rows.setdefault((tool.name, rel), self.precommit_row(tool, rel, number))
                    continue
                m = re.match(r"^\s*entry\s*:\s*(.+)$", line)
                if m:
                    for tool in self.match_tools(m.group(1), ALL_TOOLS):
                        rows.setdefault((tool.name, rel), self.precommit_row(tool, rel, number))
        husky = sorted(f for f in repo.files if f.startswith(".husky/") and "/_/" not in f
                       and not f.startswith(".husky/_"))
        lefthook = [f for name in ("lefthook.yml", "lefthook.yaml", ".lefthook.yml")
                    for f in repo.by_name.get(name, [])]
        for rel in husky:
            for number, command in shell_commands(repo.text(rel)):
                for tool in self.match_tools(command, ALL_TOOLS):
                    rows.setdefault((tool.name, rel), self.precommit_row(tool, rel, number))
        for rel in lefthook:
            for number, command in yaml_commands(repo.text(rel)):
                for tool in self.match_tools(command, ALL_TOOLS):
                    rows.setdefault((tool.name, rel), self.precommit_row(tool, rel, number))
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
                pins.append({"kind": name, "file": rel, "line": 1, "subproject": sub_of(rel)})
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
        for rel in repo.by_name.get("package.json", []):
            hit = repo.match_spec("package.json::engines", dir_of(rel))
            if hit:
                pins.append({"kind": "package.json engines", "file": rel, "line": hit[1], "subproject": sub_of(rel)})
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
        return {"lockfiles": sorted(lockfiles, key=lambda r: r["file"]),
                "requirements_files": requirements,
                "toolchain_pins": sorted(pins, key=lambda r: (r["file"], r["kind"])),
                "task_runners": sorted(runners, key=lambda r: r["file"]),
                "devcontainer": devcontainer, "dockerfiles": dockerfiles[:20], "compose": compose[:20]}

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
        docs = {"readme": readme, "headings": [], "install": None, "run": None, "test": None,
                "contributing": None, "adr_dirs": [], "architecture_docs": [], "docs_dir": None}
        if readme:
            text = repo.text(readme)
            headings = self.headings(text, readme)
            docs["headings"] = headings[:80]
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

    # ---- assembly -------------------------------------------------------

    def run(self):
        repo = self.repo
        subs = find_subprojects(repo)
        for rel in repo.files:
            if posixpath.basename(rel) in ("pyproject.toml", "Cargo.toml"):
                repo.check_toml(rel)
        # Source files outside every manifest directory belong to an implicit root project.
        cache = {}
        orphans = any(language_of(rel) and self.owner(dir_of(rel), set(subs), cache) is None
                      for rel in repo.files)
        if "." not in subs and (orphans or not subs):
            subs["."] = {"manifests": [], "languages": set()}
        subproject_dirs = set(subs)
        languages, other, suppressions, per_sub = self.scan_sources(subproject_dirs)
        self.collect_scripts()
        owner_cache = {}
        self.script_commands = [(rel, line, command, self.owner(dir_of(rel), subproject_dirs, owner_cache))
                                for rel, line, command in self.script_commands]
        ci = self.detect_ci()
        precommit = self.detect_precommit()

        # shared tools, relative to the repo root
        shared = []
        for tool in ALL_TOOLS:
            if tool.language != "shared":
                continue
            for spec in tool.specs:
                hit = repo.match_spec(spec, ".")
                if hit:
                    shared.append(self.row(tool, hit, "config"))
                    break

        records = []
        for d, entry in subs.items():
            stats = per_sub.get(d, {lang: new_stats() for lang in LANGUAGES})
            langs = set(entry["languages"])
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
            subprojects.append(self.subproject_record(d, entry, langs, stats, shared))
        more_subprojects = [{"path": d, "manifest": (entry["manifests"] or [None])[0],
                             "languages": langs, "loc": loc} for d, entry, langs, stats, loc in more]

        has_git = repo.is_git
        commit = None
        branch = None
        if has_git:
            out = run_git(repo.root, ["rev-parse", "HEAD"])
            commit = out.decode().strip() if out else None
            out = run_git(repo.root, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
            if out:
                branch = out.decode().strip().split("/", 1)[-1]
            else:
                for name in ("main", "master"):
                    if run_git(repo.root, ["rev-parse", "--verify", "--quiet", "refs/heads/" + name]):
                        branch = name
                        break
        return {
            "repo": repo.root,
            "git": has_git,
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
            "parse_errors": [{"file": f, "parse_error": e} for f, e in sorted(repo.parse_errors.items())],
        }

    @staticmethod
    def row(tool, hit, how, **extra):
        row = {"tool": tool.name, "category": tool.category, "file": hit[0], "line": hit[1], "how": how}
        row.update(extra)
        return row

    def subproject_record(self, d, entry, langs, stats, shared):
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
                for candidate in ancestors(d):
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
        for rel, line, command, owner in self.script_commands:
            if owner != d:
                continue
            for tool in tool_rows:
                if tool.ci_match(command.lower()) and (tool.name, rel) not in owned:
                    owned[(tool.name, rel)] = self.row(tool, (rel, line), "script")
        for row in owned.values():
            categories[row["category"]].append(row)
        for row in shared:
            if row["category"] in categories:
                categories[row["category"]].append(row)
        record = {
            "path": d,
            "manifest": (entry["manifests"] or [None])[0],
            "manifests": [{"file": m, "parse_error": repo.parse_errors.get(m)} for m in entry["manifests"]],
            "languages": langs,
            "stats": {lang: stats[lang] for lang in langs},
            "categories": categories,
            "dependencies": count_dependencies(repo, d, entry["manifests"]),
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
