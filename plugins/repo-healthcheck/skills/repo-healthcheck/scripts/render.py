#!/usr/bin/env python3
"""Render a repo-healthcheck findings.json (schema 2) and its score.json as a Markdown report.

    render.py findings.json [-o report.md] [--share share.md] [--previous OLD.json | --no-previous]

Writes the report (default report-<stamp>.md beside the input), a share file of at
most 15 lines for a pull request or chat (default share-<stamp>.md beside the input),
then prints a terminal summary: the headline, the top five actions with their first
command, the "since last run" counts and the absolute report path. Standard library
only; Python 3.9+.

render.py lays out; it does not judge. Levels, gaps, the profile, hotspots and changes
come from the score.json that findings["score"] names (beside the findings file); the
model writes the headline, the recommendations, overrides and reviews.

findings.json, schema 2 (an error names the field):

    schema 2, repo, stamp (YYYY-MM-DDTHHMM, local time), headline, score (file name),
    recommendations[], not_checked[]
    optional: lang (zh or en), commit, inputs {detect, hotspots, ghfacts: file names},
              overrides[] {dimension, subproject, level 0-3, reason}, reviews {}
    recommendations[]  {gap, title, why, impact high|medium|low, effort small|medium|large,
                        first_step {file, snippet, command, verify}, reorder_reason}
                       gap is a gap id of score.json, or "extra:<slug>" for a tier 2 finding.
    not_checked[]      {what, why, how_to_run?}

Validation
    * first_step needs `verify` and a `snippet` or a `command`.
    * A first_step text (snippet, command, verify) that is prose is rejected: more than one
      sentence (two or more of . ! ? followed by space or the end) and none of the code
      characters ` $ | = / { } ( ) < >. A command is at most 12 lines.
    * Every `gap` exists in score.json (or starts with "extra:").
    * The order of recommendations follows the gaps' priority order in score.json. A
      recommendation placed above one with a higher-priority gap needs `reorder_reason`.

Previous runs: the newest findings-<stamp>.json older than this one beside it (an old
findings-YYYY-MM-DD.json counts; schema 1 files give level changes only, no gap changes).
The score.json `changes` block (made with score.py --previous) wins when present.
A "Security data" section after the scorecard lists score.json's security_freshness (tools, last
data and source, age, fresh or stale, and the counts of a tier 1 security run). share.md gets one
line only when an entry is stale. In a zh report the scorecard uses summary_zh of score.json. The Change column is left out
on a first run (no previous run).
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score as scoring  # noqa: E402  (changes_between for a previous run without a changes block)

DIMENSIONS = [("lint", "Lint and formatting"), ("types", "Type checking"), ("static", "Static analysis and security"),
              ("secrets", "Secret scanning"), ("tests", "Tests"), ("coverage", "Coverage"), ("ci", "CI"),
              ("setup", "Setup and reproducibility"), ("docs", "Docs"), ("deps", "Dependencies"),
              ("arch", "Architecture")]
DIMENSION_ORDER = {key: i for i, (key, _n) in enumerate(DIMENSIONS)}
NAMES = dict(DIMENSIONS)
LEVEL_NAMES = {0: "absent", 1: "present", 2: "enforced", 3: "effective"}

TEXT = {
    "en": {
        "title": "# Repo healthcheck report: %s", "commit": "Commit: `%s`", "date": "Date: %s",
        "compared": "compared with %s", "first": "## Do these first", "no_recs": "No recommendations.",
        "why": "Why: %s", "verify": "Verify: `%s`", "touches": "Touches hotspots: %s",
        "since": "## Since last run", "closed": "Closed gaps (%d)", "new": "New gaps (%d)",
        "regressed": "Regressions: marked done, detected again (%d)", "levels_changed": "Level changes (%d)",
        "nothing": "none", "scorecard": "## Scorecard", "table": "| Dimension | Level | Summary | Change |",
        "legend": "Levels: 0 absent, 1 present, 2 enforced, 3 effective. unknown: a fact is not visible, "
                  "the level is not guessed. n/a: does not apply to this repository.",
        "more": "## More recommendations", "hotspots": "## Hotspots",
        "hot_table": "| File | Commits | LOC | Tests in CI | Top author |", "evidence": "## Evidence",
        "override": "Override to level %s: %s", "not_checked": "## Not checked", "to_run": " To run it: `%s`",
        "none_skipped": "Nothing was skipped.", "dismissed": "Dismissed", "reason": "reason",
        "levels": LEVEL_NAMES, "unknown": "unknown (needs: %s)", "na": "n/a", "partial": "partial: %d of %d %s",
        "searched": "Searched: %s",
        "searched_in": {"lint": "linter configs, package scripts, hooks, CI steps",
                        "types": "type checker configs, package scripts, CI steps",
                        "static": "security analysis configs, CI steps, GitHub settings",
                        "secrets": "scanner configs, CI steps, GitHub settings",
                        "tests": "test files and CI steps", "coverage": "coverage configs and CI steps",
                        "ci": "CI workflow files", "setup": "lockfiles, toolchain pins, task runners",
                        "docs": "README and CONTRIBUTING", "deps": "lockfiles, update bot configs, CI audits",
                        "arch": "architecture docs and rule tool configs"},
        "units": {}, "yes": "yes", "no": "no", "unk": "unknown", "new_row": "new", "names": {},
        "summary_first": "Do these first:", "summary_cmd": "   first step: %s", "report": "Report: %s",
        "summary_since": "Since last run: %d closed, %d new, %d regressed.", "share_first": "Do first:",
        "share_card": "Scorecard: %s",
        "security": "## Security data",
        "security_table": "| Check | Tools | Last data | Age | State |",
        "security_note": "Security tools are checked by config, CI rows and GitHub settings. Data older than %d days, "
                         "or with no visible run date, is stale: the skill runs the tools only if you agree.",
        "age": "%d days", "fresh": "fresh", "stale": "stale", "continuous": "continuous",
        "why_old": "older than %d days", "why_none": "no run date visible",
        "security_run": "%s ran %s: %d high, %d critical, %d findings (%s)",
        "share_stale": "Security data is %d days old: rerun with consent",
        "share_no_date": "Security data has no visible run date: rerun with consent",
        "no_gaps_note": "Gap changes are not available: the previous run has no score file.",
    },
    "zh": {
        "title": "# 仓库健康报告：%s", "commit": "提交：`%s`", "date": "日期：%s", "compared": "对比 %s",
        "first": "## 优先行动", "no_recs": "没有建议。", "why": "原因：%s", "verify": "验证：`%s`",
        "touches": "涉及热点：%s", "since": "## 自上次运行", "closed": "已关闭的缺口（%d）",
        "new": "新增缺口（%d）", "regressed": "回退：标记为完成但再次检出（%d）", "levels_changed": "等级变化（%d）",
        "nothing": "无", "scorecard": "## 计分表", "table": "| 维度 | 等级 | 摘要 | 变化 |",
        "legend": "等级：0 没有，1 有配置，2 强制，3 有效。未知：看不到判定所需的事实，不猜等级。n/a：不适用于本仓库。",
        "more": "## 更多建议", "hotspots": "## 热点", "hot_table": "| 文件 | 提交数 | 行数 | CI 跑测试 | 最大作者占比 |",
        "evidence": "## 证据", "override": "改为等级 %s：%s", "not_checked": "## 未检查", "to_run": " 运行方法：`%s`",
        "none_skipped": "没有跳过任何项。", "dismissed": "已忽略", "reason": "原因",
        "levels": {0: "没有", 1: "有配置", 2: "强制", 3: "有效"}, "unknown": "未知（需要：%s）", "na": "不适用",
        "partial": "部分：%d/%d %s", "units": {"test suites": "个测试套件", "languages": "种语言", "ecosystems": "个生态"},
        "searched": "已查找：%s",
        "searched_in": {"lint": "linter 配置、包脚本、钩子、CI 步骤", "types": "类型检查配置、包脚本、CI 步骤",
                        "static": "安全分析配置、CI 步骤、GitHub 设置", "secrets": "扫描器配置、CI 步骤、GitHub 设置",
                        "tests": "测试文件和 CI 步骤", "coverage": "覆盖率配置和 CI 步骤", "ci": "CI 工作流文件",
                        "setup": "锁文件、工具链版本固定、任务运行器", "docs": "README 和 CONTRIBUTING",
                        "deps": "锁文件、更新机器人配置、CI 审计", "arch": "架构文档和规则工具配置"},
        "yes": "是", "no": "否", "unk": "未知", "new_row": "新",
        "names": {"lint": "Lint 与格式化", "types": "类型检查", "static": "静态分析与安全", "secrets": "密钥扫描",
                  "tests": "测试", "coverage": "覆盖率", "ci": "CI", "setup": "环境搭建与可复现", "docs": "文档",
                  "deps": "依赖", "arch": "架构"},
        "summary_first": "优先行动：", "summary_cmd": "   第一步：%s", "report": "报告：%s",
        "summary_since": "自上次运行：关闭 %d，新增 %d，回退 %d。", "share_first": "先做：",
        "share_card": "计分：%s",
        "security": "## 安全数据",
        "security_table": "| 检查 | 工具 | 最近数据 | 距今 | 状态 |",
        "security_note": "安全工具只按配置、CI 行和 GitHub 设置检查。数据超过 %d 天，或看不到运行日期，即为过期："
                         "只有你同意，才会运行这些工具。",
        "age": "%d 天", "fresh": "新", "stale": "过期", "continuous": "持续扫描",
        "why_old": "超过 %d 天", "why_none": "看不到运行日期",
        "security_run": "%s 于 %s 运行：高危 %d，严重 %d，共 %d 条（%s）",
        "share_stale": "安全数据已过期 %d 天：征得同意后重新运行",
        "share_no_date": "安全数据看不到运行日期：征得同意后重新运行",
        "no_gaps_note": "无法比较缺口：上次运行没有 score 文件。",
    },
}

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{4}$")
FINDINGS_NAME = re.compile(r"^findings-(\d{4}-\d{2}-\d{2}(?:T\d{4})?).*\.json$")
IMPACT = ("high", "medium", "low")
EFFORT = ("small", "medium", "large")
TOP = 5
MAX_COMMAND_LINES = 12
SHARE_LINES = 15
CODE_CHARS = set("`$|=/{}()<>")
HOTSPOT_ROWS = 10


class FindingsError(ValueError):
    """The findings file is not valid; the message names the field."""


def text_for(findings):
    lang = findings.get("lang") if isinstance(findings, dict) else None
    return TEXT["zh"] if isinstance(lang, str) and lang.lower().startswith("zh") else TEXT["en"]


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _require(obj, field, where, kind=None):
    prefix = where + "." if where else ""
    if not isinstance(obj, dict):
        raise FindingsError("%s must be an object" % (where or "findings"))
    if field not in obj or obj[field] is None:
        raise FindingsError("missing required field: %s%s" % (prefix, field))
    if kind is not None and not isinstance(obj[field], kind):
        raise FindingsError("%s%s must be %s" % (prefix, field, kind.__name__))
    return obj[field]


def is_prose(text):
    """More than one sentence and no code characters."""
    sentences = len(re.findall(r"[.!?。！？](?:\s|$)", text.strip()))
    return sentences > 1 and not (CODE_CHARS & set(text))


def validate(findings, gap_order=None):
    """Raise FindingsError for the first problem. gap_order maps gap id to its priority index."""
    if not isinstance(findings, dict):
        raise FindingsError("findings must be a JSON object")
    if _require(findings, "schema", "") != 2:
        raise FindingsError("schema must be 2, got %r" % (findings["schema"],))
    _require(findings, "repo", "", str)
    if not STAMP.match(_require(findings, "stamp", "", str)):
        raise FindingsError("stamp must look like 2026-11-10T0930, got %r" % findings["stamp"])
    if not _require(findings, "headline", "", str).strip():
        raise FindingsError("headline must not be empty")
    _require(findings, "score", "", str)
    recs = _require(findings, "recommendations", "", list)
    not_checked = _require(findings, "not_checked", "", list)
    for i, item in enumerate(findings.get("overrides") or []):
        where = "overrides[%d]" % i
        _require(item, "dimension", where, str)
        _require(item, "subproject", where, str)
        _require(item, "reason", where, str)
        level = _require(item, "level", where)
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 3:
            raise FindingsError("%s.level must be an integer 0-3, got %r" % (where, level))
    for i, rec in enumerate(recs):
        where = "recommendations[%d]" % i
        gap = _require(rec, "gap", where, str)
        _require(rec, "title", where, str)
        _require(rec, "why", where, str)
        if _require(rec, "impact", where, str) not in IMPACT:
            raise FindingsError("%s.impact must be one of %s" % (where, "|".join(IMPACT)))
        if _require(rec, "effort", where, str) not in EFFORT:
            raise FindingsError("%s.effort must be one of %s" % (where, "|".join(EFFORT)))
        step = _require(rec, "first_step", where, dict)
        w = where + ".first_step"
        for field in ("file", "snippet", "command", "verify"):
            if step.get(field) is not None and not isinstance(step[field], str):
                raise FindingsError("%s.%s must be text or null" % (w, field))
        if not (step.get("verify") or "").strip():
            raise FindingsError("%s.verify is required: a command whose output proves it worked" % w)
        if not ((step.get("snippet") or "").strip() or (step.get("command") or "").strip()):
            raise FindingsError("%s needs a snippet or a command" % w)
        for field in ("snippet", "command", "verify"):
            if step.get(field) and is_prose(step[field]):
                raise FindingsError("%s.%s is prose, not code or a command" % (w, field))
        if len((step.get("command") or "").strip().splitlines()) > MAX_COMMAND_LINES:
            raise FindingsError("%s.command is longer than %d lines" % (w, MAX_COMMAND_LINES))
        if gap_order is not None and not gap.startswith("extra:") and gap not in gap_order:
            raise FindingsError("%s.gap %r is not a gap of score.json" % (where, gap))
    for i, item in enumerate(not_checked):
        where = "not_checked[%d]" % i
        _require(item, "what", where, str)
        _require(item, "why", where, str)
    if gap_order is not None:
        indexes = [gap_order.get(r["gap"]) for r in recs]
        for i, rec in enumerate(recs):
            if indexes[i] is None:
                continue
            later_higher = any(j is not None and j < indexes[i] for j in indexes[i + 1:])
            if later_higher and not (rec.get("reorder_reason") or "").strip():
                raise FindingsError("recommendations[%d].reorder_reason is required: it is placed above a "
                                    "recommendation with a higher-priority gap" % i)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def cell(text):
    return re.sub(r"\s+", " ", str(text)).replace("|", "\\|").strip()


def fence(text):
    longest = max([len(m) for m in re.findall(r"`+", text)] or [0])
    ticks = "`" * max(3, longest + 1)
    return "%s\n%s\n%s" % (ticks, text.strip("\n"), ticks)


def dimension_name(dim_id, t):
    return t["names"].get(dim_id) or NAMES.get(dim_id, dim_id)


def first_command(rec):
    step = rec["first_step"]
    command = (step.get("command") or "").strip()
    if command:
        return command.splitlines()[0]
    return (step.get("file") or (step.get("snippet") or "").strip().splitlines()[0]).strip()


def pointer_names(findings):
    inputs = findings.get("inputs") or {}
    return {key: inputs[key] for key in ("detect", "hotspots", "ghfacts") if isinstance(inputs.get(key), str)}


def real_fact(fact, names):
    for key, name in names.items():
        fact = fact.replace("%s.json#" % key, "%s#" % name)
    return fact


def effective_rows(score, findings):
    """Dimension rows with overrides applied: [(row, level, override or None)]."""
    overrides = {(o["dimension"], o["subproject"]): o for o in findings.get("overrides") or []}
    out = []
    for row in score["dimensions"]:
        override = overrides.get((row["id"], row["subproject"]))
        out.append((row, override["level"] if override else row["level"], override))
    out.sort(key=lambda p: (DIMENSION_ORDER.get(p[0]["id"], 99), p[0]["subproject"]))
    return out


def level_text(row, level, t):
    if row["status"] == "not_applicable":
        return t["na"]
    if level is None:
        return t["unknown"] % (row.get("needs") or "?")
    text = "%d %s" % (level, t["levels"][level])
    partial = row.get("partial")
    if partial and level == row["level"]:
        text += " (%s)" % (t["partial"] % (partial["covered"], partial["total"],
                                           t["units"].get(partial.get("unit"), partial.get("unit", ""))))
    return text


def security_state(entry, t):
    if not entry.get("stale"):
        return t["fresh"] + (" (%s)" % t["continuous"] if entry.get("last_data") is None else "")
    why = t["why_none"] if entry.get("age_days") is None else t["why_old"] % scoring.SECURITY_STALE_DAYS
    return "%s (%s)" % (t["stale"], why)


def security_section(score, t):
    entries = score.get("security_freshness") or []
    if not entries:
        return []
    out = [t["security"], "", t["security_note"] % scoring.SECURITY_STALE_DAYS, "", t["security_table"],
           "| --- | --- | --- | --- | --- |"]
    for entry in entries:
        last = "%s (%s)" % (entry["last_data"], entry["source"]) if entry.get("last_data") else "—"
        age = t["age"] % entry["age_days"] if entry.get("age_days") is not None else "—"
        out.append("| %s | %s | %s | %s | %s |" % (
            cell(dimension_name(entry["dimension"], t)), cell(", ".join(entry.get("tools") or [])), cell(last), age,
            cell(security_state(entry, t))))
    for entry in entries:
        run = entry.get("run")
        if run:
            out += ["", "- " + t["security_run"] % (dimension_name(entry["dimension"], t), run["ran_at"], run["high"],
                                                    run["critical"], run["findings"], ", ".join(run["tools"]))]
    return out + [""]


def changes_text(change, t):
    return {"up": "↑", "down": "↓", "same": "=", "new": t["new_row"], "changed": "~"}.get(change, "—")


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def rec_block(number, rec, gaps, t):
    gap = gaps.get(rec["gap"])
    step = rec["first_step"]
    label = "" if rec["gap"].startswith("extra:") else " (`%s`)" % rec["gap"]
    out = ["### %d. %s%s" % (number, rec["title"].strip(), label)]
    out += ["", t["why"] % rec["why"].strip(), ""]
    if step.get("file"):
        out += ["`%s`" % step["file"], ""]
    if (step.get("snippet") or "").strip():
        out += [fence(step["snippet"]), ""]
    if (step.get("command") or "").strip():
        out += [fence(step["command"]), ""]
    out += [t["verify"] % step["verify"].strip().replace("`", "'"), ""]
    files = (gap or {}).get("hotspot_files") or []
    if files:
        out += [t["touches"] % ", ".join("`%s`" % f for f in files[:3]), ""]
    return out


def since_section(changes, score, t):
    gaps_now = {g["id"]: g for g in score["gaps"]}
    out = [t["since"], ""]
    if changes.get("gaps") is not None:
        gaps = changes["gaps"]
        for label, items in ((t["closed"], [(g["id"], g["what"]) for g in gaps["closed"]]),
                             (t["new"], [(i, gaps_now[i]["what"]) for i in gaps["new"] if i in gaps_now])):
            out.append("- %s: %s" % (label % len(items), "" if items else t["nothing"]))
            out += ["  - `%s` %s" % (i, w) for i, w in items]
        out.append("- %s: %s" % (t["regressed"] % len(score["regressed"]), "" if score["regressed"] else t["nothing"]))
        out += ["  - `%s` %s" % (g["id"], g["what"]) for g in score["regressed"]]
    else:
        out.append("- %s" % t["no_gaps_note"])
    moved = [c for c in changes["dimensions"] if c["change"] in ("up", "down")]
    out.append("- %s: %s" % (t["levels_changed"] % len(moved), "" if moved else t["nothing"]))
    out += ["  - %s%s: %s → %s %s" % (c["id"], "" if c["subproject"] == "." else " (%s)" % c["subproject"],
                                       c["before"], c["after"], changes_text(c["change"], t)) for c in moved]
    return out + [""]


def render(findings, score, previous_changes=None, compared=None):
    """The report, as Markdown. previous_changes overrides score["changes"] when given."""
    gap_order = {g["id"]: i for i, g in enumerate(score["gaps"])}
    validate(findings, gap_order)
    t = text_for(findings)
    names = pointer_names(findings)
    gaps = {g["id"]: g for g in score["gaps"]}
    changes = score.get("changes") or previous_changes
    if changes and not compared:
        compared = changes.get("compared_with")
    stamp = findings["stamp"]
    meta = []
    if findings.get("commit"):
        meta.append(t["commit"] % str(findings["commit"])[:12])
    meta.append(t["date"] % stamp[:10])
    if changes and compared:
        meta.append(t["compared"] % compared)
    out = [t["title"] % findings["repo"], "", " · ".join(meta), "", "**%s**" % findings["headline"].strip(), ""]
    recs = findings["recommendations"]
    out += [t["first"], ""]
    if recs:
        for number, rec in enumerate(recs[:TOP], 1):
            out += rec_block(number, rec, gaps, t)
    else:
        out += [t["no_recs"], ""]
    if changes:
        out += since_section(changes, score, t)

    rows = effective_rows(score, findings)
    change_of = {(c["id"], c["subproject"]): c["change"] for c in (changes or {}).get("dimensions", [])}
    several = len({r["subproject"] for r, _l, _o in rows}) > 1
    table_head = t["table"] if changes else t["table"].rsplit(" | ", 1)[0] + " |"
    out += [t["scorecard"], "", table_head, "| --- | --- | --- |" + (" --- |" if changes else "")]
    for row, level, override in rows:
        label = dimension_name(row["id"], t)
        if several and row["subproject"] != ".":
            label += " (%s)" % row["subproject"]
        shown = level_text(row, level, t)
        text = (row.get("summary_zh") or row["summary"]) if t is TEXT["zh"] else row["summary"]
        if changes:
            change = changes_text(change_of.get((row["id"], row["subproject"])), t)
            out.append("| %s | %s | %s | %s |" % (cell(label), cell(shown), cell(text), change))
        else:
            out.append("| %s | %s | %s |" % (cell(label), cell(shown), cell(text)))
    out += ["", t["legend"], ""]
    out += security_section(score, t)

    if len(recs) > TOP:
        out += [t["more"], ""]
        for rec in recs[TOP:]:
            out.append("- %s (`%s`) — `%s`" % (rec["title"].strip(), rec["gap"], first_command(rec).replace("`", "'")))
        out.append("")

    table = score.get("hotspots") or []
    if table:
        out += [t["hotspots"], "", t["hot_table"], "| --- | --- | --- | --- | --- |"]
        for item in table[:HOTSPOT_ROWS]:
            ci = {True: t["yes"], False: t["no"]}.get(item["tests_in_ci"], t["unk"])
            share = "%d%%" % round(item["top_author_share"] * 100) if item.get("top_author_share") is not None else "—"
            out.append("| %s | %s | %s | %s | %s |" % (cell(item["path"]), item.get("commits", "—"),
                                                       item.get("loc", "—"), ci, share))
        out.append("")

    evidence = [(r, lv, o) for r, lv, o in rows if r["status"] != "not_applicable" and
                (lv is None or lv < 2 or r.get("partial") or o)]
    if evidence:
        out += [t["evidence"], ""]
        for row, level, override in evidence:
            label = dimension_name(row["id"], t) + ("" if row["subproject"] == "." else " (%s)" % row["subproject"])
            out.append("**%s** — %s" % (label, level_text(row, level, t)))
            if override:
                out.append("- " + t["override"] % (override["level"], override["reason"].strip()))
            partial = row.get("partial")
            if partial and partial.get("missing"):
                out.append("- %s" % ", ".join("`%s`" % m for m in partial["missing"][:6]))
            out += ["- " + real_fact(f, names) for f in row["facts"][:5]]
            if not row["facts"] and not (partial and partial.get("missing")) and not override:
                out.append("- " + t["searched"] % t["searched_in"].get(row["id"], row["id"]))
            out.append("")

    out += [t["not_checked"], ""]
    seen = set()
    shown = 0
    for item in findings["not_checked"]:
        key = item["what"].strip()
        if key in seen:
            continue
        seen.add(key)
        why = item["why"].strip()
        if why and why[-1] not in ".!?。！？":
            why += "."
        line = "- **%s** — %s" % (key, why)
        if item.get("how_to_run"):
            line += t["to_run"] % item["how_to_run"].strip().replace("`", "'")
        out.append(line)
        shown += 1
    if not shown:
        out.append(t["none_skipped"])
    out.append("")
    if score["dismissed"]:
        out += ["<details><summary>%s (%d)</summary>" % (t["dismissed"], len(score["dismissed"])), ""]
        out += ["- `%s` — %s: %s (%s)" % (d["id"], t["reason"], d["reason"] or "—", d["date"] or "—")
                for d in score["dismissed"]]
        out += ["", "</details>", ""]
    return "\n".join(out).rstrip("\n") + "\n"


def share(findings, score):
    """At most 15 lines of Markdown for a pull request, issue or chat."""
    t = text_for(findings)
    worst = {}
    for row, level, _o in effective_rows(score, findings):
        if row["status"] == "not_applicable":
            continue
        value = -1 if level is None else level
        worst[row["id"]] = min(worst.get(row["id"], 9), value)
    card = " · ".join("%s %s" % (k, "?" if v < 0 else v) for k, v in sorted(
        worst.items(), key=lambda kv: DIMENSION_ORDER.get(kv[0], 99)))
    lines = ["**%s**" % findings["headline"].strip(), "", t["share_card"] % card]
    stale = [e for e in score.get("security_freshness") or [] if e.get("stale")]
    if stale:
        ages = [e["age_days"] for e in stale if e.get("age_days") is not None]
        lines.append(t["share_stale"] % max(ages) if ages else t["share_no_date"])
    lines += ["", t["share_first"]]
    for number, rec in enumerate(findings["recommendations"][:3], 1):
        lines.append("%d. %s — `%s`" % (number, rec["title"].strip(), first_command(rec).replace("`", "'")))
    return "\n".join(lines[:SHARE_LINES]) + "\n"


def summary(findings, score, report_path=None, changes=None):
    t = text_for(findings)
    lines = [findings["headline"].strip(), ""]
    recs = findings["recommendations"][:TOP]
    if recs:
        lines.append(t["summary_first"])
        for number, rec in enumerate(recs, 1):
            lines += ["%d. %s" % (number, rec["title"].strip()), t["summary_cmd"] % first_command(rec)]
    else:
        lines.append(t["no_recs"])
    changes = changes or score.get("changes")
    if changes and changes.get("gaps") is not None:
        gaps = changes["gaps"]
        lines += ["", t["summary_since"] % (len(gaps["closed"]), len(gaps["new"]), len(score["regressed"]))]
    if report_path:
        lines += ["", t["report"] % report_path]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

def load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        raise FindingsError("cannot read %s: %s" % (path, exc))
    except ValueError as exc:
        raise FindingsError("%s is not valid JSON: %s" % (path, exc))


def current_stamp(path, findings):
    own = FINDINGS_NAME.match(os.path.basename(path))
    return own.group(1) if own else str(findings.get("stamp", ""))


def find_previous(path, findings):
    """(path, data, stamp) of the newest findings file beside `path` that is older, or None."""
    folder = os.path.dirname(os.path.abspath(path))
    current = current_stamp(path, findings)
    candidates = []
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        m = FINDINGS_NAME.match(name)
        if m and m.group(1) < current and os.path.join(folder, name) != os.path.abspath(path):
            candidates.append((m.group(1), name))
    for stamp, name in sorted(candidates, reverse=True):
        full = os.path.join(folder, name)
        try:
            data = load_json(full)
        except FindingsError as exc:
            sys.stderr.write("render.py: skipping %s\n" % exc)
            continue
        if isinstance(data, dict) and (isinstance(data.get("dimensions"), list) or data.get("schema") == 2):
            return full, data, stamp
    return None


def previous_changes(score, previous_path, previous):
    """changes block against an earlier findings file (schema 1: levels only)."""
    folder = os.path.dirname(os.path.abspath(previous_path))
    if previous.get("schema") == 2 and isinstance(previous.get("score"), str):
        old_path = os.path.join(folder, previous["score"])
        if os.path.exists(old_path):
            return scoring.changes_between(score, load_json(old_path), os.path.basename(previous_path))
    old = {"dimensions": [{"id": d.get("id"), "subproject": d.get("subproject", "."), "level": d.get("level"),
                           "summary": "", "facts": []} for d in previous.get("dimensions") or []
                          if isinstance(d, dict)], "gaps": [], "dismissed": []}
    result = scoring.changes_between(score, old, os.path.basename(previous_path))
    result["gaps"] = None
    return result


def default_name(path, findings, prefix):
    return os.path.join(os.path.dirname(os.path.abspath(path)), "%s-%s.md" % (prefix, findings["stamp"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render a repo-healthcheck findings.json (schema 2) as Markdown.")
    parser.add_argument("findings")
    parser.add_argument("--previous", help="an earlier findings file to compare with")
    parser.add_argument("--no-previous", action="store_true", help="do not look for an earlier findings file")
    parser.add_argument("-o", "--output", help="report path (default: report-STAMP.md beside the input)")
    parser.add_argument("--share", help="share file path (default: share-STAMP.md beside the input)")
    args = parser.parse_args(argv)
    try:
        findings = load_json(args.findings)
        if isinstance(findings, dict) and findings.get("schema") == 2:
            score_path = os.path.join(os.path.dirname(os.path.abspath(args.findings)), str(findings.get("score", "")))
            score = load_json(score_path)
        else:
            validate(findings)
            return 2
        gap_order = {g["id"]: i for i, g in enumerate(score["gaps"])}
        validate(findings, gap_order)
        changes = None
        compared = None
        if not score.get("changes") and not args.no_previous:
            found = None
            if args.previous:
                found = (args.previous, load_json(args.previous), None)
            else:
                found = find_previous(args.findings, findings)
            if found:
                changes = previous_changes(score, found[0], found[1])
                compared = found[2] or os.path.basename(found[0])
        report = render(findings, score, changes, compared)
        output = args.output or default_name(args.findings, findings, "report")
        share_path = args.share or default_name(args.findings, findings, "share")
        for target, body in ((output, report), (share_path, share(findings, score))):
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(body)
    except (FindingsError, OSError, KeyError) as exc:
        sys.stderr.write("render.py: %s\n" % (("missing key %s in score.json" % exc) if isinstance(exc, KeyError)
                                              else exc))
        return 2
    sys.stdout.write(summary(findings, score, os.path.abspath(output), changes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
