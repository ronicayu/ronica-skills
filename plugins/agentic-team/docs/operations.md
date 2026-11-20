# Operations

Running the plugin day to day: the compaction hook, report checks, worker hooks, notifications, cost in `status`, the run directory and the permission rules that workers need.

## The compaction hook

After a context compaction, the Manager would have only a summary. The plugin
ships a `SessionStart` hook with the matcher `compact` (`hooks/hooks.json`,
`scripts/recompact`, `scripts/recompact.py`) that puts the role and the orders
back, in the Manager session only. `run.py` writes the Manager's session id
(`$CLAUDE_CODE_SESSION_ID`) to `.agentic-team/manager-session` in `notify-to` (with a name or `--clear`: Start step
4), and in `record` only when the file does not exist yet, so a `record` in another Claude session never takes the
Manager's place. The hook finds
the project from the session's working directory (the nearest directory upward
with `.agentic-team.toml`) and prints nothing unless the session id equals that
file's. In the Manager session it adds to the context, in this order: an
instruction to read `agents/manager.md` in full first (the hook does not inline
it), `standing-orders.md`, `manager-orders.md` (when it exists), a short
`run status --brief` (work not yet closed, and open decisions), and an
instruction to run `run record` and start `run wait` again. The context is at
most 9000 characters, because Claude Code replaces a longer one with a preview.
An orders file that does not fit is not inlined: the hook gives its absolute
path, and the Manager reads it in full. The status has a 5 second limit; when it
is slow, the hook gives the rest without it. Workers and other sessions get
nothing. On any error (no run directory, an unreadable file, bad input) the
hook exits 0 with no output; it never blocks a session
start. If you wrote a user-level hook for this, delete it after the upgrade.

## Report checks

`[report] checks` lets a project put its own quality gate before the verifier. The worker brief's `check-report`
command gains one `--check=<command>` for each command of `checks` and then of `checks_by_kind` for the task's verify
kind, and `--check-timeout <seconds>`. When the report is a worker `PASS` and has no other problem, `check-report` runs
each command through the shell in the task worktree, one after the other. A command that exits non-zero, or runs longer
than `check_timeout_seconds`, refuses the `PASS`: the problem names the command and, for an exit code, the last 20
lines of its output; the later commands do not run. `ISSUES` and `BLOCKED` reports, verifier reports, and a rebase
round (which gets no checks, as it gets no `--require-ran`) are not checked.

Each command writes its output to a temporary file, not a pipe, so a child that keeps the output open cannot hold
`check-report` after a timeout. On a timeout, SIGTERM or SIGINT, `check-report` kills the command's process group and
every process below it, also one that ran `setsid`. The worker brief tells the worker to run `check-report` with a
Bash timeout of at least the sum of the check timeouts plus 60 seconds, or in the background with Monitor (Bash allows
600 seconds in the foreground at most).

The checks judge committed code. `check-report` refuses a `PASS` when `git status --porcelain` lists changes before the
checks run (commit first), and when it lists changes after a check ran (the check left files behind; the problem names
them). A path that git ignores does not count.

How the gap of a worker that leaves out the flags is closed: `record` runs the same checks itself. When a worker `PASS`
row arrives (filed by the worker or salvaged) and `[report] checks` apply to the task's verify kind, `record` runs them in
the task worktree, at the `Head:` of the report, under the same clean-tree rule. A failure files an `ISSUES` row by the
Manager in place of the `PASS`: the worker's report with its `Status:` replaced and an `Issues: blocking:` line that
names the command and the end of its output. This is the path that `record` already uses for a report it recovers
(`salvage` files the row, and the task follows the ISSUES rows: a fix round or a revision), so the next step is the
usual `fix round:` hint, and `verify` never sees the PASS. Each PASS row is checked once (its id is kept in
`inbox/<id>-<attempt>.checked` of the run directory). `record` skips the checks, with a `checks-skipped` line, when the
worktree is gone or is not at the reported `Head`, and waits while a worker session is still busy in it.

