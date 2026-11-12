"""Tests for the strictness, coverage threshold, locked install and toolchain facts of detect.py.

Run: python -m unittest discover -s plugins/repo-healthcheck/tests
"""

import datetime
import importlib.util
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "skills", "repo-healthcheck", "scripts", "detect.py")

_spec = importlib.util.spec_from_file_location("repo_healthcheck_detect_facts", SCRIPT)
detect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detect)

WORKFLOW = ".github/workflows/ci.yml"


def git(root, *args, **kwargs):
    env = dict(os.environ)
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.com"})
    if kwargs.get("when"):
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = kwargs["when"]
    cmd = ["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false"] + list(args)
    return subprocess.run(cmd, cwd=root, env=env, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).stdout.decode().strip()


class Facts(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="repo-healthcheck-facts-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel, text=""):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(textwrap.dedent(text).lstrip("\n"))

    def detect(self):
        return detect.Detector(self.root, 10).run()

    def workflow(self, script):
        body = "\n".join("          " + line for line in textwrap.dedent(script).strip("\n").split("\n"))
        self.write(WORKFLOW, "on: pull_request\njobs:\n  a:\n    steps:\n      - run: |\n" + body + "\n")

    @staticmethod
    def kinds(result, key="strictness", how=None):
        return sorted((f["kind"], f["file"], f["line"]) for f in result[key] if how is None or f["how"] == how)


class Strictness(Facts):
    def test_mypy(self):
        self.write("pyproject.toml", """
            [tool.mypy]
            python_version = "3.11"
            strict = true
            disallow_untyped_defs = true

            [[tool.mypy.overrides]]
            module = "x.*"
            strict = true
        """)
        self.write("pkg/mypy.ini", "[mypy]\nstrict = True\n\n[mypy-other.*]\ndisallow_untyped_defs = True\n")
        self.write("pkg/setup.cfg", "[mypy]\ndisallow_untyped_defs = yes\n")
        self.write("off/pyproject.toml", "[tool.mypy]\nstrict = false\n")
        self.assertEqual(self.kinds(self.detect()), [
            ("mypy-disallow-untyped-defs", "pkg/setup.cfg", 2), ("mypy-disallow-untyped-defs", "pyproject.toml", 4),
            ("mypy-strict", "pkg/mypy.ini", 2), ("mypy-strict", "pyproject.toml", 3)])

    def test_pyright(self):
        self.write("pyrightconfig.json", '{\n  // comment\n  "typeCheckingMode": "strict",\n  "strict": ["src"]\n}\n')
        self.write("b/pyproject.toml", '[tool.pyright]\ntypeCheckingMode = "strict"\nstrict = ["src"]\n')
        self.write("c/pyproject.toml", '[tool.pyright]\ntypeCheckingMode = "basic"\n')
        self.assertEqual(self.kinds(self.detect()), [
            ("pyright-strict", "b/pyproject.toml", 2), ("pyright-strict", "pyrightconfig.json", 3),
            ("pyright-strict-paths", "b/pyproject.toml", 3), ("pyright-strict-paths", "pyrightconfig.json", 4)])

    def test_tsconfig(self):
        self.write("tsconfig.json", '{\n  "compilerOptions": {"strict": true}\n}\n')
        self.write("web/tsconfig.app.json", '{"compilerOptions": {"strict": false}}')
        self.write("none/tsconfig.json", '{"compilerOptions": {}}')
        facts = [(f["file"], f["value"]) for f in self.detect()["strictness"] if f["kind"] == "tsconfig-strict"]
        self.assertEqual(sorted(facts), [("tsconfig.json", True), ("web/tsconfig.app.json", False)])

    def test_clippy_deny_warnings_in_ci(self):
        for command in ["cargo clippy -- -D warnings", "cargo clippy --all-targets -- -Dwarnings",
                        "cargo clippy -- --deny warnings", "cargo +nightly clippy --workspace -- -D warnings -A x"]:
            self.workflow(command)
            facts = [f for f in self.detect()["strictness"] if f["how"] == "ci"]
            self.assertEqual([f["kind"] for f in facts], ["clippy-deny-warnings"], command)
            self.assertEqual((facts[0]["file"], facts[0]["line"]), (WORKFLOW, 6))
        self.workflow("cargo clippy --all-targets")
        self.assertEqual(self.detect()["strictness"], [])

    def test_rustflags_deny_warnings(self):
        self.workflow("RUSTFLAGS=-Dwarnings cargo test")
        self.assertEqual([f["kind"] for f in self.detect()["strictness"]], ["rustflags-deny-warnings"])
        self.workflow("export RUSTFLAGS='-D warnings'\ncargo build")
        self.assertEqual([f["kind"] for f in self.detect()["strictness"]], ["rustflags-deny-warnings"])
        self.write(WORKFLOW, "on: pull_request\nenv:\n  RUSTFLAGS: -D warnings\njobs:\n  a:\n    steps:\n      - run: cargo test\n")
        facts = self.detect()["strictness"]
        self.assertEqual([(f["kind"], f["line"]) for f in facts], [("rustflags-deny-warnings", 3)])

    def test_go_vet_in_ci(self):
        self.workflow("go vet ./...")
        self.assertEqual([f["kind"] for f in self.detect()["strictness"]], ["go-vet"])

    def test_werror_and_all_warnings_as_errors_are_structured(self):
        self.write("pom.xml", "<project>\n  <compilerArgs><arg>-Werror</arg></compilerArgs>\n</project>\n")
        self.write("app/build.gradle.kts", "kotlin {\n  compilerOptions { allWarningsAsErrors.set(true) }\n}\n")
        self.write("lib/build.gradle", "tasks.withType(JavaCompile) { options.compilerArgs << '-Werror' }\n")
        self.write("off/build.gradle.kts", "kotlin { compilerOptions { allWarningsAsErrors.set(false) } }\n")
        self.assertEqual(self.kinds(self.detect()), [
            ("javac-werror", "lib/build.gradle", 1), ("javac-werror", "pom.xml", 2),
            ("kotlin-all-warnings-as-errors", "app/build.gradle.kts", 2)])

    def test_cargo_lints(self):
        self.write("Cargo.toml", "[workspace.lints.rust]\nwarnings = \"deny\"\n")
        self.assertEqual(self.kinds(self.detect()), [("cargo-lints-deny-warnings", "Cargo.toml", 2)])


class Thresholds(Facts):
    def test_python(self):
        self.write("pyproject.toml", "[tool.coverage.report]\nfail_under = 85\n")
        self.write("a/.coveragerc", "[report]\nfail_under = 70.5\n")
        self.write("b/pytest.ini", "[pytest]\naddopts = --cov=b --cov-fail-under=60\n")
        self.write("c/setup.cfg", "[tool:pytest]\naddopts = --cov-fail-under 50\n")
        facts = {(f["kind"], f["file"]): f["value"] for f in self.detect()["coverage_thresholds"]}
        self.assertEqual(facts, {("fail_under", "pyproject.toml"): "85", ("fail_under", "a/.coveragerc"): "70.5",
                                 ("cov-fail-under", "b/pytest.ini"): "60", ("cov-fail-under", "c/setup.cfg"): "50"})

    def test_python_in_ci_and_scripts(self):
        self.workflow("pytest --cov=app --cov-fail-under=80\ncoverage report --fail-under=75")
        self.write("Makefile", "cov:\n\tpytest --cov --cov-fail-under 90\n")
        facts = sorted((f["kind"], f["how"], f["file"], f["line"], f["value"])
                       for f in self.detect()["coverage_thresholds"])
        self.assertEqual(facts, [("cov-fail-under", "ci", WORKFLOW, 6, "80"),
                                 ("cov-fail-under", "script", "Makefile", 2, "90"),
                                 ("fail_under", "ci", WORKFLOW, 7, "75")])

    def test_jvm(self):
        self.write("pom.xml", "<project><plugin><artifactId>jacoco-maven-plugin</artifactId>\n"
                              "<limit><minimum>0.80</minimum></limit></plugin></project>\n")
        self.write("app/build.gradle.kts", "plugins { jacoco }\njacocoTestCoverageVerification {\n"
                                           "  violationRules { rule { limit { minimum = 0.8.toBigDecimal() } } }\n}\n")
        self.write("k/build.gradle.kts", "plugins { id(\"org.jetbrains.kotlinx.kover\") }\n"
                                         "kover { verify { rule { minBound(70) } } }\n")
        self.write("none/build.gradle.kts", "plugins { jacoco }\n")
        facts = {(f["kind"], f["file"], f["line"]) for f in self.detect()["coverage_thresholds"]}
        self.assertEqual(facts, {("jacoco-violation-rules", "pom.xml", 2),
                                 ("jacoco-violation-rules", "app/build.gradle.kts", 3),
                                 ("kover-min-bound", "k/build.gradle.kts", 2)})

    def test_typescript(self):
        self.write("vitest.config.ts", "export default {\n  test: { coverage: { thresholds: { lines: 80 } } },\n};\n")
        self.write("web/jest.config.js", "module.exports = {\n  coverageThreshold: { global: { lines: 80 } },\n};\n")
        self.write("pkg/package.json", '{"name": "x", "jest": {"coverageThreshold": {"global": {"lines": 1}}}}')
        self.write("plain/vitest.config.ts", "export default { test: { coverage: {} } };\n")
        facts = {(f["kind"], f["file"]) for f in self.detect()["coverage_thresholds"]}
        self.assertEqual(facts, {("vitest-thresholds", "vitest.config.ts"),
                                 ("jest-coverage-threshold", "web/jest.config.js"),
                                 ("jest-coverage-threshold", "pkg/package.json")})

    def test_codecov_patch_target(self):
        self.write("codecov.yml", """
            coverage:
              status:
                project:
                  default:
                    target: 80%
                patch:
                  default:
                    target: 90%
        """)
        facts = [(f["kind"], f["value"], f["line"]) for f in self.detect()["coverage_thresholds"]]
        self.assertEqual(facts, [("codecov-patch-target", "90%", 8)])
        self.write("codecov.yml", "coverage:\n  status:\n    project:\n      default:\n        target: 80%\n")
        self.assertEqual(self.detect()["coverage_thresholds"], [])


class LockedInstalls(Facts):
    def locked(self, script, **files):
        self.workflow(script)
        for rel, text in files.items():
            self.write(rel, text)
        return [l["kind"] for l in self.detect()["ci"]["locked_installs"]]

    def test_locked_forms(self):
        for command, kind in [("npm ci", "npm ci"), ("pnpm install --frozen-lockfile", "pnpm install --frozen-lockfile"),
                              ("pnpm i --frozen-lockfile", "pnpm install --frozen-lockfile"),
                              ("yarn install --immutable", "yarn install --immutable"),
                              ("yarn install --frozen-lockfile", "yarn install --immutable"),
                              ("uv sync --locked", "uv sync --locked"), ("uv sync --frozen", "uv sync --locked"),
                              ("poetry install --sync", "poetry install --sync"),
                              ("cargo build --locked", "cargo --locked"), ("cargo test --locked --workspace", "cargo --locked"),
                              ("go mod verify", "go mod verify"), ("go build -mod=readonly ./...", "go -mod=readonly"),
                              ("GOFLAGS=-mod=readonly go test ./...", "go -mod=readonly")]:
            self.assertEqual(self.locked(command), [kind], command)

    def test_unlocked_forms(self):
        for command in ["npm install", "pnpm install", "yarn install", "yarn", "uv sync", "poetry install",
                        "cargo build", "cargo test", "pip install -r requirements.txt", "go build ./..."]:
            self.assertEqual(self.locked(command), [], command)

    def test_poetry_install_with_a_lock_check(self):
        self.assertEqual(self.locked("poetry check --lock\npoetry install"), ["poetry install + poetry check --lock"])
        self.assertEqual(self.locked("poetry lock --check\npoetry install"), ["poetry install + poetry check --lock"])
        self.assertEqual(self.locked("poetry check --lock"), [])

    def test_pip_install_of_a_pinned_file(self):
        pinned = "requests==2.31.0\nclick==8.1.7 \\\n    --hash=sha256:abc\n# c\n-r other.txt\n"
        self.assertEqual(self.locked("pip install -r requirements.txt", **{"requirements.txt": pinned}),
                         ["pip install -r pinned"])
        self.assertEqual(self.locked("pip install --no-deps -r ./requirements.txt",
                                     **{"requirements.txt": pinned}), ["pip install -r pinned"])
        self.assertEqual(self.locked("pip install -r requirements.txt", **{"requirements.txt": "requests>=2\n"}), [])
        self.assertEqual(self.locked("pip install -r requirements.txt",
                                     **{"requirements.txt": "requests==2\nclick\n"}), [])
        self.assertEqual(self.locked("pip install -r requirements.txt", **{"requirements.txt": "-e .\nx==1\n"}), [])
        self.assertEqual(self.locked("pip install -r requirements.txt ruff", **{"requirements.txt": pinned}), [])
        self.assertEqual(self.locked("pip install -r missing.txt"), [])

    def test_locked_installs_carry_file_line_and_command(self):
        self.workflow("echo x\nnpm ci")
        lock = self.detect()["ci"]["locked_installs"][0]
        self.assertEqual((lock["file"], lock["line"], lock["command"]), (WORKFLOW, 7, "npm ci"))


class ToolchainPins(Facts):
    def pins(self):
        return {(p["kind"], p["file"]): p.get("value") for p in self.detect()["setup"]["toolchain_pins"]}

    def test_node_pins(self):
        self.write("package.json", '{\n "name": "x",\n "packageManager": "pnpm@9.1.0",\n'
                                   ' "engines": {"node": ">=20"},\n "volta": {"node": "20.11.0"}\n}\n')
        self.write(".node-version", "20.11.0\n")
        self.write(".nvmrc", "# comment\nv20\n")
        pins = self.pins()
        self.assertEqual(pins[("package.json packageManager", "package.json")], "pnpm@9.1.0")
        self.assertEqual(pins[("package.json engines", "package.json")], ">=20")
        self.assertEqual(pins[("package.json volta", "package.json")], "20.11.0")
        self.assertEqual(pins[(".node-version", ".node-version")], "20.11.0")
        self.assertEqual(pins[(".nvmrc", ".nvmrc")], "v20")
        lines = {p["kind"]: p["line"] for p in self.detect()["setup"]["toolchain_pins"] if p["file"] == "package.json"}
        self.assertEqual(lines, {"package.json packageManager": 3, "package.json engines": 4, "package.json volta": 5})

    def test_package_manager_alone_is_a_pin(self):
        self.write("package.json", '{"name": "x", "packageManager": "pnpm@9"}')
        self.assertEqual(self.pins(), {("package.json packageManager", "package.json"): "pnpm@9"})

    def test_python_pins(self):
        self.write("pyproject.toml", '[project]\nrequires-python = ">=3.9"\n')
        self.write(".python-version", "3.12\n")
        self.assertEqual(self.pins(), {("requires-python", "pyproject.toml"): ">=3.9",
                                       (".python-version", ".python-version"): "3.12"})

    def test_rust_go_and_jvm_pins(self):
        self.write("Cargo.toml", '[package]\nname = "x"\nrust-version = "1.75"\n')
        self.write("rust-toolchain.toml", '[toolchain]\nchannel = "1.78.0"\n')
        self.write("go.mod", "module x\n\ngo 1.22\n\ntoolchain go1.22.3\n")
        self.write("build.gradle.kts", "kotlin {\n    jvmToolchain(17)\n}\n")
        self.write("lib/build.gradle", "java {\n  toolchain {\n    languageVersion = JavaLanguageVersion.of(21)\n  }\n}\n")
        self.write("gradle/wrapper/gradle-wrapper.properties", "distributionUrl=x\n")
        self.write(".mvn/wrapper/maven-wrapper.properties", "distributionUrl=x\n")
        self.write(".java-version", "21\n")
        self.write(".sdkmanrc", "java=21.0.1-tem\n")
        self.write(".tool-versions", "nodejs 20.11.0\n")
        self.write("mise.toml", "[tools]\nnode = '20'\n")
        pins = self.pins()
        self.assertEqual(pins[("rust-version", "Cargo.toml")], "1.75")
        self.assertEqual(pins[("rust-toolchain.toml", "rust-toolchain.toml")], "1.78.0")
        self.assertEqual(pins[("go directive", "go.mod")], "1.22")
        self.assertEqual(pins[("go toolchain", "go.mod")], "go1.22.3")
        self.assertEqual(pins[("java.toolchain", "build.gradle.kts")], "17")
        self.assertEqual(pins[("java.toolchain", "lib/build.gradle")], "21")
        for key in [("gradle-wrapper.properties", "gradle/wrapper/gradle-wrapper.properties"),
                    ("maven-wrapper.properties", ".mvn/wrapper/maven-wrapper.properties"),
                    (".java-version", ".java-version"), (".sdkmanrc", ".sdkmanrc"),
                    (".tool-versions", ".tool-versions"), ("mise.toml", "mise.toml")]:
            self.assertIn(key, pins)


class LockfileAge(Facts):
    def test_last_commit_of_each_lockfile(self):
        git(self.root, "init", "-q")
        self.write("package-lock.json", "{}")
        git(self.root, "add", "package-lock.json")
        git(self.root, "commit", "-q", "-m", "a", when="2024-03-01T12:00:00 +0000")
        self.write("uv.lock", "version = 1\n")
        git(self.root, "add", "uv.lock")
        git(self.root, "commit", "-q", "-m", "b", when="2025-06-15T08:30:00 +0000")
        self.write("package-lock.json", '{"a": 1}')
        self.write("Cargo.lock", "")
        locks = {l["file"]: l["last_commit"] for l in self.detect()["setup"]["lockfiles"]}
        self.assertTrue(locks["package-lock.json"].startswith("2024-03-01T12:00:00"))
        self.assertTrue(locks["uv.lock"].startswith("2025-06-15T08:30:00"))
        self.assertIsNone(locks["Cargo.lock"])   # not committed

    def test_no_git_gives_none(self):
        self.write("uv.lock", "")
        self.assertIsNone(self.detect()["setup"]["lockfiles"][0]["last_commit"])

    def test_at_most_twenty_lockfiles_are_dated(self):
        git(self.root, "init", "-q")
        for index in range(23):
            self.write("p%02d/package-lock.json" % index, "{}")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "all")
        dated = [l for l in self.detect()["setup"]["lockfiles"] if l["last_commit"]]
        self.assertEqual(len(dated), 20)

    def test_subfolder_lockfile_uses_the_git_root_path(self):
        git(self.root, "init", "-q")
        self.write("svc/uv.lock", "version = 1\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "x", when="2025-01-02T03:04:05 +0000")
        result = detect.Detector(os.path.join(self.root, "svc"), 10).run()
        self.assertTrue(result["setup"]["lockfiles"][0]["last_commit"].startswith("2025-01-02T03:04:05"))


if __name__ == "__main__":
    unittest.main()
