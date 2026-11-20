"""Tests for workflow instances: `run.py add --workflow`, the approval decisions, `run.py stage` and the relay of upstream
results into a stage brief. Run: "$PY" plugins/agentic-team/tests/run_parallel.py (all tests, in parallel)

Each test builds a temporary git repository and a temporary Taskgraph database, and runs run.py and the real tg.py against
them. A fake `claude` lists no sessions. Nothing here starts a Claude session or reaches the network.
"""

import datetime
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
import workflows as wfl  # noqa: E402

SHA = "a" * 40
NOTES = "Why: users need it.\n- [ ] first behaviour\n- [ ] second behaviour"


def stamp(delta=datetime.timedelta()):
    return (datetime.datetime.now(datetime.timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    config_extra = ""

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
            fh.write("#!/bin/sh\necho '[]'\n")
        os.chmod(os.path.join(self.bin, "claude"), 0o755)
        self.config("")
        self.env = {**os.environ, "HOME": self.home, "TASKGRAPH_DB": os.path.join(self.dir, "tasks.db"),
                    "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""), "CLAUDE_CONFIG_DIR": os.path.join(self.home, "claude")}
        self.env.pop("TASKGRAPH_TG", None)

    def config(self, extra, enabled=True):
        with open(os.path.join(self.root, ".agentic-team.toml"), "w") as fh:
            fh.write('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n'
                     f"[workflow_policy]\nenabled = {str(enabled).lower()}\n" + textwrap.dedent(extra))

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

    def tg(self, *args):
        out = subprocess.run([sys.executable, TG, "--project", "demo", "--json", *args], capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def node(self, tid):
        return self.tg("show", str(tid))

    def meta(self, tid):
        return self.node(tid)["meta"]

    def deps(self, tid):
        return sorted(d["id"] for d in self.node(tid)["depends_on"])

    def add(self, workflow, title="Add export", *flags, notes=NOTES, meta=("scope=src/export/", "verify=make test"), link=("--independent", "alone")):
        events = self.events("add", title, "--workflow", workflow, "--notes", notes, "--meta", *meta, *link, *flags)
        return events

    def instance(self, events):
        return next(e["task"] for e in events if e["event"] == "workflow-added")

    def stages(self, inst):
        """{stage id: task id} of an instance, from its record."""
        return {e["id"]: e["task"] for e in self.meta(inst)["workflow_record"]["stages"]}

    def approval(self, inst, stage):
        return next(e["approval_id"] for e in self.meta(inst)["workflow_record"]["stages"] if e["id"] == stage)

    def merge(self, tid):
        """Record a stage task as closed and merged, as `run.py merged` does."""
        self.tg("edit", str(tid), "--meta", "attempt=1", f"verdict_ref={SHA}", "verdict=test-verified", "sessions=[]")
        self.tg("done", str(tid))
        self.events("merged", str(tid), "--by", "operator")

    def report(self, tid, body):
        subprocess.run([sys.executable, TG, "--project", "demo", "--json", "result", "add", str(tid), "--kind", "task",
                        "--attempt", "1", "--by", "worker", "--status", "PASS", "--body-file", "-"],
                       input=body, capture_output=True, text=True, env=self.env, check=True)

    def queue(self):
        return json.loads(self.run_cmd("--json", "notify-queue").stdout)


class ExpansionTest(Base):
    def test_hotfix_makes_an_instance_with_two_stages_and_no_approval(self):
        events = self.add("hotfix")
        inst = self.instance(events)
        stages = self.stages(inst)
        self.assertEqual(list(stages), ["impl", "test"])
        meta = self.meta(inst)
        self.assertEqual(meta["workflow"], "hotfix")
        self.assertEqual(meta["workflow_record"]["workflow"], "hotfix")
        self.assertEqual(self.node(inst)["title"], "Add export")
        impl, test = self.node(stages["impl"]), self.node(stages["test"])
        self.assertEqual((impl["parent"], test["parent"]), (inst, inst))
        self.assertEqual(impl["title"], "Add export — impl")
        self.assertEqual((impl["meta"]["stage"], impl["meta"]["role"], impl["meta"]["verify_kind"], impl["meta"]["scope"],
                          impl["meta"]["verify"], impl["meta"]["stage_origin"]),
                         ("impl", "software-engineer", "code", "src/export/", "make test", "expand"))
        self.assertEqual(self.deps(stages["impl"]), [])
        self.assertEqual(self.deps(stages["test"]), [stages["impl"]])
        self.assertIn("- [ ] first behaviour", impl["notes"])
        self.assertIn("Why: users need it.", impl["notes"])
        self.assertEqual(self.tg("ls", "--type", "decision"), [])

    def test_fix_leaves_out_spec_by_default_and_creates_it_with_with(self):
        plain = self.instance(self.add("fix"))
        self.assertEqual(list(self.stages(plain)), ["impl", "test"])
        self.assertEqual(self.meta(plain)["workflow_record"]["optional"], {"spec": "default-skipped"})
        inst = self.instance(self.add("fix", "Fix export", "--with", "spec"))
        stages = self.stages(inst)
        self.assertEqual(list(stages), ["spec", "impl", "test"])
        spec = self.node(stages["spec"])
        self.assertEqual((spec["meta"]["verify_kind"], spec["meta"]["role"], spec["meta"]["stage_origin"]), ("design-doc", "architect", "with"))
        self.assertEqual(spec["meta"]["scope"], "docs/design/fix-export-spec.md; do not change anything else")
        self.assertIn("Covers every instance acceptance line.", spec["notes"])
        self.assertIn("Instance acceptance: first behaviour; second behaviour", spec["notes"])
        decision = self.approval(inst, "spec")
        self.assertEqual(self.deps(stages["impl"]), sorted([stages["spec"], decision]))

    def test_change_has_prd_then_impl_then_test(self):
        inst = self.instance(self.add("change"))
        stages = self.stages(inst)
        self.assertEqual(list(stages), ["prd", "impl", "test"])
        self.assertEqual(self.deps(stages["impl"]), sorted([stages["prd"], self.approval(inst, "prd")]))
        self.assertEqual(self.deps(stages["test"]), [stages["impl"]])

    def test_feature_skips_ux_by_default_and_links_spec_to_prd(self):
        inst = self.instance(self.add("feature"))
        stages = self.stages(inst)
        self.assertEqual(list(stages), ["prd", "spec", "impl", "test"])
        self.assertEqual(self.deps(stages["spec"]), sorted([stages["prd"], self.approval(inst, "prd")]))
        self.assertEqual(self.deps(stages["impl"]), sorted([stages["spec"], self.approval(inst, "spec")]))
        self.assertEqual(self.meta(inst)["workflow_record"]["optional"], {"ux": "default-skipped"})
        explicit = self.instance(self.add("feature", "Other", "--skip", "ux"))
        self.assertEqual(self.meta(explicit)["workflow_record"]["optional"], {"ux": "skipped"})

    def test_feature_with_ux_puts_ux_between_prd_and_spec(self):
        inst = self.instance(self.add("feature", "Add export", "--with", "ux"))
        stages = self.stages(inst)
        self.assertEqual(list(stages), ["prd", "ux", "spec", "impl", "test"])
        self.assertEqual(self.deps(stages["ux"]), sorted([stages["prd"], self.approval(inst, "prd")]))
        self.assertEqual(self.deps(stages["spec"]), sorted([stages["prd"], self.approval(inst, "prd"), stages["ux"], self.approval(inst, "ux")]))
        self.assertTrue(self.meta(stages["impl"]) and self.meta(inst)["workflow_record"]["stages"][3]["split"])

    def test_figure_it_out_creates_the_investigate_stage_with_an_approval(self):
        inst = self.instance(self.add("figure-it-out"))
        stages = self.stages(inst)
        self.assertEqual(list(stages), ["investigate"])
        decision = self.node(self.approval(inst, "investigate"))
        self.assertEqual((decision["type"], decision["parent"], decision["meta"]["decider"]), ("decision", inst, "manager"))
        self.assertEqual(self.node(inst)["derived_status"], "blocked")

    def test_a_skipped_stage_in_the_middle_is_contracted_away(self):
        self.project_workflow("mid", """\
            ---
            name: mid
            description: A middle stage that may be left out.
            stages:
              - {id: prd}
              - {id: ux, optional: true, after: [prd]}
              - {id: impl, after: [ux]}
            ---
            ## When to use
            Always.
            """)
        skipped = self.stages(self.instance(self.add("mid")))
        self.assertEqual(list(skipped), ["prd", "impl"])
        inst = self.instance(self.add("mid", "Other", "--with", "ux"))
        with_ux = self.stages(inst)
        self.assertEqual(self.deps(with_ux["impl"]), sorted([with_ux["ux"], self.approval(inst, "ux")]))
        first = next(t for t in self.tg("ls") if t["title"] == "Add export — impl")
        self.assertEqual(sorted(d["id"] if isinstance(d, dict) else d for d in first["depends_on"]),
                         sorted([skipped["prd"], self.meta(skipped["prd"]).get("approval_id")]))

    def test_with_and_skip_name_optional_stages_only(self):
        self.assertIn("stage impl is required", self.refused("add", "x", "--workflow", "fix", "--with", "impl", "--independent", "a",
                                                               "--notes", NOTES, "--meta", "scope=s/", "verify=v"))
        self.assertIn("has no stage nope", self.refused("add", "x", "--workflow", "fix", "--skip", "nope", "--independent", "a",
                                                          "--notes", NOTES, "--meta", "scope=s/", "verify=v"))
        self.assertIn("both --with and --skip", self.refused("add", "x", "--workflow", "fix", "--with", "spec", "--skip", "spec",
                                                               "--independent", "a", "--notes", NOTES, "--meta", "scope=s/", "verify=v"))
        self.assertEqual(self.tg("ls"), [])

    def test_workflows_off_and_unsettled_dependencies_refuse(self):
        self.config("", enabled=False)
        self.assertIn("workflows are off", self.refused("add", "x", "--workflow", "hotfix", "--independent", "a", "--notes", NOTES,
                                                         "--meta", "scope=s/", "verify=v"))
        self.config("")
        self.assertIn("settle the dependencies", self.refused("add", "x", "--workflow", "hotfix", "--notes", NOTES,
                                                               "--meta", "scope=s/", "verify=v"))
        self.assertIn("acceptance lines", self.refused("add", "x", "--workflow", "hotfix", "--independent", "a", "--notes", "Why: a.",
                                                        "--meta", "scope=s/", "verify=v"))
        self.assertIn("no workflow named", self.refused("add", "x", "--workflow", "nope", "--independent", "a", "--notes", NOTES))
        self.assertEqual(self.tg("ls"), [])


class LinksTest(Base):
    def test_external_depends_land_on_the_root_stages_only(self):
        outside = self.tg("add", "Outside", "--meta", "scope=o/")["id"]
        inst = self.instance(self.add("feature", link=("--depends", str(outside))))
        stages = self.stages(inst)
        self.assertEqual(self.deps(stages["prd"]), [outside])
        self.assertNotIn(outside, self.deps(stages["spec"]))
        self.assertEqual(self.deps(inst), [])

    def test_blocks_make_the_task_wait_for_the_whole_instance(self):
        later = self.tg("add", "Later", "--meta", "scope=l/")["id"]
        inst = self.instance(self.add("hotfix", link=("--blocks", str(later))))
        stages = self.stages(inst)
        self.assertEqual(self.deps(later), [inst])
        self.merge(stages["impl"])
        self.assertEqual(self.node(later)["derived_status"], "blocked")
        self.merge(stages["test"])
        self.assertEqual(self.node(later)["derived_status"], "ready")

    def test_a_root_stage_without_external_links_records_why_it_has_none(self):
        stages = self.stages(self.instance(self.add("hotfix", link=("--independent", "nothing else touches it"))))
        self.assertEqual(self.meta(stages["impl"])["independent"], "nothing else touches it")

    def test_launch_refuses_an_instance_and_a_stage_that_waits(self):
        inst = self.instance(self.add("change"))
        stages = self.stages(inst)
        self.assertIn("workflow instance", self.refused("launch", str(inst)))
        self.assertIn(f"#{stages['prd']}", self.refused("launch", str(stages["impl"])))
        self.merge(stages["prd"])
        message = self.refused("launch", str(stages["impl"]))
        self.assertIn(f"#{self.approval(inst, 'prd')} (decision)", message)
        self.events("stage", str(inst), "approve", "prd")
        self.assertNotIn("(decision)", self.run_cmd("launch", str(stages["impl"]), "--dry-run").stderr)

    def test_record_leaves_the_instance_out_of_the_unmanaged_list(self):
        events = []
        task = {"id": 5, "meta": {"workflow": "feature"}, "status": "in_progress"}
        runner.record_in_progress(None, None, task, events)
        self.assertEqual(events, [])
        runner.record_in_progress(None, None, {"id": 6, "meta": {}, "status": "in_progress"}, events)
        self.assertEqual(events, [6])  # a task that run.py did not start is listed; an instance is not


class ApprovalTest(Base):
    def test_a_manager_decision_has_no_due_until_the_stage_merges_then_is_due_in_two_hours_and_approves_by_default(self):
        inst = self.instance(self.add("change"))
        stages = self.stages(inst)
        decision = self.approval(inst, "prd")
        before = self.node(decision)
        self.assertEqual((before["meta"]["decider"], before["meta"]["default"], before["meta"]["approval_state"]),
                         ("manager", "approve", "pending"))
        self.assertNotIn("due_at", before["meta"])
        self.assertEqual(before["parent"], inst)
        self.assertEqual(self.deps(decision), [stages["prd"]])
        self.merge(stages["prd"])
        after = self.meta(decision)
        due = datetime.datetime.fromisoformat(after["due_at"].replace("Z", "+00:00"))
        self.assertAlmostEqual((due - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 3600, 2, delta=0.05)
        self.assertEqual((after["approval_state"], after["decider"], after["default"]), ("open", "manager", "approve"))
        self.assertEqual(after["decide_by"], after["due_at"][:10])
        self.assertEqual([e for e in self.queue() if e["event"] == "notify"], [])  # a manager decision notifies no one

    def human_workflow(self):
        self.project_workflow("careful", """\
            ---
            name: careful
            description: A spec that the owner approves.
            stages:
              - {id: spec, approval: human}
              - {id: impl, after: [spec]}
            ---
            ## When to use
            Always.
            """)

    def test_a_human_decision_becomes_an_owner_decision_and_notifies_when_the_stage_merges(self):
        self.human_workflow()
        inst = self.instance(self.add("careful"))
        stages = self.stages(inst)
        decision = self.approval(inst, "spec")
        self.assertEqual(self.meta(decision)["decider"], "manager")
        self.assertEqual(self.meta(decision)["approval_level"], "human")
        self.assertEqual([e for e in self.queue() if e["event"] == "notify"], [])
        self.merge(stages["spec"])
        meta = self.meta(decision)
        self.assertEqual((meta["decider"], meta["default"], meta["approval_state"]), ("operator", "approve", "open"))
        due = datetime.datetime.fromisoformat(meta["due_at"].replace("Z", "+00:00"))
        self.assertAlmostEqual((due - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 3600, 48, delta=0.05)
        notices = [e for e in self.queue() if e["event"] == "notify"]
        self.assertEqual(len(notices), 1)
        self.assertIn(f"Decision #{decision} needs you", notices[0]["detail"])
        self.assertIn(f"default if no answer: approve; answer by: {meta['due_at']}", notices[0]["next"])
        self.assertIn(f"#{stages['impl']} wait for it", notices[0]["next"])
        self.events("record")  # a second pass queues nothing new
        self.assertEqual(len([e for e in self.queue() if e["event"] == "notify"]), 1)

    def test_record_approves_a_due_decision_by_default_and_unblocks_the_next_stage(self):
        inst = self.instance(self.add("change"))
        stages = self.stages(inst)
        decision = self.approval(inst, "prd")
        self.merge(stages["prd"])
        self.assertEqual(self.node(stages["impl"])["derived_status"], "blocked")
        self.events("record")
        self.assertEqual(self.node(decision)["status"], "open")  # not due yet
        self.tg("edit", str(decision), "--meta", f'due_at="{stamp(-datetime.timedelta(minutes=5))}"')
        events = self.events("record")
        self.assertEqual([e["event"] for e in events if e["event"] == "approval-due"], ["approval-due"])
        done = self.node(decision)
        self.assertEqual(done["status"], "done")
        self.assertIn("Approved by default", done["notes"])
        self.assertEqual(self.node(stages["impl"])["derived_status"], "ready")
        self.assertNotIn("decision", [e["event"] for e in events])

    def test_a_rule_can_raise_an_approval_to_human_and_hold_it_without_a_deadline(self):
        self.config("""\
            [[workflow_rule]]
            name = "billing"
            match_paths = ["src/billing/**"]
            approval = { spec = "human" }
            on_timeout = "hold"
            risk = "high"
            """)
        inst = self.instance(self.add("fix", "Fix invoice", "--with", "spec", meta=("scope=src/billing/invoice.py", "verify=make test")))
        stages = self.stages(inst)
        decision = self.approval(inst, "spec")
        self.assertEqual(self.meta(decision)["on_timeout"], "hold")
        self.assertEqual(self.meta(stages["impl"])["risk"], "high")
        self.assertEqual(self.meta(inst)["workflow_record"]["rule"], "billing")
        self.merge(stages["spec"])
        meta = self.meta(decision)
        self.assertEqual((meta["decider"], meta["approval_state"]), ("operator", "open"))
        self.assertNotIn("due_at", meta)
        self.assertIsNone(self.node(decision)["due"])
        self.events("record")
        self.assertEqual(self.node(decision)["status"], "open")
        self.assertIn("holds until the owner answers", self.refused("stage", str(inst), "approve", "spec", "--default"))
        self.assertIn("the owner's", self.refused("stage", str(inst), "approve", "spec"))
        self.events("stage", str(inst), "approve", "spec", "--by", "operator", "--note", "go ahead")
        self.assertIn("go ahead", self.node(decision)["notes"])
        self.assertEqual(self.node(decision)["status"], "done")

    def test_the_approval_floor_raises_a_stage_to_manager(self):
        self.project_workflow("plain", """\
            ---
            name: plain
            description: One stage.
            stages:
              - {id: impl}
            ---
            ## When to use
            Always.
            """)
        with open(os.path.join(self.root, ".agentic-team.toml"), "a") as fh:
            fh.write('approval_floor = { code = "manager" }\n')
        inst = self.instance(self.add("plain"))
        self.assertEqual(self.meta(self.approval(inst, "impl"))["approval_level"], "manager")

    def test_stage_approve_default_waits_for_the_due_time(self):
        inst = self.instance(self.add("change"))
        stages = self.stages(inst)
        self.assertIn("is not merged yet", self.refused("stage", str(inst), "approve", "prd"))
        self.merge(stages["prd"])
        self.assertIn("--default applies after it", self.refused("stage", str(inst), "approve", "prd", "--default"))
        self.tg("edit", str(self.approval(inst, "prd")), "--meta", f'due_at="{stamp(-datetime.timedelta(minutes=1))}"')
        self.events("stage", str(inst), "approve", "prd", "--default")
        self.assertEqual(self.node(self.approval(inst, "prd"))["status"], "done")
        self.assertEqual(self.events("stage", str(inst), "approve", "prd")[0]["detail"], "prd of #%d is approved already" % inst)

    def test_a_manager_approval_needs_the_decision_follow_ups_triaged(self):
        inst = self.instance(self.add("change"))
        stages = self.stages(inst)
        self.merge(stages["prd"])
        self.report(stages["prd"], "Status: PASS\nHead: " + SHA + "\nFollow-ups: decision: which format: owner call\n")
        message = self.refused("stage", str(inst), "approve", "prd")
        self.assertIn("decision follow-up", message)
        self.assertIn("is not triaged", message)
        row = message.split("--row ")[1].split(" ")[0]
        self.events("triage", str(stages["prd"]), "--row", row, "--to", "dismissed", "--why", "not needed")
        self.events("stage", str(inst), "approve", "prd")
        self.assertEqual(self.node(self.approval(inst, "prd"))["status"], "done")


class SplitTest(Base):
    def feature(self):
        inst = self.instance(self.add("feature"))
        stages = self.stages(inst)
        self.merge(stages["prd"])
        self.events("stage", str(inst), "approve", "prd", "--note", "ok")
        self.merge(stages["spec"])
        return inst, stages

    def test_the_spec_approval_waits_for_the_split_or_a_decline(self):
        inst, stages = self.feature()
        self.assertIn("stage impl may be split", self.refused("stage", str(inst), "approve", "spec"))
        self.events("stage", str(inst), "approve", "spec", "--decline-split", "one small phase")
        self.assertEqual(self.meta(stages["impl"])["split_declined"], "one small phase")

    def test_a_split_makes_parts_and_the_next_stage_waits_for_all_of_them(self):
        inst, stages = self.feature()
        self.events("stage", str(inst), "split", "impl", "--part", "api", "--meta", "scope=src/api/")
        self.assertEqual(self.meta(stages["impl"])["stage_part"], 1)
        self.assertEqual(self.meta(stages["impl"])["scope"], "src/api/")
        self.assertEqual(self.node(stages["impl"])["title"], "Add export — impl: api")
        events = self.events("stage", str(inst), "split", "impl", "--part", "web", "--meta", "scope=src/web/")
        second = next(e["task"] for e in events if e["event"] == "split")
        part = self.node(second)
        self.assertEqual((part["meta"]["stage"], part["meta"]["stage_part"], part["meta"]["stage_origin"], part["parent"]),
                         ("impl", 2, "split", inst))
        self.assertEqual(self.deps(second), self.deps(stages["impl"]))
        self.assertEqual(sorted(self.deps(stages["test"])), sorted([stages["impl"], second]))
        self.assertEqual(self.meta(inst)["workflow_record"]["stages"][2]["parts"], [stages["impl"], second])
        self.events("stage", str(inst), "approve", "spec")  # split done: the approval can be answered
        self.assertEqual(self.node(self.approval(inst, "spec"))["status"], "done")

    def test_parts_that_share_files_must_name_each_other_and_only_a_splittable_stage_splits(self):
        inst, stages = self.feature()
        self.events("stage", str(inst), "split", "impl", "--part", "api", "--meta", "scope=src/api/core/lexer/")
        message = self.refused("stage", str(inst), "split", "impl", "--part", "more", "--meta", "scope=src/api/core/lexer/x.py")
        self.assertIn(f"name it with --depends {stages['impl']}", message)
        self.events("stage", str(inst), "split", "impl", "--part", "more", "--meta", "scope=src/api/core/lexer/x.py", "--depends", str(stages["impl"]))
        self.assertIn("cannot be split", self.refused("stage", str(inst), "split", "test", "--part", "x", "--meta", "scope=t/"))
        self.assertIn("needs its own files", self.refused("stage", str(inst), "split", "impl", "--part", "x"))


class RelayTest(Base):
    def test_a_downstream_brief_carries_the_upstream_summary_files_head_and_the_stage_notes(self):
        inst = self.instance(self.add("change"))
        stages = self.stages(inst)
        self.report(stages["prd"], f"Status: PASS\nSummary: The export has two formats.\nHead: {SHA}\nFiles: `docs/design/add-export-prd.md`\n")
        self.merge(stages["prd"])
        self.events("stage", str(inst), "approve", "prd", "--note", "the format is csv")
        out = self.run_cmd("launch", str(stages["impl"]), "--dry-run")
        text = out.stdout
        self.assertIn(f"- Workflow: change #{inst}, stage impl (2 of 3)", text)
        self.assertIn(f"- Upstream prd #{stages['prd']}: The export has two formats.; Files: `docs/design/add-export-prd.md`; Head aaaaaaa", text)
        self.assertIn("Decision #", text)
        self.assertIn("the format is csv", text)

    def test_stage_notes_come_from_the_workflow_body(self):
        inst = self.instance(self.add("hotfix"))
        notes = self.meta(self.stages(inst)["impl"])["workflow_notes"]
        self.assertTrue(notes.startswith("Commit the failing test before the fix"))
        out = self.run_cmd("launch", str(self.stages(inst)["impl"]), "--dry-run").stdout
        self.assertIn("- Workflow notes: Commit the failing test before the fix", out)
        self.assertIn(f"- Workflow: hotfix #{inst}, stage impl (1 of 2)", out)


class PlanTest(unittest.TestCase):
    def test_stage_notes_cut_at_a_heading_and_at_150_words(self):
        body = "## Stage notes\n### a\none two\n### b\n" + "w " * 200 + "\n## Other\ntext\n"
        self.assertEqual(wfl.stage_notes(body, "a"), "one two")
        self.assertEqual(len(wfl.stage_notes(body, "b").split()), 150)
        self.assertEqual(wfl.stage_notes(body, "c"), "")
        self.assertEqual(wfl.stage_notes("## Steps\nx", "a"), "")

    def test_rule_matching_is_by_scope_glob_or_area(self):
        rule = {"name": "r", "match_paths": ["apps/api/billing/**", "db/migrations/*.sql"], "match_area": ["payments"]}
        self.assertTrue(wfl.rule_matches(rule, {"apps/api/billing/invoice.py"}, None))
        self.assertTrue(wfl.rule_matches(rule, {"apps/api/billing"}, None))
        self.assertTrue(wfl.rule_matches(rule, {"db/migrations/001.sql"}, None))
        self.assertFalse(wfl.rule_matches(rule, {"db/migrations/sub/001.sql"}, None))
        self.assertFalse(wfl.rule_matches(rule, {"apps/api/other.py"}, "Billing words"))
        self.assertTrue(wfl.rule_matches(rule, set(), "Payments"))


if __name__ == "__main__":
    unittest.main()