```toml
[report]
checks = ["make lint"]
[report.checks_by_kind]
design-doc = ["python docs/models/check_refs.py"]   # a stale `file:line` reference fails before a verifier reads it
```

## Self-review before PASS

The worker brief adds a step to its VERIFY section by verify kind, and `agents/worker.md` repeats it. For `design-doc`,
the worker starts a read-only Sonnet subagent (the Agent tool, not a fork) that checks the document for internal
contradictions, non-deterministic wording and every statement about the current code (`git grep`, or the cited lines),
pastes its findings under `Ran:` as `self-check:` lines and fixes the false ones. For `code`, the worker runs guard
mutations (it breaks the code under test on purpose: it mutates the file in place, runs the covering tests and confirms
that they fail, restores the file with `git checkout -- <file>` and confirms that `git status` is clean) and pastes each
red run as a `mutation:` line. A mutation in a copy of one file tests nothing, because the tests import from the worktree. `schema` and a rebase round have no step. The verify method for each kind says that the verifier treats
these lines as the worker's claim. To make a step required, list its prefix in `require_ran`.

## Worker hooks

With `hooks.enabled = true`, `run.py launch` (and `round`) start each worker with `--settings` that carry three more
hooks. They belong to that one session: run.py writes them into the `--settings` of the start, there is no plugin-level
`hooks/hooks.json` for them, and no other session on the machine sees them. Their scripts are in
[scripts/hooks/](../scripts/hooks/) (Python 3, standard library only, about 20 ms a call for the `pre` hook), and each reads its settings from
`.agentic-team/hooks/task-<id>-<attempt>.json`, which run.py writes at the start. A hook that fails for any reason exits 0
and changes nothing.

| Hook | What it does |
|------|--------------|
| `PreToolUse` on `Bash` (`layered`) | Rewrites a command that is one of `commands` so that the command's own output and exit code reach a reducer. Output under `passthrough_chars` is left as it is. At exit 0 only the result lines stay (`60 passed in 1.20s`). At a failure the output keeps, in this order of priority: the `FAILED` lines and the assert, error, compiler (`error TS`), `make ***`, linker, crash (`Segmentation fault`, `Killed`, `Aborted`) and timeout lines (at most 60); a key line that repeats (digits and paths ignored) shows once with its count, `(×45)`, and the first line with `Error:`, `Traceback`, `Caused by` or `E ` is always kept; then `file:line` references up to 90 lines in all; then the last 15 lines. All are copied from the full output; when lines are left out the text says how many. The same rules run at exit 0 when a `FAILED` or error line matches, and always for log commands (`gh run view --log`, `docker logs`), which exit 0 whatever the log says. A line is read up to 2,000 characters, and the reducer stops after 5 seconds and prints the full output. When no rule matches, the output stays as it is, unless `summarize_fallback` is on and the output is above `large_chars`. The command's exit code is kept, so the session still sees the failure. The full output is in `.agentic-team-scratch/hook-output/<tool call>.txt` of the worker's worktree; files older than three days go. A saved output over 20 MB is cut to its first and last 10 MB, with a marker. Before the command runs, one line says where the output is saved when it is reduced, so a timeout still shows the path (a short output is passed through and its file removed). |
| `PreCompact` (`compact_pins`) | Its output becomes part of the compaction instructions: the summary keeps the task id and attempt, GOAL, SCOPE, ACCEPTANCE, VERIFY, the open `finding` steers (`F1`..`Fn`), the Head and the uncommitted changes, word for word, in a section PINNED FACTS. The facts come from the attempt's brief file, the task's mailbox rows and `git` in the worktree. At most 9,000 characters (Claude Code caps this output at 10,000); the longest section is cut first, and a cut says so. |
| `SessionStart`, matcher `compact` (`compact_pins`) | After a compaction, it gives the same facts back as `additionalContext`, with the same limit. |

