"""Tests for scripts/render.py. Findings are built inline.

Run: python -m unittest discover -s plugins/repo-health/tests
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "skills", "repo-health", "scripts", "render.py")

_spec = importlib.util.spec_from_file_location("repo_health_render", SCRIPT)
render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render)


def dim(dim_id, level, summary="a summary", status="checked", subproject=".", **extra):
    entry = {"id": dim_id, "subproject": subproject, "tier": 0, "status": status, "level": level,
             "summary": summary, "evidence": ["pyproject.toml:12 → [tool.ruff]"], "not_run_reason": None}
    entry.update(extra)
    return entry


def rec(rec_id, impact, effort, dimension="lint", title=None, **extra):
    entry = {"id": rec_id, "dimension": dimension, "subproject": ".", "title": title or "Title " + rec_id,
             "why": "Why %s." % rec_id, "impact": impact, "effort": effort,
             "first_step": "do-%s --now" % rec_id}
    entry.update(extra)
    return entry


def sample():
    return {
        "schema": 1, "repo": "demo", "commit": "0123456789abcdef0123", "date": "2026-11-10",
        "headline": "Tests run in CI, lint does not; enforce ruff first.",
        "subprojects": [{"path": ".", "languages": ["python"]}],
        "dimensions": [
            dim("tests", 2, "pytest runs in CI"),
            dim("lint", 1, "ruff configured, not in CI"),
            dim("ci", 2, "GitHub Actions on pull_request"),
            dim("size", None, "3 files over 500 lines"),
            dim("structure", None, "", status="not_run", not_run_reason="needs consent", tier=2),
        ],
        "recommendations": [
            rec("r1", "medium", "small"),
            rec("r2", "high", "large"),
            rec("r3", "high", "small"),
            rec("r4", "low", "small"),
            rec("r5", "high", "small"),
            rec("r6", "medium", "medium"),
            rec("r7", "low", "large"),
        ],
        "not_checked": [{"what": "structure review", "why": "needs consent",
                         "how_to_run": "ask for the structure dimension"}],
    }


class Sections(unittest.TestCase):
    def test_sections_come_in_order_conclusion_first(self):
        text = render.render(sample())
        marks = ["# Repo health report: demo", "**Tests run in CI", "## Top actions", "## Scorecard",
                 "## Details", "## Not checked"]
        positions = [text.index(m) for m in marks]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Commit: `0123456789ab`", text)
        self.assertIn("Date: 2026-11-10", text)

    def test_top_actions_are_ranked_by_impact_then_effort_then_file_order(self):
        text = render.render(sample())
        top = text[text.index("## Top actions"):text.index("## Scorecard")]
        order = [t for t in ("r3", "r5", "r2", "r1", "r6") if "Title %s" % t in top]
        self.assertEqual(order, ["r3", "r5", "r2", "r1", "r6"])
        self.assertEqual([top.index("Title %s" % t) for t in order], sorted(top.index("Title %s" % t) for t in order))
        self.assertNotIn("Title r4", top)
        self.assertNotIn("Title r7", top)
        self.assertEqual(top.count("### "), 5)
        self.assertIn("### 1. Title r3", top)

    def test_remaining_recommendations_go_to_details_of_their_dimension(self):
        text = render.render(sample())
        details = text[text.index("## Details"):text.index("## Not checked")]
        self.assertIn("#### Title r4", details)
        self.assertIn("#### Title r7", details)
        self.assertNotIn("Title r3", details)
        self.assertLess(details.index("### Lint and formatting (`lint`)"), details.index("#### Title r4"))
        self.assertIn("pyproject.toml:12 → [tool.ruff]", details)

    def test_scorecard_levels_and_dashes(self):
        text = render.render(sample())
        card = text[text.index("## Scorecard"):text.index("## Details")]
        rows = {line.split("|")[1].strip(): line for line in card.splitlines() if line.startswith("| ") and "---" not in line}
        self.assertIn("2 enforced", rows["Tests"])
        self.assertIn("1 present", rows["Lint and formatting"])
        self.assertIn("| — |", rows["Size and structure metrics"])
        self.assertIn("| not run |", rows["Structure review"])
        order = [line.split("|")[1].strip() for line in card.splitlines() if line.startswith("| ") and "---" not in line][1:]
        self.assertEqual(order, ["Lint and formatting", "Tests", "CI", "Size and structure metrics", "Structure review"])

    def test_secret_scanning_is_a_named_guardrail_dimension(self):
        findings = sample()
        findings["dimensions"] += [dim("secrets", 2), dim("static", 0)]
        card = render.render(findings)
        card = card[card.index("## Scorecard"):card.index("## Details")]
        self.assertIn("| Secret scanning | 2 enforced |", card)
        self.assertLess(card.index("Static analysis and security"), card.index("Secret scanning"))
        findings["dimensions"][-2] = dim("secrets", None)
        with self.assertRaises(render.FindingsError):
            render.render(findings)

    def test_not_checked_section(self):
        text = render.render(sample())
        tail = text[text.index("## Not checked"):]
        self.assertIn("**structure review** — needs consent", tail)
        self.assertIn("`ask for the structure dimension`", tail)
        findings = sample()
        findings["not_checked"] = []
        self.assertIn("Nothing was skipped.", render.render(findings))

    def test_empty_recommendations_still_render_every_section(self):
        findings = sample()
        findings["recommendations"] = []
        text = render.render(findings)
        self.assertIn("No recommendations.", text)
        for heading in ("## Top actions", "## Scorecard", "## Details", "## Not checked"):
            self.assertIn(heading, text)

    def test_not_run_reason_is_shown(self):
        self.assertIn("Not run: needs consent", render.render(sample()))

    def test_unknown_fields_are_ignored(self):
        findings = sample()
        findings["extra"] = {"x": 1}
        findings["dimensions"][0]["whatever"] = [1]
        findings["recommendations"][0]["note"] = "n"
        self.assertEqual(render.render(findings), render.render(sample()))

    def test_pipes_and_backticks_do_not_break_the_layout(self):
        findings = sample()
        findings["dimensions"][0]["summary"] = "a | b\nc"
        findings["recommendations"][2]["first_step"] = "echo ```nested```"
        text = render.render(findings)
        self.assertIn("a \\| b c", text)
        self.assertIn("````\necho ```nested```\n````", text)

    def test_unknown_impact_sorts_last_and_unknown_dimension_keeps_its_id(self):
        findings = sample()
        findings["recommendations"].append(rec("r8", "urgent", "small", dimension="custom", title="Odd one"))
        findings["recommendations"] = [r for r in findings["recommendations"] if r["id"] in ("r3", "r8")]
        text = render.render(findings)
        top = text[text.index("## Top actions"):text.index("## Scorecard")]
        self.assertLess(top.index("Title r3"), top.index("Odd one"))
        findings["recommendations"].extend(rec("x%d" % i, "high", "small") for i in range(5))
        details = render.render(findings)
        details = details[details.index("## Details"):]
        self.assertIn("### custom (`custom`)", details)
        self.assertIn("#### Odd one", details)

    def test_several_subprojects_get_one_table_each(self):
        findings = sample()
        findings["subprojects"] = [{"path": ".", "languages": ["python"]}, {"path": "web", "languages": ["typescript"]}]
        findings["dimensions"].append(dim("lint", 3, "eslint in CI", subproject="web"))
        text = render.render(findings)
        card = text[text.index("## Scorecard"):text.index("## Details")]
        self.assertEqual(card.count("| Dimension |"), 2)
        self.assertLess(card.index("### repo root (.)"), card.index("### web"))
        self.assertIn("**web** — Level: 3 effective", text)

    def test_single_subproject_has_no_subproject_heading(self):
        card = render.render(sample())
        card = card[card.index("## Scorecard"):card.index("## Details")]
        self.assertNotIn("### ", card)


class Comparison(unittest.TestCase):
    def previous(self):
        old = sample()
        old["date"] = "2026-11-01"
        old["dimensions"] = [dim("lint", 2), dim("tests", 1), dim("ci", 2), dim("size", None),
                             dim("deps", 0)]
        return old

    def changes(self, text):
        card = text[text.index("## Scorecard"):text.index("## Details")]
        out = {}
        for line in card.splitlines():
            if line.startswith("| ") and "---" not in line and "Dimension" not in line:
                cols = [c.strip() for c in line.strip("|").split("|")]
                out[cols[0]] = cols[-1]
        return out

    def test_arrows(self):
        text = render.render(sample(), self.previous())
        changes = self.changes(text)
        self.assertEqual(changes["Lint and formatting"], "↓")
        self.assertEqual(changes["Tests"], "↑")
        self.assertEqual(changes["CI"], "=")
        self.assertEqual(changes["Size and structure metrics"], "=")      # null level, row existed
        self.assertEqual(changes["Structure review"], "new")             # null level, no row before
        self.assertIn("Compared with the run of 2026-11-01", text)

    def test_new_row_without_previous_entry(self):
        previous = self.previous()
        previous["dimensions"] = [d for d in previous["dimensions"] if d["id"] != "tests"]
        self.assertEqual(self.changes(render.render(sample(), previous))["Tests"], "new")

    def test_change_is_per_subproject(self):
        findings = sample()
        findings["dimensions"] = [dim("lint", 2, subproject="a"), dim("lint", 1, subproject="b")]
        previous = copy.deepcopy(findings)
        previous["dimensions"] = [dim("lint", 1, subproject="a"), dim("lint", 1, subproject="b")]
        text = render.render(findings, previous)
        self.assertIn("↑", text)
        self.assertIn("| = |", text)

    def test_without_previous_the_column_shows_a_dash(self):
        text = render.render(sample())
        self.assertEqual(set(self.changes(text).values()), {"—"})
        self.assertNotIn("Compared with", text)

    def test_current_level_after_a_null_level_is_new(self):
        previous = self.previous()
        previous["dimensions"][0]["level"] = None
        previous["dimensions"][0]["status"] = "not_run"
        self.assertEqual(self.changes(render.render(sample(), previous))["Lint and formatting"], "new")


class Validation(unittest.TestCase):
    def assert_error(self, findings, text):
        with self.assertRaises(render.FindingsError) as ctx:
            render.render(findings)
        self.assertIn(text, str(ctx.exception))

    def test_missing_top_level_fields_are_named(self):
        for field in ("schema", "repo", "date", "headline", "dimensions", "recommendations", "not_checked"):
            findings = sample()
            del findings[field]
            self.assert_error(findings, field)

    def test_headline_must_be_a_non_empty_string(self):
        findings = sample()
        findings["headline"] = "  "
        self.assert_error(findings, "headline")
        findings["headline"] = 3
        self.assert_error(findings, "headline")

    def test_schema_must_be_1(self):
        findings = sample()
        findings["schema"] = 2
        self.assert_error(findings, "schema")

    def test_missing_dimension_and_recommendation_fields_are_named_with_their_index(self):
        findings = sample()
        del findings["dimensions"][1]["summary"]
        self.assert_error(findings, "dimensions[1].summary")
        findings = sample()
        del findings["recommendations"][2]["first_step"]
        self.assert_error(findings, "recommendations[2].first_step")
        findings = sample()
        del findings["not_checked"][0]["why"]
        self.assert_error(findings, "not_checked[0].why")

    def test_level_rules(self):
        findings = sample()
        findings["dimensions"][1]["level"] = None            # lint, checked: not allowed
        self.assert_error(findings, "dimensions[1].level")
        findings = sample()
        findings["dimensions"][1]["status"] = "not_run"      # lint, not run: null is fine
        findings["dimensions"][1]["level"] = None
        render.render(findings)
        findings = sample()
        findings["dimensions"][3]["level"] = None            # size: null is fine when checked
        render.render(findings)
        for bad in (4, -1, "2", True, 1.5):
            findings = sample()
            findings["dimensions"][1]["level"] = bad
            self.assert_error(findings, "dimensions[1].level")

    def test_status_must_be_known(self):
        findings = sample()
        findings["dimensions"][0]["status"] = "done"
        self.assert_error(findings, "dimensions[0].status")

    def test_findings_must_be_an_object(self):
        with self.assertRaises(render.FindingsError):
            render.render([])


class Summary(unittest.TestCase):
    def test_terminal_summary(self):
        text = render.summary(sample(), "/x/report.md")
        lines = text.splitlines()
        self.assertEqual(lines[0], "Tests run in CI, lint does not; enforce ruff first.")
        self.assertIn("Top actions:", lines)
        self.assertIn("1. Title r3", lines)
        self.assertIn("   first step: do-r3 --now", lines)
        self.assertEqual(sum(1 for l in lines if l[:2] in ("1.", "2.", "3.", "4.", "5.", "6.")), 5)
        self.assertEqual(lines[-1], "Report: /x/report.md")

    def test_multi_line_first_step_shows_its_first_line(self):
        findings = sample()
        findings["recommendations"][2]["first_step"] = "line one\nline two"
        self.assertIn("first step: line one …", render.summary(findings))


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="repo-health-render-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def save(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "w") as handle:
            if isinstance(data, str):
                handle.write(data)
            else:
                json.dump(data, handle)
        return path

    def findings(self, date):
        data = sample()
        data["date"] = date
        return data

    def test_previous_is_the_newest_older_findings_file(self):
        self.save("findings-2026-11-01.json", self.findings("2026-11-01"))
        self.save("findings-2026-11-05.json", self.findings("2026-11-05"))
        current = self.save("findings-2026-11-10.json", self.findings("2026-11-10"))
        self.save("findings-2026-11-12.json", self.findings("2026-11-12"))
        self.save("other.json", self.findings("2026-11-09"))
        path, data = render.find_previous(current, self.findings("2026-11-10"))
        self.assertEqual(os.path.basename(path), "findings-2026-11-05.json")
        self.assertEqual(data["date"], "2026-11-05")

    def test_broken_older_file_is_skipped(self):
        self.save("findings-2026-11-01.json", self.findings("2026-11-01"))
        self.save("findings-2026-11-05.json", "{not json")
        current = self.save("findings-2026-11-10.json", self.findings("2026-11-10"))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            found = render.find_previous(current, self.findings("2026-11-10"))
        self.assertEqual(os.path.basename(found[0]), "findings-2026-11-01.json")
        self.assertIn("findings-2026-11-05.json", err.getvalue())

    def test_no_older_file(self):
        current = self.save("findings-2026-11-10.json", self.findings("2026-11-10"))
        self.assertIsNone(render.find_previous(current, self.findings("2026-11-10")))

    def test_cli_writes_the_report_and_prints_the_summary(self):
        old = self.findings("2026-11-01")
        old["dimensions"][1]["level"] = 2
        self.save("findings-2026-11-01.json", old)
        current = self.save("findings-2026-11-10.json", self.findings("2026-11-10"))
        proc = subprocess.run([sys.executable, SCRIPT, current], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = os.path.join(self.dir, "report-2026-11-10.md")
        self.assertTrue(os.path.exists(report))
        with open(report) as handle:
            text = handle.read()
        self.assertIn("↓", text)                              # compared with the older file beside it
        out = proc.stdout.decode()
        self.assertIn("Tests run in CI", out)
        self.assertIn("Report: " + report, out)

    def test_cli_options(self):
        old = self.save("old.json", self.findings("2026-10-01"))
        current = self.save("findings.json", self.findings("2026-11-10"))
        target = os.path.join(self.dir, "out", "r.md")
        proc = subprocess.run([sys.executable, SCRIPT, current, "--previous", old, "-o", target],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(target) as handle:
            self.assertIn("Compared with the run of 2026-10-01", handle.read())
        self.save("findings-2026-01-01.json", self.findings("2026-01-01"))
        subprocess.run([sys.executable, SCRIPT, current, "--no-previous", "-o", target],
                       stdout=subprocess.PIPE, check=True)
        with open(target) as handle:
            self.assertNotIn("Compared with", handle.read())

    def test_cli_error_names_the_field(self):
        data = sample()
        del data["headline"]
        path = self.save("findings.json", data)
        proc = subprocess.run([sys.executable, SCRIPT, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("headline", proc.stderr.decode())
        self.assertFalse(os.path.exists(os.path.join(self.dir, "report.md")))

    def test_cli_rejects_missing_and_invalid_files(self):
        proc = subprocess.run([sys.executable, SCRIPT, os.path.join(self.dir, "none.json")],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 2)
        bad = self.save("bad.json", "{oops")
        proc = subprocess.run([sys.executable, SCRIPT, bad], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not valid JSON", proc.stderr.decode())

    def test_default_output_names(self):
        self.assertTrue(render.default_output("/a/findings-2026-11-10.json", {"date": "x"}).endswith("/a/report-2026-11-10.md"))
        self.assertTrue(render.default_output("/a/findings.json", {"date": "x"}).endswith("/a/report.md"))
        self.assertTrue(render.default_output("/a/other.json", {"date": "2026-11-10"}).endswith("/a/report-2026-11-10.md"))

    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        with open(SCRIPT) as handle:
            self.assertEqual(handle.readline().strip(), "#!/usr/bin/env python3")


if __name__ == "__main__":
    unittest.main()
