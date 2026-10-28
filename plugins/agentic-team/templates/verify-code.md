Then exercise the real output: run it, open it, or read the values it
produced. Report every failure you can prove, not only the first.

### Method: code

1. Start the application from a clean state, as a user would, and drive the
   change through its real interface (UI, CLI or API). Check side effects:
   files written, rows changed, messages sent to a stub. A passing test suite
   is not proof of behaviour.
2. If the task fixes a defect (GOAL or ACCEPTANCE names a failure), first
   reproduce the failure at the base commit named in CONTEXT, then confirm it
   is gone at the head commit. Record both results under `Ran:`, each with its
   commit. A check that passes at both commits proves nothing about the fix.
3. Read `git diff <base> <head>` and flag every change outside SCOPE under
   `Issues:`.
4. Stop only the processes you started. Never stop a process by name.

Verdict levels for this kind:
- `artifact-verified`: you drove the application or read the values it
  produced, and every ACCEPTANCE line holds.
- `test-verified`: VERIFY passes and covers every ACCEPTANCE line, and the
  change has no behaviour a user or another program can see (tests, docs,
  build files, a refactor the same tests cover). A behaviour change you did
  not drive is `check-only`, not `test-verified`.
- `check-only`: static checks or a read-through only.
- `verify-blocked`: a check could not run; name the cause.
- `verify-failed`: an ACCEPTANCE line does not hold; list every failure.
