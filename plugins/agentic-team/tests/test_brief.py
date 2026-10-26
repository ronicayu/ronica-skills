"""Tests for scripts/brief.py. Run: "$PY" -m unittest discover plugins/agentic-team/tests

Each test uses a temporary Taskgraph database and the real tg.py from
plugins/taskgraph.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.dirname(os.path.dirname(HERE))
BRIEF = os.path.join(os.path.dirname(HERE), "scripts", "brief.py")
TG = os.path.join(PLUGINS, "taskgraph", "skills", "taskgraph", "scripts", "tg.py")


class BriefTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.abspath(self._tmp.name)
        self.root = os.path.join(self.dir, "repo")
        os.makedirs(self.root)
        self.git("init", "-q")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "base")
        self.db = os.path.join(self.dir, "tasks.db")
        self.env = {k: v for k, v in os.environ.items() if k != "TASKGRAPH_DB"}
        self.env["TASKGRAPH_DB"] = self.db
        self.write_config('[taskgraph]\nproject = "demo"\n')

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        out = subprocess.run(["git", "-C", self.root, *args], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def write_config(self, text):
        with open(os.path.join(self.root, ".agentic-team.toml"), "w") as fh:
            fh.write(text)

    def tg(self, *args):
        out = subprocess.run([sys.executable, TG, "--project", "demo", "--json", *args],
                             capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def add_task(self, title, notes, scope="src/", verify="make test", extra=(), depends=()):
        args = ["add", title, "--notes", textwrap.dedent(notes).strip(),
                "--meta", f"scope={scope}", f"verify={verify}", "estimate=1", *extra]
        for dep in depends:
            args += ["--depends", str(dep)]
        return self.tg(*args)["id"]

    def add_result(self, task_id, status, body, kind="task", attempt=1, by="worker"):
        out = subprocess.run(
            [sys.executable, TG, "--project", "demo", "result", "add", str(task_id), "--kind", kind,
             "--attempt", str(attempt), "--by", by, "--status", status, "--body-file", "-"],
            input=body, capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)

    def render(self, task_id, *extra, session=None, env=None, tg=TG):
        # A verify brief names its own session; a task brief gets its name from --keyword.
        name = ["--session", session] if session else ([] if "verify" in extra else ["--keyword", "sweep"])
        out = subprocess.run(
            [sys.executable, BRIEF, "--tg", tg, "--task", str(task_id), *name, "--root", self.root, *extra],
            capture_output=True, text=True, env=env or self.env)
        return out

    def brief(self, task_id, *extra, **kw):
        out = self.render(task_id, *extra, **kw)
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(out.stdout.strip()) as fh:
            return fh.read()

    @staticmethod
    def section(text, name):
        match = re.search(rf"(?ms)^## {name}\n\n(.*?)(?=^## |\Z)", text)
        return match.group(1).strip() if match else None

    def test_label_lines_stay_in_goal(self):
        task = self.add_task("Sweep domains", """
            Why: list stale domains.
            Serves: the ops team.
            Purpose: tidy up the registry.

            - [ ] every domain listed
        """)
        text = self.brief(task)
        goal = self.section(text, "GOAL")
        for line in ("Why: list stale domains.", "Serves: the ops team.", "Purpose: tidy up the registry."):
            self.assertIn(line, goal)
        self.assertEqual(self.section(text, "ACCEPTANCE"), "- every domain listed")

    def test_known_labels_still_parse(self):
        task = self.add_task("Sweep domains", """
            Why: list stale domains.
            Exit test: pytest passes
            exit tests: lint passes
            Acceptance: reviewed by a person
            - [x] checked item
        """)
        text = self.brief(task)
        self.assertEqual(self.section(text, "GOAL"), "Sweep domains. Why: list stale domains.")
        self.assertEqual(self.section(text, "ACCEPTANCE").splitlines(),
                         ["- pytest passes", "- lint passes", "- reviewed by a person", "- checked item"])

    def test_refuses_task_with_only_acceptance(self):
        task = self.add_task("Sweep domains", "Exit test: it works")
        out = self.render(task)
        self.assertEqual(out.returncode, 2)
        self.assertIn("GOAL", out.stderr)

    def test_result_command_in_brief(self):
        task = self.add_task("Sweep domains", "Why: reason.\n- [ ] done")
        text = self.brief(task)
        command = self.section(text, "REPORT")
        expected = (f'"{sys.executable}" "{TG}" --db "{self.db}" --project demo '
                    "result add 1 --kind task --attempt 1 --by task-1-1-sweep --status <STATUS> --body-file -")
        self.assertIn(expected, command)
        self.assertIn("<<'REPORT'\n<your report>\nREPORT", command)
        self.assertTrue(os.path.isabs(TG) and os.path.isabs(self.db))
        self.assertIn(f'"{sys.executable}" "{TG}" --db "{self.db}" --project demo show 1', text)

    def test_default_database_is_home_taskgraph(self):
        home = os.path.join(self.dir, "home")
        env = {k: v for k, v in self.env.items() if k != "TASKGRAPH_DB"}
        env["HOME"] = home
        out = subprocess.run([sys.executable, TG, "--project", "demo", "--json", "add", "Sweep",
                              "--notes", "Why: reason.\n- [ ] done", "--meta", "scope=src/", "verify=true"],
                             capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        text = self.brief(1, env=env)
        self.assertIn(f'--db "{os.path.join(home, ".taskgraph", "tasks.db")}"', text)

    def test_result_command_is_attempt_and_kind_specific(self):
        task = self.add_task("Sweep domains", "Why: reason.\n- [ ] done", extra=("attempt=2",))
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\n", attempt=2)
        text = self.brief(task, "--kind", "verify", "--verdict-ref", "abc1234")
        self.assertIn("result add 1 --kind verify --attempt 2 --by verify-1-2 --status <STATUS>", text)
        self.assertIn("Output under review: abc1234", text)
        self.assertIn("Task: 1\nStatus: PASS", self.section(text, "CONTEXT"))
        out = self.render(task, "--kind", "verify", "--verdict-ref", "abc1234")
        self.assertIn("task-1-2-verify.md", out.stdout)
        self.assertIn("session=verify-1-2", out.stderr)

    def test_verify_report_by_id_and_missing_result(self):
        task = self.add_task("Sweep domains", "Why: reason.\n- [ ] done", extra=("attempt=1",))
        out = self.render(task, "--kind", "verify", "--verdict-ref", "abc1234")
        self.assertEqual(out.returncode, 1)
        self.assertIn("no worker result", out.stderr)
        self.add_result(task, "ISSUES", "first report")
        self.add_result(task, "PASS", "second report")
        text = self.brief(task, "--kind", "verify", "--verdict-ref", "abc1234", "--report", "1")
        self.assertIn("first report", text)
        self.assertNotIn("second report", text)

    def test_upstream_and_previous_report_come_from_results(self):
        up = self.add_task("Build base", "Why: base.\n- [ ] built")
        task = self.add_task("Use base", "Why: needs base.\n- [ ] used", depends=(up,), extra=("attempt=1",))
        self.add_result(up, "PASS", "Task: 1\nFiles: base.txt\n", attempt=1)
        self.add_result(up, "DIED", "manager saw no session", attempt=2, by="manager")
        self.add_result(task, "ISSUES", "Task: 2\nIssues: broken\n"
                        "Checkpoint: 2026-10-26 10:00 SGT — completed: a; next: b; blocker: none\n", attempt=1)
        self.add_result(task, "DIED", "manager saw no session", attempt=2, by="manager")
        self.add_result(task, "PASS", "verifier said fine", kind="verify", attempt=1, by="verify-2-1")
        text = self.brief(task)
        context = self.section(text, "CONTEXT")
        self.assertIn("### Previous attempt (result #3, ISSUES, attempt 1)", context)
        self.assertIn("Issues: broken", context)
        self.assertIn("### Upstream #1: Build base", context)
        self.assertIn("Files: base.txt", context)
        self.assertIn("Last checkpoint: 2026-10-26 10:00 SGT — completed: a; next: b; blocker: none", context)
        self.assertNotIn("manager saw no session", text)
        self.assertNotIn("verifier said fine", text)
        self.assertIn("--attempt 2 --by task-2-2-sweep", text)

    def test_base_is_manager_head_then_previous_head(self):
        task = self.add_task("Sweep domains", "Why: reason.\n- [ ] done", extra=("attempt=1",))
        head = self.git("rev-parse", "HEAD")
        text = self.brief(task)
        self.assertIn(f"Base commit: {head}", text)
        self.assertIn(f"git reset --keep {head}", text)
        previous = "a" * 40
        self.add_result(task, "PASS", f"Task: 1\nBranch: worktree-task-1-1\nHead: {previous}\n")
        text = self.brief(task)
        self.assertIn(f"git reset --keep {previous}", text)
        self.assertNotIn(f"git reset --keep {head}", text)

    def test_upstream_without_result(self):
        up = self.add_task("Build base", "Why: base.\n- [ ] built")
        task = self.add_task("Use base", "Why: needs base.\n- [ ] used", depends=(up,))
        self.assertIn("No report on file.", self.brief(task))

    def test_manager_notes_are_skipped_but_a_salvaged_report_counts(self):
        task = self.add_task("Sweep domains", "Why: reason.\n- [ ] done", extra=("attempt=2",))
        self.add_result(task, "ISSUES", "worker report", attempt=1)
        self.add_result(task, "BLOCKED", "permission prompt", attempt=2, by="manager")
        text = self.brief(task)
        self.assertIn("worker report", text)
        self.assertNotIn("permission prompt", text)
        self.add_result(task, "PASS", "report copied from the logs", attempt=2, by="manager")
        self.assertIn("report copied from the logs", self.brief(task))

    def test_session_name_has_the_attempt(self):
        task = self.add_task("Sweep domains", "Why: reason.\n- [ ] done", extra=("attempt=1",))
        out = self.render(task)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("attempt=2\nsession=task-1-2-sweep", out.stderr)
        bad = self.render(task, "--keyword", "bad name")
        self.assertEqual(bad.returncode, 2)

    def test_attempt_cap(self):
        task = self.add_task("Sweep domains", "Why: reason.\n- [ ] done", extra=("attempt=3",))
        out = self.render(task)
        self.assertEqual(out.returncode, 2)
        self.assertIn("abandon", out.stderr)
        self.assertEqual(self.render(task, "--attempt", "4").returncode, 0)
        self.tg("edit", str(task), "--meta", "attempt=2")
        self.assertEqual(self.render(task).returncode, 0)

    def test_rendered_report_command_runs_in_bash(self):
        # A repo-side path with a space and a dollar sign must survive the quoting.
        odd = os.path.join(self.dir, "we ird $dir")
        os.makedirs(odd)
        os.symlink(os.path.dirname(TG), os.path.join(odd, "bin"))
        tg = os.path.join(odd, "bin", "tg.py")
        self.db = os.path.join(odd, "my $db.sqlite")
        self.env["TASKGRAPH_DB"] = self.db
        task = self.add_task("Sweep domains", "Why: reason.\n- [ ] done")
        text = self.brief(task, tg=tg)
        command = re.search(r"```sh\n(.*?)\n```", self.section(text, "REPORT"), re.S).group(1)
        body = "Task: 1\nStatus: PASS\nIssues: a $HOME `date` \"quoted\" line\n"
        command = command.replace("<STATUS>", "PASS").replace("<your report>", body.rstrip("\n"))
        out = subprocess.run(["bash", "-c", command], capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = self.tg("result", "ls", str(task))[0]
        self.assertEqual((result["kind"], result["attempt"], result["author"], result["status"]),
                         ("task", 1, "task-1-1-sweep", "PASS"))
        self.assertEqual(result["body"], body)

    def test_template_without_result_command_is_refused(self):
        template = os.path.join(self.dir, "brief.md")
        with open(template, "w") as fh:
            fh.write("# {{TASK_TITLE}}\n{{GOAL}}\n")
        self.write_config(f'[taskgraph]\nproject = "demo"\n[sessions]\nbrief_template = "{template}"\n')
        task = self.add_task("Sweep domains", "Why: reason.\n- [ ] done")
        out = self.render(task)
        self.assertEqual(out.returncode, 2)
        self.assertIn("RESULT_COMMAND", out.stderr)

    def test_stop_order_refuses_task_brief(self):
        os.makedirs(os.path.join(self.root, ".agentic-team"))
        with open(os.path.join(self.root, ".agentic-team", "standing-orders.md"), "w") as fh:
            fh.write("STOP: paused\n")
        task = self.add_task("Sweep domains", "Why: reason.\n- [ ] done")
        self.assertEqual(self.render(task).returncode, 3)


if __name__ == "__main__":
    unittest.main()
