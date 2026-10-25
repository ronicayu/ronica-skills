# Agentic Team TOML Config Implementation Plan

**Goal:** Replace the Markdown project config (`.agentic-team.md`) with TOML
(`.agentic-team.toml`), read through one command, `scripts/config.py`. Agents
then fetch only the settings they need, defaults live in one place, and typos
are caught instead of being ignored.

**Status:** Implemented (Tasks 1-7; validation and live smoke test pass). Approved by the operator on 2026-10-24. Nothing uses
`.agentic-team.md` yet, so switch outright. There is no migration or
dual-format support.

**Architecture:** `config.py` merges the tracked `.agentic-team.toml` with an
optional, gitignored `.agentic-team.local.toml` (a deep merge; local keys
win), fills in defaults from one built-in table, validates the result, and
prints a value, a section, or the whole config. `brief.py` imports it instead
of parsing Markdown. The Manager and playbooks call `config.py get <key>`
instead of reading the file. Workers never read config; it reaches them
through the brief.

**Tech stack:** Python 3.11 or later, standard library only (`tomllib`,
`argparse`, `json`). Python cannot write TOML with the standard library, so
the setup skill edits the template text.

**Scope:** `plugins/agentic-team/` only, plus the root `README.md` and
`.gitignore`. Do not touch `.markdown-collab/` or unrelated staged changes.
Commit only when the operator asks.

---

## Current state (read first)

- Template: `plugins/agentic-team/templates/project-context.md`. It has
  `## Heading` sections with `- Field: value` lines. `TODO` means
  unfilled, `None` means not applicable, and `Default` means the Manager's
  default.
- Parser: `load_config()`, `cfg()`, and `is_set()` in
  `plugins/agentic-team/scripts/brief.py`. The local file is found by
  swapping `.md` for `.local.md`.
- Defaults table: the "Use these values when a config field says `Default`"
  table in `plugins/agentic-team/agents/manager.md`.
- Field reference: the "Configuration" section of
  `plugins/agentic-team/README.md`.
- Field names are used by:
  - `agents/manager.md`;
  - `playbooks/launch.md` (`Other overrides`, `Launch outside sandbox`);
  - `playbooks/drain.md` (`Progress tool`, `Restart steps`);
  - `playbooks/verify-and-close.md` (`Verifier`);
  - `playbooks/pickup.md`;
  - `skills/principle-decision-forks/SKILL.md` (`Full-autonomy grant`,
    `Always-pause gates`);
  - `skills/setup/SKILL.md`.
- The repository `.gitignore` has `.agentic-team.local.md` and
  `.agentic-team/`.

## Schema

Write this as `templates/agentic-team.toml`, replacing
`templates/project-context.md`. Keep the comments: they are the inline
help.

```toml
# Agentic Team project config. Copy to .agentic-team.toml in the repository
# root, or run /agentic-team:setup. Replace every "TODO". Omit a key to use
# its default. Never put credentials or secrets here. Private or
# machine-specific values go in .agentic-team.local.toml (gitignored); its
# keys override these. Field reference: plugins/agentic-team/README.md.

[taskgraph]
project = "TODO"            # required; `tg projects` lists names
# plan = "PLAN.md"          # supplemental plan, context only

[consultants]
sessions = []               # bare session names
restart = ""                # how to restart a missing consultant

[constraints]               # become FORBIDDEN in every brief
read_only = "TODO"          # "" when none applies
pinned_versions = "TODO"
do_not_send = "TODO"
do_not_modify = "TODO"
other = []

[serialization]
rules = []                  # "path or area: ordering rule"

[progress]
tool = ""                   # read-only progress command, if any

[autonomy]
grant = ""                  # "" means no standing full-autonomy grant
always_pause = []           # gates that always need the operator

[sessions]
# brief_template = ".agentic-team/brief.md"
# max_parallel = 4
# permission_mode = "auto"
# launch_outside_sandbox = false
# timezone = "Asia/Singapore"
# timezone_label = "SGT"

[models]
# mechanical = "haiku"
# implementation = { model = "sonnet", effort = "high" }
# judgement = "opus"
# verifier = "opus"         # default: a different model from the worker's

# [models.overrides]
# "data migration" = { model = "opus", effort = "high" }

[notifications]
# skill = "telegram-send:telegram-send"
```

