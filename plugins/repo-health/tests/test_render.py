"""Tests for scripts/render.py (findings schema 2 with a score.json). Inputs are built inline.

Run: python -m unittest discover -s plugins/repo-health/tests
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "repo-health", "scripts")
SCRIPT = os.path.join(SCRIPTS, "render.py")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("repo_health_render", SCRIPT)
render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render)


def row(dim_id, level, summary="a summary", sub=".", status="checked", **extra):
    entry = {"id": dim_id, "subproject": sub, "level": level, "status": status, "rule": dim_id + ".x",
             "partial": None, "needs": None, "facts": ["pyproject.toml:12 (ruff)"], "summary": summary,
             "summary_zh": "中文摘要：" + dim_id}
    entry.update(extra)
    return entry


def gap(gap_id, dimension="lint", what="Do the thing", priority=5.0, hotspot_files=()):
    return {"id": gap_id, "dimension": dimension, "subproject": ".", "rule": "x", "what": what, "facts": [],
            "hotspot_files": list(hotspot_files), "effort": "add", "priority": priority}


def sample_score():
    gaps = [gap("g%d" % i, priority=10 - i, what="What %d" % i, hotspot_files=["src/hot%d.py" % i] if i == 1 else [])
            for i in range(1, 8)]
    return {
        "as_of": "2026-11-10", "repo": "/r/demo", "commit": "0123456789abcdef",
        "profile": {"authors": "team", "visibility": "public", "kind": "application"},
        "dimensions": [
            row("lint", 1, "Linter configured, not blocking in CI."),
            row("types", 2, "Type checker blocks in CI."),
            row("secrets", None, "Secret scanning setting not visible.", status="unknown",
                needs="GitHub secret-scanning setting", facts=["ghfacts.json#/security_and_analysis = not_visible"]),
            row("tests", 1, "CI runs 2 of 4 test suites.",
                partial={"covered": 2, "total": 4, "missing": ["a/tests", "b/tests"], "unit": "test suites"}),
            row("coverage", None, "No tests to measure.", status="not_applicable", facts=[]),
            row("ci", 3, "Pull requests run tests and lint.", facts=[]),
        ],
        "hotspots": [{"path": "src/hot%d.py" % i, "commits": 10 - i, "loc": 100 * i, "tests_in_ci": [True, False, "unknown"][i % 3],
                      "top_author_share": 0.5 + i / 20.0} for i in range(1, 13)],
        "ci_health": {"available": False}, "gaps": gaps, "dismissed": [], "regressed": [], "deferred": [],
        "not_applicable": [], "changes": None, "inputs": {},
    }


def rec(gap_id, impact="high", effort="small", title=None, **step):
    first = {"file": "pyproject.toml", "snippet": "[tool.ruff]\nline-length = 100", "command": "uvx ruff check .",
             "verify": "uvx ruff check . && echo ok"}
    first.update(step)
    return {"gap": gap_id, "title": title or "Title " + gap_id, "why": "Because %s matters." % gap_id,
            "impact": impact, "effort": effort, "first_step": first, "reorder_reason": None}


def sample_findings(count=7):
    return {
        "schema": 2, "lang": "en", "repo": "demo", "commit": "0123456789abcdef0123", "stamp": "2026-11-10T0930",
        "headline": "Tests run in CI for two of four suites; lint does not block.",
        "score": "score-2026-11-10T0930.json",
        "inputs": {"detect": "detect-2026-11-10T0930.json", "hotspots": "hotspots-2026-11-10T0930.json",
                   "ghfacts": "ghfacts-2026-11-10T0930.json"},
        "overrides": [],
        "recommendations": [rec("g%d" % i) for i in range(1, count + 1)],
        "reviews": {},
        "not_checked": [{"what": "structure review", "why": "needs consent", "how_to_run": "ask for the review"}],
    }


def card_rows(text):
    card = text[text.index("## Scorecard"):]
    card = card[:card.index("\n\n", card.index("| ---"))]
    return [line for line in card.splitlines() if line.startswith("| ") and "---" not in line][1:]


class Layout(unittest.TestCase):
    def test_sections_come_in_order_conclusion_first(self):
        text = render.render(sample_findings(), sample_score())
        marks = ["# Repo health report: demo", "**Tests run in CI", "## Do these first", "## Scorecard",
                 "## More recommendations", "## Hotspots", "## Evidence", "## Not checked"]
        positions = [text.index(m) for m in marks]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("## Since last run", text)
        self.assertIn("Commit: `0123456789ab`", text)
        self.assertIn("Date: 2026-11-10", text)
        self.assertNotIn("compared with", text)

    def test_top_five_blocks_have_step_verify_and_gap_id(self):
        text = render.render(sample_findings(), sample_score())
        top = text[text.index("## Do these first"):text.index("## Scorecard")]
        self.assertEqual(len(re.findall(r"^### \d\.", top, re.M)), 5)
        self.assertIn("### 1. Title g1 (`g1`)", top)
        self.assertIn("```\nuvx ruff check .\n```", top)
        self.assertIn("[tool.ruff]", top)
        self.assertIn("Verify: `uvx ruff check . && echo ok`", top)
        self.assertIn("Touches hotspots: `src/hot1.py`", top)
        self.assertIn("Title g6", text[text.index("## More recommendations"):])

    def test_more_recommendations_are_one_line_with_the_first_command(self):
        text = render.render(sample_findings(), sample_score())
        more = text[text.index("## More recommendations"):text.index("## Hotspots")]
        self.assertIn("- Title g6 (`g6`) — `uvx ruff check .`", more)
        findings = sample_findings()
        findings["recommendations"][5]["first_step"]["command"] = None
        text = render.render(findings, sample_score())
        self.assertIn("(`g6`) — `pyproject.toml`", text)

    def test_scorecard_levels(self):
        rows = card_rows(render.render(sample_findings(), sample_score()))
        self.assertTrue(rows[0].startswith("| Lint and formatting | 1 present |"))
        joined = "\n".join(rows)
        self.assertIn("| Type checking | 2 enforced |", joined)
        self.assertIn("| Tests | 1 present (partial: 2 of 4 test suites) |", joined)
        self.assertIn("| Secret scanning | unknown (needs: GitHub secret-scanning setting) |", joined)
        self.assertIn("| Coverage | n/a |", joined)
        self.assertIn("| CI | 3 effective |", joined)
        order = [r.split("|")[1].strip() for r in rows]
        self.assertEqual(order, ["Lint and formatting", "Type checking", "Secret scanning", "Tests", "Coverage", "CI"])

    def test_several_subprojects_name_the_subproject(self):
        score = sample_score()
        score["dimensions"].append(row("lint", 0, "No linter.", sub="web"))
        text = render.render(sample_findings(), score)
        self.assertIn("| Lint and formatting (web) | 0 absent |", text)

    def test_hotspots_table_has_ten_rows(self):
        text = render.render(sample_findings(), sample_score())
        table = text[text.index("## Hotspots"):text.index("## Evidence")]
        lines = [l for l in table.splitlines() if l.startswith("| src/")]
        self.assertEqual(len(lines), 10)
        self.assertIn("| src/hot1.py | 9 | 100 | no | 55% |", table)
        self.assertIn("| unknown |", table)

    def test_evidence_only_for_weak_unknown_partial_or_overridden(self):
        findings = sample_findings()
        findings["overrides"] = [{"dimension": "ci", "subproject": ".", "level": 2, "reason": "required checks seen"}]
        text = render.render(findings, sample_score())
        evidence = text[text.index("## Evidence"):text.index("## Not checked")]
        self.assertIn("**Lint and formatting**", evidence)
        self.assertIn("**Tests**", evidence)
        self.assertIn("`a/tests`", evidence)
        self.assertIn("**Secret scanning**", evidence)
        self.assertIn("**CI** — 2 enforced", evidence)
        self.assertIn("Override to level 2: required checks seen", evidence)
        self.assertNotIn("Type checking", evidence)
        self.assertNotIn("Coverage", evidence)

    def test_a_row_without_facts_says_what_was_searched(self):
        score = sample_score()
        score["dimensions"][0] = row("lint", 0, "No linter for python.", facts=[])
        text = render.render(sample_findings(), score)
        evidence = text[text.index("## Evidence"):text.index("## Not checked")]
        self.assertIn("**Lint and formatting** — 0 absent\n- Searched: linter configs, package scripts, hooks, CI steps",
                      evidence)

    def test_override_changes_the_scorecard_level(self):
        findings = sample_findings()
        findings["overrides"] = [{"dimension": "lint", "subproject": ".", "level": 3, "reason": "seen in CI log"}]
        self.assertIn("| Lint and formatting | 3 effective |", render.render(findings, sample_score()))

    def test_input_pointers_name_the_stamped_file(self):
        text = render.render(sample_findings(), sample_score())
        self.assertIn("ghfacts-2026-11-10T0930.json#/security_and_analysis = not_visible", text)
        self.assertNotIn("ghfacts.json#", text)

    def test_not_checked_lists_each_item_once_and_dismissed_is_collapsed(self):
        findings = sample_findings()
        findings["not_checked"] = findings["not_checked"] * 2
        score = sample_score()
        score["dismissed"] = [{"id": "x:.:y", "what": "w", "reason": "vendored code", "date": "2026-11-01"}]
        text = render.render(findings, score)
        self.assertEqual(text.count("**structure review**"), 1)
        self.assertIn("To run it: `ask for the review`", text)
        self.assertIn("<details><summary>Dismissed (1)</summary>", text)
        self.assertIn("`x:.:y` — reason: vendored code (2026-11-01)", text)

    def test_nothing_skipped(self):
        findings = sample_findings()
        findings["not_checked"] = []
        self.assertIn("Nothing was skipped.", render.render(findings, sample_score()))

    def test_sample_report_is_short(self):
        text = render.render(sample_findings(), sample_score())
        self.assertLess(len(text.splitlines()), 150)

    def test_pipes_and_backticks_do_not_break_tables_or_fences(self):
        score = sample_score()
        score["dimensions"][0]["summary"] = "a | b"
        findings = sample_findings()
        findings["recommendations"][0]["first_step"]["command"] = "echo ``` | cat"
        findings["recommendations"][0]["first_step"]["verify"] = "echo `x`"
        text = render.render(findings, score)
        self.assertIn("a \\| b", text)
        self.assertIn("````\necho ``` | cat\n````", text)
        self.assertIn("Verify: `echo 'x'`", text)


class SinceLastRun(unittest.TestCase):
    def changed_score(self):
        score = sample_score()
        score["changes"] = {"compared_with": "findings-2026-11-01.json",
                            "dimensions": [{"id": "lint", "subproject": ".", "change": "up", "before": 0, "after": 1},
                                           {"id": "tests", "subproject": ".", "change": "down", "before": 2, "after": 1},
                                           {"id": "ci", "subproject": ".", "change": "same", "before": 3, "after": 3}],
                            "gaps": {"closed": [{"id": "old:.:x", "dimension": "lint", "what": "Old thing"}],
                                     "new": ["g1"], "still_open": ["g2"]}}
        score["regressed"] = [{"id": "g3", "what": "Came back", "reason": "", "date": ""}]
        return score

    def test_section_sits_between_actions_and_scorecard(self):
        text = render.render(sample_findings(), self.changed_score())
        self.assertLess(text.index("## Do these first"), text.index("## Since last run"))
        self.assertLess(text.index("## Since last run"), text.index("## Scorecard"))
        since = text[text.index("## Since last run"):text.index("## Scorecard")]
        self.assertIn("Closed gaps (1)", since)
        self.assertIn("`old:.:x` Old thing", since)
        self.assertIn("New gaps (1)", since)
        self.assertIn("`g1` What 1", since)
        self.assertIn("Regressions: marked done, detected again (1)", since)
        self.assertIn("`g3` Came back", since)
        self.assertIn("lint: 0 → 1 ↑", since)
        self.assertIn("tests: 2 → 1 ↓", since)
        self.assertNotIn("ci:", since)
        self.assertIn("compared with findings-2026-11-01.json", text)

    def test_scorecard_change_column(self):
        rows = card_rows(render.render(sample_findings(), self.changed_score()))
        by = {r.split("|")[1].strip(): r.split("|")[-2].strip() for r in rows}
        self.assertEqual((by["Lint and formatting"], by["Tests"], by["CI"], by["Type checking"]), ("↑", "↓", "=", "—"))
        first = render.render(sample_findings(), sample_score())
        self.assertIn("| Dimension | Level | Summary |\n| --- | --- | --- |", first)
        self.assertNotIn("Change", first)
        self.assertNotIn("| — |", first)

    def test_summary_counts(self):
        out = render.summary(sample_findings(), self.changed_score(), "/x/report.md")
        self.assertIn("Since last run: 1 closed, 1 new, 1 regressed.", out)
        self.assertNotIn("Since last run", render.summary(sample_findings(), sample_score(), "/x/report.md"))


class Validation(unittest.TestCase):
    def check(self, mutate, expect):
        findings = sample_findings()
        mutate(findings)
        with self.assertRaises(render.FindingsError) as caught:
            render.render(findings, sample_score())
        self.assertIn(expect, str(caught.exception))

    def test_first_step_needs_verify(self):
        self.check(lambda f: f["recommendations"][0]["first_step"].update(verify=None),
                   "recommendations[0].first_step.verify")

    def test_first_step_needs_a_snippet_or_a_command(self):
        self.check(lambda f: f["recommendations"][1]["first_step"].update(snippet=None, command=None),
                   "recommendations[1].first_step needs a snippet or a command")
        findings = sample_findings()
        findings["recommendations"][1]["first_step"].update(snippet=None)
        render.render(findings, sample_score())

    def test_prose_is_rejected_but_code_is_not(self):
        self.check(lambda f: f["recommendations"][0]["first_step"].update(
            command="Run the linter. Then fix every error."), "first_step.command is prose")
        self.check(lambda f: f["recommendations"][0]["first_step"].update(
            verify="Check that it passes. Look at the output."), "first_step.verify is prose")
        findings = sample_findings()
        findings["recommendations"][0]["first_step"].update(command="make lint")
        findings["recommendations"][0]["first_step"].update(snippet="Done. Really. Yes /x")
        render.render(findings, sample_score())

    def test_command_is_a_short_block(self):
        self.check(lambda f: f["recommendations"][0]["first_step"].update(command="\n".join(["ls -l"] * 13)),
                   "longer than 12 lines")

    def test_unknown_gap_is_named(self):
        self.check(lambda f: f["recommendations"][2].update(gap="nope:.:x"), "recommendations[2].gap 'nope:.:x'")

    def test_extra_gaps_are_allowed(self):
        findings = sample_findings()
        findings["recommendations"][2]["gap"] = "extra:swallowed-errors"
        render.render(findings, sample_score())

    def test_reorder_reason_is_required_for_a_changed_order(self):
        def swap(f):
            f["recommendations"][0], f["recommendations"][1] = f["recommendations"][1], f["recommendations"][0]
        self.check(swap, "recommendations[0].reorder_reason is required")
        findings = sample_findings()
        findings["recommendations"][0], findings["recommendations"][1] = findings["recommendations"][1], \
            findings["recommendations"][0]
        findings["recommendations"][0]["reorder_reason"] = "quick win first"
        render.render(findings, sample_score())

    def test_skipping_gaps_needs_no_reason(self):
        findings = sample_findings()
        del findings["recommendations"][1]
        render.render(findings, sample_score())

    def test_missing_and_malformed_fields_are_named(self):
        for field in ("repo", "stamp", "headline", "score", "recommendations", "not_checked"):
            self.check(lambda f, field=field: f.pop(field), "missing required field: " + field)
        self.check(lambda f: f.update(schema=1), "schema must be 2")
        self.check(lambda f: f.update(stamp="2026-11-10"), "stamp must look like")
        self.check(lambda f: f["recommendations"][0].update(impact="huge"), "recommendations[0].impact")
        self.check(lambda f: f["recommendations"][0].update(effort="huge"), "recommendations[0].effort")
        self.check(lambda f: f.update(overrides=[{"dimension": "lint", "subproject": ".", "level": 9, "reason": "r"}]),
                   "overrides[0].level")
        self.check(lambda f: f.update(headline="  "), "headline must not be empty")
        self.check(lambda f: f["not_checked"][0].pop("why"), "not_checked[0].why")


def freshness_entry(dimension="secrets", **kw):
    entry = {"dimension": dimension, "tools": ["gitleaks"], "last_data": "2026-10-31",
             "source": "ci:.github/workflows/scan.yml", "age_days": 10, "stale": False, "why": "last data 10 days ago",
             "run": None}
    entry.update(kw)
    return entry


def security_text(text, heading="## Security data"):
    start = text.index(heading)
    return text[start:text.index("\n## ", start + 4)]


class SecurityData(unittest.TestCase):
    def test_no_entries_no_section_and_share_unchanged(self):
        self.assertNotIn("Security data", render.render(sample_findings(), sample_score()))
        score = sample_score()
        score["security_freshness"] = []
        self.assertEqual(render.share(sample_findings(), score), render.share(sample_findings(), sample_score()))

    def test_section_lists_fresh_and_stale_entries_after_the_scorecard(self):
        score = sample_score()
        score["security_freshness"] = [
            freshness_entry("static", tools=["bandit"], last_data=None, source=None, age_days=None, stale=True),
            freshness_entry("secrets"),
            freshness_entry("deps", tools=["pip-audit"], age_days=45, last_data="2026-09-26", source="ci:.github/workflows/audit.yml",
                            stale=True)]
        text = render.render(sample_findings(), score)
        self.assertLess(text.index("## Scorecard"), text.index("## Security data"))
        self.assertLess(text.index("## Security data"), text.index("## More recommendations"))
        section = security_text(text)
        self.assertIn("| Static analysis and security | bandit | — | — | stale (no run date visible) |", section)
        self.assertIn("| Secret scanning | gitleaks | 2026-10-31 (ci:.github/workflows/scan.yml) | 10 days | fresh |",
                      section)
        self.assertIn("| Dependencies | pip-audit | 2026-09-26 (ci:.github/workflows/audit.yml) | 45 days | stale (older than 30 days) |",
                      section)

    def test_a_tier1_run_shows_its_counts(self):
        score = sample_score()
        score["security_freshness"] = [freshness_entry(source="tier1", age_days=0, last_data="2026-11-10", run={
            "tools": ["gitleaks"], "high": 1, "critical": 2, "findings": 7, "ran_at": "2026-11-10"})]
        self.assertIn("- Secret scanning ran 2026-11-10: 1 high, 2 critical, 7 findings (gitleaks)",
                      security_text(render.render(sample_findings(), score)))

    def test_github_continuous_scanning_is_fresh_without_a_date(self):
        score = sample_score()
        score["security_freshness"] = [freshness_entry(tools=["github-secret-scanning"], last_data=None, source=None,
                                                       age_days=None)]
        self.assertIn("| — | — | fresh (continuous) |", security_text(render.render(sample_findings(), score)))

    def test_share_gets_one_line_only_when_an_entry_is_stale(self):
        score = sample_score()
        score["security_freshness"] = [freshness_entry()]
        self.assertNotIn("Security data", render.share(sample_findings(), score))
        score["security_freshness"] = [freshness_entry(), freshness_entry("deps", age_days=45, stale=True),
                                       freshness_entry("static", age_days=60, stale=True)]
        text = render.share(sample_findings(), score)
        self.assertEqual(text.count("Security data"), 1)
        self.assertIn("Security data is 60 days old: rerun with consent", text)
        self.assertLessEqual(len(text.splitlines()), 15)
        score["security_freshness"] = [freshness_entry(last_data=None, source=None, age_days=None, stale=True)]
        self.assertIn("Security data has no visible run date: rerun with consent",
                      render.share(sample_findings(), score))

    def test_chinese_report_and_share_have_no_english_labels(self):
        findings = sample_findings()
        findings["lang"] = "zh"
        score = sample_score()
        score["security_freshness"] = [freshness_entry(), freshness_entry("deps", age_days=45, stale=True)]
        section = security_text(render.render(findings, score), "## 安全数据")
        for word in ("## 安全数据", "| 检查 | 工具 | 最近数据 | 距今 | 状态 |", "10 天", "新 |", "过期 (超过 30 天)"):
            self.assertIn(word, section)
        for english in ("Security data", "fresh", "stale", "days", "Tools"):
            self.assertNotIn(english, section)
        self.assertIn("安全数据已过期 45 天：征得同意后重新运行", render.share(findings, score))


class Chinese(unittest.TestCase):
    def test_zh_has_no_english_headings_or_labels(self):
        findings = sample_findings()
        findings["lang"] = "zh-CN"
        score = sample_score()
        score["changes"] = SinceLastRun().changed_score()["changes"]
        score["dismissed"] = [{"id": "x", "what": "w", "reason": "r", "date": "d"}]
        text = render.render(findings, score)
        for heading in ("# 仓库健康报告：demo", "提交：`0123456789ab`", "## 优先行动", "## 自上次运行", "## 计分表",
                        "## 更多建议", "## 热点", "## 证据", "## 未检查", "验证：", "原因：", "已忽略"):
            self.assertIn(heading, text)
        self.assertIn("| 测试 | 1 有配置 (部分：2/4 个测试套件) |", text)
        self.assertIn("| 密钥扫描 | 未知（需要：GitHub secret-scanning setting） |", text)
        self.assertIn("| 覆盖率 | 不适用 | 中文摘要：coverage |", text)
        self.assertIn("| Lint 与格式化 | 1 有配置 | 中文摘要：lint | ↑ |", text)
        self.assertNotIn("a summary", text)
        self.assertNotIn("Linter configured", text)
        self.assertIn("已查找：", render.render(findings, dict(score, dimensions=[row("lint", 0, "x", facts=[])])))
        for english in ("Do these first", "Scorecard", "Since last run", "Verify:", "Hotspots", "Evidence",
                        "Not checked", "More recommendations", "Dismissed", "enforced", "Why:"):
            self.assertNotIn(english, text)
        out = render.summary(findings, score, "/x/report.md")
        self.assertIn("优先行动：", out)
        self.assertIn("自上次运行：关闭 1，新增 1，回退 0。", out)
        self.assertTrue(out.rstrip().endswith("报告：/x/report.md"))
        self.assertIn("计分：", render.share(findings, score))

    def test_other_languages_fall_back_to_english(self):
        findings = sample_findings()
        findings["lang"] = "fr"
        self.assertIn("## Do these first", render.render(findings, sample_score()))


class Share(unittest.TestCase):
    def test_share_is_short_and_useful(self):
        text = render.share(sample_findings(), sample_score())
        lines = text.splitlines()
        self.assertLessEqual(len(lines), 15)
        self.assertTrue(lines[0].startswith("**Tests run in CI"))
        self.assertIn("Scorecard: lint 1 · types 2 · secrets ? · tests 1 · ci 3", text)
        self.assertNotIn("coverage", text)
        self.assertEqual(len([l for l in lines if re.match(r"^\d\. ", l)]), 3)
        self.assertIn("1. Title g1 — `uvx ruff check .`", text)

    def test_share_stays_short_with_many_dimensions_and_recommendations(self):
        score = sample_score()
        score["dimensions"] += [row(d, 0) for d in ("static", "setup", "docs", "deps", "arch")]
        self.assertLessEqual(len(render.share(sample_findings(20), score).splitlines()), 15)


class Terminal(unittest.TestCase):
    def test_summary_has_headline_top_five_and_report_path(self):
        out = render.summary(sample_findings(), sample_score(), "/x/report.md")
        self.assertTrue(out.startswith("Tests run in CI"))
        self.assertEqual(len(re.findall(r"^\d\. ", out, re.M)), 5)
        self.assertIn("   first step: uvx ruff check .", out)
        self.assertTrue(out.rstrip().endswith("Report: /x/report.md"))


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="rh-render-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def save(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "w") as handle:
            if isinstance(data, str):
                handle.write(data)
            else:
                json.dump(data, handle)
        return path

    def findings(self, stamp):
        data = sample_findings()
        data["stamp"] = stamp
        data["score"] = "score-%s.json" % stamp
        return data

    def test_previous_is_the_newest_older_stamp_including_old_date_only_names(self):
        self.save("findings-2026-11-01.json", {"schema": 1, "dimensions": []})
        self.save("findings-2026-11-10T0800.json", self.findings("2026-11-10T0800"))
        self.save("findings-2026-11-10T1500.json", self.findings("2026-11-10T1500"))
        self.save("other.json", {"dimensions": []})
        current = self.save("findings-2026-11-10T0930.json", self.findings("2026-11-10T0930"))
        path, data, stamp = render.find_previous(current, self.findings("2026-11-10T0930"))
        self.assertEqual((os.path.basename(path), stamp), ("findings-2026-11-10T0800.json", "2026-11-10T0800"))
        os.remove(path)
        path, data, stamp = render.find_previous(current, self.findings("2026-11-10T0930"))
        self.assertEqual(stamp, "2026-11-01")

    def test_a_date_only_name_is_older_than_a_stamp_of_the_same_day(self):
        self.save("findings-2026-11-10.json", {"schema": 1, "dimensions": []})
        current = self.save("findings-2026-11-10T0930.json", self.findings("2026-11-10T0930"))
        self.assertEqual(render.find_previous(current, self.findings("2026-11-10T0930"))[2], "2026-11-10")

    def test_broken_older_file_is_skipped_and_none_when_alone(self):
        self.save("findings-2026-11-01.json", {"schema": 1, "dimensions": []})
        self.save("findings-2026-11-05.json", "{not json")
        current = self.save("findings-2026-11-10T0930.json", self.findings("2026-11-10T0930"))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            found = render.find_previous(current, self.findings("2026-11-10T0930"))
        self.assertEqual(found[2], "2026-11-01")
        self.assertIn("findings-2026-11-05.json", err.getvalue())
        os.remove(os.path.join(self.dir, "findings-2026-11-01.json"))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(render.find_previous(current, self.findings("2026-11-10T0930")))

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, cwd=self.dir)

    def test_cli_writes_report_and_share_beside_the_input(self):
        self.save("score-2026-11-10T0930.json", sample_score())
        path = self.save("findings-2026-11-10T0930.json", self.findings("2026-11-10T0930"))
        done = self.run_cli(path)
        self.assertEqual(done.returncode, 0, done.stderr)
        report = os.path.join(self.dir, "report-2026-11-10T0930.md")
        share = os.path.join(self.dir, "share-2026-11-10T0930.md")
        self.assertTrue(os.path.exists(report) and os.path.exists(share))
        self.assertTrue(done.stdout.rstrip().endswith("Report: " + os.path.realpath(report))
                        or done.stdout.rstrip().endswith("Report: " + report))
        with open(share) as handle:
            self.assertLessEqual(len(handle.read().splitlines()), 15)
        done = self.run_cli(path, "-o", os.path.join(self.dir, "x", "r.md"), "--share", os.path.join(self.dir, "s.md"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "x", "r.md")))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "s.md")))

    def test_cli_compares_with_a_schema_1_run_by_levels_only(self):
        old = {"schema": 1, "date": "2026-11-01", "dimensions": [
            {"id": "lint", "subproject": ".", "level": 0}, {"id": "tests", "subproject": ".", "level": 2}]}
        self.save("findings-2026-11-01.json", old)
        self.save("score-2026-11-10T0930.json", sample_score())
        path = self.save("findings-2026-11-10T0930.json", self.findings("2026-11-10T0930"))
        done = self.run_cli(path)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(os.path.join(self.dir, "report-2026-11-10T0930.md")) as handle:
            text = handle.read()
        self.assertIn("compared with 2026-11-01", text)
        self.assertIn("lint: 0 → 1 ↑", text)
        self.assertIn("Gap changes are not available", text)
        self.assertNotIn("Since last run:", done.stdout)

    def test_cli_compares_with_a_schema_2_run_through_its_score(self):
        old_score = sample_score()
        old_score["gaps"] = [gap("gone:.:x", what="Gone one")]
        old_score["dimensions"][0] = row("lint", 0, "No linter.")
        self.save("score-2026-11-09T1000.json", old_score)
        self.save("findings-2026-11-09T1000.json", self.findings("2026-11-09T1000"))
        self.save("score-2026-11-10T0930.json", sample_score())
        path = self.save("findings-2026-11-10T0930.json", self.findings("2026-11-10T0930"))
        done = self.run_cli(path)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Since last run: 1 closed, 7 new, 0 regressed.", done.stdout)

    def test_cli_error_names_the_field(self):
        self.save("score-2026-11-10T0930.json", sample_score())
        data = self.findings("2026-11-10T0930")
        data["recommendations"][0]["first_step"]["verify"] = ""
        path = self.save("findings-2026-11-10T0930.json", data)
        done = self.run_cli(path)
        self.assertEqual(done.returncode, 2)
        self.assertIn("recommendations[0].first_step.verify", done.stderr)

    def test_cli_rejects_missing_score_schema_1_and_bad_json(self):
        path = self.save("findings-2026-11-10T0930.json", self.findings("2026-11-10T0930"))
        self.assertEqual(self.run_cli(path).returncode, 2)
        self.assertEqual(self.run_cli(self.save("old.json", {"schema": 1})).returncode, 2)
        self.assertEqual(self.run_cli(self.save("bad.json", "{nope")).returncode, 2)
        self.assertEqual(self.run_cli(os.path.join(self.dir, "missing.json")).returncode, 2)

    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))


if __name__ == "__main__":
    unittest.main()
