"""Tests for how detect.py reads CI files and the commands in them.

Real-shaped CI files are in tests/fixtures/. Each test builds a repository in a
temporary directory.

Run: python -m unittest discover -s plugins/repo-health/tests
"""

import importlib.util
import os
import shutil
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
SCRIPT = os.path.join(os.path.dirname(HERE), "skills", "repo-health", "scripts", "detect.py")

_spec = importlib.util.spec_from_file_location("repo_health_detect_ci", SCRIPT)
detect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detect)

WORKFLOW = ".github/workflows/ci.yml"


class CiFixture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="repo-health-ci-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel, text=""):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(textwrap.dedent(text).lstrip("\n"))

    def fixture(self, name, rel):
        with open(os.path.join(FIXTURES, name)) as handle:
            text = handle.read()
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def detect(self):
        return detect.Detector(self.root, 10).run()

    def steps(self, script, **files):
        """Run detect on a workflow whose one step runs `script`; returns (result, CI file entry)."""
        body = "\n".join("          " + line for line in textwrap.dedent(script).strip("\n").split("\n"))
        self.write(WORKFLOW, "on: pull_request\njobs:\n  a:\n    steps:\n      - run: |\n" + body + "\n")
        for rel, text in files.items():
            self.write(rel, text)
        result = self.detect()
        return result, result["ci"]["files"][0]

    def rows(self, script, **files):
        """{(tool, via): row} of the CI rows for a script."""
        _result, entry = self.steps(script, **files)
        return {(row["tool"], row.get("via")): row for row in entry["tools"]}

    def tools(self, script, **files):
        return sorted({tool for tool, _via in self.rows(script, **files)})


class Bugs(CiFixture):
    def test_maven_batch_mode_runs_tests(self):
        self.fixture("maven-package.yml", WORKFLOW)
        entry = self.detect()["ci"]["files"][0]
        self.assertEqual(sorted(r["tool"] for r in entry["tools"]), ["junit", "kotest", "testng"])
        self.assertEqual(entry["tools"][0]["lines"], [24])
        self.assertEqual(self.tools("mvn -B verify"), ["junit", "kotest", "testng"])

    def test_installing_a_tool_is_not_running_it(self):
        result, entry = self.steps("pip install ruff mypy pytest")
        self.assertEqual(entry["tools"], [])
        self.assertEqual(entry["installs"], [{"line": 6, "command": "pip install ruff mypy pytest",
                                              "manager": "pip", "packages": ["ruff", "mypy", "pytest"]}])

    def test_merge_group_is_a_pull_request_trigger(self):
        self.write(WORKFLOW, "on:\n  merge_group:\njobs:\n  a:\n    steps:\n      - run: pytest\n")
        entry = self.detect()["ci"]["files"][0]
        self.assertIs(entry["pull_request"], True)
        self.assertEqual(entry["events"], ["merge_group"])

    def test_ruff_format_is_not_ruff(self):
        self.assertEqual(self.tools("uvx ruff format --check ."), ["ruff-format"])
        self.assertEqual(self.tools("ruff check ."), ["ruff"])
        self.assertEqual(self.tools("ruff ."), ["ruff"])
        self.assertEqual(self.tools("ruff check . && ruff format --check ."), ["ruff", "ruff-format"])
        self.assertEqual(self.tools("ruff clean"), [])


class SplittingAndWrappers(CiFixture):
    def test_commands_are_split_on_operators_and_continuations(self):
        script = """
            echo start; mypy src && pytest |
              tee out.txt
            ruff \\
              check .
        """
        self.assertEqual(self.tools(script), ["mypy", "pytest", "ruff"])

    def test_assignments_and_wrappers_are_stripped(self):
        self.assertEqual(self.tools("env CI=1 sudo -E time exec pytest -q"), ["pytest"])
        self.assertEqual(self.tools("FOO=1 BAR='a b' mypy ."), ["mypy"])

    def test_quoted_text_and_comments_are_not_commands(self):
        self.assertEqual(self.tools("echo 'run ruff check'\n# mypy src\necho \"a; pytest\""), [])

    def test_command_substitution_is_read(self):
        rows = self.rows('test -z "$(gofmt -l .)"')
        self.assertEqual(list(rows), [("gofmt", None)])
        self.assertNotIn("writes", rows[("gofmt", None)])

    def test_heredoc_body_is_not_a_command(self):
        self.assertEqual(self.tools("cat <<EOF > x.sh\nruff check .\nEOF\nmypy y"), ["mypy"])

    def test_shell_c_is_read(self):
        self.assertEqual(self.tools("bash -c 'ruff check . && mypy src'"), ["mypy", "ruff"])


