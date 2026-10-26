# Verify and close

**A worker's PASS is a claim, not a verdict.** Close a task only on a verdict
tied to the exact output.

1. **Pin the output.** Read the worker's latest result
   (`result ls <id> --kind task --latest`). Set `verdict_ref` to its `Head:`
   commit SHA. Use checksums of the output files (`shasum <files>`) only when
   the task's output is outside git. Any later change to that output voids the
   verdict.
2. **Choose the verifier.** If a `kind=verify` result already exists for the
   current attempt (`result ls <id> --kind verify --attempt <n>`), do not launch
   another verifier: go to step 3. Exception: its verdict is `verify-blocked`
   and the cause is fixed.
   - `risk=low` with a cheap VERIFY: rerun the VERIFY commands yourself inside
     the worker's `Worktree:` path, and spot-check the output files. Check that
     `git -C <worktree> rev-parse HEAD` equals `verdict_ref`. Then run
     `git -C <worktree> status --porcelain` and delete the files your rerun
     created, and only those. Set `verified_by=manager`.
   - `risk=high`, or a check that is expensive or needs judgement: render a
     verifier brief with
     `"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/brief.py" --tg "$TG" --task <id> --kind verify --report <result id> --verdict-ref <ref from step 1>`.
     `--report` is the id of the worker's result; without it, `brief.py` uses
     the latest task result for the current attempt. `brief.py` prints the
     session name, `verify-<id>-<attempt>`. The brief tells the verifier to run
     `git checkout --detach <verdict_ref>` first and to change nothing. Launch
     it as in the launch playbook's step 6, but with
     `--worktree verify-<id>-<attempt>` and `--name verify-<id>-<attempt>`.
     To retry after `verify-blocked`, pass `--session verify-<id>-<attempt>-2`
     (then `-3`) and use that name for the worktree too. Skip the launch
     playbook's step 7, so the task's session metadata stays the worker's. A
     verifier counts against `sessions.max_parallel`. Pick the model with
     `config.py model verifier`. When it prints a null model (the default),
     use a different model from the worker's: `opus`, or `sonnet` if the
     worker ran on `opus`. Its `kind=verify` result gives the verdict. Set
     `verified_by=<session>`. It commits nothing. Leave its session and
     worktree for step 8.
3. **Record the verdict.** Run `tg edit <id> --meta verdict=<level> verdict_ref=<ref> verified_by=<who>`.
   The levels are:
   - `artifact-verified`: the real output was exercised or read.
   - `test-verified`: the VERIFY commands pass, and they cover every
     ACCEPTANCE line.
   - `check-only`: only static checks pass. This is not enough for behavior.
   - `verify-blocked`: the check could not run. This is not a pass. The next
     drain lists the task again; retry when the cause is fixed.
   - `verify-failed`: start a fix round from the drain playbook; do not just
     re-verify.
4. **Close only when it holds.** Run `tg done` only when:
   - the verdict is `artifact-verified` or `test-verified`;
   - `verdict_ref` still matches the output: `git -C <worktree> rev-parse HEAD`
     still equals it;
   - the operator has confirmed every step that needs a person. A request a
     person must send is not done until they send it.
5. **Record time and tokens.** Before you stop the session, get its id from
   `claude agents --json --all`: the row whose `cwd` ends with
   `.claude/worktrees/task-<id>-<attempt>`. Run
   `"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/tokens.py" <session-id-prefix> --cwd <worktree> --tz <zone> --label <label>`,
   with `<worktree>` from the result's `Worktree:` line and `<zone>` and
   `<label>` from `config.py get sessions.timezone` and
   `sessions.timezone_label`,
   and pass its output to `tg edit <id> --meta ...`. If it cannot find the
   transcript, it exits with a message; record no tokens.
6. **Integrate.** You do not merge by default. Merge only when the standing
   orders say you may, and only when `git status --porcelain` in the main
   checkout is empty. The target is the branch the main checkout has checked
   out (`git branch --show-current`). Run `git merge --no-ff <branch>`, where
   `<branch>` is the result's `Branch:` line. If it reports a conflict, run
   `git merge --abort`, then write a gate that names both branches. Do not
   resolve a conflict by guesswork.
   When a merge is confirmed, record it:
   `tg edit <id> --meta merged_at="<now>" merged_by=<manager|operator>`.
   Use `manager` for a merge you made. Use `operator` when the operator says
   the branch is merged, including a squash or rebase merge, or when
   `git merge-base --is-ancestor <Head> HEAD` succeeds in the main checkout.
   A squash or rebase merge leaves that check false, so the operator's word is
   the record. Until `merged_at` is set, the branch is ready to merge: list it
   under "Ready to merge" in your reply and in the next report.
7. **Close.** Run `tg done <id>`. If the worker session is still running, stop
   it with `claude stop <id>`. Check `ready` for work this unblocked. A task
   whose dependency is done but not merged does not launch (launch step 1).
8. **Clean up, after the merge.** Do this only once `merged_at` is set, in this
   step or at a later drain. Never for an abandoned task: leave its worktrees
   and list them in the report.
   - Find every session of the task in `claude agents --json --all`: all
     attempts (`task-<id>-*`) and verifiers (`verify-<id>-*`).
   - Skip an attempt that was stopped with uncommitted changes
     (`git -C <worktree> status --porcelain` is not empty). List it in the
     report instead of removing it.
   - Run `claude rm <id>` on each of the others. It also removes the worktree.
   - `claude rm` refuses to delete a worktree whose commits are on no remote,
     even after a local merge. It prints a `--discard-unpushed
     <commit>@<worktree-id>` value. Pass it only when
     `git merge-base --is-ancestor <commit> HEAD` succeeds in the main
     checkout for that `<commit>` and `git -C <worktree> status --porcelain` is
     empty. Never pass it for work that is not merged.
   - `claude rm` also refuses a worktree with untracked files. List them.
     Delete only files your own rerun in step 2 created. Otherwise leave the
     worktree and list it in the report. Never pass `--force-remove-worktree`
     unless the operator says so.

Never set `tg date --start`. `started_at` is the only start field.

**Reply:** the task, its verdict and who gave it, the branch ready to merge,
and what it unblocked.
