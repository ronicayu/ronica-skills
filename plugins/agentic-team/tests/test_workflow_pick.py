"""Tests for the workflow pick and the hard rules: the resolution of two typed answers, `add --pick`, the record, `[[workflow_rule]]`
(force a stage on, move the work, refuse `--skip`), `stage recheck`, `stage rechoose`, and the reports after the fact.
Run: "$PY" plugins/agentic-team/tests/run_parallel.py (all tests, in parallel)

Each test builds a temporary git repository and a temporary Taskgraph database, and runs run.py and the real tg.py against
them. A fake `claude` lists no sessions. Nothing here starts a Claude session or reaches the network.
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
import workflows as wfl  # noqa: E402

NOTES = "Why: users need it.\n- [ ] first behaviour\n- [ ] second behaviour"
BILLING = """
    [[workflow_rule]]
    name = "billing"
    match_paths = ["apps/api/billing/**"]
    match_area = ["payments"]
    require_stage = "spec"
    risk = "high"
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
            fh.write("#!/bin/sh\necho '[]'\n")
        os.chmod(os.path.join(self.bin, "claude"), 0o755)
        self.config("")
        self.env = {**os.environ, "HOME": self.home, "TASKGRAPH_DB": os.path.join(self.dir, "tasks.db"),
                    "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""), "CLAUDE_CONFIG_DIR": os.path.join(self.home, "claude")}
        self.env.pop("TASKGRAPH_TG", None)

    def config(self, extra, policy=""):
        with open(os.path.join(self.root, ".agentic-team.toml"), "w") as fh:
            fh.write('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n'
                     f"[workflow_policy]\nenabled = true\n{policy}" + textwrap.dedent(extra))

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

    def meta(self, tid):
        return self.tg("show", str(tid))["meta"]

    def resolve(self, answers):
        events = self.events("workflows", "--resolve", answers)
        return next(e for e in events if e["event"] == "workflow-picked")["detail"]

    def add_pick(self, answers, *flags, scope="src/export/", title="Add export", seed="7", extra=(), link=("--independent", "alone")):
        meta = [f"scope={scope}", "verify=make test", *extra]
        return self.events("add", title, "--pick", answers, "--seed", seed, "--notes", NOTES, "--meta", *meta, *link, *flags)

    def add_named(self, workflow, *flags, scope="src/export/", title="Add export", extra=()):
        return self.events("add", title, "--workflow", workflow, "--notes", NOTES, "--meta", f"scope={scope}", "verify=make test", *extra,
                           "--independent", "alone", *flags)

    @staticmethod
    def instance(events):
        return next(e["task"] for e in events if e["event"] == "workflow-added")

    def record(self, inst):
        return self.meta(inst)["workflow_record"]

    def stage_ids(self, inst):
        return [e["id"] for e in self.record(inst)["stages"]]


class ResolutionTest(Base):
    def test_the_same_name_wins_and_is_not_unsure(self):
        self.assertIn("resolve to fix by agree", self.resolve("fix,fix"))
        self.assertNotIn("unsure", self.resolve("fix,fix"))

    def test_two_different_names_take_the_one_with_fewer_required_stages(self):
        self.assertIn("resolve to hotfix by fewer-stages", self.resolve("feature,hotfix"))
        self.assertIn("resolve to hotfix by fewer-stages", self.resolve("hotfix,feature"))
        self.assertIn("resolve to fix by fewer-stages", self.resolve("change,fix"))  # fix has two required stages, change has three

    def test_a_name_beside_unsure_takes_the_name(self):
        self.assertIn("resolve to feature by name-over-unsure", self.resolve("feature,unsure"))
        self.assertIn("resolve to feature by name-over-unsure", self.resolve("unsure,feature"))

    def test_both_unsure_take_figure_it_out(self):
        detail = self.resolve("unsure,unsure")
        self.assertIn("resolve to figure-it-out by both-unsure", detail)
        self.assertIn("unsure, so lighter", detail)

    def test_figure_it_out_is_outside_the_order_and_a_named_workflow_beats_it(self):
        self.assertIn("resolve to fix by named-over-deciding", self.resolve("figure-it-out,fix"))
        self.assertIn("resolve to figure-it-out by agree", self.resolve("figure-it-out,figure-it-out"))

    def test_the_answer_format_is_read(self):
        self.assertIn("resolve to fix by agree", self.resolve("PICK: Fix,pick: fix"))

    def test_a_bad_answer_is_refused_with_the_names(self):
        err = self.refused("workflows", "--resolve", "fix,banana")
        self.assertIn("'banana' is not a workflow name or unsure", err)
        self.assertIn("hotfix", err)
        self.assertIn("two answers", self.refused("workflows", "--resolve", "fix"))

    def test_when_unsure_heavier_takes_the_heavier_name_and_the_heaviest_for_two_unsure(self):
        self.config("", policy='when_unsure = "heavier"\n')
        self.assertIn("resolve to feature by more-stages", self.resolve("hotfix,feature"))
        self.assertIn("resolve to feature by when-unsure-heavier", self.resolve("unsure,unsure"))
        self.assertIn("resolve to fix by agree", self.resolve("fix,fix"))

    def test_when_unsure_figure_it_out_takes_it_for_every_unsure_or_disagreeing_row(self):
        self.config("", policy='when_unsure = "figure-it-out"\n')
        for answers in ("hotfix,feature", "feature,unsure", "unsure,unsure"):
            self.assertIn("resolve to figure-it-out by when-unsure-figure-it-out", self.resolve(answers))
        self.assertIn("resolve to fix by agree", self.resolve("fix,fix"))

    def test_a_bad_when_unsure_is_a_config_problem(self):
        self.config("", policy='when_unsure = "never"\n')
        out = subprocess.run([sys.executable, os.path.join(PLUGIN, "scripts", "config.py"), "--root", self.root, "check"],
                             capture_output=True, text=True, env=self.env)
        self.assertIn("workflow_policy.when_unsure", out.stdout + out.stderr)

    def test_the_resolver_is_deterministic_on_a_loaded_catalog(self):
        import workflows as wfl
        roles = {"software-engineer": None, "architect": None, "product-manager": None, "ux-designer": None, "tester": None}
        catalog = wfl.load(PLUGIN, self.root, roles)
        wfs = catalog.workflows
        got = [wfl.resolve_pick(wfs, "feature", "fix").workflow for _ in range(3)]
        self.assertEqual(got, ["fix"] * 3)
        self.assertEqual(wfl.resolve_pick(wfs, "unsure", "unsure", "lighter").workflow, "figure-it-out")


class PickAddTest(Base):
    def test_add_pick_records_both_answers_the_seeds_and_the_rule(self):
        events = self.add_pick("fix,unsure", seed="7")
        inst = self.instance(events)
        pick = self.record(inst)["pick"]
        self.assertEqual((pick["answers"], pick["seeds"], pick["resolved"], pick["rule"], pick["unsure"], pick["when_unsure"]),
                         (["fix", "unsure"], [7, 8], "fix", "name-over-unsure", True, "lighter"))
        self.assertEqual(self.meta(inst)["workflow"], "fix")
        self.assertTrue(self.record(inst)["picked_at"].endswith("Z"))
        picked = next(e for e in events if e["event"] == "workflow-picked")
        self.assertIn("answers fix and unsure (seeds 7, 8)", picked["detail"])
        added = next(e for e in events if e["event"] == "workflow-added")
        self.assertIn("pick fix/unsure -> fix (name-over-unsure; unsure -> lighter)", added["detail"])

    def test_an_agreeing_pick_is_not_unsure_and_a_named_workflow_says_so(self):
        inst = self.instance(self.add_pick("hotfix,hotfix"))
        self.assertEqual((self.record(inst)["pick"]["rule"], self.record(inst)["pick"]["unsure"]), ("agree", False))
        named = self.instance(self.add_named("hotfix", title="Other"))
        self.assertEqual(self.record(named)["pick"], {"answers": None, "seeds": None, "resolved": "hotfix", "rule": "named",
                                                      "unsure": False, "when_unsure": "lighter"})

    def test_disagreement_creates_the_lighter_workflow(self):
        inst = self.instance(self.add_pick("feature,hotfix"))
        self.assertEqual(self.stage_ids(inst), ["impl", "test"])
        self.assertEqual(self.record(inst)["pick"]["rule"], "fewer-stages")

    def test_pick_needs_a_seed_and_excludes_workflow(self):
        base = ["add", "T", "--pick", "fix,fix", "--notes", NOTES, "--meta", "scope=src/", "verify=x", "--independent", "a"]
        self.assertIn("--seed", self.refused(*base))
        self.assertIn("leave out --workflow", self.refused(*base, "--seed", "1", "--workflow", "fix"))

    def test_an_unsure_pick_shows_in_status_and_the_digest_and_queues_a_notice_when_asked(self):
        self.config("", policy="")
        with open(os.path.join(self.root, ".agentic-team.toml"), "a") as fh:
            fh.write('[notifications]\nevents = ["workflow-pick"]\n')
        inst = self.instance(self.add_pick("fix,unsure"))
        queue = self.events("notify-queue")
        self.assertEqual([e["event"] for e in queue if e["event"] == "notify"], ["notify"])
        self.assertIn("[workflow-pick] Workflow of #%d Add export: fix" % inst, next(e["detail"] for e in queue if e["event"] == "notify"))
        payload = json.loads(self.run_cmd("--json", "status", "--since", "1d").stdout)
        self.assertEqual(payload["workflow_picks"], [{"Instance": f"#{inst}", "Workflow": "fix Add export",
                                                      "Choice": "pick fix/unsure -> fix (name-over-unsure; unsure -> lighter)"}])
        self.assertIn("## Workflow picks and rule changes (1)", self.run_cmd("status", "--since", "1d").stdout)

    def test_an_agreeing_pick_adds_no_status_section(self):
        self.add_pick("fix,fix")
        out = self.run_cmd("status", "--since", "1d")
        self.assertNotIn("Workflow picks", out.stdout)

    def test_the_digest_lists_picks_when_the_payload_has_them(self):
        payload = {"done": [], "in_flight": [], "decisions": [],
                   "workflow_picks": [{"Instance": "#4", "Workflow": "fix", "Choice": "pick fix/unsure"}]}
        text = runner.digest_text("d", payload)
        self.assertIn("Workflow picks and rule changes: 1 (#4 fix: pick fix/unsure)", text)
        self.assertNotIn("Workflow picks", runner.digest_text("d", {"done": [], "in_flight": [], "decisions": []}))


class RuleTest(Base):
    def setUp(self):
        super().setUp()
        self.config(BILLING)

    def test_a_rule_forces_an_optional_stage_on(self):
        events = self.add_pick("fix,fix", scope="apps/api/billing/invoice.py; do not change anything else")
        inst = self.instance(events)
        self.assertEqual(self.stage_ids(inst), ["spec", "impl", "test"])
        self.assertEqual(self.record(inst)["optional"], {"spec": "with"})
        self.assertEqual(self.record(inst)["rule"], "billing")
        self.assertEqual(self.record(inst)["rules"], [{"rule": "billing", "stage": "spec", "action": "forced-with"}])
        self.assertIn("rule billing forced stage spec on", next(e for e in events if e["event"] == "workflow-added")["detail"])
        self.assertIn("billing: forced-with stage spec", next(e for e in events if e["event"] == "workflow-rule")["detail"])
        self.assertEqual(self.meta(self.record(inst)["stages"][0]["task"])["risk"], "high")

    def test_a_rule_moves_the_work_to_the_lightest_workflow_that_has_the_stage(self):
        events = self.add_pick("hotfix,hotfix", scope="apps/api/billing/")
        inst = self.instance(events)
        self.assertEqual(self.meta(inst)["workflow"], "fix")
        self.assertEqual(self.stage_ids(inst), ["spec", "impl", "test"])
        rules = self.record(inst)["rules"]
        self.assertEqual([(r["rule"], r["action"], r["from"], r["to"], r["stage"]) for r in rules],
                         [("billing", "moved", "hotfix", "fix", "spec")])
        self.assertEqual(self.record(inst)["pick"]["resolved"], "hotfix")  # the original pick stays in the record
        self.assertIn("moved the work from hotfix to fix", next(e for e in events if e["event"] == "workflow-added")["detail"])

    def test_a_workflow_that_requires_the_stage_is_left_as_picked(self):
        inst = self.instance(self.add_pick("feature,feature", scope="apps/api/billing/"))
        self.assertEqual(self.meta(inst)["workflow"], "feature")
        self.assertEqual(self.record(inst)["rules"], [{"rule": "billing", "stage": "spec", "action": "satisfied"}])

    def test_a_rule_required_stage_cannot_be_skipped(self):
        err = self.refused("add", "T", "--workflow", "fix", "--skip", "spec", "--notes", NOTES, "--meta", "scope=apps/api/billing/",
                           "verify=x", "--independent", "a")
        self.assertIn("rule billing requires stage spec", err)
        self.assertIn("cannot be skipped", err)
        err = self.refused("add", "T", "--workflow", "hotfix", "--skip", "spec", "--notes", NOTES, "--meta", "scope=apps/api/billing/",
                           "verify=x", "--independent", "a")
        self.assertIn("cannot be skipped", err)  # after the move to fix, spec is a rule stage
        self.assertEqual(self.tg("ls"), [])

    def test_the_area_meta_matches_and_title_words_never_do(self):
        inst = self.instance(self.add_pick("fix,fix", scope="src/export/", extra=("area=Payments",)))
        self.assertEqual(self.record(inst)["rule"], "billing")
        quiet = self.instance(self.add_pick("fix,fix", scope="src/export/", title="Billing payments invoice credits fix"))
        self.assertIsNone(self.record(quiet)["rule"])
        self.assertEqual(self.record(quiet)["rules"], [])
        self.assertEqual(self.stage_ids(quiet), ["impl", "test"])

    def test_a_path_outside_the_glob_does_not_match(self):
        inst = self.instance(self.add_pick("fix,fix", scope="apps/api/other/"))
        self.assertEqual(self.record(inst)["rules"], [])

    def test_two_rules_that_ask_different_stages_need_one_workflow_with_both(self):
        self.config(BILLING + textwrap.dedent("""
            [[workflow_rule]]
            name = "design"
            match_paths = ["apps/api/billing/**"]
            require_stage = "ux"
            """))
        inst = self.instance(self.add_pick("hotfix,hotfix", scope="apps/api/billing/"))
        self.assertEqual(self.meta(inst)["workflow"], "feature")
        self.assertEqual([r["rule"] for r in self.record(inst)["rules"]], ["billing", "design"])
        self.assertIn("ux", self.stage_ids(inst))

    def test_figure_it_out_defers_the_rule_to_expand(self):
        inst = self.instance(self.add_pick("unsure,unsure", scope="apps/api/billing/"))
        self.assertEqual(self.record(inst)["rules"], [{"rule": "billing", "action": "deferred-to-expand"}])
        self.assertEqual(self.stage_ids(inst), ["investigate"])


class RecheckTest(Base):
    def test_a_rule_that_matches_later_is_recorded_with_the_way_out(self):
        inst = self.instance(self.add_named("hotfix"))
        self.config(BILLING)
        stage = self.record(inst)["stages"][0]["task"]
        self.tg("edit", str(stage), "--meta", 'scope="apps/api/billing/x.py; do not change anything else"')
        events = self.events("stage", str(inst), "recheck")
        line = next(e for e in events if e["event"] == "workflow-rule")
        self.assertIn("billing: newly matches", line["detail"])
        self.assertIn("stage spec is missing", line["detail"])
        self.assertIn(f"stage {inst} rechoose", line["next"])
        rules = self.record(inst)["rules"]
        self.assertEqual([(r["rule"], r["action"]) for r in rules], [("billing", "recheck-missing")])
        again = self.events("stage", str(inst), "recheck")
        self.assertIn("no hard rule matches that the record does not hold", again[-1]["detail"])

    def test_a_started_stage_changes_the_hint(self):
        inst = self.instance(self.add_named("hotfix"))
        self.config(BILLING)
        stage = self.record(inst)["stages"][0]["task"]
        self.tg("edit", str(stage), "--meta", 'scope="apps/api/billing/x.py"', "attempt=1")
        line = next(e for e in self.events("stage", str(inst), "recheck") if e["event"] == "workflow-rule")
        self.assertIn("has started", line["next"])

    def test_a_present_stage_is_satisfied(self):
        inst = self.instance(self.add_named("fix", "--with", "spec"))
        self.config(BILLING)
        self.events("stage", str(inst), "recheck")
        self.assertEqual([(r["rule"], r["action"]) for r in self.record(inst)["rules"]], [])
        stage = self.record(inst)["stages"][1]["task"]
        self.tg("edit", str(stage), "--meta", 'scope="apps/api/billing/x.py"')
        self.events("stage", str(inst), "recheck")
        self.assertEqual([(r["rule"], r["action"]) for r in self.record(inst)["rules"]], [("billing", "recheck-satisfied")])

    def test_a_split_part_is_rechecked(self):
        self.project_split()
        self.config(BILLING)
        inst = self.instance(self.add_named("big"))
        self.events("stage", str(inst), "split", "impl", "--part", "first", "--meta", "scope=apps/api/billing/a.py")
        self.assertEqual([r["rule"] for r in self.record(inst)["rules"]], ["billing"])

    def project_split(self):
        folder = os.path.join(self.root, ".claude", "agentic-team", "workflows")
        os.makedirs(folder)
        with open(os.path.join(folder, "big.md"), "w") as fh:
            fh.write("---\nname: big\ndescription: Impl that may be split.\nstages:\n  - {id: impl, split: true}\n  - {id: test, after: [impl]}\n---\n"
                     "## When to use\nA test.\n")


class RechooseTest(Base):
    def test_rechoose_replaces_the_stages_and_records_the_override(self):
        other = self.tg("add", "Other work", "--notes", "x", "--meta", "independent=\"x\"")["id"]
        inst = self.instance(self.events("add", "Add export", "--workflow", "hotfix", "--notes", NOTES, "--meta", "scope=src/export/",
                                         "verify=make test", "--depends", str(other)))
        old = [e["task"] for e in self.record(inst)["stages"]]
        events = self.events("stage", str(inst), "rechoose", "fix", "--with", "spec", "--by", "operator", "--note", "owner wants a design")
        line = next(e for e in events if e["event"] == "workflow-rechosen")
        self.assertIn("hotfix -> fix by operator", line["detail"])
        self.assertEqual(self.stage_ids(inst), ["spec", "impl", "test"])
        self.assertEqual(self.meta(inst)["workflow"], "fix")
        override = self.record(inst)["overrides"][0]
        self.assertEqual((override["from"], override["to"], override["by"], override["why"]), ("hotfix", "fix", "operator", "owner wants a design"))
        self.assertEqual(self.record(inst)["adjustments"], [])  # an owner override is not an adjustment
        live = {t["id"] for t in self.tg("ls", "--parent", str(inst), "--status", "open", "in_progress", "done")}
        self.assertFalse(live & set(old))
        spec = self.record(inst)["stages"][0]["task"]
        self.assertEqual([d["id"] for d in self.tg("show", str(spec))["depends_on"]], [other])  # the external dependency moved too

    def test_rechoose_is_refused_after_a_stage_has_started(self):
        inst = self.instance(self.add_named("hotfix"))
        self.tg("edit", str(self.record(inst)["stages"][0]["task"]), "--meta", "attempt=1")
        self.assertIn("has started", self.refused("stage", str(inst), "rechoose", "fix", "--by", "operator"))
        self.assertEqual(self.stage_ids(inst), ["impl", "test"])

    def test_rechoose_applies_the_rules_again(self):
        self.config(BILLING)
        inst = self.instance(self.add_pick("fix,fix", scope="apps/api/billing/"))
        self.events("stage", str(inst), "rechoose", "hotfix", "--by", "operator")
        self.assertEqual(self.meta(inst)["workflow"], "fix")  # the rule moved it back to a workflow with spec
        self.assertEqual(self.stage_ids(inst), ["spec", "impl", "test"])
        self.assertEqual(self.record(inst)["overrides"][0]["to"], "fix")

    def test_rechoose_needs_a_known_workflow_name(self):
        inst = self.instance(self.add_named("hotfix"))
        self.assertIn("no workflow named 'nope'", self.refused("stage", str(inst), "rechoose", "nope", "--by", "operator"))
        self.assertIn("needs a workflow name", self.refused("stage", str(inst), "rechoose"))


class RuleGlobTest(unittest.TestCase):
    RULE = {"name": "b", "match_paths": ["apps/api/billing/**"]}

    def matches(self, scope):
        return wfl.rule_matches(self.RULE, runner.write_paths(scope), None)

    def test_a_scope_directory_above_the_glob_matches(self):
        for scope in ("apps/", "apps/api/", "apps/api/**", "apps/api/billing/", "apps/api/billing/x.py"):
            self.assertTrue(self.matches(scope), scope)

    def test_a_directory_beside_or_below_the_glob_does_not_match(self):
        for scope in ("apps/other/", "apps/ap/", "apps/api/billing2/", "apps/api/users/", "src/"):
            self.assertFalse(self.matches(scope), scope)

    def test_a_glob_with_a_wildcard_in_the_middle_is_matched_above_its_literal_text(self):
        rule = {"name": "w", "match_paths": ["apps/*/billing/**"]}
        self.assertTrue(wfl.rule_matches(rule, runner.write_paths("apps/"), None))
        self.assertFalse(wfl.rule_matches(rule, runner.write_paths("lib/"), None))


class LateRuleTest(Base):
    RAISE = BILLING + """
    [[workflow_rule]]
    name = "money"
    match_paths = ["apps/api/billing/**"]
    risk = "high"
    on_timeout = "hold"
    approval = { prd = "human", spec = "human" }
    """

    def merge(self, tid):
        self.tg("edit", str(tid), "--meta", "attempt=1", "verdict_ref=" + "a" * 40, "verdict=test-verified", "sessions=[]")
        self.tg("done", str(tid))
        self.events("merged", str(tid), "--by", "operator")

    def stage_tasks(self, inst):
        return {e["id"]: e for e in self.record(inst)["stages"]}

    def test_recheck_raises_the_approvals_that_are_not_done_and_the_risk_of_stages_that_have_not_started(self):
        inst = self.instance(self.add_named("feature", scope="lib/"))
        stages = self.stage_tasks(inst)
        self.config(self.RAISE)
        self.merge(stages["prd"]["task"])
        self.assertEqual(self.meta(stages["prd"]["approval_id"])["approval_state"], "open")
        self.assertEqual(self.meta(stages["spec"]["approval_id"])["approval_state"], "pending")
        self.tg("edit", str(stages["test"]["task"]), "--meta", 'scope="apps/api/billing/x.py"')
        events = self.events("stage", str(inst), "recheck")
        line = next(e for e in events if e["event"] == "workflow-rule" and "money" in e["detail"])
        self.assertIn("raised prd", line["detail"])
        open_one, pending = self.meta(stages["prd"]["approval_id"]), self.meta(stages["spec"]["approval_id"])
        self.assertEqual((open_one["approval_level"], open_one["decider"]), ("human", "operator"))
        self.assertEqual((pending["approval_level"], pending["on_timeout"], pending["default"]), ("human", "hold", "hold"))
        self.assertEqual(self.meta(stages["spec"]["task"]).get("risk"), "high")
        self.assertIsNone(self.meta(stages["prd"]["task"]).get("risk"))  # merged: it has started
        row = next(r for r in self.record(inst)["rules"] if r["rule"] == "money")
        self.assertEqual({(r["stage"], r["from"], r["to"], r["state"]) for r in row["raised"]},
                         {("prd", "manager", "human", "open"), ("spec", "manager", "human", "pending")})
        self.assertIn("spec", row["risk"]["stages"])
        self.assertEqual({e["id"]: e["approval"] for e in self.record(inst)["stages"]}["spec"], "human")

    def test_recheck_then_rechoose_keeps_the_rule_and_the_scope_of_a_part(self):
        self.config("""
            [[workflow_rule]]
            name = "ux-rule"
            match_paths = ["src/export/ui/**"]
            require_stage = "ux"
            """)
        inst = self.instance(self.add_named("feature", "--with", "ux", scope="lib/"))
        self.events("stage", str(inst), "split", "impl", "--part", "ui", "--meta", "scope=src/export/ui/page.py")
        self.assertEqual([(r["rule"], r["action"]) for r in self.record(inst)["rules"]], [("ux-rule", "recheck-satisfied")])
        self.events("stage", str(inst), "rechoose", "feature", "--by", "operator")
        record = self.record(inst)
        self.assertIn("ux", self.stage_ids(inst))
        self.assertEqual([(r["rule"], r["action"]) for r in record["rules"]], [("ux-rule", "recheck-satisfied"), ("ux-rule", "forced-with")])
        self.assertIn("src/export/ui/page.py", runner.write_paths(record["scope"]))
        impl = next(e["task"] for e in record["stages"] if e["id"] == "impl")
        self.assertIn("src/export/ui/page.py", runner.write_paths(self.meta(impl)["scope"]))

    def test_rechoose_is_refused_while_a_task_outside_the_instance_depends_on_a_stage(self):
        inst = self.instance(self.add_named("hotfix"))
        outside = self.tg("add", "Downstream", "--meta", 'independent="x"')["id"]
        stage = self.stage_tasks(inst)["impl"]["task"]
        self.tg("dep", "add", str(outside), str(stage))
        err = self.refused("stage", str(inst), "rechoose", "fix", "--by", "operator")
        self.assertIn(f"#{outside} depends on impl (#{stage})", err)
        self.assertIn("move the edge to the instance", err)
        self.assertEqual(self.stage_ids(inst), ["impl", "test"])
        self.assertEqual(self.meta(inst)["workflow"], "hotfix")


if __name__ == "__main__":
    unittest.main()
