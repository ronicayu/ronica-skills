#!/usr/bin/env python3
"""Render a repo-health findings.json as a Markdown report.

    render.py findings.json [--previous OLD.json | --no-previous] [-o report.md]

Writes the report, then prints a terminal summary: the headline, the top five
actions (title and first step) and the report path. Standard library only;
Python 3.9+.

render.py orders and lays out; it does not judge. The model writes the headline,
the levels, the recommendations and their impact and effort into findings.json
(schema 1, see the skill), so the report has the same shape on every run.

Required fields (an error names the missing field):
  top level        schema (must be 1), repo, date, headline, dimensions,
                   recommendations, not_checked
  dimensions[]     id, subproject, status (checked|not_run|skipped), summary;
                   level is an integer 0-3, or null for the metric and review
                   dimensions (size, hotspots, structure, errors, testquality,
                   docsaccuracy) and for status not_run or skipped
  recommendations[] id, dimension, title, why, impact, effort, first_step
  not_checked[]    what, why
Optional: commit, subproject(s), tier, evidence, not_run_reason, how_to_run.
Unknown fields are ignored. An impact or effort value outside the schema sorts
last instead of failing.

Top actions rank by impact (high, medium, low), then effort (small, medium,
large), then the order in the file. The scorecard compares each dimension and
subproject with the previous run: up, down, "=" or "new". A dimension whose
level is null compares as "=" when the previous run had the row, else "new".
With no previous run the Change column shows "—".
"""

import argparse
import json
import os
import re
import sys

LEVEL_NAMES = {0: "absent", 1: "present", 2: "enforced", 3: "effective"}

DIMENSIONS = [
    ("lint", "Lint and formatting"),
    ("types", "Type checking"),
    ("static", "Static analysis and security"),
    ("secrets", "Secret scanning"),
    ("tests", "Tests"),
    ("coverage", "Coverage"),
    ("ci", "CI"),
    ("setup", "Setup and reproducibility"),
    ("docs", "Docs"),
    ("deps", "Dependencies"),
    ("size", "Size and structure metrics"),
    ("hotspots", "Hotspots"),
    ("deadcode", "Dead code"),
    ("structure", "Structure review"),
    ("errors", "Error handling and observability"),
    ("testquality", "Test quality"),
    ("docsaccuracy", "Docs accuracy"),
]
DIMENSION_NAMES = dict(DIMENSIONS)

# Report text per language. findings["lang"] picks one: "zh..." gives Chinese, anything else English.
TEXT = {
    "en": {
        "title": "# Repo health report: %s", "commit": "Commit: `%s`", "date": "Date: %s",
        "compared": "Compared with the run of %s", "top": "## Top actions", "no_recs": "No recommendations.",
        "scorecard": "## Scorecard", "no_dims": "No dimensions were measured.", "root": "repo root (.)",
        "table": "| Dimension | Level | Summary | Change |",
        "legend": "Levels: 0 absent, 1 present, 2 enforced, 3 effective. — means measured without a level.",
        "details": "## Details", "no_details": "No details.", "level": "Level: %s.",
        "measured": "measured, no level", "not_run_reason": "Not run: %s", "evidence": "Evidence:",
        "not_checked": "## Not checked", "to_run": " To run it: `%s`", "none_skipped": "Nothing was skipped.",
        "impact": "%s impact", "effort": "%s effort", "first_step": "First step:",
        "levels": LEVEL_NAMES,
        "not_run": "not run", "skipped": "skipped", "new": "new",
        "values": {}, "names": {},
        "summary_top": "Top actions:", "summary_step": "   first step: %s%s", "report": "Report: %s",
    },
    "zh": {
        "title": "# 仓库健康报告：%s", "commit": "提交：`%s`", "date": "日期：%s",
        "compared": "对比 %s 的结果", "top": "## 优先行动", "no_recs": "没有建议。",
        "scorecard": "## 计分表", "no_dims": "没有测量任何维度。", "root": "仓库根目录 (.)",
        "table": "| 维度 | 等级 | 摘要 | 变化 |",
        "legend": "等级：0 没有，1 有配置，2 强制，3 有效。— 表示只测量、不定级。",
        "details": "## 细节", "no_details": "没有细节。", "level": "等级：%s。",
        "measured": "只测量，不定级", "not_run_reason": "未运行：%s", "evidence": "证据：",
        "not_checked": "## 未检查", "to_run": " 运行方法：`%s`", "none_skipped": "没有跳过任何项。",
        "impact": "影响%s", "effort": "工作量%s", "first_step": "第一步：",
        "levels": {0: "没有", 1: "有配置", 2: "强制", 3: "有效"},
        "not_run": "未运行", "skipped": "已跳过", "new": "新",
        "values": {"high": "高", "medium": "中", "low": "低", "small": "小", "large": "大"},
        "names": {
            "lint": "Lint 与格式化", "types": "类型检查", "static": "静态分析与安全", "secrets": "密钥扫描",
            "tests": "测试", "coverage": "覆盖率", "ci": "CI", "setup": "环境搭建与可复现", "docs": "文档",
            "deps": "依赖", "size": "规模", "hotspots": "热点", "deadcode": "死代码", "structure": "结构审查",
            "errors": "错误处理与可观测性", "testquality": "测试质量", "docsaccuracy": "文档准确性",
        },
        "summary_top": "优先行动：", "summary_step": "   第一步：%s%s", "report": "报告：%s",
    },
}


