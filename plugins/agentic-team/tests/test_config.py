"""Tests for scripts/config.py. Run: "$PY" plugins/agentic-team/tests/run_parallel.py (all tests, in parallel)"""

import contextlib
import io
import json
import os
import subprocess
import re
import sys
import tempfile
import textwrap
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import config  # noqa: E402
import reference_data  # noqa: E402

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

    def test_config_verify_keys(self):
        self.write('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n[verify]\nrevisions_per_attempt = 0\n'
                   'keep_sessions_minutes = 30\nseat = "own"\nseat_wait_minutes = 2\n')
        self.assertEqual(self.run_cli("check")[:2], (0, "ok\n"))
        self.write('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n[verify]\nseat = "elsewhere"\n')
        code, out, err = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertIn("verify.seat", out + err)

    def test_notifications_events_and_digest(self):
        self.write(MINIMAL)
        loaded = config.load(self.root)["notifications"]
        self.assertEqual((loaded["events"], loaded["digest"]),
                         (["decision", "abandon", "push-failed", "pr-closed", "all-done", "blocked"], "off"))
        self.write(MINIMAL + '[notifications]\nevents = []\ndigest = "daily"\n')
        self.assertEqual(config.problems(config.load(self.root)), [])
        for text, expect in (('events = ["decision", "merged"]', "notifications.events must be a list of notification events"),
                             ('events = "decision"', "notifications.events must be a list of notification events"),
                             ('digest = "hourly"', 'notifications.digest must be one of "off", "daily"')):
            with self.subTest(text=text):
                self.write(MINIMAL + "[notifications]\n" + text + "\n")
                self.assertIn(expect, "\n".join(config.problems(config.load(self.root))))

    def test_hooks_defaults_and_valid_values(self):
        self.write(MINIMAL)
        hooks = config.load(self.root)["hooks"]
        self.assertEqual((hooks["enabled"], hooks["layered"], hooks["compact_pins"], hooks["summarize_fallback"],
                          hooks["passthrough_chars"], hooks["large_chars"]), (False, True, True, False, 20000, 100000))
        self.assertIn("make test*", hooks["commands"])
        self.assertIn("gh run view --log", hooks["commands"])
        self.write(MINIMAL + '[hooks]\nenabled = true\nsummarize_fallback = true\npassthrough_chars = 5000\n'
                   'large_chars = 5000\ncommands = ["cargo test", "just *-test*"]\n')
        self.assertEqual(self.run_cli("check")[:2], (0, "ok\n"))
        self.assertEqual(config.load(self.root)["hooks"]["commands"], ["cargo test", "just *-test*"])

    def test_hooks_need_a_permission_mode_where_the_rewrite_is_not_asked_about(self):
        for mode, ok in (("auto", True), ("bypassPermissions", True), ("default", False), ("acceptEdits", False)):
            for enabled in (True, False):
                with self.subTest(mode=mode, enabled=enabled):
                    self.write(MINIMAL + f'[sessions]\npermission_mode = "{mode}"\ntimezone = "UTC"\n[hooks]\nenabled = {str(enabled).lower()}\n')
                    code, out, err = self.run_cli("check")
                    self.assertEqual(code, 0 if ok or not enabled else 2)
                    if enabled and not ok:
                        self.assertIn("hooks.enabled needs sessions.permission_mode", out + err)

    def test_hooks_bad_values_are_named(self):
        for text, expect in (
                ('enabled = "yes"', "hooks.enabled must be true or false"),
                ('layered = 1', "hooks.layered must be true or false"),
                ('compact_pins = "on"', "hooks.compact_pins must be true or false"),
                ('summarize_fallback = "no"', "hooks.summarize_fallback must be true or false"),
                ('passthrough_chars = 0', "hooks.passthrough_chars must be a positive integer"),
                ('large_chars = -5', "hooks.large_chars must be a positive integer"),
                ('commands = "pytest"', "hooks.commands must be a list of command prefixes or globs"),
                ('commands = [""]', "hooks.commands must be a list"),
                ('commands = [" pytest"]', "hooks.commands must be a list"),
                ('commands = [3]', "hooks.commands must be a list"),
                ('passthrough_chars = 9000\nlarge_chars = 100', "hooks.large_chars must be at least hooks.passthrough_chars"),
                ('enable = true', "hooks.enable")):
            with self.subTest(text):
                self.write(MINIMAL + "[hooks]\n" + text + "\n")
                code, out, err = self.run_cli("check")
                self.assertEqual(code, 2)
                self.assertIn(expect, out + err)

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
                                       "catch_up": "host", "after_rebase": "", "draft": False, "remove_worktrees": True,
                                       "disposable": []})
        self.assertEqual(set(cfg["merge"]), {"mode", "host", "remote", "base", "method", "catch_up", "after_rebase",
                                             "draft", "remove_worktrees", "disposable"})
        self.assertEqual(cfg["verify"], {"kind": "code", "revisions_per_attempt": 2, "keep_sessions_minutes": 60, "seat": "task",
                                         "seat_wait_minutes": 5, "ci_ref_prefix": "ci-"})
        self.assertEqual(cfg["roles"], {"default": ""})
        self.assertEqual(cfg["scope"], {"adjacent": []})
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

    def test_140_ci_ref_prefix_makes_a_valid_branch_name(self):
        for good in ("ci-", "agentic/ci-", "ci/", "CI_run.x-"):
            with self.subTest(good):
                self.write(MINIMAL + f'[verify]\nci_ref_prefix = "{good}"\n')
                self.assertEqual(config.problems(config.load(self.root)), [])
                check = subprocess.run(["git", "check-ref-format", "--branch", f"{good}1-1"], capture_output=True)
                self.assertEqual(check.returncode, 0, good)
        for bad in ("ci", "-ci-", "/ci-", ".ci-", "c i-", "ci..x-", "ci//x-", "ci/.x-", "ci./", "ci.lock/", "ci~-", "", " "):
            with self.subTest(bad):
                self.write(MINIMAL + f'[verify]\nci_ref_prefix = "{bad}"\n')
                self.assertIn("verify.ci_ref_prefix must be a branch name prefix that ends with - or /",
                              " ".join(config.problems(config.load(self.root))))

    def test_after_rebase_is_a_string_and_empty_by_default(self):
        self.write(MINIMAL + '[merge]\nafter_rebase = "test -f ok"\n')
        self.assertEqual(config.problems(config.load(self.root)), [])
        self.assertEqual(self.run_cli("get", "merge.after_rebase")[:2], (0, "test -f ok\n"))
        self.write(MINIMAL + "[merge]\nafter_rebase = 3\n")
        self.assertEqual(config.problems(config.load(self.root)), ["merge.after_rebase must be a string, not 3"])

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
        self.assertEqual(len(config.DISPOSABLE_DEFAULT), 37)
        for pattern in config.DISPOSABLE_DEFAULT:
            self.assertEqual(config.pattern_problems("x", [pattern, "!" + pattern]), [], pattern)

    def test_scope_adjacent_is_a_list_of_known_kinds(self):
        self.write(MINIMAL + '[scope]\nadjacent = ["lower-ratchet", "stale-exemption", "own-lint"]\n')
        self.assertEqual(config.problems(config.load(self.root)), [])
        self.assertEqual(self.run_cli("get", "scope.adjacent")[:2],
                         (0, '["lower-ratchet", "stale-exemption", "own-lint"]\n'))
        self.write(MINIMAL + '[scope]\nadjacent = ["lower-ratchet", "raise-ratchet"]\n')
        self.assertEqual(config.problems(config.load(self.root)), [
            'scope.adjacent: "raise-ratchet" is not an adjacent-change kind; the kinds are '
            "lower-ratchet, stale-exemption, own-lint, own-dependents, own-registry, convention-place, moved-path "
            "(did you mean lower-ratchet?)"])
        self.assertEqual(self.run_cli("check")[0], 2)
        self.write(MINIMAL + '[scope]\nadjacent = ["own-dependents", "own-registry", "convention-place", "moved-path"]\n')
        self.assertEqual(self.run_cli("check")[0], 0)
        self.write(MINIMAL + '[scope]\nadjacent = "own-lint"\n')
        self.assertEqual(config.problems(config.load(self.root)),
                         ['scope.adjacent must be a list of adjacent-change kinds, not "own-lint"'])

    def test_report_require_ran_is_a_table_of_verify_kind_to_prefixes(self):
        self.write(MINIMAL)
        self.assertEqual(config.load(self.root)["report"]["require_ran"], {})
        self.write(MINIMAL + '[report]\nrequire_ran = { "code" = ["reuse:", "mutation:"], "design-doc" = ["self-check:"] }\n')
        self.assertEqual(config.problems(config.load(self.root)), [])
        self.assertEqual(self.run_cli("get", "report.require_ran", "--json")[:2],
                         (0, '{"code": ["reuse:", "mutation:"], "design-doc": ["self-check:"]}\n'))
        self.write(MINIMAL + '[report]\nrequire_ran = { "cod" = ["reuse:"] }\n')
        self.assertEqual(config.problems(config.load(self.root)), [
            'report.require_ran: "cod" is not a verify kind; the kinds are code, schema, design-doc (did you mean code?)'])
        self.write(MINIMAL + '[report]\nrequire_ran = { "code" = "reuse:" }\n')
        self.assertIn("report.require_ran must be a table of verify kind = list of line prefixes",
                      config.problems(config.load(self.root))[0])
        self.write(MINIMAL + '[report]\nrequire_ran = { "code" = [" reuse:"] }\n')
        self.assertEqual(len(config.problems(config.load(self.root))), 1)

    def test_report_checks_are_commands_with_per_kind_lists_and_a_timeout(self):
        self.write(MINIMAL)
        report = config.load(self.root)["report"]
        self.assertEqual((report["checks"], report["checks_by_kind"], report["check_timeout_seconds"]), ([], {}, 600))
        self.write(MINIMAL + '[report]\nchecks = ["make lint"]\ncheck_timeout_seconds = 90\n'
                   '[report.checks_by_kind]\ndesign-doc = ["python docs/check_refs.py"]\n')
        self.assertEqual(config.problems(config.load(self.root)), [])
        self.assertEqual(self.run_cli("get", "report.checks_by_kind", "--json")[:2],
                         (0, '{"design-doc": ["python docs/check_refs.py"]}\n'))
        self.write(MINIMAL + '[report.checks_by_kind]\ndesign = ["x"]\n')
        self.assertEqual(config.problems(config.load(self.root)), [
            'report.checks_by_kind: "design" is not a verify kind; the kinds are code, schema, design-doc (did you mean design-doc?)'])
        for bad in ('checks = "make lint"', 'checks = [""]', 'checks = [1]', "check_timeout_seconds = 0",
                    'checks_by_kind = { code = "make" }', 'checks = ["make lint\\nmake test"]',
                    'checks_by_kind = { code = ["make\\nmake"] }'):
            with self.subTest(bad):
                self.write(MINIMAL + f"[report]\n{bad}\n")
                self.assertEqual(len(config.problems(config.load(self.root))), 1)

    def test_summary_lang_is_en_or_zh_and_defaults_to_en(self):
        self.write(MINIMAL)
        self.assertEqual(config.load(self.root)["report"]["summary_lang"], "en")
        self.write(MINIMAL + '[report]\nsummary_lang = "zh"\n')
        self.assertEqual((config.problems(config.load(self.root)), self.run_cli("get", "report.summary_lang")[:2]), ([], (0, "zh\n")))
        self.write(MINIMAL + '[report]\nsummary_lang = "fr"\n')
        self.assertIn('summary_lang must be one of "en", "zh"', " ".join(config.problems(config.load(self.root))))

    def test_verifier_by_tier_maps_tiers_and_override_keys_to_models(self):
        self.write(MINIMAL)
        self.assertEqual(config.load(self.root)["models"]["verifier_by_tier"], {})
        self.assertIsNone(config.verifier_model(config.load(self.root), "implementation"))
        self.write(MINIMAL + '[models]\nverifier = "haiku"\n[models.overrides]\n"Data Migration" = "opus"\n'
                   '[models.verifier_by_tier]\nimplementation = "sonnet"\njudgement = { model = "opus", effort = "high" }\n'
                   '"data migration" = "fable"\n')
        loaded = config.load(self.root)
        self.assertEqual(config.problems(loaded), [])
        for tier, want in (("implementation", "sonnet"), ("Implementation ", "sonnet"), ("judgement", "opus"),
                           ("DATA MIGRATION", "fable"), ("mechanical", "haiku"), (None, "haiku")):
            self.assertEqual(config.verifier_model(loaded, tier)["model"], want, tier)
        self.assertEqual(config.verifier_model(loaded, "judgement")["effort"], "high")

    def test_verifier_by_tier_rejects_unknown_keys_and_bad_models(self):
        self.write(MINIMAL + '[models.verifier_by_tier]\nimplementaton = "sonnet"\n')
        self.assertEqual(config.problems(config.load(self.root)), [
            'models.verifier_by_tier: "implementaton" is not a tier or a models.overrides key; choose from: mechanical, '
            "implementation, judgement (did you mean implementation?)"])
        self.write(MINIMAL + '[models.verifier_by_tier]\nverifier = "sonnet"\n')
        self.assertEqual(len(config.problems(config.load(self.root))), 1)
        self.write(MINIMAL + '[models.verifier_by_tier]\njudgement = ""\n')
        self.assertIn("models.verifier_by_tier must be a table of tier or models.overrides key = model",
                      config.problems(config.load(self.root))[0])
        self.write(MINIMAL + '[models.verifier_by_tier]\njudgement = { model = "opus", profile = "nope" }\n')
        self.assertIn("models.verifier_by_tier.judgement uses profile 'nope'", config.problems(config.load(self.root))[0])

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

    def write_taskgraph(self, text, folder=None):
        path = os.path.join(folder or self.root, config.TASKGRAPH_TOML)
        with open(path, "w") as fh:
            fh.write(textwrap.dedent(text))
        return path

    def test_check_warns_for_each_run_time_key_the_github_backend_would_send_to_the_issue(self):
        self.write(MINIMAL)
        with unittest.mock.patch.dict(os.environ, {"TASKGRAPH_CONFIG": ""}):  # turned off: the SQLite store
            self.assertEqual(self.run_cli("check"), (0, "ok\n", ""))
        os.environ.pop("TASKGRAPH_CONFIG", None)
        self.assertEqual(self.run_cli("check"), (0, "ok\n", ""))  # no .taskgraph.toml at all
        path = self.write_taskgraph("""\
            version = 1
            [projects."other"]
            backend = "github"
            repo = "o/r"
        """)
        self.assertEqual(self.run_cli("check"), (0, "ok\n", ""))  # the file does not name this project
        self.write_taskgraph("""\
            version = 1
            [projects."demo"]
            backend = "github"
            repo = "o/r"
            [projects."demo".meta]
            local = ["sessions", "session", "cleanup_kept", "host_rebase"]
            deferred = ["tokens", "model"]
        """)
        code, out, err = self.run_cli("check")
        self.assertEqual((code, out), (0, "ok\n"))
        warned = [line for line in err.splitlines() if "run-time meta key" in line]
        self.assertEqual(len(warned), 3, err)
        for key, kind in (("mailbox", "local"), ("mailbox_ids", "local"), ("started_at", "deferred")):
            self.assertTrue(any(f"key '{key}'" in line and
                                f'add it to {kind} under [projects."demo".meta] in {os.path.realpath(path)}' in line
                                for line in warned), (key, err))
        local, deferred = (json.dumps(list(config.RUNTIME_META[k])) for k in ("local", "deferred"))
        self.write_taskgraph(f"""\
            version = 1
            [projects."demo"]
            backend = "github"
            repo = "o/r"
            [projects."demo".meta]
            local = {local}
            deferred = {deferred}
            [projects."demo".results]
            local = {json.dumps(list(config.LOCAL_RESULT_KINDS))}
        """)
        self.assertEqual(self.run_cli("check"), (0, "ok\n", ""))
        self.write_taskgraph('version = 1\n[projects."demo"]\nbackend = "github"\nrepo = "o/r"\n')  # no meta table
        self.assertEqual(sum("run-time meta key" in line for line in self.run_cli("check")[2].splitlines()),
                         len(config.RUNTIME_META["local"]) + len(config.RUNTIME_META["deferred"]))

    def test_check_warns_for_each_recommended_local_result_kind_the_github_backend_would_post(self):
        self.write(MINIMAL)
        os.environ.pop("TASKGRAPH_CONFIG", None)
        meta = (f'[projects."demo".meta]\nlocal = {json.dumps(list(config.RUNTIME_META["local"]))}\n'
                f'deferred = {json.dumps(list(config.RUNTIME_META["deferred"]))}\n')
        head = 'version = 1\n[projects."demo"]\nbackend = "github"\nrepo = "o/r"\n' + meta
        path = self.write_taskgraph(head)
        code, out, err = self.run_cli("check")
        self.assertEqual((code, out), (0, "ok\n"))
        self.assertEqual(err.splitlines(), [
            f"config.py: warning: taskgraph: the GitHub backend posts each {kind!r} result row as an issue comment, and "
            f"comments share GitHub's rate limit on creating content; add {kind!r} to local under "
            f'[projects."demo".results] in {os.path.realpath(path)}' for kind in config.LOCAL_RESULT_KINDS] or err)
        self.write_taskgraph(head + '[projects."demo".results]\nlocal = ["steer", "ask", "check"]\n')
        err = self.run_cli("check")[2]
        self.assertEqual([k for k in config.LOCAL_RESULT_KINDS if f"posts each {k!r} result row" in err], ["ack"])
        self.write_taskgraph(head + '[projects."demo".results]\nlocal = ["ack", "steer", "check", "ask", "answer"]\n')
        self.assertEqual(self.run_cli("check"), (0, "ok\n", ""))
        self.assertEqual(config.taskgraph_store(self.root, "demo")["results_local"], ("ack", "steer", "check", "ask", "answer"))

    def test_check_fails_with_an_upgrade_instruction_when_tg_has_no_summary_option(self):
        self.write(MINIMAL)
        old = os.path.join(self.root, "tg.py")
        with open(old, "w") as fh:
            fh.write("print('usage: tg result add [-h] [--body BODY] [--body-file BODY_FILE]')\n")
        with unittest.mock.patch.dict(os.environ, {"TASKGRAPH_TG": old}):
            code, out, err = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertIn("is older than 1.22.0", out)
        self.assertIn("Upgrade Taskgraph", out)
        new = os.path.join(self.root, "tg-new.py")
        with open(new, "w") as fh:
            fh.write("print('usage: tg result add [-h] [--summary SUMMARY]')\n")
        with unittest.mock.patch.dict(os.environ, {"TASKGRAPH_TG": new}):
            self.assertEqual(self.run_cli("check")[:2], (0, "ok\n"))

    def test_check_warns_when_revise_is_kept_local_and_says_it_must_stay_remote(self):
        self.write(MINIMAL)
        os.environ.pop("TASKGRAPH_CONFIG", None)
        meta = (f'[projects."demo".meta]\nlocal = {json.dumps(list(config.RUNTIME_META["local"]))}\n'
                f'deferred = {json.dumps(list(config.RUNTIME_META["deferred"]))}\n')
        head = 'version = 1\n[projects."demo"]\nbackend = "github"\nrepo = "o/r"\n' + meta
        self.write_taskgraph(head + '[projects."demo".results]\nlocal = ["ack", "steer", "check", "revise"]\n')
        code, out, err = self.run_cli("check")
        self.assertEqual((code, out), (0, "ok\n"))
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("'revise' is in results.local", err)
        self.assertIn("must stay remote", err)

    def test_check_says_tg_could_not_run_instead_of_older_when_the_help_fails(self):
        self.write(MINIMAL)
        broken = os.path.join(self.root, "tg-broken.py")
        with open(broken, "w") as fh:
            fh.write("import sys\nprint('Traceback: boom', file=sys.stderr)\nsys.exit(1)\n")
        with unittest.mock.patch.dict(os.environ, {"TASKGRAPH_TG": broken}):
            code, out, err = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertIn("could not run tg", out)
        self.assertIn("boom", out)
        self.assertNotIn("older than", out)

    def test_the_taskgraph_file_is_found_as_tg_finds_it(self):
        os.environ.pop("TASKGRAPH_CONFIG", None)
        inner = os.path.join(self.root, "a", "b")
        os.makedirs(inner)
        path = self.write_taskgraph('version = 1\n[projects."demo"]\nbackend = "github"\nrepo = "o/r"\n')
        self.assertEqual(config.taskgraph_file(inner), os.path.realpath(path))  # a parent folder
        other = self.write_taskgraph('version = 1\n', folder=inner)
        self.assertEqual(config.taskgraph_file(inner, env={"TASKGRAPH_CONFIG": other}), other)
        self.assertIsNone(config.taskgraph_file(inner, env={"TASKGRAPH_CONFIG": ""}))
        self.assertIsNone(config.taskgraph_store(inner, "demo"))  # the nearer file does not name the project
        self.assertEqual(config.taskgraph_store(self.root, "demo")["local"], ())

    def test_the_reference_data_lists_each_run_time_key_once(self):
        listed = [k for keys, _ in reference_data.META_WHY for k in keys]
        self.assertEqual(len(listed), len(set(listed)))
        for kind, keys in config.RUNTIME_META.items():
            self.assertLessEqual(set(keys), set(listed), kind)
        self.assertEqual(set(config.RUNTIME_META["local"]) & set(config.RUNTIME_META["deferred"]), set())


if __name__ == "__main__":
    unittest.main()
