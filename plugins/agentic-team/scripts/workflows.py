"""Workflow files: the stage library, the frontmatter parser and the checks of every workflow.

A workflow is a markdown file with a restricted YAML frontmatter (docs/design/workflow-templates.md, section 4):

    ---
    name: feature
    description: One or two sentences.
    extends: other-workflow            # optional, project files only
    stages:
      - {id: prd}
      - {id: spec, after: [prd], optional: true}
    ---
    ## When to use

There is no YAML library. The parser reads flat `key: value` lines and one `stages:` key whose items are flow maps, one
per line. Every problem is one string that starts with `<file>:<line>:`. This module imports nothing from run.py or
config.py, so both can use it; the caller passes the roles it knows as {name: error or None}.
"""

import dataclasses
import glob
import hashlib
import math
import os
import random
import re
import tomllib
from typing import Any

NAME = re.compile(r"[a-z0-9-]+")
TOKEN = re.compile(r"[^\s,\[\]{}:#]+")
VERIFY_KINDS = ("code", "schema", "design-doc")
APPROVALS = ("auto", "manager", "human")
WORKFLOW_KEYS = ("name", "description", "extends", "stages")
STAGE_KEYS = ("id", "type", "role", "verify", "approval", "estimate", "after", "optional", "split", "decides")
STAGE_FLAGS = ("optional", "split", "decides")
LIBRARY_KEYS = ("role", "verify", "approval", "estimate", "scope", "verify_cmd", "acceptance")
LIBRARY_REQUIRED = ("role", "verify", "approval")
SCOPE_FIELDS = ("design_dir", "slug")  # the placeholders that a library `scope` may hold
DESCRIPTION_MAX = 300  # characters
BODY_WORDS_MAX = 600  # a longer body gets a warning, never a refusal
HARD_RULE_STAGES = ("spec",)  # the stage that a hard rule forces; the library and some workflow must have it
LIBRARY_FILE = "stages.toml"


def plugin_folder(plugin_root: str) -> str:
    return os.path.join(plugin_root, "templates", "workflows")


def project_folder(root: str) -> str:
    return os.path.join(root, ".claude", "agentic-team", "workflows")


def where(path: str, line: int | None) -> str:
    return f"{path}:{line}:" if line else f"{path}:"


# ------------------------------------------------------------------- library

class Library:
    """The stage types: {type: {role, verify, approval, estimate, scope, verify_cmd, acceptance}}, the plugin's with the
    project's fields laid over them. `errors` holds the problems of both stages.toml files."""

    def __init__(self) -> None:
        self.types: dict[str, dict[str, Any]] = {}
        self.errors: list[str] = []


def toml_line(path: str, table: str, key: str | None = None) -> int | None:
    """The line of `[stage.<table>]` in a TOML file, or of `key` inside that table; None when it is not found."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    header = re.compile(rf"\s*\[\s*stage\s*\.\s*[\"']?{re.escape(table)}[\"']?\s*\]")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None or key is None:
        return None if start is None else start + 1
    for i in range(start + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            break
        if re.match(rf"\s*{re.escape(key)}\s*=", lines[i]):
            return i + 1
    return start + 1


def number_ok(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def unquote(raw: str) -> str:
    """`raw` without one pair of matching quotes around it, stripped."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1].strip()
    return raw


