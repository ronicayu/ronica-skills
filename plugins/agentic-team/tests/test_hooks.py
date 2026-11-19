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
        self.assertNotIn("src/a.test.ts (3 tests)", out)

    def test_playwright_failure(self):
        self.tool("playwright", PLAYWRIGHT_FAIL, 1)
        out, code = self.run_wrapped("playwright test")
        self.assertEqual(code, 1)
        for line in ("  1) [chromium] › e2e/cart.spec.ts:10:5 › checkout shows the total ──────────",
                     "    Expected string: \"$12\"", "    Received string: \"$10\"", "      at e2e/cart.spec.ts:14:35"):
            self.assertIn(line + "\n", out)
        self.assertNotIn("home loads", out)

    def test_output_under_the_pass_through_size_is_unchanged_and_leaves_no_file(self):
        self.tool("pytest", "short output\n1 passed", 0)
        out, code = self.run_wrapped("pytest", passthrough_chars=10000)
        self.assertEqual((out, code), ("short output\n1 passed\n", 0))
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
        self.assertEqual((out, code), (f"{self.dir}/sub\nfast\n", 3))

    def test_a_failing_reducer_prints_the_full_output(self):
        self.tool("pytest", PYTEST_FAIL, 1)
        cfg = config(self.dir)
        wrapped = layered.wrap("pytest", cfg, "toolu_01").replace("reduce --config", "reduce --nope")
        os.makedirs(cfg["saved_dir"], exist_ok=True)
        done = subprocess.run(["bash", "-c", wrapped], capture_output=True, text=True,
                              env=dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"]))
        self.assertEqual((done.returncode, done.stdout.strip()), (1, PYTEST_FAIL.strip()))

    # --- the policy, on text

    def reduce(self, text, rc, **over):
        cfg = config(self.dir, **over)
        return layered.reduce_output(text, rc, cfg, "make test", os.path.join(self.dir, "full.txt"))

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

    def test_an_empty_summary_falls_back_to_the_unchanged_output(self):
        text = "noise line\n" * 200
        with unittest.mock.patch.object(layered, "summarize", return_value=""):
            self.assertEqual(self.reduce(text, 1, summarize_fallback=True, large_chars=100), (text, "fail-unchanged"))

    def test_summarize_calls_haiku_through_claude_p(self):
        done = subprocess.CompletedProcess([], 0, stdout="  summary \n", stderr="")
        with unittest.mock.patch.object(layered.subprocess, "run", return_value=done) as run:
            self.assertEqual(layered.summarize("x" * 100, "make test"), "summary")
        argv = run.call_args.args[0]
        self.assertEqual(argv[:5], ["claude", "-p", "--model", "haiku", "--no-session-persistence"])

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
