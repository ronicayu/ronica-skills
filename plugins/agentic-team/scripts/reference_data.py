"""Reference tables that no constant in the code holds: what each meta key and result kind means.

scripts/gen_reference.py prints them into docs/reference.md. Which meta keys stay in the local cache of the Taskgraph
GitHub backend comes from config.RUNTIME_META, not from here.
"""

# (keys, set by, meaning)
META_KEYS: list[tuple[tuple[str, ...], str, str]] = [
    (("scope", "verify", "tier", "risk"), "plan",
     ("Brief inputs. `tier` is a tier name or a `models.overrides` key. `risk=high` sends verification to a separate "
      "session.")),
    (("role",), "plan",
     ("The task's role: a name from `run.py roles`. Empty or absent means the config's `roles.default`, else no role. "
      "See [Roles](roles-and-briefs.md#roles).")),
    (("estimate",), "plan",
     "Taskgraph's own estimate in hours. The worker's timebox is twice it."),
    (("workflow", "workflow_record"), "`add --workflow`",
     ("On a workflow instance task: the workflow's name, and its record as JSON (`workflow`, `version`, `optional`, `rule` (the first matching rule), "
      "`pick`: the two answers, their seeds, the workflow resolved, the resolution rule and whether it was unsure; `rules`: each "
      "hard rule that matched, with what it did; `picked_at`, `overrides`, "
      "`adjustments` (one row for each `stage escalate` and `stage downgrade`: `kind`, `stage`, `type`, `before`, `why`, `row`, `rule`, `at`), "
      "`ended` (set by `stage cancel`: `kind`, `why`, `at`, and the tasks it abandoned, skipped and closed), `expanded` (set by "
      "`stage expand`: the workflow, the report row, the stage ids), `scope`, `verify`, and `stages`: each stage's `id`, `type`, `task`, "
      "`approval`, `approval_id`, `split`, `after`, `parts`, and `escalated`, `before`, `skipped`, `replaced`, `replaced_tasks` where they apply). "
      "The instance is never launched; its status is the derived status of its stages. A cancelled instance also has `abandoned=cancelled` and `abandoned_why`.")),
    (("stage", "stage_part", "stage_origin", "split_declined", "workflow_notes"), "`add --workflow`, `stage split`, `stage approve`, `stage escalate`",
     ("On a stage task: its stage id; the part number of a split stage; how it came to exist (`expand`, `with`, `split` or `escalate`); "
      "the one line that declined a split; and the workflow's notes for the stage, which the brief pastes under CONTEXT.")),
    (("stage_state", "skipped_why", "replaced_from", "replaced_by"), "`stage downgrade`, `stage cancel`, `stage replace`",
     ("On a stage task: `stage_state=skipped` (with `skipped_why`) marks a stage that was left out after it was created: the task is done "
      "with no attempt, and run.py never derives a merge for it. `replaced_from` is on the task that `stage replace` made, and "
      "`replaced_by` on the abandoned task it took the place of, which leaves the instance.")),
    (("approval_id",), "`add --workflow`", "On a stage task that has an approval: the id of its decision."),
    (("approval_for", "approval_stage", "approval_level", "approval_state", "on_timeout", "due_at", "decide_by", "default"),
     "`add --workflow`, the merge record, `record`, `stage approve`",
     ("On an approval decision: the stage task and stage id it answers, its level (`manager` or `human`), its state (`pending` "
      "until the stage merges, `open`, `done`; `skipped` or `cancelled` for a decision that ended with its stage), what happens at the due time (`on_timeout`: `approve` or `hold`), the due time "
      "(`due_at`, UTC; `decide_by` is its date for Taskgraph) and the `default` that `record` applies. A `human` decision has "
      "`decider=manager` until the stage merges, then `operator`.")),
    (("verify_mode",), "plan",
     ("`session` (the default) or `ci:<name>`. `ci:<name>`: the CI run on the pushed head is the verifier. GitHub: "
      "`<name>` is a workflow file name or workflow name. GitLab: `pipeline` for the whole pipeline, or a job name.")),
    (("verify_kind",), "plan",
     ("`code` (default), `schema` or `design-doc`. Selects the verifier's method text and the pass level: `code` "
      "closes on `artifact-verified` or `test-verified`; the other two only on `artifact-verified`. Unset means the "
      "config's `verify.kind`.")),
    (("started_at", "session", "model", "attempt"), "`launch`, `adopt`",
     ("The current attempt, and when it started (UTC, ISO 8601; a task from 0.27.2 or older has a local string). "
      "`adopt` writes `session=adopted` and no `model`.")),
    (("sessions",), "`launch`, `verify`, `adopt`",
     ("A JSON list with one entry per session `run.py` started: `{\"id\", \"kind\" (task or verify), \"attempt\", \"name\", "
      "\"worktree\"}` (a verifier in the task worktree has `\"worktree\": \"task-<id>\"` and its own name "
      "`verify-<id>-<n>`; its identity is that name, not the folder), `\"profile\"` for a session that runs under a "
      "profile other than the Manager's own, and `\"sessionId\"` (the full id that `--resume` needs) when the `claude "
      "agents` row had one. Every entry that `run.py` starts also has `\"plugin\"`, the agentic-team version of the "
      "`run.py` that started it (from `plugin.json`), and a worker's entry from `launch` has `\"cause\"`: why the "
      "attempt started, one of `first`, `review-fix` (a verifier's `verify-failed` verdict on a PASS), `ci-fix` (the "
      "same from a CI run), `rebase` (a `round`), `retry-issues` (the worker reported `ISSUES` or `BLOCKED`), "
      "`retry-stopped`, `retry-died`. `launch` derives it from the rows of the attempt before it, and leaves it out, "
      "with a note in the `launched` line, when they do not say (a stuck session, an abandon for another reason); "
      "`launch --cause <cause>` sets it. `record` adds `\"usage\"` (`{\"out\", \"in\", \"cache_read\", \"cache_write\"}`: the "
      "tokens summed over the session's transcript without the messages of the sessions it resumed, and `\"partial\": "
      "true` when a session of its chain was lost) once the session is no longer live and its transcript is found; an "
      "entry whose transcript cannot be read is tried again by the next `record`. `id` is the short id that `claude "
      "--bg` printed, checked against `claude agents`. `launch` and `adopt` add `\"role\"`, `\"tier\"` and "
      "`\"verify_kind\"` (see [Roles](roles-and-briefs.md#roles)); an adopted attempt has an entry with these and no "
      "`\"id\"`. A revision's resume adds an entry with the new id, the same name, `\"resumed_from\"` (the old id) and "
      "`\"revision\"`. A task in progress with an attempt and no `sessions` key was started under 0.6.0, unless the "
      "GitHub backend keeps `sessions` local: then this machine's cache lost it (see [When the local cache is "
      "lost](github-backend.md#when-the-local-cache-is-lost)).")),
    (("base",), "first `launch`, `adopt`",
     "The commit the task branch forked from. Written once; a retry keeps it. The verified change is `base..Head`."),
    (("target",), "`launch --base <branch>`, `adopt --pr`",
     "The branch the change merges into when it is not `merge.base`."),
    (("verdict", "verdict_ref", "tokens"), "`close`",
     ("`artifact-verified`, `test-verified`, `check-only`, `verify-blocked`, or `verify-failed`, tied to the worker's "
      "`Head:` commit SHA (or to output checksums when the output is outside git). `verdict_ref` moves to the new "
      "head after an accepted rebase. `tokens` is `\"<out>/<in>\"`, from the transcripts of the attempt's worker "
      "sessions (a revision's resume counts with the session it resumed, each message once); the cache counts are "
      "printed on the `tokens` event line. When there are none, that line names the reason (no session id, folder not "
      "found, no matching transcript); a full session id is also looked up in the other project folders under "
      "`~/.claude/projects`.")),
    (("ci_refs",), "`verify`, `close`, `abandon`, `round --cancel`, merge",
     ("A JSON list `[{\"ref\", \"head\", \"attempt\"}]` of the scratch branches that `verify --ci-ref` pushed for CI runs. "
      "A passing `close`, `abandon`, `round --cancel` and a recorded merge delete the branches on the remote and the "
      "key; one that could not be deleted stays listed.")),
    (("pr",), "publish, `adopt`, `repoint`",
     "The request number (GitHub PR number, GitLab MR `iid`). On a repointed task, the request it follows."),
    (("pr_branch",), "publish, `adopt`, `repoint`",
     "The branch on the remote that the request's head is. Default `task-<id>`."),
    (("repointed_at", "repointed_from", "repointed_branch", "repointed_pushed"), "`repoint`",
     ("`repointed_at` marks a task that follows another task's request: when it was last repointed. The other three "
      "keep the task's own request (number, branch, pushed head) from the first repoint; a key the task had no value "
      "for is not written. The next `launch` moves them back to `pr`, `pr_branch` and `pushed` and removes all four.")),
    (("mailbox",), "`answer`, `steer`, `record`",
     ("A JSON object `{\"<row id>\": {\"kind\", \"attempt\", \"via\" (socket, resume or pending), \"filed\", \"at\", \"tries\", "
      "...}}` for each `answer` and `steer` row that `run.py` filed, plus `{\"kind\": \"ask\", \"seen\": true}` for an ask "
      "that `record` printed. The delivery state of a message is meta, not a row, so a retry adds no row. `launch` "
      "drops the entries of earlier attempts; `cleanup` of a merged task and `abandon` remove the key.")),
    (("mailbox_ids",), "`answer`, `steer`",
     ("`{\"<attempt>\": [row ids]}`: the answer and steer rows that `run.py` filed, which nothing prunes. A later brief "
      "pastes only these from an earlier attempt, so a row that a worker filed `--by manager` is never carried as the "
      "Manager's. `abandon` keeps it; the cleanup of a merged task removes it.")),
    (("cleanup_kept",), "`cleanup`",
     ("A JSON object `{folder: reason}` for the worktree folders of a merged task that `run.py` kept, so `record` "
      "repeats a `kept` line only when its reason changes.")),
    (("pushed",), "publish, `adopt`, `record`",
     ("The request head SHA as `run.py` last pushed it or last saw it merged. The lease for every later push and the "
      "guard for every merge.")),
    (("host_rebase",), "`close`",
     ("The `pushed` head that `close` asked the host to rebase. It stays while the outcome is open (the host failed "
      "or is still busy), so that `record` reports a new head as `pr-rebased`, not as `pr-changed`, and the next "
      "`close` checks it. `close` removes it when the outcome is known.")),
    (("caught_up_from",), "`close`",
     ("The local branch's head when the host first rebased the request. The local branch and worktree stay there. "
      "`close` does not push it back over the host's head, and cleanup counts it as merged.")),
    (("merged_at", "merged_by", "merged_via"), "`close`, `merged`, `record`",
     ("Set when the task's branch is confirmed merged, in the same write as `phase=merged`, before `tg done`. "
      "`merged_by` is `manager`, `operator`, `no-change` or `repoint` (a repointed task whose followed request "
      "merged; `merged_via` then holds that request's number). In `pr` mode `record` sets them from the request "
      "state.")),
    (("phase",), "`launch`, `adopt`, `verify`, `record`, `close`, `stop`, `merged`, `abandon`",
     ("Where the task is: `running` (a worker runs), `stopped` (the attempt ended with no report: `STOPPED`, `DIED`, "
      "or the Manager's `BLOCKED`), `reported` (the worker filed its result), `verifying` (a verifier or a CI run "
      "checks it), `verdict_failed` (a verdict that did not close it), `awaiting_merge` (closed, in progress until "
      "its change is merged), `merged` (merged, or closed with nothing to merge; done), `abandoned`. `record` writes "
      "it for a task that has none, from `abandoned`, `merged_at`, the status, `verdict`, `verdict_ref` and the "
      "result rows, and keeps the first four in step with the result rows. A done task that is merged (or closed with "
      "nothing to merge) and has no phase gets none written: `run.py` derives `merged` when it reads it. A done task "
      "whose stored phase is one of the first four (an older `run.py` closed it after a newer `record` wrote the "
      "phase) is derived again from those fields, as if it had none. When the stored phase and those fields disagree "
      "on anything else, `record` prints `phase-mismatch` and leaves the task alone until you fix the meta. Every "
      "change goes through the table `TRANSITIONS` in `run.py`; an event with no row for the task's phase stops the "
      "command with an internal error, except in `record`, which prints `transition-error` for that task, goes on "
      "with the others, and exits 1.")),
    (("gates", "merge"), "`close`, `record`, `merged`, `abandon`",
     ("Taskgraph's completion gates (`tg gate`, Taskgraph 1.19.0). `run.py` owns the gate `merge` and sets it while "
      "the task waits for its merge: label `merge of <branch>` with no ref (local mode, or pr mode before the request "
      "opens), else `PR #<n>` or `MR !<n>` with the request URL as ref. `run.py` clears it, with `tg gate <id> merge "
      "--clear`, in the merge record before `tg done`, and in `abandon`. A task that is done in Taskgraph (closed by "
      "0.18.0) gets no gate. Other gates on the task are not `run.py`'s.")),
    (("abandoned",), "`abandon`",
     ("The reason code: `died`, `tool-error`, `stuck`, `failed`, `scope-wrong`, `superseded`, `operator` or `cancelled` (0.27.2 "
      "and older also wrote `unknown`). Only this marker lists a task as abandoned.")),
    (("abandoned_why",), "`abandon`",
     "The `--why` text of the abandon. `launch` removes it with `abandoned`."),
    (("round", "round_from", "round_verdict", "round_onto"), "`round`",
     ("A round in flight: its kind (`rebase`), the verified head it started from, that head's verdict, and the target "
      "commit of the kind. A passing `close`, `round --cancel`, and the merge of the request during the round remove "
      "them; `launch` after an `abandon` removes them too.")),
    (("rounds",), "`round`",
     "How many rounds the task has had; `[rounds] cap` limits them without `--attempt`. Never removed."),
    (("revision",), "`revise`",
     ("How many revisions the current attempt has had (see [Revisions](lifecycle.md#revisions-fix-in-place)). "
      "`launch` and `round` remove it.")),
    (("revisions",), "plan",
     ("The revisions one attempt of this task may have; overrides `[verify] revisions_per_attempt` (`0` turns them "
      "off for the task).")),
]

