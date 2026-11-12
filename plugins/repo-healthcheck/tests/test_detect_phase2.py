"""Tests for the facts detect.py adds for score.py: test suites, update bots, publishable.

Run: python -m unittest discover -s plugins/repo-healthcheck/tests
"""

import os
import unittest

from test_detect import Fixture


class TestSuites(Fixture):
    def test_suites_group_by_the_first_tests_folder(self):
        self.write("pyproject.toml", "[project]\nname = 'x'\n")
        self.write("a/tests/test_one.py", "def test_a():\n    pass\n")
        self.write("a/tests/unit/test_two.py", "def test_b():\n    pass\n")
        self.write("b/tests/test_three.py", "def test_c():\n    pass\n")
        self.write("c/test_four.py", "def test_d():\n    pass\n")
        suites = self.sub(self.run_detect())["test_suites"]
        self.assertEqual([(s["path"], s["language"], s["files"]) for s in suites],
                         [(".", "python", 1), ("a/tests", "python", 2), ("b/tests", "python", 1)])

    def test_member_suites_are_listed_under_the_root(self):
        self.write("package.json", '{"name": "r", "private": true, "workspaces": ["packages/*"]}')
        self.write("packages/a/package.json", '{"name": "a"}')
        self.write("packages/a/src/x.test.ts", "test('x', () => {})\n")
        self.write("packages/a/tests/y.test.ts", "test('y', () => {})\n")
        suites = self.sub(self.run_detect())["test_suites"]
        self.assertEqual([s["path"] for s in suites], ["packages/a", "packages/a/tests"])

    def test_no_tests_no_suites(self):
        self.write("pyproject.toml", "[project]\nname = 'x'\n")
        self.write("x.py", "x = 1\n")
        self.assertEqual(self.sub(self.run_detect())["test_suites"], [])


class CiRunsScripts(Fixture):
    WF = "on: pull_request\njobs:\n  a:\n    runs-on: x\n%s    steps:\n      - run: %s\n"

    def rows(self, run, header=""):
        self.write("tests/run_all.py", "print(1)\n")
        self.write("web/package.json", '{"name": "w", "private": true}')
        self.write("web/a.ts", "export {}\n")
        self.write(".github/workflows/a.yml", self.WF % (header, run))
        result = self.run_detect()
        return {r["tool"]: r for f in result["ci"]["files"] for r in f["tools"]}

    def test_a_script_in_a_test_folder_is_a_test_row(self):
        for command in ("python tests/run_all.py", "python3 -u tests/run_all.py", "./tests/run_all.py"):
            row = self.rows(command)["test-script"]
            self.assertEqual((row["category"], row["language"], row["via_file"]), ("tests", "shared", "tests/run_all.py"))
        self.assertNotIn("test-script", self.rows("python tools/other.py"))
        self.assertNotIn("test-script", self.rows("python tests/missing.py"))

    def test_working_directory_and_cd_set_the_row_folder(self):
        row = self.rows("tsc --noEmit", "    defaults:\n      run:\n        working-directory: web\n")["tsc"]
        self.assertEqual(row["dir"], "web")
        self.assertEqual(self.rows("cd web && tsc --noEmit")["tsc"]["dir"], "web")
        self.assertNotIn("dir", self.rows("tsc --noEmit")["tsc"])


class TypeScriptFiles(Fixture):
    def test_ts_files_are_counted_apart_from_javascript(self):
        self.write("package.json", '{"name": "a"}')
        for name in ("a.ts", "b.tsx", "c.mts", "d.cts", "e.js", "f.mjs"):
            self.write("src/" + name, "export {}\n")
        stats = self.sub(self.run_detect())["stats"]["typescript"]
        self.assertEqual((stats["files"], stats["ts_files"]), (6, 4))

    def test_nested_subprojects_keep_their_own_count(self):
        self.write("a.mjs", "export {}\n")
        self.write("web/package.json", '{"name": "w"}')
        self.write("web/x.ts", "export {}\n")
        result = self.run_detect()
        self.assertEqual(self.sub(result, ".")["stats"]["typescript"].get("ts_files", 0), 0)
        self.assertEqual(self.sub(result, "web")["stats"]["typescript"]["ts_files"], 1)

    def test_workspace_root_counts_its_members(self):
        self.write("package.json", '{"name": "r", "private": true, "workspaces": ["packages/*"]}')
        self.write("packages/a/package.json", '{"name": "a"}')
        self.write("packages/a/x.ts", "export {}\n")
        self.assertEqual(self.sub(self.run_detect())["stats"]["typescript"]["ts_files"], 1)


class UpdateBots(Fixture):
    def test_dependabot_ecosystems_are_normalised(self):
        self.write(".github/dependabot.yml", """
            version: 2
            updates:
              - package-ecosystem: "pip"
                directory: "/"
              - package-ecosystem: github-actions
                directory: "/"
              - package-ecosystem: gomod
                directory: "/"
        """)
        bots = self.run_detect()["setup"]["update_bots"]
        self.assertEqual(bots, [{"tool": "dependabot", "file": ".github/dependabot.yml", "line": 3,
                                 "ecosystems": ["actions", "go", "python"]}])

    def test_renovate_covers_everything(self):
        self.write("renovate.json", "{}")
        bots = self.run_detect()["setup"]["update_bots"]
        self.assertEqual([(b["tool"], b["ecosystems"]) for b in bots], [("renovate", ["*"])])

    def test_no_bot(self):
        self.write("x.py", "x = 1\n")
        self.assertEqual(self.run_detect()["setup"]["update_bots"], [])