def text_for(findings):
    lang = findings.get("lang") if isinstance(findings, dict) else None
    return TEXT["zh"] if isinstance(lang, str) and lang.lower().startswith("zh") else TEXT["en"]
DIMENSION_ORDER = {key: i for i, (key, _name) in enumerate(DIMENSIONS)}

NULL_LEVEL_OK = {"size", "hotspots", "structure", "errors", "testquality", "docsaccuracy"}
STATUSES = ("checked", "not_run", "skipped")
IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}
EFFORT_RANK = {"small": 0, "medium": 1, "large": 2}
TOP_ACTIONS = 5
NO_CHANGE_DATA = "—"
FINDINGS_NAME = re.compile(r"^findings-(\d{4}-\d{2}-\d{2}).*\.json$")


class FindingsError(ValueError):
    """The findings file is not valid; the message names the field."""


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _require(obj, field, where, kind=None):
    if not isinstance(obj, dict):
        raise FindingsError("%s must be an object" % where)
    if field not in obj or obj[field] is None:
        raise FindingsError("missing required field: %s%s" % (where + "." if where else "", field))
    value = obj[field]
    if kind is not None and not isinstance(value, kind):
        raise FindingsError("%s%s must be %s" % (where + "." if where else "", field, kind.__name__))
    return value


def validate(findings):
    """Raise FindingsError for the first missing or malformed required field."""
    if not isinstance(findings, dict):
        raise FindingsError("findings must be a JSON object")
    schema = _require(findings, "schema", "")
    if schema != 1:
        raise FindingsError("schema must be 1, got %r" % (schema,))
    _require(findings, "repo", "", str)
    _require(findings, "date", "", str)
    headline = _require(findings, "headline", "", str)
    if not headline.strip():
        raise FindingsError("headline must not be empty")
    dimensions = _require(findings, "dimensions", "", list)
    recommendations = _require(findings, "recommendations", "", list)
    not_checked = _require(findings, "not_checked", "", list)
    for i, dim in enumerate(dimensions):
        where = "dimensions[%d]" % i
        dim_id = _require(dim, "id", where, str)
        _require(dim, "subproject", where, str)
        status = _require(dim, "status", where, str)
        _require(dim, "summary", where, str)
        if status not in STATUSES:
            raise FindingsError("%s.status must be one of %s, got %r" % (where, "|".join(STATUSES), status))
        level = dim.get("level")
        if level is None:
            if dim_id not in NULL_LEVEL_OK and status == "checked":
                raise FindingsError("%s.level is required (0-3) for the checked dimension %r" % (where, dim_id))
        elif isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 3:
            raise FindingsError("%s.level must be an integer 0-3 or null, got %r" % (where, level))
        if "evidence" in dim and not isinstance(dim["evidence"], list):
            raise FindingsError("%s.evidence must be a list" % where)
    for i, rec in enumerate(recommendations):
        where = "recommendations[%d]" % i
        for field in ("id", "dimension", "title", "why", "impact", "effort", "first_step"):
            _require(rec, field, where, str)
    for i, item in enumerate(not_checked):
        where = "not_checked[%d]" % i
        _require(item, "what", where, str)
        _require(item, "why", where, str)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def cell(text):
    return re.sub(r"\s+", " ", str(text)).replace("|", "\\|").strip()


def fence(text):
    """Fence the text with more backticks than any run inside it."""
    longest = max([len(m) for m in re.findall(r"`+", text)] or [0])
    ticks = "`" * max(3, longest + 1)
    return "%s\n%s\n%s" % (ticks, text.strip("\n"), ticks)


def dimension_name(dim_id, t=TEXT["en"]):
    return t["names"].get(dim_id) or DIMENSION_NAMES.get(dim_id, dim_id)


def level_text(dim, t=TEXT["en"]):
    level = dim.get("level")
    if level is not None:
        return "%d %s" % (level, t["levels"][level])
    status = dim.get("status")
    if status == "not_run":
        return t["not_run"]
    if status == "skipped":
        return t["skipped"]
    return "—"


