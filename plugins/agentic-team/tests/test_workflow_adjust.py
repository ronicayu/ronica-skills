"""Tests for the changes of a workflow instance in flight (W4): `run.py stage <instance> escalate|downgrade|replace|cancel|expand`,
the `design:` triggers of `record`, and the approval that `recheck` creates for a stage that a rule raised from `auto`.
Run: "$PY" plugins/agentic-team/tests/run_parallel.py (all tests, in parallel)

Each test builds a temporary git repository and a temporary Taskgraph database, and runs run.py and the real tg.py against
them. A fake `claude` lists the sessions of $FAKE_AGENTS and logs the ids it is told to stop. Nothing here starts a Claude
session or reaches the network.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
RUN = os.path.join(PLUGIN, "scripts", "run.py")
TG = os.path.join(os.path.dirname(PLUGIN), "taskgraph", "skills", "taskgraph", "scripts", "tg.py")
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))

import run as runner  # noqa: E402

SHA = "a" * 40
NOTES = "Why: users need it.\n- [ ] first behaviour\n- [ ] second behaviour"
FAKE_CLAUDE = """#!/bin/sh
if [ "$1" = agents ]; then cat "$FAKE_AGENTS" 2>/dev/null || echo '[]'; exit 0; fi
if [ "$1" = stop ]; then echo "$2" >> "$FAKE_STOPS"; exit 0; fi
echo '[]'
"""
PARALLEL = """\
    ---
    name: par
    description: Two design stages side by side, then the spec.
    stages:
      - {id: prd}
      - {id: ux}
      - {id: spec, after: [prd, ux]}
    ---
    ## When to use
    Always.
    """


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.realpath(tmp.name)
        self.root, self.home, self.bin = (os.path.join(self.dir, n) for n in ("repo", "home", "bin"))
        for path in (self.root, self.home, self.bin):
            os.makedirs(path)
        for args in (["init", "-q", "-b", "main"], ["config", "user.name", "t"], ["config", "user.email", "t@example.com"],
                     ["commit", "-q", "--allow-empty", "-m", "base", "--no-gpg-sign"]):
            subprocess.run(["git", "-C", self.root, *args], check=True, capture_output=True)
        with open(os.path.join(self.bin, "claude"), "w") as fh:
            fh.write(FAKE_CLAUDE)
        os.chmod(os.path.join(self.bin, "claude"), 0o755)
        self.agents_file, self.stops_file = os.path.join(self.dir, "agents.json"), os.path.join(self.dir, "stops")
        self.config("")
        self.env = {**os.environ, "HOME": self.home, "TASKGRAPH_DB": os.path.join(self.dir, "tasks.db"),
                    "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""), "CLAUDE_CONFIG_DIR": os.path.join(self.home, "claude"),
                    "FAKE_AGENTS": self.agents_file, "FAKE_STOPS": self.stops_file}
        self.env.pop("TASKGRAPH_TG", None)

    def config(self, extra, policy=""):
        with open(os.path.join(self.root, ".agentic-team.toml"), "w") as fh:
            fh.write('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n'
                     f"[workflow_policy]\nenabled = true\n{policy}" + textwrap.dedent(extra))

    def project_workflow(self, name, text):
        folder = os.path.join(self.root, ".claude", "agentic-team", "workflows")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{name}.md"), "w") as fh:
            fh.write(textwrap.dedent(text))

    def run_cmd(self, *args, pre=()):
        return subprocess.run([sys.executable, RUN, "--root", self.root, "--tg", TG, *pre, *args], capture_output=True, text=True,
                              cwd=self.dir, env=self.env)

    def events(self, *args):
        out = self.run_cmd(*args, pre=["--json"])
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return json.loads(out.stdout)

    def refused(self, *args):
        out = self.run_cmd(*args)
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        return out.stderr

    def tg(self, *args, stdin=None):
        out = subprocess.run([sys.executable, TG, "--project", "demo", "--json", *args], capture_output=True, text=True, env=self.env,
                             input=stdin)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def node(self, tid):
        return self.tg("show", str(tid))

    def meta(self, tid):
        return self.node(tid)["meta"]

    def deps(self, tid):
        return sorted(d["id"] if isinstance(d, dict) else d for d in self.node(tid)["depends_on"])

    def add(self, workflow, title="Add export", *flags, scope="src/export/", extra_meta=()):
        events = self.events("add", title, "--workflow", workflow, "--notes", NOTES, "--meta", f"scope={scope}", "verify=make test",
                             *extra_meta, "--independent", "alone", *flags)
        return next(e["task"] for e in events if e["event"] == "workflow-added")

    def record(self, inst):
        return self.meta(inst)["workflow_record"]

    def stages(self, inst):
        return {e["id"]: e["task"] for e in self.record(inst)["stages"]}

    def approval(self, inst, stage):
        return next(e["approval_id"] for e in self.record(inst)["stages"] if e["id"] == stage)

    def merge(self, tid):
        self.tg("edit", str(tid), "--meta", "attempt=1", f"verdict_ref={SHA}", "verdict=test-verified", "sessions=[]")
        self.tg("done", str(tid))
        self.events("merged", str(tid), "--by", "operator")

    def approve(self, inst, stage):
        self.events("stage", str(inst), "approve", stage, "--by", "operator")

    def result(self, tid, status, body, kind="task", by="worker", attempt=1):
        self.tg("result", "add", str(tid), "--kind", kind, "--attempt", str(attempt), "--by", by, "--status", status, "--body-file", "-", stdin=body)

    def worktree(self, tid, dirty=False):
        path = os.path.join(self.root, ".claude", "worktrees", f"task-{tid}")
        subprocess.run(["git", "-C", self.root, "worktree", "add", "-q", "-b", f"worktree-task-{tid}", path], check=True, capture_output=True)
        if dirty:
            with open(os.path.join(path, "wip.txt"), "w") as fh:
                fh.write("unfinished\n")
        return path

    def start(self, tid, phase="reported", attempt=1, sessions=(), body="Status: PASS\nSummary: done\n", worktree=True, dirty=False, report=True):
        """A stage task in flight: started, its worker's report filed, and a git worktree on its branch."""
        path = self.worktree(tid, dirty) if worktree else None
        self.tg("edit", str(tid), "--meta", f"attempt={attempt}", f"phase={phase}", "sessions=" + json.dumps(list(sessions)))
        self.tg("start", str(tid))
        if report:
            self.result(tid, body.split("\n", 1)[0].partition(": ")[2], body, attempt=attempt)
        return path

    def agents(self, *rows):
        with open(self.agents_file, "w") as fh:
            json.dump(list(rows), fh)

    def worker_row(self, tid, status="idle", sid="sess-w", state="working"):
        path = os.path.join(self.root, ".claude", "worktrees", f"task-{tid}")
        return {"id": sid, "name": f"task-{tid}-1", "cwd": path, "status": status, "state": state, "pid": 4242}

    def worker_entry(self, tid, sid="sess-w"):
        return {"id": sid, "kind": "task", "attempt": 1, "name": f"task-{tid}-1", "worktree": f"task-{tid}"}

    def stopped(self):
        try:
            with open(self.stops_file) as fh:
                return fh.read().split()
        except OSError:
            return []

    def rows(self, tid):
        return self.tg("result", "ls", str(tid))


