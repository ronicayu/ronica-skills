"""Tests for the workflow retro (W6): the fields that the record and the approval decisions hold after each action, the statistics of
`run.py workflows --stats`, and the proposals that follow from them.
Run: "$PY" plugins/agentic-team/tests/run_parallel.py (all tests, in parallel)

The statistics and the proposals are pure functions, tested on plain data. The record tests build a temporary git repository and a
temporary Taskgraph database, and run run.py and the real tg.py against them. Nothing here starts a Claude session or reaches
the network.
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

import workflow_stats as wst  # noqa: E402

NOTES = "Why: users need it.\n- [ ] first behaviour\n- [ ] second behaviour"
FAKE_CLAUDE = "#!/bin/sh\nif [ \"$1\" = agents ]; then echo '[]'; exit 0; fi\necho '[]'\n"


def stage(sid, status="done", hours=2.0, verdicts=(), failed=(), approval=None, state=None, attempts=1, revisions=0, origin=None, started=None):
    start = "2026-11-01T00:00:00Z"
    end = f"2026-11-01T{int(hours):02d}:{int((hours % 1) * 60):02d}:00Z"
    return {"id": sid, "task": 0, "state": state, "origin": origin, "status": status, "created_at": start, "done_at": end if status == "done" else None,
            "started_at": started, "attempts": attempts, "revisions": revisions, "verdicts": list(verdicts), "failed": list(failed), "approval": approval}


def approval(outcome, level="manager", by="manager", hours=1.0):
    return {"level": level, "outcome": outcome, "by": by, "state": "done" if outcome else "open", "on_timeout": "approve",
            "opened_at": "2026-11-01T00:00:00Z", "answered_at": f"2026-11-01T{int(hours):02d}:00:00Z" if outcome else None}


def instance(iid, workflow, stages, pick=None, adjustments=(), overrides=(), optional=None, ended=None, rules=()):
    record = {"workflow": workflow, "pick": pick or {"answers": None, "resolved": workflow, "rule": "named", "unsure": False},
              "adjustments": list(adjustments), "overrides": list(overrides), "optional": optional or {}, "ended": ended, "rules": list(rules)}
    return {"id": iid, "title": f"t{iid}", "created_at": "2026-11-01T00:00:00Z", "record": record, "stages": stages}


def answers(a, b, unsure=False):
    return {"answers": [a, b], "seeds": [1, 2], "resolved": a if a == b else b, "rule": "same" if a == b else "lighter", "unsure": unsure,
            "when_unsure": "lighter"}


def escalation(trigger="verifier", kind="escalate", type_="spec"):
    return {"kind": kind, "type": type_, "stage": "spec", "before": "impl", "row": 5, "trigger": trigger, "at": "2026-11-01T01:00:00Z"}


class StatsTest(unittest.TestCase):
    def fixture(self):
        return [
            # fix: 1 merged by pick agreement; 2 escalated (verifier) after an unsure pick; 3 cancelled; 4 escalated (worker), overridden;
            # 5 merged with a downgrade
            instance(1, "fix", [stage("impl", verdicts=["test-verified"], hours=4, approval=approval("approved")),
                                stage("test", verdicts=["test-verified"], hours=2)], pick=answers("fix", "fix")),
            instance(2, "fix", [stage("spec", origin="escalate", hours=1, approval=approval("defaulted", by="run.py")),
                                stage("impl", verdicts=["verify-failed", "test-verified"], failed=["test", "design"], hours=6, attempts=2, revisions=1),
                                stage("test", hours=2)],
                     pick=answers("fix", "unsure", unsure=True), adjustments=[escalation("verifier")]),
            instance(3, "fix", [stage("impl", status="in_progress"), stage("test", status="open")],
                     ended={"kind": "cancelled", "why": "x"}, adjustments=[{"kind": "cancel", "trigger": "orphan"}]),
            instance(4, "fix", [stage("spec", origin="escalate", approval=approval("held", level="human", by="operator", hours=5)),
                                stage("impl", verdicts=["verify-failed"], failed=["design"], status="in_progress")],
                     pick=answers("fix", "change"), adjustments=[escalation("worker")],
                     overrides=[{"from": "fix", "to": "fix", "by": "operator"}]),
            instance(5, "fix", [stage("impl", verdicts=["test-verified"], hours=8), stage("ux", state="skipped", status="done")],
                     adjustments=[{"kind": "downgrade", "stage": "ux", "trigger": "manager"}], optional={"ux": "downgraded"}),
            instance(6, "hotfix", [stage("impl", verdicts=["test-verified"], hours=1)], pick=answers("hotfix", "hotfix")),
        ]

    def test_per_workflow_counts_and_rates(self):
        w = wst.compute(self.fixture())["workflows"]["fix"]
        self.assertEqual((w["instances"], w["merged"], w["cancelled"], w["running"]), (5, 3, 1, 1))
        self.assertEqual((w["completion_rate"], w["cancel_rate"]), (0.6, 0.2))
        self.assertEqual((w["escalations"], w["downgrades"], w["replacements"]), (2, 1, 0))
        self.assertEqual(w["escalated_instances"], [2, 4])
        self.assertEqual(w["triggers"], {"escalate:verifier": 1, "escalate:worker": 1, "cancel:orphan": 1, "downgrade:manager": 1})
        self.assertEqual(w["escalated_to"], {"spec": 2})

    def test_pick_agreement_unsure_and_accuracy(self):
        p = wst.compute(self.fixture())["workflows"]["fix"]["pick"]
        self.assertEqual(p["picked"], 3)  # instances 3 and 5 were named, not picked
        self.assertAlmostEqual(p["agreement_rate"], 1 / 3, places=3)
        self.assertAlmostEqual(p["unsure_rate"], 1 / 3, places=3)
        self.assertEqual((p["overridden"], p["escalated_after_pick"]), (1, 2))
        self.assertEqual(p["accuracy"], 0.6)  # instances 2 and 4 were corrected

    def test_per_stage_attempts_first_pass_categories_time_and_approvals(self):
        s = wst.compute(self.fixture())["workflows"]["fix"]["stages"]
        impl = s["impl"]
        self.assertEqual((impl["tasks"], impl["merged"], impl["verified"], impl["first_pass"]), (5, 3, 4, 2))
        self.assertEqual(impl["first_pass_rate"], 0.5)
        self.assertEqual(impl["failed_categories"], {"design": 2, "test": 1})
        self.assertEqual((impl["attempts_mean"], impl["revisions_mean"]), (1.2, 0.2))
        self.assertEqual(impl["median_hours"], 6.0)  # merged: 4, 6, 8
        spec = s["spec"]
        self.assertEqual(spec["approvals"]["outcomes"], {"defaulted": 1, "held": 1})
        self.assertEqual((spec["approvals"]["default_rate"], spec["approvals"]["hold_rate"]), (0.5, 0.5))
        self.assertEqual(spec["approvals"]["median_wait_hours"], 3.0)
        self.assertEqual(s["ux"]["skipped"], 1)
        self.assertEqual(s["ux"]["tasks"], 0)

    def test_stage_time_runs_from_the_start_of_the_attempt_not_from_the_creation(self):
        data = [instance(1, "fix", [stage("impl", hours=10, started="2026-11-01T07:00:00Z")]),
                instance(2, "fix", [stage("impl", hours=6, started="2026-11-01T04:00:00Z")]),
                instance(3, "fix", [stage("impl", hours=4)])]  # no started_at: created_at is the fallback
        self.assertEqual(wst.compute(data)["workflows"]["fix"]["stages"]["impl"]["median_hours"], 3.0)  # 3, 2 and 4 hours

    def test_the_result_does_not_depend_on_the_order_of_the_instances(self):
        data = self.fixture()
        self.assertEqual(wst.compute(data), wst.compute(list(reversed(data))))

    def test_text_names_every_workflow_and_the_proposals(self):
        data = self.fixture()
        text = wst.render(wst.compute(data), wst.propose(data, wst.compute(data)), "2026-11-01")
        for needle in ("fix: 5 instances", "hotfix: 1 instances", "stage impl:", "Proposals (", "nothing is applied"):
            self.assertIn(needle, text)

    def test_no_instances_give_empty_stats(self):
        self.assertEqual(wst.compute([]), {"instances": 0, "workflows": {}})
        self.assertEqual(wst.propose([], wst.compute([])), [])


class ProposalTest(unittest.TestCase):
    def kinds(self, data, **limits):
        return [p["kind"] for p in wst.propose(data, wst.compute(data), limits or None)]

    def make(self, n, escalated=0, **kw):
        return [instance(i, "hotfix", [stage("impl", verdicts=["test-verified"], approval=approval("approved"))],
                         adjustments=[escalation()] if i <= escalated else [], **kw) for i in range(1, n + 1)]

    def test_escalation_fires_at_30_percent_and_names_the_instances(self):
        data = self.make(10, escalated=3)
        found = [p for p in wst.propose(data, wst.compute(data)) if p["kind"] == "escalation"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["evidence"], {"instances": [1, 2, 3], "count": 3, "of": 10})
        self.assertIn("hotfix escalated to spec in 3 of 10 instances (#1, #2, #3)", found[0]["text"])

    def test_escalation_does_not_fire_below_30_percent_or_with_too_few_instances(self):
        self.assertNotIn("escalation", self.kinds(self.make(10, escalated=2)))
        self.assertNotIn("escalation", self.kinds(self.make(2, escalated=2)))

    def test_drop_stage_fires_when_an_optional_stage_is_always_left_out(self):
        data = self.make(5, optional={"ux": "skipped"})
        found = [p for p in wst.propose(data, wst.compute(data)) if p["kind"] == "drop-stage"]
        self.assertEqual((found[0]["stage"], found[0]["evidence"]["count"], found[0]["evidence"]["of"]), ("ux", 5, 5))
        self.assertIn("skipped or downgraded in 5 of 5", found[0]["text"])

    def test_drop_stage_does_not_fire_when_the_stage_is_used(self):
        data = self.make(5, optional={"ux": "skipped"})
        data[0]["record"]["optional"]["ux"] = "with"
        self.assertNotIn("drop-stage", self.kinds(data))

    def test_drop_stage_ignores_a_stage_that_was_left_out_by_default(self):
        self.assertNotIn("drop-stage", self.kinds(self.make(50, optional={"spec": "default-skipped"})))

    def test_drop_stage_counts_ended_instances_that_did_not_escalate_to_the_stage(self):
        data = self.make(5, optional={"ux": "skipped"})
        data[0]["stages"][0]["status"] = "in_progress"  # running: not counted
        data[1]["record"]["adjustments"] = [escalation(type_="ux")]  # escalated to ux: not counted
        found = [p for p in wst.propose(data, wst.compute(data)) if p["kind"] == "drop-stage"]
        self.assertEqual((found[0]["evidence"]["instances"], found[0]["evidence"]["of"]), ([3, 4, 5], 3))

    def test_auto_approval_fires_for_a_manager_approval_that_always_passes_first(self):
        data = self.make(5)
        found = [p for p in wst.propose(data, wst.compute(data)) if p["kind"] == "auto-approval"]
        self.assertEqual(found[0]["evidence"]["count"], 5)
        self.assertIn('approval = "auto"', found[0]["text"])

    def test_auto_approval_does_not_fire_after_a_failure_or_for_a_human_approval(self):
        data = self.make(5)
        data[0]["stages"][0]["verdicts"] = ["verify-failed", "test-verified"]  # 4 of 5 = 80%
        self.assertNotIn("auto-approval", self.kinds(data))
        human = self.make(5)
        for i in human:
            i["stages"][0]["approval"]["level"] = "human"
        self.assertNotIn("auto-approval", self.kinds(human))

    def test_weak_stage_fires_with_the_top_category(self):
        data = self.make(6)
        for i in data[:4]:
            i["stages"][0]["verdicts"] = ["verify-failed", "test-verified"]
            i["stages"][0]["failed"] = ["claim"]
        found = [p for p in wst.propose(data, wst.compute(data)) if p["kind"] == "weak-stage"]
        self.assertIn("most often claim", found[0]["text"])
        self.assertEqual(found[0]["evidence"]["count"], 4)

    def test_weak_stage_needs_enough_verified_stages(self):
        data = self.make(3)
        for i in data:
            i["stages"][0]["verdicts"] = ["verify-failed"]
        self.assertNotIn("weak-stage", self.kinds(data))
        self.assertIn("weak-stage", self.kinds(data, min_stages=3))

    def test_approval_defaults_fires_when_nobody_answers(self):
        data = self.make(4)
        for i in data[:3]:
            i["stages"][0]["approval"] = approval("defaulted", level="human", by="run.py")
        self.assertIn("approval-defaults", self.kinds(data))
        self.assertNotIn("approval-defaults", self.kinds(self.make(4)))

    def test_pick_rules_fire_on_unsure_and_on_corrected_picks(self):
        data = self.make(5)
        for n, i in enumerate(data):
            i["record"]["pick"] = answers("hotfix", "unsure" if n < 2 else "hotfix", unsure=n < 2)
        self.assertIn("pick-unsure", self.kinds(data))
        self.assertNotIn("pick-unsure", self.kinds(self.make(5)))
        data[0]["record"]["overrides"] = [{"from": "hotfix", "to": "fix", "by": "operator"}]
        self.assertNotIn("pick-corrected", self.kinds(data))  # one instance is not enough
        data[1]["record"]["overrides"] = [{"from": "hotfix", "to": "fix", "by": "operator"}]
        self.assertIn("pick-corrected", self.kinds(data))
        self.assertNotIn("pick-corrected", self.kinds(self.make(5)))

    def test_cancels_fires_at_20_percent(self):
        data = self.make(5)
        data[0]["record"]["ended"] = {"kind": "cancelled", "why": "x"}
        self.assertNotIn("cancels", self.kinds(data))  # one instance is not enough
        data[1]["record"]["ended"] = {"kind": "cancelled", "why": "x"}
        self.assertIn("cancels", self.kinds(data))
        self.assertNotIn("cancels", self.kinds(self.make(5)))

    def test_one_escalation_and_one_cancel_in_three_instances_propose_nothing(self):
        data = self.make(3, escalated=1)
        data[1]["record"]["ended"] = {"kind": "cancelled", "why": "x"}
        self.assertEqual(self.kinds(data), [])

    def test_an_escalation_by_a_rule_is_not_the_picks_fault(self):
        data = self.make(5)
        for i in data[:3]:
            i["record"]["adjustments"] = [escalation(trigger="rule")]
        kinds = self.kinds(data)
        self.assertIn("escalation", kinds)
        self.assertNotIn("pick-corrected", kinds)
        self.assertEqual(wst.compute(data)["workflows"]["hotfix"]["pick"]["accuracy"], 1.0)

    def split(self, n):
        """n instances whose impl stage is split into two parts; only the first part holds the approval."""
        return [instance(i, "hotfix", [stage("impl", verdicts=["test-verified"], approval=approval("approved")),
                                       stage("impl", verdicts=["test-verified"])]) for i in range(1, n + 1)]

    def test_a_split_stage_counts_once_for_each_instance_and_still_proposes_auto_approval(self):
        data = self.split(4)
        impl = wst.compute(data)["workflows"]["hotfix"]["stages"]["impl"]
        self.assertEqual((impl["instances"], impl["tasks"], impl["verified"], impl["first_pass"]), (4, 8, 4, 4))
        found = [p for p in wst.propose(data, wst.compute(data)) if p["kind"] == "auto-approval"]
        self.assertEqual(found[0]["evidence"], {"instances": [1, 2, 3, 4], "count": 4, "of": 4})

    def test_a_split_stage_that_failed_in_two_parts_is_one_failure(self):
        data = self.split(4)
        for i in data[:3]:
            for part in i["stages"]:
                part["verdicts"] = ["verify-failed", "test-verified"]
        found = [p for p in wst.propose(data, wst.compute(data)) if p["kind"] == "weak-stage"]
        self.assertEqual(found[0]["evidence"], {"instances": [1, 2, 3], "count": 3, "of": 4})

    def test_every_proposal_names_instance_ids_and_counts(self):
        data = self.make(10, escalated=4, optional={"ux": "skipped"})
        for p in wst.propose(data, wst.compute(data)):
            self.assertTrue(p["evidence"]["instances"])
            self.assertEqual(p["evidence"]["count"], len(p["evidence"]["instances"]))


class CollectTest(unittest.TestCase):
    """collect_stats makes the same few tg calls for 2 stage tasks and for 60."""

    class Fake:
        def __init__(self, n):
            self.calls = []
            self.tasks = []
            for i in range(n):
                inst = 1 + i * 3
                self.tasks += [{"id": inst, "type": "task", "title": "t", "status": "open", "parent": None, "created_at": "2026-11-01T00:00:00Z",
                                "meta": {"workflow": "fix", "workflow_record": {"workflow": "fix"}}},
                               {"id": inst + 1, "type": "task", "title": "s", "status": "done", "parent": inst, "created_at": "2026-11-01T00:00:00Z",
                                "meta": {"stage": "impl"}},
                               {"id": inst + 2, "type": "task", "title": "s", "status": "open", "parent": inst, "created_at": "2026-11-01T00:00:00Z",
                                "meta": {"stage": "test"}}]
            self.rows = [{"id": t["id"], "task_id": t["id"], "kind": "task", "attempt": 1, "status": "PASS", "body": ""} for t in self.tasks if t["parent"]]

        def tg(self, *args):
            self.calls.append(args)
            return self.rows if args[0] == "result" else [] if "decision" in args else self.tasks

    def test_the_number_of_tg_calls_does_not_grow_with_the_tasks(self):
        import run as runner
        counts = []
        for n in (1, 30):
            fake = self.Fake(n)
            found = runner.collect_stats(fake, None)
            self.assertEqual((len(found), sum(len(i["stages"]) for i in found), found[0]["stages"][0]["attempts"]), (n, 2 * n, 1))
            counts.append(len(fake.calls))
        self.assertEqual(counts[0], counts[1])


class RecordTest(unittest.TestCase):
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
        self.config("")
        self.env = {**os.environ, "HOME": self.home, "TASKGRAPH_DB": os.path.join(self.dir, "tasks.db"),
                    "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""), "CLAUDE_CONFIG_DIR": os.path.join(self.home, "claude")}
        self.env.pop("TASKGRAPH_TG", None)

    def config(self, extra):
        with open(os.path.join(self.root, ".agentic-team.toml"), "w") as fh:
            fh.write('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n[workflow_policy]\nenabled = true\n' + textwrap.dedent(extra))

    def run_cmd(self, *args, pre=()):
        return subprocess.run([sys.executable, RUN, "--root", self.root, "--tg", TG, *pre, *args], capture_output=True, text=True,
                              cwd=self.dir, env=self.env)

    def events(self, *args):
        out = self.run_cmd(*args, pre=["--json"])
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return json.loads(out.stdout)

    def tg(self, *args):
        out = subprocess.run([sys.executable, TG, "--project", "demo", "--json", *args], capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def meta(self, tid):
        return self.tg("show", str(tid))["meta"]

    def add(self, workflow, *flags, title="Add export"):
        events = self.events("add", title, "--workflow", workflow, "--notes", NOTES, "--meta", "scope=src/export/", "verify=make test",
                             "--independent", "alone", *flags)
        return next(e["task"] for e in events if e["event"] == "workflow-added")

    def record(self, inst):
        return self.meta(inst)["workflow_record"]

    def stages(self, inst):
        return {e["id"]: e for e in self.record(inst)["stages"]}

    def merge(self, tid):
        self.tg("edit", str(tid), "--meta", "attempt=1", "verdict_ref=" + "a" * 40, "verdict=test-verified", "sessions=[]")
        self.tg("done", str(tid))
        self.events("merged", str(tid), "--by", "operator")

    def stats(self, *flags):
        out = self.run_cmd("workflows", "--stats", *flags)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out.stdout

    def test_a_pick_records_both_answers_the_seeds_the_rule_and_when_unsure(self):
        inst = self.picked("change,unsure")
        pick = self.record(inst)["pick"]
        self.assertEqual((pick["answers"], pick["seeds"], pick["resolved"], pick["unsure"], pick["when_unsure"]),
                         (["change", "unsure"], [7, 8], "change", True, "lighter"))
        self.assertTrue(pick["rule"])
        self.assertEqual(self.record(inst)["rules"], [])

    def picked(self, answers):
        events = self.events("add", "Add export", "--pick", answers, "--seed", "7", "--notes", NOTES, "--meta", "scope=src/export/",
                             "verify=make test", "--independent", "alone")
        return next(e["task"] for e in events if e["event"] == "workflow-added")

    def test_an_escalation_records_its_trigger_from_the_row_kind(self):
        inst = self.add("fix")
        impl = self.stages(inst)["impl"]["task"]
        self.tg("result", "add", str(impl), "--status", "ISSUES", "--kind", "verify", "--attempt", "1", "--by", "verifier",
                "--body", "Issues: blocking[design]: the model is missing")
        row = self.tg("result", "ls", str(impl))[0]["id"]
        self.events("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "the model is missing", "--from-row", str(row))
        adj = self.record(inst)["adjustments"]
        self.assertEqual([(a["kind"], a["type"], a["trigger"], a["row"]) for a in adj], [("escalate", "spec", "verifier", str(row))])

    def test_an_escalation_without_a_row_is_the_managers_and_a_rule_one_is_a_rule(self):
        inst = self.add("fix")
        self.events("stage", str(inst), "escalate", "spec", "--before", "impl", "--why", "unclear")
        self.assertEqual(self.record(inst)["adjustments"][0]["trigger"], "manager")
        other = self.add("fix", title="Other")
        self.config('[[workflow_rule]]\nname = "money"\nmatch_paths = ["apps/**"]\nrequire_stage = "spec"\n')
        self.events("stage", str(other), "escalate", "spec", "--before", "impl", "--rule", "money", "--why", "rule")
        self.assertEqual(self.record(other)["adjustments"][0]["trigger"], "rule")

    def test_a_downgrade_records_its_trigger(self):
        inst = self.add("fix", "--with", "spec")
        self.events("stage", str(inst), "downgrade", "spec", "--why", "not needed")
        adj = self.record(inst)["adjustments"]
        self.assertEqual((adj[0]["kind"], adj[0]["stage"], adj[0]["trigger"]), ("downgrade", "spec", "manager"))

    def abandoned(self, title):
        inst = self.add("change", title=title)
        prd = self.stages(inst)["prd"]["task"]
        self.tg("edit", str(prd), "--meta", "attempt=1", "sessions=[]")
        self.tg("start", str(prd))
        self.events("abandon", str(prd), "superseded", "--why", "dropped")
        return inst, prd

    def test_replace_and_cancel_are_recorded_as_adjustments_without_using_up_the_limit(self):
        inst, prd = self.abandoned("Replaced")
        self.events("stage", str(inst), "replace", "prd")
        adj = self.record(inst)["adjustments"]
        self.assertEqual([(a["kind"], a["trigger"], a["task"]) for a in adj], [("replace", "orphan", prd)])
        other, _ = self.abandoned("Cancelled")
        self.events("stage", str(other), "cancel", "--why", "stop")
        adj = self.record(other)["adjustments"]
        self.assertEqual([(a["kind"], a["trigger"], a["why"]) for a in adj], [("cancel", "orphan", "stop")])
        stats = json.loads(self.stats("--json"))["stats"]["workflows"]["change"]
        self.assertEqual((stats["replacements"], stats["cancelled"]), (1, 1))

    def test_an_approval_records_its_outcome_by_whom_and_when(self):
        inst = self.add("change")
        stages = self.stages(inst)
        self.merge(stages["prd"]["task"])
        opened = self.meta(stages["prd"]["approval_id"])
        self.assertTrue(opened["opened_at"])
        self.events("stage", str(inst), "approve", "prd", "--by", "operator")
        done = self.meta(stages["prd"]["approval_id"])
        self.assertEqual((done["approval_outcome"], done["approved_by"]), ("approved", "operator"))
        self.assertTrue(done["answered_at"])

    def test_a_default_and_a_hold_are_recorded(self):
        self.config('[[workflow_rule]]\nname = "money"\nmatch_paths = ["src/export/**"]\napproval = { prd = "human" }\non_timeout = "hold"\n')
        held = self.add("change", title="Held")
        self.merge(self.stages(held)["prd"]["task"])
        self.events("stage", str(held), "approve", "prd", "--by", "operator")
        self.assertEqual(self.meta(self.stages(held)["prd"]["approval_id"])["approval_outcome"], "held")
        self.config("")
        late = self.add("change", title="Late")
        self.merge(self.stages(late)["prd"]["task"])
        node = self.stages(late)["prd"]["approval_id"]
        self.tg("edit", str(node), "--meta", "due_at=2020-01-01T00:00:00Z")
        self.events("stage", str(late), "approve", "prd", "--default")
        meta = self.meta(node)
        self.assertEqual((meta["approval_outcome"], meta["approved_by"]), ("defaulted", "run.py"))

    def test_stats_reads_taskgraph_and_prints_proposals(self):
        a = self.picked("change,change")
        b = self.add("fix", title="Fix it")
        self.events("stage", str(b), "escalate", "spec", "--before", "impl", "--why", "unclear")
        self.merge(self.stages(a)["prd"]["task"])
        self.events("stage", str(a), "approve", "prd", "--by", "manager")
        out = json.loads(self.stats("--json"))
        w = out["stats"]["workflows"]
        self.assertEqual(out["stats"]["instances"], 2)
        self.assertEqual((w["change"]["instances"], w["change"]["pick"]["picked"], w["change"]["pick"]["agreement_rate"]), (1, 1, 1.0))
        self.assertEqual((w["fix"]["escalations"], w["fix"]["triggers"]), (1, {"escalate:manager": 1}))
        self.assertEqual(w["change"]["stages"]["prd"]["approvals"]["outcomes"], {"approved": 1})
        self.assertEqual(out["proposals"], [])  # too few instances for any rule
        text = self.stats()
        self.assertIn("change: 1 instances", text)
        self.assertIn("Proposals (0", text)

    def test_stats_since_leaves_out_older_instances(self):
        self.add("fix")
        self.assertEqual(json.loads(self.stats("--json", "--since", "2999-01-01"))["stats"]["instances"], 0)
        self.assertEqual(json.loads(self.stats("--json", "--since", "2000-01-01"))["stats"]["instances"], 1)

    def test_stats_with_no_workflows_is_empty(self):
        self.assertIn("0 instances", self.stats())


if __name__ == "__main__":
    unittest.main()