def rank_recommendations(recommendations):
    """Recommendations with their original index, ordered for the report."""
    indexed = list(enumerate(recommendations))
    indexed.sort(key=lambda pair: (IMPACT_RANK.get(pair[1].get("impact"), 99),
                                   EFFORT_RANK.get(pair[1].get("effort"), 99), pair[0]))
    return [rec for _i, rec in indexed]


def dimension_sort_key(pair):
    index, dim = pair
    return (DIMENSION_ORDER.get(dim["id"], len(DIMENSION_ORDER)), index)


def subproject_order(findings):
    order = []
    for sub in findings.get("subprojects") or []:
        if isinstance(sub, dict) and isinstance(sub.get("path"), str) and sub["path"] not in order:
            order.append(sub["path"])
    for dim in findings["dimensions"]:
        if dim["subproject"] not in order:
            order.append(dim["subproject"])
    return order


def previous_index(previous):
    """{(dimension id, subproject): level or None} from an earlier findings dict."""
    index = {}
    if not isinstance(previous, dict):
        return index
    for dim in previous.get("dimensions") or []:
        if isinstance(dim, dict) and isinstance(dim.get("id"), str):
            level = dim.get("level")
            index[(dim["id"], dim.get("subproject", "."))] = level if isinstance(level, int) else None
    return index


def change_text(dim, index, t=TEXT["en"]):
    if index is None:
        return NO_CHANGE_DATA
    key = (dim["id"], dim["subproject"])
    if key not in index:
        return t["new"]
    before, now = index[key], dim.get("level")
    if now is None:
        return "="
    if before is None:
        return t["new"]
    if now > before:
        return "↑"
    if now < before:
        return "↓"
    return "="


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def recommendation_block(rec, heading, t=TEXT["en"]):
    meta = [t["impact"] % t["values"].get(rec["impact"], rec["impact"]),
            t["effort"] % t["values"].get(rec["effort"], rec["effort"]), rec["dimension"]]
    if rec.get("subproject") not in (None, ".", ""):
        meta.append(rec["subproject"])
    lines = ["%s %s" % (heading, rec["title"]), "", "*%s*" % " · ".join(meta), "", rec["why"].strip(), "",
             t["first_step"], "", fence(rec["first_step"]), ""]
    return lines


def render(findings, previous=None):
    """The report for a findings dict, as Markdown. `previous` is an earlier findings dict."""
    validate(findings)
    t = text_for(findings)
    index = previous_index(previous) if previous is not None else None
    ranked = rank_recommendations(findings["recommendations"])
    top = ranked[:TOP_ACTIONS]
    rest = ranked[TOP_ACTIONS:]
    out = [t["title"] % findings["repo"], ""]
    meta = []
    if findings.get("commit"):
        meta.append(t["commit"] % str(findings["commit"])[:12])
    meta.append(t["date"] % findings["date"])
    if previous is not None and isinstance(previous, dict) and previous.get("date"):
        meta.append(t["compared"] % previous["date"])
    out += [" · ".join(meta), "", "**%s**" % findings["headline"].strip(), ""]

    out += [t["top"], ""]
    if top:
        for number, rec in enumerate(top, 1):
            out += recommendation_block(rec, "### %d." % number, t)
    else:
        out += [t["no_recs"], ""]

    out += [t["scorecard"], ""]
    order = subproject_order(findings)
    indexed = list(enumerate(findings["dimensions"]))
    groups = []
    for sub in order:
        rows = sorted([p for p in indexed if p[1]["subproject"] == sub], key=dimension_sort_key)
        if rows:
            groups.append((sub, [dim for _i, dim in rows]))
    if not groups:
        out += [t["no_dims"], ""]
    for sub, rows in groups:
        if len(groups) > 1:
            out += ["### %s" % (t["root"] if sub == "." else sub), ""]
        out += [t["table"], "| --- | --- | --- | --- |"]
        for dim in rows:
            out.append("| %s | %s | %s | %s |" % (cell(dimension_name(dim["id"], t)), cell(level_text(dim, t)),
                                                  cell(dim["summary"]), change_text(dim, index, t)))
        out.append("")
    out += [t["legend"], ""]

    out += [t["details"], ""]
    by_dimension = {}
    for pair in sorted(indexed, key=dimension_sort_key):
        by_dimension.setdefault(pair[1]["id"], []).append(pair[1])
    rest_by_dimension = {}
    for rec in rest:
        rest_by_dimension.setdefault(rec["dimension"], []).append(rec)
    ids = sorted(set(by_dimension) | set(rest_by_dimension),
                 key=lambda d: (DIMENSION_ORDER.get(d, len(DIMENSION_ORDER)), d))
    if not ids:
        out += [t["no_details"], ""]
    for dim_id in ids:
        out += ["### %s (`%s`)" % (dimension_name(dim_id, t), dim_id), ""]
        entries = by_dimension.get(dim_id, [])
        for dim in entries:
            label = "**%s** — " % dim["subproject"] if (len(entries) > 1 or dim["subproject"] != ".") else ""
            shown = level_text(dim, t)
            if dim.get("level") is None and dim.get("status") == "checked":
                shown = t["measured"]
            text = label + t["level"] % shown
            if dim["summary"].strip():
                text += " " + dim["summary"].strip()
            out += [text, ""]
            if dim.get("not_run_reason"):
                out += [t["not_run_reason"] % dim["not_run_reason"], ""]
            evidence = dim.get("evidence") or []
            if evidence:
                out += [t["evidence"], ""] + ["- " + re.sub(r"\s*\n\s*", " ", str(e)) for e in evidence] + [""]
        for rec in rest_by_dimension.get(dim_id, []):
            out += recommendation_block(rec, "####", t)

    out += [t["not_checked"], ""]
    if findings["not_checked"]:
        for item in findings["not_checked"]:
            why = item["why"].strip()
            if why and why[-1] not in ".!?。！？":
                why += "."
            line = "- **%s** — %s" % (item["what"].strip(), why)
            if item.get("how_to_run"):
                line += t["to_run"] % item["how_to_run"].strip().replace("`", "'")
            out.append(line)
        out.append("")
    else:
        out += [t["none_skipped"], ""]
    return "\n".join(out).rstrip("\n") + "\n"


