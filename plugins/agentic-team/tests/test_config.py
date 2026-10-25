"""Tests for scripts/config.py. Run: python3 -m unittest discover plugins/agentic-team/tests"""

import contextlib
import io
import json
import os
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import config  # noqa: E402

MINIMAL = 'taskgraph.project = "demo"\n'


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, text, local=False):
        name = config.LOCAL if local else config.TRACKED
        with open(os.path.join(self.root, name), "w") as fh:
            fh.write(textwrap.dedent(text))

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                config.main(["--root", self.root, *args])
            except SystemExit as exc:
                code = exc.code or 0
        return code, out.getvalue(), err.getvalue()

    def test_defaults_from_minimal_file(self):
        self.write(MINIMAL)
        cfg = config.load(self.root)
        self.assertEqual(config.problems(cfg), [])
        self.assertEqual(cfg["taskgraph"], {"project": "demo", "plan": ""})
        self.assertEqual(cfg["sessions"]["max_parallel"], 4)
        self.assertEqual(cfg["sessions"]["permission_mode"], "auto")
        self.assertIs(cfg["sessions"]["launch_outside_sandbox"], False)
        self.assertTrue(cfg["sessions"]["timezone"])
        self.assertTrue(os.path.isabs(cfg["sessions"]["brief_template"]))
        self.assertTrue(cfg["sessions"]["brief_template"].endswith("templates/task-brief.md"))
        self.assertEqual(cfg["models"]["mechanical"], {"model": "haiku", "effort": None})
        self.assertEqual(cfg["models"]["implementation"], {"model": "sonnet", "effort": "high"})
        self.assertIsNone(cfg["models"]["verifier"])
        self.assertEqual(cfg["constraints"]["other"], [])
        self.assertEqual(self.run_cli("check")[:2], (0, "ok\n"))

    def test_template_needs_filling(self):
        with open(os.path.join(config.PLUGIN_ROOT, "templates", "agentic-team.toml")) as fh:
            self.write(fh.read())
        found = config.problems(config.load(self.root))
        self.assertEqual(len(found), 5, found)
        self.assertTrue(all("is TODO" in p for p in found))

    def test_local_overrides_scalar_table_and_list(self):
        self.write("""\
            [taskgraph]
            project = "demo"
            [sessions]
            max_parallel = 2
            permission_mode = "acceptEdits"
            [models]
            implementation = { model = "sonnet", effort = "high" }
            [constraints]
            other = ["a", "b"]
        """)
        self.write("""\
            [sessions]
            max_parallel = 6
            [models.implementation]
            effort = "low"
            [constraints]
            other = ["c"]
        """, local=True)
        cfg = config.load(self.root)
        self.assertEqual(config.problems(cfg), [])
        self.assertEqual(cfg["sessions"]["max_parallel"], 6)
        self.assertEqual(cfg["sessions"]["permission_mode"], "acceptEdits")
        self.assertEqual(cfg["models"]["implementation"], {"model": "sonnet", "effort": "low"})
        self.assertEqual(cfg["constraints"]["other"], ["c"])

    def test_todo_detected(self):
        self.write("""\
            taskgraph.project = "demo"
            constraints.do_not_send = "TODO"
            serialization.rules = ["TODO"]
        """)
        found = config.problems(config.load(self.root))
        self.assertEqual(len(found), 2, found)
        self.assertIn("constraints.do_not_send is TODO", found[0])
        self.assertIn("serialization.rules is TODO", found[1])
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertIn("do_not_send", out)

    def test_empty_project(self):
        self.write('taskgraph.project = ""\n')
        self.assertIn("taskgraph.project is empty", " ".join(config.problems(config.load(self.root))))

    def test_missing_file(self):
        found = config.problems(config.load(self.root))
        self.assertIn("/agentic-team:setup", found[0])

    def test_unknown_key_with_suggestion(self):
        self.write(MINIMAL + "sessions.max_paralel = 3\n[sesions]\n")
        self.write("models.judgment = \"opus\"\n", local=True)
        found = config.problems(config.load(self.root))
        self.assertEqual(len(found), 3, found)
        self.assertIn("unknown key sessions.max_paralel (did you mean sessions.max_parallel?)", found[0])
        self.assertIn("unknown section [sesions] (did you mean sessions?)", found[1])
        self.assertTrue(found[2].startswith(config.LOCAL))
        self.assertIn("did you mean models.judgement?", found[2])

    def test_wrong_types(self):
        self.write(MINIMAL + """\
            sessions.max_parallel = 0
            sessions.launch_outside_sandbox = "yes"
            sessions.timezone = "Mars/Olympus"
            consultants.sessions = "alpha"
            models.judgement = { effort = "high" }
        """)
        found = "\n".join(config.problems(config.load(self.root)))
        self.assertIn("sessions.max_parallel must be a positive integer", found)
        self.assertIn("sessions.launch_outside_sandbox must be true or false", found)
        self.assertIn("not an IANA time zone", found)
        self.assertIn("consultants.sessions must be a list of strings", found)
        self.assertIn("models.judgement must be a model id", found)

    def test_toml_syntax_error(self):
        self.write(MINIMAL + "sessions.max_parallel = \n")
        found = config.problems(config.load(self.root))
        self.assertEqual(len(found), 2, found)  # syntax error, then empty project
        self.assertIn("TOML syntax error", found[0])
        self.assertIn("line 2", found[0])

    def test_model_resolution(self):
        self.write(MINIMAL + """\
            [models]
            judgement = "opus-x"
            [models.overrides]
            "Data Migration" = { model = "opus", effort = "high" }
        """)
        cfg = config.load(self.root)
        self.assertEqual(config.resolve_model(cfg, "data migration"), {"model": "opus", "effort": "high"})
        self.assertEqual(config.resolve_model(cfg, "judgement"), {"model": "opus-x", "effort": None})
        self.assertEqual(config.resolve_model(cfg, "verifier"), {"model": None, "effort": None})
        with self.assertRaises(config.ConfigError):
            config.resolve_model(cfg, "poetry")
        code, out, _ = self.run_cli("model", "verifier")
        self.assertEqual((code, json.loads(out)), (0, {"model": None, "effort": None}))

    def test_get(self):
        self.write(MINIMAL + 'consultants.sessions = ["alpha"]\n')
        self.assertEqual(self.run_cli("get", "taskgraph.project")[:2], (0, "demo\n"))
        self.assertEqual(self.run_cli("get", "consultants.sessions")[:2], (0, '["alpha"]\n'))
        self.assertEqual(self.run_cli("get", "sessions.launch_outside_sandbox")[:2], (0, "false\n"))
        self.assertEqual(self.run_cli("get", "taskgraph.project", "--json")[:2], (0, '"demo"\n'))
        code, _, err = self.run_cli("get", "taskgraph.projet")
        self.assertEqual(code, 2)
        self.assertIn("did you mean taskgraph.project?", err)

    def test_relative_brief_template(self):
        os.makedirs(os.path.join(self.root, "t"))
        open(os.path.join(self.root, "t", "brief.md"), "w").close()
        self.write(MINIMAL + 'sessions.brief_template = "t/brief.md"\n')
        cfg = config.load(self.root)
        self.assertEqual(config.problems(cfg), [])
        self.assertEqual(cfg["sessions"]["brief_template"],
                         os.path.join(os.path.abspath(self.root), "t", "brief.md"))


if __name__ == "__main__":
    unittest.main()
