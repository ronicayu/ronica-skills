# agentic-team

A Manager agent that runs project work through [Taskgraph](../taskgraph). You
plan the work as Taskgraph tasks. The Manager launches a background worker
session for each ready task, in its own git worktree, and has a verifier confirm
the result. It closes and merges verified work and reports from Taskgraph data.
Taskgraph owns the plan and the results; the Manager owns the judgement calls
and the contact with you. Everything the Manager changes goes through one
script, `run.py`.

The design adapts the playbook and principle structure of
[pstack](https://github.com/cursor/plugins/tree/main/pstack) by Lauren Tan
(MIT).

## Install

```text
/plugin install agentic-team@ronica-skills
```

This also installs its dependency, `taskgraph`. Restart Claude Code after you
install or update the plugin: `/reload-skills` does not load a new plugin's
skills or agents.

The scripts need Python 3.11 or later.
[scripts/python-path.sh](scripts/python-path.sh) finds one (`python3.13`,
`python3.12`, `python3.11`, then `python3`). Set `AGENTIC_TEAM_PYTHON` to an
interpreter path to choose one yourself. The wrappers `scripts/run`,
`scripts/config`, and `scripts/tg` call it for you, from any directory, so no
prompt builds a command from a variable.

## Minimum setup

In the repository you want to manage:

1. Run `claude` once and accept the trust prompt. `claude --bg`, which starts
   the workers, refuses an untrusted workspace, and a trusted parent folder does
   not count.
2. Run `/agentic-team:setup`. It creates `.agentic-team.toml` from
   [the template](templates/agentic-team.toml), fills what it can find, asks for
   the rest, gitignores the run directory and worktrees, and finishes when
   `config.py check` prints `ok`. Only `taskgraph.project` has no default; every
   other key is optional. The setup skill also offers a [project verify
   skill](docs/configuration.md#the-project-verify-skill)
   (`.claude/skills/verify/SKILL.md`) that tells the verifier how to prove your
   artifacts.
3. Start the Manager (next section).

The Manager does not start work while the config check fails.

## Start a Manager

- As the session's agent type: `claude --agent agentic-team:manager`. Or select
  `agentic-team:manager` in the agent picker, or mention
  `@agent-agentic-team:manager`.
- In a session that is already running: type `/agentic-team:manager`, or ask
  the session to switch to the Manager role. A session cannot change its agent
  type, so the skill makes it act as the Manager. It first hands over the work
  the session had started, as Taskgraph tasks or integration steps, and then
  runs the Manager's Start steps. The role ends when you say so.

The Manager keeps the plan, launches and verifies work, and reports. It does
not diagnose failures, edit the repository, review diffs, or run tests itself;
each of those becomes a Taskgraph task for a worker or a verifier. After a
context compaction a hook gives it its role and orders back
([the compaction hook](docs/operations.md#the-compaction-hook)).

## Your first task

Ask the Manager to plan the work, for example "add a `--version` flag to the
CLI". The Manager runs the steps below; you can run any of them yourself with
`"${CLAUDE_PLUGIN_ROOT}/scripts/run" <command>` from the repository root.

1. **Add.** `run add "Add --version flag" --notes "<why; acceptance criteria>"
   --meta scope="src/cli.py" verify="pytest tests/test_cli.py" --independent
   "first task"`. A task needs notes, a SCOPE and a VERIFY command; `add` also
   makes you settle its dependencies.
2. **Launch.** `run launch 1` starts a worker in `.claude/worktrees/task-1` and
   prints the session. `run wait` sleeps until something changes, and
   `run record` prints one line per event: a result arrived, a session died, a
   question is waiting.
3. **Verify.** The worker files a `PASS`, `ISSUES` or `BLOCKED` report. A `PASS`
   is a claim: `run verify 1` starts a verifier that checks the exact commit the
   worker reports, and files a verdict (`artifact-verified`, `test-verified`,
   `check-only`, `verify-failed` or `verify-blocked`).
4. **Close.** `run close 1` records the verdict. In `local` mode, a `MERGE:` line
   in `.agentic-team/standing-orders.md` lets it merge into your clean main
   checkout; in `pr` mode (`[merge] mode = "pr"`) it pushes the branch and opens
   a pull request. The task is done when its change is merged.

For work that needs a design first, turn on `[workflow_policy] enabled` and use `run add --workflow`; see
[Workflows](docs/roles-and-briefs.md#workflows).

When a verifier finds blocking problems, `run revise 1` sends them to the same
worker, which fixes them in place. A worker that needs an answer files an `ask`;
you or the Manager answer with `run answer`.

## Skills

| Skill | Use |
|-------|-----|
| `/agentic-team:manager` | Make a running session act as the Manager. Model-invocable, so "switch to the Manager role" also works. |
| `/agentic-team:setup` | Create or complete `.agentic-team.toml`. |
| `principle-<name>` | One rule each, such as `principle-decision-forks`. Hidden from automatic invocation; the Manager reads them by path. |

## Where to look next

| You want to | Read |
|-------------|------|
| Look up a command, option, config key, event, meta key or result kind | [docs/reference.md](docs/reference.md), generated from the code |
| Understand attempts, phases, verification, revisions and rounds | [docs/lifecycle.md](docs/lifecycle.md) |
| Merge through pull or merge requests, handle conflicts and restacks | [docs/merge.md](docs/merge.md) |
| Let workers ask questions and let the Manager steer them | [docs/messaging.md](docs/messaging.md) |
| Tune report checks, worker hooks, notifications, cost and the run directory | [docs/operations.md](docs/operations.md) |
| Shape briefs and task roles, or plan new work with workflows (stages, approvals, a pick) | [docs/roles-and-briefs.md](docs/roles-and-briefs.md) |
| Run the project on the Taskgraph GitHub backend | [docs/github-backend.md](docs/github-backend.md) |
| Read the config, pick verifier models, or use more than one Claude profile | [docs/configuration.md](docs/configuration.md) |
| See how the parts fit, the file layout, and how to extend the plugin | [docs/architecture.md](docs/architecture.md) |
| Upgrade from an older version | [CHANGELOG.md](CHANGELOG.md) |

The Manager's own instructions are in [agents/manager.md](agents/manager.md) and
the [playbooks](playbooks/). The lifecycle has a checked TLA+ model in
[model/](model/).