# (keys, why): the class of each key is config.RUNTIME_META's, or "on the issue" for a key it does not list
META_WHY: list[tuple[tuple[str, ...], str]] = [
    (("sessions",),
     ("The ids, profiles and `--resume` ids of this machine's `claude agents` rows; rewritten at each launch, verify "
      "and recorded row. Another machine cannot use them.")),
    (("session",),
     "The newest worker session's name: this machine's report file name and the `status` line."),
    (("cleanup_kept",),
     "Why this machine kept a worktree folder; it only stops `record` from repeating a `kept` line."),
    (("host_rebase",),
     "A host rebase that this machine's `close` asked for and has not seen end; most `close` runs set and remove it."),
    (("mailbox",),
     "The delivery state of each answer and steer (socket, resume, pending, tries); it changes at each delivery try."),
    (("mailbox_ids",),
     ("Which answer and steer rows this machine's `run.py` filed. Only this machine's `run.py` and its workers, which "
      "read the same cache, check it.")),
    (("tokens",),
     "Shown by `status` and the report; nothing acts on it."),
    (("model",),
     ("The current attempt's model, for `status` and for the verifier's model; read on this machine, where the cache "
      "already holds it.")),
    (("started_at",),
     "Shown by `status`; written at each launch."),
    (("attempt", "phase"),
     "Every command reads them; another machine or a person must see where the task is."),
    (("base", "target"),
     "The verified change is `base..Head`, and `target` is where it merges; written once."),
    (("verdict", "verdict_ref"),
     "`close`, `record` and the merge read them back."),
    (("pr", "pr_branch", "pushed", "caught_up_from"),
     ("The request, the lease for each push and the guard for each merge; `close` and `record` read the full SHAs "
      "back.")),
    (("repointed_at", "repointed_from", "repointed_branch", "repointed_pushed"),
     "Written once per repoint; the next `launch` reads them back."),
    (("merged_at", "merged_by", "merged_via"),
     "The merge record; written once."),
    (("round", "round_from", "round_verdict", "round_onto", "rounds"),
     "`close`, `record` and `round --cancel` read them back, and another machine must see that a round runs."),
    (("revision", "revisions"),
     ("`record`, `verify` and `close` read `revision` back, and another machine must see that a revision runs; "
      "`revisions` is a plan key, like `risk`.")),
    (("abandoned", "abandoned_why"),
     "The only marker of an abandoned task, and its reason."),
    (("ci_refs",),
     "The scratch branches on the remote that a passing `close` or `abandon` must delete, from any machine."),
    (("gates",),
     "Written by `tg gate`, not `--meta`; the issue shows the open merge gate."),
    (("workflow", "workflow_record", "stage", "stage_part", "stage_origin", "split_declined", "workflow_notes", "approval_id",
      "approval_for", "approval_stage", "approval_level", "approval_state", "on_timeout", "due_at", "decide_by", "default",
      "stage_state", "skipped_why", "replaced_from", "replaced_by"),
     "Another machine must see the workflow and where each stage and approval stands; none of them is local."),
]

