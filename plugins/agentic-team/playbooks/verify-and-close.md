# Verify and close

**A worker's PASS is a claim, not a verdict.** Close a task only on a verdict
tied to the exact output.

1. **Pin the output.** Set `verdict_ref` to the commit SHA (`git rev-parse
   HEAD`) or to checksums of the output files (`shasum <files>`). Any later
   change to that output voids the verdict.
2. **Choose the verifier.**
   - `risk=low` with a cheap VERIFY: rerun the VERIFY commands yourself and
     spot-check the output files. Set `verified_by=manager`.
   - `risk=high`, or a check that is expensive or needs judgement: render a
     verifier brief with
     `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/brief.py" --tg "$TG" --task <id> --session <name> --kind verify --report <saved report> --verdict-ref <ref from step 1>`,
     then launch it as in the launch playbook's step 6. Skip its step 7, so
     the task's session metadata stays the worker's. Pick the model with
     `config.py model verifier`. When it prints a null model (the default),
     use a different model from the worker's: `opus`, or `sonnet` if the
     worker ran on `opus`. Its report gives the verdict. Set
     `verified_by=<session>`.
3. **Record the verdict.** Run `tg edit <id> --meta verdict=<level> verdict_ref=<ref> verified_by=<who>`.
   The levels are:
   - `artifact-verified`: the real output was exercised or read.
   - `test-verified`: the VERIFY commands pass, and they cover every
     ACCEPTANCE line.
   - `check-only`: only static checks pass. This is not enough for behavior.
   - `verify-blocked`: the check could not run. This is not a pass. Retry
     when the cause is fixed.
   - `verify-failed`: start a fix round from the drain playbook; do not just
     re-verify.
4. **Close only when it holds.** Run `tg done` only when:
   - the verdict is `artifact-verified` or `test-verified`;
   - `verdict_ref` still matches the output;
   - the operator has confirmed every step that needs a person. A request a
     person must send is not done until they send it.
5. **Record time and tokens.** Before you stop the session, get its id from
   `claude agents --json`. From the repository root, run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tokens.py" <session-id-prefix> --tz <zone> --label <label>`,
   with `<zone>` and `<label>` from `config.py get sessions.timezone` and
   `sessions.timezone_label`,
   and pass its output to `tg edit <id> --meta ...`.
6. **Close.** Run `tg done <id>` and stop the session with
   `claude stop <id>`. Then check `ready` for work this unblocked.

Never set `tg date --start`. `started_at` is the only start field.

**Reply:** the task, its verdict and who gave it, and what it unblocked.
