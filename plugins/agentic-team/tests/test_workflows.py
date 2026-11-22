"""Tests for workflow files: scripts/workflows.py, `run.py workflows` and the workflow check of `config.py check`.
Run: "$PY" plugins/agentic-team/tests/run_parallel.py (all tests, in parallel)

Each test builds its own temporary folders. The parser tests call workflows.py directly; the command tests run run.py in a
temporary git repository. Nothing here starts a Claude session or reaches the network.
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
PLUGIN = os.path.dirname(HERE)
RUN = os.path.join(PLUGIN, "scripts", "run.py")
CONFIG = os.path.join(PLUGIN, "scripts", "config.py")
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))

import workflows as wf  # noqa: E402

ROLES = {"architect": None, "software-engineer": None, "rebase": None}

LIBRARY = """
[stage.spec]
role = "architect"
verify = "design-doc"
approval = "manager"
scope = "{design_dir}/{slug}.md"
[stage.prd]
role = "architect"
verify = "design-doc"
approval = "manager"
[stage.impl]
role = "software-engineer"
verify = "code"
approval = "auto"
estimate = 3
[stage.test]
role = "software-engineer"
verify = "code"
approval = "auto"
"""


def dedent(text):
    return textwrap.dedent(text).lstrip("\n")


class Tree:
    """A temporary plugin folder and project folder, each with a workflows folder."""

    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.dir = os.path.realpath(tmp.name)
        self.plugin = os.path.join(self.dir, "plugin")
        self.root = os.path.join(self.dir, "repo")
        self.plugin_dir = os.path.join(self.plugin, "templates", "workflows")
        self.project_dir = os.path.join(self.root, ".claude", "agentic-team", "workflows")
        for path in (self.plugin_dir, self.project_dir):
            os.makedirs(path)
        self.write(self.plugin_dir, "stages.toml", LIBRARY)

    @staticmethod
    def write(folder, name, text):
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(dedent(text))
        return path

    def plugin_wf(self, name, text):
        return self.write(self.plugin_dir, f"{name}.md", text)

    def project_wf(self, name, text):
        return self.write(self.project_dir, f"{name}.md", text)

    def load(self, roles=None):
        return wf.load(self.plugin, self.root, ROLES if roles is None else roles)


def workflow(name="demo", description="A demo workflow.", stages=("  - {id: impl}",), extra="", body="## When to use\nAlways.\n"):
    return f"---\nname: {name}\ndescription: {description}\n{extra}stages:\n" + "\n".join(stages) + f"\n---\n{body}"


class ParserTest(unittest.TestCase):
    def setUp(self):
        self.tree = Tree(self)
        self.tree.plugin_wf("spec-first", workflow("spec-first", stages=("  - {id: spec}", "  - {id: impl, after: [spec]}")))

    def broken(self, text, name="demo", roles=None):
        """The problems of a plugin workflow file `name` with `text`."""
        path = self.tree.plugin_wf(name, text)
        catalog = self.tree.load(roles)
        self.assertEqual(catalog.library.errors, [])
        problems = catalog.workflows[name].errors
        self.assertTrue(problems, "the file should be broken")
        self.assertTrue(all(p.startswith(path) for p in problems), problems)
        return problems

    def test_a_valid_file_reads_every_field_with_the_library_values_under_it(self):
        self.tree.plugin_wf("demo", workflow(stages=(
            "  - {id: prd}",
            "  - {id: spec, after: [prd], optional: true, approval: human}  # a comment after the map",
            "  - {id: impl-api, type: impl, after: [spec], split: true, estimate: 4.5, role: architect, verify: code}",
            "  - {id: test, after: [impl-api]}",
        )))
        catalog = self.tree.load()
        self.assertEqual(catalog.problems, [])
        stages = {s.id: s for s in catalog.workflows["demo"].stages}
        self.assertEqual(list(stages), ["prd", "spec", "impl-api", "test"])
        self.assertEqual((stages["spec"].optional, stages["spec"].approval, stages["spec"].after), (True, "human", ["prd"]))
        self.assertEqual(stages["spec"].scope, "{design_dir}/{slug}.md")
        api = stages["impl-api"]
        self.assertEqual((api.type, api.split, api.estimate, api.role, api.verify, api.scope), ("impl", True, 4.5, "architect", "code", "instance"))
        self.assertEqual(stages["test"].estimate, None)
        self.assertEqual(stages["prd"].after, [])
        self.assertEqual(catalog.workflows["demo"].chain, "prd → spec? → impl-api* → test")
        self.assertEqual(catalog.workflows["demo"].description, "A demo workflow.")

    def test_a_description_may_hold_colons_and_hashes(self):
        self.tree.plugin_wf("demo", workflow(description="Fix #12: a defect, with a cause: known."))
        self.assertEqual(self.tree.load().workflows["demo"].description, "Fix #12: a defect, with a cause: known.")

    def test_the_frontmatter_must_open_and_close(self):
        self.assertIn("demo.md:1: the file must start with a --- line", self.broken("name: demo\n")[0])
        self.assertIn("demo.md:1: the frontmatter has no closing --- line", self.broken("---\nname: demo\n")[0])

    def test_name_must_be_present_and_equal_the_file_name(self):
        text = workflow().replace("name: demo\n", "")
        self.assertIn("demo.md:1: no `name` line", self.broken(text)[0])
        problems = self.broken(workflow(name="other"))
        self.assertIn("demo.md:2: name 'other' must be the file name, 'demo'", problems[0])
        self.assertIn("demo.md:2: name 'Demo'", self.broken(workflow(name="Demo"))[0])

    def test_a_file_name_with_capitals_is_broken(self):
        path = self.tree.plugin_wf("Bad", workflow(name="Bad"))
        problems = self.tree.load().workflows["Bad"].errors
        self.assertIn(f"{path}: the file name must be lowercase letters, digits and -", problems)

    def test_description_is_required_and_at_most_300_characters(self):
        text = workflow().replace("description: A demo workflow.\n", "")
        self.assertIn("demo.md:1: no `description` line", self.broken(text)[0])
        problems = self.broken(workflow(description="x" * 301))
        self.assertIn("demo.md:3: description is 301 characters; the limit is 300", problems[0])
        self.tree.plugin_wf("demo", workflow(description="x" * 300))
        self.assertEqual(self.tree.load().workflows["demo"].errors, [])

    def test_unknown_and_repeated_top_level_keys(self):
        self.assertIn("demo.md:4: unknown key 'colour'; the keys are name, description, extends, stages",
                      self.broken(workflow(extra="colour: red\n"))[0])
        self.assertIn("demo.md:4: description is set twice (first on line 3)", self.broken(workflow(extra="description: again\n"))[0])
        self.assertIn("demo.md:4: expected `key: value`", self.broken(workflow(extra="just words\n"))[0])

    def test_stages_is_required_and_needs_an_item(self):
        text = "---\nname: demo\ndescription: d\n---\nbody\n"
        self.assertIn("demo.md:1: no `stages:` key", self.broken(text)[0])
        self.assertIn("demo.md:4: stages: needs at least one", self.broken("---\nname: demo\ndescription: d\nstages:\n---\nbody\n")[0])
        self.assertIn("demo.md:4: stages: put one", self.broken("---\nname: demo\ndescription: d\nstages: impl\n---\nbody\n")[0])

    def test_a_stage_must_be_a_flow_map_on_one_line(self):
        self.assertIn("demo.md:5: a stage must be a flow map on one line", self.broken(workflow(stages=("  - impl",)))[0])
        self.assertIn("demo.md:5: the stage has no closing }", self.broken(workflow(stages=("  - {id: impl,",)))[0])
        self.assertIn("demo.md:5: text after the closing }", self.broken(workflow(stages=("  - {id: impl} extra",)))[0])
        self.assertIn("demo.md:5: an indented line belongs under `stages:`",
                      self.broken(workflow(stages=("  note: x",)))[0])

    def test_each_stage_field_has_its_own_error_with_the_line(self):
        cases = {
            "{role: architect}": "demo.md:5: a stage needs an `id`",
            "{id: Impl}": "demo.md:5: id: 'Impl' must be lowercase letters, digits and -",
            "{id: impl, colour: red}": "demo.md:5: unknown stage key 'colour'",
            "{id: impl, id: test}": "demo.md:5: id is set twice",
            "{id: impl, type: nosuch}": "demo.md:5: stage 'impl' is not a stage type ('nosuch' is not in the library",
            "{id: nosuch}": "demo.md:5: stage 'nosuch' is not a stage type",
            "{id: impl, role: nobody}": "demo.md:5: role: no role named 'nobody'",
            "{id: impl, verify: unit}": "demo.md:5: verify must be one of code, schema, design-doc, not 'unit'",
            "{id: impl, approval: sometimes}": "demo.md:5: approval must be one of auto, manager, human, not 'sometimes'",
            "{id: impl, estimate: 0}": "demo.md:5: estimate: must be a number of hours above 0",
            "{id: impl, estimate: soon}": "demo.md:5: estimate: must be a number of hours above 0",
            "{id: impl, optional: yes}": "demo.md:5: optional: must be true or false, not 'yes'",
            "{id: impl, split: 1}": "demo.md:5: split: must be true or false",
            "{id: impl, decides: maybe}": "demo.md:5: decides: must be true or false",
            "{id: impl, after: spec}": "demo.md:5: after: must be a list in brackets",
            "{id: impl, after: [Spec]}": "demo.md:5: after: 'Spec' is not a stage id",
            "{id: impl, after: [a, a]}": "demo.md:5: after: lists a stage twice",
            "{id: impl, after:}": "demo.md:5: after: has no value",
            "{id: impl, role: two words}": "demo.md:5: role: must be one bare word",
            "{id: impl  type: impl}": "demo.md:5: id: must be one bare word",
        }
        for stage, expected in cases.items():
            with self.subTest(stage):
                problems = self.broken(workflow(stages=(f"  - {stage}",)))
                self.assertIn(expected, problems[0])

    def test_a_broken_role_is_refused_with_its_problem(self):
        roles = {**ROLES, "broken": "no ## Method section"}
        problems = self.broken(workflow(stages=("  - {id: impl, role: broken}",)), roles=roles)
        self.assertIn("demo.md:5: role: role broken is broken: no ## Method section", problems[0])

    def test_every_problem_of_a_file_is_listed(self):
        problems = self.broken(workflow(name="x", stages=("  - {id: impl, verify: unit}", "  - {id: test, approval: never}")))
        self.assertEqual(len(problems), 3, problems)
        self.assertEqual([p.split(":")[1] for p in problems], ["5", "6", "2"])

    def test_a_duplicate_stage_id_names_both_lines(self):
        problems = self.broken(workflow(stages=("  - {id: impl}", "  - {id: impl}")))
        self.assertIn("demo.md:6: stage id 'impl' is listed twice (first on line 5)", problems[0])

    def test_after_must_name_a_stage_of_the_workflow(self):
        problems = self.broken(workflow(stages=("  - {id: impl, after: [spec]}", "  - {id: test, after: [impl]}")))
        self.assertIn("demo.md:5: stage 'impl': after: 'spec' is not a stage of this workflow (the stages are impl, test)", problems[0])
        self.assertIn("demo.md:5: stage 'impl' comes after itself",
                      self.broken(workflow(stages=("  - {id: impl, after: [impl]}",)))[0])

    def test_a_cycle_is_named(self):
        problems = self.broken(workflow(stages=("  - {id: spec, after: [test]}", "  - {id: impl, after: [spec]}",
                                                "  - {id: test, after: [impl]}")))
        self.assertIn("demo.md:5: the stages form a cycle: spec → test → impl → spec", problems[0])

    def test_a_workflow_needs_a_required_stage(self):
        problems = self.broken(workflow(stages=("  - {id: impl, optional: true}",)))
        self.assertIn("demo.md:5: every stage is optional", problems[0])

    def test_split_is_only_for_a_code_stage(self):
        problems = self.broken(workflow(stages=("  - {id: spec, split: true}",)))
        self.assertIn("demo.md:5: stage 'spec': split is only for a stage whose verify is code, not design-doc", problems[0])

    def test_decides_is_one_root_stage_and_alone(self):
        self.assertIn("with decides: true no other stage may be listed",
                      self.broken(workflow(stages=("  - {id: spec, decides: true}", "  - {id: impl}")))[0])
        self.assertIn("decides: true is for a root stage",
                      self.broken(workflow(stages=("  - {id: impl}", "  - {id: spec, decides: true, after: [impl]}")))[0])
        self.assertIn("only one stage may set decides: true",
                      self.broken(workflow(stages=("  - {id: impl, decides: true}", "  - {id: spec, decides: true}")))[0])
        self.tree.plugin_wf("demo", workflow(stages=("  - {id: spec, decides: true, estimate: 2}",)))
        self.assertEqual(self.tree.load().workflows["demo"].errors, [])

    def test_a_body_over_600_words_warns_and_is_not_an_error(self):
        self.tree.plugin_wf("demo", workflow(body="## When to use\n" + "word " * 601))
        flow = self.tree.load().workflows["demo"]
        self.assertEqual(flow.errors, [])
        self.assertEqual(len(flow.warnings), 1)
        self.assertIn("body is 605 words", flow.warnings[0])

    def test_the_hard_rule_stage_must_exist_in_the_library_and_in_a_workflow(self):
        os.remove(os.path.join(self.tree.plugin_dir, "spec-first.md"))
        self.assertTrue(any("no workflow has a `spec` stage" in p for p in self.tree.load().problems))
        self.tree.write(self.tree.plugin_dir, "stages.toml", LIBRARY.replace("[stage.spec]", "[stage.design]"))
        self.assertTrue(any("the stage library has no `spec` type" in p for p in self.tree.load().problems))


class ParserEdgeTest(unittest.TestCase):
    """Review fixes: finite estimates, quoted values, a BOM, CRLF and tab indents, `after` order, and file:line on every error."""

    def setUp(self):
        self.tree = Tree(self)
        self.tree.plugin_wf("spec-first", workflow("spec-first", stages=("  - {id: spec}", "  - {id: impl, after: [spec]}")))

    def load(self, text, name="demo", **kw):
        path = self.tree.plugin_wf(name, text)
        catalog = self.tree.load(**kw)
        return catalog.workflows[name], path, catalog

    def test_a_non_finite_estimate_is_refused_and_does_not_crash(self):
        for value in ("inf", "-inf", "nan", "1e999"):
            with self.subTest(value):
                flow, path, _ = self.load(workflow(stages=(f"  - {{id: impl, estimate: {value}}}",)))
                self.assertIn(f"{path}:5: estimate: must be a number of hours above 0", flow.errors[0])
        self.tree.write(self.tree.plugin_dir, "stages.toml", LIBRARY.replace("estimate = 3", "estimate = inf"))
        self.assertTrue(any("estimate: must be a number of hours above 0" in p for p in self.tree.load().library.errors))

    def test_one_pair_of_quotes_is_stripped_from_every_scalar(self):
        flow, _, catalog = self.load(workflow(name='"demo"', description='"a: b"', stages=(
            '  - {id: "prd", role: "architect", after: []}', "  - {id: 'impl', after: [\"prd\"], estimate: \"2\"}")))
        self.assertEqual(catalog.problems, [])
        self.assertEqual(flow.description, "a: b")
        self.assertEqual([(s.id, s.role, s.after, s.estimate) for s in flow.stages],
                         [("prd", "architect", [], None), ("impl", "software-engineer", ["prd"], 2)])

    def test_an_empty_value_after_stripping_is_missing(self):
        flow, path, _ = self.load(workflow(description='""'))
        self.assertIn(f"{path}:1: no `description` line", flow.errors[0])
        flow, path, _ = self.load(workflow(stages=("  - {id: impl, role: ''}",)))
        self.assertIn(f"{path}:5: role: has no value", flow.errors[0])

    def test_a_bom_is_accepted_in_a_workflow_and_in_the_library(self):
        path = self.tree.plugin_wf("demo", workflow())
        with open(path, "rb") as fh:
            body = fh.read()
        with open(path, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" + body)
        lib = os.path.join(self.tree.plugin_dir, "stages.toml")
        with open(lib, "rb") as fh:
            body = fh.read()
        with open(lib, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" + body)
        self.assertEqual(self.tree.load().problems, [])

    def test_crlf_line_ends_and_tab_indents_are_accepted(self):
        text = "---\r\nname: demo\r\ndescription: A demo.\r\nstages:\r\n\t- {id: prd}\r\n\t- {id: impl, after: [prd]}\r\n---\r\n## When to use\r\nx\r\n"
        path = os.path.join(self.tree.plugin_dir, "demo.md")
        with open(path, "wb") as fh:
            fh.write(text.encode())
        catalog = self.tree.load()
        self.assertEqual(catalog.problems, [])
        self.assertEqual([s.id for s in catalog.workflows["demo"].stages], ["prd", "impl"])
        self.assertNotIn("\r", catalog.workflows["demo"].body)

    def test_after_names_earlier_stages_only(self):
        flow, path, _ = self.load(workflow(stages=("  - {id: spec, after: [impl]}", "  - {id: impl}")))
        self.assertEqual(len(flow.errors), 1)
        self.assertIn(f"{path}:5: stage 'spec': after: 'impl' is listed later", flow.errors[0])

    def test_every_parser_error_starts_with_a_file_and_a_line(self):
        bad = ["no frontmatter\n", "---\nname: demo\n", workflow(name="other"), workflow(description=""), "---\nname: demo\ndescription: d\nstages: x\n---\n",
               workflow(stages=("  - impl",)), workflow(stages=("  - {id: impl, estimate: inf}",)), workflow(stages=("  - {id: impl, after: [x]}",)),
               workflow(stages=("  - {id: a, after: [b]}", "  - {id: b}")), workflow(stages=("  - {id: impl, colour: red}",)),
               workflow(stages=("  - {id: impl}", "  - {id: impl}")), workflow(extra="colour: red\n"), workflow(stages=("  - {id: nosuch}",)),
               workflow(stages=("  - {id: impl, optional: true}",)), workflow(stages=("  - {id: spec, split: true}",)),
               workflow(stages=("  - {id: spec, decides: true}", "  - {id: impl}")), workflow(stages=("  - {id: a, after: [a]}",))]
        pattern = re.compile(re.escape(os.path.join(self.tree.plugin_dir, "demo.md")) + r":\d+: ")
        for text in bad:
            with self.subTest(text[:50]):
                flow, _, _ = self.load(text)
                self.assertTrue(flow.errors, "the file should be broken")
                for error in flow.errors:
                    self.assertRegex(error, pattern)


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tree = Tree(self)
        self.tree.plugin_wf("spec-first", workflow("spec-first", stages=("  - {id: spec}", "  - {id: impl, after: [spec]}")))

    def errors(self, project_text):
        path = self.tree.write(self.tree.project_dir, "stages.toml", project_text)
        errors = self.tree.load().library.errors
        self.assertTrue(errors)
        self.assertTrue(all(e.startswith(path) for e in errors), errors)
        return errors

    def test_a_project_table_overrides_fields_and_adds_a_type(self):
        self.tree.write(self.tree.project_dir, "stages.toml", """
            [stage.impl]
            estimate = 8
            [stage.ops]
            role = "software-engineer"
            verify = "schema"
            approval = "human"
        """)
        library = self.tree.load().library
        self.assertEqual(library.errors, [])
        self.assertEqual((library.types["impl"]["estimate"], library.types["impl"]["role"]), (8, "software-engineer"))
        self.assertEqual(library.types["ops"]["verify"], "schema")

    def test_a_toml_syntax_error_names_the_file(self):
        self.assertIn("not valid TOML", self.errors("[stage.impl\nrole = 1")[0])

    def test_a_field_error_names_the_table_the_key_and_its_line(self):
        errors = self.errors('[stage.impl]\nrole = "nobody"\nverify = "unit"\napproval = "x"\nestimate = 0\nscope = "{nope}"\ncolour = 1\n')
        text = "\n".join(errors)
        self.assertIn("stages.toml:2: [stage.impl] role: no role named 'nobody'", text)
        self.assertIn("stages.toml:3: [stage.impl] verify: must be one of code, schema, design-doc", text)
        self.assertIn("stages.toml:4: [stage.impl] approval: must be one of auto, manager, human", text)
        self.assertIn("stages.toml:5: [stage.impl] estimate: must be a number of hours above 0", text)
        self.assertIn("stages.toml:6: [stage.impl] scope: unknown placeholder {nope}", text)
        self.assertIn("stages.toml:7: [stage.impl] colour: unknown key", text)

    def test_a_new_type_needs_role_verify_and_approval(self):
        errors = self.errors('[stage.ops]\nrole = "architect"\n')
        self.assertIn("stages.toml:1: [stage.ops] no `verify`: a new type needs role, verify, approval", errors[0])
        self.assertEqual(len(errors), 2)

    def test_a_type_name_and_a_stray_key_are_checked(self):
        text = "\n".join(self.errors('colour = 1\n[stage.Bad]\nrole = "architect"\nverify = "code"\napproval = "auto"\n'))
        self.assertIn("unknown top-level key 'colour'", text)
        self.assertIn("[stage.Bad] the type name must be lowercase letters, digits and -", text)

    def test_the_plugin_library_must_be_complete(self):
        self.tree.write(self.tree.plugin_dir, "stages.toml", LIBRARY + '[stage.half]\nrole = "architect"\n')
        errors = self.tree.load().library.errors
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(all("[stage.half] no `" in e for e in errors))

    def test_a_missing_plugin_library_is_an_error(self):
        os.remove(os.path.join(self.tree.plugin_dir, "stages.toml"))
        self.assertTrue(any("the plugin's stage library is missing" in e for e in self.tree.load().library.errors))


class ExtendsTest(unittest.TestCase):
    def setUp(self):
        self.tree = Tree(self)
        self.tree.plugin_wf("base", workflow("base", stages=("  - {id: spec}", "  - {id: impl, after: [spec], estimate: 2}",
                                                             "  - {id: test, after: [impl]}")))

    def child(self, name, stages, extends=None, text=None):
        extra = f"extends: {extends or 'base'}\n"
        path = self.tree.project_wf(name, text or workflow(name, stages=stages, extra=extra))
        flow = self.tree.load().workflows[name]
        return flow, path

    def test_a_child_overrides_fields_and_appends_new_stages(self):
        flow, _ = self.child("child", ("  - {id: impl, estimate: 5, split: true}", "  - {id: ux, type: prd, after: [spec]}",
                                       "  - {id: test, after: [impl, ux]}"))
        self.assertEqual(flow.errors, [])
        stages = {s.id: s for s in flow.stages}
        self.assertEqual(list(stages), ["spec", "impl", "ux", "test"])
        self.assertEqual((stages["impl"].estimate, stages["impl"].split, stages["impl"].after), (5, True, ["spec"]))
        self.assertEqual(stages["test"].after, ["impl", "ux"])
        self.assertEqual(stages["spec"].role, "architect")
        self.assertEqual(flow.where, "project, extends plugin:base")
        self.assertEqual(flow.description, "A demo workflow.")

    def test_the_parent_is_untouched_and_a_project_file_of_the_same_name_extends_the_plugin_file(self):
        flow, _ = self.child("base", ("  - {id: impl, estimate: 9}",), extends="base")
        self.assertEqual(flow.errors, [])
        self.assertEqual([s.id for s in flow.stages], ["spec", "impl", "test"])
        self.assertEqual({s.id: s.estimate for s in flow.stages}["impl"], 9)
        self.assertEqual(flow.where, "project, extends plugin:base")

    def test_a_project_file_of_the_same_name_without_extends_replaces_the_plugin_file(self):
        self.tree.project_wf("base", workflow("base", stages=("  - {id: impl}",)))
        flow = self.tree.load().workflows["base"]
        self.assertEqual(([s.id for s in flow.stages], flow.where), (["impl"], "project, overrides plugin"))

    def test_a_child_cannot_make_a_required_stage_optional(self):
        flow, path = self.child("child", ("  - {id: impl, optional: true}",))
        self.assertEqual(len(flow.errors), 1)
        self.assertIn(f"{path}:6: stage 'impl' is required in base; a workflow that extends another cannot make a stage of it optional",
                      flow.errors[0])

    def test_a_child_may_set_optional_on_a_stage_that_is_already_optional(self):
        self.tree.plugin_wf("base", workflow("base", stages=("  - {id: spec, optional: true}", "  - {id: impl, after: [spec]}")))
        flow, _ = self.child("child", ("  - {id: spec, optional: true, estimate: 3}",))
        self.assertEqual(flow.errors, [])

    def test_a_child_cannot_remove_a_stage_by_not_listing_it(self):
        flow, _ = self.child("child", ("  - {id: ux, type: prd}",))
        self.assertIn("test", [s.id for s in flow.stages])

    def test_a_merge_that_makes_a_cycle_is_refused_in_the_child_file(self):
        flow, path = self.child("child", ("  - {id: spec, after: [test]}",))
        self.assertEqual(len(flow.errors), 1)
        self.assertIn(f"{path}:6: the stages form a cycle: spec → test → impl → spec", flow.errors[0])

    def test_a_merge_that_names_a_missing_stage_is_refused(self):
        flow, path = self.child("child", ("  - {id: test, after: [impl, nosuch]}",))
        self.assertIn(f"{path}:6: stage 'test': after: 'nosuch' is not a stage of this workflow", flow.errors[0])

    def test_a_child_cannot_change_the_type_of_an_inherited_stage(self):
        flow, path = self.child("child", ("  - {id: spec, type: impl}",))
        self.assertEqual(len(flow.errors), 1)
        self.assertIn(f"{path}:6: stage 'spec' is spec in base; a workflow that extends another cannot change the type", flow.errors[0])
        flow, _ = self.child("child", ("  - {id: spec, type: spec, estimate: 3}",))
        self.assertEqual(flow.errors, [])

    def test_a_child_after_must_keep_the_parent_edges(self):
        flow, path = self.child("child", ("  - {id: impl, after: []}",))
        self.assertIn(f"{path}:6: stage 'impl': after: must keep the stages that base lists (spec missing)", flow.errors[0])
        flow, _ = self.child("child", ("  - {id: ux, type: prd}", "  - {id: impl, after: [spec, ux]}"))
        self.assertEqual(flow.errors, [])
        self.assertEqual([s.id for s in flow.stages], ["spec", "ux", "impl", "test"])

    def test_the_decides_error_of_a_child_points_at_the_line_that_added_the_stage(self):
        self.tree.plugin_wf("base", workflow("base", stages=("  - {id: spec, decides: true}",)))
        flow, path = self.child("child", ("  - {id: impl}",))
        self.assertIn(f"{path}:6: stage 'impl': with decides: true no other stage may be listed", flow.errors[0])

    def test_extends_needs_an_existing_workflow(self):
        flow, path = self.child("child", ("  - {id: impl}",), extends="nosuch")
        self.assertIn(f"{path}:4: extends: no workflow named 'nosuch' to extend; available workflows: base, child", flow.errors[0])

    def test_extends_is_one_level_only(self):
        self.child("mid", ("  - {id: impl}",))
        flow, path = self.child("grand", ("  - {id: impl}",), extends="mid")
        self.assertIn(f"{path}:4: extends: the parent workflow mid extends base itself; a workflow extends one level only", flow.errors[0])

    def test_a_plugin_workflow_cannot_extend(self):
        self.tree.plugin_wf("odd", workflow("odd", extra="extends: base\n"))
        flow = self.tree.load().workflows["odd"]
        self.assertIn("odd.md:4: extends: only a project workflow can extend another workflow", flow.errors[0])

    def test_a_broken_parent_is_named(self):
        self.tree.plugin_wf("base", workflow("base", stages=("  - {id: nosuch}",)))
        flow, _ = self.child("child", ("  - {id: impl}",))
        self.assertIn("base.md:5: stage 'nosuch' is not a stage type", flow.errors[0])
        self.tree.plugin_wf("base", "no frontmatter\n")
        flow, path = self.child("child", ("  - {id: impl}",))
        self.assertIn(f"{path}:4: extends: the parent workflow file", flow.errors[0])
        self.assertIn("base.md:1: the file must start with a ---", flow.errors[0])

    def test_a_bad_extends_value_is_refused(self):
        flow, path = self.child("child", ("  - {id: impl}",), extends="Not A Name")
        self.assertIn(f"{path}:4: extends: 'Not A Name' is not a workflow name", flow.errors[0])


class PromptTest(unittest.TestCase):
    def setUp(self):
        self.tree = Tree(self)
        for name in ("alpha", "beta", "gamma", "delta", "spec-first"):
            self.tree.plugin_wf(name, workflow(name, description=f"Description of {name}.",
                                               stages=("  - {id: spec}", "  - {id: impl, after: [spec]}")))
        self.catalog = self.tree.load()
        self.assertEqual(self.catalog.problems, [])

    def test_the_order_is_fixed_by_the_seed_and_unsure_is_among_the_options(self):
        first, order = wf.pick_prompt(self.catalog, 7, "Add a limit", "Notes line", "src/limits")
        again, order_again = wf.pick_prompt(self.catalog, 7, "Add a limit", "Notes line", "src/limits")
        self.assertEqual((first, order), (again, order_again))
        self.assertEqual(sorted(order), ["alpha", "beta", "delta", "gamma", "spec-first", "unsure"])
        orders = {tuple(wf.pick_prompt(self.catalog, seed, "t")[1]) for seed in range(20)}
        self.assertGreater(len(orders), 1)
        self.assertGreater(len({o.index("unsure") for o in orders}), 1)

    def test_the_prompt_holds_the_task_the_descriptions_and_the_answer_format(self):
        text, order = wf.pick_prompt(self.catalog, 3, "Add a limit", "Line one\nRefs #12", "src/limits")
        self.assertIn("Task: Add a limit\nNotes:\nLine one\nRefs #12\nScope: src/limits\n", text)
        for letter, name in zip("ABCDEF", order):
            expected = wf.UNSURE_TEXT if name == "unsure" else f"Description of {name}."
            self.assertIn(f"\n{letter}. {name}: {expected}\n", text)
        self.assertTrue(text.endswith("PICK: <name|unsure>\nWHY: <one line>\n"))

    def test_empty_notes_and_scope_are_left_out(self):
        text, _ = wf.pick_prompt(self.catalog, 0, "Only a title")
        self.assertNotIn("Notes:", text)
        self.assertNotIn("Scope:", text)


class CommandTest(unittest.TestCase):
    """`run.py workflows` and `config.py check` in a temporary repository, with the shipped workflows."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.realpath(tmp.name)
        self.root = os.path.join(self.dir, "repo")
        self.home = os.path.join(self.dir, "home")
        os.makedirs(self.root)
        os.makedirs(self.home)
        for args in (["init", "-q", "-b", "main"], ["config", "user.name", "t"], ["config", "user.email", "t@example.com"],
                     ["commit", "-q", "--allow-empty", "-m", "base", "--no-gpg-sign"]):
            subprocess.run(["git", "-C", self.root, *args], check=True, capture_output=True)
        self.config('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n')
        self.env = {**os.environ, "HOME": self.home, "CLAUDE_CONFIG_DIR": os.path.join(self.home, "claude")}
        self.project_dir = os.path.join(self.root, ".claude", "agentic-team", "workflows")

    def config(self, text):
        with open(os.path.join(self.root, ".agentic-team.toml"), "w") as fh:
            fh.write(text)

    def project_file(self, name, text, folder=None):
        folder = folder or self.project_dir
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(dedent(text))
        return path

    def run_py(self, *args, pre=()):
        return subprocess.run([sys.executable, RUN, "--root", self.root, "--tg", RUN, *pre, *args], capture_output=True, text=True,
                              cwd=self.dir, env=self.env)

    def check_py(self):
        return subprocess.run([sys.executable, CONFIG, "--root", self.root, "check"], capture_output=True, text=True,
                              cwd=self.dir, env=self.env)

    def test_the_list_shows_every_shipped_workflow_with_its_stages(self):
        out = self.run_py("workflows")
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = out.stdout.splitlines()
        self.assertEqual(len(lines), 5, out.stdout)
        self.assertTrue(all(line.startswith("workflow: ") for line in lines))
        text = out.stdout
        self.assertIn("workflow: change (plugin); A change to existing behaviour", text)
        self.assertIn("stages: prd → impl → test", text)
        self.assertIn("workflow: feature (plugin); New user-visible behaviour", text)
        self.assertIn("stages: prd → ux? → spec → impl* → test", text)
        self.assertIn("stages: spec? → impl → test", text)
        self.assertIn("stages: impl → test", text)
        self.assertIn("stages: investigate", text)

    def test_json_lists_the_resolved_stages(self):
        out = self.run_py("workflows", pre=["--json"])
        self.assertEqual(out.returncode, 0, out.stderr)
        rows = {r["name"]: r for r in json.loads(out.stdout)}
        self.assertEqual(sorted(rows), ["change", "feature", "figure-it-out", "fix", "hotfix"])
        stages = {s["id"]: s for s in rows["feature"]["stages"]}
        self.assertEqual((stages["impl"]["role"], stages["impl"]["verify"], stages["impl"]["split"], stages["impl"]["after"]),
                         ("software-engineer", "code", True, ["spec"]))
        self.assertEqual((stages["ux"]["optional"], stages["spec"]["after"]), (True, ["prd", "ux"]))
        self.assertTrue(rows["figure-it-out"]["stages"][0]["decides"])
        self.assertEqual(rows["fix"]["errors"], [])

    def test_a_project_file_is_listed_with_its_source(self):
        self.project_file("mine.md", workflow("mine", stages=("  - {id: impl}",)))
        self.project_file("hotfix.md", workflow("hotfix", extra="extends: hotfix\n", stages=("  - {id: impl, estimate: 6}",)))
        self.project_file("change.md", workflow("change", stages=("  - {id: impl}",)))
        rows = {r["name"]: r for r in json.loads(self.run_py("workflows", pre=["--json"]).stdout)}
        self.assertEqual({n: r["source"] for n, r in rows.items() if n in ("mine", "hotfix", "change")},
                         {"mine": "project", "hotfix": "project, extends plugin:hotfix", "change": "project, overrides plugin"})
        self.assertEqual([s["id"] for s in rows["hotfix"]["stages"]], ["impl", "test"])

    def test_a_broken_file_is_named_with_its_line_and_the_command_exits_1(self):
        path = self.project_file("broken.md", workflow("broken", stages=("  - {id: impl, after: [nosuch]}",)))
        out = self.run_py("workflows")
        self.assertEqual(out.returncode, 1)
        self.assertIn(f"workflow-broken: broken (project): {path}:5: stage 'impl': after: 'nosuch' is not a stage", out.stdout)
        self.assertIn("workflow: hotfix (plugin)", out.stdout)  # the good ones are still listed
        self.assertIn("1 workflow problem; fix it before a workflow runs", out.stderr)

    def test_a_broken_stage_library_exits_1(self):
        path = self.project_file("stages.toml", '[stage.impl]\nverify = "unit"\n')
        out = self.run_py("workflows")
        self.assertEqual(out.returncode, 1)
        self.assertIn(f"{path}:2: [stage.impl] verify: must be one of", out.stdout)

    def test_check_prints_only_problems_and_exits_non_zero_on_one(self):
        out = self.run_py("workflows", "--check")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "workflows-checked: 5 workflows and 6 stage types: ok"))
        path = self.project_file("broken.md", "no frontmatter\n")
        out = self.run_py("workflows", "--check")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stdout.splitlines(), [f"workflow-broken: broken (project): {path}:1: the file must start with a --- line "
                                                   "that opens the frontmatter"])

    def test_a_role_that_is_broken_makes_the_workflow_that_uses_it_broken(self):
        self.project_file("architect.md", "---\nnothing: here\n---\n", folder=os.path.join(self.root, ".claude", "agentic-team", "roles"))
        out = self.run_py("workflows", "--check")
        self.assertEqual(out.returncode, 1)
        self.assertIn("role architect is broken", out.stdout)

    def test_a_long_body_warns_and_still_lists_the_workflow(self):
        self.project_file("wordy.md", workflow("wordy", body="## When to use\n" + "word " * 650))
        out = self.run_py("workflows")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("warn: workflow wordy", out.stdout)
        self.assertIn("workflow: wordy (project)", out.stdout)

    def test_the_pick_prompt_is_printed_for_a_seed_and_changes_with_it(self):
        notes = os.path.join(self.dir, "notes.txt")
        with open(notes, "w") as fh:
            fh.write("Users can export a report.\nIssue #31\n")
        args = ["workflows", "--pick-prompt", "--title", "Export a report", "--notes-file", notes, "--scope", "apps/api/export"]
        first = self.run_py(*args, "--seed", "1")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("Task: Export a report\nNotes:\nUsers can export a report.\nIssue #31\nScope: apps/api/export\n", first.stdout)
        self.assertIn("A. ", first.stdout)
        self.assertIn(": none of the workflows fits", first.stdout)
        self.assertTrue(first.stdout.endswith("PICK: <name|unsure>\nWHY: <one line>\n"))
        self.assertEqual(self.run_py(*args, "--seed", "1").stdout, first.stdout)
        self.assertTrue(any(self.run_py(*args, "--seed", str(n)).stdout != first.stdout for n in range(2, 6)))
        as_json = json.loads(self.run_py(*args, "--seed", "1", pre=["--json"]).stdout)
        self.assertEqual((as_json["seed"], as_json["prompt"]), (1, first.stdout))
        self.assertEqual(sorted(as_json["options"]), ["change", "feature", "figure-it-out", "fix", "hotfix", "unsure"])

    def test_the_pick_prompt_leaves_a_broken_workflow_out_with_a_warning(self):
        path = self.project_file("broken.md", "no frontmatter\n")
        out = self.run_py("workflows", "--pick-prompt", "--seed", "1", "--title", "x")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"warn: workflow broken is left out of the prompt: {path}:1:", out.stderr)
        self.assertNotIn("broken", out.stdout)
        self.assertIn("hotfix", out.stdout)
        as_json = json.loads(self.run_py("workflows", "--pick-prompt", "--seed", "1", "--title", "x", pre=["--json"]).stdout)
        self.assertEqual(len(as_json["warnings"]), 1)
        self.assertNotIn("broken", as_json["options"])

    def test_the_pick_prompt_refuses_a_broken_stage_library_and_needs_a_seed(self):
        out = self.run_py("workflows", "--pick-prompt", "--title", "x")
        self.assertEqual(out.returncode, 2)
        self.assertIn("--pick-prompt needs --seed", out.stderr)
        self.project_file("stages.toml", '[stage.impl]\nverify = "unit"\n')
        out = self.run_py("workflows", "--pick-prompt", "--seed", "1", "--title", "x")
        self.assertEqual(out.returncode, 1)
        self.assertIn("fix the stage library first", out.stderr)

    def test_the_pick_prompt_refuses_an_unreadable_notes_file(self):
        out = self.run_py("workflows", "--pick-prompt", "--seed", "1", "--title", "x", "--notes-file", os.path.join(self.dir, "missing.txt"))
        self.assertEqual(out.returncode, 2)
        self.assertIn("cannot read --notes-file", out.stderr)

    def test_config_check_ignores_workflows_until_they_are_configured(self):
        self.project_file("broken.md", "no frontmatter\n", folder=os.path.join(self.root, "elsewhere"))
        self.assertEqual(self.check_py().stdout, "ok\n")
        self.config('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n[workflow_policy]\nenabled = false\n')
        self.assertEqual(self.check_py().stdout, "ok\n")

    def test_config_check_validates_workflows_when_enabled_or_when_the_project_has_files(self):
        self.config('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n[workflow_policy]\nenabled = true\n')
        out = self.check_py()
        self.assertEqual((out.returncode, out.stdout), (0, "ok\n"), out.stderr)
        path = self.project_file("broken.md", workflow("broken", stages=("  - {id: impl, after: [nosuch]}",)))
        out = self.check_py()
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"{path}:5: stage 'impl': after: 'nosuch' is not a stage", out.stdout)
        self.config('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n')  # a project file alone is enough
        self.assertEqual(self.check_py().returncode, 2)
        os.remove(path)
        self.assertEqual(self.check_py().stdout, "ok\n")

    def test_config_check_rejects_a_bad_policy_value(self):
        self.config('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n[workflow_policy]\nenabled = "yes"\n')
        out = self.check_py()
        self.assertEqual(out.returncode, 2)
        self.assertIn("workflow_policy.enabled must be true or false", out.stdout)