# (kind, status, written by, meaning)
RESULT_KINDS: list[tuple[str, str, str, str]] = [
    ("`task`", "`PASS`, `ISSUES`, `BLOCKED`", "The worker, at the end of its work",
     ("The report: Task, Status, Branch, Head, Worktree, Ran, Evidence, Files, Issues, Asked, Deviations, Follow-ups, "
      "Checkpoint. `Asked:` lists the ask ids an `ISSUES` or `BLOCKED` report relied on, or says `none: <one-line "
      "reason>` (see [Messaging](messaging.md#messaging), Ask first). Each `Follow-ups:` line is `<label>: <path or "
      "question>: <why>`, with a label from `caller`, `doc`, `test`, `other`, `found`, `split` (`split: timebox: "
      "<what remains>`), `design` (`design: <question>: <why>`: a design question that an earlier stage should answer; on a "
      "workflow stage `record` prints an `escalation-hint`) and `flake` (`flake: <check>: <the failing run and the passing rerun>`: a check that failed "
      "once, not plainly because of the change (a timeout, a network error, a test order problem), and passed on one "
      "rerun with no change; the status stays `PASS`. A failing check that runs code the task changed is not a flake "
      "unless it also fails on the base. A verifier writes a flake as a `flake:` follow-up, not a `blocking:` "
      "finding); a `leftover ...` line keeps its own form. A verifier also uses `decision:` and `nonblocking:`. The "
      "Manager triages a `flake:` line like any follow-up: a task to fix the flaky check, or won't-fix with a reason.")),
    ("`task`", "`DIED`, `BLOCKED`", "The Manager (`--by manager`)",
     ("`DIED`: a session that ended with no result. `BLOCKED`: a session stopped while waiting on a permission "
      "prompt; the body has the session, worktree, the item waited for, the model, and the last output. A worker "
      "report that `record` recovered keeps the worker's own status.")),
    ("`task`", "`STOPPED`", "The Manager",
     ("A worker that `stop` stopped (a second row carries the WIP commit `Head:`), or a worker session `close` "
      "stopped. A `Reason:` line says why: `pause` (a `STOP` line was set), `recover` (no `STOP` line), `close`, or `escalated` "
      "(`stage escalate` stopped an attempt that had reported, after it committed the WIP: one row, with the `Head:`). "
      "Only `Reason: pause` and `Reason: escalated` keep the attempt from counting toward the cap; a row with no `Reason:` line counts.")),
    ("`task`", "`ABANDONED`", "The Manager",
     "A session `abandon` stopped: `Abandoned: <reason>` and `Why: <text>`."),
    ("`task`", "`PASS`", "The Manager",
     "The evidence for an adopted task (`Worktree: None`, `Ran: not stated (adopted)`)."),
    ("`verify`", "`PASS`, `ISSUES`, `BLOCKED`", "The verifier or the Manager",
     ("The verifier files the same report plus a `Verdict:` line. A report that `record` recovers is filed under the "
      "verifier's name. The Manager files its own verdict for a `risk=low` task, and `BLOCKED` for a verifier stopped "
      "while waiting on a permission prompt before it filed a verdict. A `BLOCKED` row has no `Verdict:` line, so it "
      "does not hide a verdict filed before it.")),
    ("`ask`", "`OPEN`", "The worker (`--by` its session name)",
     "A question for the Manager: `Question:`, `Options:`, `Default:`, `Blocking: yes|no`, `Why:`."),
    ("`answer`", "`ANSWERED`", "`run.py` (`--by manager` or `operator`)",
     "`Re: #<ask id>`, `Answer:`, `Source: manager|operator|default|decision #<id>`."),
    ("`steer`", "`SENT`", "`run.py` (`--by manager` or `operator`)",
     ("`Steer:`, `Kind: info|redirect|wrap-up`, or `Kind: finding` with `Revision: <r> (verify #<row>)` and one "
      "`F<n>: blocking: ...` line (or `F<n>: blocking[<category>]: ...`) per blocking line of the verifier's row that "
      "`revise` relays.")),
    ("`check`", "`OK`, `MISSING`, `NOT-CHECKED`", "`run.py depcheck` (`--by manager`)",
     ("The dependency check before a launch: `Check: dependency`, `Verdict:`, and the subagent's answer. Its "
      "`attempt` is the attempt that the check is for.")),
    ("`triage`", "`TASK`, `ISSUE`, `DISMISSED`", "`run.py triage` (`--by manager`)",
     ("Where one `Follow-ups:` line of a result went: `Row: <result id>#<line>`, `Line:`, `To: task <id>|issue "
      "<n>|dismissed`, `Why:`.")),
    ("`revise`", "`OPEN`", "`run.py revise` (`--by manager`)",
     ("The start of a revision: `Revision:`, `From: verify #<row>`, `Head:` (the head the verifier judged), "
      "`Verifier:`, `Worker:`. The rows of the attempt after it are the revision's: a revision adds a second task row "
      "and a second verify row to the attempt.")),
    ("`ack`", "`SEEN`", "The worker",
     ("`Re: #<message id>`, `Action:` (one line); the ack of a `finding` steer adds one `F<n>: <action>` line per "
      "finding. The only proof that a message was delivered.")),
    ("`verify`", "`PASS`, `ISSUES`, `BLOCKED`", "`ci`",
     ("The CI run on the pushed head, in `verify_mode = ci:<name>`: `Verdict:`, `Workflow:`, `Run:`, `Head:`, "
      "`Branch:`, `Conclusion:`.")),
]

