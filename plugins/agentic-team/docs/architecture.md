# Architecture

How the parts of agentic-team fit together, what each file is for, and how to extend the plugin. For the first run see the [README](../README.md); for the per-key and per-command tables see the [reference](reference.md).

## How it works

![The Manager reads config through config.py and runs run.py, one command per step. run.py renders briefs from Taskgraph and the run directory, launches worker and verifier sessions, and reads their results from Taskgraph. The Manager reports to the operator](../assets/diagrams/overview.svg)

| Part | Role |
|------|------|
| [Manager](../agents/manager.md) | A short index: startup, playbook routing, principles, escalation, standing orders, and session rules. |
| [Playbooks](../playbooks/) | One file per situation: `plan`, `run`, `report`, and `pause`. The Manager copies the matching playbook's steps into its todo list word for word, and marks any it skips with a reason. |
| [Worker](../agents/worker.md) | Each task session runs as `--agent agentic-team:worker`, in its own worktree. The worker agent holds the fixed rules and the report format (`PASS`, `ISSUES`, or `BLOCKED`), so briefs carry only task content. |
| [Dependency check](../agents/dependency-check.md) | A subagent (`agentic-team:dependency-check`, model `sonnet`), read-only by instruction (its frontmatter cannot limit Bash), that the Manager starts with the Agent tool before it launches a task. It checks whether the code that the task's SCOPE touches or builds on is only in an open request or an unmerged branch, and whether a Taskgraph dependency is missing, and returns `ok` or one `missing:` line per dependency. |
| [Principles](../skills/) | One skill per principle (`principle-<name>`), hidden from automatic invocation. The Manager keeps a one-line index and reads the full rule only when it applies. |
| [Config script](../scripts/config.py) | The only reader of the project config. It merges, fills defaults, validates, and answers `get`, `show`, `check`, and `model`. |
| [Run script](../scripts/run.py) | Launches, adopts, drains, verifies, closes, merges, stops, abandons, and reports. It refuses an unscoped task, a fourth attempt, a launch under `STOP`, and a merge without a `MERGE:` line or (in `local` mode) into a dirty checkout. It matches sessions to tasks by the session id it recorded, never by name. |
| [Host script](../scripts/host.py) | The one module that speaks to a code host in `pr` mode: push, request, checks, merge. GitHub through `gh`, GitLab through `glab`. |

Three rules carry the rest:

- Completions and questions are queue events. A worker files one
  `tg result add`, or an `ask` row, then may send the Manager one line with
  SendMessage, which only wakes it. The Manager runs `run.py record` at drain
  points, reads one line per event, and returns to its current step.
  `run.py wait`, in the background, wakes it when no message comes.
- The brief is the product. A worker may ask the Manager a question; the
  question and the answer are Taskgraph rows, and the answer reaches the same
  session. Its task content comes only from Taskgraph. `run.py launch` refuses
  a task with no purpose, acceptance criteria, scope, or verify command, and
  the Manager fixes the task in Taskgraph rather than writing the brief by
  hand. Every attempt is still a fresh session; a resume happens only inside
  an attempt, through `run.py answer` or `run.py steer`.
- A worker's `PASS` is a claim. A task closes only on a verdict tied to the
  exact output: the commit SHA the worker reports, at the pass level of its
  verify kind.

## One task, end to end

