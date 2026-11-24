# Changelog

Each entry says what a version changes and, where it needs one, how to upgrade from the version before it. The newest version is first. For the current behaviour see the [README](README.md) and [docs/](docs/).

## 0.33.2

Upgrading from 0.33.1. From the honest-router pr-manager trial.

- **A worker never merges or opens a request.** A worker followed the repository's CLAUDE.md ("squash merge when CI is green"), ran `gh pr merge` before its verifier had filed PASS, and `close` then opened a second request for the same head. `agents/worker.md` now says up front that a worker or verifier never runs `git push`, `gh pr create|ready|merge|close|edit|comment`, `gh pr update-branch`, a `glab mr` write or `gh run rerun|cancel`, whatever the repository's own docs say.
- **`close` and `verify` (ci mode) refuse to publish a head the target already holds.** Before the first publish of a task (no `pushed` and no `pr` meta), `run.py` fetches the target and proves the head is in it: the head is an ancestor of the target, or merging it into the target leaves the target's tree unchanged (a squash or rebase merge). A patch match on the top commit alone does not count. If the target holds the head, nothing is pushed and no request is opened; the refusal says `run.py merged <id> --by operator` records the merge (after `close` first, when the task has no verdict yet).

## 0.33.1

Upgrading from 0.33.0. From the first pr-manager trial (honest-router).

- **pr-manager judges only current runs.** A request is judged only by a CI run on its current head, made against the current target. A request that is `BEHIND`, or whose newest run started before its last update, has no result yet; the agent never orders, merges or reruns on such a stale run. In the trial it judged queued requests by runs on old heads until the project file said so.
- **A pr-manager session can end on its own.** When the Manager's send to `.agentic-team/pr-manager.addr` fails, the Manager starts a new session with the same command and tells the operator; the new session takes the queue over from `.agentic-team/pr-queue.md`.

## 0.33.0

Upgrading from 0.32.0. Nothing changes unless a project starts the new agent.

