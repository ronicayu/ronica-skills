# Configuration guide

What the per-key tables of the [reference](reference.md#configuration) do not say: how agents read the config, how the verifier model is picked, which ignored files a cleanup may delete, the project verify skill, and workers on more than one Claude profile.

## Reading config

Agents read config only through [scripts/config.py](../scripts/config.py), by
the `config` wrapper, run from the repository root (or pass `--root DIR`). Workers never read it; their
brief carries what they need.

```sh
"${CLAUDE_PLUGIN_ROOT}/scripts/config" check                      # every problem, one per line; else "ok"
"${CLAUDE_PLUGIN_ROOT}/scripts/config" get sessions.max_parallel  # one value; tables and lists print as JSON
"${CLAUDE_PLUGIN_ROOT}/scripts/config" get models --json          # always JSON
"${CLAUDE_PLUGIN_ROOT}/scripts/config" show                       # the merged config with defaults filled in
"${CLAUDE_PLUGIN_ROOT}/scripts/config" model implementation       # {"model": "sonnet", "effort": "high"}
"${CLAUDE_PLUGIN_ROOT}/scripts/config" model "data migration"     # a models.overrides key, else a tier
```

A tier that names profiles prints them: `{"model": "haiku", "effort": null, "profile": "api"}`. A tier without
`profile` prints no `profile` key.

`check` reports a missing file, TOML syntax errors with their line, `"TODO"`
values, an empty `taskgraph.project`, unknown sections or keys (with the
closest known key), wrong types (a value outside a fixed choice reads `must be
one of "local", "pr"`), and invalid time zones. With a `[profiles]` table it also
reports a profile name that a tier uses and `[profiles]` does not define, a profile
directory that does not exist, and `default` defined in `[profiles]`, and it runs
`claude plugin list --json` under each profile and fails when `agentic-team` is
not installed there (a different version only warns). It reads no git state and makes
no network call. `get` and `model`
refuse to answer while `check` fails. Exit codes: 0 OK, 2 config problem, 1
unexpected error. It needs Python 3.11 or later; the `config` wrapper finds
one through `scripts/python-path.sh`.

## Verifier model per tier

`run.py verify` picks the verifier model in this order: `--model`; `[models.verifier_by_tier]` for the tier of the attempt
(the `tier` that launch stored, else the one the task names now; a key matches a tier or a `[models.overrides]` key, in any
case); `[models] verifier`; else a model that differs from the worker's (`opus`, or `sonnet` when the task's `model` meta
starts with `opus`). `--effort` and the profile come from the table that wins, as for `verifier`.

The shipped default is no table, so a project that sets nothing gets exactly the 0.28.2 choice. The recommended setting,
which the template shows commented out, is Sonnet for implementation work and Opus for judgement work:

```toml
[models.verifier_by_tier]
implementation = "sonnet"
judgement = "opus"
mechanical = "sonnet"
```

In the vmt token retro (2026-11-17 to 11-18) Opus verifiers of implementation-tier tasks cost $128.69, and Sonnet 5.5
costs half of Opus 5.5 per token. A judgement task keeps Opus because a weak verifier of a judgement task misses what the
task is for.

## Disposable patterns

