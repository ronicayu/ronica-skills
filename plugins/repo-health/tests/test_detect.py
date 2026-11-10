"""Tests for scripts/detect.py. Fixtures are built in temporary directories.

Run: python -m unittest discover -s plugins/repo-health/tests
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "skills", "repo-health", "scripts", "detect.py")

_spec = importlib.util.spec_from_file_location("repo_health_detect", SCRIPT)
detect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detect)


def isolated_git_env():
    env = dict(os.environ)
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    })
    return env


def git(root, *args):
    cmd = ["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false",
           "-c", "user.name=Test", "-c", "user.email=test@example.com"] + list(args)
    return subprocess.run(cmd, cwd=root, env=isolated_git_env(), check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="repo-health-detect-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel, text=""):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(textwrap.dedent(text).lstrip("\n"))

    def run_detect(self, **kwargs):
        return detect.Detector(self.root, kwargs.get("max_subprojects", 10)).run()

    @staticmethod
    def sub(result, path="."):
        for record in result["subprojects"]:
            if record["path"] == path:
                return record
        raise AssertionError("no subproject %r in %r" % (path, [r["path"] for r in result["subprojects"]]))

    @staticmethod
    def tools(record, category, how=None):
        return sorted(row["tool"] for row in record["categories"][category]
                      if how is None or row["how"] == how)

    @staticmethod
    def ci_tools(result, file=None):
        names = set()
        for entry in result["ci"]["files"]:
            if file is None or entry["file"] == file:
                names.update(row["tool"] for row in entry["tools"])
        return names


WORKFLOW = """
    name: ci
    on:
      pull_request:
      push:
        branches: [main]
    jobs:
      check:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - name: Lint
            run: %s
