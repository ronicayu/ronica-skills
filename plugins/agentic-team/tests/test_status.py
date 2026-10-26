"""Tests for scripts/status.py. Run: "$PY" -m unittest discover plugins/agentic-team/tests

Each test uses a temporary Taskgraph database and the real tg.py from
plugins/taskgraph.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.dirname(os.path.dirname(HERE))
STATUS = os.path.join(os.path.dirname(HERE), "scripts", "status.py")
TG = os.path.join(PLUGINS, "taskgraph", "skills", "taskgraph", "scripts", "tg.py")

CHECKPOINT = "2026-10-26 10:00 SGT — completed: a; next: b; blocker: none"


class StatusTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.abspath(self._tmp.name)
        self.env = {k: v for k, v in os.environ.items() if k != "TASKGRAPH_DB"}
        self.env["TASKGRAPH_DB"] = os.path.join(self.dir, "tasks.db")

    def tearDown(self):
        self._tmp.cleanup()

    def tg(self, *args, stdin=None):
        out = subprocess.run([sys.executable, TG, "--project", "demo", "--json", *args],
                             input=stdin, capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def add_task(self, title, *meta, started=True):
        task_id = self.tg("add", title, "--meta", *meta)["id"]
        if started:
            self.tg("start", str(task_id))
        return task_id

    def add_result(self, task_id, status, body="", attempt=1, kind="task", by="worker"):
        self.tg("result", "add", str(task_id), "--kind", kind, "--attempt", str(attempt), "--by", by,
                "--status", status, "--body-file", "-", stdin=body)

    def status(self):
        out = subprocess.run([sys.executable, STATUS, "--tg", TG, "--project", "demo", "--root", self.dir],
                             capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        sections = {}
        for block in re.split(r"(?m)^## ", out.stdout)[1:]:
            title = re.sub(r" \(\d+\)$", "", block.splitlines()[0])
            sections[title] = block
        return sections

    def test_earlier_died_result_with_live_attempt_is_in_flight(self):
        task = self.add_task("Sweep", "attempt=2", "session=task-1-sweep", "model=sonnet")
        self.add_result(task, "DIED", "no session", attempt=1, by="manager")
        sections = self.status()
        self.assertEqual(sections["In flight"].splitlines()[0], "In flight (1)")
        self.assertIn("#1", sections["In flight"])
        self.assertIn("DIED", sections["In flight"])
        self.assertIn("None.", sections["Failed or abandoned"])
        self.assertIn("None.", sections["Waiting for verification or triage"])

    def test_abandoned_marker_lists_task_as_abandoned(self):
        task = self.add_task("Sweep", "attempt=3", "abandoned=died")
        self.add_result(task, "DIED", "no session", attempt=3, by="manager")
        sections = self.status()
        self.assertIn("#1", sections["Failed or abandoned"])
        self.assertIn("died", sections["Failed or abandoned"])
        self.assertIn("None.", sections["In flight"])

    def test_result_for_current_attempt_is_waiting_with_status_and_checkpoint(self):
        task = self.add_task("Sweep", "attempt=1", "session=task-1-sweep")
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nCheckpoint: {CHECKPOINT}\n")
        sections = self.status()
        waiting = sections["Waiting for verification or triage"]
        self.assertIn("#1", waiting)
        self.assertIn("PASS", waiting)
        self.assertIn(CHECKPOINT, waiting)
        self.assertIn("None.", sections["In flight"])

    def test_verdict_without_close_is_listed_apart(self):
        task = self.add_task("Sweep", "attempt=1", "verdict=verify-blocked")
        self.add_result(task, "PASS", "Task: 1\n")
        sections = self.status()
        self.assertIn("None.", sections["Waiting for verification or triage"])
        self.assertIn("None.", sections["In flight"])
        self.assertEqual(sections["Verdict recorded, not closed"].splitlines()[0], "Verdict recorded, not closed (1)")
        self.assertIn("verify-blocked", sections["Verdict recorded, not closed"])

    def test_done_task_without_merge_is_listed_until_merged_at(self):
        sha = "a" * 40
        unmerged = self.add_task("Sweep", "attempt=1", f"verdict_ref={sha}", "verdict=test-verified")
        merged = self.add_task("Build", "attempt=1", f"verdict_ref={sha}", "verdict=test-verified",
                               "merged_at=2026-10-26 10:00 SGT", "merged_by=operator")
        outside_git = self.add_task("Notes", "attempt=1", "verdict_ref=abc123  out.txt", "verdict=artifact-verified")
        for task in (unmerged, merged, outside_git):
            self.tg("done", str(task))
        out = subprocess.run([sys.executable, STATUS, "--tg", TG, "--project", "demo", "--root", self.dir,
                              "--since", "2099-01-01"], capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        block = re.split(r"(?m)^## ", out.stdout)
        section = next(b for b in block if b.startswith("Done, branch not merged"))
        self.assertEqual(section.splitlines()[0], "Done, branch not merged (1)")
        self.assertIn(f"#{unmerged}", section)
        self.assertNotIn(f"#{merged} ", section)
        self.assertNotIn(f"#{outside_git} ", section)

    def test_in_flight_shows_latest_result_and_old_checkpoint(self):
        self.add_task("Sweep", "attempt=2")
        self.add_result(1, "ISSUES", f"Checkpoint: {CHECKPOINT}\n", attempt=1)
        in_flight = self.status()["In flight"]
        self.assertIn("ISSUES", in_flight)
        self.assertIn(CHECKPOINT, in_flight)


if __name__ == "__main__":
    unittest.main()
