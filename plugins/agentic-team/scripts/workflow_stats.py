"""Retro statistics of workflow instances, and the proposals that follow from them (W6).

Pure functions over plain data: `run.py workflows --stats` collects one dict for each instance from Taskgraph (see
`collect_stats` in run.py) and passes the list to `compute` and `propose`. Nothing here reads Taskgraph, the clock or a
model, so the same input always gives the same output.

An instance dict holds: id, title, created_at, record (the `workflow_record` meta) and stages (one dict for each stage task
of the instance). A stage dict holds: id, task, state ("skipped" or None), origin, status, created_at, done_at, attempts,
revisions, verdicts (the verifier verdicts, in order), failed (the blocking categories of the verify-failed rows) and
approval (None, or level, outcome, by, state, on_timeout, opened_at, answered_at), started_at (the start of the task's latest
attempt). A split stage has several stage dicts with one id in an instance (its parts); the figures count it once for each instance.
"""

import datetime
import statistics
from typing import Any

# Thresholds of the proposal rules. A rule needs a minimum number of data points, so one unlucky instance never proposes a change.
THRESHOLDS: dict[str, float] = {
    "escalation_rate": 0.30,    # escalated to one stage type in at least this share of a workflow's instances
    "left_out_rate": 0.90,      # an optional stage left out in at least this share
    "first_pass_auto": 0.95,    # a stage that passes its first verify this often can lose its manager approval
    "first_pass_weak": 0.50,    # a stage that passes its first verify at most this often is weak
    "default_rate": 0.50,       # approvals that nobody answered
    "unsure_rate": 0.40,        # picks where an answer was unsure
    "override_rate": 0.20,      # picks that the owner overrode, or that an escalation corrected
    "cancel_rate": 0.20,
    "min_hits": 2,              # a rate rule needs at least this many instances that hit it, whatever the rate
    "min_instances": 3,
    "min_stages": 4,
    "min_approvals": 4,
}

FAILED = ("verify-failed", "verify-blocked")


def parse_time(value: Any) -> datetime.datetime | None:
    try:
        stamp = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=datetime.timezone.utc)


def hours_between(start: Any, end: Any) -> float | None:
    a, b = parse_time(start), parse_time(end)
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 3600, 2)


def rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def counted(items: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for item in items:
        found[item] = found.get(item, 0) + 1
    return dict(sorted(found.items(), key=lambda kv: (-kv[1], kv[0])))


def ended_kind(inst: dict[str, Any]) -> str:
    """`cancelled`, `merged` (every stage that counts is done) or `running`."""
    if (inst["record"].get("ended") or {}).get("kind") == "cancelled":
        return "cancelled"
    live = [s for s in inst["stages"] if s.get("state") != "skipped"]
    return "merged" if live and all(s["status"] == "done" for s in live) else "running"


def pick_of(inst: dict[str, Any]) -> dict[str, Any]:
    return inst["record"].get("pick") or {}


def escalated(inst: dict[str, Any]) -> bool:
    return any(a.get("kind") == "escalate" for a in inst["record"].get("adjustments") or [])


def overridden(inst: dict[str, Any]) -> bool:
    return bool(inst["record"].get("overrides"))


def corrected(inst: dict[str, Any]) -> bool:
    """The pick was overridden, or an escalation that is not a hard rule's corrected it (a rule that matched late is not the pick's fault)."""
    return overridden(inst) or any(a.get("kind") == "escalate" and a.get("trigger") != "rule" for a in inst["record"].get("adjustments") or [])


def stage_view(group: list[dict[str, Any]], sid: str) -> list[dict[str, Any]]:
    """One row for each instance of the group that has stage `sid` (a split stage's parts are one row): its live parts, whether it
    was verified, whether its first verify failed, and the approval of the stage (the first part that has one)."""
    rows = []
    for inst in group:
        parts = [s for s in inst["stages"] if s["id"] == sid]
        live = [s for s in parts if s.get("state") != "skipped"]
        if not parts:
            continue
        firsts = [s["verdicts"][0] for s in live if s.get("verdicts")]
        rows.append({"id": inst["id"], "parts": live, "skipped": len(parts) - len(live), "verified": bool(firsts),
                     "failed_first": any(v in FAILED for v in firsts),
                     "approval": next((s["approval"] for s in live if s.get("approval")), None)})
    return rows


def stage_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """One stage id of one workflow, over the rows of `stage_view`: one row for each instance."""
    live = [s for r in rows for s in r["parts"]]
    verified = [r for r in rows if r["verified"]]
    failed = [r for r in verified if r["failed_first"]]
    times = [h for h in (hours_between(s.get("started_at") or s.get("created_at"), s.get("done_at")) for s in live if s["status"] == "done")
             if h is not None]
    approvals = [r["approval"] for r in rows if r["approval"]]
    answered = [a for a in approvals if a.get("outcome")]
    outcomes = counted([a["outcome"] for a in answered])
    waits = [h for h in (hours_between(a.get("opened_at"), a.get("answered_at")) for a in answered) if h is not None]
    return {
        "instances": sum(1 for r in rows if r["parts"]),
        "tasks": len(live),
        "skipped": sum(r["skipped"] for r in rows),
        "merged": sum(1 for s in live if s["status"] == "done"),
        "attempts_mean": round(statistics.mean(s["attempts"] for s in live), 2) if live else None,
        "revisions_mean": round(statistics.mean(s["revisions"] for s in live), 2) if live else None,
        "verified": len(verified),
        "first_pass": len(verified) - len(failed),
        "first_pass_rate": rate(len(verified) - len(failed), len(verified)),
        "failed_categories": counted([c for s in live for c in s.get("failed") or []]),
        "median_hours": round(statistics.median(times), 2) if times else None,
        "approvals": {"total": len(approvals), "answered": len(answered), "outcomes": outcomes,
                      "levels": counted([a.get("level") or "?" for a in approvals]),
                      "default_rate": rate(outcomes.get("defaulted", 0), len(answered)),
                      "hold_rate": rate(outcomes.get("held", 0), len(answered)),
                      "median_wait_hours": round(statistics.median(waits), 2) if waits else None},
    }


def workflow_stats(name: str, group: list[dict[str, Any]]) -> dict[str, Any]:
    kinds = [ended_kind(i) for i in group]
    adjustments = [a for i in group for a in i["record"].get("adjustments") or []]
    picked = [i for i in group if pick_of(i).get("answers")]
    agreed = [i for i in picked if pick_of(i)["answers"][0] == pick_of(i)["answers"][1]]
    unsure = [i for i in picked if pick_of(i).get("unsure")]
    wrong = [i for i in group if corrected(i)]
    stage_ids = sorted({s["id"] for inst in group for s in inst["stages"]})
    return {
        "workflow": name,
        "instances": len(group),
        "merged": kinds.count("merged"),
        "cancelled": kinds.count("cancelled"),
        "running": kinds.count("running"),
        "completion_rate": rate(kinds.count("merged"), len(group)),
        "cancel_rate": rate(kinds.count("cancelled"), len(group)),
        "escalations": sum(1 for a in adjustments if a.get("kind") == "escalate"),
        "downgrades": sum(1 for a in adjustments if a.get("kind") == "downgrade"),
        "replacements": sum(1 for a in adjustments if a.get("kind") == "replace"),
        "escalated_instances": sorted(i["id"] for i in group if escalated(i)),
        "triggers": counted([f"{a['kind']}:{a.get('trigger') or 'unknown'}" for a in adjustments]),
        "escalated_to": counted([a.get("type") or "?" for a in adjustments if a.get("kind") == "escalate"]),
        "pick": {"picked": len(picked), "agreement_rate": rate(len(agreed), len(picked)), "unsure_rate": rate(len(unsure), len(picked)),
                 "overridden": sum(1 for i in group if overridden(i)),
                 "escalated_after_pick": sum(1 for i in group if escalated(i)),
                 "accuracy": rate(len(group) - len(wrong), len(group)),
                 "rule_applied": sum(1 for i in group if any(r.get("action") in ("moved", "forced-with") for r in i["record"].get("rules") or []))},
        "stages": {sid: stage_stats(stage_view(group, sid)) for sid in stage_ids},
    }


def grouped(instances: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for inst in sorted(instances, key=lambda i: i["id"]):
        groups.setdefault(str(inst["record"].get("workflow") or "?"), []).append(inst)
    return dict(sorted(groups.items()))


def compute(instances: list[dict[str, Any]]) -> dict[str, Any]:
    """The statistics of every workflow in `instances`, and the total."""
    return {"instances": len(instances), "workflows": {n: workflow_stats(n, g) for n, g in grouped(instances).items()}}


# ------------------------------------------------------------------------------------------------ proposals

def ids_text(ids: list[int]) -> str:
    return ", ".join(f"#{i}" for i in ids)


def propose(instances: list[dict[str, Any]], stats: dict[str, Any], limits: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Candidate changes to the workflow files or the hard rules. Each one names its evidence (instance ids and counts). Nothing
    is applied: the owner approves them at retro time, and each approved one becomes a task."""
    t = {**THRESHOLDS, **(limits or {})}
    out: list[dict[str, Any]] = []

    def add(kind: str, workflow: str, stage: str | None, text: str, ids: list[int], of: int) -> None:
        out.append({"kind": kind, "workflow": workflow, "stage": stage, "text": text,
                    "evidence": {"instances": sorted(ids), "count": len(ids), "of": of}})

    def enough(hit: list[int]) -> bool:
        return len(hit) >= t["min_hits"]

    for name, group in grouped(instances).items():
        w = stats["workflows"][name]
        n = len(group)
        if n >= t["min_instances"]:
            for stage_type in w["escalated_to"]:
                hit = [i["id"] for i in group if any(a.get("kind") == "escalate" and a.get("type") == stage_type
                                                     for a in i["record"].get("adjustments") or [])]
                if enough(hit) and len(hit) / n >= t["escalation_rate"]:
                    add("escalation", name, stage_type,
                        f"{name} escalated to {stage_type} in {len(hit)} of {n} instances ({ids_text(hit)}): consider adding {stage_type} "
                        f"to {name} as a required stage, a hard rule for the paths involved, or tightening the "
                        f"When-to-use of {name} so that this work is picked as a heavier workflow", hit, n)
            # An optional stage that was decided against (skipped or downgraded, not left out by default), in an instance that ended and
            # did not escalate to that stage type, counts as left out; an instance that never decided counts for nothing.
            options = {sid for i in group for sid in (i["record"].get("optional") or {})}
            for sid in sorted(options):
                decided = [i for i in group if ended_kind(i) != "running" and (i["record"].get("optional") or {}).get(sid) not in (None, "default-skipped")
                           and not any(a.get("kind") == "escalate" and a.get("type") == sid for a in i["record"].get("adjustments") or [])]
                left = [i["id"] for i in decided if i["record"]["optional"][sid] in ("skipped", "downgraded")]
                if len(decided) >= t["min_instances"] and enough(left) and len(left) / len(decided) >= t["left_out_rate"]:
                    add("drop-stage", name, sid, f"drop {sid} from {name}: skipped or downgraded in {len(left)} of {len(decided)} instances "
                        f"that decided it ({ids_text(left)})", left, len(decided))
            p = w["pick"]
            unsure = [i["id"] for i in group if pick_of(i).get("answers") and pick_of(i).get("unsure")]
            if p["picked"] >= t["min_instances"] and enough(unsure) and (p["unsure_rate"] or 0) >= t["unsure_rate"]:
                add("pick-unsure", name, None,
                    f"{p['unsure_rate']:.0%} of the picks that resolved to {name} had an unsure answer ({ids_text(unsure)}): "
                    "the descriptions do not separate it from its neighbours; sharpen its When-to-use", unsure, p["picked"])
            bad = [i["id"] for i in group if corrected(i)]
            if enough(bad) and len(bad) / n >= t["override_rate"]:
                add("pick-corrected", name, None,
                    f"{len(bad)} of {n} instances of {name} were overridden or escalated after the pick ({ids_text(bad)}): "
                    f"the pick chooses {name} too often; sharpen its When-to-use", bad, n)
            cancelled = [i["id"] for i in group if ended_kind(i) == "cancelled"]
            if enough(cancelled) and len(cancelled) / n >= t["cancel_rate"]:
                add("cancels", name, None, f"{len(cancelled)} of {n} instances of {name} were cancelled ({ids_text(cancelled)}): read their "
                    "`why` lines; the stage that orphaned them may need a clearer brief or a different verify kind", cancelled, n)
        for sid, st in w["stages"].items():
            rows = stage_view(group, sid)
            checked = [r for r in rows if r["verified"]]
            if st["verified"] >= t["min_stages"]:
                if (st["first_pass_rate"] or 0) >= t["first_pass_auto"]:
                    levels = {(r["approval"] or {}).get("level") for r in checked}
                    if levels == {"manager"}:
                        ids = [r["id"] for r in checked]
                        add("auto-approval", name, sid,
                            f"stage {sid} of {name} passed its first verify in {st['first_pass']} of {st['verified']} instances "
                            f"({ids_text(ids)}) with a manager approval: consider `approval = \"auto\"`", ids, st["verified"])
                elif st["first_pass_rate"] is not None and st["first_pass_rate"] <= t["first_pass_weak"]:
                    top = next(iter(st["failed_categories"]), None)
                    hit = [r["id"] for r in checked if r["failed_first"]]
                    if enough(hit):
                        add("weak-stage", name, sid,
                            f"stage {sid} of {name} failed its first verify in {len(hit)} of {st['verified']} instances ({ids_text(hit)})"
                            + (f", most often {top}" if top else "") + ": tighten its Stage notes or split it", hit, st["verified"])
            a = st["approvals"]
            if a["answered"] >= t["min_approvals"] and (a["default_rate"] or 0) >= t["default_rate"]:
                hit = [r["id"] for r in rows if (r["approval"] or {}).get("outcome") == "defaulted"]
                if enough(hit):
                    add("approval-defaults", name, sid,
                        f"the approval of {sid} in {name} was applied by default in {len(hit)} of {a['answered']} instances ({ids_text(hit)}): "
                        "nobody answers it; make it `manager`, or raise `human_due_hours`", hit, a["answered"])
    return out


# ------------------------------------------------------------------------------------------------ text

def pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def num(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def render(stats: dict[str, Any], proposals: list[dict[str, Any]], since: str | None = None) -> str:
    lines = [f"Workflow retro{' since ' + since if since else ''}: {stats['instances']} instance{'s' * (stats['instances'] != 1)}"]
    for name, w in stats["workflows"].items():
        p = w["pick"]
        lines += ["", f"{name}: {w['instances']} instances, {pct(w['completion_rate'])} merged, {pct(w['cancel_rate'])} cancelled, "
                      f"{w['running']} running",
                  f"  adjustments: {w['escalations']} escalations, {w['downgrades']} downgrades, {w['replacements']} replacements"
                  + (f" (triggers: {', '.join(f'{k} {v}' for k, v in w['triggers'].items())})" if w["triggers"] else "")]
        if p["picked"] or p["overridden"]:
            lines.append(f"  pick: {p['picked']} by --pick, agreement {pct(p['agreement_rate'])}, unsure {pct(p['unsure_rate'])}, "
                         f"overridden {p['overridden']}, escalated after the pick {p['escalated_after_pick']}, accuracy {pct(p['accuracy'])}")
        for sid, s in w["stages"].items():
            a = s["approvals"]
            lines.append(f"  stage {sid}: {s['merged']}/{s['tasks']} merged, {s['skipped']} skipped; attempts {num(s['attempts_mean'])}, "
                         f"revisions {num(s['revisions_mean'])}; first-pass {pct(s['first_pass_rate'])} of {s['verified']}; "
                         f"median {num(s['median_hours'])} h"
                         + (f"; failures: {', '.join(f'{k} {v}' for k, v in list(s['failed_categories'].items())[:3])}" if s["failed_categories"] else "")
                         + (f"; approvals {a['answered']}/{a['total']}: {', '.join(f'{k} {v}' for k, v in a['outcomes'].items())}"
                            f", default {pct(a['default_rate'])}, hold {pct(a['hold_rate'])}" if a["total"] else ""))
    lines += ["", f"Proposals ({len(proposals)}; the owner approves each at retro time, nothing is applied):"]
    lines += [f"  {n}. [{p['kind']}] {p['text']}" for n, p in enumerate(proposals, 1)] or ["  none"]
    return "\n".join(lines)