def summary(findings, report_path=None):
    """Terminal summary: headline, top five actions with first steps, report path."""
    validate(findings)
    t = text_for(findings)
    lines = [findings["headline"].strip(), ""]
    top = rank_recommendations(findings["recommendations"])[:TOP_ACTIONS]
    if top:
        lines.append(t["summary_top"])
        for number, rec in enumerate(top, 1):
            step = rec["first_step"].strip().splitlines()
            first = step[0] if step else ""
            more = " …" if len(step) > 1 else ""
            lines.append("%d. %s" % (number, rec["title"]))
            lines.append(t["summary_step"] % (first, more))
    else:
        lines.append(t["no_recs"])
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


def find_previous(path, findings):
    """The newest findings-DATE*.json beside `path` that is older than it, or None."""
    folder = os.path.dirname(os.path.abspath(path))
    own = FINDINGS_NAME.match(os.path.basename(path))
    current = own.group(1) if own else str(findings.get("date", ""))
    candidates = []
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        m = FINDINGS_NAME.match(name)
        if m and m.group(1) < current and os.path.join(folder, name) != os.path.abspath(path):
            candidates.append((m.group(1), name))
    for _date, name in sorted(candidates, reverse=True):
        full = os.path.join(folder, name)
        try:
            data = load_json(full)
        except FindingsError as exc:
            sys.stderr.write("render.py: skipping %s\n" % exc)
            continue
        if isinstance(data, dict) and isinstance(data.get("dimensions"), list):
            return full, data
    return None


def default_output(path, findings):
    folder = os.path.dirname(os.path.abspath(path))
    name = os.path.basename(path)
    if name.startswith("findings"):
        return os.path.join(folder, "report" + name[len("findings"):].rsplit(".", 1)[0] + ".md")
    return os.path.join(folder, "report-%s.md" % findings["date"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render a repo-health findings.json as Markdown.")
    parser.add_argument("findings")
    parser.add_argument("--previous", help="an earlier findings.json to compare with")
    parser.add_argument("--no-previous", action="store_true", help="do not look for an earlier findings file")
    parser.add_argument("-o", "--output", help="report path (default: report-DATE.md beside the input)")
    args = parser.parse_args(argv)
    try:
        findings = load_json(args.findings)
        validate(findings)
        previous = None
        if args.previous:
            previous = load_json(args.previous)
            if not isinstance(previous, dict) or not isinstance(previous.get("dimensions"), list):
                raise FindingsError("%s is not a findings file" % args.previous)
        elif not args.no_previous:
            found = find_previous(args.findings, findings)
            previous = found[1] if found else None
        report = render(findings, previous)
        output = args.output or default_output(args.findings, findings)
        folder = os.path.dirname(os.path.abspath(output))
        os.makedirs(folder, exist_ok=True)
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(report)
    except (FindingsError, OSError) as exc:
        sys.stderr.write("render.py: %s\n" % exc)
        return 2
    sys.stdout.write(summary(findings, os.path.abspath(output)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