What the layered hook wraps. It looks through `cd <dir> &&`, `;` and newline, leading `NAME=value`, `export`, `env`, `time`
and `scripts/with-slot.sh`, and tests the rest against `commands`. It wraps only when every earlier part is a `cd` or an
assignment. When it is not sure it does not wrap: a pipe (`pytest | tail`), `||`, a later command (`pytest && make lint`), a
background `&`, a redirect other than `2>&1` and `2>/dev/null`, a substitution, a group or subshell, a comment, a
here-document, a trailing backslash, an unclosed quote, `run_in_background`, and a command that never ends or waits for a person (`--watch`, `vitest -w`, `--follow`, `docker logs -f`, `--ui`, `--debug`, `show-report`, any word with `watch` in it such as `vitest watch` or `make test-watch`, `pytest -f`, `--looponfail`, `--pdb`, `--trace`). Read, Edit, Grep and every other tool are never
touched. The wrapped command runs in the session's own shell, inside braces, so `cd`, the environment and shell functions
behave as before; stdout and stderr are merged, as the session shows them. If the reducer itself fails, the wrapper prints the
full output.

A verifier gets no worker hooks. It judges raw evidence, its session is short, and it runs the tests itself, so a reduced
output would be a different thing from the one it reports. A resume (`answer`, `steer`, a revision) uses the full session id
(`sessionId`), which wakes the session with the settings it was started with, hooks included; the saved options are replayed
only for a full id, and a short id makes a copy. When the job is gone and `run.py` resumes the conversation with the launch
flags, it passes the hooks again and always writes the config file again.

Risks. `config.py check` reports a problem when `[hooks] enabled` is set and `sessions.permission_mode` is not `auto` or `bypassPermissions`: an allow rule such as `Bash(pytest:*)` does not match the rewritten command. The layered hook rewrites the command the session runs, so the command shown in the transcript is the wrapper. It
was tested in `auto` permission mode only; another mode may ask for permission on the rewritten command. A command that reads
standard input, or that is interactive, is not a case it handles. The Haiku fallback can miss lines; it is off by default.
Extraction rules are patterns for pytest, vitest, Playwright and common error lines; a tool with another format falls
through to the unchanged output. In a measured spike, reduced output cut the cost of a failing test task by about 40% and
kept every answer right; ordinary reads and passing output of other commands gain little.

To turn it on, put this in `.agentic-team.toml` or `.agentic-team.local.toml`:

```toml
[hooks]
enabled = true
```

It applies to the workers started after the change; a running worker keeps its saved settings.

## Notifications

The operator hears from the Manager on events, not on a schedule. `run.py` never sends a message: it queues a notice in `.agentic-team/notify-queue.jsonl`, and the Manager sends the queue through `[notifications] skill` in one message after each drain (run playbook, "Notify").

| Event | Queued when |
|-------|-------------|
| `decision` | `run.py add --type decision --meta decider=operator` creates a decision. Pass `--due <date>` and `--meta default="<text>"`: the notice carries the default and the deadline. |
| `abandon` | `run.py abandon` drops a task (the `abandoned` line). |
| `push-failed` | A push of a task branch did not reach the remote (the `push-failed` line). |
| `pr-closed` | A request was closed without a merge (the `pr-closed` line, from `record`, `repoint` or a round). |
| `all-done` | The Manager adds it with `notify-queue --add all-done "<line>"` when all work is complete. |
| `blocked` | The Manager adds it with `notify-queue --add blocked "<line>"` when it is blocked. The same line notifies once; a new reason notifies again. |
| `workflow-cancelled` | Not in the default list. `run.py stage <instance> cancel` ended an instance; the notice names the tasks that wait for it and never start. |
| `workflow-pick` | Not in the default list. `run.py add --pick` or a hard rule chose an unsure workflow or changed the work (the `workflow-picked` and `workflow-rule` lines); the notice is for information, the owner is never asked. |