# What each run.py command does; the options come from the parser
COMMAND_DOCS: dict[str, str] = {
    "launch": ("Renders the brief, creates the task worktree at the base (or continues in it on a retry), starts the worker, "
     "and records `session`, `model`, `attempt`, `sessions`, `started_at`, and, on the first launch, `base`. Options: "
     "`--keyword`, `--tier`, `--model`, `--effort`, `--profile`, `--attempt`, `--base <sha|branch>`, `--cause "
     "<cause>`, `--dry-run`. It records the `plugin` version and the `cause` of the attempt in its `sessions` entry "
     "(see `sessions` in [Task metadata](reference.md#task-metadata)). If an open task already has a live session, it "
     "records the start instead (`repaired`). It stops a session of the task that is idle with its work filed, or a "
     "worker that waits on a prompt after its result (`stopped-idle`), instead of refusing. It refuses a task in a "
     "round (`round <id> --cancel` ends it)."),
    "adopt": ("Brings a branch started outside `run.py` under the Manager. Options: `--branch`, `--head`, `--pr`, `--base`. It "
     "launches nothing."),
    "verify": ("Starts a verifier for a `PASS` result, pinned to its `Head`, in the task worktree (read only) or a folder of "
     "its own (`[verify] seat`; `seat-fallback` says why it took its own folder). In a revision it resumes the "
     "attempt's kept verifier with a revision brief, or starts a new one in the same seat when that verifier is gone. "
     "Options: `--ref`, `--result`, `--model`, `--effort`, `--profile`, `--again`, `--ci-ref` (push the worker's "
     "`Head` to the scratch branch `ci-<id>-<attempt>` for the verifier to judge its CI runs; pr mode), `--dry-run`. "
     "In CI mode (`verify_mode = ci:<name>`) it pushes the branch and finds or starts the CI run instead of a "
     "session."),
    "revise": ("After a verifier session's `verify-failed` verdict with `blocking:` lines, files a `revise` row, sets "
     "`revision`, moves the phase to `running` with no verdict, files one `finding` steer that lists the blocking "
     "lines as `F1` to `Fn` and wakes the attempt's own worker session: a revision (see "
     "[Revisions](lifecycle.md#revisions-fix-in-place)). Refused when no revision is possible (the message names the "
     "old path, `launch` or `abandon`), under a STOP order (exit 3), while the verifier still works, and on a full "
     "session cap. Prints `revised`, and `verifier-leftovers` when it stashed the verifier's changes."),
    "record": ("Reads the queue and prints one line per event: results that arrived, dead, stuck, and stopped sessions, "
     "verdicts, merges, open decisions, free slots, and ready tasks. In `pr` mode it also reads the request state, "
     "the CI runs, and merges."),
    "close": ("Records the verdict and tokens, stops the task's live worker and verifier sessions, and merges, pushes and "
     "opens a request, or lists the branch as ready to merge. A passing verdict sets `phase=awaiting_merge`, and the "
     "task stays in progress until its change is merged; a verdict that does not pass sets `phase=verdict_failed`. "
     "Accepts a rebased branch with the same change. Options: `--verdict`, `--ref`, `--ran`, `--override-verifier`. "
     "Rerun it on a task that waits for its merge: it resumes at the merge or the push. In `pr` mode it posts the "
     "verdict as a comment on the request (`commented`, or `comment-failed`), and it catches up a request that is "
     "behind its target (`[merge] catch_up`). A task whose branch holds no commit beyond its base is recorded as "
     "merged (`merged_by=no-change`) without a merge, a push or a request. In a round, a PASS with the same change as "
     "the verified head and no verifier verdict keeps the round's old verdict (a `Carried:` row)."),
    "round": ("Starts a new attempt of a task that waits for its merge, on the same branch and request: kind `rebase`, for a "
     "change that conflicts with its target. Options: `--keyword`, `--tier`, `--model`, `--effort`, `--profile`, "
     "`--attempt <n>` (also lifts `[rounds] cap`), `--dry-run`. `round <id> --cancel` ends a round: the task waits "
     "again at its verified head. Prints `round-started` or `round-cancelled`. See \"Round\" under [Merging through "
     "pull or merge requests](merge.md#merging-through-pull-or-merge-requests)."),
    "merged": ("Records that the operator merged a task branch (`--by operator`, the default), marks the task done, then "
     "removes its sessions and worktrees."),
    "repoint": ("`pr` mode: a task that waits for its merge follows request `<n>`, which carries its change (another task's "
     "request). Writes `pr`, `pr_branch` and the `repointed_*` keys, unsets `pushed`, sets the merge gate to `<n>`, "
     "and closes the task's own request with a comment that names `<n>` (`--keep-old` leaves it open). The phase "
     "stays `awaiting_merge`. `record` then only reports `<n>`, and marks the task merged (`merged_by=repoint`, "
     "`merged_via=<n>`) once `<n>` is merged; a `target-check` line says, for information, whether the task's commit "
     "is in the target. See \"Repoint\" under [Merging through pull or merge "
     "requests](merge.md#merging-through-pull-or-merge-requests)."),
    "stop": ("Stops a worker and files a `STOPPED` result. The row says `Reason: pause` when the standing orders' first line "
     "is `STOP`: a pause, which does not use an attempt. Else it says `Reason: recover`: a stop that recovers a quiet "
     "or broken session, which counts as an attempt."),
    "abandon": ("Marks a task abandoned after attempt 3 failed, and stops the task's live worker and verifier sessions. "
     "`<reason>` is a code: `died`, `tool-error`, `stuck`, `failed` (the attempts failed on their merits), "
     "`scope-wrong` (the brief, SCOPE or a dependency was wrong), `superseded` (another task or request replaces it), "
     "or `operator` (the operator dropped it); `stage cancel` abandons with `cancelled`, which no command line takes. `--why` is required: one line of free text, stored in the meta "
     "`abandoned_why`, the `ABANDONED` row (`Abandoned:`, `Why:`) and the `abandoned` line. `unknown` is gone; a "
     "missing `--why` is refused. It also drops a task that waits for its merge: its branch stays unmerged, and in "
     "`pr` mode its request stays open on the host for the operator to close."),
    "add": ("Creates a task and settles its dependencies in the same call. It passes `--notes`, `--meta`, `--type`, "
     "`--parent`, `--start`, `--due`, `--promised` and `--priority` to `tg add`, and needs exactly one way of "
     "settling dependencies: `--depends <ids>` and/or `--blocks <ids>`, or `--independent \"<reason>\"` (recorded as "
     "meta `independent`). Without one it refuses (exit 2). It lists the open and in-progress tasks that may be "
     "related, at most 10, strongest first, as `candidate` lines: `SCOPE overlap` (the write paths of `--meta scope=` "
     "against each task's; a directory covers the paths under it; write the paths a task must not change after `;` or "
     "`；`, or after `不改`, `不要改`, `do not`, `never` or `not:`, and they are not compared; a shared file or a shared "
     "directory of four or more segments is strong, a shallower shared directory is marked `shared directory only` "
     "and `weak` when it is the only reason), `same #<n> reference` (`#<n>` or `gh issue view <n>` in both notes; an "
     "external, decision or milestone shows only for this reason, with its type), and `title words` (two shared words "
     "of four letters or more, or three shared Chinese character pairs; the weakest). Order: strong SCOPE overlap, "
     "same reference, shallow SCOPE overlap, title. A candidate reachable through the given `--depends`/`--blocks` at "
     "any depth reads `linked (via #<id>)`. It prints them when it refuses and when it adds; with "
     "`--depends`/`--blocks` each reads `linked` or `not linked`. An `added` line gives the new id and its links. A "
     "`--type decision` task needs `--blocks` and prints no candidates. With `--workflow <name>` (needs `[workflow_policy] "
     "enabled = true`) it creates a workflow instance in one locked run: the gate runs once for the whole piece of work; "
     "the instance task (meta `workflow`, `workflow_record`; `--blocks` ids wait for it) is the parent of one task for "
     "each required stage and each `--with <stage>`, created with real `--depends` (a root stage takes the external "
     "`--depends`; a later stage depends on each upstream stage and on that stage's approval decision). An optional stage "
     "that is not named in `--with` is left out, as is one in `--skip`; the stages after it depend on its upstream "
     "stages instead. `--meta scope=` and `verify=` are the instance's: the stages that write code use them, a design stage "
     "gets a document path under `[workflow_policy] design_dir`. The notes need a why sentence and `- [ ]` acceptance "
     "lines. A stage whose approval is `manager` or `human` also gets a decision under the instance, due once the stage "
     "merges (see `stage`). One `workflow-added` line lists the stages, the stages left out and the approvals. "
     "`--with` and `--skip` name optional stages only. `--pick \"<a>,<b>\" --seed <n>` replaces `--workflow`: the two typed "
     "answers (a workflow name or `unsure`; the Manager's, then the subagent's from the prompt of seed n+1) resolve to one "
     "workflow: the same name wins; two names take the one with fewer required stages; a name beside `unsure` takes the name; "
     "two `unsure` take `figure-it-out`; `[workflow_policy] when_unsure` changes the unsure rows. The answers, seeds and rule "
     "go into the record, with a `workflow-picked` line. A matching `[[workflow_rule]]` that has `require_stage` forces that "
     "stage on (`--with`), or moves the work to the lightest workflow that has it, and refuses `--skip` of it; each match is a "
     "`workflow-rule` line and a row of the record. An unsure pick or a rule change queues a `workflow-pick` notice when "
     "`notifications.events` lists it, and shows in `status` and the daily digest. See [Workflows](roles-and-briefs.md#workflows)."),
    "stage": ("`approve`: answers the approval decision of a stage of a workflow instance. It refuses while the stage is not "
     "merged. A `manager` approval checks workflow facts only: every `decision:` follow-up of the stage is triaged "
     "(`triage`), and each splittable stage after it is split (`split`) or declined with `--decline-split \"<one line>\"`. "
     "A `human` approval needs `--by operator`, after the owner has answered. `--default` applies the default (approve) of an "
     "approval that is past its due time; it refuses an approval that holds (`on_timeout = \"hold\"`). `record` applies the same "
     "default itself at the due time (`approval-due`), so `--default` is for a Manager that runs it by hand; it refuses before the due time and changes nothing. A split stage has one approval for all its parts: it opens, and can be answered, only when every part has merged, and the triage check reads every part. `--by operator` on a `manager` approval skips the triage and split checks and prints a `warn` line. `split`: adds a "
     "part to a stage whose workflow sets `split: true`, before the stage has an attempt. The first call re-titles the stage's "
     "own task as part 1; each later call creates a part with the same upstream dependencies, and every later stage then "
     "depends on all parts. `--meta scope=` is required. A part whose files overlap a sibling's must name it with "
     "`--depends`. `recheck`: matches the `[[workflow_rule]]` tables again against the SCOPE paths of the stages and the `area` "
     "(a part added by `split` does it too); a rule that is new to the record gets a `workflow-rule` line, and one whose stage "
     "is missing gets the way out. `rechoose <workflow>` (`--by operator`, `--note`, `--with`, `--skip`): the owner's override; "
     "it replaces the stages with those of another workflow, with the rules applied again, only while no stage has started. "
     "It is recorded under `overrides` and is not an adjustment. The changes in flight (see [Workflows](roles-and-briefs.md#changes-in-flight)): "
     "`escalate <type> --before <stage> --why \"...\" [--from-row <result id>[#<line>]] [--rule <name>]` puts a new stage (normally `spec`) "
     "and its approval in front of a stage that is not done: they join the dependencies of every part of it. It is refused past "
     "`[workflow_policy] max_adjustments` (escalations plus downgrades per instance, default 2), for a second escalation of one "
     "type, and when a part of the target has a busy session, a verifier that has filed no row, a merge or a request waiting for "
     "its merge, or an abandon. An attempt that has reported is stopped: its idle sessions stop (a revision can no longer follow), "
     "the WIP is committed, and one `STOPPED` row with the `Head:` and `Reason: escalated` is filed, so `record` reads it before "
     "the verifier and verdict rows and hints `launch`, which waits for the new stage and does not count toward the 3-attempt cap "
     "(the row decides; `launch --cause escalated` only records the cause). `downgrade <stage> --why \"...\"` leaves out an optional stage "
     "(one made by `--with`) that has no attempt and that no rule requires and no escalation added: the stage's upstream tasks and "
     "approvals move to the stages after it, its approval closes (`skipped`), and the stage is done with `stage_state=skipped`. It "
     "counts as an adjustment. `replace <stage>` (only after `stage-orphaned`; at most `[workflow_policy] max_replacements` per "
     "stage, default 1) makes a new task with the same dependencies and approval decision, moves the tasks that waited for the abandoned "
     "one to it and takes the abandoned one out of the instance. `cancel --why \"...\"` (only after `stage-orphaned`) skips every stage "
     "that has not started, abandons every stage that has (its sessions stop), including those in parallel branches, closes every "
     "approval and ends the instance; a task that waits for the instance never starts, and the `workflow-cancelled` line lists it. "
     "`expand (--from-row <result id> | --workflow <name>) [--meta scope=... verify=...]` is for a `figure-it-out` instance once its "
     "investigate stage has merged: it reads the `workflow-plan` block of the report (`workflow: <name>` or `stages: [{id: spec}, "
     "{id: impl, after: [spec]}]`), applies the hard rules that were deferred to it, and creates the stages; every first stage waits "
     "for the investigate stage and its approval. An ad-hoc plan is recorded as workflow `adhoc`. See [Workflows](roles-and-briefs.md#workflows)."),
    "status": ("Prints the status report as Markdown tables. Options: `--since`, `--limit`, `--mark`. A task that waits for its "
     "merge is listed under \"Closed, awaiting merge\" (`awaiting_merge` in `--json`), not under \"In flight\"; it is "
     "listed as done once merged. It also counts the `Follow-ups:` lines of the worker reports filed in the period by "
     "label, with `unlabelled` for a line without a known label (verifier reports, the Manager's `DIED`, `STOPPED`, "
     "`ABANDONED` and `BLOCKED` rows, and `leftover ...` lines are not counted), and gives the mean attempts of the "
     "tasks done in the period. `--json` has them as `follow_ups` and `attempts` (`{\"tasks\", \"mean\"}`). When an "
     "in-flight session runs under another Claude profile, the In flight table gains a `Profile` column (`Profile` in "
     "`--json`). When a session's token usage is known, the Done and In flight tables gain an `Est. cost` column (see "
     "[Cost in status](operations.md#cost-in-status))."),
    "roles": ("Lists every task role, one line each: the name, its source (`plugin`, `project`, `project, overrides plugin`, "
     "or `project, extends plugin:<name>`), what it fits, its tier, verify kind and skills. `--json` prints one "
     "object per role. Read only. A broken role file is listed with its error, and the command exits 1, so you see it "
     "before a `launch` fails. See [Roles](roles-and-briefs.md#roles)."),
    "workflows": ("Lists every workflow, one line each: the name, its source (`plugin`, `project`, `project, overrides plugin`, "
     "or `project, extends plugin:<name>`), its description and its stages, in file order, as `prd → ux? → spec → impl* → "
     "test` (`?` marks an optional stage, `*` a stage that may be split). `--json` prints one object per workflow, with each "
     "stage's resolved role, verify kind, approval, estimate and `after`. Read only. A broken file is listed with its "
     "problems, each as `<file>:<line>: <problem>`, and the command exits 1; a problem of `stages.toml` is listed the same "
     "way. `--check` prints only the problems, or one `workflows-checked` line; it is the same check that `config.py check` "
     "runs when `[workflow_policy] enabled` is true or the project has workflow files. `--pick-prompt` prints the prompt that "
     "asks which workflow fits a piece of work (`--title`, `--notes-file`, `--scope`): the task text and the workflows as "
     "`A. <name>: <description>`, with `unsure` among them, in an order that `--seed` fixes; the same seed gives the same "
     "order. `--resolve \"<a>,<b>\"` prints which workflow two typed answers resolve to, and records nothing. "
     "See [Workflows](roles-and-briefs.md#workflows)."),
    "check-report": ("Checks a report file before a session files it: a `Status:` line with `PASS`, `ISSUES` or `BLOCKED`, a "
     "`Checkpoint:` line, and a label on each `Follow-ups:` line. A leading `- ` or `* ` is ignored; `None` and "
     "`leftover ...` lines pass. With `--acceptance <n>`, a `PASS` report also needs at least `<n>` non-empty lines "
     "under `Evidence:` (the first may sit on the `Evidence:` line; the lines run to the next field; a `None` line "
     "does not count), else the problem is ``PASS needs one `Evidence:` line per ACCEPTANCE line: found <k>, "
     "ACCEPTANCE has <n>``; `ISSUES` and `BLOCKED` reports are not counted, and without the option nothing changes. "
     "Without `--verifier`, an `ISSUES` or `BLOCKED` report needs an `Asked:` line: ask ids (`Asked: #12, #15`) or "
     "`Asked: none: <one-line reason>`, else the problem is ``<STATUS> needs an `Asked:` line: ...``. Prints `ok`, or "
     "one `run.py: <problem>` line per problem on stderr and exits 2. It reads only the file, so it needs no config, "
     "no Taskgraph and no repository; `--json` does not change its output. The brief's REPORT section names it with "
     "the session's report file. A worker's brief adds `--mailbox <context file>`: the command then also reads "
     "Taskgraph through that file and names a steer of the worker's attempt that has no ack (if Taskgraph cannot be "
     "read, it behaves as without the option) and `--acceptance <n>` with the number of ACCEPTANCE items of the task. "
     "The brief adds more for a worker: `--base <sha>` (the task's `base` meta, else the attempt's start) with "
     "`--target <ref>` (the fetched remote target branch in `pr` mode, else the branch of the main checkout), and one "
     "`--require-ran <prefix>` for each prefix that `[report] require_ran` lists for the task's verify kind. A rebase "
     "round gets none of these. With `--base`, a `PASS` report must name under `Files:` every file that `git diff "
     "--name-only <start>...HEAD` lists in the worker's worktree, where `<start>` is the newer of `--base` and the "
     "merge base of HEAD with `--target`: the task's own commits only, never what a rebase onto the target brought in "
     "(a stacked base that is still unmerged is newer than the merge base, so it stays the start; after a restack the "
     "merge base is); a deleted file counts as its path and a renamed file as its new path; when more than 20 files "
     "changed, a directory entry (`src/`, `src/**`) names the files under it; `ISSUES` and `BLOCKED` reports are not "
     "checked, and when git cannot say (an unknown base) nothing is checked. With `--require-ran`, a `PASS` report "
     "needs a `Ran:` line that starts with each prefix (a list marker and backticks in front are ignored), else the "
     "problem names the missing ones. A verifier's check command has neither: a verifier's report has no `Evidence:` "
     "line. With `--verifier`, a report that has more than one `Issues:` field gets the warning \"write a single "
     "`Issues:` field, one finding per line\" (exit code unchanged); every `Issues:` field is read all the same, and a "
     "line may be `blocking:` or `blocking[<category>]:` with a category from `stale-ref`, `claim`, `test`, `scope`, "
     "`shots`, `behaviour`. `record` does not check the evidence, `Files:` or `Ran:` lines of a report that it "
     "recovers from a transcript or a file; it does run the `[report] checks` of a worker `PASS` (see [Report "
     "checks](operations.md#report-checks)). With `--check`, the command also refuses a `PASS` while `git status "
     "--porcelain` lists changes before or after the checks."),
    "wait": ("Polls until something in flight changes and prints one `changed` line per change. It prints `timeout` after "
     "`--timeout` seconds (default 1800, at most 6600), or `nothing-in-flight` at once when no session runs and, in "
     "`pr` mode, no request is open and no CI run is read. It compares each poll with its own first read: the results "
     "of each task in progress, the state of each of their sessions, the open decisions, and in `pr` mode each open "
     "request of a closed task and the newest CI run that `record` reads. Options: `--tg-interval` (default 5 "
     "seconds, from `[messaging] tg_poll_seconds`: how often Taskgraph is read, so a new ask row wakes the Manager "
     "within seconds), `--interval` (default 30 seconds: how often `claude agents` is read), `--host-interval` "
     "(default 300 seconds; the host limits its rate). It writes nothing."),
    "notify-queue": ("Shows the operator notices that events queued, one `notify` line each (`[event] what happened`, then `next:` "
     "what the operator can do, and for a decision its default and deadline); `notify-queue: empty` when there are "
     "none. `--clear` shows them, then counts them as sent and empties the queue. `--add all-done|blocked \"<line>\" "
     "[--do \"<text>\"]` queues one the Manager decides. `--digest` prints the daily digest once a day when "
     "`notifications.digest = \"daily\"`, of what happened since the last digest that was marked as sent; `--digest --sent` "
     "marks the printed digest as sent. It sends nothing."),
    "notify-to": ("Stores the Manager's session name in the run directory. Each brief rendered after that tells its session to "
     "send one line with SendMessage after its `result add`, to `uds:<the Manager's inbox socket>` when "
     "`manager.addr` holds it, else to the name. `--clear` removes the name; with no argument it prints the name."),
    "answer": ("Answers a worker's `ask` row with `--file F`, `--default` (the ask's own `Default:` line) or `--decision <id>` "
     "(a done decision with `--meta ask=<ask id>`; its notes are the answer). Options: `--ask <row id>` (default: the "
     "newest open ask of the current attempt), `--supersede` (answer an ask again), `--by operator`. It refuses an "
     "ask of an ended attempt and a second answer without `--supersede`. It files the `answer` row, then delivers the "
     "doorbell."),
    "steer": ("Sends a running worker a steer: `--file F`, `--kind info|redirect|wrap-up` (`finding` is refused: only `revise` "
     "files it), `--by operator`, `--interrupt` (stop and resume a busy worker). It refuses a verifier, and a task "
     "with no live worker in its current attempt (the message says to write the text in the task notes)."),
    "depcheck": ("Records the verdict of the dependency check as a `check` row (status `OK`, `MISSING` or `NOT-CHECKED`) of the "
     "attempt that the check is for (the next one): `Check: dependency`, `Verdict:`, then the subagent's answer. The "
     "Manager runs it after the `agentic-team:dependency-check` subagent answers, so that a retro can count the "
     "checks against the launches. It changes no task state."),
    "triage": ("Records where a `Follow-ups:` line of one of the task's results went, as a `triage` row (status `TASK`, `ISSUE` "
     "or `DISMISSED`) with `Row:`, `Line:` (the line as written), `To:` and `Why:`. `<line>` counts the result's "
     "`Follow-ups:` lines from 1. `dismissed` needs `--why`; `task <id>` must be a task of this project. A retro "
     "joins the row to the follow-up line. A later row for the same line replaces the earlier one in a retro. It "
     "changes no task state."),
    "inbox": "Shows the task's messages: asks, answers, steers and acks, with the delivery state of each. Read only.",
}

