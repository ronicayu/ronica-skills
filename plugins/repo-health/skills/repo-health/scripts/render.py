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


def dimension_name(dim_id):
    return DIMENSION_NAMES.get(dim_id, dim_id)


def level_text(dim):
    level = dim.get("level")
    if level is not None:
        return "%d %s" % (level, LEVEL_NAMES[level])
    status = dim.get("status")
    if status == "not_run":
        return "not run"
    if status == "skipped":
        return "skipped"
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


def change_text(dim, index):
    if index is None:
        return NO_CHANGE_DATA
    key = (dim["id"], dim["subproject"])
    if key not in index:
        return "new"
    before, now = index[key], dim.get("level")
    if now is None:
        return "="
    if before is None:
        return "new"
    if now > before:
        return "↑"
    if now < before:
        return "↓"
    return "="


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def recommendation_block(rec, heading):
    meta = ["%s impact" % rec["impact"], "%s effort" % rec["effort"], rec["dimension"]]
    if rec.get("subproject") not in (None, ".", ""):
        meta.append(rec["subproject"])
    lines = ["%s %s" % (heading, rec["title"]), "", "*%s*" % " · ".join(meta), "", rec["why"].strip(), "",
             "First step:", "", fence(rec["first_step"]), ""]
    return lines


def render(findings, previous=None):
    """The report for a findings dict, as Markdown. `previous` is an earlier findings dict."""
    validate(findings)
    index = previous_index(previous) if previous is not None else None
    ranked = rank_recommendations(findings["recommendations"])
    top = ranked[:TOP_ACTIONS]
    rest = ranked[TOP_ACTIONS:]
    out = ["# Repo health report: %s" % findings["repo"], ""]
    meta = []
    if findings.get("commit"):
        meta.append("Commit: `%s`" % str(findings["commit"])[:12])
    meta.append("Date: %s" % findings["date"])
    if previous is not None and isinstance(previous, dict) and previous.get("date"):
        meta.append("Compared with the run of %s" % previous["date"])
    out += [" · ".join(meta), "", "**%s**" % findings["headline"].strip(), ""]

    out += ["## Top actions", ""]
    if top:
        for number, rec in enumerate(top, 1):
            out += recommendation_block(rec, "### %d." % number)
    else:
        out += ["No recommendations.", ""]

    out += ["## Scorecard", ""]
    order = subproject_order(findings)
    indexed = list(enumerate(findings["dimensions"]))
    groups = []
    for sub in order:
        rows = sorted([p for p in indexed if p[1]["subproject"] == sub], key=dimension_sort_key)
        if rows:
            groups.append((sub, [dim for _i, dim in rows]))
    if not groups:
        out += ["No dimensions were measured.", ""]
    for sub, rows in groups:
        if len(groups) > 1:
            out += ["### %s" % ("repo root (.)" if sub == "." else sub), ""]
        out += ["| Dimension | Level | Summary | Change |", "| --- | --- | --- | --- |"]
        for dim in rows:
            out.append("| %s | %s | %s | %s |" % (cell(dimension_name(dim["id"])), cell(level_text(dim)),
                                                  cell(dim["summary"]), change_text(dim, index)))
        out.append("")
    out += ["Levels: 0 absent, 1 present, 2 enforced, 3 effective. — means measured without a level.", ""]

    out += ["## Details", ""]
    by_dimension = {}
    for pair in sorted(indexed, key=dimension_sort_key):
        by_dimension.setdefault(pair[1]["id"], []).append(pair[1])
    rest_by_dimension = {}
    for rec in rest:
        rest_by_dimension.setdefault(rec["dimension"], []).append(rec)
    ids = sorted(set(by_dimension) | set(rest_by_dimension),
                 key=lambda d: (DIMENSION_ORDER.get(d, len(DIMENSION_ORDER)), d))
    if not ids:
        out += ["No details.", ""]
    for dim_id in ids:
        out += ["### %s (`%s`)" % (dimension_name(dim_id), dim_id), ""]
        entries = by_dimension.get(dim_id, [])
        for dim in entries:
            label = "**%s** — " % dim["subproject"] if (len(entries) > 1 or dim["subproject"] != ".") else ""
            shown = level_text(dim)
            if dim.get("level") is None and dim.get("status") == "checked":
                shown = "measured, no level"
            text = "%sLevel: %s." % (label, shown)
            if dim["summary"].strip():
                text += " " + dim["summary"].strip()
            out += [text, ""]
            if dim.get("not_run_reason"):
                out += ["Not run: %s" % dim["not_run_reason"], ""]
            evidence = dim.get("evidence") or []
            if evidence:
                out += ["Evidence:", ""] + ["- " + re.sub(r"\s*\n\s*", " ", str(e)) for e in evidence] + [""]
        for rec in rest_by_dimension.get(dim_id, []):
            out += recommendation_block(rec, "####")

    out += ["## Not checked", ""]
    if findings["not_checked"]:
        for item in findings["not_checked"]:
            why = item["why"].strip()
            if why and why[-1] not in ".!?":
                why += "."
            line = "- **%s** — %s" % (item["what"].strip(), why)
            if item.get("how_to_run"):
                line += " To run it: `%s`" % item["how_to_run"].strip().replace("`", "'")
            out.append(line)
        out.append("")
    else:
        out += ["Nothing was skipped.", ""]
    return "\n".join(out).rstrip("\n") + "\n"


def summary(findings, report_path=None):
    """Terminal summary: headline, top five actions with first steps, report path."""
    validate(findings)
    lines = [findings["headline"].strip(), ""]
    top = rank_recommendations(findings["recommendations"])[:TOP_ACTIONS]
    if top:
        lines.append("Top actions:")
        for number, rec in enumerate(top, 1):
            step = rec["first_step"].strip().splitlines()
            first = step[0] if step else ""
            more = " …" if len(step) > 1 else ""
            lines.append("%d. %s" % (number, rec["title"]))
            lines.append("   first step: %s%s" % (first, more))
    else:
        lines.append("No recommendations.")
    if report_path:
        lines += ["", "Report: %s" % report_path]
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
    sys.stdout.write(summary(findings, output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