![Sequence: the Manager checks config, launches a worker with run.py, finds the worker's PASS result with run.py record, has a verifier confirm the commit, closes the task, and reports](../assets/diagrams/sequence.svg)

The diagrams are rendered with [Pele](https://pele.run) from the Mermaid
sources in [assets/diagrams/](../assets/diagrams/). After editing a `.mmd` file,
run `npm install -g pele` once, then
`node plugins/agentic-team/assets/diagrams/render.mjs`.

## Layout

| Path | Purpose |
|------|---------|
| `agents/manager.md` | The Manager index |
| `agents/worker.md` | The worker agent used for every task and verifier session |
| `agents/dependency-check.md` | The read-only subagent the Manager starts before a launch |
| `playbooks/` | Step-by-step procedures the Manager follows |
| `skills/principle-*/` | One principle each, hidden from automatic invocation |
| `skills/manager/` | `/agentic-team:manager`, which makes a running session act as the Manager |
| `skills/setup/` | `/agentic-team:setup`, which creates the project config |
| `templates/` | Project config (`agentic-team.toml`), the brief, the verifier method per kind (`verify-<kind>.md`), the task roles (`roles/<name>.md`), the project verify skill skeletons (`project-verify-skill-{code,document}.md`), and standing orders |
| `assets/diagrams/` | Mermaid sources for the diagrams in `docs/`, their SVGs, and `render.mjs` (Pele) |
| `scripts/run`, `scripts/config`, `scripts/tg` | Wrappers that run `run.py`, `config.py`, and `tg.py` with a Python 3.11 or later, from any directory. Prompts use these and never a variable. |
| `hooks/hooks.json`, `scripts/recompact`, `scripts/recompact.py` | The `SessionStart` (`compact`) hook that gives the Manager its role and orders again after a compaction |
| `scripts/tg-path.sh` | Finds the installed Taskgraph CLI. `TASKGRAPH_TG` overrides it. |
| `scripts/python-path.sh` | Finds a Python 3.11 or later. `AGENTIC_TEAM_PYTHON` overrides it. |
| `scripts/config.py` | Reads, merges, and validates the project config; holds every default |
| `scripts/mailbox.py` | The worker's mailbox commands (`ask`, `inbox`, `ack`, and the `checkin` and `hook` commands that the `--settings` hooks run) and the row helpers that `run.py` shares |
| `scripts/host.py` | The code host seam: GitHub through `gh`, GitLab through `glab` |
| `scripts/run.py` | Launches, adopts, drains, verifies, closes, merges, stops, abandons, and reports |
| `scripts/events.py` | The registry of event names that `run.py` prints, with what each means |
| `scripts/reference_data.py` | The reference tables that no constant holds: command prose, meta keys, result kinds |
| `scripts/gen_reference.py` | Generates `docs/reference.md` from the parser, the config schema and the two tables above; `--check` fails when the file is out of date |
| `docs/` | The guides (this folder) and the generated `reference.md` |
| `CHANGELOG.md` | What each version changed and how to upgrade from the one before |
| `tests/` | Tests for the scripts, with a fake `claude`, a fake `gh`, and a fake `glab`. Run them in parallel, the normal gate (about two minutes): `python3.11 plugins/agentic-team/tests/run_parallel.py` (`-j N` sets the worker count, `-k PATTERN` and test names pick a subset). `tests/run_parallel.py` finds the same tests as the serial reference, `python3.11 -m unittest discover -s plugins/agentic-team/tests` (about 25 minutes), and gives the same result. Every test works in its own temporary folders, so tests may run in any order and at the same time; a new test must not use a fixed path, socket name or port. `tests/.durations.json` (git-ignored) keeps the time of each test, to start the slow ones first. The `pytest` command also works: `uv run --python 3.11 --with pytest python -m pytest plugins/agentic-team/tests -q`. |

## Extending

- **A principle.** Add `skills/principle-<name>/SKILL.md` with
  `disable-model-invocation: true` and a description that starts with
  "Apply when". Add one row to the Principles table in
  `agents/manager.md`. If workers need it, point to it from
  `agents/worker.md`.
- **A playbook.** Add `playbooks/<name>.md` with numbered steps and a
  **Reply** line. Add one row to the Playbooks table in `agents/manager.md`.
- **A skill.** Use a short name; the plugin namespace already applies, so
  `skills/review/` becomes `/agentic-team:review`. Add settings to the
  project config only if they describe the project.
- **A project setting.** Add the key, with its type and default, to `SCHEMA`
  in [scripts/config.py](../scripts/config.py), describe it in `DESCRIPTIONS` there, and add it to
  [the template](../templates/agentic-team.toml). Then run `scripts/gen_reference.py`: it prints the key into
  the [reference](reference.md#configuration). Read it with `config.py get`.
- **An event.** Add its name and a one-line meaning to `EVENTS` in [scripts/events.py](../scripts/events.py)
  before `run.py` emits it (`Run.emit` refuses an unknown name), then run `scripts/gen_reference.py`.
- **A role.** Add `.claude/agentic-team/roles/<name>.md` to the project (or `templates/roles/<name>.md` to the plugin), in the format under [Roles](roles-and-briefs.md#roles). Run `run.py roles` to check it. No release is needed for a project role. A project file with a shipped role's name replaces that role.
- **Preloading.** The Manager's `skills:` list preloads only when it runs as a
  subagent; as the main agent it loads them itself (see `agents/manager.md`).
  Use qualified `plugin:skill` names, and keep the list short. Skills with
  `disable-model-invocation: true` cannot be preloaded, which is why
  principles are read by path.