EXIT_CODES: list[tuple[str, str]] = [
    ("0", "The command ran. An event may still say `died` or `kept`."),
    ("1", "A tool failed: `tg`, `git`, or `claude`."),
    ("2", "The command refused. The message names the fix."),
    ("3", "The standing orders say `STOP`. Only `launch` returns it."),
]

# Prose around the generated tables of docs/reference.md.
RUN_INTRO = """\
[scripts/run.py](../scripts/run.py) is the only writer of run state. The Manager runs it from the repository root
through the wrapper:
`"${CLAUDE_PLUGIN_ROOT}/scripts/run" [--root DIR] [--tg PATH] [--run-dir DIR] [--json] <command>`.
A `next:` hint that says `run.py <cmd>` means that wrapper with `<cmd>`.
Only `wait` and the host catch-up in `close` sleep or poll, and `wait` writes nothing: `claude --bg` returns at once,
and the Manager runs `record` when a session's message or the end of `wait` wakes it."""

RUN_OUTPUT = """\
Each event is one line: `<event> #<id> attempt <n>: <detail>`, followed by ` | next: <step>` when a step follows.
`--json` prints one array of `{"event", "task", "attempt", "session", "detail", "next"}` objects and nothing else on
stdout (`status --json` prints one object). Refusals go to stderr as `run.py: <message>`. `local` mode never runs `gh`
or `glab`.

`run.py` finds `tg.py` through `--tg`, then `$TASKGRAPH_TG`, then `scripts/tg-path.sh`. How it matches a session to
its task is in [Lifecycle](lifecycle.md#how-runpy-matches-a-session-to-its-task)."""

