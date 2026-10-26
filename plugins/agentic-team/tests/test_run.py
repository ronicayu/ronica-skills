"""Tests for scripts/run.py. Run: "$PY" -m unittest discover plugins/agentic-team/tests

Each test builds a temporary git repository as the root, a temporary Taskgraph
database, a temporary HOME, the real tg.py from plugins/taskgraph, and a fake
`claude` first on PATH. The fake logs every call and answers from files the
test writes. Nothing here starts a real Claude session.
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
RUN = os.path.join(os.path.dirname(HERE), "scripts", "run.py")
TG = os.path.join(PLUGINS, "taskgraph", "skills", "taskgraph", "scripts", "tg.py")

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys

argv = sys.argv[1:]
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as fh:
    fh.write(json.dumps(argv) + "\n")


def read(name):
    path = os.environ.get(name)
    return open(path).read() if path and os.path.isfile(path) else None


cmd = argv[0] if argv else ""
if cmd == "agents":
    print(read("FAKE_CLAUDE_AGENTS") or "[]")
elif cmd == "--bg":
    if os.environ.get("FAKE_CLAUDE_UNTRUSTED"):
        sys.stderr.write("Workspace not trusted. Run claude in the repository first.\n")
        sys.exit(1)
    print("fake-session-id")
elif cmd == "stop":
    if os.environ.get("FAKE_CLAUDE_STOP_FAIL"):
        sys.stderr.write("boom\n")
        sys.exit(1)
elif cmd == "logs":
    folder = os.environ.get("FAKE_CLAUDE_LOGS_DIR")
    path = os.path.join(folder, argv[1] + ".txt") if folder else ""
    if path and os.path.isfile(path):
        sys.stdout.write(open(path).read())
elif cmd == "rm":
    table = json.loads(read("FAKE_CLAUDE_RM") or "{}")
    entry = table.get(argv[1], {})
    if entry.get("exit") and "--discard-unpushed" not in argv:
        sys.stderr.write(entry.get("stderr", "") + "\n")
        sys.exit(entry["exit"])
'''

CHECKPOINT = "2026-10-26 10:00 SGT — completed: a; next: b; blocker: none"
SHA_A = "a" * 40


def transcript(output_tokens):
    records = [
        {"type": "user", "timestamp": "2026-10-26T01:00:00Z", "message": {"content": "hi"}},
        {"type": "assistant", "timestamp": "2026-10-26T01:05:00Z",
         "message": {"id": "m1", "usage": {"output_tokens": output_tokens, "input_tokens": 3,
                                           "cache_read_input_tokens": 5, "cache_creation_input_tokens": 7}}},
    ]
    return "".join(json.dumps(r) + "\n" for r in records)


class RunTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.realpath(self._tmp.name)
        self.root = os.path.join(self.dir, "repo")
        self.home = os.path.join(self.dir, "home")
        self.bin = os.path.join(self.dir, "bin")
        self.logs = os.path.join(self.dir, "logs")
        for path in (self.root, self.home, self.bin, self.logs):
            os.makedirs(path)
        self.git("init", "-q")
        for key, value in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            self.git("config", key, value)
        self.git("commit", "-q", "--allow-empty", "-m", "base")
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a") as fh:
            fh.write(".claude/worktrees/\n.agentic-team/\n.agentic-team.toml\n")
        fake = os.path.join(self.bin, "claude")
        with open(fake, "w") as fh:
            fh.write(FAKE_CLAUDE)
        os.chmod(fake, 0o755)
        self.log = os.path.join(self.dir, "claude.log")
        self.agents_file = os.path.join(self.dir, "agents.json")
        self.rm_file = os.path.join(self.dir, "rm.json")
        self.db = os.path.join(self.dir, "tasks.db")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("TASKGRAPH_DB", "TASKGRAPH_TG", "CLAUDE_CONFIG_DIR")}
        self.env.update({
            "HOME": self.home, "TASKGRAPH_DB": self.db,
            "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""),
            "FAKE_CLAUDE_LOG": self.log, "FAKE_CLAUDE_AGENTS": self.agents_file,
            "FAKE_CLAUDE_LOGS_DIR": self.logs, "FAKE_CLAUDE_RM": self.rm_file,
        })
        self.write_config()

    def tearDown(self):
        self._tmp.cleanup()

    # --- helpers

    def git(self, *args, cwd=None):
        out = subprocess.run(["git", "-C", cwd or self.root, *args], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def write_config(self, extra="", sessions=""):
        with open(os.path.join(self.root, ".agentic-team.toml"), "w") as fh:
            fh.write('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n' + sessions
                     + textwrap.dedent(extra))

    def orders(self, text):
        os.makedirs(os.path.join(self.root, ".agentic-team"), exist_ok=True)
        with open(os.path.join(self.root, ".agentic-team", "standing-orders.md"), "w") as fh:
            fh.write(text)

    def tg(self, *args, stdin=None, env=None):
        out = subprocess.run([sys.executable, TG, "--project", "demo", "--json", *args],
                             input=stdin, capture_output=True, text=True, env=env or self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def add_task(self, title="Sweep domains", notes="Why: reason.\n- [ ] done", scope="src/", verify="make test",
                 start=False, depends=(), env=None, **meta):
        pairs = [f"scope={scope}", f"verify={verify}", "estimate=1"] + [f"{k}={v}" for k, v in meta.items()]
        args = ["add", title, "--notes", notes, "--meta", *pairs]
        for dep in depends:
            args += ["--depends", str(dep)]
        task_id = self.tg(*args, env=env)["id"]
        if start:
            self.tg("start", str(task_id), env=env)
        return task_id

    def add_result(self, task_id, status, body="", kind="task", attempt=1, by="worker"):
        return self.tg("result", "add", str(task_id), "--kind", kind, "--attempt", str(attempt), "--by", by,
                       "--status", status, "--body-file", "-", stdin=body)

    def results(self, task_id):
        return self.tg("result", "ls", str(task_id))

    def meta(self, task_id):
        return self.tg("show", str(task_id))["meta"]

    def status_of(self, task_id):
        return self.tg("show", str(task_id))["status"]

    def worktree(self, name, base="HEAD"):
        path = os.path.join(self.root, ".claude", "worktrees", name)
        self.git("worktree", "add", "-q", path, "-b", f"worktree-{name}", base)
        return path

    def wt_commit(self, wt, name="out.txt", text="x\n"):
        with open(os.path.join(wt, name), "w") as fh:
            fh.write(text)
        self.git("add", "-A", cwd=wt)
        self.git("commit", "-q", "-m", f"work on {name}", cwd=wt)
        return self.git("rev-parse", "HEAD", cwd=wt)

    def row(self, wtname, status="busy", state="working", name=None, **extra):
        cwd = os.path.join(self.root, ".claude", "worktrees", wtname)
        return {"id": f"sess-{wtname}", "name": name or wtname, "cwd": cwd, "status": status,
                "state": state, **extra}

    def finished(self, wtname, **extra):
        return self.row(wtname, status="idle", state="done", **extra)

    def agents(self, *rows):
        with open(self.agents_file, "w") as fh:
            json.dump(list(rows), fh)

    def calls(self, command=None):
        if not os.path.isfile(self.log):
            return []
        with open(self.log) as fh:
            found = [json.loads(line) for line in fh if line.strip()]
        return [c for c in found if command is None or c[0] == command]

    def run_cmd(self, *args, pre=(), tg=TG, env=None, root=None):
        cmd = [sys.executable, RUN, "--root", root or self.root]
        if tg:
            cmd += ["--tg", tg]
        return subprocess.run(cmd + list(pre) + list(args), capture_output=True, text=True,
                              cwd=self.dir, env=env or self.env)

    def ok(self, *args, **kw):
        out = self.run_cmd(*args, **kw)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out

    def events(self, *args, **kw):
        out = self.ok(*args, pre=["--json"], **kw)
        return json.loads(out.stdout)

    @staticmethod
    def named(events, name):
        return [e for e in events if e["event"] == name]

    def one(self, events, name):
        found = self.named(events, name)
        self.assertEqual(len(found), 1, f"{name} in {[e['event'] for e in events]}")
        return found[0]

    @staticmethod
    def section(text, name):
        match = re.search(rf"(?ms)^## {name}\n\n(.*?)(?=^## |\Z)", text)
        return match.group(1).strip() if match else None

    def brief(self, task_id, *extra, **kw):
        return self.ok("launch", str(task_id), "--dry-run", *extra, **kw).stdout

    def pass_report(self, task_id=1, attempt=1, wt=None, head=None, branch=None):
        wt = wt or self.worktree(f"task-{task_id}-{attempt}")
        head = head or self.wt_commit(wt)
        self.add_result(task_id, "PASS", f"Task: {task_id}\nStatus: PASS\nBranch: {branch or f'worktree-task-{task_id}-{attempt}'}\n"
                        f"Head: {head}\nWorktree: {wt}\nCheckpoint: {CHECKPOINT}\n", attempt=attempt)
        return wt, head

    def running_task(self, attempt=1, **meta):
        return self.add_task(start=True, attempt=attempt, **meta)

    # --- common

    def test_01_not_a_repository_root(self):
        plain = os.path.join(self.dir, "plain")
        os.makedirs(plain)
        out = self.run_cmd("record", root=plain)
        self.assertEqual(out.returncode, 2)
        self.assertIn(plain, out.stderr)
        self.assertIn("not a repository root", out.stderr)
        sub = os.path.join(self.root, "sub")
        os.makedirs(sub)
        out = self.run_cmd("record", root=sub)
        self.assertEqual(out.returncode, 2)
        self.assertIn(sub, out.stderr)

    def test_02_config_problem(self):
        with open(os.path.join(self.root, ".agentic-team.toml"), "w") as fh:
            fh.write('[taskgraph]\nproject = "TODO"\n')
        out = self.run_cmd("record")
        self.assertEqual(out.returncode, 2)
        self.assertIn("taskgraph.project is TODO", out.stderr)

    def test_03_tg_resolution(self):
        env = dict(self.env, TASKGRAPH_TG=TG)
        self.assertEqual(self.run_cmd("record", tg=None, env=env).returncode, 0)
        out = self.run_cmd("record", tg=os.path.join(self.dir, "missing-tg.py"), env=env)
        self.assertEqual(out.returncode, 1)
        self.assertIn("tg", out.stderr)

    def test_04_json_is_one_array_and_refusals_stay_on_stderr(self):
        self.add_task()
        events = self.events("record")
        self.assertIsInstance(events, list)
        self.assertEqual(set(events[0]), {"event", "task", "attempt", "session", "detail", "next"})
        decision = self.tg("add", "Q?", "--type", "decision")["id"]
        out = self.run_cmd("launch", str(decision), pre=["--json"])
        self.assertEqual(out.returncode, 2)
        self.assertEqual(json.loads(out.stdout), [])
        self.assertTrue(out.stderr.startswith("run.py: "))

    # --- brief rendering, through launch --dry-run

    def test_05_label_lines_stay_in_goal(self):
        task = self.add_task(notes=textwrap.dedent("""
            Why: list stale domains.
            Serves: the ops team.
            Purpose: tidy up the registry.

            - [ ] every domain listed
        """).strip())
        text = self.brief(task)
        goal = self.section(text, "GOAL")
        for line in ("Why: list stale domains.", "Serves: the ops team.", "Purpose: tidy up the registry."):
            self.assertIn(line, goal)
        self.assertEqual(self.section(text, "ACCEPTANCE"), "- every domain listed")

    def test_05_known_labels_still_parse(self):
        task = self.add_task(notes=textwrap.dedent("""
            Why: list stale domains.
            Exit test: pytest passes
            exit tests: lint passes
            Acceptance: reviewed by a person
            - [x] checked item
        """).strip())
        text = self.brief(task)
        self.assertEqual(self.section(text, "GOAL"), "Sweep domains. Why: list stale domains.")
        self.assertEqual(self.section(text, "ACCEPTANCE").splitlines(),
                         ["- pytest passes", "- lint passes", "- reviewed by a person", "- checked item"])

    def test_06_unscoped_task_is_refused_with_the_fix(self):
        task = self.tg("add", "Sweep", "--notes", "Exit test: it works")["id"]
        out = self.run_cmd("launch", str(task), "--dry-run")
        self.assertEqual(out.returncode, 2)
        for word in ("not scoped", "GOAL", "SCOPE", "VERIFY", f"edit {task} --meta scope="):
            self.assertIn(word, out.stderr)
        self.assertNotIn("ACCEPTANCE", out.stderr)

    def test_07_result_command_and_keyword(self):
        task = self.add_task()
        text = self.brief(task)
        command = self.section(text, "REPORT")
        expected = (f'"{sys.executable}" "{TG}" --db "{self.db}" --project demo '
                    "result add 1 --kind task --attempt 1 --by task-1-1 --status <STATUS> --body-file -")
        self.assertIn(expected, command)
        self.assertIn("<<'REPORT'\n<your report>\nREPORT", command)
        self.assertIn(f'"{sys.executable}" "{TG}" --db "{self.db}" --project demo show 1', text)
        self.assertIn("--by task-1-1-sweep", self.brief(task, "--keyword", "sweep"))
        bad = self.run_cmd("launch", str(task), "--dry-run", "--keyword", "bad name")
        self.assertEqual(bad.returncode, 2)

    def test_08_default_database_is_home_taskgraph(self):
        env = {k: v for k, v in self.env.items() if k != "TASKGRAPH_DB"}
        task = self.add_task(env=env)
        text = self.brief(task, env=env)
        self.assertIn(f'--db "{os.path.join(self.home, ".taskgraph", "tasks.db")}"', text)

    def test_09_upstream_and_previous_report_come_from_results(self):
        up = self.add_task("Build base", "Why: base.\n- [ ] built")
        task = self.add_task("Use base", "Why: needs base.\n- [ ] used", depends=(up,), attempt=1)
        self.add_result(up, "PASS", "Task: 1\nFiles: base.txt\n", attempt=1)
        self.add_result(up, "DIED", "manager saw no session", attempt=2, by="manager")
        self.add_result(task, "ISSUES", f"Task: 2\nIssues: broken\nCheckpoint: {CHECKPOINT}\n", attempt=1)
        self.add_result(task, "DIED", "manager saw no session", attempt=2, by="manager")
        self.add_result(task, "BLOCKED", "permission prompt", attempt=2, by="manager")
        self.add_result(task, "PASS", "verifier said fine", kind="verify", attempt=1, by="verify-2-1")
        self.tg("done", str(up))
        text = self.brief(task)
        context = self.section(text, "CONTEXT")
        self.assertIn("### Previous attempt (result #3, ISSUES, attempt 1)", context)
        self.assertIn("Issues: broken", context)
        self.assertIn("### Upstream #1: Build base", context)
        self.assertIn("Files: base.txt", context)
        self.assertIn(f"Last checkpoint: {CHECKPOINT}", context)
        for skipped in ("manager saw no session", "permission prompt", "verifier said fine"):
            self.assertNotIn(skipped, text)
        self.assertIn("--attempt 2 --by task-2-2", text)
        self.add_result(task, "PASS", "report copied from the logs", attempt=1, by="manager")
        self.assertIn("report copied from the logs", self.brief(task))

    def test_09_upstream_without_result(self):
        up = self.add_task("Build base", "Why: base.\n- [ ] built")
        task = self.add_task("Use base", "Why: needs base.\n- [ ] used", depends=(up,))
        self.tg("done", str(up))
        self.assertIn("No report on file.", self.brief(task))

    def test_10_base_commit_sources(self):
        task = self.add_task(attempt=1)
        head = self.git("rev-parse", "HEAD")
        text = self.brief(task)
        self.assertIn(f"Base commit: {head}", text)
        self.assertIn(f"git reset --keep {head}", text)
        self.add_result(task, "PASS", f"Task: 1\nBranch: worktree-task-1-1\nHead: {SHA_A}\n")
        text = self.brief(task, "--attempt", "2")
        self.assertIn(f"git reset --keep {SHA_A}", text)
        self.assertNotIn(f"git reset --keep {head}", text)
        later = "b" * 40
        self.add_result(task, "STOPPED", f"Session: s\nWorktree: w\nBranch: b\nHead: {later}\nFiles: None\n",
                        attempt=2, by="manager")
        self.assertIn(f"git reset --keep {later}", self.brief(task, "--attempt", "3"))

    def test_11_report_command_runs_in_bash(self):
        odd = os.path.join(self.dir, "we ird $dir")
        os.makedirs(odd)
        os.symlink(os.path.dirname(TG), os.path.join(odd, "bin"))
        tg = os.path.join(odd, "bin", "tg.py")
        env = dict(self.env, TASKGRAPH_DB=os.path.join(odd, "my $db.sqlite"))
        task = self.add_task(env=env)
        text = self.brief(task, tg=tg, env=env)
        command = re.search(r"```sh\n(.*?)\n```", self.section(text, "REPORT"), re.S).group(1)
        body = "Task: 1\nStatus: PASS\nIssues: a $HOME `date` \"quoted\" line\n"
        command = command.replace("<STATUS>", "PASS").replace("<your report>", body.rstrip("\n"))
        out = subprocess.run(["bash", "-c", command], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = self.tg("result", "ls", str(task), env=env)[0]
        self.assertEqual((result["kind"], result["attempt"], result["author"], result["status"]),
                         ("task", 1, "task-1-1", "PASS"))
        self.assertEqual(result["body"], body)

    def test_12_forbidden_and_removed_sections(self):
        self.write_config('[constraints]\nforbidden = ["do not touch the lockfile", "send nothing"]\n')
        task = self.add_task()
        text = self.brief(task)
        self.assertEqual(self.section(text, "FORBIDDEN").splitlines(),
                         ["- do not touch the lockfile", "- send nothing"])
        for gone in ("Shared-file rules", "Supplemental plan", "Consultants", "Session:"):
            self.assertNotIn(gone, text)
        self.write_config("[constraints]\nforbidden = []\n")
        self.assertEqual(self.section(self.brief(task), "FORBIDDEN"), "None beyond the worker rules.")

    def test_13_verify_brief(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {SHA_A}\nFiles: out.txt\n")
        text = self.ok("verify", str(task), "--dry-run").stdout
        self.assertIn("Judge whether the output of task 1", self.section(text, "GOAL"))
        self.assertIn("Do not fix anything", self.section(text, "GOAL"))
        self.assertTrue(self.section(text, "SCOPE").startswith("Read only."))
        context = self.section(text, "CONTEXT")
        self.assertIn(f"Output under review: {SHA_A}", context)
        self.assertIn(f"git checkout --detach {SHA_A}", context)
        self.assertIn("### Worker report (result #1, PASS, attempt 1)", context)
        self.assertIn("Files: out.txt", context)
        self.assertIn("Last checkpoint: None", context)
        self.assertIn("Then exercise the real output", self.section(text, "VERIFY"))
        self.assertIn("--kind verify --attempt 1 --by verify-1-1 --status <STATUS>", text)
        self.assertIn("`Verdict:` line", self.section(text, "REPORT"))
        self.assertTrue(self.section(text, "AUTONOMY").startswith("- None."))
        self.assertEqual(self.calls("--bg"), [])

    # --- launch

    def test_14_stop_first_line_halts_launch(self):
        task = self.add_task()
        self.orders("# Standing orders\n\nSTOP: paused\n")
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 3)
        self.assertIn("STOP: paused", out.stderr)
        self.orders("1. STOP: paused\n")
        self.assertEqual(self.run_cmd("launch", str(task)).returncode, 3)
        self.orders("1. Keep tests green\nSTOP: paused\n")
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)
        self.orders("<!--\nSTOP: example\n-->\n\nNone yet.\n")
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)

    def test_15_launch_happy_path(self):
        task = self.add_task(verdict="test-verified", verdict_ref="abc1234")
        events = self.events("launch", str(task))
        launched = self.one(events, "launched")
        self.assertEqual((launched["task"], launched["attempt"], launched["session"]), (1, 1, "task-1-1"))
        self.assertIn("claude said: fake-session-id", launched["detail"])
        brief_path = os.path.join(self.root, ".agentic-team", "briefs", "task-1-1.md")
        with open(brief_path) as fh:
            text = fh.read()
        self.assertEqual(self.calls("--bg"), [[
            "--bg", "--worktree", "task-1-1", "--agent", "agentic-team:worker", "--model", "sonnet",
            "--effort", "high", "--permission-mode", "auto", "--name", "task-1-1", text]])
        self.assertEqual(self.status_of(task), "in_progress")
        meta = self.meta(task)
        self.assertEqual((meta["session"], meta["model"], meta["attempt"]), ("task-1-1", "sonnet", 1))
        self.assertRegex(meta["started_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$")
        self.assertNotIn("verdict", meta)
        self.assertNotIn("verdict_ref", meta)

    def test_15_started_at_is_set_on_every_launch(self):
        task = self.add_task()
        self.ok("launch", str(task))
        self.tg("edit", str(task), "--meta", 'started_at="2000-01-01 00:00 UTC"')
        self.ok("launch", str(task))
        self.assertNotEqual(self.meta(task)["started_at"], "2000-01-01 00:00 UTC")
        self.assertEqual(self.meta(task)["attempt"], 2)

    def test_16_model_resolution(self):
        self.write_config('[models.overrides]\n"data migration" = { model = "opus", effort = "high" }\n')
        mech = self.add_task(tier="mechanical")
        over = self.add_task(tier="data migration")
        plain = self.add_task()
        unknown = self.add_task(tier="poetry")

        def command(task, *extra):
            out = self.run_cmd("launch", str(task), "--dry-run", *extra)
            self.assertEqual(out.returncode, 0, out.stderr)
            return out.stderr

        self.assertIn("--model haiku --permission-mode", command(mech))
        self.assertIn("--model opus --effort high", command(over))
        self.assertIn("--model sonnet --effort high", command(plain))
        self.assertIn("--model opus --permission-mode", command(plain, "--tier", "judgement"))
        self.assertIn("--model x --effort low", command(plain, "--model", "x", "--effort", "low"))
        out = self.run_cmd("launch", str(unknown), "--dry-run")
        self.assertEqual(out.returncode, 2)
        self.assertIn("no tier or models.overrides entry named 'poetry'", out.stderr)

    def test_17_refusals_by_task_state(self):
        decision = self.tg("add", "Q?", "--type", "decision")["id"]
        out = self.run_cmd("launch", str(decision))
        self.assertEqual(out.returncode, 2)
        self.assertIn("is a decision", out.stderr)
        finished = self.add_task()
        self.tg("done", str(finished))
        out = self.run_cmd("launch", str(finished))
        self.assertEqual((out.returncode, "is done" in out.stderr), (2, True))
        blocked = self.add_task(depends=(self.add_task(),))
        out = self.run_cmd("launch", str(blocked))
        self.assertEqual(out.returncode, 2)
        self.assertIn("waits for #", out.stderr)

    def test_17_decision_that_blocks_a_started_task(self):
        task = self.running_task()
        self.add_result(task, "BLOCKED", "Task: 1\nStatus: BLOCKED\n")
        gate = self.tg("add", "Which way?", "--type", "decision", "--meta", "decider=operator", "--blocks", str(task))["id"]
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"waits for #{gate} (decision)", out.stderr)
        self.assertEqual(self.calls("--bg"), [])
        self.tg("edit", str(gate), "--notes", "go left")
        self.tg("done", str(gate))
        self.assertEqual(self.run_cmd("launch", str(task)).returncode, 0)

    def test_17_abandoned_task_needs_an_attempt(self):
        task = self.running_task(attempt=3, abandoned="died", verdict="check-only")
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("is abandoned (died)", out.stderr)
        self.assertIn("--attempt 4", out.stderr)
        self.ok("launch", str(task), "--attempt", "4")
        meta = self.meta(task)
        self.assertEqual(meta["attempt"], 4)
        self.assertNotIn("abandoned", meta)
        self.assertNotIn("verdict", meta)

    def test_17a_stopped_attempt_needs_record_first(self):
        task = self.running_task()
        wt = self.worktree("task-1-1")
        self.add_result(task, "STOPPED", f"Session: sess-task-1-1\nWorktree: {wt}\nBranch: worktree-task-1-1\n"
                        "Stopped: now\nFiles: wip.txt\n", by="manager")
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("run run.py record first", out.stderr)
        with open(os.path.join(wt, "wip.txt"), "w") as fh:
            fh.write("half done\n")
        self.agents()
        self.ok("record")
        head = self.git("rev-parse", "HEAD", cwd=wt)
        text = self.brief(task)
        self.assertIn(f"git reset --keep {head}", text)
        self.assertIn("--worktree task-1-2", self.run_cmd("launch", str(task), "--dry-run").stderr)

    def test_17b_verifier_tier_without_a_model(self):
        task = self.add_task(tier="verifier")
        out = self.run_cmd("launch", str(task), "--dry-run")
        self.assertEqual(out.returncode, 2)
        self.assertIn("has no model", out.stderr)
        self.write_config('[models]\nverifier = "opus"\n')
        self.assertIn("--model opus", self.run_cmd("launch", str(task), "--dry-run").stderr)

    def test_18_unmerged_dependency_blocks_launch(self):
        up = self.add_task("Build base", "Why: base.\n- [ ] built", attempt=1, verdict_ref=SHA_A)
        task = self.add_task("Use base", "Why: needs base.\n- [ ] used", depends=(up,))
        self.tg("done", str(up))
        out = self.run_cmd("launch", str(task), "--dry-run")
        self.assertEqual(out.returncode, 2)
        self.assertIn("worktree-task-1-1 is not merged", out.stderr)
        self.assertIn("run.py merged 1 --by operator", out.stderr)
        self.tg("edit", str(up), "--meta", 'merged_at="2026-10-26 10:00 UTC"')
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)
        self.tg("edit", str(up), "--unset-meta", "merged_at", "--meta", 'verdict_ref="abc123  out.txt"')
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)

    def test_19_attempt_cap(self):
        failed = self.running_task(attempt=3)
        self.add_result(failed, "ISSUES", "Task: 1\n", attempt=3)
        out = self.run_cmd("launch", str(failed), "--dry-run")
        self.assertEqual(out.returncode, 2)
        self.assertIn("attempt 3 has failed", out.stderr)
        self.assertIn("run.py abandon 1", out.stderr)
        self.assertIn("--worktree task-1-4", self.run_cmd("launch", str(failed), "--dry-run", "--attempt", "4").stderr)
        paused = self.running_task(attempt=3)
        self.add_result(paused, "STOPPED", f"Session: s\nWorktree: w\nBranch: b\nHead: {SHA_A}\nFiles: None\n",
                        attempt=3, by="manager")
        self.assertIn("--worktree task-2-4", self.run_cmd("launch", str(paused), "--dry-run").stderr)
        retry = self.running_task(attempt=2)
        self.assertIn("--worktree task-3-3", self.run_cmd("launch", str(retry), "--dry-run").stderr)

    def test_20_live_session_blocks_launch(self):
        task = self.running_task()
        self.agents(self.row("task-1-1", name="task-1-1-sweep"))
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("has a live session sess-task-1-1", out.stderr)
        self.agents(self.finished("task-1-1"))
        self.assertEqual(self.run_cmd("launch", str(task)).returncode, 0)

    def test_21_cap_counts_live_workers_and_verifiers(self):
        self.write_config(sessions="max_parallel = 1\n")
        task = self.add_task()
        self.agents(self.row("task-9-1"))
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("cap full: 1/1 sessions live", out.stderr)
        self.agents(self.finished("task-9-1"))
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)
        self.agents(self.row("verify-9-1"))
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 2)

    def test_22_untrusted_workspace(self):
        task = self.add_task()
        env = dict(self.env, FAKE_CLAUDE_UNTRUSTED="1")
        out = self.run_cmd("launch", str(task), env=env)
        self.assertEqual(out.returncode, 1)
        self.assertIn("not trusted", out.stderr)
        self.assertIn("accept the trust prompt", out.stderr)
        self.assertEqual(self.status_of(task), "open")
        self.assertNotIn("session", self.meta(task))

    def test_23_second_launch_is_attempt_two(self):
        task = self.add_task()
        self.ok("launch", str(task))
        self.ok("launch", str(task))
        self.assertEqual([c[2] for c in self.calls("--bg")], ["task-1-1", "task-1-2"])
        self.assertEqual(self.meta(task)["session"], "task-1-2")

    # --- verify

    def test_24_verify_refusals(self):
        task = self.running_task()
        out = self.run_cmd("verify", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("no worker result for attempt 1", out.stderr)
        self.add_result(task, "ISSUES", "Task: 1\n")
        out = self.run_cmd("verify", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("reported ISSUES, not PASS", out.stderr)
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\nFiles: sums.txt\n")
        out = self.run_cmd("verify", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("has no Head: line; pass --ref", out.stderr)
        accepted = self.run_cmd("verify", str(task), "--ref", "sums.txt abc", "--dry-run")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("Output under review: sums.txt abc", accepted.stdout)
        idle = self.add_task()
        self.assertEqual(self.run_cmd("verify", str(idle)).returncode, 2)

    def test_25_verify_happy_path(self):
        task = self.running_task(session="task-1-1", model="sonnet")
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {SHA_A}\n")
        before = self.meta(task)
        self.ok("verify", str(task))
        argv = self.calls("--bg")[0]
        self.assertEqual(argv[:-1], ["--bg", "--worktree", "verify-1-1", "--agent", "agentic-team:worker",
                                     "--model", "opus", "--permission-mode", "auto", "--name", "verify-1-1"])
        with open(os.path.join(self.root, ".agentic-team", "briefs", "task-1-1-verify.md")) as fh:
            self.assertEqual(fh.read(), argv[-1])
        self.assertEqual(self.meta(task), before)
        self.assertEqual(self.status_of(task), "in_progress")

    def test_25_verifier_model_choice(self):
        task = self.running_task(model="opus")
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {SHA_A}\n")
        self.assertIn("--model sonnet", self.run_cmd("verify", str(task), "--dry-run").stderr)
        self.write_config('[models]\nverifier = { model = "haiku", effort = "low" }\n')
        self.ok("verify", str(task))
        argv = self.calls("--bg")[0]
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[argv.index("--effort") + 1], "low")

    def test_26_existing_verdict_blocks_a_second_verifier(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {SHA_A}\n")
        self.add_result(task, "BLOCKED", "Verdict: verify-blocked\n", kind="verify", by="verify-1-1")
        out = self.run_cmd("verify", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("already has verify result #2 (Verdict: verify-blocked)", out.stderr)
        self.agents(self.finished("verify-1-1"))
        self.ok("verify", str(task), "--again")
        argv = self.calls("--bg")[0]
        self.assertIn("verify-1-1-2", argv)
        self.assertEqual(argv[argv.index("--worktree") + 1], "verify-1-1-2")
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".agentic-team", "briefs", "task-1-1-verify-2.md")))

    def test_26_manager_verify_row_does_not_block(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {SHA_A}\n")
        self.add_result(task, "PASS", "Verdict: test-verified\nRan: make test\n", kind="verify", by="manager")
        self.assertEqual(self.run_cmd("verify", str(task), "--dry-run").returncode, 0)

    def test_26_running_verifier_blocks(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {SHA_A}\n")
        self.agents(self.row("verify-1-1"))
        out = self.run_cmd("verify", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("is still running", out.stderr)

    def test_27_verify_launches_under_stop(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {SHA_A}\n")
        self.orders("STOP: paused\n")
        self.ok("verify", str(task))
        self.assertEqual(len(self.calls("--bg")), 1)

    # --- record

    def test_28_arrived_pass(self):
        low = self.running_task()
        high = self.running_task(risk="high")
        self.add_result(low, "PASS", "Task: 1\n")
        self.add_result(high, "PASS", "Task: 2\n")
        arrived = {e["task"]: e for e in self.named(self.events("record"), "arrived")}
        self.assertIn("run.py close 1", arrived[1]["next"])
        self.assertIn("rerun VERIFY", arrived[1]["next"])
        self.assertEqual(arrived[2]["next"], "run.py verify 2")
        self.assertEqual(arrived[1]["detail"], "PASS by worker (result #1)")
        text = self.ok("record").stdout
        self.assertIn("arrived #1 attempt 1: PASS by worker (result #1) | next:", text)

    def test_29_verifier_sessions(self):
        task = self.running_task()
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\n")
        self.agents(self.row("verify-1-1"))
        self.assertEqual(len(self.named(self.events("record"), "verifying")), 1)
        self.agents(self.row("verify-1-1", status="waiting", state="blocked", waitingFor="permission"))
        stuck = self.one(self.events("record"), "stuck")
        self.assertIn("sess-verify-1-1", stuck["detail"])
        self.assertIn(["stop", "sess-verify-1-1"], self.calls("stop"))
        filed = [r for r in self.results(task) if r["kind"] == "verify"]
        self.assertEqual([(r["status"], r["author"]) for r in filed], [("BLOCKED", "manager")])

    def test_29_finished_verifier_with_no_result_is_filed_once(self):
        task = self.running_task()
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\n")
        self.agents(self.finished("verify-1-1"))
        first = self.events("record")
        self.assertEqual(self.one(first, "verifier-died")["task"], 1)
        self.assertEqual(len(self.named(first, "arrived")), 1)
        second = self.events("record")
        self.assertEqual(self.named(second, "verifier-died"), [])
        died = [r for r in self.results(task) if r["kind"] == "verify" and r["status"] == "DIED"]
        self.assertEqual(len(died), 1)
        self.assertEqual(died[0]["author"], "manager")

    def test_30_verified_events(self):
        task = self.running_task()
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\n")
        self.add_result(task, "PASS", "Verdict: test-verified\nRan: make test\n", kind="verify", by="manager")
        events = self.events("record")
        self.assertEqual(self.named(events, "verified"), [])
        self.assertEqual(len(self.named(events, "arrived")), 1)
        self.add_result(task, "PASS", "Status: PASS\nVerdict: test-verified\n", kind="verify", by="verify-1-1")
        verified = self.one(self.events("record"), "verified")
        self.assertIn("Verdict test-verified by verify-1-1 (result #3)", verified["detail"])
        self.assertEqual(verified["next"], "run run.py close 1")

    def test_30_second_verifier_beats_an_old_verdict(self):
        task = self.running_task(verdict="verify-blocked")
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\n")
        self.add_result(task, "BLOCKED", "Verdict: verify-blocked\n", kind="verify", by="verify-1-1")
        self.assertEqual(len(self.named(self.events("record"), "unclosed")), 1)
        self.add_result(task, "PASS", "Verdict: test-verified\n", kind="verify", by="verify-1-1-2")
        events = self.events("record")
        self.assertEqual(self.named(events, "unclosed"), [])
        self.assertIn("Verdict test-verified", self.one(events, "verified")["detail"])

    def test_30_verifier_result_without_a_verdict_line(self):
        task = self.running_task()
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\n")
        self.add_result(task, "PASS", "all fine\n", kind="verify", by="verify-1-1")
        verified = self.one(self.events("record"), "verified")
        self.assertIn("no Verdict line", verified["detail"])
        self.assertIn("--verdict L", verified["next"])

    def test_31_unclosed_next_step_by_verdict(self):
        wanted = {"verify-blocked": "retry the check", "verify-failed": "fix round: run.py launch",
                  "check-only": "run.py verify", "test-verified": "run run.py close",
                  "artifact-verified": "run run.py close"}
        for verdict, text in wanted.items():
            task = self.running_task(verdict=verdict)
            self.add_result(task, "PASS", "Task: 1\n")
        found = {e["task"]: e for e in self.named(self.events("record"), "unclosed")}
        self.assertEqual(len(found), 5)
        for index, (verdict, text) in enumerate(wanted.items(), start=1):
            self.assertIn(f"verdict {verdict}", found[index]["detail"])
            self.assertIn(text, found[index]["next"])
        self.assertIn("--again", found[3]["next"])

    def test_32_stuck_worker_is_stopped_and_filed(self):
        task = self.running_task()
        self.agents(self.row("task-1-1", status="waiting", state="working", waitingFor="Bash permission"))
        stuck = self.one(self.events("record"), "stuck")
        self.assertIn("Bash permission", stuck["detail"])
        self.assertIn("--model sonnet", stuck["next"])
        self.assertIn(["stop", "sess-task-1-1"], self.calls("stop"))
        filed = self.results(task)
        self.assertEqual([(r["status"], r["author"], r["attempt"]) for r in filed], [("BLOCKED", "manager", 1)])
        self.assertIn("Bash permission", filed[0]["body"])
        self.assertIn("Session: sess-task-1-1", filed[0]["body"])
        self.running_task()
        self.agents(self.row("task-2-1", status="idle", state="blocked"))
        again = {e["task"]: e for e in self.named(self.events("record"), "stuck")}
        self.assertEqual(again[1]["detail"], "filed earlier")
        self.assertIn("stopped sess-task-2-1", again[2]["detail"])

    def test_33_busy_and_unknown_rows(self):
        busy = self.running_task()
        odd = self.running_task()
        self.agents(self.row("task-1-1"), self.row("task-2-1", status="idle", state="foo"))
        events = self.events("record")
        self.assertEqual(self.one(events, "running")["task"], busy)
        unknown = self.one(events, "unknown")
        self.assertEqual(unknown["task"], odd)
        self.assertIn("not filed as DIED", unknown["detail"])
        self.assertEqual(self.results(odd), [])

    def test_34_finished_session_with_a_complete_report_is_salvaged(self):
        task = self.running_task()
        self.agents(self.finished("task-1-1"))
        report = (f"Task: 1\nStatus: ISSUES\nBranch: worktree-task-1-1\nHead: {SHA_A}\n"
                  f"Issues: one\nCheckpoint: {CHECKPOINT}\n")
        with open(os.path.join(self.logs, "sess-task-1-1.txt"), "w") as fh:
            fh.write("tool output\nTask: 1 started\nTask: 1\n" + "old\n" + "Task: 1\n" + report[len("Task: 1\n"):]
                     + '{"id": 5, "status": "PASS"}\nsession ended\n')
        events = self.events("record")
        salvaged = self.one(events, "salvaged")
        self.assertIn("ISSUES from claude logs sess-task-1-1 (result #1)", salvaged["detail"])
        arrived = self.one(events, "arrived")
        self.assertIn("ISSUES by manager (result #1)", arrived["detail"])
        row = self.results(task)[0]
        self.assertEqual((row["status"], row["author"], row["kind"]), ("ISSUES", "manager", "task"))
        self.assertEqual(row["body"], report)

    def test_35_incomplete_logs_file_died(self):
        task = self.running_task(attempt=3)
        early = self.running_task(attempt=1)
        gone = self.running_task(attempt=2)
        self.agents(self.finished("task-1-3"), self.finished("task-2-1"))
        with open(os.path.join(self.logs, "sess-task-1-3.txt"), "w") as fh:
            fh.write("Task: 1\nStatus: PASS\n")  # no Checkpoint line: incomplete
        events = {e["task"]: e for e in self.named(self.events("record"), "died")}
        self.assertIn("abandon 1 died", events[task]["next"])
        self.assertEqual(events[early]["next"], f"run.py launch {early}")
        self.assertIn("no result", self.results(early)[0]["body"])
        self.assertIn("status", self.results(early)[0]["body"].replace("idle/done", "status"))
        self.assertIn("no session for .claude/worktrees/task-3-2", self.results(gone)[0]["body"])
        self.assertEqual([r["status"] for r in self.results(task)], ["DIED"])

    def test_36_pause_phase_one_commits_the_wip(self):
        task = self.running_task()
        wt = self.worktree("task-1-1")
        base = self.git("rev-parse", "HEAD", cwd=wt)
        with open(os.path.join(wt, "wip.txt"), "w") as fh:
            fh.write("half\n")
        self.add_result(task, "STOPPED", f"Session: sess-task-1-1\nWorktree: {wt}\nBranch: worktree-task-1-1\n"
                        "Stopped: now\nFiles: ?? wip.txt\n", by="manager")
        self.agents(self.row("task-1-1", status="busy"))
        busy = self.events("record")
        self.assertEqual(len(self.named(busy, "stopping")), 1)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), base)
        self.assertEqual(len(self.results(task)), 1)
        self.agents()
        stopped = self.one(self.events("record"), "stopped")
        head = self.git("rev-parse", "HEAD", cwd=wt)
        self.assertNotEqual(head, base)
        self.assertEqual(self.git("log", "-1", "--format=%s", cwd=wt), "WIP task 1 attempt 1: stopped by pause")
        self.assertIn(f"WIP committed {head} on worktree-task-1-1", stopped["detail"])
        latest = self.results(task)[-1]
        self.assertEqual((latest["status"], latest["author"]), ("STOPPED", "manager"))
        self.assertIn(f"Head: {head}", latest["body"])
        self.assertIn("Files: ?? wip.txt", latest["body"])

    def test_36_clean_worktree_is_not_committed(self):
        task = self.running_task()
        wt = self.worktree("task-1-1")
        base = self.git("rev-parse", "HEAD", cwd=wt)
        self.add_result(task, "STOPPED", f"Session: s\nWorktree: {wt}\nBranch: b\nStopped: now\nFiles: None\n", by="manager")
        self.ok("record")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), base)
        self.assertIn(f"Head: {base}", self.results(task)[-1]["body"])

    def test_36_missing_worktree_files_head_none(self):
        task = self.running_task()
        self.add_result(task, "STOPPED", "Session: s\nWorktree: /nowhere/task-1-1\nBranch: b\nStopped: now\nFiles: None\n",
                        by="manager")
        stopped = self.one(self.events("record"), "stopped")
        self.assertIn("worktree missing", stopped["detail"])
        self.assertIn("Head: None", self.results(task)[-1]["body"])
        self.assertEqual(len(self.named(self.events("record"), "stopped")), 1)

    def stopped_row(self, name, sid="e6ebab39"):
        # What the real CLI lists in --all after `claude stop`: no status, state "stopped",
        # and a working directory that is not the worktree.
        return {"id": sid, "cwd": os.path.join(self.dir, "elsewhere"), "kind": "background",
                "startedAt": 1761000000000, "sessionId": "0d7c-stopped", "name": name, "state": "stopped"}

    def test_36_stopped_session_is_matched_by_its_recorded_id_and_its_wip_committed(self):
        task = self.running_task()
        wt = self.worktree("task-1-1")
        base = self.git("rev-parse", "HEAD", cwd=wt)
        self.agents(self.row("task-1-1", name="task-1-1-smoke"))
        self.ok("stop", str(task))
        self.assertIn(f"Worktree: {wt}", self.results(task)[0]["body"])
        with open(os.path.join(wt, "wip.txt"), "w") as fh:
            fh.write("half\n")
        self.agents(self.stopped_row("task-1-1-smoke", sid="sess-task-1-1"))
        stopped = self.one(self.events("record"), "stopped")
        head = self.git("rev-parse", "HEAD", cwd=wt)
        self.assertNotEqual(head, base)
        self.assertEqual(self.git("log", "-1", "--format=%s", cwd=wt), "WIP task 1 attempt 1: stopped by pause")
        self.assertIn(f"WIP committed {head}", stopped["detail"])
        self.assertEqual(stopped["session"], "sess-task-1-1")
        latest = self.results(task)[-1]
        self.assertIn(f"Worktree: {wt}", latest["body"])
        self.assertIn(f"Head: {head}", latest["body"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "elsewhere")))

    def test_36_stopped_session_is_not_live_and_not_counted(self):
        self.write_config(sessions="max_parallel = 1\n")
        task = self.add_task()
        running = self.running_task(attempt=1)
        self.add_result(running, "STOPPED", "Session: e6ebab39\nWorktree: x/task-2-1\nFiles: None\n", by="manager")
        self.agents(self.stopped_row("task-2-1-smoke"), self.stopped_row("task-9-1-smoke", sid="f00d"))
        self.assertEqual(self.one(self.events("record"), "slots")["detail"], "0/1 live")
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)

    def test_36_foreign_live_rows_are_ignored(self):
        self.write_config(sessions="max_parallel = 1\n")
        task = self.add_task()
        running = self.running_task(attempt=1)
        foreign_cwd = os.path.join(self.dir, "other-repo", ".claude", "worktrees", f"task-{running}-1")
        foreign = {"id": "foreign-1", "name": f"task-{running}-1", "cwd": foreign_cwd, "status": "busy", "state": "working"}
        stuck = dict(foreign, id="foreign-2", name=f"task-{task}-1", status="waiting", state="blocked",
                     waitingFor="permission")
        self.agents(foreign, stuck)
        events = self.events("record")
        self.assertEqual(self.one(events, "slots")["detail"], "0/1 live")
        self.assertEqual(self.named(events, "running"), [])
        self.assertEqual(self.one(events, "died")["task"], running)
        self.assertEqual(self.calls("stop"), [])
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)
        verify = self.running_task(attempt=1)
        self.add_result(verify, "PASS", f"Task: {verify}\nStatus: PASS\nHead: {SHA_A}\n")
        self.agents(dict(foreign, name=f"verify-{verify}-1", cwd=foreign_cwd.replace("task-", "verify-")))
        self.assertEqual(self.run_cmd("verify", str(verify), "--dry-run").returncode, 0)

    def test_36_foreign_stopped_rows_are_never_stopped_or_removed(self):
        task = self.add_task(attempt=1, verdict_ref=SHA_A, merged_at="x", merged_by="operator")
        self.tg("done", str(task))
        self.agents(self.stopped_row("task-1-1-smoke", sid="foreign-stopped"),
                    self.stopped_row("verify-1-1", sid="foreign-verify"))
        events = self.events("record")
        self.assertEqual(self.named(events, "removed") + self.named(events, "kept"), [])
        self.events("merged", str(task))
        self.assertEqual(self.calls("rm"), [])
        self.assertEqual(self.calls("stop"), [])

    def test_36_stopped_worker_without_a_recorded_id_is_no_session(self):
        task = self.running_task()
        self.agents(self.stopped_row("task-1-1-smoke"))
        died = self.one(self.events("record"), "died")
        self.assertEqual(died["task"], task)
        self.assertIsNone(died["session"])
        self.assertIn("no session for .claude/worktrees/task-1-1", self.results(task)[0]["body"])

    def test_36_stopped_session_tokens_use_the_derived_worktree(self):
        task = self.running_task()
        wt, _ = self.pass_report(task)
        self.add_result(task, "STOPPED", f"Session: e6ebab39\nWorktree: {wt}\nFiles: None\n", by="manager")
        self.agents(self.stopped_row("task-1-1-smoke"))
        self.transcript_for(wt, "0d7c-stopped.jsonl", tokens=9)
        self.ok("close", str(task), "--verdict", "test-verified")
        self.assertEqual(self.meta(task)["tokens"], "9/3")

    def test_37_stopped_with_a_head_files_nothing(self):
        task = self.running_task()
        self.add_result(task, "STOPPED", f"Session: s\nWorktree: w\nBranch: b\nHead: {SHA_A}\nFiles: None\n", by="manager")
        stopped = self.one(self.events("record"), "stopped")
        self.assertIn(f"head {SHA_A}", stopped["detail"])
        self.assertEqual(len(self.results(task)), 1)

    def test_38_gated_by_an_open_decision(self):
        task = self.running_task()
        self.add_result(task, "BLOCKED", "Task: 1\nStatus: BLOCKED\nIssues: which API?\n")
        gate = self.tg("add", "Which API?", "--type", "decision", "--meta", "decider=operator", "--blocks", str(task))["id"]
        events = self.events("record")
        gated = self.one(events, "gated")
        self.assertIn(f'waits for decision #{gate} "Which API?"', gated["detail"])
        self.assertEqual(self.named(events, "arrived"), [])

    def test_39_merged_branch_is_recorded_and_unmerged_is_listed(self):
        task = self.add_task(attempt=1)
        wt = self.worktree("task-1-1")
        head = self.wt_commit(wt)
        later = self.add_task("Use base", depends=(task,))
        self.tg("edit", str(task), "--meta", f"verdict_ref={head}", "verdict=test-verified")
        self.tg("done", str(task))
        unmerged = self.one(self.events("record"), "unmerged")
        self.assertIn("worktree-task-1-1", unmerged["detail"])
        self.assertIn(f"blocks #{later}", unmerged["detail"])
        self.assertNotIn("merged_at", self.meta(task))
        self.git("merge", "--no-ff", "-q", "-m", "merge", "worktree-task-1-1")
        merged = self.one(self.events("record"), "merged")
        self.assertIn("recorded merged_by=operator", merged["detail"])
        meta = self.meta(task)
        self.assertEqual(meta["merged_by"], "operator")
        self.assertRegex(meta["merged_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$")

    def test_39_recorded_merge_runs_cleanup(self):
        task = self.add_task(attempt=1)
        wt = self.worktree("task-1-1")
        head = self.wt_commit(wt)
        self.git("merge", "--no-ff", "-q", "-m", "merge", "worktree-task-1-1")
        self.tg("edit", str(task), "--meta", f"verdict_ref={head}")
        self.tg("done", str(task))
        self.agents(self.finished("task-1-1"))
        events = self.events("record")
        self.assertEqual(len(self.named(events, "merged")), 1)
        self.assertEqual(self.one(events, "removed")["session"], "sess-task-1-1")
        self.assertIn(["rm", "sess-task-1-1"], self.calls("rm"))

    def test_40_leftover_rows_of_a_merged_task_are_removed(self):
        task = self.add_task(attempt=1, verdict_ref=SHA_A, merged_at="x", merged_by="operator")
        self.tg("done", str(task))
        self.agents(self.finished("task-1-1"), self.finished("verify-1-1"))
        events = self.events("record")
        self.assertEqual(sorted(e["session"] for e in self.named(events, "removed")),
                         ["sess-task-1-1", "sess-verify-1-1"])
        self.assertEqual(len(self.calls("rm")), 2)

    def test_41_decisions_and_ready_lists(self):
        base = self.add_task("Base", attempt=1, verdict_ref=SHA_A)
        self.tg("done", str(base))
        behind = self.add_task("Behind", depends=(base,))
        free = self.add_task("Free")
        held = self.add_task("Held")
        gate = self.tg("add", "Pick a name", "--type", "decision", "--meta", "decider=operator",
                       "--due", "2026-11-01", "--blocks", str(held))["id"]
        undated = self.tg("add", "Pick a colour", "--type", "decision")["id"]
        events = self.events("record")
        decisions = {e["task"]: e["detail"] for e in self.named(events, "decision")}
        self.assertEqual(decisions[gate], '"Pick a name" decider operator by 2026-11-01 blocks #' + str(held))
        self.assertEqual(decisions[undated], '"Pick a colour" decider none by no date blocks none')
        self.assertEqual(self.one(events, "ready")["detail"], f"#{free}")
        self.assertEqual(self.one(events, "waits")["task"], behind)
        self.assertIn(f"dependency #{base} not merged", self.one(events, "waits")["detail"])
        text = self.ok("record").stdout
        self.assertIn(f"decision #{gate}: ", text)
        self.assertIn(f"ready: #{free}", text)

    def test_41_nothing_ready(self):
        self.assertEqual(self.one(self.events("record"), "ready")["detail"], "none")

    def test_42_slots_count_live_rows_only(self):
        self.agents(self.row("task-5-1"), self.finished("task-6-1"), self.row("verify-7-1", status="waiting"))
        self.assertEqual(self.one(self.events("record"), "slots")["detail"], "2/2 live")

    def test_43_abandoned_tasks_are_skipped(self):
        task = self.running_task(attempt=3, abandoned="died")
        done = self.add_task(attempt=1, verdict_ref=SHA_A, merged_at="x", abandoned="died")
        self.tg("done", str(done))
        self.agents(self.finished("task-1-3"), self.finished("task-2-1"))
        events = self.events("record")
        self.assertEqual([e for e in events if e["task"] in (task, done)], [])
        self.assertEqual(self.calls("rm"), [])
        self.assertEqual(self.calls("stop"), [])

    # --- close

    def test_44_close_needs_a_passing_worker_result(self):
        task = self.running_task()
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn("no worker result for attempt 1", out.stderr)
        self.add_result(task, "ISSUES", "Task: 1\n")
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn("reported ISSUES, not PASS", out.stderr)

    def test_45_manager_verdict_is_filed(self):
        task = self.running_task()
        self.pass_report(task)
        out = self.run_cmd("close", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("has no verifier verdict", out.stderr)
        self.ok("close", str(task), "--verdict", "test-verified", "--ran", "pytest ok")
        filed = [r for r in self.results(task) if r["kind"] == "verify"][-1]
        self.assertEqual((filed["status"], filed["author"]), ("PASS", "manager"))
        self.assertIn("Verdict: test-verified", filed["body"])
        self.assertIn("Ran: pytest ok", filed["body"])
        self.assertEqual(self.status_of(task), "done")

    def test_45_failed_and_blocked_verdicts_map_to_statuses(self):
        task = self.running_task()
        self.pass_report(task)
        self.ok("close", str(task), "--verdict", "verify-failed")
        self.ok("close", str(task), "--verdict", "verify-blocked", "--ran", "no network")
        filed = [r for r in self.results(task) if r["kind"] == "verify"]
        self.assertEqual([r["status"] for r in filed], ["ISSUES", "BLOCKED"])
        self.assertIn("Ran: not stated", filed[0]["body"])

    def test_46_verifier_verdict_is_used(self):
        task = self.running_task()
        self.pass_report(task)
        self.add_result(task, "PASS", "Status: PASS\nVerdict: artifact-verified\n", kind="verify", by="verify-1-1")
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn("verifier verify-1-1 said artifact-verified", out.stderr)
        events = self.events("close", str(task))
        self.assertIn("artifact-verified at", self.one(events, "closed")["detail"])
        self.assertEqual(self.meta(task)["verdict"], "artifact-verified")
        self.assertEqual([r["author"] for r in self.results(task) if r["kind"] == "verify"], ["verify-1-1"])

    def test_47_output_must_not_change_after_the_verdict(self):
        task = self.running_task()
        wt, head = self.pass_report(task)
        self.wt_commit(wt, "more.txt")
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn("the output changed after the verdict", out.stderr)
        self.assertEqual(self.status_of(task), "in_progress")
        self.assertNotIn("verdict", self.meta(task))
        self.assertEqual([r for r in self.results(task) if r["kind"] == "verify"], [])

    def test_47_missing_branch_and_checksum_output(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nBranch: worktree-gone\nHead: {SHA_A}\n")
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn("branch worktree-gone not found", out.stderr)
        self.ok("close", str(task), "--verdict", "artifact-verified", "--ref", "abc123  out.txt")
        self.assertEqual(self.meta(task)["verdict_ref"], "abc123  out.txt")
        self.assertEqual(self.status_of(task), "done")
        self.assertEqual(self.calls("--bg"), [])

    def test_48_check_only_does_not_close(self):
        task = self.running_task()
        self.pass_report(task)
        events = self.events("close", str(task), "--verdict", "check-only")
        self.assertIn("check-only; not closed", self.one(events, "verdict")["detail"])
        self.assertEqual(self.named(events, "closed"), [])
        self.assertEqual(self.status_of(task), "in_progress")
        meta = self.meta(task)
        self.assertEqual(meta["verdict"], "check-only")
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", meta["verdict_ref"]))

    def transcript_for(self, wt, name, tokens=11, folder=None):
        folder = os.path.join(self.home, ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", folder or wt))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "w") as fh:
            fh.write(transcript(tokens))

    def test_49_tokens_from_the_transcript(self):
        task = self.running_task()
        wt, head = self.pass_report(task)
        self.agents(self.finished("task-1-1", sessionId="abc123-full"))
        self.transcript_for(wt, "abc123-full.jsonl")
        events = self.events("close", str(task), "--verdict", "test-verified")
        self.assertEqual(self.meta(task)["tokens"], "11/3")
        self.assertIn("out 11 in 3 cache-read 5 cache-write 7", self.one(events, "tokens")["detail"])

    def test_49_missing_foreign_and_ambiguous_transcripts(self):
        for case in ("missing", "foreign", "ambiguous"):
            with self.subTest(case):
                task = self.running_task(attempt=1)
                wt, _ = self.pass_report(task, attempt=1, wt=self.worktree(f"task-{task}-1"))
                self.agents(self.finished(f"task-{task}-1", sessionId="abc123"))
                if case == "foreign":
                    self.transcript_for(wt, "abc123.jsonl", folder="/work/other-project")
                if case == "ambiguous":
                    self.transcript_for(wt, "abc123-a.jsonl")
                    self.transcript_for(wt, "abc123-b.jsonl")
                events = self.events("close", str(task), "--verdict", "test-verified")
                self.assertIn("none recorded", self.one(events, "tokens")["detail"])
                self.assertNotIn("tokens", self.meta(task))

    def test_49_session_id_falls_back_to_the_row_id(self):
        task = self.running_task()
        wt, _ = self.pass_report(task)
        self.agents(self.finished("task-1-1"))
        self.transcript_for(wt, "sess-task-1-1.jsonl", tokens=4)
        self.ok("close", str(task), "--verdict", "test-verified")
        self.assertEqual(self.meta(task)["tokens"], "4/3")

    def test_50_close_marks_done_and_stops_the_session(self):
        task = self.running_task()
        self.pass_report(task)
        self.agents(self.row("task-1-1"))
        later = self.add_task("Next", depends=(task,))
        events = self.events("close", str(task), "--verdict", "test-verified", "--ran", "make test")
        closed = self.one(events, "closed")
        self.assertEqual(self.one(events, "waits")["task"], later)
        self.assertIn("test-verified at", closed["detail"])
        self.assertIn("branch worktree-task-1-1", closed["detail"])
        self.assertEqual(self.status_of(task), "done")
        self.assertIn(["stop", "sess-task-1-1"], self.calls("stop"))
        stopped = [r for r in self.results(task) if r["status"] == "STOPPED"]
        self.assertEqual(len(stopped), 1)
        self.assertIn("Session: sess-task-1-1", stopped[0]["body"])
        self.assertEqual(self.one(events, "ready")["detail"], "none")

    def merge_setup(self):
        task = self.running_task()
        wt, head = self.pass_report(task)
        self.agents(self.finished("task-1-1"))
        return task, wt, head

    def merges(self):
        return self.git("log", "--merges", "--format=%s")

    def test_51_no_merge_line_lists_the_branch(self):
        task, wt, head = self.merge_setup()
        before = self.git("rev-parse", "HEAD")
        events = self.events("close", str(task), "--verdict", "test-verified")
        ready = self.one(events, "ready-to-merge")
        self.assertEqual(ready["detail"], "branch worktree-task-1-1")
        self.assertIn(f"run.py merged {task} --by operator", ready["next"])
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(self.named(events, "merged"), [])
        self.assertEqual(self.calls("rm"), [])

    def test_51_merge_line_merges_into_a_clean_checkout(self):
        task, wt, head = self.merge_setup()
        self.orders("# Standing orders\n\n1. Keep tests green\n2. MERGE: verified branches into main\n")
        events = self.events("close", str(task), "--verdict", "test-verified")
        merged = self.one(events, "merged")
        self.assertIn("worktree-task-1-1 into", merged["detail"])
        self.assertEqual(self.merges(), "Merge worktree-task-1-1 (task #1)")
        meta = self.meta(task)
        self.assertEqual(meta["merged_by"], "manager")
        self.assertIn("merged_at", meta)
        self.assertIn(["rm", "sess-task-1-1"], self.calls("rm"))

    def test_51_dirty_checkout_detached_head_and_stop(self):
        task, wt, head = self.merge_setup()
        self.orders("MERGE: verified branches into main\n")
        with open(os.path.join(self.root, "dirty.txt"), "w") as fh:
            fh.write("x\n")
        events = self.events("close", str(task), "--verdict", "test-verified")
        self.assertIn("main checkout is not clean", self.one(events, "ready-to-merge")["detail"])
        self.assertEqual(self.merges(), "")
        os.remove(os.path.join(self.root, "dirty.txt"))
        self.git("checkout", "-q", "--detach")
        other = self.running_task()
        self.pass_report(other, wt=self.worktree("task-2-1"))
        events = self.events("close", str(other), "--verdict", "test-verified")
        self.assertIn("main checkout is detached", self.one(events, "ready-to-merge")["detail"])

    def test_51_stop_blocks_the_merge(self):
        task, wt, head = self.merge_setup()
        self.orders("STOP: paused\nMERGE: verified branches into main\n")
        events = self.events("close", str(task), "--verdict", "test-verified")
        self.assertIn("not merged during a pause", self.one(events, "ready-to-merge")["detail"])
        self.assertEqual(self.merges(), "")
        self.assertEqual(self.status_of(task), "done")

    def test_51_conflict_is_aborted(self):
        with open(os.path.join(self.root, "f.txt"), "w") as fh:
            fh.write("one\n")
        self.git("add", "f.txt")
        self.git("commit", "-q", "-m", "add f")
        task = self.running_task()
        wt = self.worktree("task-1-1")
        head = self.wt_commit(wt, "f.txt", "theirs\n")
        self.pass_report(task, wt=wt, head=head)
        with open(os.path.join(self.root, "f.txt"), "w") as fh:
            fh.write("ours\n")
        self.git("commit", "-q", "-am", "ours")
        later = self.add_task("Next", depends=(task,))
        self.orders("MERGE: verified branches into main\n")
        out = self.ok("close", str(task), "--verdict", "test-verified", pre=["--json"])
        events = json.loads(out.stdout)
        conflict = self.one(events, "conflict")
        self.assertIn("merge aborted", conflict["detail"])
        self.assertIn("--type decision", conflict["next"])
        self.assertIn(f"--blocks {later}", conflict["next"])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".git", "MERGE_HEAD")))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertNotIn("merged_at", self.meta(task))

    # --- merged and cleanup

    def closed_task(self, merged=False):
        task = self.add_task(attempt=1, verdict_ref=SHA_A, verdict="test-verified")
        if merged:
            self.tg("edit", str(task), "--meta", 'merged_at="2026-10-26 10:00 UTC"', "merged_by=operator")
        self.tg("done", str(task))
        return task

    def test_52_merged_records_the_operators_word(self):
        task = self.closed_task()
        events = self.events("merged", str(task))
        self.assertEqual(self.one(events, "merged")["detail"], "recorded merged_by=operator")
        meta = self.meta(task)
        self.assertEqual(meta["merged_by"], "operator")
        self.assertIn("merged_at", meta)
        again = self.events("merged", str(task))
        self.assertIn("already recorded", self.one(again, "merged")["detail"])
        running = self.running_task()
        out = self.run_cmd("merged", str(running))
        self.assertEqual(out.returncode, 2)
        self.assertIn("is not a closed task", out.stderr)

    def test_53_cleanup_keeps_uncommitted_work(self):
        task = self.closed_task()
        wt = self.worktree("task-1-1")
        with open(os.path.join(wt, "wip.txt"), "w") as fh:
            fh.write("x\n")
        self.agents(self.finished("task-1-1"))
        events = self.events("merged", str(task))
        self.assertIn("uncommitted changes", self.one(events, "kept")["detail"])
        self.assertEqual(self.calls("rm"), [])
        self.assertTrue(os.path.isfile(os.path.join(wt, "wip.txt")))

    def test_53_discard_unpushed_only_for_commits_in_head(self):
        task = self.closed_task()
        head = self.git("rev-parse", "HEAD")
        self.agents(self.finished("task-1-1"))
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-task-1-1": {"exit": 1, "stderr": f"unpushed commits; pass --discard-unpushed {head[:12]}@wt-1"}}, fh)
        events = self.events("merged", str(task))
        self.assertIn("discarded", self.one(events, "removed")["detail"])
        self.assertEqual(self.calls("rm")[-1], ["rm", "sess-task-1-1", "--discard-unpushed", f"{head[:12]}@wt-1"])
        self.assertTrue(all("--force-remove-worktree" not in c for c in self.calls()))

    def test_53_unmerged_commit_is_never_discarded(self):
        task = self.closed_task()
        wt = self.worktree("task-1-1")
        side = self.wt_commit(wt)
        self.agents(self.finished("task-1-1"))
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-task-1-1": {"exit": 1, "stderr": f"unpushed commits; pass --discard-unpushed {side}@wt-1"}}, fh)
        events = self.events("merged", str(task))
        self.assertIn(f"commit {side} is not in HEAD", self.one(events, "kept")["detail"])
        self.assertEqual(len(self.calls("rm")), 1)
        self.assertTrue(os.path.isdir(wt))

    def test_53_untracked_files_are_listed_never_deleted(self):
        task = self.closed_task()
        wt = self.worktree("task-1-1")
        self.agents(self.finished("task-1-1"))
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-task-1-1": {"exit": 1, "stderr": "worktree has untracked files"}}, fh)
        events = self.events("merged", str(task))
        self.assertIn("untracked files", self.one(events, "kept")["detail"])
        self.assertTrue(os.path.isdir(wt))
        self.assertTrue(all("--force-remove-worktree" not in c for c in self.calls()))

    def test_53_other_failure_and_directory_without_a_session(self):
        task = self.closed_task()
        self.worktree("task-1-1")
        self.agents(self.finished("verify-1-1"))
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-verify-1-1": {"exit": 1, "stderr": "detached at an unmerged commit\nmore"}}, fh)
        events = self.events("merged", str(task))
        kept = self.named(events, "kept")
        details = sorted(e["detail"] for e in kept)
        self.assertEqual(details, ["task-1-1: no session; remove it by hand if you want",
                                   "verify-1-1: claude rm said: detached at an unmerged commit"])

    def test_53_abandoned_task_is_never_cleaned_up(self):
        task = self.closed_task(merged=True)
        self.tg("edit", str(task), "--meta", "abandoned=died")
        self.agents(self.finished("task-1-1"))
        self.events("merged", str(task))
        self.assertEqual(self.calls("rm"), [])

    # --- stop and abandon

    def test_54_stop_files_a_stopped_row_and_touches_no_git_state(self):
        task = self.running_task()
        wt = self.worktree("task-1-1")
        with open(os.path.join(wt, "wip.txt"), "w") as fh:
            fh.write("half\n")
        head = self.git("rev-parse", "HEAD", cwd=wt)
        self.agents(self.row("task-1-1"))
        events = self.events("stop", str(task))
        self.assertIn("run.py record commits its WIP", self.one(events, "stopped")["detail"])
        self.assertIn(["stop", "sess-task-1-1"], self.calls("stop"))
        row = self.results(task)[0]
        self.assertEqual((row["status"], row["author"], row["attempt"]), ("STOPPED", "manager", 1))
        for line in ("Session: sess-task-1-1", f"Worktree: {wt}", "Branch: worktree-task-1-1", "Files: ?? wip.txt"):
            self.assertIn(line, row["body"])
        self.assertNotIn("Head:", row["body"])
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), head)
        self.assertTrue(os.path.isfile(os.path.join(wt, "wip.txt")))
        self.agents()
        out = self.run_cmd("stop", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("has no live session", out.stderr)

    def test_55_abandon(self):
        task = self.running_task(attempt=3)
        self.worktree("task-1-3")
        self.agents(self.row("task-1-3"), self.finished("task-1-1"))
        events = self.events("abandon", str(task), "died")
        self.assertEqual(self.meta(task)["abandoned"], "died")
        self.assertIn(["stop", "sess-task-1-3"], self.calls("stop"))
        detail = self.one(events, "abandoned")["detail"]
        self.assertIn("worktrees kept: task-1-1, task-1-3", detail)
        filed = [r for r in self.results(task) if r["status"] == "ABANDONED"]
        self.assertEqual(len(filed), 1)
        self.assertIn("Session: sess-task-1-3", filed[0]["body"])
        self.assertIn("Worktree:", filed[0]["body"])
        out = self.run_cmd("abandon", str(task), "gave-up")
        self.assertEqual(out.returncode, 2)
        idle = self.add_task()
        self.assertEqual(self.run_cmd("abandon", str(idle), "died").returncode, 2)

    # --- review fixes

    def test_57_close_survives_a_failing_stop_and_can_be_resumed(self):
        task = self.running_task()
        self.pass_report(task)
        self.agents(self.row("task-1-1"))
        self.orders("MERGE: verified branches into main\n")
        with open(os.path.join(self.root, "dirty.txt"), "w") as fh:
            fh.write("x\n")
        env = dict(self.env, FAKE_CLAUDE_STOP_FAIL="1")
        events = self.events("close", str(task), "--verdict", "test-verified", env=env)
        self.assertIn("still live; claude stop said: boom", self.one(events, "kept")["detail"])
        self.assertEqual(self.status_of(task), "done")
        self.assertIn("main checkout is not clean", self.one(events, "ready-to-merge")["detail"])
        self.assertEqual([r for r in self.results(task) if r["status"] == "STOPPED"], [])
        os.remove(os.path.join(self.root, "dirty.txt"))
        again = self.events("close", str(task))
        self.assertEqual(self.one(again, "resumed")["task"], task)
        self.assertEqual(self.one(again, "merged")["task"], task)
        self.assertEqual(self.merges(), "Merge worktree-task-1-1 (task #1)")
        self.assertEqual(self.meta(task)["merged_by"], "manager")
        self.assertIn(["stop", "sess-task-1-1"], self.calls("stop"))
        self.assertEqual(self.run_cmd("close", str(task)).returncode, 2)

    def test_57_resumed_close_refuses_a_changed_branch(self):
        task = self.running_task()
        wt, _ = self.pass_report(task)
        self.ok("close", str(task), "--verdict", "test-verified")
        self.wt_commit(wt, "later.txt")
        out = self.run_cmd("close", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("the output changed after the verdict", out.stderr)

    def test_58_a_done_decisions_notes_reach_the_next_brief(self):
        task = self.running_task()
        self.add_result(task, "BLOCKED", "Task: 1\nStatus: BLOCKED\nIssues: which API?\n")
        gate = self.tg("add", "Which API?", "--type", "decision", "--meta", "decider=operator",
                       "--notes", "Options: REST or RPC.", "--blocks", str(task))["id"]
        self.tg("edit", str(gate), "--notes", "Options: REST or RPC. Answer: use the REST API.")
        self.tg("done", str(gate))
        arrived = self.one(self.events("record"), "arrived")
        self.assertEqual(arrived["next"], f"decision #{gate} answered; run.py launch {task}")
        context = self.section(self.brief(task), "CONTEXT")
        self.assertIn(f"### Decision #{gate}: Which API? (done)", context)
        self.assertIn("Answer: use the REST API.", context)
        self.assertNotIn("No report on file.", context)

    def test_59_launch_repairs_an_open_task_with_a_live_session(self):
        task = self.add_task()
        self.agents(self.row("task-1-1", name="task-1-1-smoke"))
        events = self.events("launch", str(task))
        repaired = self.one(events, "repaired")
        self.assertEqual((repaired["task"], repaired["attempt"], repaired["session"]), (1, 1, "sess-task-1-1"))
        self.assertEqual(self.calls("--bg"), [])
        self.assertEqual(self.status_of(task), "in_progress")
        meta = self.meta(task)
        self.assertEqual((meta["attempt"], meta["session"]), (1, "task-1-1-smoke"))
        self.assertIn("started_at", meta)
        again = self.run_cmd("launch", str(task))
        self.assertEqual(again.returncode, 2)
        self.assertIn("has a live session", again.stderr)

    def test_60_cleanup_skips_a_session_that_is_still_running(self):
        task = self.closed_task(merged=True)
        self.agents(self.row("verify-1-1"), self.finished("task-1-1"))
        events = self.events("merged", str(task))
        self.assertIn("still running", self.one(events, "kept")["detail"])
        self.assertEqual(self.calls("rm"), [["rm", "sess-task-1-1"]])

    def test_61_checksum_close_cleans_up_at_once(self):
        task = self.running_task()
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\nHead: abc123  out.txt\n")
        self.agents(self.finished("task-1-1"))
        events = self.events("close", str(task), "--verdict", "artifact-verified")
        self.assertEqual(self.one(events, "removed")["session"], "sess-task-1-1")

    def test_62_repeating_a_close_files_one_manager_verdict(self):
        task = self.running_task()
        self.pass_report(task)
        for _ in range(2):
            self.ok("close", str(task), "--verdict", "check-only", "--ran", "lint")
        filed = [r for r in self.results(task) if r["kind"] == "verify"]
        self.assertEqual(len(filed), 1)
        self.ok("close", str(task), "--verdict", "test-verified", "--ran", "pytest")
        self.assertEqual(len([r for r in self.results(task) if r["kind"] == "verify"]), 2)

    def test_63_dry_run_json_and_a_live_verifier_blocks_launch(self):
        task = self.add_task()
        out = self.run_cmd("launch", str(task), "--dry-run", pre=["--json"])
        self.assertEqual(out.returncode, 0, out.stderr)
        events = json.loads(out.stdout)
        self.assertEqual([e["event"] for e in events], ["dry-run"])
        self.assertIn("## GOAL", events[0]["detail"])
        self.assertIn("--worktree task-1-1", out.stderr)
        self.assertEqual(self.calls("--bg"), [])
        self.agents(self.row("verify-1-1"))
        blocked = self.run_cmd("launch", str(task))
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("has a live session sess-verify-1-1", blocked.stderr)

    # --- status

    def status_sections(self, *args):
        out = self.ok("status", *args)
        sections = {}
        for block in re.split(r"(?m)^## ", out.stdout)[1:]:
            sections[re.sub(r" \(\d+\)$", "", block.splitlines()[0])] = block
        return sections

    def test_56_earlier_died_result_with_live_attempt_is_in_flight(self):
        task = self.running_task(attempt=2, session="task-1-2", model="sonnet", started_at='"2026-10-26 09:00 UTC"')
        self.add_result(task, "DIED", "no session", attempt=1, by="manager")
        sections = self.status_sections()
        self.assertEqual(sections["In flight"].splitlines()[0], "In flight (1)")
        self.assertIn("#1", sections["In flight"])
        self.assertIn("DIED", sections["In flight"])
        self.assertIn("2026-10-26 09:00 UTC", sections["In flight"])
        self.assertIn("None.", sections["Failed or abandoned"])
        self.assertIn("None.", sections["Waiting for verification or triage"])

    def test_56_abandoned_marker_lists_task_as_abandoned(self):
        task = self.running_task(attempt=3, abandoned="died")
        self.add_result(task, "DIED", "no session", attempt=3, by="manager")
        sections = self.status_sections()
        self.assertIn("#1", sections["Failed or abandoned"])
        self.assertIn("died", sections["Failed or abandoned"])
        self.assertIn("None.", sections["In flight"])

    def test_56_result_for_current_attempt_is_waiting(self):
        task = self.running_task(session="task-1-1")
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nCheckpoint: {CHECKPOINT}\n")
        sections = self.status_sections()
        waiting = sections["Waiting for verification or triage"]
        for word in ("#1", "PASS", CHECKPOINT):
            self.assertIn(word, waiting)
        self.assertIn("None.", sections["In flight"])

    def test_56_verdict_without_close_is_listed_apart(self):
        task = self.running_task(verdict="verify-blocked")
        self.add_result(task, "PASS", "Task: 1\n")
        sections = self.status_sections()
        self.assertIn("None.", sections["Waiting for verification or triage"])
        self.assertIn("None.", sections["In flight"])
        self.assertEqual(sections["Verdict recorded, not closed"].splitlines()[0], "Verdict recorded, not closed (1)")
        self.assertIn("verify-blocked", sections["Verdict recorded, not closed"])

    def test_56_done_task_without_merge_is_listed_until_merged_at(self):
        unmerged = self.add_task("Sweep", attempt=1, verdict_ref=SHA_A, verdict="test-verified")
        merged = self.add_task("Build", attempt=1, verdict_ref=SHA_A, verdict="test-verified",
                               merged_at='"2026-10-26 10:00 UTC"', merged_by="operator")
        outside = self.add_task("Notes", attempt=1, verdict_ref='"abc123  out.txt"', verdict="artifact-verified")
        for task in (unmerged, merged, outside):
            self.tg("done", str(task))
        section = self.status_sections("--since", "2099-01-01")["Done, branch not merged"]
        self.assertEqual(section.splitlines()[0], "Done, branch not merged (1)")
        self.assertIn(f"#{unmerged} ", section)
        self.assertNotIn(f"#{merged} ", section)
        self.assertNotIn(f"#{outside} ", section)

    def test_56_in_flight_shows_latest_result_and_old_checkpoint(self):
        self.running_task(attempt=2)
        self.add_result(1, "ISSUES", f"Checkpoint: {CHECKPOINT}\n", attempt=1)
        in_flight = self.status_sections()["In flight"]
        self.assertIn("ISSUES", in_flight)
        self.assertIn(CHECKPOINT, in_flight)

    def test_56_stopped_task_is_in_flight(self):
        task = self.running_task()
        self.add_result(task, "STOPPED", "Session: s\nFiles: None\n", by="manager")
        sections = self.status_sections()
        self.assertIn("STOPPED", sections["In flight"])
        self.assertIn("None.", sections["Waiting for verification or triage"])

    def test_56_decisions_ready_done_columns_and_mark(self):
        done = self.add_task("Shipped", attempt=1, tokens='"11/3"', verdict="test-verified",
                             started_at='"2026-10-26 08:00 UTC"')
        self.add_result(done, "PASS", "Task: 1\nStatus: PASS\n")
        self.add_result(done, "PASS", "Verdict: test-verified\n", kind="verify", by="verify-1-1")
        self.tg("done", str(done))
        free = self.add_task("Free work")
        held = self.add_task("Held work")
        self.tg("add", "Pick a name", "--type", "decision", "--meta", "decider=operator", "--due", "2026-11-01",
                "--blocks", str(held))
        self.tg("add", "Open question", "--type", "decision", "--meta", "decider=operator")
        sections = self.status_sections("--mark")
        row = next(line for line in sections["Done since last report"].splitlines() if "Shipped" in line)
        for word in ("11 / 3", "test-verified", "verify-1-1", "2026-10-26 08:00 UTC"):
            self.assertIn(word, row)
        header = sections["Done since last report"].splitlines()[2]
        self.assertIn("Verified by", header)
        self.assertIn("Started", header)
        self.assertNotIn("Ended", header)
        decisions = sections["Open decisions"]
        self.assertEqual(decisions.splitlines()[0], "Open decisions (2)")
        self.assertIn("Pick a name", decisions)
        self.assertIn("2026-11-01", decisions)
        self.assertIn(f"#{held}", decisions)
        ready = sections["Ready"]
        self.assertEqual(ready.splitlines()[0], "Ready (1)")
        self.assertNotIn("Pick a name", ready)
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".agentic-team", "last-report")))
        self.assertNotIn("Open gates", self.ok("status").stdout)

    def test_56_json_report(self):
        self.running_task(session="task-1-1")
        out = self.ok("status", pre=["--json"])
        data = json.loads(out.stdout)
        self.assertEqual(data["project"], "demo")
        self.assertEqual(len(data["in_flight"]), 1)
        self.assertEqual(data["in_flight"][0]["Task"], "#1")

    def test_56_empty_project(self):
        out = self.run_cmd("status")
        self.assertEqual(out.returncode, 2)
        self.assertIn("has no tasks", out.stderr)


if __name__ == "__main__":
    unittest.main()
