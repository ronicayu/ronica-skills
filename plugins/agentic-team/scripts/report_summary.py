"""The short readable summary of a result row. `tg result add --summary` shows it on the issue comment above the full
report. A worker or verifier report carries it as its `Summary:` field, written by the author; every other row, and a
report without one, gets a short text built from the row's fields, with no model. Used by run.py and by mailbox.py.

summarize(kind, status, body) -> str; "" when the row has no summary form (a STOPPED or DIED row, an ack)."""
import re

# The labels that start a report section at column 0: the one definition that run.py (SECTION_LINE, REPORT_LABEL), check-report,
# report_field and fields() below share. Any other `Word:` line, such as `Note:` or `Changed:`, continues the section above it.
SECTION_LABELS = ("Task", "Status", "Summary", "Revision", "Verdict", "Branch", "Head", "Worktree", "Ran", "Evidence",
                  "Acceptance evidence", "Files", "Issues", "Findings", "Asked", "Deviations", "Follow-ups", "Checkpoint", "Session",
                  "Stopped", "Workflow", "Run", "Conclusion", "Overrides", "Reason", "Needs CI", "Notes")
LABELS = SECTION_LABELS + ("From",)  # `From:` is the label of a revise row, not of a report
LABEL_PATTERN = "|".join(re.escape(label) for label in LABELS)
SECTION_PATTERN = "|".join(re.escape(label) for label in SECTION_LABELS)
LABEL_LINE = re.compile(r"^(" + LABEL_PATTERN + r"):(?:[ \t]+(.*)|$)")
COMMENT = re.compile(r"<!--.*?-->", re.S)
SUMMARY_LINES, SUMMARY_CHARS = 3, 2000  # the most lines and characters of a Summary; `tg result add --summary` refuses more
LIST_MARK = re.compile(r"^(?:[-*]|\d+[.)])\s+")
BLOCKING = re.compile(r"^blocking(?:\[[a-z-]+\])?:\s*", re.I)
QUESTION_LINE = re.compile(r"(?m)^Question:[ \t]*(.+)$")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
LONG_MESSAGE = 300  # characters of an ask or answer body above which it gets a one-line summary
CUT = 120  # characters of a finding, issue or evidence line in a summary

WORDS = {
    "pass": "✅ PASS", "ISSUES": "⚠️ ISSUES", "BLOCKED": "⚠️ BLOCKED", "head": "head {}",
    "files": ("{} file changed", "{} files changed"), "ran": ("{} command ran", "{} commands ran"),
    "evidence": "Evidence: {}", "asked": "Asked: {}",
    "failed": ("❌ verify-failed", "{} blocking finding", "{} blocking findings", "{} finding", "{} findings"),
    "vblocked": "⚠️ verify-blocked", "revision": "🔁 revision {} from verify #{}",
    "ask": "❓ {}", "answer": "💬 {}",
}


def cut(text, size=CUT):
    text = " ".join(text.split())
    return text if len(text) <= size else text[:size - 1].rstrip() + "…"


def sections(body):
    """[(label, text)] of a report, the one parser: `<!-- -->` comments are dropped first; a section is the rest of its
    `Label:` line (LABELS, at column 0) and the lines up to the next label. A line inside a ``` fence is text, so a label
    that appears only in a fence is missing. A label that repeats gives one section each."""
    found, fenced = [], False
    for line in COMMENT.sub("", body or "").splitlines():
        match = None if fenced else LABEL_LINE.match(line)
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if match:
            found.append((match.group(1), [match.group(2) or ""]))
        elif found:
            found[-1][1].append(line)
    return [(label, "\n".join(lines).strip()) for label, lines in found]


def fields(body):
    """{label: [text of each occurrence]} (see sections). A verifier's `Issues:` line per finding gives one entry each."""
    out = {}
    for label, text in sections(body):
        out.setdefault(label, []).append(text)
    return out


def bounded(text):
    """A Summary cut to SUMMARY_LINES non-empty lines and SUMMARY_CHARS characters, so `tg result add` accepts it."""
    out = "\n".join([line.rstrip() for line in (text or "").splitlines() if line.strip()][:SUMMARY_LINES]).strip()
    return out if len(out) <= SUMMARY_CHARS else out[:SUMMARY_CHARS - 1].rstrip() + "…"