class Runners(CiFixture):
    def test_runners_are_looked_through(self):
        for command, expected in [
            ("npx --yes -p typescript tsc --noEmit", "tsc"),
            ("npx eslint@8 .", "eslint"),
            ("npx --yes @biomejs/biome lint .", "biome"),
            ("pnpm exec eslint .", "eslint"),
            ("pnpm dlx prettier --check .", "prettier"),
            ("yarn dlx biome lint .", "biome"),
            ("bunx oxlint", "oxlint"),
            ("uvx --from ruff ruff check", "ruff"),
            ("uvx ruff@latest check", "ruff"),
            ("uv run --with x --python 3.12 pytest -q", "pytest"),
            ("poetry run mypy src", "mypy"),
            ("pdm run black --check .", "black"),
            ("pipx run --spec x ruff check", "ruff"),
            ("hatch run pytest", "pytest"),
            ("python3 -m mypy src", "mypy"),
            ("python -W error -m pytest", "pytest"),
            ("go run github.com/golangci/golangci-lint/cmd/golangci-lint@v1.59 run", "golangci-lint"),
            ("go run honnef.co/go/tools/cmd/staticcheck@latest ./...", "staticcheck"),
            ("java -jar checkstyle-10.12.jar -c x.xml src", "checkstyle"),
            ("./node_modules/.bin/eslint .", "eslint"),
        ]:
            self.assertEqual(self.tools(command), [expected], command)

    def test_cargo_subcommands(self):
        self.assertEqual(self.tools("cargo +nightly clippy --all-targets"), ["clippy"])
        self.assertEqual(self.tools("cargo fmt --all -- --check"), ["rustfmt"])
        self.assertEqual(self.tools("cargo nextest run"), ["nextest"])
        self.assertEqual(self.tools("cargo llvm-cov nextest"), ["cargo-llvm-cov", "nextest"])
        self.assertEqual(self.tools("cargo tarpaulin --out Xml"), ["tarpaulin"])
        self.assertEqual(self.tools("cargo deny check && cargo audit && cargo machete && cargo udeps"),
                         ["cargo-audit", "cargo-deny", "cargo-machete", "cargo-udeps"])
        self.assertEqual(self.tools("cargo build --release"), [])

    def test_install_commands_are_not_runs(self):
        for command in ["pip install ruff", "pip3 install -r r.txt", "uv pip install ruff", "uv add ruff",
                        "uv tool install ruff", "pipx install ruff", "npm i eslint", "npm install", "npm ci",
                        "npm add eslint", "pnpm add eslint", "pnpm install", "yarn add eslint", "yarn install",
                        "cargo install cargo-deny", "go install github.com/x/staticcheck@latest",
                        "go get github.com/x/y", "apt-get install -y shellcheck", "brew install pytest",
                        "gem install rubocop", "python -m pip install pytest"]:
            result, entry = self.steps(command)
            self.assertEqual(entry["tools"], [], command)
            self.assertEqual(len(entry["installs"]), 1, command)

    def test_script_name_is_resolved_not_a_flag(self):
        self.write("package.json", '{"scripts": {"lint": "eslint .", "test": "vitest run"}}')
        self.assertEqual(self.tools("npm run lint --silent", **{}), ["eslint"])
        self.assertEqual(self.tools("npm test"), ["vitest"])
        self.assertEqual(self.tools("yarn lint"), ["eslint"])
        self.assertEqual(self.tools("pnpm run test -- --coverage"), ["vitest"])
        self.assertEqual(self.tools("bun run lint"), ["eslint"])

    def test_pre_and_post_scripts_run(self):
        self.write("package.json", '{"scripts": {"pretest": "eslint .", "test": "vitest run"}}')
        self.assertEqual(self.tools("npm test"), ["eslint", "vitest"])

    def test_run_all_scripts(self):
        self.write("package.json", '{"scripts": {"lint:js": "eslint .", "lint:css": "prettier --check .", '
                                   '"lint": "run-p lint:*"}}')
        self.assertEqual(self.tools("npm run lint"), ["eslint", "prettier"])


