Then exercise the real output: run it, open it, or read the values it
produced. Report every failure you can prove, not only the first. A miss is a
`blocking:` finding under `Issues:`, or a `nonblocking:` line under Follow-ups
when the non-blocking test in your brief holds.
A category on a `blocking:` line is optional: `blocking[stale-ref]:` (a `file:line` reference that no longer
points at what it names), `blocking[claim]:` (a statement about the code that is false), `blocking[test]:`,
`blocking[scope]:`, `blocking[shots]:` or `blocking[behaviour]:`. Write one `Issues:` field, one finding per line.

### Method: code

A change to a tracked file, or a new file that git does not ignore, in the worktree under review is
a verifier error: your checks write only ignored build output and the scratch folder your brief names.
In the task worktree, run.py stashes such a change before the task session resumes.

Order of runs: do every run at the head commit first (steps 1, 2 and 3), then export the
base commit as your brief says and do every run at the base commit. The export stays in
`.agentic-team-scratch/`; you delete nothing.

1. Start the application from a clean state, as a user would, and drive the
   change through its real interface (UI, CLI or API). Check side effects:
   files written, rows changed, messages sent to a stub. A passing test suite
   is not proof of behaviour.
2. If the task fixes a defect (GOAL or ACCEPTANCE names a failure), confirm
   that the failure is gone at the head commit, then reproduce it at the base
   commit named in CONTEXT, after all head runs. Record both results under
   `Ran:`, each with its commit. A check that passes at both commits proves nothing about the fix.
3. Run every command of the project verify skill's `Checks` section at the
   head commit, and at the base commit named in CONTEXT. Record each run under
   `Ran:` with its commit. A problem that only the head has is a miss, and
   the change fails that check. A problem that the base already
   has goes under `Follow-ups:` as `found:`. When the section is missing, or a
   kind is still `TODO`, say so under `Follow-ups:` as
   `doc: .claude/skills/verify/SKILL.md: no <kind> check; ask the user to add one`.
4. Read `git diff <base> <head>` and flag every change outside SCOPE. Also flag
   a workaround: a skipped or loosened test, an ignore comment, a type-hiding
   cast, a raised timeout, or a new exemption or baseline entry without a
   stated root cause.
5. Stop only the processes you started. Never stop a process by name.

A change that only CI runs (a CI workflow or job file, such as
`.github/workflows/*.yml` or `.gitlab-ci.yml`) is proved by a CI run of its
head. When CONTEXT names a CI ref, judge the runs on it as CONTEXT says. With
no CI ref, report `check-only` and say under `Ran:` that only a CI run
proves the change; the Manager then runs `run.py verify <id> --again --ci-ref`.

Verdict levels for this kind:
- `artifact-verified`: you drove the application or read the values it
  produced, and every ACCEPTANCE line holds.
- `test-verified`: VERIFY passes and covers every ACCEPTANCE line, and the
  change has no observable behaviour change (tests, docs, build files, a
  pure refactor the same tests cover). A behaviour change you did
  not drive is `check-only`, not `test-verified`. Also `test-verified`: a
  green CI run on the CI ref that exercises the changed workflow or job.
- Guard mutations are test evidence. When you break the code under test on
  purpose, in a copy in your scratch folder, and every break turns the
  covering tests red, the tests prove that code: with VERIFY passing at the
  head and covering every ACCEPTANCE line, that is `test-verified`, not
  `check-only`, also for a behaviour change those tests cover. List each
  mutation and its red run under `Ran:`.
- `check-only`: static checks or a read-through only, with no test, mutation
  or CI run that proves the change.
- `verify-blocked`: a check could not run; name the cause.
- `verify-failed`: an ACCEPTANCE line does not hold; list every failure.
