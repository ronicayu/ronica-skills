# agentic-team

A Manager agent that runs project work through [Taskgraph](../taskgraph). The
Manager runs one script, `run.py`, for every state change. The script launches
a background worker session for each ready task in its own git worktree, reads
the results the workers file in Taskgraph, verifies them, closes and merges
verified work, and reports from Taskgraph data. Taskgraph owns the plan, task
state, and worker results. The Manager owns the plan content, the judgement
calls, and the contact with the operator. Workers do the work and commit it on
their own branch.

The design adapts the playbook, and principle structure of
[pstack](https://github.com/cursor/plugins/tree/main/pstack) by Lauren Tan
(MIT).

## Install

```text
/plugin install agentic-team@ronica-skills
```

This also installs its dependency, `taskgraph`. After installing or updating
the plugin, restart Claude Code. `/reload-skills` does not load a freshly
installed plugin's skills or agents.

The scripts need Python 3.11 or later.
[scripts/python-path.sh](scripts/python-path.sh) finds one (`python3.13`,
`python3.12`, `python3.11`, then `python3`). Set `AGENTIC_TEAM_PYTHON` to an
interpreter path to choose one yourself. The wrappers `scripts/run`,
`scripts/config`, and `scripts/tg` call it for you, from any directory, so no
prompt builds a command from a variable.

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
each of those becomes a Taskgraph task for a worker or a verifier.

## Set up a project

Run `/agentic-team:setup` in the repository. It creates `.agentic-team.toml`
from [the template](templates/agentic-team.toml), fills what it can find,
asks for the rest, and gitignores `.agentic-team.local.toml`, the run
directory `.agentic-team/`, and the worktree directory `.claude/worktrees/`. It finishes only when `config.py check` prints
`ok`. The Manager does not start work while the check fails.

`claude --bg` refuses to start in a workspace that is not trusted. A trusted
parent folder does not count. Run `claude` once in the repository and accept
the trust prompt before the Manager launches its first worker.

## Skills

| Skill | Use |
|-------|-----|
| `/agentic-team:manager` | Make a running session act as the Manager. Model-invocable, so "switch to the Manager role" also works. |
| `/agentic-team:setup` | Create or complete `.agentic-team.toml`. |
| `principle-<name>` | One rule each, such as `principle-decision-forks`. Hidden from automatic invocation; the Manager reads them by path. |

## How it works

![The Manager reads config through config.py and runs run.py, one command per step. run.py renders briefs from Taskgraph and the run directory, launches worker and verifier sessions, and reads their results from Taskgraph. The Manager reports to the operator](assets/diagrams/overview.svg)

| Part | Role |
|------|------|
| [Manager](agents/manager.md) | A short index: startup, playbook routing, principles, escalation, standing orders, and session rules. |
| [Playbooks](playbooks/) | One file per situation: `plan`, `run`, `report`, and `pause`. The Manager copies the matching playbook's steps into its todo list word for word, and marks any it skips with a reason. |
| [Worker](agents/worker.md) | Each task session runs as `--agent agentic-team:worker`, in its own worktree. The worker agent holds the fixed rules and the report format (`PASS`, `ISSUES`, or `BLOCKED`), so briefs carry only task content. |
| [Principles](skills/) | One skill per principle (`principle-<name>`), hidden from automatic invocation. The Manager keeps a one-line index and reads the full rule only when it applies. |
| [Config script](scripts/config.py) | The only reader of the project config. It merges, fills defaults, validates, and answers `get`, `show`, `check`, and `model`. |
| [Run script](scripts/run.py) | Launches, adopts, drains, verifies, closes, merges, stops, abandons, and reports. It refuses an unscoped task, a fourth attempt, a launch under `STOP`, and a merge without a `MERGE:` line or (in `local` mode) into a dirty checkout. It matches sessions to tasks by the session id it recorded, never by name. |
| [Host script](scripts/host.py) | The one module that speaks to a code host in `pr` mode: push, request, checks, merge. GitHub through `gh`, GitLab through `glab`. |

Three rules carry the rest:

- Completions are queue events. A worker's last action is one
  `tg result add`, and it sends no message. The Manager runs `run.py record`
  at drain points, reads one line per event, and returns to its current step.
- A worker cannot ask a question, so the brief is the product. Its task
  content comes only from Taskgraph. `run.py launch` refuses a task with no
  purpose, acceptance criteria, scope, or verify command, and the Manager
  fixes the task in Taskgraph rather than writing the brief by hand.
- A worker's `PASS` is a claim. A task closes only on a verdict tied to the
  exact output: the commit SHA the worker reports.

### Task lifecycle

Nothing is patched in place. A refused launch is fixed in Taskgraph, a retry
or fix round renders a fresh brief, and a closed task unblocks the next. Only
calls that need the operator leave the loop, as Taskgraph `decision` nodes.

`run.py launch <id>` renders the brief and starts the worker in the task's one
worktree (`.claude/worktrees/task-<id>`), on the task's one branch
(`worktree-task-<id>`). A task keeps that worktree and branch for its whole
life. The first attempt creates the worktree itself, at the base commit, with
`git worktree add`, and `claude --bg --worktree` reuses it. This relies on
`claude --bg --worktree <name>` reusing an existing worktree, which was
verified with Claude Code 2.1.311; the `launched` and `verifying` events warn if
the session's worktree is no longer at the base. The worker resets and checks
out nothing: its brief names the commit the worktree is at, and it reports
`BLOCKED` if `HEAD` is not there. The first `launch` refuses when the branch or
folder already exists (the message gives the steps to reuse the name), and
removes the worktree and branch again if `claude` fails to start, unless a
session, a change or a new commit is there. The base of a first attempt is the
Manager's `HEAD`; in `pr` mode the fetched target branch replaces it.
`launch --base <sha|branch>` starts a first attempt from any commit and wins
over both.

A retry or fix round is a fresh session with a fresh brief, in the same
worktree, on top of the commits of the earlier attempts. The attempt is only a
number: it caps retries at 3 and labels result rows, session names, and brief
files. The retry starts at the worktree's `HEAD`, and its brief says so and pastes
the previous report. `launch --base` on a retry is refused while the worktree
exists, and the message gives the by-hand reset; `run.py` never resets,
rebases, or checks out another commit in place. Before a retry the worktree
must be clean. `launch` refuses a `STOPPED` attempt whose WIP commit is not made
yet (run `record` first). When a dead or stuck attempt left uncommitted files,
`launch` commits them as `WIP task <id> attempt <n>: <status>` and says so in
the `launched` line. A worktree on another branch, or a plain folder, is
refused with the fix. If the worktree is missing on a retry, `launch` reattaches
`worktree-task-<id>` when the branch exists; else it creates the worktree at the
`Head` of the latest worker or stopped result (an adopted task's first fix
round); else it asks for `--base`. A failed `claude --bg` on a retry removes
nothing. `base` in the task's metadata is the commit the branch forked from; it
is written once and a retry does not change it.

`run.py verify` creates a verifier's worktree of its own
(`verify-<id>-<attempt>`, then `-2`, `-3` for a second verifier), fresh at the
commit under review, and `cleanup` removes it with its session. `claude --bg`
writes session data under `~/.claude`, so run
`launch` and `verify` outside the Bash sandbox or allow writes to `~/.claude`;
either needs the operator's agreement. Before it files its report, whatever the
status, the worker commits on its branch (a `WIP task <id> attempt <n>: <status>` commit for
`ISSUES` or `BLOCKED`), so `Head` is always set and the worktree is clean. It
files its report with `tg result add`. The report names the `Branch`, the
`Head` commit SHA, and the `Worktree` path. The Manager never messages a
worker.

`run.py record` finds the result, one line per event. A session that ends with
no result is filed as `DIED` and retried; a complete report in `claude logs`
is filed as the worker's own. A session stuck on a permission prompt is
stopped and filed as `BLOCKED`. Attempt 3 is the last (`launch` refuses a
fourth): when it fails, `run.py abandon` marks the task abandoned. Its
worktree stays, and the report lists it for the operator to remove.

The Manager then verifies the commit. For a `risk=low` task it reruns VERIFY
inside the worker's worktree. For a `risk=high` task, `run.py verify` starts a
verifier in a worktree of its own, created at the `Head` commit. Then
`run.py close` records the verdict and the token counts, runs `tg done`, and
then follows `merge.mode`. In `local` mode it merges only when a standing-orders
line starts with `MERGE:`, and only into the checked-out branch of a clean main
checkout. Without that line, `close` lists the branch as ready to merge. On a
conflict it aborts the merge and prints the decision to add, naming both
branches. A confirmed merge is recorded as `merged_at` and `merged_by`. When the
operator says a branch is merged, by any method including squash or rebase,
`run.py merged <id>` records it. In `pr` mode `close` pushes the branch and
opens a request instead (next section). A task that builds on a done but unmerged branch waits, and the Manager
says so plainly in its replies and reports. After the merge, `run.py` removes
every session of the task with `claude rm`, newest first and the task's first
session last. `claude` locks a worktree in the name of the first session that
used it. `claude rm` of any later session removes only that row; `claude rm` of
the first session removes the folder, when the tree is clean and pushed. When a
folder is still there after the last `rm` and no `kept` line explains it, the
`kept` line `still present (<lock reason>)` gives the by-hand command
(`git worktree remove -f -f ...`). `claude rm` refuses work that is on no
remote, so the script passes `--discard-unpushed` only for a commit that
`git merge-base --is-ancestor` finds in `HEAD` or, in `pr` mode, in the
recorded merged head (`pushed`). It never deletes a file and never forces a
worktree removal.

A question only the operator can answer is a Taskgraph `decision` node that
`--blocks` the tasks it holds back. Blocked tasks leave `ready` by themselves,
and `run.py record` and `run.py status` list the open decisions.

A pause adds `STOP: ...` as the first standing-orders line. `run.py stop <id>`
stops a worker that cannot finish soon and files a `STOPPED` result. Once the
session has exited, `run.py record` commits the worktree's uncommitted work as
a WIP commit and files a second `STOPPED` row with its `Head`. The next
attempt is a fresh session in the same worktree, on top of that commit; there
is no resume. A stopped attempt does not count as a failure.

![A ready task is launched by run.py, recorded, then verified and closed, retried in a fix round, split, or turned into a decision for the operator](assets/diagrams/lifecycle.svg)

### Merging through pull or merge requests

Set `[merge] mode = "pr"` for a repository whose protected branch takes changes
only through pull requests (GitHub) or merge requests (GitLab). Setting it is
the operator's standing permission for `run.py` to push task branches to
`<remote>/task-<id>` and to open requests. Merging still needs a `MERGE:` line.
`local` mode never pushes and never runs `gh` or `glab`.

1. `run.py close` records the verdict, runs `tg done`, pushes the branch, and
   opens a request against the target branch (`merge.base`, else the host's
   default branch). The task keeps one request across attempts: a fix round
   pushes `worktree-task-<id>` to the same `task-<id>`. Every push after the
   first carries a lease on the last pushed head (`--force-with-lease`), recorded
   as `pushed`. A remote branch that is not ours stops the first push.
2. `run.py record` reads the request at each drain. It prints `pr-pending`,
   `pr-blocked` (with the required checks), `pr-draft`, `conflict`,
   `pr-behind`, `pr-changed`, `pr-unpinned`, or `ready-to-merge`. When the host reports the
   request clean, a `MERGE:` line exists, and `STOP` is absent, `record` merges
   it with `merge.method`. The merge is guarded by the pushed head
   (`--match-head-commit` on GitHub, `sha` on GitLab). A request whose head is
   not the pushed head is never merged by `run.py`, and an open request with no
   recorded `pushed` head is never merged either (`pr-unpinned`; `close <id>`
   pushes and records it). If the host fails for one task, `record` prints
   `host-error` for that task, goes on with the others, and exits 1 at the end.
3. A merge that anyone did on the host is recorded at the next drain from the
   request state (`merged_by=operator`), squash and rebase merges included.
   `run.py merged <id> --by operator` is for a merge the host cannot show. A
   request closed without a merge is reported at every drain (`pr-closed`).
4. When the host reports the request behind its target, `run.py close <id>`
   rebases the branch in its idle worktree, checks that the change is the same,
   and pushes it again. A conflict is aborted and written as a decision. A
   worktree that is missing, dirty, or in use is not touched. `run.py` never
   approves, force-resolves, or unprotects. A push is made only when our head
   moved. If someone else moved the remote branch while our head stayed, `record`
   prints `pr-changed`; `push-refused` appears when our head moved too.

**Rebase tolerance.** A rebase moves the commit that a verdict names. `close`
and the push accept a branch at a new head when the change is the same. The
change id is a hash of `git diff -U0 base tip` without line numbers or blob
ids. The base of the old head is its merge base with the target, which covers
every attempt on the branch and survives repeated rebases; the task's `base`
meta (the commit the branch forked from, which a retry does not move) is a
second span for a stacked task whose dependency was merged and dropped by the
rebase. A clean rebase, a squash, a split, and
a reorder give the same id. A whitespace edit, an added commit, a conflict
resolved by hand into a changed line, and a binary file changed on both sides do
not. Two trade-offs: with no context lines, the same `-` and `+` lines at
another place in the same file count as the same change; and a target that
renamed a file the task edited is refused (the `diff --git` line differs), which
is the safe side. The move is printed
(`rebased`) and written (`verdict_ref`); any other difference is refused.

**CI as the verifier.** With `--meta verify_mode=ci:<name>` on the task,
`run.py verify <id>` pushes the branch, opens the request, and finds the CI run
for the pushed head, or dispatches one when it has a manual trigger. `record`
files the finished run as a `verify` result by `ci` (`test-verified`, or
`verify-failed`; a cancelled run is `verify-blocked`), once per run id and
attempt. `artifact-verified` stays a Manager override. On GitHub `<name>` is a
workflow file or name; on GitLab it is `pipeline` or a job name.

**Override.** `run.py close <id> --verdict <level> --override-verifier "<why>"`
changes a verifier's verdict and files the reason. An upgrade needs a run id or
a link in `--ran`. `verify-failed` is never upgraded; it needs a fix round.

**Adopt.** `run.py adopt <id> --branch <b> --head <sha> [--pr <n>]` brings work
that started outside `run.py` under the Manager. It files a `PASS` result by the
Manager (no worktree, no session) and records the request when `--pr` is given.
`record` lists tasks in progress with no `attempt` in one `unmanaged` line.

**The host seam.** [scripts/host.py](scripts/host.py) is the only module that
speaks to a code host: GitHub through `gh`, GitLab through `glab api`.
`merge.host = "auto"` reads the `remote` URL: `github.com` is GitHub, and a host
name that contains `gitlab` is GitLab. A self-managed GitLab on another host
name needs `host = "gitlab"`. The operator runs `gh auth login` or
`glab auth login --hostname <host>` once. The GitLab host is tested only against
a fake `glab`; its calls rest on the documented REST API and carry `UNVERIFIED`
notes in `host.py` until they are checked against a test project. The seam is
separate from Taskgraph's storage backend (issue #15); neither depends on the
other.

GitLab differs from GitHub in these ways:

- `run.py` keeps only pipelines whose `sha` is the pushed head. A pipeline run on
  a merged-results commit (Premium) never matches, so the task waits (`ci-waiting`),
  which is the safe side.
- Requests are numbered by `iid` per project. The `pr` meta holds the `iid`.
  Event lines say `MR !<iid>` for GitLab and `PR #<n>` for GitHub.
- GitLab has one pipeline per commit, not named workflows, so `verify_mode` is
  `ci:pipeline` or `ci:<job name>`.
- The merge method is a project setting (merge commit, rebase and merge,
  fast-forward). `merge.method` only controls `squash`. A fast-forward project
  reports `need_rebase` when the branch is behind; `run.py` rebases locally and
  pushes again, and never calls the server-side rebase endpoint.
- Required approvals and protected branches show as `pr-blocked` (`not_approved`)
  or as a failed merge with the API message. `run.py` never approves and never
  unprotects.
- The pushed branch `task-<id>` must not match a protected branch pattern that
  forbids force pushes; a refused push is reported, not forced.

### One task, end to end

![Sequence: the Manager checks config, launches a worker with run.py, finds the worker's PASS result with run.py record, has a verifier confirm the commit, closes the task, and reports](assets/diagrams/sequence.svg)

The diagrams are rendered with [Pele](https://pele.run) from the Mermaid
sources in [assets/diagrams/](assets/diagrams/). After editing a `.mmd` file,
run `npm install -g pele` once, then
`node plugins/agentic-team/assets/diagrams/render.mjs`.

## `run.py`

[scripts/run.py](scripts/run.py) is the only writer of run state. The Manager
runs it from the repository root through the wrapper:
`"${CLAUDE_PLUGIN_ROOT}/scripts/run" [--root DIR] [--tg PATH] [--run-dir DIR] [--json] <command>`.
A `next:` hint that says `run.py <cmd>` means that wrapper with `<cmd>`.
Nothing in it waits, sleeps, or polls: `claude --bg` returns at once, and the
Manager runs `record` later.

| Command | What it does |
|---------|--------------|
| `launch <id>` | Renders the brief, creates the task worktree at the base (or continues in it on a retry), starts the worker, and records `session`, `model`, `attempt`, `sessions`, `started_at`, and, on the first launch, `base`. Options: `--keyword`, `--tier`, `--model`, `--effort`, `--attempt`, `--base <sha\|branch>`, `--dry-run`. If an open task already has a live session, it records the start instead (`repaired`). |
| `adopt <id>` | Brings a branch started outside `run.py` under the Manager. Options: `--branch`, `--head`, `--pr`, `--base`. It launches nothing. |
| `verify <id>` | Starts a verifier for a `PASS` result, pinned to its `Head`. Options: `--ref`, `--result`, `--model`, `--effort`, `--again`, `--dry-run`. In CI mode (`verify_mode = ci:<name>`) it pushes the branch and finds or starts the CI run instead of a session. |
| `record` | Reads the queue and prints one line per event: results that arrived, dead, stuck, and stopped sessions, verdicts, merges, open decisions, free slots, and ready tasks. In `pr` mode it also reads the request state, the CI runs, and merges. |
| `close <id>` | Records the verdict and tokens, runs `tg done`, and merges, pushes and opens a request, or lists the branch as ready to merge. Accepts a rebased branch with the same change. Options: `--verdict`, `--ref`, `--ran`, `--override-verifier`. Rerun it if it stopped after `tg done`: it resumes at the merge or the push. |
| `merged <id>` | Records that the operator merged a task branch (`--by operator`, the default), then removes its sessions and worktrees. |
| `stop <id>` | Stops a worker for a pause and files a `STOPPED` result. |
| `abandon <id> <mode>` | Marks a task abandoned after attempt 3 failed. `mode` is `died`, `tool-error`, `stuck`, or `unknown`. |
| `status` | Prints the status report as Markdown tables. Options: `--since`, `--limit`, `--mark`. |

Each event is one line: `<event> #<id> attempt <n>: <detail>`, followed by
` | next: <step>` when a step follows. `--json` prints one array of
`{"event", "task", "attempt", "session", "detail", "next"}` objects and nothing
else on stdout (`status --json` prints one object). Refusals go to stderr as
`run.py: <message>`.

| Exit code | Meaning |
|-----------|---------|
| 0 | The command ran. An event may still say `died` or `kept`. |
| 1 | A tool failed: `tg`, `git`, or `claude`. |
| 2 | The command refused. The message names the fix. |
| 3 | The standing orders say `STOP`. Only `launch` returns it. |

`local` mode never runs `gh` or `glab`.

`run.py` finds `tg.py` through `--tg`, then `$TASKGRAPH_TG`, then
`scripts/tg-path.sh`. It matches a session to its task by the session id it
recorded in the task's `sessions` meta when it started the session. A live or
finished row whose id is not recorded, and whose working directory is a
worktree folder of this repository (`.claude/worktrees/task-<id>` or
`verify-<id>-<attempt>`), belongs to the task of that folder, current attempt;
this covers a launch that died before it wrote its meta. A second
`claude --bg --worktree task-<id>` after the first session finished reuses the
same folder and branch, so the folder is shared by every attempt and the id
tells the sessions apart. It never uses names, because `claude agents --all`
lists every project on the machine. A session that `claude stop` ended shows
`state` `stopped`, no `status`, and the repository root as its directory. A
stopped row cannot be matched by its directory: `run.py` ties it to a task only
through its recorded id, counts it as exited, and derives the worktree path from
the task. A stopped row that is not recorded, such as a worker the operator
stopped by hand, belongs to nobody. The `Session: <id>` lines in result bodies
are a record, not the match.

## Configuration

The project config is `.agentic-team.toml` in the repository root, in TOML.
An optional, gitignored `.agentic-team.local.toml` holds private or
machine-specific values. It is merged into the tracked file table by table;
its keys win, and a list there replaces the tracked list. Omit a key to use
its default. `""` or `[]` means the item does not apply. The string `"TODO"`
marks a value someone still has to fill in. Never put credentials or secrets
in either file.

Model values are either a model id (`"opus"`) or a table
(`{ model = "sonnet", effort = "high" }`). The config has 7 sections and 19 keys.

### `[taskgraph]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `project` | string | none; required | Taskgraph project name (`tg projects` lists them). |

### `[constraints]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `forbidden` | list | `[]` | One rule per item; they become FORBIDDEN in every brief. The template sets `["TODO"]` until someone confirms the list, even if it ends up empty. |

### `[autonomy]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `grant` | string | `""` | Decisions and actions the Manager may take without asking. `""` means no standing grant. |
| `always_pause` | list | `[]` | Decisions that always need the operator, even under the grant. |

The grant never overrides safety rules, required approvals, or constraints.
See the [decision-forks principle](skills/principle-decision-forks/SKILL.md).

### `[sessions]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `max_parallel` | positive integer | `2` | Cap on in-flight sessions, workers and verifiers. Start with 1 or 2. The Manager refills as sessions finish. |
| `permission_mode` | string | `"auto"` | `--permission-mode` for worker sessions. |
| `timezone` | string | System zone (`/etc/localtime`), else `"UTC"` | IANA zone name, for example `"Asia/Singapore"`. Used for all recorded times. |
| `timezone_label` | string | Derived from `timezone` | Label written after times, for example `"SGT"`. Set it when the derived label is an offset such as `+08`. |

### `[models]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `mechanical` | model | `"haiku"` | Sweeps, counts, diffs, summaries. Use an alias: an older pinned id such as `claude-haiku-4-5-20251001` drops out of `auto` mode in a `--bg` worker and waits on a permission prompt. |
| `implementation` | model | `{ model = "sonnet", effort = "high" }` | Well-scoped build or edit work with a known answer shape. |
| `judgement` | model | `"opus"` | Judgement, review, prose readers rely on, long unattended runs. |
| `verifier` | model | unset | Verification sessions. Unset means a different model from the worker's: `opus`, or `sonnet` if the worker ran on `opus`. |
| `overrides` | table | `{}` | `[models.overrides]` maps a work type to a model, for example `"data migration" = { model = "opus", effort = "high" }`. Matched case-insensitively before the tiers. A task's `tier` meta may name an override key. |

### `[merge]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `mode` | `"local"` or `"pr"` | `"local"` | `local`: `close` merges into the main checkout under a `MERGE:` line, as before. `pr`: `close` pushes the task branch and opens a pull or merge request; `record` merges it under a `MERGE:` line when the host reports it clean, and records merges done by anyone from the request state. Setting `pr` is the operator's standing permission to push task branches and open requests. Merging still needs the `MERGE:` line. |
| `host` | `"auto"`, `"github"`, `"gitlab"` | `"auto"` | Which CLI speaks to the host: `gh` or `glab`. `auto` reads the `remote` URL: a host name of `github.com` means GitHub, a host name that contains `gitlab` means GitLab. A self-managed GitLab on another host name needs `host = "gitlab"`. Only read in `pr` mode. |
| `remote` | string | `"origin"` | The git remote the host is reached through. |
| `base` | string | `""` | The branch requests target. `""` means the host's default branch, asked once per `run.py` command. A task launched with `--base <branch>` targets that branch instead (meta `target`). |
| `method` | `"merge"`, `"squash"`, `"rebase"` | `"merge"` | How `record` merges. GitHub: `gh pr merge --merge\|--squash\|--rebase`. GitLab: the project's merge method setting decides between merge commit, rebase and fast-forward; `squash` adds `squash=true`, the other two values add nothing. |

### `[notifications]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `skill` | string | `""` | Skill for messages when all work is complete or the Manager is blocked, for example `"telegram-send:telegram-send"`. With `""`, the Manager reports only in the conversation. |

### Reading config

Agents read config only through [scripts/config.py](scripts/config.py), by
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

`check` reports a missing file, TOML syntax errors with their line, `"TODO"`
values, an empty `taskgraph.project`, unknown sections or keys (with the
closest known key), wrong types (a value outside a fixed choice reads `must be
one of "local", "pr"`), and invalid time zones. It reads no git state and makes
no network call. `get` and `model`
refuse to answer while `check` fails. Exit codes: 0 OK, 2 config problem, 1
unexpected error. It needs Python 3.11 or later; the `config` wrapper finds
one through `scripts/python-path.sh`.

## Briefs

[templates/task-brief.md](templates/task-brief.md) is the one brief template.
Its sections are GOAL, SCOPE, CONTEXT, ACCEPTANCE, VERIFY, TIMEBOX, FORBIDDEN,
AUTONOMY, STANDING ORDERS, and REPORT (the command that files the report). The
report format lives in the worker agent. `run.py` fills the template from
Taskgraph, the config, and the run directory. Task content is copied from
Taskgraph, never written by hand: GOAL is the title plus the prose in the
notes, ACCEPTANCE is the `- [ ]` items and `Exit test:` or `Acceptance:` lines,
SCOPE and VERIFY are the `scope` and `verify` meta, and TIMEBOX is twice the
`estimate` meta (2 hours without one). CONTEXT holds the base commit, the last
checkpoint, the previous report of a fix round, and the latest report of each
task this one depends on. To change the brief for every task, edit the
template. `run.py verify` fills the same template, with verifier values in
GOAL, SCOPE, SETUP, UPSTREAM, and AUTONOMY, and a `Verdict:` line request in
REPORT.

The worker runs `result add` from its own session, so its permission mode
must allow that command. Pin `--db` and allow only `--body-file -` if you
write a permission rule for it. In `auto` mode nothing enforces that rule: the
brief gives the worker the paths to `tg.py` and the database, and only the
worker's instructions keep it to the one `result add` command.

## Run directory

The Manager keeps run state in the gitignored `.agentic-team/`:

| Path | Content |
|------|---------|
| `standing-orders.md` | Numbered operator directives, pasted into every brief. `STOP: <reason>` as the first line halts launches. A line that starts with `MERGE:` lets the Manager merge verified branches into a clean main checkout, or (in `pr` mode) lets `record` merge a clean request. |
| `briefs/task-<id>-<attempt>.md` | Every brief sent, as rendered (`-verify` for a verifier brief, `-verify-<k>` for a second one). A record only; never edited or read as a source. |
| `last-report` | Time of the last status report. |

## Results

Worker reports live in the Taskgraph result log, not in files. Each result has
a `kind`, a `status`, an `attempt`, and an author (`--by`):

| Kind | Status | Written by | Meaning |
|------|--------|------------|---------|
| `task` | `PASS`, `ISSUES`, `BLOCKED` | The worker, as its last action | The report: Task, Status, Branch, Head, Worktree, Ran, Files, Issues, Deviations, Follow-ups, Checkpoint. |
| `task` | `DIED`, `BLOCKED` | The Manager (`--by manager`) | `DIED`: a session that ended with no result. `BLOCKED`: a session stopped while waiting on a permission prompt. A worker report that the Manager copied from `claude logs` keeps the worker's own status. |
| `task` | `STOPPED` | The Manager | A worker stopped for a pause (a second row carries the WIP commit `Head:`), or a session `close` stopped. |
| `task` | `ABANDONED` | The Manager | A session `abandon` stopped. |
| `task` | `PASS` | The Manager | The evidence for an adopted task (`Worktree: None`, `Ran: not stated (adopted)`). |
| `verify` | `PASS`, `ISSUES`, `BLOCKED`, `DIED` | The verifier or the Manager | The verifier files the same report plus a `Verdict:` line. The Manager files its own verdict for a `risk=low` task, and `DIED` for a verifier that ended with no result. |
| `verify` | `PASS`, `ISSUES`, `BLOCKED` | `ci` | The CI run on the pushed head, in `verify_mode = ci:<name>`: `Verdict:`, `Workflow:`, `Run:`, `Head:`, `Branch:`, `Conclusion:`. |

`verify` results by `manager` carry `Verdict:` and `Ran:`; an override adds
`Overrides:` and `Reason:`. Every row filed when
`run.py` stops a session carries `Session: <id>` and `Worktree: <path>` lines;
they are a record, not how sessions are matched.

`tg result ls <id>` lists them. An attempt has arrived when a result exists
for the task's current `attempt` and the task has no `verdict`.

## Task metadata

Task notes hold the purpose and acceptance criteria, following the Taskgraph
skill. Metadata holds everything else, 22 keys:

| Key | Set by | Meaning |
|-----|--------|---------|
| `scope`, `verify`, `tier`, `risk` | plan | Brief inputs. `tier` is a tier name or a `models.overrides` key. `risk=high` sends verification to a separate session. |
| `estimate` | plan | Taskgraph's own estimate in hours. The worker's timebox is twice it. |
| `verify_mode` | plan | `session` (the default) or `ci:<name>`. `ci:<name>`: the CI run on the pushed head is the verifier. GitHub: `<name>` is a workflow file name or workflow name. GitLab: `pipeline` for the whole pipeline, or a job name. |
| `started_at`, `session`, `model`, `attempt` | `launch`, `adopt` | The current attempt, and when it started. `adopt` writes `session=adopted` and no `model`. |
| `sessions` | `launch`, `verify`, `adopt` | A JSON list with one entry per session `run.py` started: `{"id", "kind" (task or verify), "attempt", "name", "worktree"}`. `id` is the short id that `claude --bg` printed, checked against `claude agents`. `adopt` writes `[]`. A task in progress with an attempt and no `sessions` key was started under 0.6.0. |
| `base` | first `launch`, `adopt` | The commit the task branch forked from. Written once; a retry keeps it. The verified change is `base..Head`. |
| `target` | `launch --base <branch>`, `adopt --pr` | The branch the change merges into when it is not `merge.base`. |
| `verdict`, `verdict_ref`, `tokens` | `close` | `artifact-verified`, `test-verified`, `check-only`, `verify-blocked`, or `verify-failed`, tied to the worker's `Head:` commit SHA (or to output checksums when the output is outside git). `verdict_ref` moves to the new head after an accepted rebase. `tokens` is `"<out>/<in>"`, from the session transcript under the task's worktree path (the session whose id is recorded for the current attempt); the cache counts are printed on the `tokens` event line. When there are none, that line names the reason (no session id, folder not found, no matching transcript); a full session id is also looked up in the other project folders under `~/.claude/projects`. |
| `pr` | publish, `adopt` | The request number (GitHub PR number, GitLab MR `iid`). |
| `pr_branch` | publish, `adopt` | The branch on the remote that the request's head is. Default `task-<id>`. |
| `pushed` | publish, `adopt`, `record` | The request head SHA as `run.py` last pushed it or last saw it merged. The lease for every later push and the guard for every merge. |
| `merged_at`, `merged_by` | `close`, `merged`, `record` | Set when the task's branch is confirmed merged. `merged_by` is `manager` or `operator`. In `pr` mode `record` sets them from the request state. A done task with a commit `verdict_ref` and no `merged_at` is listed as "Done, branch not merged", and tasks that depend on it do not launch. |
| `abandoned` | `abandon` | One word: `died`, `tool-error`, `stuck`, or `unknown`. Set when attempt 3 has failed. Only this marker lists a task as abandoned. |

`launch` never unsets `pr`, `pr_branch`, `pushed`, or `target`: a task has one
request across attempts.

### Upgrading from 0.6.0

Version 0.7.0 gives a task one worktree for its whole life; 0.6.0 gave each
attempt its own (`.claude/worktrees/task-<id>-<attempt>`). Finish or abandon
the tasks in flight before you upgrade. `run.py` does not migrate a task that
0.6.0 started: a task in progress with an attempt and no `sessions` meta is
`legacy`. `record` prints one `legacy` line for it and skips it, and `launch`,
`verify`, `close`, `stop`, and `abandon` refuse it with the same text. Once its
session has ended and its result is filed, declare it a 0.7.0 task with
`tg edit <id> --meta sessions='[]'`, then run `run.py record`. The next
`launch` creates `.claude/worktrees/task-<id>` at the last reported `Head`. The
old folders stay; `cleanup` lists them as `no session; remove it by hand if you
want`, and removes nothing of a 0.6.0 task that is done.

## Layout

| Path | Purpose |
|------|---------|
| `agents/manager.md` | The Manager index |
| `agents/worker.md` | The worker agent used for every task and verifier session |
| `playbooks/` | Step-by-step procedures the Manager follows |
| `skills/principle-*/` | One principle each, hidden from automatic invocation |
| `skills/manager/` | `/agentic-team:manager`, which makes a running session act as the Manager |
| `skills/setup/` | `/agentic-team:setup`, which creates the project config |
| `templates/` | Project config (`agentic-team.toml`), the brief, and standing orders |
| `assets/diagrams/` | Mermaid sources for the README diagrams, their SVGs, and `render.mjs` (Pele) |
| `scripts/run`, `scripts/config`, `scripts/tg` | Wrappers that run `run.py`, `config.py`, and `tg.py` with a Python 3.11 or later, from any directory. Prompts use these and never a variable. |
| `scripts/tg-path.sh` | Finds the installed Taskgraph CLI. `TASKGRAPH_TG` overrides it. |
| `scripts/python-path.sh` | Finds a Python 3.11 or later. `AGENTIC_TEAM_PYTHON` overrides it. |
| `scripts/config.py` | Reads, merges, and validates the project config; holds every default |
| `scripts/host.py` | The code host seam: GitHub through `gh`, GitLab through `glab` |
| `scripts/run.py` | Launches, adopts, drains, verifies, closes, merges, stops, abandons, and reports |
| `tests/` | Tests for the scripts, with a fake `claude`, a fake `gh`, and a fake `glab`. Run `uv run --python 3.11 --with pytest python -m pytest plugins/agentic-team/tests -q`. |

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
  in [scripts/config.py](scripts/config.py), then document it under
  Configuration above and in [the template](templates/agentic-team.toml).
  Read it with `config.py get`.
- **Preloading.** The Manager's `skills:` list preloads only when it runs as a
  subagent; as the main agent it loads them itself (see `agents/manager.md`).
  Use qualified `plugin:skill` names, and keep the list short. Skills with
  `disable-model-invocation: true` cannot be preloaded, which is why
  principles are read by path.