class ShippedTest(unittest.TestCase):
    """The workflows and the stage library that ship in templates/workflows/."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        shipped = {n[:-3]: None for n in os.listdir(os.path.join(PLUGIN, "templates", "roles")) if n.endswith(".md")}
        self.catalog = wf.load(PLUGIN, tmp.name, shipped)

    def test_every_shipped_file_passes_the_check(self):
        self.assertEqual(self.catalog.problems, [])
        self.assertEqual(self.catalog.library.errors, [])
        folder = os.path.join(PLUGIN, "templates", "workflows")
        shipped = sorted(n[:-3] for n in os.listdir(folder) if n.endswith(".md"))
        self.assertEqual(sorted(self.catalog.workflows), shipped)
        for name in ("hotfix", "fix", "change", "feature", "figure-it-out"):
            self.assertIn(name, shipped)

    def test_every_shipped_workflow_has_the_body_sections_and_stays_short(self):
        for name, flow in self.catalog.workflows.items():
            with self.subTest(name):
                self.assertIn("## When to use", flow.body)
                self.assertIn("## Steps", flow.body)
                self.assertLessEqual(flow.words, wf.BODY_WORDS_MAX)
                self.assertEqual(flow.warnings, [])
                self.assertLessEqual(len(flow.description), wf.DESCRIPTION_MAX)

    def test_the_stages_of_the_shipped_workflows(self):
        chains = {name: flow.chain for name, flow in self.catalog.workflows.items()}
        self.assertEqual(chains, {
            "hotfix": "impl → test",
            "fix": "spec? → impl → test",
            "change": "prd → impl → test",
            "feature": "prd → ux? → spec → impl* → test",
            "figure-it-out": "investigate",
        })

    def test_the_library_has_the_six_types_with_the_spec_values(self):
        types = self.catalog.library.types
        self.assertEqual(sorted(types), ["impl", "investigate", "prd", "spec", "test", "ux"])
        for kind, role in (("investigate", "architect"), ("prd", "product-manager"), ("ux", "ux-designer"), ("spec", "architect")):
            self.assertEqual((types[kind]["role"], types[kind]["verify"], types[kind]["approval"]), (role, "design-doc", "manager"))
        for kind in ("impl", "test"):
            self.assertEqual((types[kind]["role"], types[kind]["verify"], types[kind]["approval"], types[kind]["scope"]),
                             ("software-engineer", "code", "auto", "instance"))
        self.assertTrue(types["spec"]["acceptance"])


if __name__ == "__main__":
    unittest.main()
