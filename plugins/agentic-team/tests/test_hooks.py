"""Tests for scripts/hooks/layered.py and scripts/hooks/compact.py. Run: "$PY" plugins/agentic-team/tests/run_parallel.py"""

import base64
import importlib.util
import io
import json
import os
import shlex
import stat
import subprocess
import sys
import time
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(os.path.dirname(HERE), "scripts", "hooks")


def load(name):
    spec = importlib.util.spec_from_file_location(f"hook_{name}", os.path.join(HOOKS, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


layered, compact = load("layered"), load("compact")

NOTICE = "[agentic-team hook: the full output is saved to "
COMMANDS = ["make test*", "pytest", "vitest", "pnpm test*", "playwright", "gh run view --log", "docker logs"]

PYTEST_PASS = "\n".join(
    [f"tests/test_mod.py::test_case_{i} PASSED" for i in range(60)]
    + ["", "============================= 60 passed in 1.20s =============================", ""])
PYTEST_FAIL = "\n".join(
    [f"tests/test_mod.py::test_case_{i} PASSED" for i in range(40)]
    + ["=================================== FAILURES ===================================",
       "______________________________ test_total_is_right ______________________________",
       "    def test_total_is_right():",
       ">       assert total([1, 2]) == 4",
       "E       assert 3 == 4",
       "E        +  where 3 = total([1, 2])",
       "",
       "tests/test_mod.py:41: AssertionError",
       "=========================== short test summary info ============================",
       "FAILED tests/test_mod.py::test_total_is_right - assert 3 == 4",
       "========================= 1 failed, 40 passed in 0.31s =========================", ""])
VITEST_FAIL = "\n".join(
    [" ✓ src/a.test.ts (3 tests) 4ms"] * 30
    + [" ❯ src/cart.test.ts (2 tests | 1 failed) 7ms",
       "   × cart > adds the tax 3ms",
       " FAIL  src/cart.test.ts > cart > adds the tax",
       "AssertionError: expected 110 to be 120 // Object.is equality",
       " ❯ src/cart.test.ts:12:21",
       " Test Files  1 failed | 1 passed (2)",
       "      Tests  1 failed | 4 passed (5)", ""])
PLAYWRIGHT_FAIL = "\n".join(
    ["  ✓  1 [chromium] › e2e/home.spec.ts:3:1 › home loads (1.1s)"] * 30
    + ["  1) [chromium] › e2e/cart.spec.ts:10:5 › checkout shows the total ──────────",
       "    Error: expect(received).toHaveText(expected)",
       "    Expected string: \"$12\"",
       "    Received string: \"$10\"",
       "      at e2e/cart.spec.ts:14:35",
       "  1 failed",
       "    [chromium] › e2e/cart.spec.ts:10:5 › checkout shows the total",
       "  30 passed (9.0s)", ""])


def config(directory, **over):
    cfg = {"layered": True, "compact_pins": True, "summarize_fallback": False, "passthrough_chars": 200, "large_chars": 1000,
           "commands": COMMANDS, "saved_dir": os.path.join(directory, "out"), "config_file": os.path.join(directory, "cfg.json")}
    cfg.update(over)
    with open(cfg["config_file"], "w") as fh:
        json.dump(cfg, fh)
    return cfg


class Layered(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.realpath(self._tmp.name)
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        self.addCleanup(self._tmp.cleanup)

    def tool(self, name, output, code):
        """An executable `name` that prints `output` and exits with `code`."""
        with open(os.path.join(self.bin, name), "w") as fh:
            fh.write(f"#!/bin/sh\ncat <<'END'\n{output}\nEND\nexit {code}\n")
        os.chmod(os.path.join(self.bin, name), 0o755)

    def wrapped(self, cmd, cfg=None):
        return layered.wrap(cmd, cfg or config(self.dir), "toolu_01")

    def run_wrapped(self, cmd, **over):
        """What the session sees when the Bash tool runs `cmd` with the hook's rewrite: (stdout, exit code)."""
        cfg = config(self.dir, **over)
        wrapped = layered.wrap(cmd, cfg, "toolu_01")
        self.assertIsNotNone(wrapped, cmd)
        os.makedirs(cfg["saved_dir"], exist_ok=True)
        done = subprocess.run(["bash", "-c", wrapped], capture_output=True, text=True, cwd=self.dir,
                              env=dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"]))
        return done.stdout, done.returncode

    # --- what is wrapped

    def test_unmatched_commands_are_not_touched(self):
        for cmd in ("git diff", "cat pytest.ini", "ls -l", "make build", "echo pytest", "sed -n 1,5p vitest.config.ts"):
            self.assertIsNone(self.wrapped(cmd), cmd)

    def test_matched_commands_are_wrapped(self):
        for cmd in ("pytest", "pytest -x tests/", "make test", "make test-unit FOO=1", "pnpm test --run", "vitest run",
                    "playwright test", "gh run view 123 --log", "docker logs web", "pytest tests/ 2>&1"):
            self.assertIsNotNone(self.wrapped(cmd), cmd)

    def test_prefix_and_glob_patterns(self):
        cfg = config(self.dir, commands=["cargo test", "just *-test*"])
        self.assertIsNotNone(self.wrapped("cargo test -p core", cfg))
        self.assertIsNone(self.wrapped("cargo testing", cfg))
        self.assertIsNotNone(self.wrapped("just unit-test fast", cfg))
        self.assertIsNone(self.wrapped("just build", cfg))

    def test_prefixes_cd_assignments_and_wrapper_words_are_looked_through(self):
        for cmd in ("cd app && pytest", "cd app; pytest -x", "FOO=1 BAR=2 pytest", "export A=1 && make test",
                    "scripts/with-slot.sh make test", "cd x && FOO=1 scripts/with-slot.sh pytest -q", "env CI=1 pytest",
                    "time pytest", "cd a\npytest"):
            self.assertIsNotNone(self.wrapped(cmd), cmd)

    def test_piped_and_compound_commands_that_are_not_safe_are_not_wrapped(self):
        for cmd in ("pytest | tail -5", "pytest 2>&1 | tee log", "pytest || true", "pytest && echo done", "pytest; echo $?",
                    "pytest & wait", "pytest > out.txt", "pytest < in", "(cd a && pytest)", "{ pytest; }", "pytest $(echo -x)",
                    "pytest `echo -x`", "pytest # note", "pytest <<EOF\nx\nEOF", "pytest \\", "echo a && pytest && make lint",
                    "make test; exit 1", "pytest 'unclosed", "! pytest"):
            self.assertIsNone(self.wrapped(cmd), cmd)

    def test_a_flag_only_pattern_matches_nothing(self):
        self.assertIsNone(self.wrapped("ls --log", config(self.dir, commands=["--log"])))

    def test_quoted_operators_do_not_split(self):
        self.assertIsNotNone(self.wrapped("pytest -k 'a|b and c' tests/"))
        self.assertIsNotNone(self.wrapped('pytest -k "a && b;c"'))

    # --- the pre hook

    def pre(self, data, cfg=None):
        cfg = cfg or config(self.dir)
        out = io.StringIO()
        with unittest.mock.patch("sys.stdin", io.StringIO(data if isinstance(data, str) else json.dumps(data))), \
                unittest.mock.patch("sys.stdout", out):
            code = layered.main(["pre", "--config", cfg["config_file"]])
        return code, out.getvalue()

    def test_pre_rewrites_a_matching_bash_command_and_keeps_the_other_fields(self):
        code, out = self.pre({"tool_name": "Bash", "tool_use_id": "toolu_9", "tool_input": {
            "command": "pytest -x", "description": "run", "timeout": 5000}})
        update = json.loads(out)["hookSpecificOutput"]
        self.assertEqual((code, update["hookEventName"]), (0, "PreToolUse"))
        self.assertEqual({k: v for k, v in update["updatedInput"].items() if k != "command"},
                         {"description": "run", "timeout": 5000})
        self.assertIn("pytest -x", update["updatedInput"]["command"])
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "out")))

    def test_pre_leaves_other_tools_background_runs_and_disabled_layering_alone(self):
        off = dict(layered=False)
        for data, over in (
                ({"tool_name": "Read", "tool_use_id": "t", "tool_input": {"command": "pytest"}}, None),
                ({"tool_name": "Grep", "tool_use_id": "t", "tool_input": {"pattern": "pytest"}}, None),
                ({"tool_name": "Edit", "tool_use_id": "t", "tool_input": {"file_path": "pytest"}}, None),
                ({"tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": "pytest", "run_in_background": True}}, None),
                ({"tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": "git status"}}, None),
                ({"tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": "pytest"}}, off)):
            self.assertEqual(self.pre(data, config(self.dir, **(over or {}))), (0, ""), data)

    def test_broken_input_is_exit_0_and_no_change(self):
        for text in ("", "{not json", "[]", "null", '{"tool_name": "Bash"}', '{"tool_name": "Bash", "tool_input": 5}'):
            self.assertEqual(self.pre(text), (0, ""), text)

    def test_a_missing_or_broken_config_is_exit_0_and_no_change(self):
        data = json.dumps({"tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": "pytest"}})
        for body in (None, "{bad"):
            path = os.path.join(self.dir, "cfg2.json")
            if body is not None:
                with open(path, "w") as fh:
                    fh.write(body)
            out = io.StringIO()
            with unittest.mock.patch("sys.stdin", io.StringIO(data)), unittest.mock.patch("sys.stdout", out):
                self.assertEqual(layered.main(["pre", "--config", path]), 0)
            self.assertEqual(out.getvalue(), "")

    # --- the wrapper, run in a real shell with fake test tools

    def test_pass_keeps_the_result_line_only_and_exit_0(self):
        self.tool("pytest", PYTEST_PASS, 0)
        out, code = self.run_wrapped("pytest -q")
        self.assertEqual(code, 0)
        self.assertIn("60 passed in 1.20s", out)
        self.assertNotIn("test_case_7 PASSED", out)
        self.assertIn("result lines only", out)
        self.assertLess(len(out), len(PYTEST_PASS) // 2)

    def test_pytest_failure_keeps_verbatim_lines_the_path_and_the_exit_code(self):
        self.tool("pytest", PYTEST_FAIL, 1)
        out, code = self.run_wrapped("cd . && pytest")
        self.assertEqual(code, 1)
        for line in ("FAILED tests/test_mod.py::test_total_is_right - assert 3 == 4", "E       assert 3 == 4",
                     "tests/test_mod.py:41: AssertionError", "========================= 1 failed, 40 passed in 0.31s ========================="):
            self.assertIn(line + "\n", out)
        self.assertNotIn("test_case_7 PASSED", out)
        path = out.split("characters: ")[1].split(";")[0]
        with open(path) as fh:
            self.assertEqual(fh.read().strip(), PYTEST_FAIL.strip())

    def test_vitest_failure(self):
        self.tool("vitest", VITEST_FAIL, 1)
        out, code = self.run_wrapped("vitest run")
        self.assertEqual(code, 1)
        for line in ("   × cart > adds the tax 3ms", " FAIL  src/cart.test.ts > cart > adds the tax",
                     "AssertionError: expected 110 to be 120 // Object.is equality", " ❯ src/cart.test.ts:12:21",
                     "      Tests  1 failed | 4 passed (5)"):
            self.assertIn(line + "\n", out)
        self.assertLess(out.count("src/a.test.ts (3 tests)"), 2)

    def test_playwright_failure(self):
        self.tool("playwright", PLAYWRIGHT_FAIL, 1)
        out, code = self.run_wrapped("playwright test")
        self.assertEqual(code, 1)
        for line in ("  1) [chromium] › e2e/cart.spec.ts:10:5 › checkout shows the total ──────────",
                     "    Expected string: \"$12\"", "    Received string: \"$10\"", "      at e2e/cart.spec.ts:14:35"):
            self.assertIn(line + "\n", out)
        self.assertLess(out.count("home loads"), 2)

    def test_output_under_the_pass_through_size_is_unchanged_and_leaves_no_file(self):
        self.tool("pytest", "short output\n1 passed", 0)
        out, code = self.run_wrapped("pytest", passthrough_chars=10000)
        self.assertTrue(out.splitlines()[0].startswith(NOTICE))
        self.assertEqual((out.splitlines()[1:], code), (["short output", "1 passed"], 0))
        self.assertIn(os.path.join(self.dir, "out", "toolu_01.txt"), out.splitlines()[0])
        self.assertEqual(os.listdir(os.path.join(self.dir, "out")), [])

    def test_exit_codes_are_kept(self):
        for code in (0, 1, 2, 5, 130):
            self.tool("make", "ok\n" * 200, code)
            self.assertEqual(self.run_wrapped("make test", passthrough_chars=10)[1], code)

    def test_cd_and_environment_work_inside_the_wrapper(self):
        os.makedirs(os.path.join(self.dir, "sub"))
        with open(os.path.join(self.bin, "pytest"), "w") as fh:
            fh.write("#!/bin/sh\npwd\necho \"$MODE\"\nexit 3\n")
        os.chmod(os.path.join(self.bin, "pytest"), 0o755)
        out, code = self.run_wrapped("cd sub && MODE=fast pytest", passthrough_chars=1000)
        self.assertTrue(out.splitlines()[0].startswith(NOTICE))
        self.assertEqual((out.splitlines()[1:], code), ([f"{self.dir}/sub", "fast"], 3))

    def test_a_failing_reducer_prints_the_full_output(self):
        self.tool("pytest", PYTEST_FAIL, 1)
        cfg = config(self.dir)
        wrapped = layered.wrap("pytest", cfg, "toolu_01").replace("reduce --config", "reduce --nope")
        os.makedirs(cfg["saved_dir"], exist_ok=True)
        done = subprocess.run(["bash", "-c", wrapped], capture_output=True, text=True,
                              env=dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"]))
        self.assertTrue(done.stdout.startswith(NOTICE))
        self.assertEqual((done.returncode, done.stdout.strip().split("\n", 1)[1]), (1, PYTEST_FAIL.strip()))

    # --- the policy, on text

    def reduce(self, text, rc, log=False, **over):
        cfg = config(self.dir, **over)
        lines = text.splitlines()
        out, how = layered.reduce_output(lines, len(text), rc, cfg, "make test", os.path.join(self.dir, "full.txt"), log)
        return (text if out is None else out), how

    def test_failure_with_no_matching_line_is_unchanged_when_the_fallback_is_off(self):
        text = "noise line\n" * 200
        with unittest.mock.patch.object(layered, "summarize") as summarize:
            self.assertEqual(self.reduce(text, 1, large_chars=100), (text, "fail-unchanged"))
        summarize.assert_not_called()

    def test_fallback_on_summarizes_only_above_the_large_size_and_only_when_no_rule_matched(self):
        text = "noise line\n" * 200
        with unittest.mock.patch.object(layered, "summarize", return_value="the build died in step 3") as summarize:
            out, how = self.reduce(text, 1, summarize_fallback=True, large_chars=100)
            self.assertEqual(how, "fail-summary")
            self.assertIn("the build died in step 3", out)
            self.assertIn("full.txt", out)
            summarize.assert_called_once()
            summarize.reset_mock()
            self.assertEqual(self.reduce(text, 1, summarize_fallback=True, large_chars=100000)[1], "fail-unchanged")
            self.assertEqual(self.reduce(PYTEST_FAIL, 1, summarize_fallback=True, large_chars=10)[1], "fail-rules")
            self.assertEqual(self.reduce(text, 0, summarize_fallback=True, large_chars=100)[1], "pass")
            summarize.assert_not_called()

    def test_an_empty_summary_shows_the_last_lines_and_the_path(self):
        text = "noise line\n" * 200
        with unittest.mock.patch.object(layered, "summarize", return_value=""):
            out, how = self.reduce(text, 1, summarize_fallback=True, large_chars=100)
        self.assertEqual(how, "fail-tail")
        self.assertIn("no summary; the last lines", out)
        self.assertIn("full.txt", out)

    def test_summarize_calls_haiku_through_claude_p(self):
        done = subprocess.CompletedProcess([], 0, stdout="  summary \n", stderr="")
        with unittest.mock.patch.object(layered.subprocess, "run", return_value=done) as run:
            self.assertEqual(layered.summarize("x" * 100, "make test"), "summary")
        argv = run.call_args.args[0]
        self.assertEqual(argv[:5], ["claude", "-p", "--model", "haiku", "--no-session-persistence"])

    # --- review fixes (0.29.0)

    NOISE = "\n".join(f"tests/test_m.py::test_{i} PASSED" for i in range(80)) + "\n"
    WARN = "\n".join(f"src/lib.py:{i}: DeprecationWarning: x is old" for i in range(100)) + "\n"

    def kept(self, text, rc=1, **kw):
        out, how = self.reduce(text, rc, passthrough_chars=500, **kw)
        return out

    def test_the_key_line_survives_a_flood_of_file_line_noise(self):
        frames = "".join(f"src/x.py:{i}: in f{i}\n    call()\n" for i in range(90))
        out = self.kept(frames + "E   KeyError: 'secret'\nFAILED tests/test_k.py::test_key - KeyError\n=== 1 failed in 1s ===\n")
        self.assertIn("E   KeyError: 'secret'\n", out)
        self.assertIn("FAILED tests/test_k.py::test_key - KeyError\n", out)
        self.assertIn("matching lines omitted", out)
        self.assertNotIn("verbatim", out)
        self.assertIn("=== 1 failed in 1s ===", out)

    def test_compiler_make_linker_and_crash_lines_are_key_lines(self):
        for line in ("src/a.ts(3,5): error TS2322: Type 'string' is not assignable to type 'number'.",
                     "make: *** [typecheck] Error 2", "ld: symbol(s) not found for architecture arm64",
                     "clang: error: linker command failed with exit code 1", "foo.c:10:5: error: use of undeclared identifier 'bar'",
                     "Segmentation fault (core dumped)", "Fatal Python error: Segmentation fault", "Killed", "Aborted (core dumped)",
                     "build/main.o: undefined reference to `foo'", "/r/src/a.ts:3:14: ERROR: Expected \";\" but found \"x\"",
                     "Error: page.click: Test timeout of 30000ms exceeded."):
            for before in (self.WARN, self.NOISE):
                text = before + line + "\n" + "tail line\n" * 40
                self.assertIn(line + "\n", self.kept(text), line)

    def test_the_last_lines_are_always_kept_and_an_exact_list_says_verbatim(self):
        text = self.NOISE + "FAILED tests/t.py::t - boom\n" + "".join(f"last {i}\n" for i in range(20))
        out = self.kept(text)
        self.assertIn("last 19\n", out)
        self.assertIn("last 5\n", out)
        self.assertNotIn("last 4\n", out)
        self.assertNotIn("omitted", out)
        self.assertIn("verbatim", out)

    def test_a_failure_with_only_an_error_line_in_a_pile_of_passes(self):
        out = self.kept(self.NOISE + "Segmentation fault (core dumped)\n")
        self.assertIn("Segmentation fault", out)

    def test_exit_0_with_a_failed_or_error_line_uses_the_failure_rules(self):
        out, how = self.reduce(self.NOISE + "ERROR something broke\n" + "tail\n" * 3, 0, passthrough_chars=500)
        self.assertEqual(how, "fail-rules")
        self.assertIn("ERROR something broke", out)
        self.assertEqual(self.reduce(PYTEST_PASS, 0, passthrough_chars=500)[1], "pass")

    def test_a_log_command_with_exit_0_uses_the_failure_rules(self):
        gh = ("\n".join(f"build\tstep\tline {i}" for i in range(100)) + "\nbuild\tRun tests\tE   assert 1 == 2\n"
              "build\tRun tests\tFAILED tests/test_z.py::test_z\n" + "\n".join(f"build\tPost\tcleanup {i}" for i in range(30)) + "\n")
        out, how = self.reduce(gh, 0, log=True, passthrough_chars=500)
        self.assertEqual(how, "fail-rules")
        self.assertIn("FAILED tests/test_z.py::test_z", out)
        self.assertIn("exit 0", out)
        wrapped = layered.wrap("gh run view 9 --log", config(self.dir), "t")
        self.assertIn("--log", wrapped.split("reduce", 1)[1])
        self.assertNotIn("--log", layered.wrap("pytest", config(self.dir), "t").split("reduce", 1)[1])

    def test_one_huge_line_does_not_hang_the_reducer(self):
        self.tool("pytest", "ok", 1)
        for line in ("a b " * 250000, "_" * 1000000, "E " * 500000, "= " * 500000):
            with open(os.path.join(self.dir, "big.txt"), "w") as fh:
                fh.write("x.py:1: Error: y\n" + line + "\nFAILED t::t\n")
            cfg = config(self.dir)
            started = time.time()
            done = subprocess.run([sys.executable, "-S", os.path.join(HOOKS, "layered.py"), "reduce", "--config", cfg["config_file"],
                                   "--file", os.path.join(self.dir, "big.txt"), "--rc", "1", "--cmd-b64", "eA=="],
                                  capture_output=True, text=True)
            self.assertLess(time.time() - started, 4)
            self.assertEqual(done.returncode, 0)
            self.assertIn("FAILED t::t", done.stdout)
            self.assertIn("[line cut]", done.stdout)

    def test_a_reducer_that_runs_too_long_exits_1_and_the_wrapper_prints_the_file(self):
        self.tool("pytest", PYTEST_FAIL, 1)
        cfg = config(self.dir)
        wrapped = layered.wrap("pytest", cfg, "toolu_01")
        os.makedirs(cfg["saved_dir"], exist_ok=True)
        slow = os.path.join(self.dir, "slow.py")
        with open(slow, "w") as fh:
            fh.write("import sys, time\nsys.path.insert(0, %r)\nimport layered\nlayered.REDUCE_SECONDS = 1\n"
                     "layered.extract = lambda lines: time.sleep(30)\nsys.exit(layered.main())\n" % HOOKS)
        wrapped = wrapped.replace(os.path.join(HOOKS, "layered.py"), slow)
        started = time.time()
        done = subprocess.run(["bash", "-c", wrapped], capture_output=True, text=True,
                              env=dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"]))
        self.assertLess(time.time() - started, 10)
        self.assertEqual(done.returncode, 1)
        self.assertIn(PYTEST_FAIL.strip(), done.stdout)

    def test_errexit_in_the_shell_does_not_hide_the_output_or_the_code(self):
        self.tool("pytest", PYTEST_FAIL, 4)
        cfg = config(self.dir)
        wrapped = layered.wrap("pytest", cfg, "toolu_01")
        os.makedirs(cfg["saved_dir"], exist_ok=True)
        done = subprocess.run(["bash", "-c", "set -e; set -o pipefail; " + wrapped], capture_output=True, text=True,
                              env=dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"]))
        self.assertEqual(done.returncode, 4)
        self.assertIn("FAILED tests/test_mod.py::test_total_is_right", done.stdout)

    def test_watch_and_follow_commands_are_not_wrapped(self):
        for cmd in ("vitest --watch", "vitest -w", "pnpm test --watch", "docker logs -f web", "docker logs --follow web",
                    "playwright test --ui", "npx playwright show-report", "playwright test --debug", "make test --watchAll"):
            self.assertIsNone(self.wrapped(cmd), cmd)
        self.assertFalse(layered.never_ends("make -f Makefile test"))
        self.assertIsNotNone(self.wrapped("make test-fast"))

    def test_the_wrapper_names_the_output_file_before_the_command_runs(self):
        with open(os.path.join(self.bin, "pytest"), "w") as fh:
            fh.write("#!/bin/sh\nsleep 30\n")
        os.chmod(os.path.join(self.bin, "pytest"), 0o755)
        cfg = config(self.dir)
        wrapped = layered.wrap("pytest", cfg, "toolu_01")
        os.makedirs(cfg["saved_dir"], exist_ok=True)
        proc = subprocess.Popen(["bash", "-c", wrapped], stdout=subprocess.PIPE, text=True,
                                env=dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"]))
        first = proc.stdout.readline()
        proc.kill()
        proc.wait()
        proc.stdout.close()
        self.assertIn(os.path.join(cfg["saved_dir"], "toolu_01.txt"), first)

    def test_every_default_pattern_matches_a_realistic_command(self):
        defaults = ["make test*", "pytest", "python* -m pytest*", "uv run pytest", "vitest", "npx vitest", "pnpm test*",
                    "playwright", "npx playwright", "gh run view --log", "docker logs"]
        real = {"make test*": "make test-unit", "pytest": "pytest -x tests/", "python* -m pytest*": "python3 -m pytest -q tests",
                "uv run pytest": "uv run pytest -q", "vitest": "vitest run", "npx vitest": "npx vitest run src",
                "pnpm test*": "pnpm test --run", "playwright": "playwright test e2e", "npx playwright": "npx playwright test",
                "gh run view --log": "gh run view 123 --log", "docker logs": "docker logs --tail 100 web"}
        for pattern in defaults:
            self.assertIsNotNone(layered.wrap(real[pattern], config(self.dir, commands=[pattern]), "t"), pattern)
        self.assertIsNotNone(layered.wrap("python -m pytest", config(self.dir, commands=["python -m pytest"]), "t"))

    def test_a_pass_line_is_dropped_but_a_failure_that_names_passed_is_not(self):
        out = self.kept(self.NOISE + "FAILED tests/t.py::t - AssertionError: 2 PASSED expected\n")
        self.assertIn("FAILED tests/t.py::t - AssertionError: 2 PASSED expected", out)

    def test_a_saved_output_over_the_cap_is_cut_to_head_and_tail(self):
        path = os.path.join(self.dir, "huge.txt")
        with open(path, "w") as fh:
            fh.write("first\n" + "middle line\n" * 5000 + "FAILED t::t\nlast\n")
        with unittest.mock.patch.object(layered, "FILE_CAP", 20000):
            lines = layered.read_lines(path)
        self.assertEqual((lines[0], lines[-1]), ("first", "last"))
        self.assertTrue(any("cut from the middle" in ln for ln in lines))
        self.assertLessEqual(os.path.getsize(path), 20200)

    def test_more_watch_and_endless_forms_are_not_wrapped(self):
        for cmd in ("vitest watch", "make test-watch", "pytest -f", "pytest --looponfail", "pytest --pdb tests/",
                    "python -m pytest --trace", "pnpm test:watch", "npx vitest watch src"):
            self.assertIsNone(self.wrapped(cmd), cmd)
        self.assertIsNotNone(self.wrapped("pytest -x tests/"))

    def test_the_haiku_fallback_is_not_killed_by_the_alarm_and_a_timeout_shows_the_last_lines(self):
        text = "noise line\n" * 300
        cfg = config(self.dir, summarize_fallback=True, large_chars=100, summarize_seconds=1)
        with open(os.path.join(self.dir, "o.txt"), "w") as fh:
            fh.write(text)
        stub = os.path.join(self.dir, "run.py")
        with open(stub, "w") as fh:
            fh.write("import sys, time, subprocess\nsys.path.insert(0, %r)\nimport layered\nlayered.REDUCE_SECONDS = 1\n"
                     "def fake(argv, **kw):\n    time.sleep(2.5)\n    if kw['timeout'] < 2:\n        raise subprocess.TimeoutExpired(argv, kw['timeout'])\n"
                     "    return subprocess.CompletedProcess(argv, 0, stdout='slow summary', stderr='')\n"
                     "layered.subprocess.run = fake\nsys.exit(layered.main())\n" % HOOKS)
        def run(seconds):
            config(self.dir, summarize_fallback=True, large_chars=100, summarize_seconds=seconds)
            return subprocess.run([sys.executable, stub, "reduce", "--config", cfg["config_file"], "--file", os.path.join(self.dir, "o.txt"),
                                   "--rc", "1", "--cmd-b64", "eA=="], capture_output=True, text=True)
        done = run(5)  # slower than the 1 s alarm: the alarm is off while Haiku runs
        self.assertEqual(done.returncode, 0)
        self.assertIn("slow summary", done.stdout)
        with open(os.path.join(self.dir, "o.txt"), "w") as fh:
            fh.write(text)
        done = run(1)
        self.assertEqual(done.returncode, 0)
        self.assertIn("no summary; the last lines", done.stdout)
        self.assertIn("o.txt", done.stdout)

    def test_repeated_key_lines_collapse_and_a_root_cause_in_the_middle_survives(self):
        flood = "".join(f"ERROR tests/t_{i}.py::t_{i} fixture failed\n" for i in range(45))
        text = flood + "Caused by: ConnectionRefusedError: db is down\n" + flood.replace("ERROR", "ERROR  ") + "=== 90 errors ===\n"
        text += "".join(f"ERROR other {i}\n" for i in range(0, 0))
        out = self.kept(text)
        self.assertIn("Caused by: ConnectionRefusedError: db is down", out)
        self.assertIn("(×45)", out)
        self.assertLessEqual(out.count("fixture failed"), 17)  # one per group, and the 15 last lines

    def test_the_first_root_cause_line_is_kept_even_when_unique_keys_exceed_the_budget(self):
        text = "".join(f"ERROR unique failure {chr(97 + i % 26)}{'x' * i}\n" for i in range(30))
        text += "E   KeyError: 'root'\n" + "".join(f"FAILED t::{chr(97 + i % 26)}{'y' * i}\n" for i in range(100))
        self.assertIn("E   KeyError: 'root'", self.kept(text))

    def test_the_notice_never_names_a_file_that_is_unexplained(self):
        self.assertIn("when the output is reduced", layered.wrap("pytest", config(self.dir), "t"))

    def test_cutting_a_big_file_replaces_it_whole(self):
        path = os.path.join(self.dir, "huge2.txt")
        with open(path, "w") as fh:
            fh.write("x\n" * 20000)
        with unittest.mock.patch.object(layered, "FILE_CAP", 10000), unittest.mock.patch.object(layered.os, "replace", wraps=os.replace) as rep:
            layered.read_lines(path)
        rep.assert_called_once_with(path + ".cut", path)
        self.assertFalse(os.path.exists(path + ".cut"))

    def test_old_saved_files_are_pruned(self):
        out = os.path.join(self.dir, "out")
        os.makedirs(out)
        old, new = os.path.join(out, "old.txt"), os.path.join(out, "new.txt")
        for path in (old, new):
            open(path, "w").close()
        os.utime(old, (1, 1))
        layered.prune(out)
        self.assertEqual(os.listdir(out), ["new.txt"])


BRIEF = """# Task 7 — Fix the cart total

Project: demo

## GOAL

Make the cart total include tax.

## SCOPE

src/cart/

## CONTEXT

- Task: `tg show 7`

## ACCEPTANCE

- [ ] total includes tax
- [ ] a test covers it

## VERIFY

make test

## TIMEBOX

one hour
"""


class Compact(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.realpath(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.wt = os.path.join(self.dir, "wt")
        os.makedirs(self.wt)
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.name=t", "-c", "user.email=t@e.com", "commit", "-q", "--allow-empty", "-m", "base")
        self.head = self.git("rev-parse", "HEAD")
        self.brief = os.path.join(self.dir, "brief.md")
        self.write_brief(BRIEF)
        self.cfg = {"task": 7, "attempt": 2, "brief": self.brief}
        self.cfg_file = os.path.join(self.dir, "cfg.json")
        self.save_cfg()

    def git(self, *args):
        return subprocess.run(["git", "-C", self.wt, *args], capture_output=True, text=True, check=True).stdout.strip()

    def write_brief(self, text):
        with open(self.brief, "w") as fh:
            fh.write(text)

    def save_cfg(self):
        with open(self.cfg_file, "w") as fh:
            json.dump(self.cfg, fh)

    def hook(self, event, **extra):
        data = {"hook_event_name": event, "cwd": self.wt, **extra}
        out = io.StringIO()
        with unittest.mock.patch("sys.stdin", io.StringIO(json.dumps(data))), unittest.mock.patch("sys.stdout", out):
            self.assertEqual(compact.main(["--config", self.cfg_file]), 0)
        return out.getvalue()

    def test_pre_compact_prints_the_instruction_and_the_pinned_facts(self):
        with open(os.path.join(self.wt, "dirty.txt"), "w") as fh:
            fh.write("x")
        out = self.hook("PreCompact", trigger="auto")
        self.assertIn("PINNED FACTS", out)
        for part in ("Task id 7, attempt 2", "# Task 7 — Fix the cart total", "## GOAL\nMake the cart total include tax.",
                     "## SCOPE\nsrc/cart/", "## ACCEPTANCE\n- [ ] total includes tax\n- [ ] a test covers it", "## VERIFY\nmake test",
                     f"Head: {self.head} (branch main)", "Uncommitted changes: 1\n?? dirty.txt"):
            self.assertIn(part, out)
        self.assertNotIn("TIMEBOX", out)
        self.assertLessEqual(len(out), 10000)

    def test_session_start_after_a_compaction_carries_the_same_facts_as_additional_context(self):
        out = json.loads(self.hook("SessionStart", source="compact"))["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        for part in ("Task id 7, attempt 2", "make test", f"Head: {self.head}", "Uncommitted changes: none"):
            self.assertIn(part, out["additionalContext"])

    def test_session_start_for_other_sources_and_other_events_print_nothing(self):
        for source in ("startup", "resume", "clear"):
            self.assertEqual(self.hook("SessionStart", source=source), "")
        self.assertEqual(self.hook("PostToolUse"), "")

    def test_open_finding_steers_are_pinned(self):
        block = "steer #31:\nF1: src/cart/total.py:12 the tax is added twice\nF2: no test for a zero total"
        with unittest.mock.patch.object(compact, "finding_lines", return_value=[block]):
            self.cfg["ctx"] = "x"
            self.save_cfg()
            out = self.hook("PreCompact")
        self.assertIn("F1: src/cart/total.py:12 the tax is added twice\nF2: no test for a zero total", out)

    def test_findings_are_read_from_the_mailbox_context(self):
        rows = [{"id": 31, "kind": "steer", "author": "manager", "attempt": 2,
                 "body": "Steer: 2 findings\nKind: finding\nF1: the tax is added twice\nF2: no zero test\n"},
                {"id": 30, "kind": "steer", "author": "manager", "attempt": 2, "body": "Steer: acked one\nKind: finding\nF1: old\n"},
                {"id": 32, "kind": "ack", "author": "task-7-2", "attempt": 2, "body": "Re: 30\nAction: done\nF1: fixed\n"}]
        meta = {"mailbox": {"30": {"kind": "steer"}, "31": {"kind": "steer"}}}
        tg = os.path.join(self.dir, "tg.py")
        with open(tg, "w") as fh:
            fh.write("import json, sys\nsys.stdout.write(json.dumps(%r if 'result' in sys.argv else {'meta': %r}))\n" % (rows, meta))
        ctx = os.path.join(self.dir, "ctx.json")
        with open(ctx, "w") as fh:
            json.dump({"python": sys.executable, "tg": tg, "db": "x", "project": "p", "task": 7, "attempt": 2, "by": "w"}, fh)
        self.assertEqual(compact.finding_lines(ctx),
                         ["steer #31:\nF1: the tax is added twice\nF2: no zero test"])
        self.assertEqual(compact.finding_lines(os.path.join(self.dir, "missing.json")), [])

    def test_a_large_brief_stays_under_the_cap_and_keeps_every_section(self):
        big = BRIEF.replace("make test", "make test\n" + "line of verify text\n" * 800).replace(
            "- [ ] a test covers it", "\n".join(f"- [ ] criterion {i} " + "x" * 80 for i in range(300)))
        self.write_brief(big)
        block = "steer #31:\n" + "\n".join(f"F{i}: " + "y" * 200 for i in range(1, 30))
        with unittest.mock.patch.object(compact, "finding_lines", return_value=[block]):
            self.cfg["ctx"] = "x"
            self.save_cfg()
            pre = self.hook("PreCompact")
            start = json.loads(self.hook("SessionStart", source="compact"))["hookSpecificOutput"]["additionalContext"]
        for text in (pre, start):
            self.assertLessEqual(len(text), compact.LIMIT)
            for part in ("## GOAL", "## SCOPE", "## ACCEPTANCE", "## VERIFY", "OPEN FINDINGS", f"Head: {self.head}", "[cut:"):
                self.assertIn(part, text)
        self.assertIn("Make the cart total include tax.", pre)

    def test_git_runs_in_the_worktree_of_the_config_not_in_the_hook_cwd(self):
        elsewhere = os.path.join(self.dir, "elsewhere")
        os.makedirs(elsewhere)
        self.cfg["worktree"] = self.wt
        self.save_cfg()
        data = {"hook_event_name": "PreCompact", "cwd": elsewhere}
        out = io.StringIO()
        with unittest.mock.patch("sys.stdin", io.StringIO(json.dumps(data))), unittest.mock.patch("sys.stdout", out):
            compact.main(["--config", self.cfg_file])
        self.assertIn(f"Head: {self.head}", out.getvalue())

    def test_no_git_block_when_there_is_no_head(self):
        self.cfg["worktree"] = os.path.join(self.dir, "not-a-repo")
        os.makedirs(self.cfg["worktree"])
        self.save_cfg()
        out = self.hook("PreCompact")
        self.assertNotIn("Head:", out)
        self.assertNotIn("Uncommitted", out)
        self.assertIn("## GOAL", out)

    def test_a_long_title_is_counted_and_the_output_stays_under_10000(self):
        big = "# Task 7 — " + "T" * 3000 + BRIEF[BRIEF.index("\n"):]
        big = big.replace("make test", "make test\n" + "verify line\n" * 2000)
        self.write_brief(big)
        for text in (self.hook("PreCompact"), json.loads(self.hook("SessionStart", source="compact"))["hookSpecificOutput"]["additionalContext"]):
            self.assertLessEqual(len(text), compact.LIMIT)
            self.assertIn("Task id 7, attempt 2", text)

    def test_a_cut_findings_block_points_to_the_mailbox_inbox(self):
        block = "steer #31:\n" + "\n".join(f"F{i}: " + "y" * 300 for i in range(1, 40))
        with unittest.mock.patch.object(compact, "finding_lines", return_value=[block]):
            self.cfg["ctx"] = "/x/1-1.ctx.json"
            self.save_cfg()
            out = self.hook("PreCompact")
        self.assertRegex(out, r"\[cut: run .*mailbox\.py.* --ctx /x/1-1\.ctx\.json inbox for the rest\]")

    def test_a_missing_brief_still_pins_the_head(self):
        self.cfg["brief"] = os.path.join(self.dir, "none.md")
        self.save_cfg()
        out = self.hook("PreCompact")
        self.assertIn(f"Head: {self.head}", out)
        self.assertIn("Task id 7, attempt 2", out)

    def test_broken_input_is_exit_0_and_prints_nothing(self):
        for text in ("", "{bad", "[]", "null", '{"cwd": "/"}'):
            out = io.StringIO()
            with unittest.mock.patch("sys.stdin", io.StringIO(text)), unittest.mock.patch("sys.stdout", out):
                self.assertEqual(compact.main(["--config", self.cfg_file]), 0)
            self.assertEqual(out.getvalue(), "", text)

    def test_a_broken_config_is_exit_0_and_prints_nothing(self):
        with open(self.cfg_file, "w") as fh:
            fh.write("{bad")
        self.assertEqual(self.hook("PreCompact"), "")

    def test_the_script_runs_as_a_process_and_exits_0_on_garbage(self):
        done = subprocess.run([sys.executable, "-S", os.path.join(HOOKS, "compact.py"), "--config", self.cfg_file],
                              input="{garbage", capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        done = subprocess.run([sys.executable, "-S", os.path.join(HOOKS, "layered.py"), "pre", "--config", self.cfg_file],
                              input="{garbage", capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