def library_file(path: str, library: Library, roles: dict[str, str | None], partial: bool) -> dict[str, dict[str, Any]]:
    """The stage tables of one stages.toml, checked. `partial` is a project file: it may leave required keys out."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = tomllib.loads(fh.read())
    except OSError as exc:
        library.errors.append(f"{path}: cannot read the file: {exc}")
        return {}
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        library.errors.append(f"{path}: not valid TOML: {exc}")
        return {}
    tables = data.pop("stage", {})
    for extra in data:
        library.errors.append(f"{path}: unknown top-level key {extra!r}; the file holds `[stage.<type>]` tables only")
    if not isinstance(tables, dict):
        library.errors.append(f"{path}: `stage` must be a table of `[stage.<type>]` tables")
        return {}
    found: dict[str, dict[str, Any]] = {}
    for kind, table in tables.items():
        def bad(message: str, key: str | None = None) -> None:
            library.errors.append(f"{where(path, toml_line(path, kind, key))} [stage.{kind}]{' ' + key + ':' if key else ''} {message}")
        if not NAME.fullmatch(kind):
            bad("the type name must be lowercase letters, digits and -")
            continue
        if not isinstance(table, dict):
            bad("must be a table")
            continue
        clean: dict[str, Any] = {}
        for key, value in table.items():
            problem = library_value(key, value, roles)
            if problem:
                bad(problem, key)
            else:
                clean[key] = value
        if not partial:
            for key in LIBRARY_REQUIRED:
                if key not in table:
                    bad(f"no `{key}`", None)
        found[kind] = clean
    return found


def library_value(key: str, value: Any, roles: dict[str, str | None]) -> str | None:
    """The problem with one library value, or None."""
    if key not in LIBRARY_KEYS:
        return f"unknown key; the keys are {', '.join(LIBRARY_KEYS)}"
    if key == "role":
        return role_problem(value, roles)
    if key == "verify":
        return None if value in VERIFY_KINDS else f"must be one of {', '.join(VERIFY_KINDS)}, not {value!r}"
    if key == "approval":
        return None if value in APPROVALS else f"must be one of {', '.join(APPROVALS)}, not {value!r}"
    if key == "estimate":
        return None if number_ok(value) else f"must be a number of hours above 0, not {value!r}"
    if key == "acceptance":
        ok = isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value)
        return None if ok else "must be a list of non-empty lines"
    if not isinstance(value, str) or not value.strip():
        return "must be a non-empty string"
    if key == "scope" and value != "instance":
        names = re.findall(r"\{([^{}]*)\}", value)
        unknown = [n for n in names if n not in SCOPE_FIELDS]
        if unknown:
            return f"unknown placeholder {{{unknown[0]}}}; the placeholders are {', '.join('{' + f + '}' for f in SCOPE_FIELDS)}"
    return None


def role_problem(value: Any, roles: dict[str, str | None]) -> str | None:
    if not isinstance(value, str) or value not in roles:
        known = ", ".join(sorted(roles)) or "none"
        return f"no role named {value!r}; available roles: {known}"
    if roles[value]:
        return f"role {value} is broken: {roles[value]}"
    return None


def load_library(plugin_root: str, root: str, roles: dict[str, str | None]) -> Library:
    """The plugin's stage types with the project's laid over them: a project table adds a type, or overrides its fields."""
    library = Library()
    plugin_path = os.path.join(plugin_folder(plugin_root), LIBRARY_FILE)
    project_path = os.path.join(project_folder(root), LIBRARY_FILE)
    if os.path.isfile(plugin_path):
        library.types = library_file(plugin_path, library, roles, partial=False)
    else:
        library.errors.append(f"{plugin_path}: the plugin's stage library is missing")
    if os.path.isfile(project_path):
        for kind, fields in library_file(project_path, library, roles, partial=True).items():
            new = kind not in library.types
            library.types.setdefault(kind, {}).update(fields)
            for key in LIBRARY_REQUIRED if new else ():
                if key not in fields:
                    library.errors.append(f"{where(project_path, toml_line(project_path, kind))} [stage.{kind}] no `{key}`: a new type "
                                          f"needs {', '.join(LIBRARY_REQUIRED)}")
    return library


# ------------------------------------------------------------------- workflow files

@dataclasses.dataclass
class Item:
    """One `- {...}` line of a stages list: the fields it sets."""
    path: str
    line: int
    fields: dict[str, Any]


@dataclasses.dataclass
class Stage:
    """A stage after the library is applied: every value is final."""
    id: str
    type: str
    role: str
    verify: str
    approval: str
    estimate: float | None
    scope: str
    verify_cmd: str | None
    acceptance: list[str]
    after: list[str]
    optional: bool
    split: bool
    decides: bool
    path: str
    line: int

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class Workflow:
    """One workflow file. `source` is "plugin" or "project"; `overrides` marks a project file that hides a plugin file of
    the same name. read_workflow fills the rest and sets `errors` (each starts with `<file>:<line>:`) or `warnings`."""

    def __init__(self, name: str, path: str, source: str, overrides: bool = False, hidden: "Workflow | None" = None) -> None:
        self.name, self.path, self.source, self.overrides, self.hidden = name, path, source, overrides, hidden
        self.description = ""
        self.extends: str | None = None
        self.parent: Workflow | None = None
        self.items: list[Item] = []
        self.dropped = 0  # stage lines that parse_file refused; each has an error already
        self.stages: list[Stage] = []
        self.body = ""
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def where(self) -> str:
        if self.parent:
            return f"project, extends {self.parent.source}:{self.parent.name}"
        return "project, overrides plugin" if self.overrides else self.source

    @property
    def shown_path(self) -> str:
        return f"{self.path}, extends {self.parent.path}" if self.parent else self.path

    @property
    def chain(self) -> str:
        return chain_text(self.stages)

    @property
    def words(self) -> int:
        return len(self.body.split())


def chain_text(stages: list[Stage]) -> str:
    """`prd → ux? → spec → impl* → test`: `?` marks an optional stage and `*` a splittable one."""
    return " → ".join(s.id + ("?" if s.optional else "") + ("*" if s.split else "") for s in stages)


def split_top(text: str) -> list[str]:
    """`text` cut at the commas that are outside brackets."""
    parts, depth, current = [], 0, ""
    for char in text:
        depth += (char == "[") - (char == "]")
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    return parts + [current]


def flow_value(key: str, raw: str) -> Any:
    """The value of one stage field; ValueError names a problem."""
    raw = raw.strip()
    if key != "after":
        raw = unquote(raw)
    if not raw:
        raise ValueError("has no value")
    if key == "after":
        if not (raw.startswith("[") and raw.endswith("]")):
            raise ValueError(f"must be a list in brackets, as [a, b] or [], not {raw!r}")
        names = [unquote(n) for n in raw[1:-1].split(",")] if raw[1:-1].strip() else []
        for name in names:
            if not NAME.fullmatch(name):
                raise ValueError(f"{name!r} is not a stage id (lowercase letters, digits and -)")
        if len(set(names)) != len(names):
            raise ValueError("lists a stage twice")
        return names
    if key in STAGE_FLAGS:
        if raw not in ("true", "false"):
            raise ValueError(f"must be true or false, not {raw!r}")
        return raw == "true"
    if key == "estimate":
        try:
            number = float(raw)
        except ValueError:
            raise ValueError(f"must be a number of hours above 0, not {raw!r}") from None
        if not number_ok(number):
            raise ValueError(f"must be a number of hours above 0, not {raw!r}")
        return int(number) if number == int(number) else number
    if not TOKEN.fullmatch(raw):
        raise ValueError(f"must be one bare word, not {raw!r}")
    if key in ("id", "type") and not NAME.fullmatch(raw):
        raise ValueError(f"{raw!r} must be lowercase letters, digits and -")
    return raw


def flow_map(text: str) -> dict[str, Any]:
    """The fields of one `{key: value, ...}` text; ValueError names a problem."""
    text = text.strip()
    if not text.startswith("{"):
        raise ValueError("a stage must be a flow map on one line, as `- {id: impl, after: [spec]}`")
    depth, end = 0, None
    for i, char in enumerate(text):
        depth += (char == "{") - (char == "}")
        if depth == 0:
            end = i
            break
    if end is None:
        raise ValueError("the stage has no closing } on its line; a stage is one line")
    rest = text[end + 1:].strip()
    if rest and not rest.startswith("#"):
        raise ValueError(f"text after the closing }}: {rest!r}")
    inner = text[1:end]
    fields: dict[str, Any] = {}
    if not inner.strip():
        return fields
    for part in split_top(inner):
        key, colon, raw = part.partition(":")
        key = key.strip()
        if not colon:
            raise ValueError(f"expected `key: value`, found {part.strip()!r}")
        if key not in STAGE_KEYS:
            raise ValueError(f"unknown stage key {key!r}; the keys are {', '.join(STAGE_KEYS)}")
        if key in fields:
            raise ValueError(f"{key} is set twice")
        try:
            fields[key] = flow_value(key, raw)
        except ValueError as exc:
            raise ValueError(f"{key}: {exc}") from None
    return fields


def parse_file(wf: Workflow, roles: dict[str, str | None]) -> dict[str, tuple[int, str]] | None:
    """Read wf.path: set wf.items and wf.body, add each syntax problem to wf.errors, and return {key: (line, text)} of the
    top-level frontmatter keys. None when the file has no readable frontmatter."""
    try:
        with open(wf.path, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        wf.errors.append(f"{wf.path}: cannot read the file: {exc}")
        return None
    if not lines or lines[0].strip() != "---":
        wf.errors.append(f"{where(wf.path, 1)} the file must start with a --- line that opens the frontmatter")
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        wf.errors.append(f"{where(wf.path, 1)} the frontmatter has no closing --- line")
        return None
    wf.body = "\n".join(lines[end + 1:]).strip()
    keys: dict[str, tuple[int, str]] = {}
    in_stages = False
    for number, line in enumerate(lines[1:end], 2):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if line[0] in " \t":
            if not (in_stages and text.startswith("-")):
                wf.errors.append(f"{where(wf.path, number)} an indented line belongs under `stages:` and starts with `- `")
                wf.dropped += 1
                continue
            try:
                fields = flow_map(text[1:])
            except ValueError as exc:
                wf.errors.append(f"{where(wf.path, number)} {exc}")
                wf.dropped += 1
                continue
            problem = item_problem(fields, roles)
            if problem:
                wf.errors.append(f"{where(wf.path, number)} {problem}")
                wf.dropped += 1
                continue
            wf.items.append(Item(wf.path, number, fields))
            continue
        in_stages = False
        key, colon, raw = text.partition(":")  # the first colon only: a description holds more
        key = key.strip()
        if not colon:
            wf.errors.append(f"{where(wf.path, number)} expected `key: value`")
        elif key not in WORKFLOW_KEYS:
            wf.errors.append(f"{where(wf.path, number)} unknown key {key!r}; the keys are {', '.join(WORKFLOW_KEYS)}")
        elif key in keys:
            wf.errors.append(f"{where(wf.path, number)} {key} is set twice (first on line {keys[key][0]})")
        elif key == "stages":
            keys[key] = (number, raw.strip())
            in_stages = True
            if raw.strip():
                wf.errors.append(f"{where(wf.path, number)} stages: put one `- {{id: ...}}` line under `stages:`, not a value on this line")
        else:
            value = raw.strip() if key == "description" else re.split(r"(?:^|\s)#", raw.strip(), maxsplit=1)[0].strip()
            keys[key] = (number, unquote(value))
    return keys


def item_problem(fields: dict[str, Any], roles: dict[str, str | None]) -> str | None:
    """The problem with the values of one stage line that the parser cannot see, or None."""
    if "id" not in fields:
        return "a stage needs an `id`"
    if "role" in fields and (problem := role_problem(fields["role"], roles)):
        return f"role: {problem}"
    if "verify" in fields and fields["verify"] not in VERIFY_KINDS:
        return f"verify must be one of {', '.join(VERIFY_KINDS)}, not {fields['verify']!r}"
    if "approval" in fields and fields["approval"] not in APPROVALS:
        return f"approval must be one of {', '.join(APPROVALS)}, not {fields['approval']!r}"
    return None


def check_header(wf: Workflow, keys: dict[str, tuple[int, str]]) -> None:
    """Check name, description, extends and the number of stage lines."""
    stem = os.path.basename(wf.path)[:-3]
    if not NAME.fullmatch(stem):
        wf.errors.append(f"{where(wf.path, None)} the file name must be lowercase letters, digits and -")
    if "name" not in keys or not keys["name"][1]:
        wf.errors.append(f"{where(wf.path, 1)} no `name` line; it must be {stem}")
    elif keys["name"][1] != stem:
        wf.errors.append(f"{where(wf.path, keys['name'][0])} name {keys['name'][1]!r} must be the file name, {stem!r}")
    if "description" not in keys or not keys["description"][1]:
        wf.errors.append(f"{where(wf.path, 1)} no `description` line: say in one or two sentences which work the workflow is for")
    else:
        line, text = keys["description"]
        wf.description = text
        if len(text) > DESCRIPTION_MAX:
            wf.errors.append(f"{where(wf.path, line)} description is {len(text)} characters; the limit is {DESCRIPTION_MAX}")
    if "extends" in keys:
        line, text = keys["extends"]
        if not NAME.fullmatch(text):
            wf.errors.append(f"{where(wf.path, line)} extends: {text!r} is not a workflow name")
        else:
            wf.extends = text
    if "stages" not in keys:
        wf.errors.append(f"{where(wf.path, 1)} no `stages:` key; a workflow needs at least one stage")
    elif not wf.items and not wf.dropped:
        wf.errors.append(f"{where(wf.path, keys['stages'][0])} stages: needs at least one `- {{id: ...}}` line")
    seen: dict[str, int] = {}
    for item in wf.items:
        stage_id = item.fields["id"]
        if stage_id in seen:
            wf.errors.append(f"{where(wf.path, item.line)} stage id {stage_id!r} is listed twice (first on line {seen[stage_id]})")
        seen.setdefault(stage_id, item.line)


def workflow_files(plugin_root: str, root: str) -> dict[str, Workflow]:
    """{name: Workflow} for every workflow file, not yet read. A project file hides the plugin file of the same name."""
    found: dict[str, Workflow] = {}
    for source, folder in (("plugin", plugin_folder(plugin_root)), ("project", project_folder(root))):
        for path in sorted(glob.glob(os.path.join(glob.escape(folder), "*.md"))):
            name = os.path.basename(path)[:-3]
            found[name] = Workflow(name, path, source, overrides=name in found, hidden=found.get(name))
    return found


def merge_parent(wf: Workflow, parent: Workflow) -> list[Item]:
    """The stage lines of `parent`, each with the fields that a stage of `wf` with the same id sets; the new stages of `wf`
    follow. A stage of the parent cannot be removed, or made optional."""
    merged = {item.fields["id"]: Item(item.path, item.line, dict(item.fields)) for item in parent.items}
    for item in wf.items:
        stage_id = item.fields["id"]
        if stage_id not in merged:
            merged[stage_id] = item
            continue
        current = merged[stage_id]
        if item.fields.get("optional") and not current.fields.get("optional"):
            wf.errors.append(f"{where(wf.path, item.line)} stage {stage_id!r} is required in {parent.name}; a workflow that extends "
                             "another cannot make a stage of it optional (it cannot remove one)")
            continue
        if "type" in item.fields and item.fields["type"] != current.fields.get("type", stage_id):
            wf.errors.append(f"{where(wf.path, item.line)} stage {stage_id!r} is {current.fields.get('type', stage_id)} in {parent.name}; a workflow "
                             "that extends another cannot change the type of a stage of it (that would remove the stage)")
            continue
        if "after" in item.fields and not set(current.fields.get("after", [])) <= set(item.fields["after"]):
            lost = sorted(set(current.fields.get("after", [])) - set(item.fields["after"]))
            wf.errors.append(f"{where(wf.path, item.line)} stage {stage_id!r}: after: must keep the stages that {parent.name} lists "
                             f"({', '.join(lost)} missing); a workflow that extends another can add edges, not remove them")
            continue
        merged[stage_id] = Item(item.path, item.line, {**current.fields, **item.fields})
    return list(merged.values())


def later_in_child(wf: Workflow, parent: Workflow) -> None:
    """A stage line of a child file may follow a stage of the parent, or a stage listed before it in the child file."""
    known = {item.fields["id"] for item in parent.items}
    for item in wf.items:
        for name in item.fields.get("after", []):
            if name not in known and name in {i.fields["id"] for i in wf.items} and name != item.fields["id"]:
                wf.errors.append(f"{where(wf.path, item.line)} stage {item.fields['id']!r}: after: {name!r} is listed later; a stage may "
                                 "follow only stages that are listed before it")
        known.add(item.fields["id"])


def in_order(items: list[Item]) -> list[Item]:
    """The merged stage lines, each after the stages it follows (the stable order); a cycle leaves the rest in place."""
    placed: list[Item] = []
    pending = list(items)
    names = {i.fields["id"] for i in items}
    while pending:
        ready = next((i for i in pending if all(a in {p.fields["id"] for p in placed} or a not in names
                                                 for a in i.fields.get("after", []))), pending[0])
        placed.append(ready)
        pending.remove(ready)
    return placed


def apply_library(wf: Workflow, items: list[Item], library: Library) -> None:
    """Turn the stage lines into Stage objects with the library values laid under them."""
    for item in items:
        fields = item.fields
        kind = fields.get("type", fields["id"])
        base = library.types.get(kind)
        if base is None:
            hint = "name one with `type:`" if "type" not in fields else "check the `type:` value"
            known = ", ".join(sorted(library.types)) or "none"
            wf.errors.append(f"{where(item.path, item.line)} stage {fields['id']!r} is not a stage type ({kind!r} is not in the library; "
                             f"the types are {known}); {hint}")
            continue
        merged = {**base, **{k: v for k, v in fields.items() if k in LIBRARY_KEYS}}
        if any(k not in merged for k in LIBRARY_REQUIRED):
            continue  # the library error already says so
        wf.stages.append(Stage(
            id=fields["id"], type=kind, role=merged["role"], verify=merged["verify"], approval=merged["approval"],
            estimate=merged.get("estimate"), scope=merged.get("scope", "instance"), verify_cmd=merged.get("verify_cmd"),
            acceptance=list(merged.get("acceptance", [])), after=list(fields.get("after", [])),
            optional=bool(fields.get("optional", False)), split=bool(fields.get("split", False)),
            decides=bool(fields.get("decides", False)), path=item.path, line=item.line))


def check_graph(wf: Workflow) -> None:
    """The checks over the whole stage list: dangling `after`, a cycle, a required stage, `split`, `decides`."""
    ids = {s.id for s in wf.stages}
    by_id = {s.id: s for s in wf.stages}
    position = {s.id: i for i, s in enumerate(wf.stages)}
    for stage in wf.stages:
        for name in stage.after:
            if name == stage.id:
                wf.errors.append(f"{where(stage.path, stage.line)} stage {stage.id!r} comes after itself")
            elif name not in ids:
                wf.errors.append(f"{where(stage.path, stage.line)} stage {stage.id!r}: after: {name!r} is not a stage of this workflow "
                                 f"(the stages are {', '.join(s.id for s in wf.stages)})")
    cycle = find_cycle({s.id: [n for n in s.after if n in ids] for s in wf.stages})
    if cycle:
        wf.errors.append(f"{where(by_id[cycle[0]].path, by_id[cycle[0]].line)} the stages form a cycle: {' → '.join(cycle)}")
    else:
        for stage in wf.stages:
            for name in stage.after:
                if name in ids and name != stage.id and position[name] > position[stage.id]:
                    wf.errors.append(f"{where(stage.path, stage.line)} stage {stage.id!r}: after: {name!r} is listed later; a stage may "
                                     "follow only stages that are listed before it")
    if wf.stages and all(s.optional for s in wf.stages):
        wf.errors.append(f"{where(wf.stages[0].path, wf.stages[0].line)} every stage is optional; a workflow needs at least one required stage")
    for stage in wf.stages:
        if stage.split and stage.verify != "code":
            wf.errors.append(f"{where(stage.path, stage.line)} stage {stage.id!r}: split is only for a stage whose verify is code, "
                             f"not {stage.verify}")
    deciders = [s for s in wf.stages if s.decides]
    if deciders:
        first = deciders[0]
        if len(deciders) > 1:
            wf.errors.append(f"{where(deciders[1].path, deciders[1].line)} only one stage may set decides: true")
        elif first.after:
            wf.errors.append(f"{where(first.path, first.line)} stage {first.id!r}: decides: true is for a root stage; it has `after`")
        elif len(wf.stages) > 1:
            other = next(s for s in wf.stages if s is not first)
            wf.errors.append(f"{where(other.path, other.line)} stage {other.id!r}: with decides: true no other stage may be listed "
                             f"(stage {first.id!r} decides); its result names the rest")


def find_cycle(edges: dict[str, list[str]]) -> list[str]:
    """One cycle of the graph, as [a, b, ..., a], or []."""
    state: dict[str, int] = {}  # 1 on the path, 2 done
    path: list[str] = []

    def visit(node: str) -> list[str]:
        state[node] = 1
        path.append(node)
        for nxt in edges.get(node, []):
            if state.get(nxt) == 1:
                return path[path.index(nxt):] + [nxt]
            if nxt not in state and (found := visit(nxt)):
                return found
        path.pop()
        state[node] = 2
        return []

    for node in edges:
        if node not in state and (found := visit(node)):
            return found
    return []


def read_workflow(wf: Workflow, found: dict[str, Workflow], library: Library, roles: dict[str, str | None]) -> None:
    """Parse `wf` and, when it extends a parent, merge the parent in. Every problem goes to wf.errors."""
    keys = parse_file(wf, roles)
    if keys is None:
        return
    check_header(wf, keys)
    if wf.errors:
        return
    items = wf.items
    if wf.extends:
        if wf.source != "project":
            wf.errors.append(f"{where(wf.path, keys['extends'][0])} extends: only a project workflow can extend another workflow")
            return
        parent = wf.hidden if wf.extends == wf.name else found.get(wf.extends)
        if parent is None or parent is wf:
            names = ", ".join(sorted(found)) or "none"
            wf.errors.append(f"{where(wf.path, keys['extends'][0])} extends: no workflow named {wf.extends!r} to extend; available workflows: {names}")
            return
        parent = Workflow(parent.name, parent.path, parent.source)
        parent_keys = parse_file(parent, roles)
        if parent_keys is not None:
            check_header(parent, parent_keys)
        if parent.errors:
            wf.errors.append(f"{where(wf.path, keys['extends'][0])} extends: the parent workflow file {parent.path} is broken: {parent.errors[0]}")
            return
        if parent.extends:
            wf.errors.append(f"{where(wf.path, keys['extends'][0])} extends: the parent workflow {parent.name} extends {parent.extends} "
                             "itself; a workflow extends one level only")
            return
        items = merge_parent(wf, parent)
        wf.parent = parent
        later_in_child(wf, parent)
        items = in_order(items)
        if wf.errors:
            return
    apply_library(wf, items, library)
    if not wf.errors:
        check_graph(wf)
    if wf.words > BODY_WORDS_MAX:
        wf.warnings.append(f"workflow {wf.name} ({wf.shown_path}) body is {wf.words} words; over {BODY_WORDS_MAX} words the Manager "
                           "reads it less closely; shorten it")


# ------------------------------------------------------------------- catalog

class Catalog:
    """Every workflow and the stage library, read and checked. `errors` holds problems that belong to no one file."""

    def __init__(self, library: Library, workflows: dict[str, Workflow]) -> None:
        self.library, self.workflows = library, workflows
        self.errors: list[str] = []

    @property
    def problems(self) -> list[str]:
        found = list(self.library.errors)
        for wf in self.workflows.values():
            found += wf.errors
        return found + self.errors


def load(plugin_root: str, root: str, roles: dict[str, str | None]) -> Catalog:
    """Read the stage library and every workflow file (the plugin's, then the project's) and check them against `roles`."""
    library = load_library(plugin_root, root, roles)
    found = workflow_files(plugin_root, root)
    for wf in found.values():
        read_workflow(wf, found, library, roles)
    catalog = Catalog(library, found)
    if not library.errors:
        for kind in HARD_RULE_STAGES:
            if kind not in library.types:
                catalog.errors.append(f"{plugin_folder(plugin_root)}: the stage library has no `{kind}` type, which a hard rule needs")
            elif not any(s.type == kind for w in found.values() if not w.errors for s in w.stages):
                catalog.errors.append(f"{plugin_folder(plugin_root)}: no workflow has a `{kind}` stage, which a hard rule needs")
    return catalog


# ------------------------------------------------------------------- pick prompt

UNSURE_TEXT = "none of the workflows fits, or you cannot tell which fits"


def pick_order(names: list[str], seed: int) -> list[str]:
    """The workflow names and `unsure` in the order that `seed` gives. The same seed gives the same order."""
    options = sorted(names) + ["unsure"]
    random.Random(seed).shuffle(options)
    return options


def pick_prompt(catalog: Catalog, seed: int, title: str, notes: str = "", scope: str = "") -> tuple[str, list[str]]:
    """(the pick prompt, the answer options in the order shown). The prompt holds the task text and the descriptions, never a
    code census."""
    order = pick_order(list(catalog.workflows), seed)
    lines = ["Pick the workflow for the piece of work below. Read the task, then the workflows. Choose the one whose "
             "description fits best. If none fits, or you cannot tell, choose unsure.", "", f"Task: {title}"]
    if notes.strip():
        lines += ["Notes:", notes.strip()]
    if scope.strip():
        lines.append(f"Scope: {scope.strip()}")
    lines += ["", "Workflows:"]
    for letter, name in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", order):
        lines.append(f"{letter}. {name}: {UNSURE_TEXT if name == 'unsure' else catalog.workflows[name].description}")
    lines += ["", "Answer with exactly these two lines:", "PICK: <name|unsure>", "WHY: <one line>"]
    return "\n".join(lines) + "\n", order


# ------------------------------------------------------------------- expansion

@dataclasses.dataclass
class Plan:
    """The stages that one instance creates: `stages` in creation order (every stage comes after its upstream stages),
    `after` the upstream stage ids of each with the skipped stages contracted away, and `optional` what happened to each
    optional stage: `with`, `skipped` (named in --skip) or `default-skipped` (named in neither)."""
    stages: list[Stage]
    after: dict[str, list[str]]
    optional: dict[str, str]


def contracted(stage_id: str, by_id: dict[str, Stage], kept: set[str]) -> list[str]:
    """The upstream stages of `stage_id` that exist: an `after` stage that is skipped is replaced by its own upstream stages."""
    found: list[str] = []
    for name in by_id[stage_id].after:
        for real in [name] if name in kept else contracted(name, by_id, kept):
            if real not in found:
                found.append(real)
    return found


def build_plan(wf: Workflow, with_ids: list[str], skip_ids: list[str]) -> Plan:
    """The plan of `wf`: every required stage and each optional stage in `with_ids`; the others are left out and their edges
    contracted. ValueError names a stage that --with or --skip cannot name."""
    by_id = {s.id: s for s in wf.stages}
    optional = [s.id for s in wf.stages if s.optional]
    for flag, ids in (("--with", with_ids), ("--skip", skip_ids)):
        for name in ids:
            if name not in by_id:
                raise ValueError(f"{flag} {name}: workflow {wf.name} has no stage {name}; its stages are {', '.join(by_id)}")
            if not by_id[name].optional:
                raise ValueError(f"{flag} {name}: stage {name} is required in {wf.name}; only an optional stage can be named "
                                 f"({', '.join(optional) or 'this workflow has none'})")
    both = sorted(set(with_ids) & set(skip_ids))
    if both:
        raise ValueError(f"{both[0]} is named in both --with and --skip")
    mode = {name: "with" if name in with_ids else "skipped" if name in skip_ids else "default-skipped" for name in optional}
    kept = {s.id for s in wf.stages if not s.optional or mode[s.id] == "with"}
    ordered: list[Stage] = []
    after = {s.id: contracted(s.id, by_id, kept) for s in wf.stages if s.id in kept}
    pending = [s for s in wf.stages if s.id in kept]
    while pending:  # list order already puts a stage after its upstream stages; this keeps a hand-built plan sound too
        ready = next(s for s in pending if all(a in {o.id for o in ordered} for a in after[s.id]))
        ordered.append(ready)
        pending.remove(ready)
    return Plan(ordered, after, mode)


def stage_notes(body: str, stage_id: str) -> str:
    """The `### <stage id>` subsection of the `## Stage notes` section of a workflow body, cut at 150 words; "" when there is none."""
    section = re.search(r"(?ms)^## Stage notes[ \t]*\n(.*?)(?=^## |\Z)", body)
    if not section:
        return ""
    sub = re.search(rf"(?ms)^### {re.escape(stage_id)}[ \t]*\n(.*?)(?=^### |\Z)", section.group(1))
    text = sub.group(1).strip() if sub else ""
    words = text.split()
    return " ".join(words[:150]) if len(words) > 150 else text


def file_version(path: str) -> str:
    """The first 12 hex digits of the SHA-1 of a workflow file: the `version` of a workflow record."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()[:12]
    except OSError:
        return ""