class WorkspaceRunners(CiFixture):
    FILES = {
        "package.json": '{"name": "root", "workspaces": ["apps/*", "packages/*"]}',
        "apps/web/package.json": '{"name": "web", "scripts": {"test": "vitest run", "lint": "oxlint"}}',
        "packages/ui/package.json": '{"name": "@acme/ui", "scripts": {"lint": "eslint .", "typecheck": "tsc --noEmit"}}',
        "tools/package.json": '{"name": "tools", "scripts": {"lint": "biome lint ."}}',
    }

    def setUp(self):
        super(WorkspaceRunners, self).setUp()
        for rel, text in self.FILES.items():
            self.write(rel, text)

    def test_pnpm_fixture(self):
        self.fixture("pnpm-monorepo.yml", WORKFLOW)
        entry = self.detect()["ci"]["files"][0]
        rows = {(r["tool"], r["via"]) for r in entry["tools"]}
        self.assertEqual(rows, {("vitest", "test"), ("eslint", "lint"), ("oxlint", "lint"), ("tsc", "typecheck")})
        self.assertEqual(entry["installs"][0]["manager"], "pnpm")

    def test_pnpm_filter_names_the_package(self):
        self.assertEqual(self.tools("pnpm --filter web lint"), ["oxlint"])
        self.assertEqual(self.tools("pnpm --filter=@acme/ui lint"), ["eslint"])
        self.assertEqual(self.tools("pnpm -F './packages/*' lint"), ["eslint"])

    def test_recursive_runs_only_workspace_members(self):
        self.assertEqual(self.tools("pnpm -r lint"), ["eslint", "oxlint"])
        self.assertEqual(self.tools("pnpm --recursive run lint"), ["eslint", "oxlint"])
        self.assertEqual(self.tools("npm run lint --workspaces"), ["eslint", "oxlint"])
        self.assertEqual(self.tools("npm run lint -w web"), ["oxlint"])
        self.assertEqual(self.tools("yarn workspaces foreach -A run lint"), ["eslint", "oxlint"])
        self.assertEqual(self.tools("yarn workspaces foreach --include web run lint"), ["oxlint"])
        self.assertEqual(self.tools("yarn workspace web lint"), ["oxlint"])

    def test_turbo_nx_lerna(self):
        self.fixture("turbo.yml", WORKFLOW)
        entry = self.detect()["ci"]["files"][0]
        self.assertEqual({(r["tool"], r["via"]) for r in entry["tools"]},
                         {("eslint", "lint"), ("oxlint", "lint"), ("vitest", "test")})
        self.assertIs(entry["pull_request"], True)
        self.assertEqual(self.tools("turbo lint"), ["eslint", "oxlint"])
        self.assertEqual(self.tools("nx run-many -t lint typecheck"), ["eslint", "oxlint", "tsc"])
        self.assertEqual(self.tools("nx affected --target=typecheck"), ["tsc"])
        self.assertEqual(self.tools("nx run web:test"), ["vitest"])
        self.assertEqual(self.tools("lerna run lint --scope web"), ["eslint", "oxlint"])


class Actions(CiFixture):
    def test_actions_are_matched_by_name_but_a_build_action_is_not_a_test_run(self):
        self.write(WORKFLOW, """
            on: pull_request
            jobs:
              a:
                steps:
                  - uses: github/codeql-action/init@v3
                  - uses: gradle/gradle-build-action@v3
                  - uses: gitleaks/gitleaks-action@v2
                  - uses: actions/checkout@v4
        """)
        rows = {r["tool"] for r in self.detect()["ci"]["files"][0]["tools"]}
        self.assertEqual(rows, {"codeql", "gitleaks"})


class Gradle(CiFixture):
    BUILD = """
        plugins {
            kotlin("jvm") version "2.0.0"
            id("io.gitlab.arturbosch.detekt") version "1.23.0"
            id("com.diffplug.spotless") version "6.25.0"
            jacoco
        }
        tasks.jacocoTestCoverageVerification { violationRules { rule { limit { minimum = "0.8".toBigDecimal() } } } }
    """

    def test_gradle_fixture(self):
        self.fixture("gradle.yml", WORKFLOW)
        self.write("build.gradle.kts", self.BUILD)
        entry = self.detect()["ci"]["files"][0]
        rows = {(r["tool"], r.get("via")) for r in entry["tools"]}
        self.assertEqual(rows, {("junit", None), ("testng", None), ("kotest", None), ("detekt", "gradle check"),
                                ("spotless", "gradle check"), ("jacoco", "gradle check")})
        build = [j for j in entry["jobs"] if j["name"] == "build"][0]
        publish = [j for j in entry["jobs"] if j["name"] == "publish"][0]
        self.assertIs(build["pull_request"], True)
        self.assertIs(publish["pull_request"], False)
        self.assertEqual(publish["rows"], [])  # `-x test` publishes without tests

    def test_task_flags(self):
        self.write("build.gradle.kts", self.BUILD)
        self.assertEqual(self.tools("./gradlew clean test --info"), ["junit", "kotest", "testng"])
        self.assertEqual(self.tools("./gradlew build -x test"), ["detekt", "jacoco", "spotless"])
        self.assertEqual(self.tools("gradle check -x test --no-daemon"), ["detekt", "jacoco", "spotless"])
        self.assertEqual(self.tools("./gradlew :app:test"), ["junit", "kotest", "testng"])
        self.assertEqual(self.tools("./gradlew assemble"), [])

    def test_explicit_tasks_map_to_their_tools(self):
        for command, tool, writes in [("./gradlew detekt", "detekt", False), ("./gradlew ktlintCheck", "ktlint", False),
                                      ("./gradlew spotlessCheck", "spotless", False),
                                      ("./gradlew spotlessApply", "spotless", True),
                                      ("./gradlew jacocoTestCoverageVerification", "jacoco", False),
                                      ("./gradlew koverVerify", "kover", False),
                                      ("./gradlew checkstyleMain", "checkstyle", False)]:
            rows = self.rows(command)
            self.assertEqual(list(rows), [(tool, None)], command)
            self.assertEqual(bool(rows[(tool, None)].get("writes")), writes, command)

    def test_check_without_configured_plugins_runs_tests_only(self):
        self.write("build.gradle", "plugins { id 'java' }\n")
        self.assertEqual(self.tools("./gradlew check"), ["junit", "kotest", "testng"])