class Publishable(Fixture):
    def kind(self, manifest, text):
        self.write(manifest, text)
        self.write(os.path.join(os.path.dirname(manifest), "x.py"), "x = 1\n")
        record = self.sub(self.run_detect(), os.path.dirname(manifest) or ".")
        return record["publishable"] and record["publishable"]["kind"]

    def test_npm_private_is_not_published(self):
        self.assertIsNone(self.kind("package.json", '{"name": "a", "private": true}'))

    def test_npm_with_a_name_is_published(self):
        self.assertEqual(self.kind("package.json", '{"name": "a", "version": "1.0.0"}'), "npm")

    def test_pyproject_needs_project_and_build_system(self):
        self.assertEqual(self.kind("pyproject.toml", "[project]\nname='a'\n[build-system]\nrequires=[]\n"), "pypi")

    def test_pyproject_without_build_system_is_not_published(self):
        self.assertIsNone(self.kind("pyproject.toml", "[project]\nname='a'\n"))

    def test_cargo_publish_false(self):
        self.assertIsNone(self.kind("Cargo.toml", "[package]\nname='a'\npublish = false\n"))
        self.assertEqual(self.kind("Cargo.toml", "[package]\nname='a'\n"), "crate")


class ArchitectureDocs(Fixture):
    def docs(self):
        return {(d["kind"], d["path"]): d for d in self.run_detect()["architecture_docs"]}

    def test_architecture_file_and_readme_section(self):
        self.write("README.md", "# x\n\n## Architecture\n\ntext\n")
        self.write("ARCHITECTURE.md", "# a\n")
        self.write("docs/architecture/layers.md", "# l\n")
        self.write("x.py", "x = 1\n")
        found = self.docs()
        self.assertEqual(sorted(found), [("architecture", "ARCHITECTURE.md"), ("architecture", "docs/architecture"),
                                         ("readme-section", "README.md")])
        self.assertEqual(found[("readme-section", "README.md")]["line"], 3)
        self.assertIsNone(found[("architecture", "ARCHITECTURE.md")]["last_commit"])

    def test_adrs_and_models_do_not_count(self):
        self.write("docs/adr/0001.md", "# 1\n")
        self.write("workspace.dsl", "workspace {}\n")
        self.write("a.c4", "model {}\n")
        self.write("records/0001.md", "# 1\n")
        self.write(".adr-dir", "records\n")
        self.assertEqual(self.run_detect()["architecture_docs"], [])

    def test_last_commit_comes_from_git(self):
        from test_detect import git
        self.write("ARCHITECTURE.md", "# a\n")
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "x")
        self.assertRegex(self.docs()[("architecture", "ARCHITECTURE.md")]["last_commit"], r"^\d{4}-\d\d-\d\dT")


class ArchTools(Fixture):
    def arch(self, record=None):
        return {r["tool"]: r for r in self.sub(self.run_detect(), ".")["categories"]["arch"]}

    def test_python_tools(self):
        self.write("pyproject.toml", "[tool.importlinter]\nroot_package='x'\n")
        self.write("tach.toml", "")
        self.write("requirements-dev.txt", "pytestarch==3\n")
        self.write("x.py", "x = 1\n")
        found = self.arch()
        self.assertEqual(sorted(found), ["import-linter", "pytestarch", "tach"])
        self.assertEqual(found["pytestarch"]["rides_on"], "tests")
        self.assertNotIn("rides_on", found["tach"])

    def test_ci_words(self):
        self.write("x.py", "x = 1\n")
        self.write(".github/workflows/a.yml", "on: pull_request\\njobs:\\n  a:\\n    runs-on: x\\n    steps:\\n      - run: lint-imports\\n".replace("\\n", "\n"))
        self.assertIn("import-linter", self.ci_tools(self.run_detect()))

    def test_typescript_plugin_rides_on_eslint(self):
        self.write("package.json", '{"name": "a"}')
        self.write("eslint.config.js", "export default [{rules: {'boundaries/element-types': 2}}]\n")
        self.write("a.ts", "export {}\n")
        self.assertEqual(self.arch()["eslint-plugin-boundaries"]["rides_on"], "eslint")

    def test_java_archunit_also_for_kotlin(self):
        self.write("build.gradle.kts", 'plugins { kotlin("jvm") }\ndependencies { testImplementation("com.tngtech.archunit:archunit") }\n')
        self.write("A.kt", "class A\n")
        self.assertIn("archunit", self.arch())

    def test_go_depguard(self):
        self.write("go.mod", "module x\n\ngo 1.22\n")
        self.write("a.go", "package a\n")
        self.write(".golangci.yml", "linters:\n  enable: [depguard]\n")
        self.assertEqual(self.arch()["depguard"]["rides_on"], "golangci-lint")


if __name__ == "__main__":
    unittest.main()