def slug(text: str, limit: int = 40) -> str:
    """Lowercase letters and digits of `text`, joined by -, at most `limit` characters."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-") or "work"


def glob_regex(pattern: str) -> "re.Pattern[str]":
    """A path glob as a regex: `**` crosses folders, `*` and `?` stay inside one."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out)


def rule_matches(rule: dict[str, Any], paths: set[str], area: Any) -> bool:
    """A `[[workflow_rule]]` matches when a write path of the SCOPE (a directory counts as every path under it) fits one of its
    `match_paths` globs, or lies above a glob (the glob's literal text before its first wildcard is under that directory), or the task's `area` is one of its `match_area` names. Title words never match."""
    areas = rule.get("match_area") or []
    if areas and str(area or "").strip().lower() in {a.strip().lower() for a in areas}:
        return True
    for pattern in rule.get("match_paths") or []:
        regex = glob_regex(pattern)
        prefix = re.split(r"[*?\[]", pattern, maxsplit=1)[0]  # the literal text before the first wildcard
        for p in paths:
            if regex.fullmatch(p) or regex.fullmatch(p.rstrip("/") + "/x"):
                return True
            if prefix and prefix.startswith(p.rstrip("/") + "/"):  # a SCOPE directory above the glob holds paths that fit it
                return True
    return False


