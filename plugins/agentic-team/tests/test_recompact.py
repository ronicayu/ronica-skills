"""Tests for scripts/recompact.py, the SessionStart(compact) hook that gives the Manager its role and orders again.

Run: python3.11 plugins/agentic-team/tests/run_parallel.py (all tests, in parallel)

Each test feeds the hook a fake stdin and a temporary project with a run directory. The status part has no
Taskgraph there, so it shows its "unavailable" line; `run status --brief` has its own test in test_run.py.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
HOOK = os.path.join(PLUGIN, "scripts", "recompact.py")
WRAPPER = os.path.join(PLUGIN, "scripts", "recompact")
MANAGER = "11111111-aaaa-bbbb-cccc-000000000001"


class RecompactTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.run_dir = os.path.join(self.root, ".agentic-team")
        os.makedirs(self.run_dir)
        with open(os.path.join(self.root, ".agentic-team.toml"), "w") as fh:
            fh.write('[taskgraph]\nproject = "x"\n')
        self.write("manager-session", MANAGER + "\n")
        self.write("standing-orders.md", "1. Never push to main.\n")
        self.write("manager-orders.md", "1. Report in Chinese.\n")
        self.sub = os.path.join(self.root, "src", "deep")
        os.makedirs(self.sub)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        with open(os.path.join(self.run_dir, name), "w") as fh:
            fh.write(text)

    def hook(self, stdin, cmd=None):
        return subprocess.run(cmd or [sys.executable, HOOK], input=stdin, capture_output=True, text=True, timeout=60)

    def event(self, session=MANAGER, cwd=None):
        return json.dumps({"session_id": session, "cwd": cwd or self.root, "hook_event_name": "SessionStart",
                           "source": "compact"})

    def context(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        return out["hookSpecificOutput"]["additionalContext"]

    def silent(self, proc):
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_manager_session_gets_the_role_the_orders_and_the_next_steps(self):
        text = self.context(self.hook(self.event()))
        self.assertIn(os.path.join(PLUGIN, "agents", "manager.md"), text)
        self.assertIn("in full", text)
        self.assertIn("1. Never push to main.", text)
        self.assertIn("1. Report in Chinese.", text)
        self.assertIn("Status", text)
        self.assertIn("scripts/run\" record", text)
        self.assertIn("scripts/run\" wait", text)
        self.assertLess(text.index("manager.md"), text.index("Never push"))

    def test_the_project_is_found_from_a_subdirectory(self):
        self.assertIn("Never push", self.context(self.hook(self.event(cwd=self.sub))))

    def test_missing_manager_orders_are_not_an_error(self):
        os.remove(os.path.join(self.run_dir, "manager-orders.md"))
        text = self.context(self.hook(self.event()))
        self.assertIn("Never push", text)
        self.assertIn("(none)", text)

    def test_another_session_gets_nothing(self):
        self.silent(self.hook(self.event(session="22222222-other")))

    def test_no_manager_session_file_gets_nothing(self):
        os.remove(os.path.join(self.run_dir, "manager-session"))
        self.silent(self.hook(self.event()))

    def test_an_empty_manager_session_file_gets_nothing(self):
        self.write("manager-session", "\n")
        self.silent(self.hook(self.event(session="")))

    def test_no_run_directory_gets_nothing(self):
        with tempfile.TemporaryDirectory() as other:
            self.silent(self.hook(self.event(cwd=os.path.realpath(other))))
        os.remove(os.path.join(self.root, ".agentic-team.toml"))
        self.silent(self.hook(self.event(cwd=self.sub)))

    def test_broken_input_gets_nothing(self):
        for stdin in ("", "not json", "[]", "null", json.dumps({"session_id": MANAGER}),
                      json.dumps({"session_id": 5, "cwd": self.root})):
            self.silent(self.hook(stdin))

    def test_unreadable_standing_orders_still_give_the_role(self):
        os.remove(os.path.join(self.run_dir, "standing-orders.md"))
        text = self.context(self.hook(self.event()))
        self.assertIn("could not read standing-orders.md", text)
        self.assertIn("manager.md", text)

    def test_the_output_size_is_bounded(self):
        self.write("standing-orders.md", "x" * 500000)
        self.write("manager-orders.md", "y" * 500000)
        proc = self.hook(self.event())
        text = self.context(proc)
        self.assertLess(len(proc.stdout), 200000)
        self.assertIn("(cut at", text)

    def test_the_wrapper_gives_the_same_answer_and_never_fails(self):
        env_py = {"AGENTIC_TEAM_PYTHON": sys.executable}
        run = lambda stdin: subprocess.run([WRAPPER], input=stdin, capture_output=True, text=True, timeout=60,
                                           env={**os.environ, **env_py})
        self.assertIn("Never push", self.context(run(self.event())))
        self.silent(run(self.event(session="other")))
        self.silent(run("garbage"))

    def test_the_plugin_declares_the_hook(self):
        with open(os.path.join(PLUGIN, "hooks", "hooks.json")) as fh:
            hooks = json.load(fh)["hooks"]["SessionStart"]
        self.assertEqual([h["matcher"] for h in hooks], ["compact"])
        self.assertEqual(hooks[0]["hooks"][0]["command"], "${CLAUDE_PLUGIN_ROOT}/scripts/recompact")


if __name__ == "__main__":
    unittest.main()
