# Merging

How a verified change reaches the target branch: `local` mode, `pr` mode, the merge queue, catch-up and restack.

## Merging through pull or merge requests

Set `[merge] mode = "pr"` for a repository whose protected branch takes changes
only through pull requests (GitHub) or merge requests (GitLab). Setting it is
the operator's standing permission for `run.py` to push task branches to
`<remote>/task-<id>` and to open requests. Merging still needs a `MERGE:` line.
`local` mode never pushes and never runs `gh` or `glab`.

1. `run.py close` records the verdict, pushes the branch, and opens a request
   against the target branch (`merge.base`, else the host's
   default branch). The task keeps one request across attempts: a fix round
   pushes `worktree-task-<id>` to the same `task-<id>`. Every push after the
   first carries a lease on the last pushed head (`--force-with-lease`), recorded
   as `pushed`. A remote branch that is not ours stops the first push.
   A head that the fetched target already holds (merged by hand, outside `run.py`) stops the first publish too:
   nothing is pushed and no request opens; `run.py merged <id> --by operator` records it.
   With `[merge] draft = true` the request opens as a draft (GitHub
   `gh pr create --draft`, GitLab a `Draft: ` title), so it starts no full
   CI run until someone marks it ready. `record` then reports `pr-draft`
   until it is ready. The default is `false`. The task's `merge` gate says
   `merge of <branch>` until the request exists, then `PR #<n>` (GitHub) or
   `MR !<n>` (GitLab) with the request URL as its ref; a later publish or
   `record` updates the same gate when the request changes. On the Taskgraph
   GitHub backend the issue body then shows `Waiting for: [PR #<n>](../<url>)`, and
   GitHub lists the issue on the pull request. A GitLab URL is a plain link.
2. `run.py record` reads the request at each drain. It prints `pr-pending`,
   `pr-blocked` (with the required checks), `pr-draft`, `conflict`,
   `pr-behind`, `pr-rebased`, `pr-changed`, `pr-unpinned`, or `ready-to-merge`. A
   `conflict` line names `run.py round <id> rebase` first and the decision
   second (item 5). When the host reports the
   request clean, a `MERGE:` line exists, and `STOP` is absent, `record` merges
   it with `merge.method`. The merge is guarded by the pushed head
   (`--match-head-commit` on GitHub, `sha` on GitLab). A request whose head is
   not the pushed head is never merged by `run.py`, and an open request with no
   recorded `pushed` head is never merged either (`pr-unpinned`; `close <id>`
   pushes and records it). If the host fails for one task, `record` prints
   `host-error` for that task, goes on with the others, and exits 1 at the end.
3. A merge that anyone did on the host is recorded at the next drain from the
   request state (`merged_by=operator`), squash and rebase merges included.
   `run.py merged <id> --by operator` is for a merge the host cannot show. The
   task is done from that merge on; until then it stays in progress with
   `phase=awaiting_merge`. On the Taskgraph GitHub backend the host may close
   the task's issue at the merge first (a request or commit that says
   `Closes #<n>`; `run.py`'s own request text does not). Taskgraph then reads
   the task as done; `record` still records the merge, clears the gate and
   runs `tg done`, which keeps the task's `done_at` and removes the
   `tg:in-progress` label that the close left on the issue (Taskgraph 1.19.0).
   In the other order, `tg done` before the host closes the issue, the host's
   close is a no-op on GitHub. A request closed without a merge is reported at every
   drain (`pr-closed`), and the task stays in progress: reopen the request, or
   `run.py abandon <id> <mode>` (the request stays open on the host, and
   `record` no longer follows it). To redo the task, abandon it, then
   `run.py launch <id> --attempt <n+1>`.