class Maven(CiFixture):
    def test_phases_run_tests_unless_skipped(self):
        for phase in ["test", "verify", "install", "package", "deploy"]:
            self.assertEqual(self.tools("mvn -B -ntp %s" % phase), ["junit", "kotest", "testng"], phase)
        self.assertEqual(self.tools("./mvnw -pl app -am verify -T 4"), ["junit", "kotest", "testng"])
        for skip in ["-DskipTests", "-DskipTests=true", "-Dmaven.test.skip=true", "-Dmaven.test.skip"]:
            self.assertEqual(self.tools("mvn verify %s" % skip), [], skip)
        self.assertEqual(self.tools("mvn verify -DskipTests=false"), ["junit", "kotest", "testng"])
        self.assertEqual(self.tools("mvn clean compile"), [])

    def test_plugin_goals_map_to_tools(self):
        self.assertEqual(self.tools("mvn checkstyle:check spotbugs:check pmd:check"),
                         ["checkstyle", "pmd", "spotbugs"])
        self.assertEqual(self.tools("mvn jacoco:report"), ["jacoco"])
        self.assertEqual(self.tools("mvn org.apache.maven.plugins:maven-checkstyle-plugin:check"), ["checkstyle"])
        rows = self.rows("mvn spotless:check")
        self.assertFalse(rows[("spotless", None)].get("writes"))
        rows = self.rows("mvn spotless:apply")
        self.assertTrue(rows[("spotless", None)]["writes"])
        self.assertEqual(self.tools("mvn dependency-check:check"), ["dependency-check"])


class SubCommands(CiFixture):
    def check(self, command, tool, writes):
        rows = self.rows(command)
        self.assertIn((tool, None), rows, command)
        self.assertEqual(bool(rows[(tool, None)].get("writes")), writes, command)

    def test_formatters_check_or_write(self):
        self.check("prettier --check .", "prettier", False)
        self.check("prettier -c .", "prettier", False)
        self.check("prettier --write .", "prettier", True)
        self.check("prettier .", "prettier", True)
        self.check("cargo fmt --check", "rustfmt", False)
        self.check("cargo fmt -- --check", "rustfmt", False)
        self.check("cargo fmt", "rustfmt", True)
        self.check("gofmt -l .", "gofmt", False)
        self.check("gofmt -d .", "gofmt", False)
        self.check("gofmt -w .", "gofmt", True)
        self.check("black --check .", "black", False)
        self.check("black --diff .", "black", False)
        self.check("black .", "black", True)
        self.check("isort --check-only .", "isort", False)
        self.check("isort .", "isort", True)
        self.check("ruff format --check .", "ruff-format", False)
        self.check("ruff format .", "ruff-format", True)
        self.check("dprint check", "dprint", False)
        self.check("dprint fmt", "dprint", True)

    def test_biome_sub_commands(self):
        self.assertEqual(self.tools("biome format ."), ["biome-format"])
        self.assertEqual(self.tools("biome lint ."), ["biome"])
        self.assertEqual(self.tools("biome check ."), ["biome", "biome-format"])
        self.assertEqual(self.tools("biome ci ."), ["biome", "biome-format"])
        self.check("biome format .", "biome-format", False)
        self.check("biome format --write .", "biome-format", True)
        self.check("biome check --write .", "biome-format", True)

    def test_go_sub_commands(self):
        self.assertEqual(self.tools("go test ./..."), ["go-test"])
        self.assertEqual(self.tools("go test -race -cover ./..."), ["go-cover", "go-test"])
        self.assertEqual(self.tools("go test -coverprofile=c.out ./..."), ["go-cover", "go-test"])
        self.assertEqual(self.tools("go vet ./..."), ["go-vet"])
        self.assertEqual(self.tools("go build ./..."), [])