def summary_problem(text):
    """What is wrong with the length of a Summary, or "" when it fits."""
    lines = len([line for line in text.splitlines() if line.strip()])
    if lines > SUMMARY_LINES:
        return f"the `Summary:` has {lines} lines; write at most {SUMMARY_LINES}, and put the detail in the other fields"
    if len(text) > SUMMARY_CHARS:
        return f"the `Summary:` has {len(text)} characters; write at most {SUMMARY_CHARS}"
    return ""


def lines_of(values):
    """The non-empty lines of a field, list markers dropped; `None` is nothing."""
    out = [LIST_MARK.sub("", line.strip()) for value in values for line in value.splitlines() if line.strip()]
    return [] if [line.rstrip(".").lower() for line in out] == ["none"] else out


def short_head(values):
    head = (lines_of(values) or [""])[0].split(" ")[0]
    return head[:7] if SHA.match(head) else head[:12]


def count_files(values):
    names = [name.strip().strip("`") for line in lines_of(values) for name in re.split(r",\s+", line)]
    return len([n for n in names if n and n.lower() != "none"])


def count_commands(values):
    """The lines of a Ran field outside ``` fences: a fence holds the output of a command, not another command."""
    fenced, count = False, 0
    for line in lines_of(values):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            count += 1
    return count


def plural(pair, n):
    return pair[0 if n == 1 else 1].format(n)


def worker_summary(status, body, words):
    got = fields(body)
    if status == "PASS":
        parts = [words["pass"]]
        head = short_head(got.get("Head", []))
        if head:
            parts.append(words["head"].format(head))
        for label, key, pair in (("Files", "files", count_files), ("Ran", "ran", count_commands)):
            n = pair(got.get(label, []))
            if n:
                parts.append(plural(words[key], n))
        out = [" · ".join(parts)]
        evidence = lines_of(got.get("Evidence", []))
        if evidence:
            out.append(words["evidence"].format(cut(evidence[0])))
        return "\n".join(out)
    issues = lines_of(got.get("Issues", []))
    out = [" · ".join([words[status], *([cut(issues[0])] if issues else [])])]
    asked = lines_of(got.get("Asked", []))
    if asked:
        out.append(words["asked"].format(cut(asked[0])))
    return "\n".join(out)


def verify_summary(status, body, words):
    got = fields(body)
    verdict = (lines_of(got.get("Verdict", [])) or [""])[0].split(" ")[0]
    head = short_head(got.get("Head", []))
    issues = lines_of(got.get("Issues", []))
    if status == "ISSUES" or verdict == "verify-failed":
        blocking = [BLOCKING.sub("", line) for line in issues if BLOCKING.match(line)]
        findings = blocking or issues
        title, one, many, plain_one, plain_many = words["failed"]
        count = (one, many) if blocking else (plain_one, plain_many)
        first = [title] + ([count[0 if len(findings) == 1 else 1].format(len(findings))] if findings else [])
        return "\n".join([" · ".join(first), *(f"- {cut(f)}" for f in findings[:2])])
    if status == "BLOCKED" or verdict == "verify-blocked":
        return " · ".join([words["vblocked"], *([cut(issues[0])] if issues else [])])
    if status != "PASS":
        return ""
    return " · ".join([f"✅ {verdict}" if verdict else words["pass"], *([words["head"].format(head)] if head else [])])


def revise_summary(body, words):
    got = fields(body)
    number, source = (got.get("Revision") or [""])[0], re.search(r"#(\d+)", (got.get("From") or [""])[0])
    return words["revision"].format(number, source.group(1)) if number and source else ""


def message_summary(kind, body, words):
    text = (body or "").strip()
    if len(text) <= LONG_MESSAGE:
        return ""
    asked = QUESTION_LINE.search(text)
    first = lines_of([asked.group(1)] if asked else []) or lines_of([text])
    return words[kind].format(cut(first[0])) if first else ""


REPORT_STATUSES = ("PASS", "ISSUES", "BLOCKED")


def summarize(kind, status, body):
    """A worker or verifier report: its `Summary:` text as written; the fallback from its other fields only when it has
    none (a salvaged report, DIED, STOPPED)."""
    report = kind in ("task", "verify") and status in REPORT_STATUSES
    if report and (written := bounded((fields(body).get("Summary") or [""])[0])):
        return written
    if kind == "task" and report:
        return worker_summary(status, body, WORDS)
    if kind == "verify":
        return verify_summary(status, body, WORDS)
    if kind == "revise":
        return revise_summary(body, WORDS)
    if kind in ("ask", "answer"):
        return message_summary(kind, body, WORDS)
    return ""