Rules:

- **Missing values.** An omitted key takes its default, so `Default` and
  `None` disappear. An empty string or empty list means "does not apply".
- **`TODO`.** The exact string `"TODO"` marks an unfilled required value.
  `check` reports it. Constraints start as `TODO` because they affect safety,
  and a person must confirm `""` for each.
- **Model values.** Either a string (the model id) or a table
  `{ model = "...", effort = "..." }`. `config.py` turns both into
  `{"model": ..., "effort": ... or null}`.
- **Time zone.** `timezone` is an IANA name. When `timezone_label` is unset,
  derive the label from the zone, with
  `datetime.now(ZoneInfo(tz)).strftime("%Z")`.

### Field mapping (old to new)

| Old heading / field | New key |
|---|---|
| Taskgraph / Project | `taskgraph.project` |
| Taskgraph / Supplemental plan | `taskgraph.plan` |
| Consultants / Sessions | `consultants.sessions` (list) |
| Consultants / Restart steps | `consultants.restart` |
| Task-brief constraints / Read-only sources, Pinned versions, Do not send, Do not modify, Other | `constraints.read_only`, `.pinned_versions`, `.do_not_send`, `.do_not_modify`, `.other` (list) |
| Shared-file serialization / Rules | `serialization.rules` (list) |
| Progress / Progress tool | `progress.tool` |
| Autonomy / Full-autonomy grant, Always-pause gates | `autonomy.grant`, `autonomy.always_pause` (list) |
| Sessions / Brief template, Max parallel sessions, Permission mode, Launch outside sandbox, Time zone | `sessions.brief_template`, `.max_parallel`, `.permission_mode`, `.launch_outside_sandbox` (bool), `.timezone` + `.timezone_label` |
| Models / Mechanical, Implementation, Judgement, Verifier, Other overrides | `models.mechanical`, `.implementation`, `.judgement`, `.verifier`, `models.overrides` (table) |
| Notifications / Notify skill | `notifications.skill` |

### Defaults (move out of `manager.md` into `config.py`)

| Key | Default |
|---|---|
| `taskgraph.plan` | `""` |
| `sessions.brief_template` | `${CLAUDE_PLUGIN_ROOT}/templates/task-brief.md`; `config.py` resolves it to an absolute path |
| `sessions.max_parallel` | `4` |
| `sessions.permission_mode` | `"auto"` |
| `sessions.launch_outside_sandbox` | `false` |
| `sessions.timezone` | System zone (`/etc/localtime` target, else `"UTC"`) |
| `models.mechanical` | `{model: "haiku"}` |
| `models.implementation` | `{model: "sonnet", effort: "high"}` |
| `models.judgement` | `{model: "opus"}` |
| `models.verifier` | `null`, meaning "a different model from the worker's" (see `verify-and-close.md`) |
| `notifications.skill` | `""` |
| every list | `[]` |

---

## Task 1: Write `scripts/config.py`

**Files:** create `plugins/agentic-team/scripts/config.py` (executable,
standard library only).

**Interface:**

```text
config.py [--root DIR] get <dotted.key> [--json]
config.py [--root DIR] show [--json]
config.py [--root DIR] check
config.py [--root DIR] model <tier|work type>
```

- `--root` defaults to the current directory. Files are
  `<root>/.agentic-team.toml` and `<root>/.agentic-team.local.toml`.
- `get`: one value. Print a scalar plainly, or a table or list as JSON.
  `--json` always prints JSON. Exit 2 for an unknown key.
- `show`: the merged config with defaults filled in, as JSON or TOML-like
  text.
- `check`: list every problem, one per line, then exit 2 if there are any,
  else print `ok` and exit 0. Problems are:
  - a missing file (point to `/agentic-team:setup`);
  - a TOML syntax error, with its line number;
  - a `"TODO"` value;
  - `taskgraph.project` empty;
  - an unknown section or key (suggest the closest known key with
    `difflib.get_close_matches`);
  - a wrong type (for example, `max_parallel` not a positive integer);
  - an invalid IANA zone;
  - a local file that adds a key the schema lacks.