class Coverage(CiFixture):
    def test_js_coverage_is_not_python_coverage(self):
        self.assertEqual(self.tools("npx jest --coverage"), ["jest", "jest-coverage"])
        self.assertEqual(self.tools("npx vitest run --coverage"), ["vitest", "vitest-coverage"])
        self.assertEqual(self.tools("npx vitest run --coverage.enabled"), ["vitest", "vitest-coverage"])
        self.assertEqual(self.tools("jest --coverage=false"), ["jest"])
        self.assertEqual(self.tools("c8 mocha"), ["c8", "mocha"])
        self.assertEqual(self.tools("nyc --reporter=lcov mocha"), ["mocha", "nyc"])
        for tools in (self.tools("npx jest --coverage"), self.tools("vitest run --coverage"), self.tools("c8 npm test")):
            self.assertNotIn("coverage.py", tools)

    def test_python_coverage(self):
        self.assertEqual(self.tools("pytest --cov=app --cov-report=xml"), ["coverage.py", "pytest"])
        self.assertEqual(self.tools("coverage run -m pytest"), ["coverage.py", "pytest"])
        self.assertEqual(self.tools("python -m coverage run --branch -m unittest"), ["coverage.py", "unittest"])
        self.assertEqual(self.tools("coverage report --fail-under=90"), ["coverage.py"])
        self.assertEqual(self.tools("pytest"), ["pytest"])

    def test_config_evidence_for_the_new_rows(self):
        self.write("package.json", '{"name": "x"}')
        self.write("vitest.config.ts", "export default { test: { coverage: { provider: 'v8' } } };\n")
        self.write("jest.config.js", "module.exports = { collectCoverage: true };\n")
        self.write("biome.json", '{"formatter": {"enabled": true}}')
        self.write("src/a.ts", "export {};\n")
        record = self.detect()["subprojects"][0]
        coverage = sorted(r["tool"] for r in record["categories"]["coverage"])
        self.assertEqual(coverage, ["jest-coverage", "vitest-coverage"])
        self.assertIn("biome-format", [r["tool"] for r in record["categories"]["format"]])

    def test_jest_coverage_false_in_config_is_not_evidence(self):
        self.write("package.json", '{"name": "x"}')
        self.write("jest.config.js", "module.exports = { collectCoverage: false };\n")
        self.write("src/a.ts", "export {};\n")
        record = self.detect()["subprojects"][0]
        self.assertEqual(record["categories"]["coverage"], [])


class NonBlocking(CiFixture):
    def test_fixture(self):
        self.fixture("continue-on-error.yml", WORKFLOW)
        entry = self.detect()["ci"]["files"][0]
        checks = {r["tool"]: r for r in [j for j in entry["jobs"] if j["name"] == "checks"][0]["rows"]}
        self.assertTrue(checks["ruff"]["non_blocking"])      # || true
        self.assertTrue(checks["mypy"]["non_blocking"])      # continue-on-error on the step
        self.assertFalse(checks["pytest"]["non_blocking"])
        experimental = {r["tool"]: r for r in [j for j in entry["jobs"] if j["name"] == "experimental"][0]["rows"]}
        self.assertTrue(all(r["non_blocking"] for r in experimental.values()))  # continue-on-error on the job
        merged = {r["tool"]: r for r in entry["tools"]}
        self.assertFalse(merged["pytest"]["non_blocking"])   # one blocking run is enough

    def test_command_forms(self):
        for command in ["pytest || true", "pytest || :", "pytest; true", "pytest; exit 0", "pytest || exit 0",
                        "pytest || echo failed", "pytest && mypy . || true", "ruff check --exit-zero .",
                        "pylint --exit-zero src", "flake8 --exit-zero", "gitleaks detect --exit-code 0",
                        "gitleaks detect --exit-code=0", "npm audit || echo audit failed"]:
            rows = self.rows(command)
            self.assertTrue(all(r["non_blocking"] for r in rows.values()), command)
        for command in ["pytest || exit 1", "pytest; echo done", "pytest && true", "ruff check .",
                        "pytest\ntrue"]:
            rows = self.rows(command)
            self.assertFalse(any(r["non_blocking"] for r in rows.values() if r["tool"] == "pytest" or
                                 r["tool"] == "ruff"), command)

    def test_gitlab_allow_failure(self):
        self.fixture("gitlab-ci.yml", ".gitlab-ci.yml")
        entry = self.detect()["ci"]["files"][0]
        lint = [j for j in entry["jobs"] if j["name"] == "lint"][0]
        self.assertTrue(lint["rows"][0]["non_blocking"])