A notice always carries the operator-facing text of its event as its `next:` (what the operator can do), never the Manager's command hint that the same event prints in the `run.py` output. The queue is guarded by a lock (`notify-queue.lock`): `--clear` clears exactly the notices it prints.

`[notifications] events` lists the events that notify; a notice for an event that is not listed is never queued. Each notice has a key (event, task, attempt and text): one that is queued or was cleared as sent is not queued again, so a `pr-closed` line that every `record` repeats notifies once, and a new failure (a new head, a new reason) notifies again. `all-done` and `blocked` dedup only against the queue, since the same words can be true again later.

With `digest = "daily"`, `run.py notify-queue --digest` prints one digest a day (the first call of each day in the project time zone): what merged or finished since the last digest that was sent (the last day on the first run), what is in flight, the decisions waiting, and, when there are any, the workflow picks that were unsure or changed by a rule. The Manager adds it to the same message, then runs `notify-queue --digest --sent`; the digest counts as made only then, so a digest that was printed and never sent is printed again. With events and the daily digest on, a periodic brief is not needed; a project's own cron is the project's choice.

## Cost in status

When a session's `usage` is known (`record` writes it from the transcript, each message id once; see the [0.28.2 entry of the changelog](../CHANGELOG.md#0282)),
`run.py status` adds an `Est. cost` column to the Done and In flight tables, and `--json` adds the `Est. cost` key. A cell is
the sum over the task's sessions, each priced at its model's family in `MODEL_PRICES` (`scripts/run.py`): list prices from
platform.claude.com/docs/en/about-claude/pricing, fetched 2026-11-18, USD per million tokens, cache write at the 5-minute
price. The table is keyed by model family and version, so an older pinned model gets its own price, not the current
family price: `claude-opus-4-1` is $15/$75, `opus` is Opus 5.5. A bare alias (`opus[1m]`, `sonnet`) is the family's
current model. A session whose model id is not in the table adds nothing and puts a `+` after the amount. Without any
known usage the column does not appear. It is an estimate, with two gaps. Haiku 5.5 costs $0.50 / $2.50 per million
input / output tokens for a request whose prompt is over 100,000 tokens (the usual $0.10 / $0.50 below), and the
estimate uses the lower price, because a summed usage cannot tell which request was long. Subagent costs are not counted:
the self-check of a `design-doc` task, the Sonnet reads of a `judgement` task and any other subagent a session starts bill
under their own transcripts, which `record` does not read.

## Running a workflow retro

Each workflow instance writes its own history: the pick (both answers, the seeds, the rule, `unsure`), the hard rules that applied, the owner's overrides, each adjustment (escalate, downgrade, replace, cancel) with its trigger (`verifier`, `worker`, `rule`, `manager` or `orphan`) and the row that caused it, and, on each stage task and approval decision, the attempts, revisions, verdicts, blocking findings by category, the time from created to merged, and how the approval ended (`approved`, `defaulted` or `held`, by whom, when). Nothing else needs to be kept. The retro reads Taskgraph only, needs no model, and changes nothing.

```
run.py workflows --stats                  # all instances
run.py workflows --stats --since 2026-12-01 --json
```

Run it after about 20 instances, then every month or so. It prints, for each workflow and each of its stages:

| Group | What it shows | What it tells you |
|---|---|---|
| Instances | merged, cancelled and running counts; completion and cancel rates | whether the workflow ends |
| Adjustments | escalations, downgrades, replacements, and `kind:trigger` counts; the instances escalated | the workflow was too light (escalations) or too heavy (downgrades) |
| Pick | instances picked with `--pick`; agreement rate of the two answers; `unsure` rate; owner overrides; escalations after the pick; accuracy (instances neither overridden nor escalated) | whether the descriptions separate the workflows |
| Stage | tasks, merged, skipped; mean attempts and revisions; first-pass verify rate (the first verifier verdict is not `verify-failed` or `verify-blocked`); blocking findings by category; median hours from the start of the stage's latest attempt to its merge (waiting for upstream stages is not counted); a split stage counts once for each instance in the rates | where a stage is weak or slow |
| Approval | answered of total; outcomes; default rate; hold rate; median wait | whether the due times and levels fit |