# ------------------------------------------------------------------- the pick

def weight(wf: Workflow, with_ids: list[str] | None = None) -> tuple[int, int, str]:
    """The order of the workflows from light to heavy, in one definition: the number of stages in the plan that would be
    created (every required stage and each optional stage in `with_ids`), then the number of those whose approval is not
    `auto`, then the name."""
    plan = build_plan(wf, list(with_ids or []), [])
    return (len(plan.stages), sum(1 for s in plan.stages if s.approval != "auto"), wf.name)


def usable(workflows: dict[str, Workflow]) -> dict[str, Workflow]:
    return {n: w for n, w in workflows.items() if not w.errors}


def deciding(workflows: dict[str, Workflow]) -> list[str]:
    """The names of the workflows with a `decides` stage (figure-it-out): outside the light-to-heavy order."""
    return sorted(n for n, w in usable(workflows).items() if any(s.decides for s in w.stages))


def parse_answer(text: str, names: list[str]) -> str:
    """The workflow name, or `unsure`, in one typed answer: `feature`, `PICK: feature` or a `PICK:` line inside more text.
    ValueError names what is wrong."""
    raw = (text or "").strip()
    line = next((l for l in raw.splitlines() if re.match(r"(?i)\s*pick\s*:", l)), raw.splitlines()[0] if raw else "")
    value = re.sub(r"(?i)^\s*pick\s*:", "", line).strip().strip("`*\"'. ").lower()
    if value == "unsure" or value in names:
        return value
    raise ValueError(f"{value or 'an empty answer'!r} is not a workflow name or unsure; the workflows are {', '.join(sorted(names))}")