class Triggers(CiFixture):
    def entries(self):
        return {e["file"]: e for e in self.detect()["ci"]["files"]}

    def test_github_events_and_job_conditions(self):
        self.write(WORKFLOW, """
            on:
              push:
                branches: [main]
              pull_request_target:
            jobs:
              test:
                steps:
                  - run: pytest
              deploy:
                if: github.event_name == 'push'
                steps:
                  - run: mypy src
              not-pr:
                if: github.event_name != 'pull_request'
                steps:
                  - run: ruff check .
              main-only:
                if: github.ref == 'refs/heads/main'
                steps:
                  - run: bandit -r src
              either:
                if: github.event_name == 'push' || github.event_name == 'pull_request'
                steps:
                  - run: pylint src
        """)
        entry = self.entries()[WORKFLOW]
        self.assertEqual(entry["events"], ["push", "pull_request_target"])
        jobs = {j["name"]: j["pull_request"] for j in entry["jobs"]}
        self.assertEqual(jobs, {"test": True, "deploy": False, "not-pr": False, "main-only": False, "either": True})
        self.assertIs(entry["pull_request"], True)

    def test_a_push_only_file_has_no_pull_request_jobs(self):
        self.write(WORKFLOW, "on: [push]\njobs:\n  a:\n    steps:\n      - run: pytest\n")
        entry = self.entries()[WORKFLOW]
        self.assertIs(entry["pull_request"], False)
        self.assertIs(entry["jobs"][0]["pull_request"], False)

    def test_a_step_that_skips_pull_requests(self):
        self.write(WORKFLOW, """
            on: pull_request
            jobs:
              a:
                steps:
                  - run: pytest
                  - if: github.event_name == 'push'
                    run: mypy src
        """)
        rows = {r["tool"]: r for r in self.entries()[WORKFLOW]["tools"]}
        self.assertIs(rows["pytest"]["pull_request"], True)
        self.assertIs(rows["mypy"]["pull_request"], False)

    def test_gitlab_merge_request_rules(self):
        self.fixture("gitlab-ci.yml", ".gitlab-ci.yml")
        entry = self.entries()[".gitlab-ci.yml"]
        self.assertIs(entry["pull_request"], True)
        jobs = {j["name"]: j["pull_request"] for j in entry["jobs"]}
        self.assertEqual(jobs, {"unit-tests": True, "lint": True, "deploy": False})

    def test_gitlab_without_merge_request_rules_is_push_default(self):
        self.write(".gitlab-ci.yml", "test:\n  script:\n    - pytest\n")
        entry = self.entries()[".gitlab-ci.yml"]
        self.assertEqual(entry["pull_request"], "push-default")
        self.assertIn("merge request", entry["trigger_note"])

    def test_gitlab_only_merge_requests(self):
        self.write(".gitlab-ci.yml", "test:\n  script:\n    - pytest\n  only:\n    - merge_requests\n")
        self.assertIs(self.entries()[".gitlab-ci.yml"]["pull_request"], True)

    def test_bitbucket_pull_requests_pipeline(self):
        self.fixture("bitbucket-pipelines.yml", "bitbucket-pipelines.yml")
        entry = self.entries()["bitbucket-pipelines.yml"]
        self.assertIs(entry["pull_request"], True)
        jobs = {j["name"]: j["pull_request"] for j in entry["jobs"]}
        self.assertEqual(jobs, {"default": "push-default", "pull-requests:**": True, "custom:nightly": False})
        self.assertEqual({r["tool"] for r in entry["tools"]}, {"ruff", "pytest", "pip-audit"})

    def test_providers_that_build_pushes_by_default(self):
        self.fixture("circleci-config.yml", ".circleci/config.yml")
        self.write(".travis.yml", "script:\n  - pytest\n")
        self.write("Jenkinsfile", "pipeline { stages { stage('t') { steps { sh 'pytest' } } } }\n")
        self.write("azure-pipelines.yml", "steps:\n  - script: pytest\n")
        self.write(".buildkite/pipeline.yml", "steps:\n  - command: pytest\n")
        entries = self.entries()
        for name in (".circleci/config.yml", ".travis.yml", "Jenkinsfile", "azure-pipelines.yml",
                     ".buildkite/pipeline.yml"):
            self.assertEqual(entries[name]["pull_request"], "push-default", name)
            self.assertTrue(entries[name]["trigger_note"], name)
        self.assertEqual({r["tool"] for r in entries[".circleci/config.yml"]["tools"]}, {"jest", "jest-coverage"})
        for name in (".travis.yml", "Jenkinsfile", "azure-pipelines.yml", ".buildkite/pipeline.yml"):
            self.assertEqual([r["tool"] for r in entries[name]["tools"]], ["pytest"], name)

    def test_jenkins_multiline_sh(self):
        self.write("Jenkinsfile", "pipeline {\n  stages {\n    stage('t') {\n      steps {\n        sh '''\n"
                                  "          ruff check .\n          pytest\n        '''\n      }\n    }\n  }\n}\n")
        rows = {r["tool"]: r["line"] for r in self.entries()["Jenkinsfile"]["tools"]}
        self.assertEqual(rows, {"ruff": 6, "pytest": 7})