4. When the host reports the request behind its target, `run.py close <id>`
   catches it up. With `[merge] catch_up = "host"` (the default) it asks the
   host to rebase the request: GitHub `gh pr update-branch <n> --rebase`,
   GitLab `PUT merge_requests/<iid>/rebase`. Then it reads the request until
   the head moves (at most 20 reads, 3 seconds apart), fetches the new head,
   and checks that the change is the same. The same change moves `verdict_ref`
   and `pushed` to the new head (`rebased ... on the host`). Nothing is pushed
   from this machine, so a local pre-push hook does not run, and the task
   worktree is not touched. A changed diff is a decision, and `pushed` stays at
   the old head, so `record` prints `pr-changed` and never merges the request.
   A conflict on the host is a `conflict` line: a round (item 5), or a decision. A host that cannot rebase (an old `gh`,
   no endpoint) or that refuses this user falls back to the local rebase
   (`catch-up-local`). A rebase that the host finishes late is found by the next
   `record` (`pr-rebased`) and checked by the next `close`. With
   `catch_up = "local"`, `close` rebases the branch in its idle worktree, checks
   that the change is the same, and pushes it again. A conflict is aborted and
   gets the same `conflict` line. A worktree that is missing, dirty, or in use is not
   touched. `run.py` never approves, force-resolves, or unprotects. A push is
   made only when our head moved. A push that fails while the remote branch is
   still at `pushed` did not reach the remote, for example because of a pre-push
   hook, credentials, or a protected branch: `push-failed`, with git's line. If
   someone else moved the remote branch while our head stayed, `record` prints
   `pr-changed`; `push-refused` appears when our head moved too, with where the
   remote branch is and git's line. One case is accepted: someone else (a
   merge-queue manager, a person) rebased the request branch and it carries
   the same change as `pushed` (#138). `record` and `close` fetch it and, in
   place of `pr-changed`, move `verdict_ref` and `pushed` to it (`rebased ...
   by someone else`). When `close` has a new head to push (a new attempt), it
   pushes over that rebase, with the lease set to the head it found: the
   rebase held only old content. A different change is refused as before.
   `[merge] after_rebase` (below) also runs on an accepted rebase.
5. **Round.** `run.py round <id> rebase` (#119) starts a new attempt of a task
   that waits for its merge and whose change conflicts with its target, on the
   same branch and the same request. It takes a task with
   `phase=awaiting_merge` whose request (in `pr` mode) is open at the pushed
   head, which is the verified head; it refuses a task that is repointed,
   already in a round, or at `[rounds] cap` without `--attempt <n>`, and a task
   with no conflict that `run.py` can see (the host says the request is
   `DIRTY`, or `git merge-tree --write-tree <target> <head>` finds a conflict;
   in `local` mode the second check only, which `record` also runs and prints
   as `conflict` instead of `unmerged`). The worktree must be clean and at the
   verified head; after a host rebase it may be at `caught_up_from`, and
   `round` first moves the branch to the host's head (the same change). The
   round is attempt `n+1` with the phase `running`: its brief's ROLE is the
   role named like the kind (`rebase`, shipped in `templates/roles/rebase.md`;
   a project replaces it or `extends` it, see [Roles](roles-and-briefs.md#roles)), with the
   round's values filled in, and its SETUP says that ROLE names the one command
   that moves the branch. The worker rebases onto the target commit that
   `round` names, resolves each conflict keeping both behaviours, runs VERIFY,
   commits, and does not push. A round does not count toward the attempt cap.
   It writes `round`, `round_from` (the verified head), `round_verdict`,
   `round_onto` (the target commit) and `rounds`, and unsets `verdict` and
   `verdict_ref`; `pr`, `pr_branch`, `pushed` and the `merge` gate stay. Then
   the usual flow: a PASS whose head carries the same change as `round_from`
   needs no verifier, and `close` carries `round_verdict` with a Manager
   `verify` row (`Carried: ...`), on that head only (`close --ref` with
   another commit needs a verdict); any other PASS goes to `run.py verify` under
   `[rounds] verify = "always"` (the default), whatever the risk and the kind,
   and the verifier's base is the target commit, so its diff holds only the
   task's change. A passing `close` pushes the new head to the same request
   with the lease, and the task waits for its merge again. A round that fails
   (ISSUES, BLOCKED, DIED, stuck, stopped, a failing verdict) gets the hint
   `run.py round <id> --cancel`, never `launch` or `abandon`. `--cancel`
   refuses a request that merged (`record` records it) before it writes
   anything, and a worktree on another branch; else it stops the round's
   sessions, aborts a rebase in progress, commits the WIP, keeps the
   round's head in `refs/agentic-team/round/<id>-<attempt>`, resets the branch
   to `round_from`, pushes `round_from` back to the request when a CI verify
   of the round had pushed the round's head, files the carried row, and puts
   the verdict back: the task waits again. While a round runs, `record` reads
   its request: `round-not-needed` when the conflict went away (cancel, or let
   the round finish), `pr-closed` and `pr-changed` as usual. When the request
   merges during a round, `record` stops the round's sessions and records the
   merge (`merged_by=operator`); it puts back the verdict of `round_from` only
   when the merged head is `round_from` or carries the same change, and else
   records the merge with no verdict. The round's worktree then holds an
   unmerged head, so cleanup keeps it with a `kept` line. `launch` and `adopt`
   refuse a task in a round; `abandon` drops it, and a later `launch` starts a
   plain fix round.
6. **Repoint.** When the changes of several tasks go into one request (the
   operator combined their requests to resolve a conflict), each task follows
   that request: `run.py repoint <id> --pr <n>`. It takes only a task with
   `phase=awaiting_merge` in `pr` mode, and refuses a request that is closed,
   that merges into another branch than the task's target, or that is the task's
   own. It writes `pr` and `pr_branch` of request `<n>` and `repointed_at`; the
   first repoint keeps the task's own request in `repointed_from`,
   `repointed_branch` and `repointed_pushed`, and unsets `pushed`: the head of
   `<n>` is not pinned, because the task that owns `<n>` may add commits to it.
   The merge gate becomes `PR #<n>` or `MR !<n>` with its URL (`tg gate`). By
   default it closes the task's own request with a comment that names `<n>`
   (`superseded`; GitHub `gh pr close --comment`, GitLab a note, then
   `state_event=close`); `--keep-old` leaves it open. It also leaves it open, with
   `kept-open` naming them, while another task that waits for its merge follows
   that request (it was repointed to it before). The phase does not change,
   so the transition table has no row for it. A repeat with the same request does
   the steps a failed run left (`host-error` when the close failed). When the
   comment was posted but the close failed, the repeat posts the comment again,
   so the old request can show it twice.
   `record` then reads `<n>` for the task as information only: `follows` while
   it is open, whatever its merge state; it opens no decision and never rebases,
   pushes or merges `<n>` for this task. The task that owns `<n>` does that.
   When `<n>` is merged, the merge completes the task: the repoint is your word
   that the task's change goes in through `<n>`, as `run.py merged <id> --by
   operator` is. `record` records the merge with `merged_by=repoint` and
   `merged_via=<n>`: the task is done, the gate is cleared, and its dependents
   become ready. The cleanup of the merged task then removes its worktree and
   its local branch, even when the task's commit is not in the target; the
   commit stays on the host on the branch of the task's own request
   (`repointed_branch`). Before the merge record it prints one `target-check` line, for information
   only: `in target` when the task's `verdict_ref` is in the fetched target
   branch (the commit or one with the same patch, `git merge-base
   --is-ancestor` and `git cherry`: a merge commit, or a rebase merge of one
   commit; else `git merge-tree --write-tree <target> <verdict_ref>` gives the
   target's own tree: a squash merge, or a rebase merge of several commits, git
   2.38 or later), else `not proven in target (<why>): its content may have been
   redone in <n>`. A combined request that another task redid and rebased often
   holds neither the task's commits nor their exact content, so the check does
   not hold the task back; read the line when you want to look. When `<n>` was
   merged into another branch than the task's target (its base changed after the
   repoint), `record` prints `pr-retargeted` and does not mark the task merged:
   repoint it to a request into the target, or run `run.py merged <id> --by
   operator` when the change is in the target. When `<n>` is
   closed without a merge, `record` prints `pr-closed`: repoint the task again,
   run `run.py merged <id> --by operator` when the change is in the target
   another way, or abandon it and launch the next attempt.
   `close` refuses a repointed task (its publish would push to another task's
   branch). `abandon` leaves `<n>` alone, and the next `launch` gives the task its
   own request back (`pr`, `pr_branch` and `pushed` from the `repointed_*`
   keys); if repoint closed that request, the next `close` reports it as
   `pr-closed` until you reopen it on the host. `status` shows the request as
   `#<n> (repointed from #<own>)`.
7. `run.py close` posts the verdict on the request as one comment: the level, whether it closes the task, the verified head, the kind, the attempt, who filed it, and the evidence from that verify result (its `Ran:`, `Issues:` and `Follow-ups:` lines; for CI, `Run:` and `Conclusion:`; for an override, `Overrides:` and `Reason:`). A hidden marker is the comment's first line; a later verdict on the task edits that comment instead of adding one. A verdict that does not close the task is posted too, when a request exists; before any push there is none, and nothing is posted. A failed post is one `comment-failed` line with the next step, and `close` still exits 0. GitHub: `gh api` on the issue-comments resource. GitLab: `glab api` on the merge request notes.

## A PR manager session

A repository whose CI is costly can merge through a queue run by the `agentic-team:pr-manager`
agent (model `haiku`), instead of `record` merging every clean request. GitHub only. The agent
keeps one request ready at the head and every other queued request a draft, so one full CI run is
spent at a time; it catches the head up, merges it when its CI is green and clean, and sends
`ci-failed` and `conflict` back to the Manager. It decides the order itself, from the task
priorities, the Manager's wishes, the size of each change and its conflict history. It queues only
agentic-team requests (with the run.py verdict comment, or sent by the Manager) and merges only the
head it pinned: the verified head, or the result of its own update-branch from it. A head that moved
any other way, and a request it reported as failed, wait for a new `ready` from the Manager. It
changes no code and no Taskgraph state; `record` records its merges as merges by someone else.

**Prerequisites** in the CI workflow, or the draft queue saves nothing and `gh pr ready` starts no run:

- the `pull_request` trigger lists `types: [opened, synchronize, reopened, ready_for_review]`;
- the heavy jobs skip drafts (`if: github.event.pull_request.draft == false`);
- a `concurrency` group per request with `cancel-in-progress: true`, so a new run replaces the old one.

To use it:

1. Remove the `MERGE:` line from `standing-orders.md`, so `record` does not merge as well.
   Set `[merge] draft = true`, so new requests open as drafts.
2. Optional: write `.claude/agentic-team/pr-manager.md` (tracked) with the project's rules: which CI
   jobs do the work and which only summarise, the merge method (for example: fall back to `--squash`
   when a rebase merge is refused for merge commits), order rules, and anything the queue learns. It
   wins over the agent's own text.
3. Start it from the main checkout:
   `claude --bg --agent agentic-team:pr-manager --permission-mode auto "/loop Run one pr-manager round."`.
   `/loop` without an interval lets it choose when to wake. Give it `Bash(gh pr ready:*)`,
   `Bash(gh pr merge:*)`, `Bash(gh pr update-branch:*)`, `Bash(gh run cancel:*)` and
   `Bash(gh run rerun:*)` in the project's permission rules when the mode needs them.
4. The Manager sends `ready PR #<n> task <id>` after a passing `close`, and `fixing PR #<n>` before a
   round on a published request, to the address the agent writes to `.agentic-team/pr-manager.addr`;
   when that send fails, it appends the line to `.agentic-team/to-pr-manager.log`, which the agent
   reads every round. The agent reports to the Manager's socket in `.agentic-team/manager.addr`, and
   appends to `.agentic-team/pr-manager.log` when that send fails.

With `[merge] after_rebase` set, `record` runs that check on every rebase the agent makes; a failure
there is a `conflict` line from `record`, not from the agent.

**Batching** is not in the agent. A project that wants it describes it in the project file and lets
the agent push: build the batch in a separate worktree or clone, never in the main checkout; the agent
sends the Manager `batch PR #<b> members #a #b`, and the Manager runs `run.py repoint <id> --pr <b>`
for each member's task, so `record` completes them when the batch merges (item 6).

Its state is the queue file `.agentic-team/pr-queue.md`, GitHub and the project file, so a new session
picks up where the last one stopped. A session can end on its own; when a send to its address fails,
the Manager starts a new one with the same command. To stop it, stop its session; nothing else needs undoing.

**Stacked base that merged under other SHAs.** A task launched with `--base` on another request's branch holds that
request's commits. When the request later merged by rebase or squash, the target holds its change but not its commits.
Before `close` publishes (and before `launch` continues a retry in the same branch), `run.py` looks at the commits of
the `base` meta that the target lacks. The base counts as merged when `git cherry` finds every one of them in the target
(a rebase merge), when merging the base into the target changes nothing (a squash merge), or when a dependency task of
the task is merged (done, or `merged_at`) and its pushed or verified head holds the base (a squash merge that the target
changed again). Then it rebases only the task's own commits (`git rebase --onto <target> <base>`) in the idle task
worktree, checks `same_change` on that span, runs `[merge] after_rebase` (the result goes into the after-rebase cache,
so the push does not run it again), moves `verdict_ref`, and prints `rebased`. `verify` with `verify_mode = ci` stops a
kept worker session first, as `close` does. It refuses, with each stale commit named (short SHA and subject), when the
worktree is missing, dirty, has a live session or is not at the head to publish, when the rebase conflicts or changes the
diff, or when the check fails; the branch is then put back at its head with `git reset --hard`. The fix it names is
`git -C .claude/worktrees/task-<id> rebase --onto <target> <base> <branch>` before the request exists, and
`run.py round <id> rebase` once it does; the round's role text then rebases with `--onto <target> <base>`, so the stale
commits are not replayed. A base that the target does not hold, no open dependency holds, and no check found merged
gets a `warn` line (its commits may be stale); so does a target that cannot be fetched, and a git older than 2.40, whose
`git merge-tree --write-tree --merge-base` is missing, so that the squash check cannot run. A base whose net change is
empty (a commit and its revert) counts as merged; the rebase is harmless there.

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
(`rebased`) and written (`verdict_ref`); any other difference is refused. A
round whose head carries the same change as the verified head keeps its verdict
by the same rule (item 5 above).

**CI as the verifier.** With `--meta verify_mode=ci:<name>` on the task,
`run.py verify <id>` pushes the branch, opens the request, and finds the CI run
for the pushed head, or dispatches one when it has a manual trigger. `record`
files the finished run as a `verify` result by `ci` (`test-verified`, or
`verify-failed`; a cancelled run is `verify-blocked`), once per run id and
attempt. `artifact-verified` stays a Manager override. On GitHub `<name>` is a
workflow file or name; on GitLab it is `pipeline` or a job name. A CI
`test-verified` does not close a `schema` or `design-doc` task.

**CI ref for a session verifier.** A change that only CI can prove, such as a
change to `.github/workflows/ci.yml`, has no other run to judge before `close`,
and `close` pushes the request only after a closing verdict. `run.py verify <id>
--ci-ref` (with `--again` after a first verdict) pushes the worker's `Head` to a
scratch branch, `<[verify] ci_ref_prefix><id>-<attempt>` (default `ci-<id>-<attempt>`),
never to the request's branch, and prints a `ci-ref` line. CI runs there as on any
push, so the branch prefix must match the push filter of the workflow; a
workflow that runs only on `pull_request` never runs on a scratch branch (the
verifier then says `check-only`), and the request's own run comes only after a
closing verdict, because `close` pushes the request. Add a `push` trigger for the
prefix, such as `on: { pull_request: {}, push: { branches: ["ci-**"] } }`, or
override with other evidence. The verifier stays read only: run.py pushes, and the brief names the branch, the
commit and the read-only commands that find the runs, wait for them and read a
failed job (`gh run list --branch <ref> --commit <sha>`, `gh run watch`, `gh run
view --log-failed`; `glab ci list --ref`, `glab ci status --live`, `glab ci
trace` on GitLab; these glab flags are UNVERIFIED, like the other GitLab calls).
The verifier runs them with the operator's `gh` or `glab` login; no allow rule
is needed in auto mode for these read-only calls, and a verifier that cannot
run them says `check-only` with the reason. The brief tells it to list the runs
again for at least 5 minutes before it decides there is none (a run shows up
late), and to run a watch in the background, or again, when it outlasts the
10-minute limit of one Bash call. A green run that exercises the changed workflow or job is
`test-verified`; a red run is `verify-failed` with a `blocking:` line per failed
job; no run of that commit, or no run that exercises the change, is `check-only`
with the reason. The verifier puts each run's URL under `Ran:`. The `ci_refs`
meta lists the pushed branches; a passing `close` and `abandon` delete them on
the remote (`ci-ref-deleted`), and a branch that cannot be deleted stays listed
with a `warn` line that names the `git push --delete` to run. A `close` that does
not pass keeps them. Once an attempt has a CI ref, every later `verify` of that
attempt (`--again`, or the verify of a revision) pushes the new head to it
without the flag, and the brief names the new commit; a revision brief also says
that a run of any other commit proves nothing. `round --cancel` and every
recorded merge delete the branches too. `--ci-ref` is for a `code` task (a CI run
gives at most `test-verified`) and needs `merge.mode = "pr"`; with `verify_mode = ci:<name>` it is refused, because that
mode already pushes the request's branch.

**Check-only never closes.** No command accepts `check-only`: `close
--verdict check-only` records it and the task stays in progress. The `next:`
hint names the two ways on: `run.py verify <id> --again` for a stronger verdict
(with `--ci-ref` for a `code` task in pr mode when only a CI run can prove the change), or `run.py
close <id> --verdict test-verified --override-verifier "<why>" --ran "<CI run URL
or artifact link>"` (`artifact-verified` for a `schema` or `design-doc` task).
Guard mutations count as test evidence: a verifier that breaks the code under
test on purpose, in a scratch copy, and sees every break turn the covering tests
red reports `test-verified`, not `check-only`.

**Override.** `run.py close <id> --verdict <level> --override-verifier "<why>"`
changes a verifier's verdict and files the reason. An upgrade needs a run id or
a link in `--ran`. `verify-failed` is never upgraded; it needs a fix round.

**Adopt.** `run.py adopt <id> --branch <b> --head <sha> [--pr <n>]` brings work
that started outside `run.py` under the Manager. It files a `PASS` result by the
Manager (no worktree, no session) and records the request when `--pr` is given.
`record` lists tasks in progress with no `attempt` in one `unmanaged` line.

**The host seam.** [scripts/host.py](../scripts/host.py) is the only module that
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