- `model`: resolve a tier (`mechanical`, `implementation`, `judgement`,
  `verifier`) or a work-type string. Match `models.overrides` keys first,
  case-insensitively; then a tier. Print JSON
  `{"model": ..., "effort": ...}`. This replaces the prose rule in
  `launch.md` step 5.
- Also expose `load(root) -> dict` and `problems(config) -> list[str]` for
  `brief.py` to import. `brief.py` adds its own directory to `sys.path`.
- Exit codes: 0 OK, 2 config problem, 1 unexpected error. Errors go to
  stderr, prefixed `config.py:`.
- On Python older than 3.11 (no `tomllib`), exit 2 and say
  "needs Python 3.11 or later".

**Implementation notes:**

- Keep one `SCHEMA` dict: section → key → (type, default). Merge, validation,
  and `show` all use it, so nothing has a second list of keys.
- Deep merge: local tables merge into tracked tables key by key. A local
  list replaces the tracked list; it is not appended.
- Resolve `brief_template`: a relative path is relative to `--root`; the
  default is the plugin's template.

**Verify:** add `plugins/agentic-team/tests/test_config.py` (`unittest`,
temporary directories). Cover:

- defaults with a minimal file containing only `taskgraph.project`;
- a local override of a scalar, a table, and a list;
- `TODO` detection;
- an unknown key with a suggestion;
- the wrong type;
- a TOML syntax error;
- `model` with an override, a tier, and the default verifier (`null`).

Run `python3 -m unittest discover plugins/agentic-team/tests`.

## Task 2: Switch `brief.py` to `config.py`

**Files:** modify `plugins/agentic-team/scripts/brief.py`.

- Delete `load_config`, `cfg`, and `is_set`. Import `load` and `problems`
  from `config.py`, and replace `--config` with `--root`.
- Before rendering, refuse with exit 2 when `problems()` returns anything,
  as the current TODO check does.