class Followed(CiFixture):
    def test_pre_commit_run_follows_the_hooks(self):
        self.fixture("precommit-ci.yml", WORKFLOW)
        self.fixture("pre-commit-config.yaml", ".pre-commit-config.yaml")
        entry = self.detect()["ci"]["files"][0]
        rows = {(r["tool"], r.get("via")) for r in entry["tools"]}
        self.assertEqual(rows, {("pre-commit", None), ("ruff", "pre-commit"), ("ruff-format", "pre-commit"),
                                ("mypy", "pre-commit")})
        ruff = [r for r in entry["tools"] if r["tool"] == "ruff"][0]
        self.assertEqual((ruff["via_file"], ruff["via_line"]), (".pre-commit-config.yaml", 5))

    def test_pre_commit_run_with_a_hook_name(self):
        self.fixture("pre-commit-config.yaml", ".pre-commit-config.yaml")
        rows = self.rows("pre-commit run mypy --all-files")
        self.assertEqual(sorted(t for t, _ in rows), ["mypy", "pre-commit"])
        rows = self.rows("SKIP=mypy pre-commit run --all-files")
        self.assertEqual(sorted(t for t, _ in rows), ["pre-commit", "ruff", "ruff-format"])

    def test_pre_commit_action(self):
        self.fixture("pre-commit-config.yaml", ".pre-commit-config.yaml")
        self.write(WORKFLOW, "on: pull_request\njobs:\n  a:\n    steps:\n      - uses: pre-commit/action@v3.0.1\n")
        rows = {(r["tool"], r.get("via")) for r in self.detect()["ci"]["files"][0]["tools"]}
        self.assertIn(("mypy", "pre-commit"), rows)

    def test_tox_runs_the_commands_of_its_envs(self):
        self.fixture("tox.ini", "tox.ini")
        rows = self.rows("tox -e lint,py311")
        self.assertEqual(set(rows), {("tox", None), ("ruff", "tox:lint"), ("ruff-format", "tox:lint"),
                                     ("pytest", "tox:py311")})
        self.assertEqual((rows[("ruff", "tox:lint")]["via_file"], rows[("ruff", "tox:lint")]["via_line"]), ("tox.ini", 11))
        self.assertFalse(rows[("ruff-format", "tox:lint")].get("writes"))

    def test_tox_without_e_runs_the_envlist(self):
        self.fixture("tox.ini", "tox.ini")
        rows = self.rows("tox")
        self.assertEqual({v for _t, v in rows}, {None, "tox:py39", "tox:py311", "tox:lint", "tox:type"})

    def test_tox_in_pyproject(self):
        self.write("pyproject.toml", '[tool.tox]\nlegacy_tox_ini = """\n[tox]\nenvlist = lint\n[testenv:lint]\n'
                                     'commands = ruff check .\n"""\n')
        rows = self.rows("tox")
        self.assertIn(("ruff", "tox:lint"), rows)
        self.assertEqual(rows[("ruff", "tox:lint")]["via_file"], "pyproject.toml")

    def test_tox_factor_conditions_and_ignored_errors(self):
        self.write("tox.ini", """
            [tox]
            envlist = py39, py311
            [testenv]
            commands =
                py311: mypy src
                -pylint src
                {envpython} -m pytest {posargs}
        """)
        rows = self.rows("tox -e py311")
        self.assertEqual({t for t, _ in rows}, {"tox", "mypy", "pylint", "pytest"})
        self.assertTrue(rows[("pylint", "tox:py311")]["non_blocking"])
        rows = self.rows("tox -e py39")
        self.assertNotIn(("mypy", "tox:py39"), rows)

    def test_nox_reads_session_run_calls_as_text(self):
        self.write("noxfile.py", """
            import nox

            nox.options.sessions = ["lint", "tests"]

            @nox.session
            def lint(session):
                session.install("ruff")
                session.run("ruff", "check", ".")

            @nox.session(python=["3.11", "3.12"])
            def tests(session):
                session.install("-e", ".[test]")
                session.run("python", "-m", "pytest", *session.posargs)

            @nox.session(name="types")
            def mypy_session(session):
                session.run("mypy", "src", env={"A": "b"})

            @nox.session
            def docs(session):
                session.run("sphinx-build", "docs", "out")
        """)
        rows = self.rows("nox")
        self.assertEqual(set(rows), {("nox", None), ("ruff", "nox:lint"), ("pytest", "nox:tests")})
        rows = self.rows("nox -s types")
        self.assertEqual(set(rows), {("nox", None), ("mypy", "nox:types")})
        self.assertEqual(rows[("mypy", "nox:types")]["via_line"], 17)

    def test_nox_file_is_never_executed(self):
        marker = os.path.join(self.root, "ran")
        self.write("noxfile.py", "import os\nopen(%r, 'w').close()\n" % marker)
        self.rows("nox")
        self.assertFalse(os.path.exists(marker))

    def test_shell_scripts_are_followed_to_depth_three(self):
        self.write("scripts/ci.sh", "#!/bin/bash\nset -e\nruff check .\n./scripts/test.sh\n")
        self.write("scripts/test.sh", "#!/bin/sh\npytest\nbash scripts/deep.sh\n")
        self.write("scripts/deep.sh", "mypy src\nsh scripts/deeper.sh\n")
        self.write("scripts/deeper.sh", "bandit -r src\nsh scripts/deepest.sh\n")
        self.write("scripts/deepest.sh", "pylint src\n")
        rows = self.rows("./scripts/ci.sh")
        self.assertEqual({t for t, _ in rows}, {"ruff", "pytest", "mypy"})   # deeper.sh is the fourth file
        self.assertEqual(rows[("ruff", "scripts/ci.sh")]["via_line"], 3)
        self.assertEqual(rows[("pytest", "scripts/test.sh")]["via_line"], 2)
        self.assertEqual(rows[("pytest", "scripts/test.sh")]["lines"], [6])
        rows = self.rows("bash scripts/test.sh")
        self.assertIn(("pytest", "scripts/test.sh"), rows)
        rows = self.rows("sh scripts/deep.sh")
        self.assertIn(("mypy", "scripts/deep.sh"), rows)

    def test_a_script_that_calls_itself_does_not_loop(self):
        self.write("scripts/a.sh", "pytest\n./scripts/a.sh\n")
        self.assertEqual(self.tools("./scripts/a.sh"), ["pytest"])

    def test_scripts_outside_the_repository_or_missing_are_not_read(self):
        self.assertEqual(self.tools("./scripts/missing.sh && ../x/y.sh"), [])

    def test_make_and_just(self):
        self.write("Makefile", "lint:\n\t@ruff check .\n\ncheck: lint\n\t-pytest\n")
        self.write("justfile", "typecheck:\n    mypy src\n")
        rows = self.rows("make check\njust typecheck")
        self.assertEqual(set(rows), {("ruff", "lint"), ("pytest", "check"), ("mypy", "typecheck")})