- **New agent `agentic-team:pr-manager`** (model `haiku`): an optional background session that runs the merge queue on GitHub. It queues only verified agentic-team requests, keeps one ready request at the head and the rest as drafts, readies the head before it rebases it, merges on green CI only the head it pinned (the verified head or its own catch-up of it), holds a failed request until the Manager sends `ready` again, tells working-job failures from summary-job and cleanup failures, cancels only draft `pull_request` runs, and reports `merged`, `ci-failed`, `conflict` and `stuck` to the Manager. It orders the queue by its own judgement and keeps its state in `.agentic-team/pr-queue.md`. Project rules go in `.claude/agentic-team/pr-manager.md`. The CI workflow needs `ready_for_review` in its trigger, heavy jobs that skip drafts, and a per-request concurrency group. Batching is not in the agent; docs/merge.md says how a project adds it with `run.py repoint`. No `run.py` change: `record` records its merges. See [A PR manager session](docs/merge.md#a-pr-manager-session).

## 0.32.0

Upgrading from 0.31.1.

- **Two new roles: `product-manager` and `ux-designer`.** `product-manager` writes PRDs, scope and acceptance criteria, and task breakdowns; `ux-designer` writes user flows, screens with every state, copy and accessibility notes. Each has a Method for the worker and a Review for the verifier, and a default document structure that a project template replaces. The design-doc verifier now takes a role's own structure, or a template in ACCEPTANCE, in place of its default completeness list. Neither lists a skill: the plugin does not manage skills. A project adds its own PRD or UX skill with an extending role (see [Extending a role](docs/roles-and-briefs.md#extending-a-role)).
- **The workflow stages `prd` and `ux` use the new roles** instead of `architect`. Stage tasks that already exist keep the role they were created with; a stage task created after the upgrade (`add --workflow`, `stage expand`, an escalation) gets the new role. `stage replace` keeps the role of the task it replaces; set `--meta role=` on the new task to change it. A project that wants the old behaviour sets `role: architect` on those stages in its workflow file.

## 0.31.1

Upgrading from 0.31.0.

Version 0.31.1 is a patch release for the worker hooks (`[hooks] enabled = true`). It fixes the defects found in the first real trial of the hooks (task 1011 of video-making-tools). With hooks off nothing changes. No migration, no new setting; a project that raised `passthrough_chars` to 40000 because of the lossy output can set it back to the default (20000) if it wants more reduction, and the saved file still has everything.

- **`docker logs` was not reduced.** Cause: for a log command the reducer used the failure rules, and the postgres lines (`2026-11-21 04:12:12.456 UTC [201] ERROR:  duplicate key ...`) matched no error rule. A log with exit 0 and no error line was then treated as pass-through: the reducer printed the whole log and deleted the saved file. Now `ERROR:`, `FATAL:`, `PANIC:` (also with two spaces), `LOG:  ... error` and `level=error` lines are error lines in a log; the `DETAIL`, `HINT`, `CONTEXT` and `STATEMENT` lines after one are kept; a log with no error line shows its last 30 lines and a pointer instead of the whole log. A reduction of a 562 KB log takes about 0.15 s.
- **Log commands are found with options anywhere:** `docker logs --tail 3000 name`, `docker compose [-f file] logs`, `docker-compose logs`, `podman logs`, `kubectl -n ns logs pod`, `journalctl`, `gh run view --log`. `docker compose logs -f`, `kubectl -n ns logs -f` and `journalctl -f` are never wrapped, because they follow.
- **The saved file survives every fallback**, and a fallback that prints the full output says why in one line: `the reducer timed out after 5 s`, `the reducer failed (<error>)`, `no reduction rule matched this output`, or, when the interpreter itself failed, `the reducer did not run`. An output above `passthrough_chars` is never deleted any more.
- **Distinct failing tests no longer merge.** Only identical lines merge into one line with `(×N)`. A line that names a test or a place never merges with a different one, so every distinct `FAILED` test id stays (up to 200). Only when more than 60 error lines are left, lines that differ in digits and name no test or place merge too, shown as `(×N similar)`.
- **Detail blocks.** For the first 8 failures (at most 200 lines) the reducer keeps the vitest `- Expected / + Received` diff (at most 30 lines) and the source frame after it, and for Playwright the `Locator:` and `Timeout:` lines, the call log (at most 15 lines), the source frame and the attachment lines. It says how many failures were cut.
- **Review fixes.** The reduced text is capped at 20,000 characters (detail blocks go first, then ids and error lines, then line width; the first line says what was cut). In a log, `ERROR:` lines are error lines, not test ids. A group of similar lines shows each distinct variant up to 3, so `('127.0.0.1', 5432)` and `6379` both show. `journalctl -fu` and `-xef` are not wrapped. A pattern such as `kubectl logs` or `docker compose logs` matches commands with options before `logs`. `gh run view --log-failed` is a default command. eslint stylish error rows are kept with their file name. A failing log with no error line shows its last lines. The failure count in the detail-block line counts all failures. `--follow=false` and names with `watch` are wrapped. The wrapper tells "did not run" from "ran and failed (exit N)". A second timestamp and zones other than UTC are ignored in a log.
- **Docs.** [Worker hooks](docs/operations.md#worker-hooks) says what is kept, the fallback line, the log commands and how a project can add `ruff`, `eslint`, `tsc`, `pnpm typecheck` and `pnpm lint` to `commands` (not a default).

## 0.31.0

Upgrading from 0.30.0.

Version 0.31.0 adds workflow templates: a markdown playbook that lists the stages of one kind of work (prd, spec, impl, test, ...), the commands that create and change an instance of it, the pick of a workflow from two typed answers, hard rules, and a retro that reads the records. Workflows are off unless `[workflow_policy] enabled = true`; with them off, nothing changes (`run.py add` without `--workflow` is unchanged, and `add --workflow` is refused with a hint). The one lifecycle change is behind workflows too: an attempt that reported can be stopped by an escalation (the `escalated` event and phase rows below, owner decision 4). The `taskgraph` plugin is unchanged. No migration.

**To try them:** set `enabled = true` under `[workflow_policy]` in `.agentic-team.toml` (it is optional, and `config.py check` then also checks the workflow files); run `run.py workflows` to see the five shipped workflows; add work with `run.py add "<title>" --workflow fix --notes ... --meta scope=... verify=...`, or with `--pick "<a>,<b>" --seed <n>` after the Manager and one subagent answered `run.py workflows --pick-prompt`. Add `[[workflow_rule]]` tables for billing, migrations or security if you want a spec stage forced. After about 20 instances run `run.py workflows --stats`. The full walk-through, with every command, is [Workflows](docs/roles-and-briefs.md#workflows); the retro is [Running a workflow retro](docs/operations.md#running-a-workflow-retro).

Workflow templates, phases W1 to W6: the workflow files and their checks, then `run.py add --workflow`, the approval decisions and `run.py stage`, then the pick and the hard rules, the model of a workflow instance, the changes of an instance in flight (escalate, downgrade, replace, cancel, expand), and the retro data and statistics.

- **Retro** (W6). `run.py workflows --stats [--since <date>] [--json]` reads Taskgraph only, with no model, and prints for each workflow and stage: instances, completion and cancel rates, escalations, downgrades, replacements and their triggers, first-pass verify rate and the top blocking categories, mean attempts and revisions, median time from created to merged, approval outcomes (default and hold rates, median wait), and the pick's agreement, `unsure` and accuracy rates. It then prints candidate changes (`escalation`, `drop-stage`, `auto-approval`, `weak-stage`, `approval-defaults`, `pick-unsure`, `pick-corrected`, `cancels`), each with its evidence (instance ids and counts). Nothing is applied: the owner approves them at retro time. The design names it `retro --workflows`; it is a flag of `workflows`. To feed it, each `adjustments` row of the record gains `trigger` (`verifier`, `worker`, `rule`, `manager` or `orphan`); `stage replace` and `stage cancel` now write a row too (they do not count toward `max_adjustments`); and an approval decision gains `opened_at`, `approval_outcome` (`approved`, `defaulted`, `held`), `approved_by` and `answered_at`. See [Running a workflow retro](docs/operations.md#running-a-workflow-retro).
- **Workflow files.** A workflow is a markdown playbook with a restricted YAML frontmatter that lists its stages. The plugin ships `hotfix`, `fix`, `change`, `feature` and `figure-it-out` and a stage library, `stages.toml`, in `templates/workflows/`. A project adds or replaces files in `.claude/agentic-team/workflows/`, and may extend a workflow by one level.
- **`run.py workflows`.** Lists the workflows with their descriptions and stages and exits 1 when a file is broken. `--check` prints only the problems. `--pick-prompt` prints the prompt that picks a workflow, with the options in an order that `--seed` fixes.
- **`[workflow_policy]`.** New optional section with `enabled` (default `false`) and `design_dir` (default `docs/design`). With `enabled = true`, or with workflow files in the project, `config.py check` also validates the workflow files and the stage library.
- **`run.py add --workflow <name>`** (W2). Creates an instance task and one task for each required stage and each `--with` stage, with real `--depends`: a root stage takes the external `--depends`, a later stage depends on its upstream stages and their approval decisions, a task that `--blocks` waits for the whole instance. An optional stage that is not named, or is in `--skip`, is left out and its edges are contracted. The instance is never launched and `record` leaves it out of `unmanaged`. Needs `[workflow_policy] enabled = true`.
- **Approval decisions.** A stage with `approval = "manager"` or `"human"` gets a decision that depends on the stage. It is due `manager_due_hours` (2) or `human_due_hours` (48) after the stage merges and approves by default; `record` applies the default (`approval-due`). A `human` decision is created for the Manager and turns into an owner decision, with one notify-queue notice, when the stage merges. `[[workflow_rule]]` raises an approval, sets `risk` and may set `on_timeout = "hold"` (no deadline); `[workflow_policy] approval_floor` sets the lowest approval for a verify kind.
- **`run.py stage <instance> approve|split <stage>`.** `approve` answers an approval (`--default` after the due time, `--by operator` for the owner's answer, `--decline-split` for a splittable stage that stays whole); `split` adds a part to a stage with `split: true`.
- **The pick** (W3). `run.py add --pick "<a>,<b>" --seed <n>` takes two typed answers (a workflow name or `unsure`): the Manager's own, and one non-fork Sonnet subagent's from the prompt of seed `n+1`. The same name wins; two names take the one with fewer stages in the plan; a name beside `unsure` takes the name; two `unsure` take `figure-it-out`. The record keeps both answers, the seeds, the rule and `unsure`. `run.py workflows --resolve "<a>,<b>"` shows the result and adds nothing. `[workflow_policy] when_unsure` (`lighter`, the default, `heavier` or `figure-it-out`) changes the unsure rows. `playbooks/plan.md` and `agents/manager.md` give the exact procedure. The Manager never asks the owner which workflow to use.
- **Hard rules** (W3). A `[[workflow_rule]]` with `require_stage` forces an optional stage on (`--with`), or moves the work to the lightest workflow that has the stage, and a stage that a rule requires cannot be skipped. Rules match SCOPE paths or the `area` meta, never title words. Each match is a `workflow-rule` line and a row of `workflow_record.rules`. `run.py stage <instance> recheck` matches the rules again (`stage split` does too); `stage <instance> rechoose <workflow>` is the owner's override, before any stage has started.
- **Workflow model** (W5). `model/Workflow.tla` checks one workflow instance with TLC: no stage waits on a stage that does not exist, approvals are never bypassed, a split stage's approval opens only when every part has merged, rule stages are never removed, adjustments are bounded, and every instance ends merged, cancelled, held by the owner, or orphaned with a hint. Configs `wf-*.cfg` and `regress-wf-*.cfg`; the chart `assets/diagrams/workflow-statechart.mmd`. It found two open issues in the code above (an abandoned last stage gets no `stage-orphaned` hint; `rechoose` drops a rule found after a split) and the guards W4 needs. `Lifecycle.tla` models owner decision 4 behind `ESCALATIONS`: an attempt interrupted by an escalation does not count toward the cap (`escalate*.cfg`, `regress-esc-cap.cfg`).
- **Changes in flight** (W4). `run.py stage <instance> escalate <type> --before <stage> --why "..."` puts a stage (normally `spec`) and its approval in front of a stage that is not done: both join the dependencies of every part of it. It is refused past `[workflow_policy] max_adjustments` (new, default 2, escalations plus downgrades), for a second escalation of a stage type, and in front of a busy, merged, abandoned or skipped part or a verifier that has filed no row. An attempt that had reported is stopped in the order the model needs: its idle sessions stop, the WIP is committed, and one `STOPPED` row with the `Head:` and `Reason: escalated` is filed; `record` reads it before the verifier and verdict rows, and its next step is `launch`, which waits for the new stage and does not count toward the 3-attempt cap (the row decides, not `launch --cause escalated`, a new cause that only records why). `stage <instance> downgrade <stage>` skips an optional stage that has not started: its upstream tasks and approvals move to the stages after it before it is marked skipped (`stage_state=skipped`), and it counts as an adjustment; never a required stage, a stage a rule requires or one an escalation added. `replace <stage>` (new `max_replacements`, default 1) and `cancel --why` are offered only on `stage-orphaned`: `replace` makes a new task with the same dependencies and approval decision and takes the abandoned one out of the instance; `cancel` skips what has not started, abandons what still runs in parallel branches (marked `abandoned=cancelled`), closes every approval and ends the instance. `expand --from-row <id>` or `--workflow <name>` creates the stages of a `figure-it-out` instance from the `workflow-plan` block of its investigate report, with the deferred hard rules applied. The orphan hint now names `replace` and `cancel`. New events `escalation-hint`, `escalated`, `downgraded`, `stage-replaced`, `workflow-cancelled` and `workflow-expanded`.
- **W4 review fixes.** `stage expand` applies every `deferred-to-expand` rule (and matches the rules on the paths of the instance, old SCOPE and new), whatever `--meta scope=` says, and the deferred row gets a `resolved` entry. `stage escalate` is refused when the attempt has a passing verdict (`close` it), when the attempt is at the 3-attempt cap and its newest row is a failure (no `escalated` row would exempt the next launch, and `launch --attempt 4` would run without the new stage; the Manager runs `abandon <task> superseded`, `stage <instance> replace <stage>`, then `escalate`, and asks no one), and for a `--rule` that is not configured. `stage recheck` names each started stage that runs without a new approval, and its escalate target skips stages that escalate would refuse. `stage downgrade` and `recheck` take the task locks, and every locked action refuses when the instance's tasks changed while the locks were taken. `stage cancel` drops the queued `decision` notices of the approvals it closes and queues a `workflow-cancelled` notice (optional notification event, like `workflow-pick`) that names the waiting tasks.
- **Triggers** (W4). A worker `Follow-ups:` line labelled `design:` (any status) and a verifier finding `blocking[design]:` on a stage task make `record` print an `escalation-hint` whose `next:` is the escalate command; the Manager runs it itself and never asks the owner. Past the limits the line says to put it in the report.
- **A rule's approval takes effect** (W3 leftover). `stage recheck` creates the approval decision of a stage whose approval was `auto` when a rule raises it (pending, or open when every part has merged) and makes the stages after it that have not started wait for it.
- **Phase edges.** `TRANSITIONS` gains `reported` and `verifying` to `stopped` on `escalated`; `model/phase-view.mjs` labels the `Escalate` step `escalated`, and `model/phase-edges.json` (34 edges) is regenerated from `check.cfg`, `check-pr.cfg`, `overview-revise.cfg` and `escalate.cfg`.
- **Reporting after the fact.** The `workflow-picked`, `workflow-rule` and `workflow-rechosen` events; the Workflow picks section of `run.py status` and the daily digest; and the optional notification event `workflow-pick`, which is not in the default list.
- **Briefs.** A stage brief gets a `Workflow:` line in CONTEXT with the stage's place, each upstream stage's Summary, Files and Head, and the workflow's notes for the stage.
- **Meta.** `workflow`, `workflow_record`, `stage`, `stage_part`, `stage_origin`, `split_declined`, `workflow_notes`, `approval_id` and the approval decision keys stay on the issue on the GitHub backend.

## 0.30.0

Upgrading from 0.29.0.

Version 0.30.0 adds the quality gate before verify, the cost defaults and event-driven operator notifications. No lifecycle, phase or model change (the TLA+ model under `model/` is unchanged); no migration. Every new key is optional, and the shipped defaults keep 0.29.0 behaviour except for the changes listed under Behaviour changes below.

### Behaviour changes from 0.29.0

- **Notification events are on by default.** With a `[notifications] skill` set, the Manager now notifies on `decision`, `abandon`, `push-failed`, `pr-closed`, `all-done` and `blocked`. Set `events = ["all-done", "blocked"]` for the old behaviour.
- **`Summary:` is required.** `check-report` refuses a worker or verifier report with no `Summary:` text, or with a `Summary:` of more than 3 lines or 2,000 characters. A salvaged report is cut to those limits.
- **A machine with fewer `revise` rows than the task's `revision` is refused.** `verify`, `close`, `revise`, `answer` and `steer` refuse the task; `record` prints a `revision-gap` line and takes no action on it. This only happens when `revise` is in `results.local` and the cache is lost or another machine ran the revision; `config.py check` now warns about that setting.
- **`mailbox.py file-verify` flags.** The verifier brief no longer passes `--python` and `--lang`. `file-verify` still accepts both, hidden and ignored, for this release, so verifiers that started from a 0.29.0 brief during an upgrade still file. `--tg` is any existing file, as `run.py` takes it.

### Changes

- **Event-driven notifications.** New `[notifications] events` (default `["decision", "abandon", "push-failed", "pr-closed", "all-done", "blocked"]`) and `digest` (`"off"` or `"daily"`, default `"off"`), and a new command `run.py notify-queue`. `run.py` queues a notice for each listed event; the Manager sends the queue as one message after each drain, through `[notifications] skill`, and clears it. With no `skill`, the notices go in the Manager's reply. The old rule, to notify only when all work is complete or the Manager is blocked, is now the `all-done` and `blocked` events plus four more. With a `skill` set, the Manager now also notifies on `decision`, `abandon`, `push-failed` and `pr-closed`; set `events = ["all-done", "blocked"]` for the old behaviour. A project with its own hourly brief can keep it or drop it. See [Notifications](docs/operations.md#notifications).
- **`[report] checks`, `checks_by_kind`, `check_timeout_seconds`.** New optional keys; empty keeps the old behaviour. See [Report checks](docs/operations.md#report-checks).
- **Issue comment summaries.** A worker report and a verifier report now have a required `Summary:` line (1-3 lines: what behaviour changed, written by the author), and `check-report` refuses a report without it. Taskgraph 1.22.0 or later shows it, as written, above the full body on the issue comment; a `revise` row and a long `ask` or `answer` get a short built text. New optional key `[report] summary_lang = "en" | "zh"` (default `"en"`): the language the session writes the `Summary:` line in. **Upgrade Taskgraph to 1.22.0 on every machine that runs the project, before agentic-team:** with an older Taskgraph every report fails with "unrecognized arguments", and `config.py check` says so. A verifier's brief now ends with `mailbox.py file-verify` where it ended with `tg result add`; the row is the same, but a permission rule written for `tg.py ... result add` no longer matches the verifier's command: allow `mailbox.py file-verify` instead (the worker's `mailbox.py report` is unchanged). Do not put `revise` in `results.local`; it stays off the recommended list because a lost cache cannot be read safely (see [When the local cache is lost](docs/github-backend.md#when-the-local-cache-is-lost)). See [Issue comment summaries](docs/github-backend.md#issue-comment-summaries).
- **Self-review before PASS.** A worker brief for a `design-doc` or `code` task now carries a self-review step (a `self-check:` subagent pass, or `mutation:` guard runs); it is text only, and `check-report` does not require the lines unless `require_ran` does. See [Self-review before PASS](docs/operations.md#self-review-before-pass).
- **A revision verifier no longer runs the whole method again.** The revision brief (and `agents/worker.md`) now says: rerun every VERIFY command and every `Checks` command of the project verify skill at the new head, then check each fixed finding and the code that the revision diff touched. This changes what a verifier does on a revision; there is no setting for it.
- **`[models.verifier_by_tier]`.** A new optional table. `verify` picks the model as: `--model`, then `verifier_by_tier[<the attempt's tier>]`, then `verifier`, then a model that differs from the worker's. The shipped default is an empty table, so a project that sets nothing keeps the 0.28.2 verifier. Recommended: `implementation = "sonnet"`, `judgement = "opus"`. See [Verifier model per tier](docs/configuration.md#verifier-model-per-tier).
- **Judgement-tier brief.** A worker brief for a `judgement` task gains one line: read or search code through a non-fork Sonnet subagent. See [Judgement-tier brief](docs/roles-and-briefs.md#judgement-tier-brief).
- **Cost in `status`.** `Est. cost` column, shown only when usage is known. See [Cost in status](docs/operations.md#cost-in-status).
- **Quality-gate fixes.** `record` now runs the `[report] checks` of a worker `PASS` itself and files `ISSUES` when they fail; `check-report` refuses a `PASS` on a dirty tree before or after the checks, reads each check's output from a temp file and kills a check's whole process tree on a timeout, SIGTERM or SIGINT; `MODEL_PRICES` is per model version; a config command with a newline is an error; a resumed revision verifier prints a note that it keeps its model. A `[models.overrides]` key on Opus or Fable gets the judgement brief. See [Report checks](docs/operations.md#report-checks) and [Cost in status](docs/operations.md#cost-in-status).
- **Documentation restructure.** The README is a quickstart of under 150 lines. The reference (commands, options, configuration keys, events, task metadata and result kinds) is `docs/reference.md`, generated from the code by `scripts/gen_reference.py`; a test fails when it is out of date. The guides moved to `docs/` (lifecycle, merge, messaging, operations, briefs and roles, GitHub backend, configuration, architecture) and the upgrade notes moved here. `Run.emit` now refuses an event name that is not in `scripts/events.py`. A link to a README section now points to one of these files. No setting or behaviour changed.

## 0.29.0

Upgrading from 0.28.2.

Version 0.29.0 adds worker hooks. No lifecycle, phase or model change (`model/Lifecycle.tla` is unchanged: the hooks add no state, event or guard to the attempt lifecycle); no migration. A new `[hooks]` table in `.agentic-team.toml`, all off: `enabled = false` (the master switch), `layered = true`, `compact_pins = true`, `summarize_fallback = false`, `passthrough_chars = 20000`, `large_chars = 100000` and `commands`. With `enabled = false` the launch line, the settings and every file are as in 0.28.2. With `enabled = true`, a worker started afterwards gets a reducer for the output of test, build and log commands, and pinned facts that survive a compaction (see Worker hooks). Read the risks there first: the reducer rewrites the Bash commands of the worker, and it was tested in `auto` permission mode only. Turn it on for one project and read a few transcripts before you keep it. A worker that is already running keeps its saved settings. `run.py` adds `.agentic-team/hooks/` to the run directory; no other file changes.

## 0.28.2

Upgrading from 0.28.1.

Version 0.28.2 fixes the usage of resumed sessions. No lifecycle, phase or model change; no migration.

- **Usage of resumed sessions.** A revision resumed with `claude --resume` has the messages of its parent session in its own transcript, with the same message ids. 0.28.0 counted them again: the `usage` of the `sessions` entry and the `tokens #N` line of `close` were too high for every resumed session (one real revision read out 94,501 and cache-read 34,268,834 where its own messages are out 22,875 and cache-read 10,966,453). Now each message id counts once in a transcript, with the largest count that any of its records shows, and a message that an earlier entry of the same `resumed_from` chain already holds is skipped. Entries that `record` already wrote keep their old `usage`. When a session of the chain has no entry or no transcript, `record` cannot know which messages to skip: it leaves the entry without `usage` and counts `usage_tries`, and at the third try it writes the `usage` with `"partial": true` (the lost session's messages are in it). A copy that a resume started anyway is recorded with `resumed_from` too. The `tokens #N` line of `close` is now the sum over all worker sessions of the attempt, each message id once, followed by `; verifier ...` for the attempt's verifier sessions when they have transcripts, and says `(partial: no transcript for <id>)` when a session has none; the `tokens` meta stays the worker's `<out>/<in>`.

## 0.28.1

Upgrading from 0.28.0.

Version 0.28.1 adds `run.py add`; no lifecycle, phase or model change (it is plan content, so `model/Lifecycle.tla` does not change). The Manager now creates tasks with `run.py add`, which refuses a task whose dependencies are not settled (`--depends`, `--blocks` or `--independent "<reason>"`) and lists the open tasks that may be related. `tg add` still works and is unchanged; the Manager uses it no more (`agents/manager.md`, `playbooks/plan.md`). No migration. A script that calls `tg add` needs no change.

## 0.28.0

Upgrading from 0.27.2.

Version 0.28.0 fixes a bug that lost findings and adds checks and records that a retro needs; no lifecycle, phase or model change (`model/Lifecycle.tla` models the attempt lifecycle, and nothing here adds a state, an event or a guard to it: every item is a field of a row or of the meta, or a refusal inside `check-report`, `abandon` and `launch` that the model does not draw).

- **Bug: `revise` lost findings.** A verifier that wrote one `Issues: blocking: ...` line per finding gave several `Issues:` fields, and `issue_lines()` read only the first, so the `finding` steer of a revision listed some findings and not others. Every `Issues:` field is read now, each up to the next label. `check-report --verifier` warns (exit code unchanged) when a report has more than one: write a single `Issues:` field, one finding per line. `Follow-ups:`, `Evidence:`, `Ran:` and the other report fields are read the same way.
- **`[scope] adjacent`: four new kinds.** `own-dependents`, `own-registry`, `convention-place` and `moved-path` (see [`[scope]`](docs/reference.md#scope)). A project that wrote the same rule into its standing orders can list the kinds instead; the worker brief names them and the verifier brief checks each `adjacent: <kind>: <path>` line under `Deviations:`.
- **`[report] require_ran`.** A new optional table; empty keeps the old behaviour. The worker's `check-report` refuses a `PASS` whose `Ran:` section has no line that starts with a required prefix. `record` does not check a report that it recovers.
- **`Files:` against git.** The worker's `check-report` refuses a `PASS` whose `Files:` leaves out a file of `git diff --name-only <base>...HEAD`. Briefs written by an older `run.py` have no `--base`, so they are not checked.
- **Records.** `sessions` entries gain `plugin`, `cause` (a worker's) and `usage`; `launch --cause` overrides the derived cause. New commands `depcheck` and `triage` file `check` and `triage` rows (Taskgraph accepts any result kind; on the GitHub backend add `check` to the `local` result kinds, since the subagent's answer is long, and leave `triage` as an issue comment: a few short rows per task). The Manager playbook runs `depcheck` after the dependency-check subagent. A subagent type that an update adds loads only after a Claude session restart.
- **`abandon` needs a reason code and `--why`.** The codes are `died`, `tool-error`, `stuck`, `failed`, `scope-wrong`, `superseded`, `operator`; `unknown` is no longer accepted. The `next:` hints still print `run.py abandon <id> <mode>`; add `--why "<text>"`, or the command refuses and says so. Scripts that call it must add `--why`.
- **Verifier categories.** A `blocking:` line may be `blocking[stale-ref]:`, `blocking[claim]:`, `blocking[test]:`, `blocking[scope]:`, `blocking[shots]:` or `blocking[behaviour]:`. The category is optional; every parser that reads `blocking:` accepts the bracket form, and the `F<n>:` lines of a `finding` steer keep it.
- **Times are UTC.** `started_at`, `merged_at`, `repointed_at` and the `Stopped:` line are written as `2026-11-17T09:05:00Z`, not as a local string with a zone label. `status` shows them in `[sessions] timezone`, and shows the older local strings of tasks from 0.27.x as they are. Nothing reads them back as dates, so no migration is needed.

## 0.27.2

Upgrading from 0.27.1.

Version 0.27.2 (issue #129) stops `close` from publishing the commits of a stacked base that already merged under other SHAs; no lifecycle, phase or model change. A task launched with `--base` on a request that later merged by rebase or squash now has its own commits rebased onto the target before the push, or `close` refuses and names the stale commits (see "Stacked base that merged under other SHAs"). `launch` of a retry does the same in the task branch, and a rebase round of such a task rebases with `--onto`. No new config key, no migration.

## 0.27.1

Upgrading from 0.27.0.

Version 0.27.1 (issues #138 and #139) accepts a rebase by someone else and adds a project check after every rebase; no lifecycle, phase or model change. A request branch that a merge-queue manager rebased with the same change no longer ends in `push-refused` (`close`) or `pr-changed` (`record`): `run.py` accepts the new head, or pushes a new head over it. New optional key `[merge] after_rebase = "<shell command>"`; empty or absent keeps the 0.27.0 behaviour. See the `after_rebase` row of the `[merge]` table. The `pr-changed` hint no longer mentions the lost local `host_rebase` meta, because `record` now takes that rebase when the change is the same. No migration. A new agent type that a release adds (for example `agentic-team:dependency-check`) loads only after a Claude session restart, so restart it after the update.

## 0.27.0

Upgrading from 0.26.0.

Version 0.27.0 (issue #140) adds a verify path for changes that only CI can prove and corrects the `check-only` hint; no lifecycle, phase or model change. The `next:` hint of a `check-only` verdict said "or accept it", but no command accepts `check-only`; it now names `run.py verify <id> --again` (with `--ci-ref` in pr mode) or `run.py close <id> --verdict test-verified --override-verifier "<why>" --ran "<CI run URL or artifact link>"`. New: `run.py verify <id> --ci-ref` pushes the worker's `Head` to the scratch branch `ci-<id>-<attempt>` (new key `[verify] ci_ref_prefix`), the verifier judges the CI runs there, later verifies of the attempt move the branch to the new head, and a passing `close`, `abandon`, `round --cancel` or a recorded merge deletes it (new meta `ci_refs`). The `code` verifier method now says that guard mutations which all turn the tests red are test evidence (`test-verified`, not `check-only`), and how to judge a CI-only change. No migration; a running verifier keeps the brief it started with.

## 0.26.0

Upgrading from 0.25.1.

Version 0.26.0 (issue #133) cuts the result rows that a project on the Taskgraph GitHub backend posts as comments.
First, add the `[projects."<name>".results]` block with `local = ["ack", "steer", "check"]` (Taskgraph 1.21.0 or later; see
[Result kinds on the Taskgraph GitHub backend](docs/github-backend.md#result-kinds-on-the-taskgraph-github-backend)); `config.py check`
warns until it is there. On the local SQLite store nothing changes. Second, a revision sends all blocking findings in
one `finding` steer, `F1` to `Fn`, and the worker acks it once with one `F<n>: <action>` line per finding
(`mailbox.py ack <id> --action "F1: ..." --action "F2: ..."`); the report stays refused until the ack names every
finding, and a report lists each under `Deviations:` as `finding F<n>: <what changed>` (see [Messaging](docs/messaging.md#messaging),
Finding steers). A revision that 0.25.0 started (one steer per finding) still works: each of those steers has no `F`
lines and takes the old one-line ack. `run.py` now reads "the rows after the newest `revise` row" in the order of
`tg result ls`, not by id, since local rows have ids of their own range. No lifecycle, phase or model change; no
migration.

## 0.25.1

Upgrading from 0.25.0.

Version 0.25.1 (issue #137) fixes a `verify` in a revision that refused for good: a resumed worker that ended its turn reads `idle/working`, and `verify` counted it as busy. A live row with status `idle` that waits on nothing now counts as turn over once its work of its revision is filed after the row started (a worker report for a recorded worker, a verify row under its name for a verifier); with nothing filed it still works. Every resume of a worker in a revision, a retry too, records the revision on its `sessions` entry. This applies to `verify` (both seats, attempt 1 too), `revise` and the checks for a later revision. In a revision with seat `task`, `verify` now waits `[verify] seat_wait_minutes` after the worker's report for a worker that is still busy, then starts a new verifier in a folder of its own. While revisions are on for the task, such an `idle/working` session is kept like an idle `done` one: it holds no slot of `[sessions] max_parallel`, and `record` stops it (`kept-session-stopped`) once `[verify] keep_sessions_minutes` pass after its newest row of the revision. No migration.

## 0.25.0

Upgrading from 0.24.1.

Version 0.25.0 (issue #130) changes three rules; no lifecycle, phase or model change. First, ask first: a worker asks the Manager before it reports `ISSUES` or `BLOCKED` for a question one answer can settle, and its `ISSUES` or `BLOCKED` report has an `Asked:` line (ask ids, or `none: <one-line reason>`); `check-report` without `--verifier` refuses one without it (see [Messaging](docs/messaging.md#messaging), Ask first). A session started before the upgrade whose check command runs the 0.25.0 `run.py` gets that refusal for an `ISSUES` or `BLOCKED` report; the message names the rule and the line to add, and the report command itself does not check it. Second, a check that fails once and passes on a rerun with no change is a `flake:` follow-up, not `ISSUES`; `flake` is a new Follow-ups label (it shows in `status`). Third, the Manager starts the new read-only subagent `agentic-team:dependency-check` (model `sonnet`) with the Agent tool before the first attempt of each task and before a later attempt on a different base (the run playbook, step 4); it is not skipped for docs-only tasks. `Asked` is a report field: `report_field` stops at it, and a carried report keeps it first after `Status` when it is cut. The software-engineer role asks at once, instead of `BLOCKED` at once, when its census shows that ACCEPTANCE does not fit SCOPE, and the rebase role asks with the conflicting hunks before it reports `BLOCKED`. The dependency check is read-only by instruction: agent frontmatter cannot limit Bash to some commands. The Manager's "Brief frozen" rule now lets SCOPE widen to answer such an ask. No migration.

## 0.24.1

Upgrading from 0.24.0.

Version 0.24.1 fixes a launch that refused for good on a task carried over from 0.22.3: 0.22.3's `close` wrote a STOPPED row with no `Head:` line, and `launch` read it as a stop whose WIP was not committed yet. `record` did not finish such a pause in every phase, so the refusal never cleared. `launch` now finishes an unfinished pause itself, as `record` does: it commits the WIP (nothing when the folder is clean), files the stopped row with its `Head:`, and goes on from there; `--dry-run` says so in a `warn` line. Reported by the vmt Manager (task 760).

## 0.24.0

Upgrading from 0.23.0.

Version 0.24.0 (issue #127) fixes a verifier's blocking findings in place: `run.py revise <id>` sends them to the same worker session, in the same worktree and attempt, and `run.py verify` then resumes the same verifier session (see [Revisions](docs/lifecycle.md#revisions-fix-in-place)). Revisions are on by default: `[verify] revisions_per_attempt = 2`, `keep_sessions_minutes = 60`, and the verifier runs in the task worktree (`seat = "task"`). `revisions_per_attempt = 0` gives the behaviour of 0.23.0; `seat = "own"` keeps the verifier's own folder. The `close` after a verifier's `verify-failed` now hints `revise: run.py revise <id>` when a revision is possible; act on it before a fix round. New: the command `revise`, the result row kind `revise`, the steer kind `finding` (only `revise` files it), the meta keys `revision` and `revisions` (on the issue on the Taskgraph GitHub backend), the `[verify]` keys above, and the events `revised`, `verifier-leftovers`, `seat-fallback` and `kept-session-stopped`. Two folder fixes apply with any setting: a verifier folder goes once its verdict is recorded, and a completed task's clean folder goes while the branch that holds its `HEAD` stays. The folders of done tasks that earlier versions kept go at the next `record` sweep, with a `branch stays` line for each branch that keeps commits. During a revision, run every command of that task with 0.24.0: an older `record` reads no `revise` row and can settle the phase back to `verifying` (0.24.0's `record` tolerates that and lets the revision's rows move it on). No migration.


A `--dry-run` of `launch`, `verify` or `round` starts nothing, so a full session cap no longer refuses it: it prints `warn: cap full: <n>/<cap> sessions live ... (dry run: shown anyway)` and shows the brief and the command.

## 0.23.0

Upgrading from 0.22.3.

Version 0.23.0 (issue #119) adds `run.py round <id> rebase`: a new attempt of a task that waits for its merge and whose change conflicts with its target, on the same branch and request, instead of `abandon` and `launch --attempt`. Each `conflict` line now names the round first and the decision second; in `local` mode `record` prints `conflict` (not `unmerged`) for a branch that `git merge-tree` finds in conflict with its target. A round that fails names `run.py round <id> --cancel`. New: the `[rounds]` config section (`cap = 3`, `verify = "always"`), the shipped role `rebase` (a project file of that name replaces it; `run.py roles` lists it, and the Manager does not give it to a task), the meta keys `round`, `round_from`, `round_verdict`, `round_onto` and `rounds` (on the issue on the Taskgraph GitHub backend), the events `round-started`, `round-cancelled` and `round-not-needed`, and `{{NAME}}` variables in role text. A role file that holds `{{` text of its own keeps it, unless it is one of the names in [Variables in role text](docs/roles-and-briefs.md#variables-in-role-text). No migration.

## 0.22.3

Upgrading from 0.22.2.

Version 0.22.3 (issue #123) is for projects on the Taskgraph GitHub backend; on the local SQLite store nothing changes. The README now owns the list of meta keys that `run.py` writes and their class on that backend ([Meta keys on the Taskgraph GitHub backend](docs/reference.md#meta-keys-on-the-taskgraph-github-backend)); add the `deferred` list (`tokens`, `model`, `started_at`) next to the `local` one. `config.py check` warns for each such key that `.taskgraph.toml` lists in neither. When this machine's cache has lost `sessions` (a new machine, a cleared `~/.taskgraph`), a task in progress is no longer read as a 0.6.0 task: `run.py` rebuilds `sessions` and `session` from `claude agents`, and a task with no row and no result gets a `sessions-lost` line and is left alone, never filed DIED for want of a row (see [When the local cache is lost](docs/github-backend.md#when-the-local-cache-is-lost)). A `pr-changed` line whose `host_rebase` meta was lost says how to let `close` take the host's head. No migration.

## 0.22.2

Upgrading from 0.22.1.

Version 0.22.2 fixes #120: a verifier report whose `Status:` is ISSUES or BLOCKED now reads as `verify-failed` or `verify-blocked` whatever its `Verdict:` line says, so it never closes a task; `check-report --verifier` refuses such a report before it is filed. A task that an earlier version closed from such a report is not reopened: check the verifier rows of your recently closed tasks. The Manager texts state each rule once (about 500 words fewer); no rule changed.

## 0.22.1

Upgrading from 0.22.0.

Version 0.22.1 (issue #117) makes `record` fast on a project with many kept worktree folders: it reads the session list, `lsof` and `git worktree list` once per command instead of once per merged task, and reuses a folder's last `git status` result from the new `.agentic-team/sweep-cache.json` while the folder is unchanged (at most 30 minutes). Before a removal it checks the folder again with fresh data. A `claude rm` that fails with `No job matching` (the CLI no longer has the session) now counts as removed, not as a `kept` line. The shipped role, verify and Manager texts use a few precise terms instead of longer wording: triage / won't-fix for follow-ups, fail-to-pass test, deterministic transition table (at most one transition fires per state and event), observable behaviour change and pure refactor. On video-making-tools (576 closed tasks, 243 folders) one `record` took 100–140 s.

## 0.22.0

Upgrading from 0.21.0.

Version 0.22.0 (issue #114) adds `extends` to role files: a project role can add to a shipped role instead of replacing it (see [Extending a role](docs/roles-and-briefs.md#extending-a-role)). Nothing changes for an existing role file. A project that keeps a full copy of a shipped role can replace the copy with `extends` and only its own lines, and then gets the shipped role's later changes.

## 0.21.0

Upgrading from 0.20.0.

Version 0.21.0 (issue #111) adds `run.py repoint <id> --pr <n>`: a task that waits for its merge follows another task's request when its change went into that request. No data migration and no Taskgraph change: repoint uses the `tg gate` of Taskgraph 1.19.0.

- **Combined requests.** Before, a task whose change went into another request kept its own request, which stayed open with a conflict: every `record` printed `conflict` with a decision, closing it gave the `abandon` hint, and the only way out was `run.py merged <id> --by operator` after the combined request merged, which `run.py` did not check. Now run `run.py repoint <id> --pr <n>` for each such task (it closes the old request; `--keep-old` keeps it open). If you already closed the old requests by hand, repoint still works: it closes only a request that is open.
- **New event names.** `repointed`, `superseded`, `kept-open` (repoint), `follows`, `target-check` and `pr-retargeted` (record). `pr-closed` also comes for a repointed task, with a repoint hint instead of a decision.
- **New meta keys.** `repointed_at`, `repointed_from`, `repointed_branch`, `repointed_pushed`, and `merged_via` on a repointed task once it is merged (see [Task metadata](docs/reference.md#task-metadata)). On the Taskgraph GitHub backend they are written once per repoint or merge, so they need no `local` entry.
- **GitLab.** The close is two `glab api` calls (a note, then `PUT merge_requests/<iid>` with `state_event=close`), unverified like the other GitLab calls (`host.py`, note 13).
- **The followed request's merge completes the task** (the Decision in #111). `record` marks a repointed task merged with `merged_by=repoint` and `merged_via=<n>` as soon as `<n>` is merged, whether or not the task's commit is provably in the target: a combined request that another task redid and rebased often holds neither the commits nor their exact content. The `target-check` line before it is information only (`in target`, or `not proven in target ... may have been redone in <n>`). Its squash case uses `git merge-tree --write-tree` (git 2.38 or later); with an older git that case reads as not proven, which changes nothing else.
- **`merged_by=repoint`.** A new value, with the new key `merged_via`. A report or script that lists the `merged_by` values should add it.

## 0.20.0

Upgrading from 0.19.0.

Version 0.20.0 (issues #104, #106 and #107) makes the reports in a brief shorter, moves four generic worker rules into the plugin, and gives the Manager its role and orders again after a compaction. No data migration, but roll it out in this order:

1. Stop the Manager: let it finish its drain, and stop its background `run wait`.
2. Upgrade `agentic-team` and `taskgraph` together.
3. Start a new Manager session. Claude Code loads plugin hooks when a session starts, so a Manager session that was open during the upgrade has no compaction hook, and its context still names the old plugin path. Its Start step 4 (`run notify-to`) writes `manager-session`.

Then clean the project's own files: remove from `standing-orders.md` and `manager-orders.md` the rules that `agents/worker.md` now has (wait loops, scratch copies, cold caches, deletions) and any rule that contradicts them, such as one that allows `mktemp` or deleting the scratch folder. The compaction hook puts `manager-orders.md` back in full after every compaction, so a stale rule there wins over the playbooks.

- **Worker rules.** `agents/worker.md` now forbids wait loops (`sleep`, countdowns, polling) and sets the rules for scratch copies of the tree and for cold-cache runs. The `architect` role now requires a `stateDiagram-v2` and a transition table for each lifecycle, and its Review checks them. A project can remove its matching standing orders.
- **Allow rules.** See "Auto-mode allow rules for workers". Add them to your settings if workers stop on a prompt for scratch folders or caches.
- **Compaction hook.** The plugin now ships a `SessionStart` hook (matcher `compact`). In the Manager session only, it tells the Manager to read `agents/manager.md` in full, then gives the standing orders, `manager-orders.md` and a short `run status --brief` (see "Start a Manager"). It shows at most 9000 characters; an orders file that does not fit is named by its path, to read in full. `run.py` writes `.agentic-team/manager-session` at `notify-to`, and at `record` only when the file does not exist, so a `record` from another session never takes the Manager's place. The hook loads at session start: a Manager session started before the upgrade has none. A user-level hook that does the same can be deleted. `run.py status --brief` is new.
- **Briefs get shorter.** The previous attempt, each upstream report and the worker report of a verify brief lose their `Ran:` block (see "Carried reports are short" for where it ends). An upstream report is a summary (`Status`, `Head`, `Branch`, `Files`, `Issues`, `Findings`, `Follow-ups`, `Deviations`). Each carried report is at most 3000 bytes and all of them 12000 bytes; every carried report ends with the result id and the command that prints it in full. Decision notes are not cut.
- **See a full report.** Run the command at the end of the carried report, `tg result ls <task id> --kind task --attempt <n>`; it prints every report of that attempt with its `Ran:` log. `tg result ls <task id>` lists them all.
- **New keys.** `[brief] carried_report_bytes` and `carried_total_bytes` change the caps; `config.py check` validates them. Raise them to get longer reports back.
- **A worker that depended on a log.** A worker no longer sees the `Ran:` lines of earlier attempts. The previous attempt's `Issues`, `Findings` and `Checkpoint` stay whole, and so do the `Issues` and `Findings` of the latest verifier report on that attempt, so a fix round after `verify-failed` has what it needs; it prints the full report when it wants the log.
- **A redo of a closed task.** `pr-blocked` (a required check failed) and the refusal of a task that waits for its merge now name the way to a new attempt on the same branch and request: `run.py abandon <id> <mode>`, then `run.py launch <id> --attempt <n>`. A fix task on another branch never turns the request green.
- **Phases of done tasks.** `record` no longer writes a `phase` for a done task that is merged or has nothing to merge; it derives it. A done task with an in-flight phase (closed by a Manager still on 0.18.0) is derived again from its fields, not a `phase-mismatch`, and `run.py merged` accepts it.

## 0.19.0

Upgrading from 0.18.0.

Version 0.19.0 (issue #97) marks a task done only when its change is merged. Roll it out in this order: stop the Manager and its background `run wait`, upgrade `agentic-team` and `taskgraph` together, then start a new Manager session. A Manager session left open on 0.18.0 still closes tasks the old way (done at once), while a newer `record` in another session writes their `phase`; `record` reads such a task from its fields again (see `phase` in [Task metadata](docs/reference.md#task-metadata)), but two versions should not drive one project. The first `record` writes the `phase` of each task it must act on; a finished task gets none, so it stays quick on a project with many done tasks.

- **Done means merged.** A passing `close` that merges at once (a local merge under a `MERGE:` line, a branch with no commit beyond its base, output outside git) still ends with the task done. A close that opens a request, or a local merge that waits, leaves the task in progress with `phase=awaiting_merge`. `tg ready` no longer lists the tasks that depend on it, and the `tg done` comes from the merge record: `record` (the request merged, or the commit in `HEAD`), `close` (a merge), or `run.py merged`. `done_at` is the merge time, so "Done since last report" and the mean attempts count a task when it merges. On the Taskgraph GitHub backend the issue now closes at the merge, not when the request opens.
- **Tasks closed by 0.18.0.** A task that 0.18.0 closed and that is not merged yet (done, a commit `verdict_ref`, no `merged_at`) reads as `awaiting_merge`. `record` writes its `phase`, follows its request or its branch as before, and records the merge; it stays done in Taskgraph meanwhile. Every task in progress, and every done task that waits for its merge, gets its `phase` at the next `record`; a done task that is merged gets none (its phase is derived).
- **The Manager's workaround is gone.** The workaround from #97, a "待合并 #PR：" title prefix and an `awaiting_merge=<PR>` meta on a done task with an open request, is no longer needed: such a task is now in progress with `phase=awaiting_merge`, and `status` lists it under "Closed, awaiting merge". Remove the prefix and the `awaiting_merge` meta key from the tasks that still carry them (`run.py` reads neither).
- **The merge gate.** A task that waits for its merge carries the Taskgraph gate `merge` (see [Task metadata](docs/reference.md#task-metadata)). This needs Taskgraph 1.19.0 (`tg gate`); with an older Taskgraph `run.py` prints one `warn` line per command and goes on without the gate. A task that waits and has no gate (closed before this gate existed, or by a close that stopped before it) gets it at the next `record`, once: a later `record` writes nothing when the gate already says the same. A task that 0.18.0 closed is done in Taskgraph and gets no gate; `record` still follows it and records its merge.
- **`status`.** The "Done, branch not merged" table is now "Closed, awaiting merge"; its `--json` key is `awaiting_merge` (was `unmerged`).
- **Refusals.** `launch`, `adopt`, `verify`, `answer`, `steer` and `stop` refuse a task that waits for its merge. `abandon` accepts it and says what happens to its branch or request.
- **`phase-mismatch`.** `record` prints it when a task's stored `phase` disagrees with its fields on whether it is closed, merged or abandoned, and does nothing else for that task. Fix the meta with `tg edit <id> --meta phase=<phase>`. A done task with an in-flight phase is not a mismatch: `record` and `run.py merged` derive its phase again.

## 0.18.0

Upgrading from 0.17.0.

Version 0.18.0 adds rules from issue #89. No migration.

- **No session deletes scratch.** Sessions leave `.agentic-team-scratch/` in place and `run.py` removes it with the worktree. A `/.agentic-team-scratch/` exclude line that cannot be written now refuses the launch or the verify.
- **Refs, not Closes.** A worker commit message has no `Closes`, `Fixes` or `Resolves` keyword; it writes `Refs #n`. The Manager writes `Closes #n` only when the merge finishes the whole issue.
- **Blocking test.** A finding whose correction changes neither the conclusion, the acceptance verdict, nor what the coders who follow would build is non-blocking; a finding that fits neither list is blocking.
- **Blocking and non-blocking findings.** A verifier writes `blocking: <finding>: <why it blocks>` for every line under `Issues:`, and reports `ISSUES` only when one exists. A finding that does not block goes under `Follow-ups:` as `nonblocking: <finding>: <why it does not block>`, and the verifier reports `PASS`. `nonblocking` is a new Follow-ups label (it shows in `status`). The Manager sorts these follow-ups like the others and never opens a fix round for one.
- **`check-report --verifier`.** The verifier brief passes the flag. With it, an `ISSUES` report needs every `Issues:` line to start with `blocking:`, and `Issues: None` with `ISSUES` is refused; a `PASS` report with an `Issues:` line is refused too. A worker report is checked as before, except for the path check below.
- **Path check.** For a `PASS` or `ISSUES` worker report, every backticked token under `Files:`, `Evidence:` and `Ran:` that looks like a repository path (no whitespace; a `/` in it, or a common file extension; `:<line>` or `:<line>-<line>` dropped) must exist relative to the worktree. A token with `<`, `*`, `$` or `{`, a URL, a flag, or an absolute path outside the worktree is skipped. A line that says `deleted` or `removed` is exempt, and so is a relative path that git ignores (`git check-ignore`), and a relative path with a `..` segment is skipped.
- **`[scope] adjacent`.** A list, empty by default, of the changes a worker may make outside SCOPE without `BLOCKED`: `lower-ratchet`, `stale-exemption`, `own-lint`, `own-dependents`, `own-registry`, `convention-place`, `moved-path` (see [`[scope]`](docs/reference.md#scope)). An unknown kind is a config error.
- **Worker rules for every task.** Fix the root cause and never work around it; pick the option that is best over months; build on the previous attempt's commits; one command per Bash call, a path passed to the tool instead of a `cd` (a bare `cd` only in its own call); a self-review before `PASS`. The `software-engineer` role gains an impact census and the code forms of a workaround (skipped test, `xfail`, type-hiding cast and the like), and loses its long-term-choice rule to the worker. The `architect` role points to the full design template in ACCEPTANCE, required in round 1; every number in a delivered document names its source. A spent attempt cap means re-planning, not another fix round.

## 0.17.0

Upgrading from 0.16.0.

Version 0.17.0 adds task roles (see [Roles](docs/roles-and-briefs.md#roles)): the `role` meta, a `[roles] default` config key, `templates/roles/` with `architect` and `software-engineer`, project roles in `.claude/agentic-team/roles/`, and the `run.py roles` command. A task with no role and no `roles.default` behaves as before. Every brief gains a ROLE section, which reads `None.` for such a task. `launch` also adds the tier source to its `launched` line, and `launch` and `adopt` add `"role"`, `"tier"` and `"verify_kind"` to the attempt's `sessions` entry; `adopt` now writes an entry (with no `"id"`) where it wrote `[]`. No migration.

It also makes a worker prove its `PASS`. A task report gains an `Evidence:` line, one line for each ACCEPTANCE line (the line in short, then the command and its result, or the `path:line`, that proves it), and the worker rule says to prove each check from this run's output. A worker brief's `check-report` command now carries `--acceptance <n>`, and a `PASS` report with fewer than `<n>` evidence lines fails the check; a session started before the upgrade has the old command and is not counted. Sessions now keep temporary files in `.agentic-team-scratch/` at the top of their worktree instead of a `mktemp` folder outside it: `launch`, `verify` and a resume add `/.agentic-team-scratch/` to the repository's `info/exclude`, the folder is on the default disposable list, and the verifier's base-commit export goes to `.agentic-team-scratch/base`, after the verifier has run every head-commit check, and stays there. The Manager gains four rules in `agents/manager.md` and the `run` and `plan` playbooks: the brief of a started worker is frozen (a steer never adds a requirement), every slot stays busy, open requests that conflict with a new base are rebased after each merge in `pr` mode, and no `Follow-ups:` line is left unsorted when a task closes. No migration.

## 0.16.0

Upgrading from 0.15.0.

Version 0.16.0 lets a worker ask the Manager and lets the Manager answer and steer a running worker, across Claude profiles (see [Messaging](docs/messaging.md#messaging)): `mailbox.py`, the `answer`, `steer` and `inbox` commands, `ask`, `answer`, `steer` and `ack` result kinds, a MAILBOX brief section, a `[messaging]` table, and the `mailbox` meta. A project that never uses `ask`, `answer` or `steer` keeps today's behaviour, output and exit codes, with two intended exceptions. First, `launch` now passes a `--settings` JSON to each worker (a `SessionStart` check-in hook and a `PostToolUse` pointer hook), writes `.agentic-team/inbox/<task>-<attempt>.ctx.json`, adds the MAILBOX section to the brief, and gives the worker a new report command (`mailbox.py report`, which runs the same `tg result add` after a check that no steer is unacked), so the `claude --bg` command line and the brief text change. Second, the worker's notify step still uses SendMessage, but its `to` is now `uds:<the Manager's inbox socket>` once any `run.py` call in the Manager's Bash has written `.agentic-team/manager.addr` (that makes the line reach a Manager from a worker on any profile), and the bare session name before that. The verifier gets no hooks and no MAILBOX. `run.py wait` now reads Taskgraph every 5 seconds (`--tg-interval`; `claude agents` still every `--interval`), and `record` reads `claude agents` once for each task in progress (under that task's lock), not once for the whole command. On the Taskgraph GitHub backend add `"mailbox"` and `"mailbox_ids"` to the `local` list under `[projects."<name>".meta]`. Rules 1 and 2 of "Three rules" changed on purpose; see the README. No migration.

## 0.15.0

Upgrading from 0.14.1.

Version 0.15.0 lets a model tier name a Claude profile (a `CLAUDE_CONFIG_DIR`), so one Manager can start workers and verifiers under more than one account: a `[profiles]` table, a `profile` key on tiers and overrides, `--profile` on `launch` and `verify`, and a `profile` key in a `sessions` entry. A project without a `[profiles]` table sees no change: its `sessions` entries, its `claude` calls and its tables stay as they were. To use a second profile, follow [Workers on more than one Claude profile](docs/configuration.md#workers-on-more-than-one-claude-profile): trust the repository and install `agentic-team` in that profile, and mirror the permission rules. No migration.

## 0.14.1

Upgrading from 0.14.0.

Version 0.14.1 lists ready tasks in Taskgraph's priority order: P0 first, then P1, P2 and P3, then tasks without a priority, and by id within each group. `run.py` keeps the order of `tg ready`, and the Manager launches in that order. The plan step may set `--priority` on a task. This needs Taskgraph 1.16.0. A project that sets no priority sees the same order as before. No migration.

## 0.14.0

Upgrading from 0.13.0.

Version 0.14.0 adds a `Checks` section to the project verify skill skeleton (`templates/project-verify-skill-code.md`): the project's lint, format check, type check, other static analysis and tests. The agent that fills the skeleton checks the project's configuration first; when a kind is missing it tells the user, proposes a standard tool, and asks the user to add it, and it writes `none: <reason>` only with the user's reason. The code verifier now runs every `Checks` command at the base and the head: a problem only the head has is an issue, one the base already has is a `found:` follow-up, and a missing or `TODO` kind is a `doc:` follow-up. A project verify skill made before 0.14.0 has no `Checks` section: copy it from the skeleton and fill it, or the verifier reports a `doc:` follow-up for each kind. No migration.

## 0.13.0

Upgrading from 0.12.3.

Version 0.13.0 labels Follow-ups so that they can be counted. Each `Follow-ups:` line of a report is `<label>: <path or question>: <why>`, with a label from `caller`, `doc`, `test`, `other`, `found` and `split` (`split: timebox: <what remains>`). A verifier keeps `decision:`, and `leftover ...` lines keep their own form and are not counted. The new command `run.py check-report <file>` checks a report file before a session files it, and the brief's REPORT section names it. `run.py status` counts the `Follow-ups:` lines of the worker reports filed in the period by label, and gives the mean attempts of the tasks done in the period (`follow_ups` and `attempts` in `--json`). Reports filed before the upgrade have no labels, so their lines count as `unlabelled`: to measure from the upgrade, pass `status --since <upgrade date>`. A session started before the upgrade has no check step and files its report as before. No migration.

## 0.12.3

Upgrading from 0.12.2.

Version 0.12.3 closes a task whose branch holds no commit beyond its base without a merge, a push or a request, and records `merged_by=no-change`. A task that a pr-mode `close` left done with no request finishes at the next `run.py close <id>`.

## 0.12.1

Upgrading from 0.12.0.

Version 0.12.1 stops counting session rows with no process (no status, no pid) toward the session cap, and cleanup removes them once their task is merged. Such a row counts as ended after 30 minutes with no transcript write, as a quiet verifier does. A session that `run.py` stops now counts as ended at once, so `launch` after a `close` that stopped an idle worker no longer refuses. A commit whose patch the target already holds, as after a rebase merge, now counts as merged. No migration.

## 0.12.0

Upgrading from 0.11.3.

Version 0.12.0 makes every `record` hint lead to a command that works. At attempt 3, a hint that would retry names `run.py abandon <id> <mode>` and the `--attempt 4` override. `run.py stop` writes a `Reason:` line: only `Reason: pause`, written under a `STOP` line, lets the next launch pass attempt 3. A `STOPPED` row with no `Reason:` line, such as one filed by 0.11.3, counts as an attempt. `close` and `abandon` also stop a live verifier session. `launch` stops a worker that waits on a prompt after its result, and `record` stops a verifier that waits on a prompt after its verdict and keeps the verdict; a Manager `BLOCKED` verify row no longer hides an earlier verdict. An idle worker with no result gets a `run.py stop` step. No migration: to relaunch a task at attempt 3 that a 0.11.3 pause stopped, pass `--attempt 4`.

## 0.11.2

Upgrading from 0.11.1.

Version 0.11.2 finishes a pause before it reports a verdict, so `run.py stop` after `verify-failed` no longer leaves a task that `launch` refuses. `launch` stops an idle session whose work is filed instead of asking for `run.py stop`. No migration: a task already stuck this way is fixed by the next `record`.

## 0.11.1

Upgrading from 0.11.0.

Version 0.11.1 catches up on the host by default in `pr` mode. When a request is behind its target, `run.py close` now asks the host to rebase it (GitHub `gh pr update-branch <n> --rebase`, GitLab `PUT merge_requests/<iid>/rebase`) and pushes nothing, in place of a rebase in the task worktree and a push. Set `[merge] catch_up = "local"` to keep the 0.11.0 behaviour. A failed push now says why: `push-failed` with git's line when the remote branch did not move (a pre-push hook, credentials, or a protected branch), and `push-refused` only when someone else moved it. No migration.

## 0.11.0

Upgrading from 0.10.3.

Version 0.11.0 wakes the Manager. `run.py notify-to "<name>"` stores the Manager's session name in the run directory, and each brief rendered after that tells its session to send that name one line with SendMessage after its `result add`: `task <id> attempt <n> <kind> filed <STATUS>; run record`. `run.py wait` polls Taskgraph, `claude agents` and, in `pr` mode, the code host, and exits at the first change or after 30 minutes; it writes nothing. The Manager runs it in the background after each drain that leaves work in flight. Without an address, briefs have no notify step, and only `wait` wakes the Manager. The REPORT text now says "Then run this one command, once." in place of "Then your last action is this one command, run once." A brief rendered before the upgrade still works, with no notify step. No migration.

## 0.10.3

Upgrading from 0.10.2.

Version 0.10.3 changes how a session reports. The brief now says to write the report to `.agentic-team/report-<session>.md` in the worktree with the Write tool, and `result add` reads it with `--body-file`, so no report text reaches a shell command. `run.py` adds `/.agentic-team/` to `info/exclude`, and that line also ignores the run directory in the main checkout. A verifier with no result is recovered from its report file, its transcript or `claude logs`; if that fails, `record` prints `no-verdict`, which replaces `verifier-died`, and files no `DIED` row. A row with state `failed` now counts as ended, so a worker in that state goes from `unknown` to `died`. A brief that was rendered before the upgrade still works: its heredoc command is valid. No migration.

## 0.10.2

Upgrading from 0.10.1.

Version 0.10.2 keeps a merged worktree that may hold data. `run.py` removes a folder only when every ignored path in it is on the disposable list (the defaults plus the new `[merge] disposable` key), and when no Docker container, running or stopped, uses a path in it. A folder that 0.10.1 would have removed may now stay with a `kept` line, for example for an ignored `.env` file or a project cache such as `.sdk-wheels/`. Add the project's regenerable paths to `[merge] disposable`; the next `run.py record` removes those folders. With `docker` on `PATH` and Docker stopped, every merged folder stays until Docker answers. No migration.

## 0.10.1

Upgrading from 0.10.0.

Version 0.10.1 records the `model` of each session in the `sessions` meta and puts the waiting item, the model, and the last output of `claude logs` in the `BLOCKED` row of a stuck session. The `stuck` hint names a pinned model id only for a session that ran on one. `config.py check` prints one line when `.agentic-team.toml` is missing. No migration: an older session entry has no `model`, and the row shows `Model: unknown`.

## 0.10.0

Upgrading from 0.9.0.

Version 0.10.0 adds the project verify skill and, in `pr` mode, the verdict comment on the request. No migration. A project without `.claude/skills/verify/SKILL.md` runs as before; the verifier brief says the skill is missing, and `/agentic-team:setup` creates it. A task closed under 0.9.0 gets its comment at its next `run.py close`, if any; `record` posts nothing.

## 0.9.0

Upgrading from 0.8.x.

Version 0.9.0 adds the `verify_kind` meta. A task without it is `code` and
behaves as before, apart from the base and head lines and the levels list in the
verifier brief. No migration.

## 0.8.0

Upgrading from 0.7.0.

Version 0.8.0 removes a merged task's worktrees by default, including the old
`task-<id>-<n>` folders and the folders of tasks that 0.4.0 to 0.6.0 closed:
the next `run.py record` sweeps every done task with `merged_at`. Set
`[merge] remove_worktrees = false` before you upgrade to keep them.

## 0.7.0

Upgrading from 0.6.0.

Version 0.7.0 gives a task one worktree for its whole life; 0.6.0 gave each
attempt its own (`.claude/worktrees/task-<id>-<attempt>`). Finish or abandon
the tasks in flight before you upgrade. `run.py` does not migrate a task that
0.6.0 started: a task in progress with an attempt and no `sessions` meta is
`legacy`. `record` prints one `legacy` line for it and skips it, and `launch`,
`verify`, `close`, `stop`, and `abandon` refuse it with the same text. Once its
session has ended and its result is filed, declare it a 0.7.0 task with
`tg edit <id> --meta sessions='[]'`, then run `run.py record`. The next
`launch` creates `.claude/worktrees/task-<id>` at the last reported `Head`. The
old folders stay until the task is merged; then `cleanup` removes them like any
other safe folder.