CONFIG_INTRO = """\
The project config is `.agentic-team.toml` in the repository root, in TOML. An optional, gitignored
`.agentic-team.local.toml` holds private or machine-specific values. It is merged into the tracked file table by
table; its keys win, and a list there replaces the tracked list. Omit a key to use its default. `""` or `[]` means the
item does not apply. The string `"TODO"` marks a value someone still has to fill in. Never put credentials or
secrets in either file.

Model values are either a model id (`"opus"`) or a table (`{ model = "sonnet", effort = "high" }`). A table may add
`profile`, a Claude profile for the sessions of that tier (see [Profiles](configuration.md#workers-on-more-than-one-claude-profile)). One optional table,
`[profiles]`, has names of your own and is not in the list below. So is the array of tables `[[workflow_rule]]`, the hard rules
of the workflows: each has a `name`, `match_paths` (globs over the write paths of a SCOPE) or `match_area` (the `area` meta),
and optionally `require_stage`, `approval` (a table of stage = level, for example `{ spec = "human" }`), `risk` (`low`,
`medium` or `high`, set on every stage task) and `on_timeout` (`approve` or `hold`; `hold` makes a `human` approval wait for the
owner with no deadline). See [Workflows](roles-and-briefs.md#workflows). How agents read the config, and what `check`
reports, is in [Configuration](configuration.md)."""