Then it prints candidate changes. A rate rule needs a minimum of data and at least 2 instances that hit it (`min_hits`), so one bad instance proposes nothing. Each proposal names its evidence: the instance ids and `count of N`.

| Proposal | When it fires (defaults) | What it suggests |
|---|---|---|
| `escalation` | a workflow escalated to one stage type in at least 30% of at least 3 instances | add that stage to the workflow as a required stage, add a hard rule for the paths, or tighten the workflow's When-to-use |
| `drop-stage` | an optional stage that was skipped or downgraded in at least 90% of at least 3 ended instances that decided it (an instance that left it out by default, or escalated to it, does not count) | drop it from the workflow |
| `auto-approval` | a stage with a `manager` approval passed its first verify in at least 95% of at least 4 verified stages | set `approval = "auto"` |
| `weak-stage` | a stage failed its first verify in at least 50% of at least 4 verified stages | tighten its Stage notes or split it; the top category is named |
| `approval-defaults` | an approval was applied by default in at least 50% of at least 4 answers | make it `manager`, or raise `human_due_hours` |
| `pick-unsure` | at least 40% of at least 3 picks had an `unsure` answer | sharpen the When-to-use of the workflow |
| `pick-corrected` | at least 20% of at least 3 instances were overridden, or escalated by a verifier, worker or the Manager (not by a hard rule), after the pick | sharpen its When-to-use |
| `cancels` | at least 20% of at least 3 instances were cancelled | read the `why` lines; fix the stage that orphaned them |

The owner approves each proposal once, at retro time. Nothing applies by itself: each approved change becomes one task that edits a workflow file under `.claude/agentic-team/workflows/` or a `[[workflow_rule]]`. Declined proposals appear again at the next retro if the evidence still holds. The thresholds are in `THRESHOLDS` in `scripts/workflow_stats.py`; the statistics are `compute` and the proposals `propose` there, over data that `run.py` reads from Taskgraph.

## Run directory

The Manager keeps run state in the gitignored `.agentic-team/`:

| Path | Content |
|------|---------|
| `standing-orders.md` | Numbered operator directives, pasted into every brief. `STOP: <reason>` as the first line halts launches. A line that starts with `MERGE:` lets the Manager merge verified branches into a clean main checkout, or (in `pr` mode) lets `record` merge a clean request. |
| `briefs/task-<id>-<attempt>.md` | Every brief sent, as rendered (`-verify` for a verifier brief, `-verify-<k>` for a second one). A record only; never edited or read as a source. |
| `manager-session` | The Manager's session id, one line, written by `run.py` from `$CLAUDE_CODE_SESSION_ID`: `notify-to` replaces it, `record` writes it only when there is none; the compaction hook gives the role and orders back only to the session it names. |
| `manager-orders.md` | Optional. Orders for the Manager only (not pasted into briefs); the compaction hook shows it in full. |
| `last-report` | Time of the last status report. |
| `notify-to` | The Manager's session name, one line, from `run.py notify-to`. Each brief rendered while it is set has a notify step. The Manager sets it at Start. |
| `notify-queue.jsonl` | The operator notices that events queued and the Manager has not sent: one JSON object a line (`key`, `event`, `task`, `attempt`, `line`, `do`, `default`, `due`, `at`). |
| `notify-sent` | The key of each notice that `notify-queue --clear` counted as sent, one per line; the same event never queues again. |
| `notify-digest` | The time (UTC) of the last daily digest that `notify-queue --digest --sent` marked as sent. `notify-digest.pending` holds the time of the digest that was printed and not yet marked. |
| `notify-queue.lock` | The lock that guards `notify-queue.jsonl` and `notify-sent`. |
| `manager.addr` | The Manager's inbox socket, as JSON, from `$CLAUDE_CODE_MESSAGING_SOCKET`; `run.py` refreshes it on every call that has the variable. Each brief's notify step names it as `uds:<path>`. |
| `inbox/` | Per attempt: `<task>-<attempt>.ctx.json` (the context that `mailbox.py` reads), `<task>-<attempt>.addr` (written by the worker's `SessionStart` hook); `task-<id>-<attempt>.flag` (the pointer line that the `PostToolUse` hook shows while a message waits). Removed with the task's worktree. |
| `hooks/task-<id>-<attempt>.json` | Per attempt, with `hooks.enabled`: the settings of the worker hooks (see [Worker hooks](#worker-hooks)): the commands and sizes, and the paths of the brief and the context file. Rewritten at each start of the attempt. |
| `locks/task-<id>.lock` | The task's lock file (see [Messaging](messaging.md)). It is never removed. |
| `sweep-cache.json` | The last `git status` result of each folder `record`'s sweep checked, with the folder's modification times and when it was checked (see [Lifecycle](lifecycle.md#verdict-and-close)). Safe to delete: the next `record` checks every folder again. A damaged file reads as empty. |
| `stopped-sessions` | The session ids that `run.py` stopped, one per line. `claude stop` keeps a row's state and removes its status and pid, so a stopped `working` row looks like a dead one; a row listed here counts as ended at once. |

A session's report file is not in this folder. It is
`.agentic-team/report-<session>.md` in the session's own worktree, one file per
session name, so a retry never reads the report of an earlier attempt. `run.py`
adds `/.agentic-team/` to `info/exclude` in the common git dir, once, at each
launch and verify, so git ignores the file in every worktree. It deletes a file
of the same session name right before the session starts. The file goes with
the worktree after the merge: `.agentic-team/` is on the disposable list.

A session keeps every temporary file and folder in `.agentic-team-scratch/` at
the top of its own worktree, never in `mktemp`, `/tmp` or another folder
outside it: a write outside the worktree can raise a permission prompt that
stalls a session nobody watches. Before a `launch`, a `verify` or a resume
starts a session, `run.py` adds `/.agentic-team-scratch/` to the same
`info/exclude` (once; other lines stay), so git ignores the folder in every
worktree. A line that cannot be written refuses the launch or the verify, and
the message names the file and the fix: a folder left in a worktree that does
not ignore it shows as uncommitted and keeps the worktree. The folder is on the
disposable list too. No session deletes what it put there, because a deletion
can stall an unattended session on a permission prompt; `run.py` removes the
folder with the worktree after the merge.

### Auto-mode allow rules for workers

A worker uses scratch folders and cold-cache runs, both inside its worktree's
`.agentic-team-scratch/` (it never uses `/tmp` or `mktemp`). In auto
mode, a prompt on these steps stalls a session nobody watches. Add rules like these
to `autoMode.allow` in the Claude Code settings of the operator (`~/.claude/settings.json`),
and change the paths to your own:

```json
{
  "autoMode": {
    "allow": [
      "$defaults",
      "Scratch folders in worker worktrees: inside a git worktree under <repo>/.claude/worktrees/, creating folders under that worktree's .agentic-team-scratch/ and writing or copying files into them is routine and allowed. A worker may also delete a cache folder inside its own worktree that its own test or build run created, such as node_modules/.cache, .pytest_cache, .ruff_cache or a .vitest cache. Deleting scratch folders is not allowed."
    ]
  }
}
```

A rule is free text that the auto-mode classifier reads. Keep `"$defaults"` first so the
built-in rules stay. A rule must not allow deleting a shared cache or a path outside
the worktrees. The rule allows what `agents/worker.md` needs and no more: a worker
creates and writes scratch folders and leaves them in place (`run.py` removes them with
the worktree), and deletes only a cache folder of its own run.

A worker that runs under another Claude profile (a `CLAUDE_CONFIG_DIR`, see "Workers on
more than one Claude profile") reads the settings of that profile, not
`~/.claude/settings.json`. Put the rule in each such profile's `settings.json` too.
