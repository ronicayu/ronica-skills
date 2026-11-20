"""The short readable summary of a result row, built from its text with no model. `tg result add --summary` shows it
on the issue comment above the full report. Used by run.py and by mailbox.py.

summarize(kind, status, body, lang) -> str; "" when the row has no summary form (a STOPPED or DIED row, an ack)."""
import re

LABELS = ("Task", "Status", "Revision", "Verdict", "Branch", "Head", "Worktree", "Ran", "Evidence", "Files", "Issues", "Findings",
          "Asked", "Deviations", "Follow-ups", "Checkpoint", "Session", "From")
LABEL_LINE = re.compile(r"^(" + "|".join(LABELS) + r"):[ \t]*(.*)$")
LIST_MARK = re.compile(r"^(?:[-*]|\d+[.)])\s+")
BLOCKING = re.compile(r"^blocking(?:\[[a-z-]+\])?:\s*", re.I)
QUESTION_LINE = re.compile(r"(?m)^Question:[ \t]*(.+)$")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
LONG_MESSAGE = 300  # characters of an ask or answer body above which it gets a one-line summary
CUT = 120  # characters of a finding, issue or evidence line in a summary
LANGS = ("en", "zh")

TEXT = {
    "en": {
        "pass": "✅ PASS", "ISSUES": "⚠️ ISSUES", "BLOCKED": "⚠️ BLOCKED", "head": "head {}",
        "files": ("{} file changed", "{} files changed"), "ran": ("{} command ran", "{} commands ran"),
        "evidence": "Evidence: {}", "asked": "Asked: {}",
        "failed": ("❌ verify-failed", "{} blocking finding", "{} blocking findings"),
        "vblocked": "⚠️ verify-blocked", "revision": "🔁 revision {} from verify #{}",
        "ask": "❓ {}", "answer": "💬 {}",
    },
    "zh": {
        "pass": "✅ 通过", "ISSUES": "⚠️ 有问题", "BLOCKED": "⚠️ 受阻",
        "head": "提交 {}", "files": ("改了 {} 个文件",) * 2, "ran": ("跑了 {} 条命令",) * 2,
        "evidence": "证据: {}", "asked": "已提问: {}",
        "failed": ("❌ 验证未通过", "{} 条阻塞问题", "{} 条阻塞问题"),
        "vblocked": "⚠️ 验证受阻",
        "revision": "🔁 第 {} 轮修订，来自验证 #{}",
        "ask": "❓ {}", "answer": "💬 {}",
    },
}


def cut(text, size=CUT):
    text = " ".join(text.split())
    return text if len(text) <= size else text[:size - 1].rstrip() + "…"


def fields(body):
    """{label: [text of each occurrence]}: the rest of its line and the lines up to the next label. A line inside a ```
    fence is text. A label that repeats gives one entry each, as a verifier's `Issues:` line per finding does."""
    found, current, fenced = {}, None, False
    for line in (body or "").splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        match = None if fenced else LABEL_LINE.match(line)
        if match:
            current = found.setdefault(match.group(1), [])
            current.append(match.group(2))
        elif current is not None:
            current[-1] += "\n" + line
    return {k: [v.strip() for v in vs] for k, vs in found.items()}


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
        findings = [BLOCKING.sub("", line) for line in issues if BLOCKING.match(line)] or issues
        title, one, many = words["failed"]
        first = [title] + ([(one if len(findings) == 1 else many).format(len(findings))] if findings else [])
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


def summarize(kind, status, body, lang="en"):
    words = TEXT.get(lang) or TEXT["en"]
    if kind == "task" and status in ("PASS", "ISSUES", "BLOCKED"):
        return worker_summary(status, body, words)
    if kind == "verify":
        return verify_summary(status, body, words)
    if kind == "revise":
        return revise_summary(body, words)
    if kind in ("ask", "answer"):
        return message_summary(kind, body, words)
    return ""
