from datetime import date

DUE_KEYS = {"task": "due", "objective": "due", "milestone": "date", "decision": "decide_by", "external": "needed_by", "risk": "review", "issue": "due"}


def parse_date(value):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.isoformat() == value else None


def normal(value):
    return value if parse_date(value) else None


def tracked(task):
    fields = {
        "title": task["title"], "status": task["status"], "type": task["type"], "parent": task["parent"], "notes": task["notes"],
        "start": task["start"], "due": task["due"], "promised": normal(task["meta"].get("promised")), "depends_on": task["depends_on"],
    }
    skip = {"type", "start", "promised", *DUE_KEYS.values()}
    fields.update({f"meta.{k}": v for k, v in task["meta"].items() if k not in skip})
    return fields
