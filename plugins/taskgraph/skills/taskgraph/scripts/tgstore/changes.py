import json
from dataclasses import dataclass
from datetime import date

PRIORITIES = ("P0", "P1", "P2", "P3")  # highest first
DUE_KEYS = {"task": "due", "objective": "due", "milestone": "date", "decision": "decide_by", "external": "needed_by", "risk": "review", "issue": "due"}


def parse_date(value):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.isoformat() == value else None


def normal(value):
    return value if parse_date(value) else None


def priority_of(meta):
    # a priority is one of PRIORITIES; any other value in meta counts as none
    return meta.get("priority") if meta.get("priority") in PRIORITIES else None


def tracked(task):
    fields = {
        "title": task["title"], "status": task["status"], "type": task["type"], "parent": task["parent"], "notes": task["notes"],
        "start": task["start"], "due": task["due"], "promised": normal(task["meta"].get("promised")), "depends_on": task["depends_on"],
    }
    if priority_of(task["meta"]):
        fields["priority"] = priority_of(task["meta"])  # only a task that has one: a project without priorities journals what it always did
    skip = {"type", "start", "promised", "priority", *DUE_KEYS.values()}
    fields.update({f"meta.{k}": v for k, v in task["meta"].items() if k not in skip})
    return fields


@dataclass(frozen=True)
class Created:
    id: int
    project: str
    title: str
    fields: dict  # tracked() of the new task


@dataclass(frozen=True)
class Removed:
    id: int
    project: str
    title: str


@dataclass(frozen=True)
class FieldChange:
    id: int
    project: str
    field: str  # a key of tracked(); "meta.<key>" for a meta key
    old: object  # None when the field was missing: a meta key that was set has old None, one that was unset has new None
    new: object


@dataclass(frozen=True)
class ChangeSet:
    created: tuple = ()
    removed: tuple = ()
    changed: tuple = ()  # FieldChange, by task id and field name
    edges_added: tuple = ()  # (task_id, depends_on) over all tasks, including created ones
    edges_removed: tuple = ()  # including the edges of removed tasks

    def __bool__(self):
        return bool(self.created or self.removed or self.changed or self.edges_added or self.edges_removed)


def edges(tasks):
    return {(i, d) for i, t in tasks.items() for d in t["depends_on"]}


def changeset(before, after):
    created, removed, changed = [], [], []
    for i in sorted(before.keys() | after.keys()):
        if i not in before:
            created.append(Created(i, after[i]["project"], after[i]["title"], tracked(after[i])))
        elif i not in after:
            removed.append(Removed(i, before[i]["project"], before[i]["title"]))
        else:
            old, new = tracked(before[i]), tracked(after[i])
            for field in sorted(old.keys() | new.keys()):
                if old.get(field) != new.get(field):
                    changed.append(FieldChange(i, after[i]["project"], field, old.get(field), new.get(field)))
    old_edges, new_edges = edges(before), edges(after)
    return ChangeSet(tuple(created), tuple(removed), tuple(changed), tuple(sorted(new_edges - old_edges)), tuple(sorted(old_edges - new_edges)))


def event_rows(changes, ts):
    # One events row per created task, removed task and field change, in task id order.
    rows = [(c.id, c.project, ts, "created", None, json.dumps(c.title, ensure_ascii=False)) for c in changes.created]
    rows += [(r.id, r.project, ts, "removed", json.dumps(r.title, ensure_ascii=False), None) for r in changes.removed]
    rows += [(f.id, f.project, ts, f.field, *(json.dumps(v, ensure_ascii=False) for v in (f.old, f.new))) for f in changes.changed]
    return sorted(rows, key=lambda row: row[0])