@dataclasses.dataclass
class Resolution:
    """`workflow`: the chosen name. `rule`: why (agree, fewer-stages, more-stages, name-over-unsure, named-over-deciding,
    both-unsure, when-unsure-<mode>). `unsure`: True when the answers did not simply agree on a name."""
    workflow: str
    rule: str
    unsure: bool


def resolve_pick(workflows: dict[str, Workflow], first: str, second: str, when_unsure: str = "lighter") -> Resolution:
    """Resolve the two typed answers (names or `unsure`), as the spec's table says.
    - Both name the same workflow: it.
    - Two different names: the lighter by `weight`; `heavier` takes the heavier; `figure-it-out` takes the deciding workflow.
      A deciding workflow loses to a named one that is not deciding.
    - A name and `unsure`: the name; `figure-it-out` takes the deciding workflow.
    - Both `unsure`: the deciding workflow (`heavier` takes the heaviest, and so does the lightest when none decides)."""
    pool = usable(workflows)
    decides = deciding(workflows)
    plain = {n: w for n, w in pool.items() if n not in decides}
    ordered = sorted(plain.values(), key=weight)
    if first == second and first != "unsure":
        return Resolution(first, "agree", False)
    if when_unsure == "figure-it-out" and decides:
        return Resolution(decides[0], "when-unsure-figure-it-out", True)
    if first == "unsure" and second == "unsure":
        if when_unsure == "heavier" and ordered:
            return Resolution(ordered[-1].name, "when-unsure-heavier", True)
        if decides:
            return Resolution(decides[0], "both-unsure", True)
        return Resolution(ordered[0].name, "both-unsure-lightest", True)
    if "unsure" in (first, second):
        return Resolution(first if second == "unsure" else second, "name-over-unsure", True)
    named = [n for n in (first, second) if n in plain]
    if len(named) == 1:
        return Resolution(named[0], "named-over-deciding", True)
    if not named:
        return Resolution(sorted((first, second))[0], "both-deciding", True)
    if when_unsure == "heavier":
        return Resolution(max(named, key=lambda n: weight(plain[n])), "more-stages", True)
    return Resolution(min(named, key=lambda n: weight(plain[n])), "fewer-stages", True)


