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
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def library_file(path: str, library: Library, roles: dict[str, str | None], partial: bool) -> dict[str, dict[str, Any]]:
    """The stage tables of one stages.toml, checked. `partial` is a project file: it may leave required keys out."""
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
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
    if not raw:
        raise ValueError("has no value")
    if key == "after":
        if not (raw.startswith("[") and raw.endswith("]")):
            raise ValueError(f"must be a list in brackets, as [a, b] or [], not {raw!r}")
        names = [n.strip() for n in raw[1:-1].split(",")] if raw[1:-1].strip() else []
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
        with open(wf.path, encoding="utf-8") as fh:
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
            keys[key] = (number, re.split(r"(?:^|\s)#", raw.strip(), maxsplit=1)[0].strip() if key != "description" else raw.strip())
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
        merged[stage_id] = Item(item.path, item.line, {**current.fields, **item.fields})
    return list(merged.values())


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
            wf.errors.append(f"{where(first.path, first.line)} stage {first.id!r}: with decides: true no other stage may be listed; "
                             "its result names the rest")


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
