"""Tests for the README command checks (docs.commands) of detect.py.

Run: python -m unittest discover -s plugins/repo-health/tests
"""

import importlib.util
import os
import shutil
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "skills", "repo-health", "scripts", "detect.py")

_spec = importlib.util.spec_from_file_location("repo_health_detect_readme", SCRIPT)
detect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detect)

FENCE = "```"


class ReadmeCommands(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="repo-health-readme-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.write("package.json", '{"scripts": {"dev": "vite", "lint": "eslint .", "test": "vitest"}}')
        self.write("web/package.json", '{"name": "web", "scripts": {"dev": "vite", "build": "vite build"}}')
        self.write("Makefile", "build:\n\techo\n\nserve:\n\techo\n")
        self.write("justfile", "serve:\n    echo\n")
        self.write("scripts/setup.sh", "#!/bin/sh\n")
        self.write("demo/__init__.py", "")
        self.write("demo/cli.py", "")
        self.write("pyproject.toml", '[project]\nname = "demo"\n')
        self.write("requirements.txt", "a==1\n")
        self.write("docker-compose.yml", "x: 1\n")
        self.write("Cargo.toml", "[package]\n")
        self.write("gradlew", "")

    def write(self, rel, text=""):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(textwrap.dedent(text).lstrip("\n"))

    def commands(self, readme):
        self.write("README.md", readme)
        docs = detect.Detector(self.root, 10).run()["docs"]
        return {c["command"]: c for c in docs["commands"]}

    def block(self, body, language="sh"):
        return "# Demo\n\n%s%s\n%s\n%s\n" % (FENCE, language, textwrap.dedent(body).strip("\n"), FENCE)

    def expect(self, commands, command, kind, check):
        self.assertIn(command, commands)
        self.assertEqual((commands[command]["kind"], commands[command]["check"]), (kind, check), commands[command])

    def test_record_shape_and_lines(self):
        found = self.commands(self.block("npm ci\n# comment\nnpm run dev\n")) 
        records = list(found.values())
        self.assertEqual([r["line"] for r in records], [4, 6])
        self.assertEqual(set(records[0]), {"line", "command", "kind", "check", "why"})
        self.assertTrue(all(r["why"] for r in records))

    def test_package_scripts(self):
        found = self.commands(self.block("npm run dev\nnpm run nope\nnpm test\nyarn lint\nyarn dev\npnpm run lint\n"
                                         "bun run build\nnpm start\nnpm ci\nnpm install\n"))
        self.expect(found, "npm run dev", "run", "ok")
        self.expect(found, "npm run nope", "other", "missing")
        self.expect(found, "npm test", "test", "ok")
        self.expect(found, "yarn lint", "lint", "ok")
        self.expect(found, "pnpm run lint", "lint", "ok")
        self.expect(found, "bun run build", "build", "missing")
        self.expect(found, "npm start", "run", "missing")
        self.expect(found, "npm ci", "install", "unknown")
        self.assertIn("nope", found["npm run nope"]["why"])

    def test_unknown_yarn_name_may_be_a_binary(self):
        found = self.commands(self.block("yarn tsc --noEmit\n"))
        self.expect(found, "yarn tsc --noEmit", "other", "unknown")

    def test_the_right_package_json_after_cd(self):
        found = self.commands(self.block("cd web && npm run build\n") + "\n" + self.block("cd web\nnpm run lint\n"))
        self.expect(found, "npm run build", "build", "ok")
        self.expect(found, "npm run lint", "lint", "missing")

    def test_no_package_json_is_missing(self):
        os.remove(os.path.join(self.root, "package.json"))
        found = self.commands(self.block("npm run dev\n"))
        self.expect(found, "npm run dev", "run", "missing")

    def test_make_and_just(self):
        found = self.commands(self.block("make build\nmake nothing\nmake\nmake -C web build\njust serve\njust nope\n"))
        self.expect(found, "make build", "build", "ok")
        self.expect(found, "make nothing", "other", "missing")
        self.expect(found, "make", "run", "ok")
        self.expect(found, "make -C web build", "build", "missing")
        self.expect(found, "just serve", "run", "ok")
        self.expect(found, "just nope", "other", "missing")

    def test_make_target_from_an_include_is_unknown(self):
        self.write("Makefile", "include common.mk\n\nbuild:\n\techo\n")
        found = self.commands(self.block("make lint\n"))
        self.expect(found, "make lint", "lint", "unknown")

    def test_paths(self):
        found = self.commands(self.block("./scripts/setup.sh\nbash scripts/missing.sh\nsh ./scripts/setup.sh\n"
                                         "docker compose -f docker-compose.yml up\n"
                                         "docker compose -f docker-compose.prod.yml up\n"
                                         "pip install -r requirements.txt\npip install -r nothere.txt\n"
                                         "./gradlew test\n./mvnw verify\npython scripts/run.py\n"
                                         "pytest tests/test_a.py\npytest -o cache_dir=x tests\n"))
        self.expect(found, "./scripts/setup.sh", "other", "ok")
        self.expect(found, "bash scripts/missing.sh", "other", "missing")
        self.expect(found, "sh ./scripts/setup.sh", "other", "ok")
        self.expect(found, "docker compose -f docker-compose.yml up", "run", "ok")
        self.expect(found, "docker compose -f docker-compose.prod.yml up", "run", "missing")
        self.expect(found, "pip install -r requirements.txt", "install", "ok")
        self.expect(found, "pip install -r nothere.txt", "install", "missing")
        self.expect(found, "./gradlew test", "test", "ok")
        self.expect(found, "./mvnw verify", "test", "missing")
        self.expect(found, "python scripts/run.py", "run", "missing")
        self.expect(found, "pytest tests/test_a.py", "test", "missing")
        self.assertIn("scripts/missing.sh", found["bash scripts/missing.sh"]["why"])

    def test_python_modules(self):
        found = self.commands(self.block("python -m demo.cli\npython3 -m demo.nothere\npython -m http.server 8000\n"
                                         "python -m pytest\npython -m other_tool\n"))
        self.expect(found, "python -m demo.cli", "run", "ok")
        self.expect(found, "python3 -m demo.nothere", "run", "missing")
        self.expect(found, "python -m http.server 8000", "run", "ok")
        self.expect(found, "python -m pytest", "test", "unknown")
        self.expect(found, "python -m other_tool", "run", "unknown")

    def test_cargo_go_maven_gradle_subcommands(self):
        found = self.commands(self.block("cargo test\ncargo nextest run\ncargo tset\ncargo frobnicate\ngo build ./...\n"
                                         "go foo\nmvn verify\nmvn builld\nmvn checkstyle:check\n"
                                         "./gradlew build\n./gradlew mystery\n"))
        self.expect(found, "cargo test", "test", "ok")
        self.expect(found, "cargo nextest run", "test", "ok")
        self.expect(found, "cargo tset", "other", "missing")
        self.assertIn("test", found["cargo tset"]["why"])
        self.expect(found, "cargo frobnicate", "other", "unknown")
        self.expect(found, "go build ./...", "build", "ok")
        self.expect(found, "go foo", "other", "missing")
        self.expect(found, "mvn verify", "test", "ok")
        self.expect(found, "mvn builld", "other", "missing")
        self.expect(found, "mvn checkstyle:check", "lint", "unknown")
        self.expect(found, "./gradlew build", "build", "ok")
        self.expect(found, "./gradlew mystery", "other", "unknown")

    def test_kinds(self):
        found = self.commands(self.block("pytest\nruff check .\nnpx prettier --check .\npip install x\nuv sync\n"
                                         "poetry install\ncargo build\ncargo clippy\ngo test ./...\nmake test\n"
                                         "npm run build\nnpm run start\nnode server.js\npython app.py\n"
                                         "docker compose up\n"))
        for command, kind in [("pytest", "test"), ("ruff check .", "lint"), ("npx prettier --check .", "lint"),
                              ("pip install x", "install"), ("uv sync", "install"), ("poetry install", "install"),
                              ("cargo build", "build"), ("cargo clippy", "lint"), ("go test ./...", "test"),
                              ("make test", "test"), ("npm run build", "build"), ("npm run start", "run"),
                              ("node server.js", "run"), ("python app.py", "run"), ("docker compose up", "run")]:
            self.assertEqual(found[command]["kind"], kind, command)

    def test_which_blocks_are_read(self):
        readme = "\n".join([
            "# Demo", "",
            FENCE + "console", "$ pytest", "collected 3 items", "$ npm run lint", FENCE, "",
            FENCE, "$ make build", "npm test", "some prose", FENCE, "",
            FENCE + "json", '{"scripts": "npm run nope"}', FENCE, "",
            FENCE + "python", "npm run nope2", FENCE, "",
            "Run `pytest` to test and `npm run dev` to start; `make` builds, `foo bar` is not a command, ",
            "`inline_function()` is not either, and `cargo` alone is not enough.", ""])
        found = self.commands(readme)
        self.assertEqual(sorted(found), ["make", "make build", "npm run dev", "npm run lint", "npm test", "pytest"])

    def test_untagged_block_lines_need_a_prompt_or_a_known_program(self):
        found = self.commands("# Demo\n\n" + FENCE + "\nSome text here\n$ npm run dev\nfoo --bar\nnpm test\n" + FENCE + "\n")
        self.assertEqual(sorted(found), ["npm run dev", "npm test"])

    def test_continuation_comments_and_heredocs(self):
        found = self.commands(self.block("pip install \\\n  -r requirements.txt  # deps\ncat <<EOF\nnpm run nope\nEOF\n"
                                         "npm run dev\n"))
        self.assertEqual(sorted(found), ["npm run dev", "pip install -r requirements.txt"])
        self.assertEqual(found["pip install -r requirements.txt"]["line"], 4)

    def test_chained_commands_are_separate_records(self):
        found = self.commands(self.block("npm ci && npm run build || true\n"))
        self.assertEqual(sorted(found), ["npm ci", "npm run build"])

    def test_placeholders_and_unknown_programs_are_not_checked(self):
        found = self.commands(self.block("npm run <script>\nmake ...\ncurl -fsSL https://x.io/install.sh | sh\n"
                                         "git clone https://github.com/a/b\nsudo apt-get install -y libfoo\n"))
        self.assertNotIn("npm run <script>", found)
        self.assertNotIn("make ...", found)
        self.expect(found, "curl -fsSL https://x.io/install.sh", "other", "unknown")
        self.expect(found, "git clone https://github.com/a/b", "other", "unknown")
        self.expect(found, "sudo apt-get install -y libfoo", "install", "unknown")

    def test_heading_facts_are_kept(self):
        self.write("README.md", "# Demo\n\n## Installation\n\n## Usage\n")
        docs = detect.Detector(self.root, 10).run()["docs"]
        self.assertEqual(docs["install"]["via"], "heading")
        self.assertEqual(docs["commands"], [])

    def test_no_readme_has_no_commands(self):
        docs = detect.Detector(self.root, 10).run()["docs"]
        self.assertEqual((docs["readme"], docs["commands"]), (None, []))

    def test_workspace_filter_checks_the_members(self):
        self.write("package.json", '{"name": "root", "workspaces": ["web"]}')
        found = self.commands(self.block("pnpm --filter web build\npnpm -r dev\npnpm --filter web nope\n"))
        self.expect(found, "pnpm --filter web build", "build", "ok")
        self.expect(found, "pnpm -r dev", "run", "ok")
        self.expect(found, "pnpm --filter web nope", "other", "unknown")


if __name__ == "__main__":
    unittest.main()
