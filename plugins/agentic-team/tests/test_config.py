"""Tests for scripts/config.py. Run: "$PY" plugins/agentic-team/tests/run_parallel.py (all tests, in parallel)"""

import contextlib
import io
import json
import os
import sys
import tempfile
import textwrap
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import config  # noqa: E402

MINIMAL = 'taskgraph.project = "demo"\n'


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.user = os.path.join(self.root, "user-claude")  # the user settings that `check` reads: never the real ones
        os.makedirs(self.user)
        self._env = unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.user})
        self._env.start()

    def tearDown(self):
        self._env.stop()
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
        self.assertEqual(cfg["taskgraph"], {"project": "demo"})
        self.assertEqual(cfg["sessions"]["max_parallel"], 2)
        self.assertEqual(cfg["sessions"]["permission_mode"], "auto")
        self.assertEqual(set(cfg["sessions"]),
                         {"max_parallel", "permission_mode", "timezone", "timezone_label"})
        self.assertTrue(cfg["sessions"]["timezone"])
        self.assertEqual(cfg["models"]["mechanical"], {"model": "haiku", "effort": None})
        self.assertEqual(cfg["models"]["implementation"], {"model": "sonnet", "effort": "high"})
        self.assertIsNone(cfg["models"]["verifier"])
        self.assertEqual(cfg["constraints"]["forbidden"], [])
        self.assertEqual(cfg["merge"], {"mode": "local", "host": "auto", "remote": "origin", "base": "", "method": "merge",
                                       "catch_up": "host", "draft": False, "remove_worktrees": True, "disposable": []})
        self.assertEqual(set(cfg["merge"]), {"mode", "host", "remote", "base", "method", "catch_up", "draft",
                                             "remove_worktrees", "disposable"})
        self.assertEqual(cfg["verify"], {"kind": "code"})
        self.assertEqual(self.run_cli("check")[:2], (0, "ok\n"))

    def test_template_needs_filling(self):
        with open(os.path.join(config.PLUGIN_ROOT, "templates", "agentic-team.toml")) as fh:
            self.write(fh.read())
        found = config.problems(config.load(self.root))
        self.assertEqual(len(found), 2, found)
        self.assertTrue(all("is TODO" in p for p in found))
        self.assertIn("taskgraph.project", found[0])
        self.assertIn("constraints.forbidden", found[1])

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
            forbidden = ["a", "b"]
        """)
        self.write("""\
            [sessions]
            max_parallel = 6
            [models.implementation]
            effort = "low"
            [constraints]
            forbidden = ["c"]
        """, local=True)
        cfg = config.load(self.root)
        self.assertEqual(config.problems(cfg), [])
        self.assertEqual(cfg["sessions"]["max_parallel"], 6)
        self.assertEqual(cfg["sessions"]["permission_mode"], "acceptEdits")
        self.assertEqual(cfg["models"]["implementation"], {"model": "sonnet", "effort": "low"})
        self.assertEqual(cfg["constraints"]["forbidden"], ["c"])

    def test_todo_detected(self):
        self.write("""\
            taskgraph.project = "demo"
            constraints.forbidden = ["TODO"]
        """)
        found = config.problems(config.load(self.root))
        self.assertEqual(len(found), 1, found)
        self.assertIn("constraints.forbidden is TODO", found[0])
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertIn("forbidden", out)

    def test_empty_project(self):
        self.write('taskgraph.project = ""\n')
        self.assertIn("taskgraph.project is empty", " ".join(config.problems(config.load(self.root))))

    def test_missing_file(self):
        found = config.problems(config.load(self.root))
        self.assertIn("/agentic-team:setup", found[0])

    def test_missing_file_is_one_line(self):
        loaded = config.load(self.root)
        self.assertTrue(loaded.missing)
        found = config.problems(loaded)
        self.assertEqual(len(found), 1, found)
        self.assertIn("run /agentic-team:setup, or pass --root <repository root>", found[0])
        self.assertNotIn("taskgraph.project", found[0])
        code, out, _ = self.run_cli("check")
        self.assertEqual((code, out), (2, found[0] + "\n"))
        self.write(MINIMAL)
        self.assertFalse(config.load(self.root).missing)
        self.assertEqual(config.problems(config.load(self.root)), [])

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
            sessions.timezone = "Mars/Olympus"
            constraints.forbidden = "x"
            models.judgement = { effort = "high" }
            merge.mode = "PR"
            merge.method = 3
            verify.kind = "prose"
        """)
        found = "\n".join(config.problems(config.load(self.root)))
        self.assertIn("sessions.max_parallel must be a positive integer", found)
        self.assertIn("not an IANA time zone", found)
        self.assertIn("constraints.forbidden must be a list of strings", found)
        self.assertIn("models.judgement must be a model id", found)
        self.assertIn('merge.mode must be one of "local", "pr", not "PR"', found)
        self.assertIn('merge.method must be one of "merge", "squash", "rebase", not 3', found)
        self.assertIn('verify.kind must be one of "code", "schema", "design-doc", not "prose"', found)

    def test_64_merge_section(self):
        self.write(MINIMAL + '[merge]\nmode = "pr"\nhost = "gitlab"\nremote = "upstream"\nmethod = "squash"\nmethd = 1\n')
        found = config.problems(config.load(self.root))
        self.assertEqual(len(found), 1, found)
        self.assertIn("unknown key merge.methd (did you mean merge.method?)", found[0])
        self.assertEqual(self.run_cli("get", "merge.host")[:2], (2, ""))
        self.write(MINIMAL + '[merge]\nmode = "pr"\nhost = "gitlab"\nremote = "upstream"\nmethod = "squash"\n')
        self.assertEqual(self.run_cli("get", "merge.host")[:2], (0, "gitlab\n"))
        self.write(MINIMAL + '[merge]\nremote = " "\n')
        self.assertIn("merge.remote must be a non-empty string", " ".join(config.problems(config.load(self.root))))

    def test_remove_worktrees_must_be_a_boolean(self):
        self.write(MINIMAL + "[merge]\nremove_worktrees = false\n")
        self.assertEqual(config.problems(config.load(self.root)), [])
        self.assertEqual(self.run_cli("get", "merge.remove_worktrees")[:2], (0, "false\n"))
        for bad in ('"no"', "0", "[]"):
            self.write(MINIMAL + f"[merge]\nremove_worktrees = {bad}\n")
            found = config.problems(config.load(self.root))
            self.assertEqual(found, [f"merge.remove_worktrees must be true or false, not {bad}"])
            self.assertEqual(self.run_cli("check")[0], 2)

    def test_disposable_is_a_list_of_patterns(self):
        self.write(MINIMAL + '[merge]\ndisposable = ["infra/.data/", "*.sqlite", "!build/"]\n')
        self.assertEqual(config.problems(config.load(self.root)), [])
        self.assertEqual(self.run_cli("get", "merge.disposable")[:2], (0, '["infra/.data/", "*.sqlite", "!build/"]\n'))
        self.write(MINIMAL + '[merge]\ndisposable = ["", "/", "**", " x", "!", "!logs/"]\n')
        usable = 'is not a usable pattern; name files or folders, for example "*.sqlite-journal" or "generated/"'
        self.assertEqual(config.problems(config.load(self.root)), [
            f'merge.disposable: "" {usable}',
            f'merge.disposable: "/" {usable}',
            f'merge.disposable: "**" {usable}',
            f'merge.disposable: " x" {usable}',
            f'merge.disposable: "!" {usable}',
            'merge.disposable: "!logs/" turns off nothing: "logs/" is not a default pattern'])
        self.assertEqual(self.run_cli("check")[0], 2)
        self.write(MINIMAL + '[merge]\ndisposable = "node_modules/"\n')
        self.assertEqual(config.problems(config.load(self.root)),
                         ['merge.disposable must be a list of path patterns, not "node_modules/"'])
        self.write(MINIMAL + '[merge]\ndisposable = ["TODO"]\n')
        self.assertEqual(config.problems(config.load(self.root)),
                         ['merge.disposable is TODO; set it, or "" / [] if it does not apply'])
        self.assertEqual(len(config.DISPOSABLE_DEFAULT), 36)
        for pattern in config.DISPOSABLE_DEFAULT:
            self.assertEqual(config.pattern_problems("x", [pattern, "!" + pattern]), [], pattern)

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
        self.write(MINIMAL + 'constraints.forbidden = ["alpha"]\n')
        self.assertEqual(self.run_cli("get", "taskgraph.project")[:2], (0, "demo\n"))
        self.assertEqual(self.run_cli("get", "constraints.forbidden")[:2], (0, '["alpha"]\n'))
        self.assertEqual(self.run_cli("get", "sessions.max_parallel")[:2], (0, "2\n"))
        self.assertEqual(self.run_cli("get", "taskgraph.project", "--json")[:2], (0, '"demo"\n'))
        code, _, err = self.run_cli("get", "taskgraph.projet")
        self.assertEqual(code, 2)
        self.assertIn("did you mean taskgraph.project?", err)

    def test_a_tier_may_name_a_profile_or_a_list_and_nothing_else_changes(self):
        api = os.path.join(self.root, "api")
        os.makedirs(api)
        self.write(MINIMAL + f"""\
            [profiles]
            api = {json.dumps(api)}
            [models]
            mechanical = {{ model = "haiku", profile = "api" }}
            implementation = {{ model = "sonnet", effort = "high", profile = ["default", "api"] }}
            judgement = "opus"
            [models.overrides]
            "data migration" = {{ model = "opus", profile = "api" }}
        """)
        cfg = config.load(self.root)
        self.assertEqual(config.problems(cfg), [])
        self.assertEqual(config.resolve_model(cfg, "mechanical"), {"model": "haiku", "effort": None, "profile": "api"})
        self.assertEqual(config.resolve_model(cfg, "implementation")["profile"], ["default", "api"])
        self.assertEqual(config.resolve_model(cfg, "judgement"), {"model": "opus", "effort": None})
        self.assertEqual(config.resolve_model(cfg, "data migration")["profile"], "api")
        self.assertEqual(config.profile_path(cfg, "api"), api)
        self.assertIsNone(config.profile_path(cfg, "default"))
        self.assertIsNone(config.profile_path(cfg, None))
        self.assertEqual(self.run_cli("get", "profiles.api")[:2], (0, api + "\n"))
        self.assertIn(f"[profiles]\napi = {json.dumps(api)}", self.run_cli("show")[1])
        self.write(MINIMAL)
        cfg = config.load(self.root)
        self.assertNotIn("profiles", cfg)
        self.assertNotIn("[profiles]", self.run_cli("show")[1])
        self.assertNotIn("profile", self.run_cli("show", "--json")[1])

    def test_profile_problems(self):
        api = os.path.join(self.root, "api")
        os.makedirs(api)
        self.write(MINIMAL + f"""\
            [profiles]
            api = {json.dumps(api)}
            gone = {json.dumps(os.path.join(self.root, "missing"))}
            default = {json.dumps(api)}
            [models]
            mechanical = {{ model = "haiku", profile = "apii" }}
            implementation = {{ model = "sonnet", profile = ["default", "nope"] }}
            judgement = {{ model = "opus", profile = "default" }}
            [models.overrides]
            "data migration" = {{ model = "opus", profile = "other" }}
        """)
        found = config.problems(config.load(self.root))
        self.assertEqual(len(found), 5, found)
        self.assertIn("profiles.gone: directory", found[0])
        self.assertIn("does not exist", found[0])
        self.assertIn("profiles.default", found[1])
        self.assertIn("reserved", found[1])
        self.assertIn("models.mechanical uses profile 'apii', which [profiles] does not define (did you mean api?)", found[2])
        self.assertIn("models.implementation uses profile 'nope'", found[3])
        self.assertIn("models.overrides.data migration uses profile 'other'", found[4])
        self.assertEqual(self.run_cli("check")[0], 2)
        self.write(MINIMAL + '[models]\njudgement = { model = "opus", profile = "api" }\n')
        found = config.problems(config.load(self.root))
        self.assertEqual(len(found), 1, found)
        self.assertIn('add api = "<CLAUDE_CONFIG_DIR>" under [profiles]', found[0])
        self.write(MINIMAL + '[models]\njudgement = { model = "opus", profile = [] }\n')
        self.assertIn("models.judgement must be a model id", " ".join(config.problems(config.load(self.root))))
        self.write(MINIMAL + '[profiles]\napi = 3\n')
        self.assertIn("profiles.api must be the CLAUDE_CONFIG_DIR", " ".join(config.problems(config.load(self.root))))
        self.write(MINIMAL + 'profiles = 3\n')
        self.assertIn("profiles must be a table", " ".join(config.problems(config.load(self.root))))

    def test_local_file_may_define_profiles_for_tiers_in_the_tracked_file(self):
        api = os.path.join(self.root, "api")
        os.makedirs(api)
        self.write(MINIMAL + '[models]\nmechanical = { model = "haiku", profile = "api" }\n')
        self.assertEqual(len(config.problems(config.load(self.root))), 1)
        self.write(f"[profiles]\napi = {json.dumps(api)}\n", local=True)
        self.assertEqual(config.problems(config.load(self.root)), [])

    def test_a_home_relative_profile_path_is_expanded(self):
        self.write(MINIMAL + '[profiles]\napi = "~/no-such-claude-dir-for-this-test"\n')
        cfg = config.load(self.root)
        self.assertEqual(config.profile_path(cfg, "api"), os.path.expanduser("~/no-such-claude-dir-for-this-test"))
        self.assertIn("does not exist", " ".join(config.problems(cfg)))

    def test_messaging_defaults_and_types(self):
        self.write(MINIMAL)
        cfg = config.load(self.root)
        self.assertEqual(cfg["messaging"], {"asks_per_attempt": 3, "ask_due_minutes": 60, "pending_minutes": 10,
                                            "doorbell": "socket", "tg_poll_seconds": 5})
        self.assertEqual(self.run_cli("get", "messaging.doorbell")[:2], (0, "socket\n"))
        self.write(MINIMAL + "[messaging]\nasks_per_attempt = 0\ndoorbell = \"resume\"\n")
        self.assertEqual(config.problems(config.load(self.root)), [])  # 0 forbids asks
        for bad, text in (('asks_per_attempt = -1', "asks_per_attempt must be an integer that is 0 or more"),
                          ('pending_minutes = 0', "pending_minutes must be a positive integer"),
                          ('doorbell = "smoke"', 'doorbell must be one of "socket", "resume"'),
                          ('tg_poll = 5', "unknown key messaging.tg_poll")):
            self.write(MINIMAL + "[messaging]\n" + bad + "\n")
            self.assertIn(text, " ".join(config.problems(config.load(self.root))))

    def test_check_warns_when_the_manager_bypasses_permissions_and_the_doorbell_is_a_socket(self):
        self.write(MINIMAL)
        self.assertEqual(self.run_cli("check"), (0, "ok\n", ""))
        os.makedirs(os.path.join(self.root, ".claude"))
        with open(os.path.join(self.root, ".claude", "settings.local.json"), "w") as fh:
            json.dump({"permissions": {"defaultMode": "bypassPermissions"}}, fh)
        code, out, err = self.run_cli("check")
        self.assertEqual((code, out), (0, "ok\n"))
        self.assertIn("warning: messaging.doorbell is \"socket\" but the Manager runs in bypassPermissions", err)
        self.write(MINIMAL + '[messaging]\ndoorbell = "resume"\n')
        self.assertEqual(self.run_cli("check"), (0, "ok\n", ""))
        os.remove(os.path.join(self.root, ".claude", "settings.local.json"))  # the user settings count too
        with open(os.path.join(self.user, "settings.json"), "w") as fh:
            json.dump({"permissions": {"defaultMode": "bypassPermissions"}}, fh)
        self.write(MINIMAL)
        self.assertIn("bypassPermissions", self.run_cli("check")[2])


if __name__ == "__main__":
    unittest.main()