class MiniYaml(unittest.TestCase):
    def test_structures(self):
        tree = detect.parse_yaml(textwrap.dedent("""\
            # comment
            on:
              push:
                branches: [main, 'dev']
              pull_request:
            env: {A: 1, B: "x y"}
            jobs:
              build:
                steps:
                  - uses: actions/checkout@v4
                  - name: Run
                    run: |
                      echo one
                      echo two
                  - run: echo "a: b" # not a comment kept
                  - name: Folded
                    run: >-
                      echo
                      three
                list:
                - a
                - 'b: c'
                - - nested
            "quoted key": yes
        """))
        self.assertEqual(list(tree["on"]), ["push", "pull_request"])
        self.assertEqual(list(tree["on"]["push"]["branches"]), ["main", "dev"])
        self.assertEqual(dict(tree["env"]), {"A": "1", "B": "x y"})
        steps = tree["jobs"]["build"]["steps"]
        self.assertEqual(steps[0]["uses"], "actions/checkout@v4")
        self.assertEqual(steps[1]["run"], "echo one\necho two")
        self.assertEqual(steps[1]["run"].line, 13)
        self.assertEqual(steps[2]["run"], 'echo "a: b"')
        self.assertEqual(steps[3]["run"], "echo three")
        self.assertEqual(list(tree["jobs"]["build"]["list"][:2]), ["a", "b: c"])
        self.assertEqual(list(tree["jobs"]["build"]["list"][2]), ["nested"])
        self.assertEqual(tree["quoted key"], "yes")

    def test_garbage_does_not_raise(self):
        for text in ["", "{{{", "- - -\n  : :\n\t\t", "a:\n  b:\n c: d\n", "key: [unclosed\n", "- uses: [a\n }  - b",
                     "{a: [b}, c]}", "[}]", "{]: x}"]:
            detect.parse_yaml(text)


class ShellSplitting(unittest.TestCase):
    def words(self, text):
        return [(u.argv, u.swallowed) for u in detect.split_commands(text)]

    def test_operators(self):
        self.assertEqual(self.words("a && b || c; d | e\nf & g"),
                         [(["a"], False), (["b"], False), (["c"], False), (["d"], False), (["e"], False),
                          (["f"], False), (["g"], False)])

    def test_swallowed(self):
        self.assertEqual(self.words("a || true"), [(["a"], True), (["true"], False)])
        self.assertEqual(self.words("a && b || echo no"), [(["a"], True), (["b"], True), (["echo", "no"], False)])
        self.assertEqual(self.words("a; exit 0"), [(["a"], True), (["exit", "0"], False)])
        self.assertEqual(self.words("a\ntrue"), [(["a"], False), (["true"], False)])

    def test_redirections_and_keywords_are_dropped(self):
        self.assertEqual(self.words("if ! a 2>&1 >out.txt; then b; fi"),
                         [(["a"], False), (["b"], False)])
        self.assertEqual(self.words("(cd x && a)"), [(["cd", "x"], False), (["a"], False)])

    def test_line_numbers(self):
        self.assertEqual([u.line for u in detect.split_commands("a\n\nb \\\n  c\nd")], [0, 2, 4])


if __name__ == "__main__":
    unittest.main()