class EscalateTest(Base):
    def test_a_spec_goes_before_impl_with_its_approval_and_the_record(self):
        inst = self.add("fix")
        stages = self.stages(inst)
        self.assertNotIn("spec", stages)
        events = self.events("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "the data model is missing")
        line = next(e for e in events if e["event"] == "escalated")
        new = self.stages(inst)["spec"]
        self.assertIn(f"stage spec (#{new}) goes before impl", line["detail"])
        self.assertEqual(line["next"], f"run.py launch {new}")
        task = self.node(new)
        self.assertEqual((task["parent"], task["meta"]["stage"], task["meta"]["stage_origin"], task["meta"]["role"]), (inst, "spec", "escalate", "architect"))
        decision = self.node(self.approval(inst, "spec"))
        self.assertEqual((decision["meta"]["approval_level"], decision["meta"]["approval_state"]), ("manager", "pending"))
        self.assertEqual(self.deps(stages["impl"]), sorted([new, decision["id"]]))
        record = self.record(inst)
        self.assertEqual([e["id"] for e in record["stages"]], ["spec", "impl", "test"])
        self.assertEqual(next(e for e in record["stages"] if e["id"] == "impl")["after"], ["spec"])
        self.assertEqual([(a["kind"], a["type"], a["stage"], a["before"], a["why"]) for a in record["adjustments"]],
                         [("escalate", "spec", "spec", "impl", "the data model is missing")])
        self.assertIn("waits for", self.refused("launch", str(stages["impl"])))

    def test_the_new_stage_depends_on_the_upstream_of_the_target_and_every_part_waits_for_it(self):
        inst = self.add("feature")
        stages = self.stages(inst)
        for part, files in (("api", "src/export/api.py"), ("ui", "src/export/ui.py")):
            self.events("stage", str(inst), "split", "impl", "--part", part, "--meta", f"scope={files}")
        parts = [t["id"] for t in self.tg("ls", "--parent", str(inst)) if (t.get("meta") or {}).get("stage") == "impl"]
        self.assertEqual(len(parts), 2)
        self.events("stage", str(inst), "escalate", "ux", "--before", "impl", "--why", "the flow is undecided")
        new = self.stages(inst)["ux"]
        approval = self.approval(inst, "ux")
        upstream = sorted(set(self.deps(parts[0])) - {new, approval})
        self.assertEqual(upstream, sorted([stages["spec"], self.approval(inst, "spec")]))
        self.assertEqual(self.deps(new), upstream)  # the upstream of the target
        for part in parts:
            self.assertTrue({new, approval} <= set(self.deps(part)), part)

    def test_the_bound_counts_escalations_and_downgrades(self):
        self.config("", policy="max_adjustments = 1\n")
        inst = self.add("feature", "Add export", "--with", "ux")
        self.events("stage", str(inst), "escalate", "prd", "--before", "impl", "--why", "the outcome is unclear")
        err = self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "again")
        self.assertIn("used its 1 adjustment", err)
        self.assertIn("never asks the owner", err)
        err = self.refused("stage", str(inst), "downgrade", "ux", "--why", "not needed")
        self.assertIn("used its 1 adjustment", err)

    def test_the_default_bound_is_two(self):
        inst = self.add("fix")
        self.events("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "one")
        self.events("stage", str(inst), "escalate", "ux", "--before", "impl", "--why", "two")
        self.assertIn("used its 2 adjustments", self.refused("stage", str(inst), "escalate", "prd", "--before", "impl", "--why", "three"))

    def test_a_stage_type_is_escalated_once_per_instance(self):
        inst = self.add("fix")
        self.events("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "one")
        self.assertIn("escalated a spec stage already", self.refused("stage", str(inst), "escalate", "spec", "--before", "test", "--why", "two"))

    def test_escalate_needs_before_why_a_stage_and_a_type_of_the_library(self):
        inst = self.add("fix")
        self.assertIn("needs --before", self.refused("stage", str(inst), "escalate", "spec", "--why", "x"))
        self.assertIn("needs --why", self.refused("stage", str(inst), "escalate", "spec", "--before", "impl"))
        self.assertIn("has no stage nope", self.refused("stage", str(inst), "escalate", "spec", "--before", "nope", "--why", "x"))
        self.assertIn("no stage type 'bogus'", self.refused("stage", str(inst), "escalate", "bogus", "--before", "impl", "--why", "x"))
        self.assertIn("needs a stage type", self.refused("stage", str(inst), "escalate"))
        self.assertIn("no stage task of", self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x", "--from-row", "99999"))
        self.assertIn("--from-row takes", self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x", "--from-row", "abc"))
        self.assertEqual(self.record(inst)["adjustments"], [])

    def test_a_busy_session_refuses_and_changes_nothing(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        self.start(impl, phase="running", report=False, sessions=[self.worker_entry(impl)])
        self.agents(self.worker_row(impl, status="busy"))
        err = self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x")
        self.assertIn("busy session", err)
        self.assertEqual(set(self.stages(inst)), {"impl", "test"})
        self.assertEqual(self.stopped(), [])

    def test_a_part_that_is_merged_or_abandoned_refuses(self):
        inst = self.add("feature")
        self.events("stage", str(inst), "split", "impl", "--part", "api", "--meta", "scope=src/export/api.py")
        self.events("stage", str(inst), "split", "impl", "--part", "ui", "--meta", "scope=src/export/ui.py")
        parts = sorted(t["id"] for t in self.tg("ls", "--parent", str(inst)) if (t.get("meta") or {}).get("stage") == "impl")
        self.merge(parts[0])
        err = self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x")
        self.assertIn(f"stage impl (#{parts[0]}) is merged or waits for its merge", err)
        self.assertIn("ran without the new stage", err)
        inst2 = self.add("fix", "Other")
        impl2 = self.stages(inst2)["impl"]
        self.tg("edit", str(impl2), "--meta", "attempt=1", "sessions=[]")
        self.tg("start", str(impl2))
        self.events("abandon", str(impl2), "superseded", "--why", "dropped")
        err = self.refused("stage", str(inst2), "escalate", "spec", "--before", "impl", "--why", "x")
        self.assertIn("was abandoned", err)
        self.assertIn("replace impl", err)

    def test_a_task_that_waits_for_its_merge_refuses(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        self.start(impl, phase="awaiting_merge")
        self.tg("edit", str(impl), "--meta", f"verdict_ref={SHA}", "verdict=test-verified")
        self.assertIn("is merged or waits for its merge", self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x"))

    def test_a_verifier_that_filed_no_row_refuses(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        verifier = {"id": "sess-v", "kind": "verify", "attempt": 1, "name": f"verify-{impl}-1", "worktree": f"verify-{impl}-1"}
        self.start(impl, phase="verifying", sessions=[self.worker_entry(impl), verifier])
        err = self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x")
        self.assertIn("has filed no row yet", err)
        self.assertEqual(self.rows(impl)[-1]["status"], "PASS")
        self.assertEqual(set(self.stages(inst)), {"impl", "test"})

    def test_a_reported_attempt_is_stopped_with_the_wip_committed_and_a_stopped_row_that_says_escalated(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        wt = self.start(impl, phase="reported", sessions=[self.worker_entry(impl)], dirty=True)
        self.agents(self.worker_row(impl))
        events = self.events("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "the data model is missing")
        self.assertIn("sess-w", self.stopped())
        stop = next(e for e in events if e["event"] == "stopped")
        self.assertIn("WIP committed", stop["detail"])
        head = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(subprocess.run(["git", "-C", wt, "status", "--porcelain"], capture_output=True, text=True).stdout, "")
        self.assertIn("stopped by escalation", subprocess.run(["git", "-C", wt, "log", "-1", "--format=%s"], capture_output=True, text=True).stdout)
        row = self.rows(impl)[-1]
        self.assertEqual(row["status"], "STOPPED")
        self.assertIn(f"Head: {head}", row["body"])
        self.assertIn("Reason: escalated", row["body"])
        self.assertIn("wip.txt", row["body"])
        self.assertEqual(self.meta(impl)["phase"], "stopped")
        self.assertIn("once the stage that the escalation added is merged and approved", stop["next"])
        self.assertIn("attempt", next(e for e in events if e["event"] == "escalated")["detail"])
        seen = [e for e in self.events("record") if e["task"] == impl and e["event"] in ("stopped", "arrived", "verified", "unclosed")]
        self.assertEqual([e["event"] for e in seen], ["stopped"])
        self.assertIn("escalated; head", seen[0]["detail"])

    def test_a_verifying_attempt_with_a_passing_verdict_filed_is_refused_and_left_as_it_was(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        verifier = {"id": "sess-v", "kind": "verify", "attempt": 1, "name": f"verify-{impl}-1", "worktree": f"verify-{impl}-1"}
        self.start(impl, phase="verifying", sessions=[self.worker_entry(impl), verifier])
        self.result(impl, "PASS", "Status: PASS\nVerdict: test-verified\nSummary: fine\n", kind="verify", by=f"verify-{impl}-1")
        self.assertIn("passing verdict", self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x"))
        self.assertEqual(self.meta(impl)["phase"], "verifying")
        self.assertEqual((self.rows(impl)[-1]["kind"], self.rows(impl)[-1]["status"]), ("verify", "PASS"))

    def test_a_failed_verdict_keeps_its_phase_and_record_still_reads_the_escalated_row_first(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        self.start(impl, phase="verdict_failed", sessions=[self.worker_entry(impl)])
        self.result(impl, "ISSUES", "Status: ISSUES\nVerdict: verify-failed\nIssues:\n- blocking: no design\nSummary: no\n", kind="verify", by="verify-1-1")
        self.tg("edit", str(impl), "--meta", "verdict=verify-failed")
        self.events("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x")
        self.assertEqual(self.meta(impl)["phase"], "verdict_failed")
        self.assertIn("Reason: escalated", self.rows(impl)[-1]["body"])
        seen = [e["event"] for e in self.events("record") if e["task"] == impl and e["event"] in ("stopped", "verified", "unclosed")]
        self.assertEqual(seen, ["stopped"])

    def test_a_missing_worktree_refuses_before_any_change(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        self.start(impl, phase="reported", worktree=False)
        err = self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x")
        self.assertIn("is gone, so its WIP cannot be committed", err)
        self.assertEqual(set(self.stages(inst)), {"impl", "test"})
        self.assertEqual(self.rows(impl)[-1]["status"], "PASS")

    def test_the_launch_after_an_escalation_is_exempt_from_the_cap_by_the_row_not_by_the_flag(self):
        stopped = lambda reason: [{"kind": "task", "attempt": 3, "status": "STOPPED", "body": f"Head: {SHA}\n{reason}Files: None"}]
        runner.refuse_past_cap(5, 4, stopped("Reason: escalated\n"), None)  # no Refused
        runner.refuse_past_cap(5, 4, stopped("Reason: pause\n"), None)
        with self.assertRaises(runner.Refused):
            runner.refuse_past_cap(5, 4, stopped("Reason: recover\n"), None)
        with self.assertRaises(runner.Refused):
            runner.refuse_past_cap(5, 4, stopped(""), None)
        with self.assertRaises(runner.Refused):
            runner.refuse_past_cap(5, 4, [{"kind": "task", "attempt": 3, "status": "ISSUES", "body": "Status: ISSUES"}], None)
        self.assertEqual(runner.launch_cause({}, stopped("Reason: escalated\n"), 3), "escalated")
        self.assertEqual(runner.launch_cause({}, stopped("Reason: recover\n"), 3), "retry-stopped")

    def test_launch_at_the_cap_passes_after_an_escalation_and_is_refused_after_an_ordinary_stop(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        self.start(impl, phase="reported", attempt=3, sessions=[self.worker_entry(impl)])
        self.events("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x")
        spec = self.stages(inst)["spec"]
        self.merge(spec)
        self.approve(inst, "spec")
        out = self.run_cmd("launch", str(impl), "--dry-run")
        self.assertNotIn("has failed", out.stderr)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        other = self.add("fix", "Other")
        impl2 = self.stages(other)["impl"]
        self.start(impl2, phase="stopped", attempt=3, report=False)
        self.result(impl2, "STOPPED", "Session: s\nReason: recover\nHead: " + SHA + "\nFiles: None", attempt=3)
        self.assertIn("attempt 3 has failed", self.refused("launch", str(impl2), "--dry-run"))


class DowngradeTest(Base):
    def test_a_skipped_stage_hands_its_upstream_to_its_dependents_and_closes_its_approval(self):
        inst = self.add("feature", "Add export", "--with", "ux")
        stages = self.stages(inst)
        ux_approval = self.approval(inst, "ux")
        self.assertIn(stages["ux"], self.deps(stages["spec"]))
        events = self.events("stage", str(inst), "downgrade", "ux", "--why", "the flow follows the existing design")
        self.assertIn("downgraded", [e["event"] for e in events])
        want = sorted([stages["prd"], self.approval(inst, "prd")])
        self.assertEqual(self.deps(stages["spec"]), want)
        self.assertNotIn(ux_approval, self.deps(stages["spec"]))
        ux = self.node(stages["ux"])
        self.assertEqual((ux["status"], ux["meta"]["stage_state"], self.deps(stages["ux"])), ("done", "skipped", []))
        decision = self.node(ux_approval)
        self.assertEqual((decision["status"], decision["meta"]["approval_state"]), ("done", "skipped"))
        record = self.record(inst)
        spec = next(e for e in record["stages"] if e["id"] == "spec")
        self.assertEqual(spec["after"], ["prd"])
        self.assertTrue(next(e for e in record["stages"] if e["id"] == "ux")["skipped"])
        self.assertEqual([(a["kind"], a["stage"]) for a in record["adjustments"]], [("downgrade", "ux")])
        self.assertEqual(record["optional"]["ux"], "downgraded")

    def test_a_dependent_cannot_start_before_the_upstream_approval_of_the_skipped_stage(self):
        inst = self.add("feature", "Add export", "--with", "ux")
        stages = self.stages(inst)
        self.events("stage", str(inst), "downgrade", "ux", "--why", "not needed")
        self.assertIn(f"#{stages['prd']}", self.refused("launch", str(stages["spec"]), "--dry-run"))
        self.merge(stages["prd"])
        err = self.refused("launch", str(stages["spec"]), "--dry-run")
        self.assertIn(f"#{self.approval(inst, 'prd')} (decision)", err)  # the approval of prd is still open
        self.approve(inst, "prd")
        out = self.run_cmd("launch", str(stages["spec"]), "--dry-run")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_record_leaves_a_skipped_stage_alone_and_the_instance_still_ends(self):
        inst = self.add("feature", "Add export", "--with", "ux")
        self.events("stage", str(inst), "downgrade", "ux", "--why", "not needed")
        seen = [e for e in self.events("record") if e["event"] in ("warn", "unmanaged", "stage-orphaned", "phase-mismatch")]
        self.assertEqual(seen, [])

    def test_only_an_optional_stage_with_no_attempt_that_no_rule_requires_and_no_escalation_added(self):
        inst = self.add("feature", "Add export", "--with", "ux")
        stages = self.stages(inst)
        self.assertIn("is required by workflow feature", self.refused("stage", str(inst), "downgrade", "prd", "--why", "x"))
        self.assertIn("needs --why", self.refused("stage", str(inst), "downgrade", "ux"))
        self.assertIn("has no stage nope", self.refused("stage", str(inst), "downgrade", "nope", "--why", "x"))
        self.tg("edit", str(stages["ux"]), "--meta", "attempt=1", "sessions=[]")
        self.tg("start", str(stages["ux"]))
        self.assertIn("has started", self.refused("stage", str(inst), "downgrade", "ux", "--why", "x"))
        other = self.add("fix", "Other")
        self.events("stage", str(other), "escalate", "spec", "--before", "impl", "--why", "x")
        self.assertIn("added by an escalation", self.refused("stage", str(other), "downgrade", "spec", "--why", "x"))
        self.assertEqual(self.record(other)["adjustments"][-1]["kind"], "escalate")

    def test_a_stage_that_a_rule_requires_is_not_downgraded(self):
        self.config("""
            [[workflow_rule]]
            name = "ux-rule"
            match_paths = ["src/export/**"]
            require_stage = "ux"
            """)
        inst = self.add("feature")
        self.assertIn("ux", self.stages(inst))
        err = self.refused("stage", str(inst), "downgrade", "ux", "--why", "x")
        self.assertIn("rule ux-rule requires stage ux", err)
        self.assertIn("ux", self.stages(inst))


class OrphanTest(Base):
    def abandon(self, tid):
        self.tg("edit", str(tid), "--meta", "attempt=1", "sessions=[]")
        self.tg("start", str(tid))
        return self.events("abandon", str(tid), "superseded", "--why", "dropped")

    def test_the_orphan_hint_names_replace_and_cancel_as_commands(self):
        inst = self.add("change")
        stages = self.stages(inst)
        line = next(e for e in self.abandon(stages["prd"]) if e["event"] == "stage-orphaned")
        self.assertIn(f"run.py stage {inst} replace prd", line["next"])
        self.assertIn(f"run.py stage {inst} cancel --why", line["next"])

    def test_replace_and_cancel_are_refused_without_an_abandoned_stage(self):
        inst = self.add("change")
        self.assertIn("has no abandoned task", self.refused("stage", str(inst), "replace", "prd"))
        self.assertIn("no stage of", self.refused("stage", str(inst), "cancel", "--why", "x"))
        self.assertIn("needs a stage id", self.refused("stage", str(inst), "replace"))
        self.assertIn("has no stage nope", self.refused("stage", str(inst), "replace", "nope"))

    def test_replace_makes_a_new_task_with_the_same_place_approval_and_dependents(self):
        inst = self.add("change")
        stages = self.stages(inst)
        approval = self.approval(inst, "prd")
        old = self.node(stages["prd"])
        self.abandon(stages["prd"])
        events = self.events("stage", str(inst), "replace", "prd")
        new = self.stages(inst)["prd"]
        self.assertNotEqual(new, stages["prd"])
        self.assertIn(f"#{new} replaces the abandoned #{stages['prd']}", next(e for e in events if e["event"] == "stage-replaced")["detail"])
        task = self.node(new)
        self.assertEqual((task["parent"], task["title"], task["meta"]["stage"], task["meta"]["scope"], task["meta"]["replaced_from"]),
                         (inst, old["title"], "prd", old["meta"]["scope"], stages["prd"]))
        self.assertEqual(self.deps(new), [])
        decision = self.node(approval)
        self.assertEqual((decision["depends_on"][0]["id"] if isinstance(decision["depends_on"][0], dict) else decision["depends_on"][0],
                          decision["meta"]["approval_for"]), (new, new))
        self.assertEqual(self.meta(new)["approval_id"], approval)
        self.assertTrue({new, approval} <= set(self.deps(stages["impl"])))
        self.assertNotIn(stages["prd"], self.deps(stages["impl"]))
        self.assertIsNone(self.node(stages["prd"])["parent"])
        self.assertEqual(self.meta(stages["prd"])["replaced_by"], new)
        entry = next(e for e in self.record(inst)["stages"] if e["id"] == "prd")
        self.assertEqual((entry["task"], entry["replaced"], entry["replaced_tasks"]), (new, 1, [stages["prd"]]))
        self.assertEqual([e for e in self.events("record") if e["event"] == "stage-orphaned"], [])

    def test_a_replacement_is_limited_per_stage(self):
        inst = self.add("change")
        first = self.stages(inst)["prd"]
        self.abandon(first)
        self.events("stage", str(inst), "replace", "prd")
        second = self.stages(inst)["prd"]
        self.abandon(second)
        err = self.refused("stage", str(inst), "replace", "prd")
        self.assertIn("replaced 1 time already (max_replacements = 1)", err)
        self.assertIn("cancel", err)

    def test_replace_keeps_the_dependencies_of_a_stage_after_the_first(self):
        inst = self.add("change")
        stages = self.stages(inst)
        self.merge(stages["prd"])
        self.approve(inst, "prd")
        self.abandon(stages["impl"])
        self.events("stage", str(inst), "replace", "impl")
        new = self.stages(inst)["impl"]
        self.assertEqual(self.deps(new), sorted([stages["prd"], self.approval(inst, "prd")]))
        self.assertIn(new, self.deps(stages["test"]))
        self.assertNotIn(stages["impl"], self.deps(stages["test"]))

    def test_cancel_abandons_the_stages_that_still_run_in_other_branches_and_ends_the_instance(self):
        self.project_workflow("par", PARALLEL)
        inst = self.add("par")
        stages = self.stages(inst)
        self.abandon(stages["prd"])
        self.start(stages["ux"], phase="running", report=False, sessions=[self.worker_entry(stages["ux"])])
        self.agents(self.worker_row(stages["ux"], status="busy"))
        events = self.events("stage", str(inst), "cancel", "--why", "the scope changed")
        self.assertIn("sess-w", self.stopped())
        self.assertEqual(self.meta(stages["ux"])["abandoned"], "cancelled")
        self.assertEqual(self.node(stages["spec"])["meta"]["stage_state"], "skipped")
        self.assertEqual(self.node(stages["spec"])["status"], "done")
        for stage in ("prd", "ux", "spec"):
            self.assertEqual(self.node(self.approval(inst, stage))["status"], "done", stage)
            self.assertEqual(self.node(self.approval(inst, stage))["meta"]["approval_state"], "cancelled")
        record = self.record(inst)
        self.assertEqual(record["ended"]["kind"], "cancelled")
        self.assertEqual((record["ended"]["abandoned"], record["ended"]["skipped"]), ([stages["ux"]], [stages["spec"]]))
        self.assertEqual(self.meta(inst)["abandoned"], "cancelled")
        detail = next(e for e in events if e["event"] == "workflow-cancelled")["detail"]
        self.assertIn(f"abandoned #{stages['ux']}", detail)
        self.assertIn(f"skipped #{stages['spec']}", detail)
        self.assertEqual([e for e in events if e["event"] == "stage-orphaned"], [])
        self.assertEqual([e for e in self.events("record") if e["event"] == "stage-orphaned"], [])
        self.assertIn("ended (cancelled", self.refused("stage", str(inst), "cancel", "--why", "again"))
        self.assertIn("ended (cancelled", self.refused("stage", str(inst), "replace", "prd"))

    def test_cancel_names_the_tasks_that_wait_for_the_instance(self):
        inst = self.add("change")
        waiting = self.tg("add", "Later", "--meta", 'independent="x"')["id"]
        self.tg("dep", "add", str(waiting), str(inst))
        self.abandon(self.stages(inst)["prd"])
        detail = next(e for e in self.events("stage", str(inst), "cancel", "--why", "dropped") if e["event"] == "workflow-cancelled")["detail"]
        self.assertIn(f"#{waiting} wait for the instance and never start", detail)
        self.assertNotEqual(self.node(inst)["derived_status"], "done")

    def test_cancel_leaves_a_merged_stage_as_it_is(self):
        self.project_workflow("par", PARALLEL)
        inst = self.add("par")
        stages = self.stages(inst)
        self.merge(stages["prd"])
        self.abandon(stages["ux"])
        self.events("stage", str(inst), "cancel", "--why", "dropped")
        self.assertEqual(self.node(stages["prd"])["status"], "done")
        self.assertNotIn("stage_state", self.meta(stages["prd"]))
        self.assertEqual(self.record(inst)["stages"][0]["task"], stages["prd"])


class RecheckApprovalTest(Base):
    RULE = """
        [[workflow_rule]]
        name = "money"
        match_paths = ["apps/api/billing/**"]
        approval = { impl = "human" }
        """

    def widen(self, inst, stage):
        self.tg("edit", str(self.stages(inst)[stage]), "--meta", 'scope="apps/api/billing/x.py"')

    def test_recheck_creates_the_approval_of_an_auto_stage_that_a_rule_raised(self):
        inst = self.add("feature", scope="lib/")
        stages = self.stages(inst)
        self.assertIsNone(self.approval(inst, "impl"))
        self.config(self.RULE)
        self.widen(inst, "test")
        events = self.events("stage", str(inst), "recheck")
        approval = self.approval(inst, "impl")
        self.assertIsNotNone(approval)
        decision = self.node(approval)
        self.assertEqual((decision["type"], decision["parent"], decision["meta"]["approval_level"], decision["meta"]["approval_state"],
                          decision["meta"]["approval_for"]), ("decision", inst, "human", "pending", stages["impl"]))
        self.assertEqual(self.meta(stages["impl"])["approval_id"], approval)
        self.assertEqual([d["id"] if isinstance(d, dict) else d for d in decision["depends_on"]], [stages["impl"]])
        self.assertIn(approval, self.deps(stages["test"]))
        row = next(r for r in self.record(inst)["rules"] if r["rule"] == "money")
        self.assertEqual([(r["stage"], r["from"], r["to"], r["state"]) for r in row["raised"]], [("impl", "auto", "human", "created-pending")])
        self.assertEqual(next(e for e in self.record(inst)["stages"] if e["id"] == "impl")["approval"], "human")
        self.assertIn("raised impl auto -> human", next(e for e in events if e["event"] == "workflow-rule" and "newly matches" in e["detail"])["detail"])
        self.assertIn(f"#{approval}", self.refused("launch", str(stages["test"]), "--dry-run"))

    def test_the_created_approval_opens_when_the_stage_has_merged_and_notifies_the_owner(self):
        inst = self.add("feature", scope="lib/")
        stages = self.stages(inst)
        self.config(self.RULE)
        for stage in ("prd", "spec", "impl"):
            self.merge(stages[stage])
            if stage != "impl":
                self.approve(inst, stage)
        self.widen(inst, "test")
        self.events("stage", str(inst), "recheck")
        decision = self.node(self.approval(inst, "impl"))
        self.assertEqual((decision["meta"]["approval_state"], decision["meta"]["decider"]), ("open", "operator"))
        self.assertIn("due_at", decision["meta"])
        self.assertIn(decision["id"], self.deps(stages["test"]))
        queue = json.loads(self.run_cmd("--json", "notify-queue").stdout)
        self.assertTrue(any("needs you" in str(item) for item in queue), queue)


class TriggerTest(Base):
    def impl_with(self, follow, status="ISSUES"):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        self.start(impl, phase="running", report=False, sessions=[], worktree=False)
        body = f"Status: {status}\nAsked: none: x\nSummary: s\nFollow-ups:\n{follow}\nCheckpoint: c\n"
        self.result(impl, status, body)
        return inst, impl

    def hint(self, impl):
        return [e for e in self.events("record") if e["event"] == "escalation-hint" and e["task"] == impl]

    def test_check_report_accepts_the_design_label(self):
        path = os.path.join(self.dir, "report.md")
        with open(path, "w") as fh:
            fh.write("Status: ISSUES\nAsked: none: x\nSummary: needs a design\nFollow-ups:\n- design: auth model: the token owner is undefined\nCheckpoint: c\n")
        out = self.run_cmd("check-report", path)
        self.assertNotIn("no label", out.stderr)

    def test_a_design_follow_up_gives_the_manager_the_escalate_command(self):
        inst, impl = self.impl_with("- design: who owns the token?: the code cannot decide it")
        rows = self.rows(impl)
        found = self.hint(impl)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["next"], f'run.py stage {inst} escalate spec --before impl --from-row {rows[-1]["id"]}#1 --why "<one line>" (the Manager runs it)')
        self.assertIn("design: who owns the token?", found[0]["detail"])

    def test_a_follow_up_with_another_label_gives_no_hint_and_neither_does_a_task_outside_an_instance(self):
        inst, impl = self.impl_with("- other: a file: x")
        self.assertEqual(self.hint(impl), [])
        loose = self.tg("add", "Loose", "--meta", 'independent="x"')["id"]
        self.tg("edit", str(loose), "--meta", "attempt=1", "sessions=[]", "phase=running")
        self.tg("start", str(loose))
        self.result(loose, "ISSUES", "Status: ISSUES\nAsked: none: x\nSummary: s\nFollow-ups:\n- design: q: why\nCheckpoint: c\n")
        self.assertEqual(self.hint(loose), [])

    def test_a_blocking_design_finding_of_a_verifier_gives_the_same_hint(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        self.start(impl, phase="verifying", report=True, worktree=False)
        self.result(impl, "ISSUES", "Status: ISSUES\nVerdict: verify-failed\nIssues:\n- blocking[design]: the retry contract is undefined\nSummary: no\n",
                    kind="verify", by="verify-1-1")
        found = self.hint(impl)
        self.assertEqual(len(found), 1)
        self.assertIn(f"run.py stage {inst} escalate spec --before impl --from-row", found[0]["next"])
        self.assertIn("verifier row", found[0]["detail"])

    def test_past_the_limit_or_after_a_spec_escalation_the_hint_says_to_report_it_and_asks_nobody(self):
        self.config("", policy="max_adjustments = 0\n")
        inst, impl = self.impl_with("- design: q: why")
        found = self.hint(impl)
        self.assertIn("used its 0 adjustments", found[0]["detail"])
        self.assertEqual(found[0]["next"], "put the design question in the report; the owner is not asked")
        self.config("")
        other, impl2 = self.impl_with("- design: q: why")
        self.events("stage", str(other), "escalate", "spec", "--before", "test", "--why", "x")
        found = self.hint(impl2)
        self.assertIn("escalated a spec stage already", found[0]["detail"])
        self.assertNotIn("run.py stage", found[0]["next"])


class ExpandTest(Base):
    def investigated(self, plan, scope="src/export/", extra=""):
        inst = self.add("figure-it-out", scope=scope)
        inv = self.stages(inst)["investigate"]
        self.merge(inv)
        body = f"Status: PASS\nSummary: sized\n\n```workflow-plan\n{plan}\n```\n"
        self.result(inv, "PASS", body)
        return inst, inv, self.rows(inv)[-1]["id"]

    def test_a_named_plan_creates_the_stages_behind_the_investigation_and_its_approval(self):
        inst, inv, row = self.investigated("workflow: fix   # the fix workflow\nwhy: one function is wrong")
        before = self.stages(inst)
        events = self.events("stage", str(inst), "expand", "--from-row", str(row))
        stages = self.stages(inst)
        self.assertEqual(list(stages), ["investigate", "impl", "test"])
        gate = sorted([inv, self.approval(inst, "investigate")])
        self.assertEqual(self.deps(stages["impl"]), gate)
        self.assertEqual(self.deps(stages["test"]), sorted([stages["impl"]]))
        self.assertEqual(before, {"investigate": inv})
        record = self.record(inst)
        self.assertEqual((record["workflow"], self.meta(inst)["workflow"]), ("fix", "fix"))
        self.assertEqual((record["expanded"]["workflow"], record["expanded"]["row"], record["expanded"]["from"]), ("fix", str(row), "figure-it-out"))
        line = next(e for e in events if e["event"] == "workflow-expanded")
        self.assertIn("one function is wrong", line["detail"])
        self.assertEqual(line["next"], f"run.py stage {inst} approve investigate")
        self.assertIn("waits for", self.refused("launch", str(stages["impl"])))

    def test_an_ad_hoc_plan_names_its_own_stages(self):
        inst, inv, row = self.investigated("stages: [{id: spec}, {id: impl, after: [spec], split: true}, {id: test, after: [impl]}]")
        self.events("stage", str(inst), "expand", "--from-row", str(row))
        stages = self.stages(inst)
        self.assertEqual(list(stages), ["investigate", "spec", "impl", "test"])
        record = self.record(inst)
        self.assertEqual((record["workflow"], self.meta(inst)["workflow"]), ("adhoc", "adhoc"))
        self.assertEqual(self.deps(stages["spec"]), sorted([inv, self.approval(inst, "investigate")]))
        self.assertTrue({stages["spec"], self.approval(inst, "spec")} <= set(self.deps(stages["impl"])))
        self.assertTrue(next(e for e in record["stages"] if e["id"] == "impl")["split"])

    def test_expand_applies_the_rules_that_were_deferred_to_it(self):
        self.config("""
            [[workflow_rule]]
            name = "billing"
            match_paths = ["apps/api/billing/**"]
            require_stage = "spec"
            approval = { spec = "human" }
            risk = "high"
            """)
        inst, inv, row = self.investigated("workflow: fix", scope="apps/api/billing/")
        self.assertEqual([(r["rule"], r["action"]) for r in self.record(inst)["rules"]], [("billing", "deferred-to-expand")])
        self.events("stage", str(inst), "expand", "--from-row", str(row))
        stages = self.stages(inst)
        self.assertEqual(list(stages), ["investigate", "spec", "impl", "test"])
        self.assertEqual(self.node(self.approval(inst, "spec"))["meta"]["approval_level"], "human")
        self.assertEqual(self.meta(stages["impl"]).get("risk"), "high")
        self.assertEqual([(r["rule"], r["action"]) for r in self.record(inst)["rules"]],
                         [("billing", "deferred-to-expand"), ("billing", "forced-with")])

    def test_an_ad_hoc_plan_without_the_stage_a_rule_requires_is_refused_and_a_named_workflow_may_replace_it(self):
        self.config("""
            [[workflow_rule]]
            name = "billing"
            match_paths = ["apps/api/billing/**"]
            require_stage = "spec"
            """)
        inst, inv, row = self.investigated("stages: [{id: impl}, {id: test, after: [impl]}]", scope="apps/api/billing/")
        err = self.refused("stage", str(inst), "expand", "--from-row", str(row))
        self.assertIn("rule billing requires a spec stage", err)
        self.assertEqual(list(self.stages(inst)), ["investigate"])
        self.events("stage", str(inst), "expand", "--workflow", "fix")
        self.assertEqual(list(self.stages(inst)), ["investigate", "spec", "impl", "test"])

    def test_a_deferred_rule_applies_whatever_scope_expand_names(self):
        self.config("""
            [[workflow_rule]]
            name = "billing"
            match_paths = ["apps/api/billing/**"]
            require_stage = "spec"
            """)
        inst, inv, row = self.investigated("stages: [{id: impl}, {id: test, after: [impl]}]", scope="apps/api/billing/")
        err = self.refused("stage", str(inst), "expand", "--from-row", str(row), "--meta", "scope=src/other/")
        self.assertIn("rule billing requires a spec stage", err)
        self.assertEqual(list(self.stages(inst)), ["investigate"])
        self.events("stage", str(inst), "expand", "--workflow", "fix", "--meta", "scope=src/other/")
        self.assertEqual(list(self.stages(inst)), ["investigate", "spec", "impl", "test"])
        rows = self.record(inst)["rules"]
        self.assertEqual((rows[0]["action"], rows[0]["resolved"]["action"], rows[0]["resolved"]["stage"]), ("deferred-to-expand", "forced-with", "spec"))
        self.assertEqual((rows[1]["rule"], rows[1]["via"]), ("billing", "expand"))

    def test_expand_refusals(self):
        inst = self.add("figure-it-out")
        inv = self.stages(inst)["investigate"]
        self.assertIn("is not merged yet", self.refused("stage", str(inst), "expand", "--workflow", "fix"))
        self.merge(inv)
        self.assertIn("needs one of --from-row", self.refused("stage", str(inst), "expand"))
        self.assertIn("one of --from-row", self.refused("stage", str(inst), "expand", "--workflow", "fix", "--from-row", "1"))
        self.assertIn("no workflow named 'nope'", self.refused("stage", str(inst), "expand", "--workflow", "nope"))
        self.assertIn("decides its own stages", self.refused("stage", str(inst), "expand", "--workflow", "figure-it-out"))
        self.result(inv, "PASS", "Status: PASS\nSummary: x\n")
        self.assertIn("has no ```workflow-plan block", self.refused("stage", str(inst), "expand", "--from-row", str(self.rows(inv)[-1]["id"])))
        self.result(inv, "PASS", "Status: PASS\nSummary: x\n```workflow-plan\nstages: [{id: nope}]\n```\n")
        self.assertIn("not a workflow", self.refused("stage", str(inst), "expand", "--from-row", str(self.rows(inv)[-1]["id"])))
        self.assertEqual(list(self.stages(inst)), ["investigate"])
        plain = self.add("fix", "Other")
        self.assertIn("is not an instance of a workflow that decides", self.refused("stage", str(plain), "expand", "--workflow", "fix"))

    def test_a_second_expand_is_refused(self):
        inst, inv, row = self.investigated("workflow: fix")
        self.events("stage", str(inst), "expand", "--from-row", str(row))
        self.assertIn("was expanded already", self.refused("stage", str(inst), "expand", "--workflow", "fix"))


class ReviewFixTest(Base):
    """The W4 review fixes: the passing verdict and the cap guard of escalate, started dependents of a late approval, the task locks
    of downgrade and recheck, the notices of cancel, the target of a recheck hint and the check of --rule."""

    def test_an_attempt_with_a_passing_verdict_is_not_escalated(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        self.start(impl, phase="verifying", report=True)
        self.result(impl, "PASS", "Status: PASS\nVerdict: test-verified\nSummary: ok\n", kind="verify", by="verify-1-1")
        err = self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x")
        self.assertIn("passing verdict (test-verified)", err)
        self.assertIn(f"run.py close {impl}", err)
        self.assertEqual(self.record(inst)["adjustments"], [])

    def test_an_attempt_at_the_cap_that_died_is_refused_and_one_below_it_is_not(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        self.start(impl, phase="died", attempt=3, report=False, sessions=[], worktree=False)
        self.result(impl, "DIED", "Session: s\nReason: died\n", by="manager", attempt=3)
        err = self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "x")
        self.assertIn("attempt 3 has already failed", err)
        self.assertIn("abandon", err)
        self.assertIn("stage <instance> replace impl", err)
        self.assertNotIn("ask the owner", err)
        self.assertEqual(list(self.stages(inst)), ["impl", "test"])
        other = self.add("fix", "Other")
        impl2 = self.stages(other)["impl"]
        self.start(impl2, phase="died", attempt=2, report=False, sessions=[], worktree=False)
        self.result(impl2, "DIED", "Session: s\nReason: died\n", by="manager", attempt=2)
        self.events("stage", str(other), "escalate", "spec", "--before", "impl", "--why", "x")
        self.assertIn("spec", self.stages(other))

    def test_a_rule_that_is_not_configured_is_refused(self):
        inst = self.add("fix")
        self.assertIn("no [[workflow_rule]] of that name", self.refused("stage", str(inst), "escalate", "spec", "--before", "impl", "--rule", "nope", "--why", "x"))

    def test_recheck_names_the_started_stage_that_runs_without_the_new_approval(self):
        inst = self.add("feature", scope="lib/")
        stages = self.stages(inst)
        self.start(stages["test"], phase="running", report=False, sessions=[], worktree=False)
        self.config(RecheckApprovalTest.RULE)
        self.tg("edit", str(stages["test"]), "--meta", 'scope="apps/api/billing/x.py"')
        events = self.events("stage", str(inst), "recheck")
        line = next(e for e in events if e["event"] == "workflow-rule" and "newly matches" in e["detail"])["detail"]
        self.assertIn(f"#{stages['test']} already started and run without the new approval of impl", line)
        row = next(r for r in self.record(inst)["rules"] if r["rule"] == "money")
        self.assertEqual(row["started_without"], {"impl": [stages["test"]]})
        self.assertNotIn(self.approval(inst, "impl"), self.deps(stages["test"]))

    def test_the_recheck_hint_skips_a_stage_that_waits_for_its_merge(self):
        self.config('[[workflow_rule]]\nname = "billing"\nmatch_paths = ["apps/api/billing/**"]\nrequire_stage = "spec"\n')
        inst = self.add("hotfix", scope="lib/")
        stages = self.stages(inst)
        self.start(stages["impl"], phase="awaiting_merge", report=True)
        self.tg("edit", str(stages["test"]), "--meta", 'scope="apps/api/billing/x.py"')
        events = self.events("stage", str(inst), "recheck")
        line = next(e for e in events if e["event"] == "workflow-rule" and "newly matches" in e["detail"])
        self.assertIn("--before test", line["next"])

    def hold(self, tid):
        import fcntl
        path = os.path.join(self.root, ".agentic-team", "locks", f"task-{tid}.lock")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = open(path, "a+")
        self.addCleanup(fh.close)
        fcntl.flock(fh, fcntl.LOCK_EX)

    def test_downgrade_and_recheck_wait_for_the_task_locks(self):
        inst = self.add("feature", "Add export", "--with", "ux")
        stages = self.stages(inst)
        self.hold(stages["impl"])
        env = dict(self.env, AGENTIC_TEAM_LOCK_SECONDS="1")
        for args in (("downgrade", "ux", "--why", "x"), ("recheck",)):
            out = subprocess.run([sys.executable, RUN, "--root", self.root, "--tg", TG, "stage", str(inst), *args], capture_output=True, text=True,
                                 cwd=self.dir, env=env)
            self.assertNotEqual(out.returncode, 0, args)
            self.assertIn("holds", out.stderr + out.stdout)
        self.assertNotIn("adjustments", {k for k, v in self.record(inst).items() if v})

    def test_cancel_drops_the_decision_notices_it_closes_and_queues_one_notice_for_the_instance(self):
        self.config('[notifications]\nevents = ["decision", "workflow-cancelled"]\n[[workflow_rule]]\nname = "money"\nmatch_paths = ["src/export/**"]\napproval = { prd = "human" }\n')
        inst = self.add("change")
        stages = self.stages(inst)
        waiting = self.tg("add", "Later", "--meta", 'independent="x"')["id"]
        self.tg("dep", "add", str(waiting), str(inst))
        self.merge(stages["prd"])
        before = json.loads(self.run_cmd("--json", "notify-queue").stdout)
        self.assertTrue(any(i["event"] == "notify" and "[decision]" in i["detail"] for i in before), before)
        self.tg("edit", str(stages["impl"]), "--meta", "attempt=1", "sessions=[]")
        self.tg("start", str(stages["impl"]))
        self.events("abandon", str(stages["impl"]), "superseded", "--why", "dropped")
        self.events("stage", str(inst), "cancel", "--why", "dropped")
        after = [i["detail"] for i in json.loads(self.run_cmd("--json", "notify-queue").stdout) if i["event"] == "notify"]
        self.assertFalse([d for d in after if "[decision]" in d], after)
        found = [d for d in after if "[workflow-cancelled]" in d]
        self.assertEqual(len(found), 1, after)
        self.assertIn(f"#{waiting}", found[0])

    def test_the_escalation_hint_stops_after_the_escalation(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]
        self.start(impl, phase="running", report=False, sessions=[])
        self.result(impl, "ISSUES", "Status: ISSUES\nAsked: none: x\nSummary: s\nFollow-ups:\n- design: q: why\nCheckpoint: c\n")
        first = [e for e in self.events("record") if e["event"] == "escalation-hint" and e["task"] == impl]
        self.assertIn("escalate spec", first[0]["next"])
        self.events("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "q")
        later = [e for e in self.events("record") if e["event"] == "escalation-hint" and e["task"] == impl]
        self.assertTrue(all("escalate spec" not in (e["next"] or "") for e in later), later)


if __name__ == "__main__":
    unittest.main()