- Build FORBIDDEN from `constraints`, labelling each item ("Read-only
  sources: ...", "Do not modify: ..."). Skip empty items. Add `other` items
  one per line.
- Build AUTONOMY from `autonomy.grant` and `autonomy.always_pause`, using
  "None" wording when empty, as now.
- SCOPE: join `serialization.rules` under "Shared-file rules:".
- CONSULTANTS: join `consultants.sessions`, or say
  "None. Do not contact a consultant."
- TIMEZONE: use `sessions.timezone_label`, or derive it from
  `sessions.timezone`.
- PLAN_FILE and the legacy `State at` lookup: use `taskgraph.plan`.
- Brief template: use `sessions.brief_template` as already resolved by
  `config.py`.
- Update the module docstring.

**Verify:** repeat the scratch test from the previous session against a
temporary Taskgraph database. Do not use `~/.taskgraph`, which the sandbox
blocks.

```sh
export TASKGRAPH_DB="$TMPDIR/bt/tasks.db"
TG=plugins/taskgraph/skills/taskgraph/scripts/tg.py
```

Seed three tasks in project `demo`:

- one with a `- [ ]` checklist and `scope`, `verify`, and `estimate`
  metadata;
- one with legacy notes (`Serves:`, `Exit test:`, `State at ...:`);
- one with no acceptance criteria.

Write a `.agentic-team.toml` in `$TMPDIR/bt`, then check:

- a full brief renders and contains no `{{`;
- a missing field exits 2 and lists `tg edit` fixes;
- a `TODO` in the config exits 2;
- `STOP` in the standing orders exits 3;
- `--kind verify` renders;
- a fix round includes the previous report.

Delete `$TMPDIR/bt` afterwards.

## Task 3: Optional project default in `status.py`

**Files:** modify `plugins/agentic-team/scripts/status.py`.

Make `--project` optional. When it is omitted, read `taskgraph.project`
through `config.py` from `--root` (default `.`). Keep `--project` as an
override. Update `playbooks/report.md` to drop `--project <project>`.

**Verify:** run with and without `--project` against the scratch database.

## Task 4: Template and setup skill

**Files:**

- Create `plugins/agentic-team/templates/agentic-team.toml` (the schema
  above).
- Delete `plugins/agentic-team/templates/project-context.md`.
- Modify `plugins/agentic-team/skills/setup/SKILL.md`.

Setup skill changes:

- Copy the template to `.agentic-team.toml`. Fill values by editing the
  text, one key at a time, and keep the comments.
- Suggest `taskgraph.project` from `tg projects`.
- Keep asking one question at a time for each `TODO`.
- Gitignore `.agentic-team.local.toml` and `.agentic-team/`.
- Finish by running `config.py check`. Setup is done only when it prints
  `ok`.
- Update the description to say `.agentic-team.toml`.

**Verify:** `claude plugin validate plugins/agentic-team` and
`./scripts/validate.sh`.

## Task 5: Manager, playbooks, and principle

**Files:**

- `agents/manager.md`;
- `playbooks/launch.md`, `playbooks/drain.md`,
  `playbooks/verify-and-close.md`, `playbooks/pickup.md`,
  `playbooks/report.md`;
- `skills/principle-decision-forks/SKILL.md`.

Changes:

- **Manager, Start step 2.** Replace "Read `.agentic-team.md` ..." with:
  run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" check`. On exit 2,
  run `agentic-team:setup`. Then fetch values with `config.py get <key>`
  when a playbook step needs them. Do not read the TOML files directly.
- **Manager defaults table.** Delete it. It now lives in `config.py`; point
  to `config.py show`.
- **Field names.** Replace each prose name with its key:
  - `Notify skill` → `notifications.skill`;
  - `Other overrides` → `models.overrides`;
  - `Launch outside sandbox` → `sessions.launch_outside_sandbox`;
  - `Max parallel sessions` → `sessions.max_parallel`;
  - `Permission mode` → `sessions.permission_mode`;
  - `Progress tool` → `progress.tool`;
  - `Restart steps` → `consultants.restart`;
  - `Verifier` → `models.verifier`;
  - `Full-autonomy grant` → `autonomy.grant`;
  - `Always-pause gates` → `autonomy.always_pause`.
- **`launch.md` step 5.** Replace the model rule with
  `config.py model <work type or tier>`.
- **`launch.md` step 6.** Read the permission mode and sandbox flag with
  `config.py get`.

**Verify:** run
`grep -rn -E '\.agentic-team(\.local)?\.md|Notify skill|Other overrides|Launch outside sandbox|Max parallel sessions|Progress tool|Restart steps|Full-autonomy grant|Always-pause gates' plugins/agentic-team README.md`.
It must return nothing.

## Task 6: Docs and gitignore

**Files:**

- `plugins/agentic-team/README.md`;
- root `README.md`;
- `.gitignore`.

Changes:

- **Plugin README "Configuration".** Rewrite it as a key reference grouped
  by table. For each key give its type, default, and meaning. Add a
  "Reading config" subsection showing `get`, `show`, `check`, and `model`.
- **Plugin README "Set up a project".** Name `.agentic-team.toml`.
- **Plugin README "Extending".** Say a project setting is added in
  `config.py`'s `SCHEMA`, then documented in the README and the template.
- **Plugin README layout tables.** Add `scripts/config.py` and
  `tests/test_config.py`.
- **Root `README.md`.** Change the `.agentic-team.md` mention to
  `.agentic-team.toml`.
- **`.gitignore`.** Replace `.agentic-team.local.md` with
  `.agentic-team.local.toml`.

## Task 7: Final validation

Run:

```sh
./scripts/validate.sh
claude plugin validate plugins/agentic-team
python3 -m unittest discover plugins/agentic-team/tests
git diff --check
```

Then delete any `__pycache__` folders and temporary files. Expected:

- all checks pass;
- the plugin validator reports nothing;
- the old-name grep from Task 5 returns nothing.

If the Claude CLI is available, also run a live smoke test. From a scratch
repository that has a valid `.agentic-team.toml`, run
`claude --plugin-dir plugins/agentic-team --agent agentic-team:manager -p "Run only Start steps 1-2 and report the config check result."`.
It should report `ok`. During the previous session the CLI failed with
"unknown error" even on `claude --version`. If it still fails, record that
and do not block on it.

## Out of scope

- Supporting `.agentic-team.md` alongside TOML.
- YAML or JSON config files.
- Workers reading config directly.
- Changing the Taskgraph plugin.
