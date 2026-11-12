"""Tests for workspace roots (one subproject with members) in detect.py.

Run: python -m unittest discover -s plugins/repo-healthcheck/tests
"""

import importlib.util
import os
import shutil
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "skills", "repo-healthcheck", "scripts", "detect.py")

_spec = importlib.util.spec_from_file_location("repo_healthcheck_detect_ws", SCRIPT)
detect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detect)


class Workspaces(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="repo-healthcheck-ws-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel, text=""):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(textwrap.dedent(text).lstrip("\n"))

    def detect(self, **kwargs):
        return detect.Detector(self.root, kwargs.get("max_subprojects", 10)).run()

    @staticmethod
    def members(record):
        return [m["path"] for m in record["members"]]

    def test_a_cargo_workspace_is_one_subproject(self):
        self.write("Cargo.toml", '[workspace]\nmembers = ["crates/*", "tools/cli"]\nexclude = ["crates/old"]\n')
        for index in range(30):
            self.write("crates/c%02d/Cargo.toml" % index, '[package]\nname = "c%02d"\n' % index)
            self.write("crates/c%02d/src/lib.rs" % index, "pub fn f() {}\n")
        self.write("crates/old/Cargo.toml", '[package]\nname = "old"\n')
        self.write("tools/cli/Cargo.toml", '[package]\nname = "cli"\n')
        self.write("tools/cli/src/main.rs", "fn main() {}\n")
        self.write("tools/other/Cargo.toml", '[package]\nname = "other"\n')
        result = self.detect()
        self.assertEqual([r["path"] for r in result["subprojects"]], [".", "crates/old", "tools/other"])
        root = result["subprojects"][0]
        self.assertEqual(len(root["members"]), 31)
        self.assertEqual(root["workspace"], {"kind": "cargo", "manifest": "Cargo.toml"})
        self.assertEqual(root["languages"], ["rust"])
        self.assertEqual(root["stats"]["rust"]["files"], 31)
        member = [m for m in root["members"] if m["path"] == "crates/c07"][0]
        self.assertEqual((member["languages"], member["stats"]["rust"]["files"]), (["rust"], 1))
        self.assertEqual(member["members"], [])
        self.assertIsNone(member["workspace"])

    def test_a_virtual_cargo_manifest_without_member_sources_still_roots_the_workspace(self):
        self.write("Cargo.toml", '[workspace]\nmembers = [\n  "a",\n  "b", # comment\n]\n')
        self.write("a/Cargo.toml", '[package]\nname = "a"\n')
        self.write("b/Cargo.toml", '[package]\nname = "b"\n')
        result = self.detect()
        self.assertEqual([r["path"] for r in result["subprojects"]], ["."])
        self.assertEqual(self.members(result["subprojects"][0]), ["a", "b"])

    def test_maven_modules_are_transitive(self):
        self.write("pom.xml", "<project><modules>\n<module>core</module>\n<module>web/pom.xml</module></modules></project>\n")
        self.write("core/pom.xml", "<project><modules><module>../shared</module></modules></project>\n")
        self.write("core/src/main/java/A.java", "class A {}\n")
        self.write("web/pom.xml", "<project></project>\n")
        self.write("web/src/main/java/B.java", "class B {}\n")
        self.write("shared/pom.xml", "<project></project>\n")
        self.write("shared/src/main/java/C.java", "class C {}\n")
        self.write("unrelated/pom.xml", "<project></project>\n")
        result = self.detect()
        self.assertEqual([r["path"] for r in result["subprojects"]], [".", "unrelated"])
        root = result["subprojects"][0]
        self.assertEqual(self.members(root), ["core", "shared", "web"])
        self.assertEqual(root["workspace"]["kind"], "maven")
        self.assertEqual(root["stats"]["java"]["files"], 3)

    def test_gradle_includes(self):
        self.write("settings.gradle.kts", 'rootProject.name = "x"\ninclude(":app", ":libs:core")\ninclude("tools")\n')
        self.write("app/build.gradle.kts", 'plugins { kotlin("jvm") }\n')
        self.write("app/src/main/kotlin/A.kt", "class A\n")
        self.write("libs/core/build.gradle.kts", 'plugins { kotlin("jvm") }\n')
        self.write("libs/core/src/main/kotlin/B.kt", "class B\n")
        self.write("tools/build.gradle.kts", 'plugins { kotlin("jvm") }\n')
        result = self.detect()
        self.assertEqual([r["path"] for r in result["subprojects"]], ["."])
        root = result["subprojects"][0]
        self.assertEqual(self.members(root), ["app", "libs/core", "tools"])
        self.assertEqual(root["workspace"], {"kind": "gradle", "manifest": "settings.gradle.kts"})
        self.assertEqual(root["manifest"], "settings.gradle.kts")
        self.assertEqual(root["languages"], ["kotlin"])

    def test_gradle_groovy_include_forms(self):
        self.write("settings.gradle", "include 'a', 'b'\ninclude ':c'\n")
        for name in "abc":
            self.write("%s/build.gradle" % name, "plugins { id 'java' }\n")
        result = self.detect()
        self.assertEqual(self.members(result["subprojects"][0]), ["a", "b", "c"])

    def test_go_work(self):
        self.write("go.work", "go 1.22\n\nuse (\n\t./api\n\t./lib // shared\n)\nuse ./cmd\n")
        for name in ("api", "lib", "cmd", "other"):
            self.write("%s/go.mod" % name, "module x/%s\n\ngo 1.22\n" % name)
            self.write("%s/main.go" % name, "package main\n")
        result = self.detect()
        self.assertEqual([r["path"] for r in result["subprojects"]], [".", "other"])
        root = result["subprojects"][0]
        self.assertEqual(self.members(root), ["api", "cmd", "lib"])
        self.assertEqual(root["workspace"]["kind"], "go")

    def test_npm_and_pnpm_workspaces_list_members_with_their_own_rows(self):
        self.write("package.json", '{"name": "root", "workspaces": ["packages/*"], "devDependencies": {"x": "1"}}')
        self.write("eslint.config.js", "export default [];\n")
        self.write("packages/a/package.json", '{"name": "a", "scripts": {"test": "vitest run"}, "dependencies": {"r": "1"}}')
        self.write("packages/a/index.ts", "export {};\n")
        self.write("packages/b/package.json", '{"name": "b"}')
        self.write("packages/b/tsconfig.json", '{"compilerOptions": {"strict": true}}')
        result = self.detect()
        root = result["subprojects"][0]
        self.assertEqual([r["path"] for r in result["subprojects"]], ["."])
        self.assertEqual(self.members(root), ["packages/a", "packages/b"])
        self.assertEqual(root["workspace"]["kind"], "npm")
        a = root["members"][0]
        self.assertEqual([r["tool"] for r in a["categories"]["tests"]], ["vitest"])
        self.assertEqual(a["categories"]["lint"][0]["inherited_from"], ".")
        self.assertEqual(a["languages"], ["typescript"])
        self.assertEqual(a["dependencies"]["direct"], 1)
        # the root sees the rows of its members, marked with the member they came from
        rows = [(r["tool"], r.get("member")) for r in root["categories"]["tests"]]
        self.assertEqual(rows, [("vitest", "packages/a")])
        self.assertEqual(root["dependencies"]["direct"], 1)
        self.assertEqual(root["dependencies"]["dev"], 1)

        shutil.rmtree(os.path.join(self.root, "packages"))
        os.remove(os.path.join(self.root, "package.json"))
        self.write("pnpm-workspace.yaml", "packages:\n  - 'apps/*'\n")
        self.write("package.json", '{"name": "root"}')
        self.write("apps/web/package.json", '{"name": "web"}')
        result = self.detect()
        self.assertEqual(result["subprojects"][0]["workspace"]["kind"], "pnpm")
        self.assertEqual(self.members(result["subprojects"][0]), ["apps/web"])

    def test_a_workspace_inside_a_workspace_is_flattened(self):
        self.write("Cargo.toml", '[workspace]\nmembers = ["inner"]\n')
        self.write("inner/Cargo.toml", '[workspace]\nmembers = ["leaf"]\n')
        self.write("inner/leaf/Cargo.toml", '[package]\nname = "leaf"\n')
        result = self.detect()
        self.assertEqual([r["path"] for r in result["subprojects"]], ["."])
        self.assertEqual(self.members(result["subprojects"][0]), ["inner", "inner/leaf"])

    def test_max_subprojects_counts_top_level_subprojects_only(self):
        self.write("Cargo.toml", '[workspace]\nmembers = ["crates/*"]\n')
        for index in range(12):
            self.write("crates/c%02d/Cargo.toml" % index, '[package]\nname = "c"\n')
            self.write("crates/c%02d/src/lib.rs" % index, "pub fn f() {}\n" * 3)
        self.write("py/pyproject.toml", "[project]\nname = 'p'\n")
        self.write("py/a.py", "x = 1\n")
        result = self.detect(max_subprojects=2)
        self.assertEqual([r["path"] for r in result["subprojects"]], [".", "py"])
        self.assertEqual(len(result["subprojects"][0]["members"]), 12)
        self.assertEqual(result["more_subprojects"], [])

    def test_a_folder_that_is_not_a_workspace_has_no_members(self):
        self.write("pyproject.toml", "[project]\nname = 'x'\n")
        self.write("a.py", "x = 1\n")
        record = self.detect()["subprojects"][0]
        self.assertEqual((record["members"], record["workspace"]), ([], None))


if __name__ == "__main__":
    unittest.main()