# ------------------------------------------------------------------- hard rules

def rule_kind(wf: Workflow, kind: str) -> Stage | None:
    """The stage of `wf` that a rule's `require_stage` names: a stage whose id or type is `kind`."""
    return next((s for s in wf.stages if s.id == kind or s.type == kind), None)


def lightest_with(workflows: dict[str, Workflow], kinds: list[str]) -> Workflow | None:
    """The lightest workflow that has a stage for every kind in `kinds` (the stage is forced on when optional): fewest stages
    in the plan, then fewest approvals, then name (`weight`). A deciding workflow never qualifies."""
    best: tuple[tuple[int, int, str], Workflow] | None = None
    for name, wf in usable(workflows).items():
        if any(s.decides for s in wf.stages):
            continue
        found = [rule_kind(wf, k) for k in kinds]
        if any(s is None for s in found):
            continue
        key = weight(wf, [s.id for s in found if s and s.optional])
        if best is None or key < best[0]:
            best = (key, wf)
    return best[1] if best else None


def apply_rules(workflows: dict[str, Workflow], wf: Workflow, rules: list[dict[str, Any]], with_ids: list[str],
                skip_ids: list[str]) -> tuple[Workflow, list[str], list[dict[str, Any]]]:
    """(workflow, with_ids, applications) after the hard rules that matched (`rules`). Each application is a dict with the rule
    name, `action` and, for a `require_stage`, the stage id:
    - `satisfied`: the workflow requires the stage already;
    - `forced-with`: the stage is optional, and is now in `with_ids`;
    - `moved`: the workflow had no such stage; the work moved to the lightest one that has a stage for every rule (`from`, `to`);
    - `matched`: the rule asks no stage (it raises an approval or sets a risk);
    - `deferred-to-expand`: the workflow decides its own stages; `run.py stage expand` applies the rules.
    ValueError: a rule's stage is in `skip_ids`, or no workflow has the stages that the rules need."""
    if any(s.decides for s in wf.stages):
        return wf, with_ids, [{"rule": r["name"], "action": "deferred-to-expand"} for r in rules]
    kinds = [r["require_stage"] for r in rules if r.get("require_stage")]
    original, target = wf, wf
    if any(rule_kind(wf, k) is None for k in kinds):
        found = lightest_with(workflows, kinds)
        if found is None:
            raise ValueError(f"the rules that match need a stage of each of {', '.join(sorted(set(kinds)))}, and no workflow has them all")
        target = found
    forced = list(with_ids)
    applied: list[dict[str, Any]] = []
    for rule in rules:
        kind = rule.get("require_stage")
        if not kind:
            applied.append({"rule": rule["name"], "action": "matched"})
            continue
        stage = rule_kind(target, kind)
        assert stage is not None
        if stage.id in skip_ids:
            raise ValueError(f"--skip {stage.id}: rule {rule['name']} requires stage {stage.id}; a stage that a rule requires cannot be skipped")
        app: dict[str, Any] = {"rule": rule["name"], "stage": stage.id}
        if rule_kind(original, kind) is None:
            app.update(action="moved", **{"from": original.name, "to": target.name})
        else:
            app["action"] = "forced-with" if stage.optional and stage.id not in forced else "satisfied"
        if stage.optional and stage.id not in forced:
            forced.append(stage.id)
        applied.append(app)
    return target, forced, applied