"""


class LanguageFixtures(Fixture):
    def test_python(self):
        self.write("pyproject.toml", """
            [project]
            name = "demo"
            requires-python = ">=3.9"
            dependencies = [
              "requests>=2",
              "click[extra]",
            ]

            [tool.ruff.lint]
            select = ["E"]

            [tool.pytest.ini_options]
            testpaths = ["tests"]
        """)
        self.write("uv.lock", "version = 1\n")
        self.write("src/app.py", "def main():\n    return 1\n\n\nprint(main())\n")
        self.write("tests/test_app.py", "def test_x():\n    assert True\n")
        self.write(".github/workflows/ci.yml", WORKFLOW % "ruff check .\n          - run: python -m pytest")
        result = self.run_detect()
        record = self.sub(result)
        self.assertEqual(record["languages"], ["python"])
        self.assertEqual(self.tools(record, "lint", "config"), ["ruff"])
        self.assertEqual(self.tools(record, "tests", "config"), ["pytest"])
        ruff = record["categories"]["lint"][0]
        self.assertEqual((ruff["file"], ruff["line"]), ("pyproject.toml", 9))
        self.assertEqual({"ruff", "pytest"}, self.ci_tools(result))
        entry = result["ci"]["files"][0]
        self.assertEqual(entry["file"], ".github/workflows/ci.yml")
        self.assertTrue(entry["pull_request"])
        self.assertEqual(result["languages"]["python"],
                         {"files": 1, "loc": 3, "test_files": 1, "test_loc": 2})
        self.assertEqual(record["dependencies"]["direct"], 2)
        self.assertEqual([lock["file"] for lock in result["setup"]["lockfiles"]], ["uv.lock"])
        pins = [pin for pin in result["setup"]["toolchain_pins"] if pin["kind"] == "requires-python"]
        self.assertEqual(pins[0]["value"], ">=3.9")

    def test_typescript(self):
        self.write("package.json", """
            {"name": "demo",
             "scripts": {"lint": "eslint .", "test": "vitest run"},
             "dependencies": {"react": "1"}, "devDependencies": {"vitest": "1", "eslint": "9"}}
        """)
        self.write("eslint.config.js", "export default [];\n")
        self.write("tsconfig.json", """
            {
              // comments and trailing commas are allowed in tsconfig
              "compilerOptions": {
                "strict": true,
                "paths": {"@/*": ["./src/*"],},
              },
            }
        """)
        self.write("package-lock.json", "{}")
        self.write("src/a.ts", "export const a = 1;\n")
        self.write("src/a.test.ts", "test('a', () => {});\n")
        self.write("src/__tests__/b.ts", "export const b = 2;\n")
        self.write(".github/workflows/ci.yml", WORKFLOW % "npm run lint\n          - run: npx tsc --noEmit")
        result = self.run_detect()
        record = self.sub(result)
        self.assertEqual(record["languages"], ["typescript"])
        self.assertEqual(self.tools(record, "lint", "config"), ["eslint"])
        self.assertEqual(self.tools(record, "lint", "script"), ["eslint"])
        self.assertEqual(self.tools(record, "tests", "script"), ["vitest"])
        tsc = record["categories"]["types"][0]
        self.assertEqual(tsc["tool"], "tsc")
        self.assertIs(tsc["strict"], True)
        self.assertEqual({"eslint", "tsc"}, self.ci_tools(result))
        via = [row for row in result["ci"]["files"][0]["tools"] if row["tool"] == "eslint"]
        self.assertEqual(via[0]["via"], "lint")
        # eslint.config.js counts as source by extension
        self.assertEqual(result["languages"]["typescript"]["files"], 2)
        self.assertEqual(result["languages"]["typescript"]["test_files"], 2)
        self.assertEqual(record["dependencies"], {"direct": 1, "dev": 2, "files": ["package.json"]})

    def test_rust(self):
        self.write("Cargo.toml", """
            [package]
            name = "demo"
            version = "0.1.0"

            [lints.clippy]
            pedantic = "warn"

            [dependencies]
            serde = "1"
            anyhow = "1"
        """)
        self.write("Cargo.lock", "")
        self.write("src/lib.rs", "pub fn a() {}\n\n#[cfg(test)]\nmod tests {\n    #[test]\n    fn t() {}\n}\n")
        self.write("src/other.rs", "pub fn b() {}\n")
        self.write("tests/it.rs", "#[test]\nfn it() {}\n")
        self.write(".github/workflows/ci.yml", WORKFLOW % "cargo clippy --all-targets\n          - run: cargo test")
        result = self.run_detect()
        record = self.sub(result)
        self.assertEqual(self.tools(record, "lint"), ["clippy"])
        self.assertEqual({"clippy", "cargo-test"}, self.ci_tools(result))  # "cargo test" is not "go test"
        rust = result["languages"]["rust"]
        self.assertEqual((rust["files"], rust["test_files"], rust["inline_test_files"]), (2, 1, 1))
        self.assertEqual(record["dependencies"]["direct"], 2)
        self.assertEqual(result["setup"]["lockfiles"][0]["file"], "Cargo.lock")

    def test_java(self):
        self.write("pom.xml", """
            <project>
              <build><plugins>
                <plugin><artifactId>maven-checkstyle-plugin</artifactId></plugin>
                <plugin><artifactId>jacoco-maven-plugin</artifactId></plugin>
              </plugins></build>
              <dependencies>
                <dependency><artifactId>junit-jupiter</artifactId><scope>test</scope></dependency>
                <dependency><artifactId>guava</artifactId></dependency>
              </dependencies>
            </project>
        """)
        self.write("src/main/java/A.java", "class A {}\n")
        self.write("src/test/java/ATest.java", "class ATest {}\n")
        self.write(".github/workflows/ci.yml", WORKFLOW % "mvn verify")
        result = self.run_detect()
        record = self.sub(result)
        self.assertEqual(record["languages"], ["java"])
        self.assertEqual(self.tools(record, "lint"), ["checkstyle"])
        self.assertEqual(self.tools(record, "tests"), ["junit"])
        self.assertEqual(self.tools(record, "coverage"), ["jacoco"])
        # junit, testng and kotest share the same CI words
        self.assertEqual(self.ci_tools(result), {"junit", "testng", "kotest"})
        self.assertEqual(result["languages"]["java"]["test_files"], 1)
        self.assertEqual(record["dependencies"], {"direct": 1, "dev": 1, "files": ["pom.xml"]})

    def test_go(self):
        self.write("go.mod", "module demo\n\ngo 1.22\n\nrequire (\n\tgithub.com/a/b v1.0.0\n\tgithub.com/c/d v1.0.0 // indirect\n)\n")
        self.write("go.sum", "")
        self.write(".golangci.yml", "linters:\n  enable: [govet]\n")
        self.write("main.go", "package main\n\nfunc main() {}\n")
        self.write("main_test.go", "package main\n")
        self.write(".github/workflows/ci.yml", WORKFLOW % "golangci-lint run\n          - run: go test -cover ./...")
        result = self.run_detect()
        record = self.sub(result)
        self.assertEqual(self.tools(record, "lint"), ["golangci-lint"])
        self.assertEqual({"golangci-lint", "go-test", "go-cover"}, self.ci_tools(result))
        self.assertEqual(result["languages"]["go"]["test_files"], 1)
        self.assertEqual(record["dependencies"]["direct"], 1)
        directive = [p for p in result["setup"]["toolchain_pins"] if p["kind"] == "go directive"]
        self.assertEqual(directive[0]["value"], "1.22")

    def test_kotlin_gradle_with_jacoco(self):
        self.write("build.gradle.kts", """
            plugins {
                kotlin("jvm") version "2.0.0"
                id("io.gitlab.arturbosch.detekt") version "1.23.0"
                jacoco
            }
            dependencies {
                implementation("a:b:1")
                testImplementation("io.kotest:kotest-runner-junit5:5")
            }
        """)
        self.write("gradle.lockfile", "")
        self.write("src/main/kotlin/A.kt", "class A\n")
        self.write("src/test/kotlin/ATest.kt", "class ATest\n")
        self.write(".github/workflows/ci.yml", WORKFLOW % "./gradlew check\n          - run: ./gradlew detekt")
        result = self.run_detect()
        record = self.sub(result)
        self.assertEqual(record["languages"], ["kotlin"])
        self.assertEqual(self.tools(record, "coverage"), ["jacoco"])
        self.assertEqual(self.tools(record, "lint"), ["detekt"])
        self.assertEqual(self.tools(record, "tests"), ["junit", "kotest"])
        self.assertIn("detekt", self.ci_tools(result))
        # build.gradle.kts is a build file, not Kotlin source
        self.assertEqual(result["languages"]["kotlin"]["files"], 1)
        self.assertEqual(result["languages"]["kotlin"]["test_files"], 1)
        self.assertEqual(record["dependencies"], {"direct": 1, "dev": 1, "files": ["build.gradle.kts"]})


class Matching(Fixture):
    def test_short_words_match_whole_words_only(self):
        self.write("pyproject.toml", "[project]\nname = 'x'\n")
        self.write(".github/workflows/ci.yml", """
            on: pull_request
            jobs:
              a:
                steps:
                  - run: ./blackbox.sh
                  - run: echo toxic
                  - run: echo nycx c8x anyc
        """)
        result = self.run_detect()
        self.assertEqual(self.ci_tools(result), set())
        self.write(".github/workflows/ci.yml", """
            on: pull_request
            jobs:
              a:
                steps:
                  - run: black --check .
                  - run: tox -e py
        """)
        self.assertEqual(self.ci_tools(self.run_detect()), {"black", "tox"})

    def test_ci_reads_run_blocks_and_uses_but_not_names(self):
        self.write(".github/workflows/ci.yml", """
            on: [push]
            jobs:
              a:
                steps:
                  - name: Run ruff and pytest here
                    uses: github/codeql-action/init@v3
                  - run: |
                      echo start
                      mypy src
                  - name: not a command
                    env:
                      X: gitleaks
        """)
        result = self.run_detect()
        self.assertEqual(self.ci_tools(result), {"codeql", "mypy"})
        self.assertFalse(result["ci"]["files"][0]["pull_request"])
        mypy = [r for r in result["ci"]["files"][0]["tools"] if r["tool"] == "mypy"][0]
        self.assertEqual(mypy["line"], 9)

    def test_go_cover_does_not_match_coverage_flag(self):
        self.write(".github/workflows/ci.yml", "on: pull_request\njobs:\n  a:\n    steps:\n      - run: npx jest --coverage\n")
        tools = self.ci_tools(self.run_detect())
        self.assertIn("jest", tools)
        self.assertNotIn("go-cover", tools)

    def test_gitlab_script_list(self):
        self.write(".gitlab-ci.yml", """
            test:
              script:
                - pip install tox
                - tox
              rules:
                - if: $CI_PIPELINE_SOURCE == "merge_request_event"
        """)
        result = self.run_detect()
        entry = result["ci"]["files"][0]
        self.assertEqual(entry["provider"], "gitlab")
        self.assertTrue(entry["pull_request"])
        self.assertEqual({r["tool"] for r in entry["tools"]}, {"tox"})

    def test_make_target_resolved_from_ci(self):
        self.write("pyproject.toml", "[project]\nname = 'x'\n")
        self.write("Makefile", "lint:\n\truff check .\n\ncheck: lint\n\tpytest\n")
        self.write(".github/workflows/ci.yml", "on: pull_request\njobs:\n  a:\n    steps:\n      - run: make check\n")
        result = self.run_detect()
        rows = {r["tool"]: r for r in result["ci"]["files"][0]["tools"]}
        self.assertEqual(set(rows), {"ruff", "pytest"})
        self.assertEqual(rows["ruff"]["via"], "lint")
        record = self.sub(result)
        self.assertEqual(self.tools(record, "lint", "script"), ["ruff"])

    def test_precommit_husky_and_lefthook(self):
        self.write(".pre-commit-config.yaml", """
            repos:
              - repo: https://github.com/astral-sh/ruff-pre-commit
                rev: v0.5.0
                hooks:
                  - id: ruff
                  - id: ruff-format
              - repo: local
                hooks:
                  - id: tests
                    entry: pytest -q
        """)
        self.write(".husky/pre-commit", "#!/bin/sh\n# comment\nnpx eslint .\n")
        self.write("lefthook.yml", "pre-commit:\n  commands:\n    fmt:\n      run: prettier --check .\n")
        result = self.run_detect()
        pre = result["precommit"]
        self.assertEqual(pre["config"], ".pre-commit-config.yaml")
        self.assertEqual([h["id"] for h in pre["hooks"]], ["ruff", "ruff-format", "tests"])
        self.assertEqual(pre["hooks"][0]["rev"], "v0.5.0")
        self.assertEqual({r["tool"] for r in pre["tools"]}, {"ruff", "ruff-format", "pytest", "eslint", "prettier"})
        self.assertTrue(all(r["how"] == "precommit" for r in pre["tools"]))
        self.assertEqual(pre["husky"], [".husky/pre-commit"])
        shared = {row["tool"] for row in result["shared"]}
        self.assertTrue({"pre-commit", "husky", "lefthook"} <= shared)

    def test_shared_tools_found_at_root(self):
        self.write("pyproject.toml", "[project]\nname = 'x'\n")
        self.write(".github/dependabot.yml", "version: 2\n")
        self.write(".github/workflows/codeql.yml", "on: pull_request\n")
        self.write(".gitleaks.toml", "")
        self.write(".semgrep/rules.yml", "rules: []\n")
        result = self.run_detect()
        self.assertEqual({row["tool"] for row in result["shared"]},
                         {"dependabot", "codeql", "gitleaks", "semgrep"})
        record = self.sub(result)
        self.assertEqual(self.tools(record, "deps_bot"), ["dependabot"])
        self.assertEqual(self.tools(record, "static"), ["codeql", "semgrep"])
        self.assertEqual(self.tools(record, "secrets"), ["gitleaks"])

    def test_config_is_inherited_from_the_repo_root(self):
        self.write("pyproject.toml", "[tool.ruff]\nline-length = 100\n")
        self.write("services/a/pyproject.toml", "[project]\nname = 'a'\n")
        self.write("services/a/a.py", "x = 1\n")
        result = self.run_detect()
        record = self.sub(result, "services/a")
        ruff = record["categories"]["lint"][0]
        self.assertEqual(ruff["file"], "pyproject.toml")
        self.assertEqual(ruff["inherited_from"], ".")
        self.assertNotIn("inherited_from", self.sub(result, ".")["categories"]["lint"][0])


class Structure(Fixture):
    def test_monorepo_skips_node_modules(self):
        self.write("api/pyproject.toml", "[project]\nname = 'api'\n")
        self.write("api/app.py", "x = 1\n")
        self.write("web/package.json", '{"name": "web"}')
        self.write("web/src/index.ts", "export {};\n")
        self.write("web/node_modules/dep/index.js", "module.exports = 1;\n" * 50)
        self.write("web/node_modules/dep/package.json", '{"name": "dep"}')
        self.write("core/Cargo.toml", "[package]\nname = 'core'\n")
        self.write("core/src/lib.rs", "pub fn a() {}\n")
        self.write("core/target/debug/gen.rs", "fn x() {}\n")
        self.write("vendor/lib/x.go", "package x\n")
        result = self.run_detect()
        self.assertEqual([r["path"] for r in result["subprojects"]], ["api", "core", "web"])
        self.assertEqual(result["languages"]["typescript"]["files"], 1)
        self.assertEqual(result["languages"]["rust"]["files"], 1)
        self.assertEqual(result["languages"]["go"]["files"], 0)
        self.assertFalse(result["git"])
        self.assertEqual(self.sub(result, "web")["languages"], ["typescript"])

    def test_workspace_members_are_not_subprojects(self):
        self.write("package.json", '{"name": "root", "workspaces": ["packages/*"]}')
        self.write("packages/a/package.json", '{"name": "a"}')
        self.write("packages/a/index.ts", "export {};\n")
        self.write("tools/package.json", '{"name": "tools"}')
        result = self.run_detect()
        self.assertEqual({r["path"] for r in result["subprojects"]}, {".", "tools"})

    def test_subproject_cap_lists_the_rest(self):
        for name, loc in (("a", 30), ("b", 20), ("c", 10)):
            self.write("%s/pyproject.toml" % name, "[project]\nname = '%s'\n" % name)
            self.write("%s/m.py" % name, "x = 1\n" * loc)
        result = self.run_detect(max_subprojects=2)
        self.assertEqual([r["path"] for r in result["subprojects"]], ["a", "b"])
        self.assertEqual([r["path"] for r in result["more_subprojects"]], ["c"])

    def test_no_manifest_gives_one_root_subproject(self):
        self.write("script.py", "print(1)\n")
        result = self.run_detect()
        self.assertEqual([r["path"] for r in result["subprojects"]], ["."])
        self.assertEqual(self.sub(result)["languages"], ["python"])

    def test_other_languages_are_counted_not_analysed(self):
        self.write("a.rb", "puts 1\n")
        self.write("b.cs", "class B {}\n")
        self.write("c.cpp", "int main() {}\n")
        self.assertEqual(self.run_detect()["other_languages"], {"c/c++": 1, "csharp": 1, "ruby": 1})

    def test_malformed_manifests_do_not_crash(self):
        self.write("pyproject.toml", "[tool.ruff\nline-length = = 3\n[project\n")
        self.write("package.json", '{"name": "x", "scripts": {')
        self.write("tsconfig.json", '{"compilerOptions": {"strict": true,')
        self.write("src/a.ts", "export {};\n")
        result = self.run_detect()
        files = {e["file"]: e["parse_error"] for e in result["parse_errors"]}
        self.assertIn("package.json", files)
        if detect.tomllib is not None:
            self.assertIn("pyproject.toml", files)
        record = self.sub(result)
        self.assertEqual(record["manifests"][0]["file"] in ("package.json", "pyproject.toml"), True)
        tsc = [r for r in record["categories"]["types"] if r["tool"] == "tsc"][0]
        self.assertIs(tsc["strict"], True)  # found by the regex fallback

    def test_suppression_counts(self):
        self.write("a.py", "x = 1  # noqa\ny = 2  # noqa: E501\nz = f()  # type: ignore\n")
        self.write("b.py", "x = 1  # noqa\n")
        self.write("c.ts", "// @ts-ignore\n/* eslint-disable */\n// @ts-expect-error\n")
        self.write("d.rs", "#![allow(unused)]\n#[allow(dead_code)]\nfn f() {}\n")
        self.write("E.java", "@SuppressWarnings(\"x\")\nclass E {} // NOPMD\n")
        self.write("f.kt", "@Suppress(\"x\")\nclass F\n")
        self.write("g.go", "package g\n//nolint\n// #nosec\n")
        sup = self.run_detect()["suppressions"]
        self.assertEqual(sup["python"]["markers"], {"# noqa": 3, "# type: ignore": 1})
        self.assertEqual(sup["python"]["total"], 4)
        self.assertEqual(sup["python"]["top_files"][0], {"file": "a.py", "count": 3})
        self.assertEqual(sup["typescript"]["markers"], {"@ts-expect-error": 1, "@ts-ignore": 1, "eslint-disable": 1})
        self.assertEqual(sup["rust"]["markers"], {"#![allow(": 1, "#[allow(": 1})
        self.assertEqual(sup["java"]["markers"], {"@SuppressWarnings": 1, "NOPMD": 1})
        self.assertEqual(sup["kotlin"]["markers"], {"@Suppress(": 1})
        self.assertEqual(sup["go"]["markers"], {"#nosec": 1, "//nolint": 1})

    def test_docs(self):
        self.write("README.md", """
            # Demo

            ## Installation

            ```sh
            # not a heading
            pip install demo
            ```

            ## Usage
        """)
        self.write("CONTRIBUTING.md", "")
        self.write("docs/adr/0001-x.md", "")
        self.write("docs/architecture.md", "")
        docs = self.run_detect()["docs"]
        self.assertEqual(docs["readme"], "README.md")
        self.assertEqual([h["text"] for h in docs["headings"]], ["Demo", "Installation", "Usage"])
        self.assertEqual(docs["install"]["via"], "heading")
        self.assertEqual(docs["run"]["via"], "heading")
        self.assertFalse(docs["test"]["found"])
        self.assertEqual(docs["contributing"], "CONTRIBUTING.md")
        self.assertEqual(docs["adr_dirs"], ["docs/adr"])
        self.assertIn("docs/architecture.md", docs["architecture_docs"])

    def test_readme_commands_count_without_headings(self):
        self.write("README.md", "# Demo\n\nRun `pytest` to test, `npm install` to install, `python -m demo` to run.\n")
        docs = self.run_detect()["docs"]
        self.assertEqual((docs["install"]["via"], docs["run"]["via"], docs["test"]["via"]),
                         ("command", "command", "command"))

    def test_setup_files(self):
        self.write("Makefile", "test:\n\tpytest\n\nlint:\n\truff .\n")
        self.write(".python-version", "3.12\n")
        self.write("Dockerfile", "FROM python:3.12\n")
        self.write(".devcontainer/devcontainer.json", "{}")
        self.write("requirements.txt", "requests==2\n# c\nclick==8\n")
        setup = self.run_detect()["setup"]
        self.assertEqual(setup["task_runners"][0]["targets"], ["test", "lint"])
        self.assertEqual(setup["toolchain_pins"][0]["file"], ".python-version")
        self.assertEqual(setup["dockerfiles"], ["Dockerfile"])
        self.assertEqual(setup["devcontainer"], [".devcontainer/devcontainer.json"])
        self.assertEqual(setup["requirements_files"], ["requirements.txt"])

    def test_loc_counts_non_blank_lines(self):
        self.write("a.py", "a = 1\n\n   \nb = 2\n")
        self.assertEqual(self.run_detect()["languages"]["python"]["loc"], 2)

    def test_large_file_loc_is_scaled(self):
        line = "x = 1\n"
        self.write("big.py", line * (detect.READ_LIMIT // len(line) * 2))
        loc = self.run_detect()["languages"]["python"]["loc"]
        expected = detect.READ_LIMIT // len(line) * 2
        self.assertLess(abs(loc - expected), expected * 0.01)


class GitRepo(Fixture):
    def test_git_listing_honours_gitignore(self):
        git(self.root, "init", "-q")
        self.write(".gitignore", "scratch/\n")
        self.write("a.py", "x = 1\n")
        self.write("scratch/b.py", "x = 1\n")
        git(self.root, "add", "a.py", ".gitignore")
        git(self.root, "commit", "-q", "-m", "init")
        result = self.run_detect()
        self.assertTrue(result["git"])
        self.assertEqual(result["commit"], git(self.root, "rev-parse", "HEAD"))
        self.assertEqual(result["default_branch"], "main")
        self.assertEqual(result["languages"]["python"]["files"], 1)

    def test_directory_inside_a_larger_repo_is_not_git(self):
        git(self.root, "init", "-q")
        self.write("outer.py", "x = 1\n")
        inner = os.path.join(self.root, "inner")
        os.makedirs(inner)
        with open(os.path.join(inner, "b.py"), "w") as handle:
            handle.write("y = 1\n")
        result = detect.Detector(inner, 10).run()
        self.assertFalse(result["git"])
        self.assertEqual(result["languages"]["python"]["files"], 1)


class Cli(Fixture):
    def test_cli_prints_json(self):
        self.write("a.py", "x = 1\n")
        out = subprocess.run([sys.executable, SCRIPT, self.root], stdout=subprocess.PIPE, check=True).stdout
        data = json.loads(out.decode())
        self.assertEqual(data["languages"]["python"]["files"], 1)
        pretty = subprocess.run([sys.executable, SCRIPT, self.root, "--pretty"], stdout=subprocess.PIPE, check=True).stdout
        self.assertEqual(json.loads(pretty.decode()), data)

    def test_cli_rejects_a_missing_directory(self):
        proc = subprocess.run([sys.executable, SCRIPT, os.path.join(self.root, "nope")],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 2)

    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        with open(SCRIPT) as handle:
            self.assertEqual(handle.readline().strip(), "#!/usr/bin/env python3")


class ToolTable(unittest.TestCase):
    def test_rows_are_well_formed(self):
        names = [row[1] for row in detect.TOOLS]
        self.assertEqual(len(names), len(set(names)))
        for language, name, category, specs, words in detect.TOOLS:
            self.assertIn(language, set(detect.LANGUAGES) | {"shared"}, name)
            self.assertIn(category, detect.CATEGORIES, name)
            self.assertIsInstance(specs, list)
            self.assertIsInstance(words, list)
            self.assertTrue(specs or words, "%s has neither config nor CI words" % name)

    def test_kotlin_also_gets_the_named_java_rows(self):
        names = {t.name for t in detect.tools_for_language("kotlin")}
        self.assertTrue(set(detect.KOTLIN_FROM_JAVA) <= names)
        self.assertNotIn("checkstyle", names)

    def test_brace_expansion(self):
        self.assertEqual(detect.expand_braces("a.{js,ts}"), ["a.js", "a.ts"])
        self.assertEqual(detect.expand_braces("x"), ["x"])


if __name__ == "__main__":
    unittest.main()