META_INTRO = """\
Task notes hold the purpose and acceptance criteria, following the Taskgraph skill. Metadata holds everything else."""

META_NOTES = """\
`launch` never unsets `pr`, `pr_branch`, `pushed`, or `target`: a task has one request across attempts. The one
exception is a repointed task: its `pr` is another task's request, so `launch` puts the task's own request back.

A task's priority (`P0` to `P3`, none by default) is a Taskgraph field that `tg add --priority` and `tg edit
--priority` set; it is not one of these keys. `record` lists the ready tasks in `tg ready` order, which is priority
first and then id, and the Manager launches them in that order."""

META_CLASS_INTRO = """\
On the Taskgraph GitHub backend every meta write is an issue edit, unless `.taskgraph.toml` lists the key under
`[projects."<name>".meta]`: a `local` key stays in this machine's Taskgraph cache and is never sent; a `deferred` key
waits in the cache and goes to the issue with the next write to that issue, or with `tg sync`. Every key that `run.py`
writes, and its class. The block to add to `.taskgraph.toml`, and what happens when the cache is lost, are in
[GitHub backend](github-backend.md)."""

META_CLASS_NOTES = """\
The plan keys (`scope`, `verify`, `verify_kind`, `verify_mode`, `tier`, `role`, `risk`, `estimate`) and a decision's
`decider` and `ask` are written by the Manager or you with `tg`, not by `run.py`; they stay on the issue."""

RESULTS_INTRO = """\
Worker reports live in the Taskgraph result log. A report file only carries the text there. Each result has a `kind`,
a `status`, an `attempt`, and an author (`--by`)."""

RESULTS_NOTES = """\
`verify` results by `manager` carry `Verdict:` and `Ran:`; an override adds `Overrides:` and `Reason:`. A round's
carried verdict (a clean round's `close`, `round --cancel`, the request merged during a round at the verified head)
is a `PASS` row by `manager` with `Verdict:`, `Carried: <verified head> (<why>)` and `Head:`. Every row filed when
`run.py` stops a session carries `Session: <id>` and `Worktree: <path>` lines; they are a record, not how sessions
are matched.

`tg result ls <id>` lists them. An attempt has arrived when a result exists for the task's current `attempt` and the
task has no `verdict`. Which kinds stay in the local cache of the GitHub backend is in
[GitHub backend](github-backend.md#result-kinds-on-the-taskgraph-github-backend)."""