After a merge, `run.py` deletes a worktree's ignored files only when each one
is disposable: the project rebuilds it with a command. Any other ignored file
keeps the worktree (see the cleanup in [Lifecycle](lifecycle.md#verdict-and-close)). The default
list:

- Dependencies: `node_modules/`, `bower_components/`, `.pnpm-store/`.
- Python: `.venv/`, `venv/`, `.tox/`, `.nox/`, `__pycache__/`, `*.pyc`,
  `*.pyo`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.hypothesis/`,
  `.coverage`, `.coverage.*`, `htmlcov/`, `*.egg-info/`, `.eggs/`.
- JavaScript: `.next/`, `next-env.d.ts`, `.nuxt/`, `.svelte-kit/`, `.turbo/`,
  `.parcel-cache/`, `.eslintcache`, `*.tsbuildinfo`, `coverage/`.
- Other build output and caches: `.cache/`, `dist/`, `build/`, `target/`,
  `.gradle/`.
- Operating system files: `.DS_Store`, `Thumbs.db`.
- Session report and scratch files: `.agentic-team/`, `.agentic-team-scratch/`.

The list holds nothing that can be data: no `.env` file, log, database or
editor file. `[merge] disposable` adds this project's patterns, for example
`disposable = [".sdk-wheels/", "*.sqlite-journal"]`. An entry `"!<pattern>"`
turns off that default pattern, for example `"!build/"` when `build/` holds
files that no command rebuilds. A list in `.agentic-team.local.toml` replaces
the tracked list.

The pattern rules are close to `.gitignore`:

- A pattern that ends in `/` matches only a folder.
- A pattern with no other `/` matches a name at any depth: `node_modules/`
  matches `pkg/sub/node_modules/`.
- A pattern with a `/` inside matches the path from the worktree root:
  `apps/*/generated/`. A leading `/` changes nothing.
- `*` matches any characters, `/` included; `?` matches one character;
  `[abc]` matches one of a set. Case counts.
- A path is disposable when it, or a folder on its path, matches a pattern.

`config.py check` reports a pattern that is empty, has spaces at an end, or
holds only `*`, `?` and `/`, and an entry `"!<pattern>"` that names no default
pattern.

## The project verify skill

The setup skill also checks for the project verify skill, `.claude/skills/verify/SKILL.md`, which tells the verifier how to prove this project's artifacts: how to launch and drive the application (a code project), or where the sources are and which script recomputes a count (a schema or design-document project). When the file is missing, setup offers to create it from the skeleton for the config's `verify.kind` ([templates/project-verify-skill-code.md](../templates/project-verify-skill-code.md) or [templates/project-verify-skill-document.md](../templates/project-verify-skill-document.md)) and fills what the repository shows. The file is repository content; commit it when you are satisfied. Without it the verifier still runs, reports the highest level it can prove, and names the method step it could not carry out.

## Workers on more than one Claude profile

One Manager can start its worker and verifier sessions under more than one
Claude profile (a `CLAUDE_CONFIG_DIR`), for example a subscription profile and
an API-billed profile, to share the usage between accounts. A model tier names
the profile, or a list of profiles to balance across. Without a `[profiles]`
table nothing changes.

```toml
[profiles]
# name = the CLAUDE_CONFIG_DIR of that profile; "default" is always the Manager's own environment and needs no entry
api = "~/.claude-api"

[models]
mechanical = { model = "haiku", profile = "api" }
implementation = { model = "sonnet", effort = "high", profile = ["default", "api"] }   # balance: fewest live sessions first
judgement = "opus"                       # no profile: default
verifier = { model = "opus", profile = "default" }

[models.overrides]
"data migration" = { model = "opus", effort = "high", profile = "api" }
```

- `[profiles]` maps a name to the profile's directory (`~` is expanded). `default` is the Manager's own
  environment, is always there, and cannot be defined. Paths are machine-specific, so `[profiles]` may live in
  `.agentic-team.local.toml` while the tiers that use it stay in the tracked file.
- A tier value without `profile`, and a string tier, use `default`.
- With a list, `launch` and `verify` pick the listed profile with the fewest live sessions of this project (the
  count that `max_parallel` uses); a tie goes to the name listed first.
- `launch --profile NAME` and `verify --profile NAME` override the tier. `--model` replaces the model only; the
  tier still names the profile.
- `run.py` writes `"profile": "<name>"` into the `sessions` entry of each session that is not on `default`, and
  uses that profile for every later call on the session: `claude agents`, `logs`, `stop`, `rm`, and the
  transcript folder (`<dir>/projects/...`). `claude agents` lists one profile only, so `run.py` reads the list of
  `default` and of each profile that a `sessions` entry names, and keeps one row when two lists return the same
  id. `record` and `status` show the profile next to a session that is not on `default`.
- `claude --bg` under a profile that does not trust the repository refuses with `profile <name> does not trust
  <repo>: run CLAUDE_CONFIG_DIR=<dir> claude in <repo> once and accept the trust prompt`. `run.py` never changes
  trust, and writes no `sessions` entry.

Set up each extra profile once, in this order:

1. **Trust the repository.** Run `CLAUDE_CONFIG_DIR=<dir> claude` in the repository and accept the trust prompt.
   Trust is per profile, and a trusted parent folder does not count.
2. **Install the plugin.** Plugins are per profile. A worker starts with `--agent agentic-team:worker`, so the
   profile needs `agentic-team`:
   `CLAUDE_CONFIG_DIR=<dir> claude plugin marketplace add ronicayu/ronica-skills`, then
   `CLAUDE_CONFIG_DIR=<dir> claude plugin install agentic-team@ronica-skills`. It does not need `taskgraph`: the
   brief carries absolute paths to the Manager's `python`, `tg.py` and `run.py`. `config.py check` fails when
   `agentic-team` is missing in a profile and warns when its version differs from the Manager's.
3. **Mirror the permission rules.** `run.py` copies no permissions or settings between profiles. A worker
   profile needs the same permission rules as the Manager's profile for the commands workers run, or workers
   stop at permission prompts (`record` files them as BLOCKED).

Cost and failure notes:

- A profile on an API key bills per token. A subscription profile draws on its plan's limits. Put a tier on the
  API profile only when you accept that bill.
- A profile can fail at the account level, for example `Credit balance too low`. `launch` cannot see it (the
  session starts); `record` sees an idle session with no result. Check the profile's account, then rerun.
- Not in this version: moving a running session to another profile, retrying a failed launch on the next
  profile, and two Managers on one project.
