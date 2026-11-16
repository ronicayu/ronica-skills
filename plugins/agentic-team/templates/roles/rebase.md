---
fits: rounds only (run.py round <id> rebase): a task that waits for its merge and whose change conflicts with its target; rebase it onto the target and keep both sides
skills: []
---

## Method

This attempt is a rebase round. The task's change passed with verdict {{ROUND_VERDICT}} at `{{ROUND_FROM}}`, on top of `{{ROUND_OLD_BASE}}`. The target has moved to `{{ROUND_ONTO}}`, and the two conflict. Files that both sides changed: {{ROUND_OVERLAP}}.

1. Run `{{ROUND_REBASE}}`. This is the one command that moves the branch in this round. Use that exact commit: do not fetch, and do not rebase onto a branch name.
2. For each conflict, read the target's commits that touch the file (`git log --oneline {{ROUND_OLD_BASE}}..{{ROUND_ONTO}} -- <file>`). Resolve it so that both sides keep their behaviour: the task's change, and the target's changes. Change nothing else. Then run `git add <file>` and `git rebase --continue`. Beyond SCOPE you may touch only the lines of a conflict in the files above; a resolution may keep target lines outside SCOPE, but must not change them.
3. When a conflict needs a product decision, or you cannot keep both behaviours, run `git rebase --abort`, then ask the Manager with the conflicting hunks (see Ask first); report `BLOCKED` when the answer does not settle it or no ask is left.
4. When the rebase ends, run every VERIFY command and the tests of the target's commits in the files above. Fix only what the resolution broke, and commit each fix.
5. Do not push. `Head:` is the new head. Under `Deviations:`, write one line for each file you resolved: `rebase: <path>: <what each side kept>`. A rebase with no conflict is a `PASS` with `Deviations: rebase: no conflict`.

## Review

This round rebased the task's change, which passed at `{{ROUND_FROM}}` on top of `{{ROUND_OLD_BASE}}`, onto `{{ROUND_ONTO}}`. Files that both sides changed: {{ROUND_OVERLAP}}. Check these, in this order:

1. Run `git range-diff {{ROUND_OLD_BASE}}..{{ROUND_FROM}} {{ROUND_ONTO}}..<head>`. Each difference must come from a conflict in the files above. Any other difference is a blocking issue.
2. The task's side: each ACCEPTANCE line still holds at the head.
3. The target's side: for each file above, read `git log {{ROUND_OLD_BASE}}..{{ROUND_ONTO}} -- <file>`, find the behaviour that each of those commits added, and prove that it holds at the head: run its tests, or drive it. A lost or changed behaviour of the target is blocking: `blocking: rebase dropped <commit>: <behaviour>`.
4. Report `artifact-verified` only when both sides hold.
