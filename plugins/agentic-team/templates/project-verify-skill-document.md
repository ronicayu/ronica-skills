---
name: verify
description: How to prove this project's schemas and design documents are right. The agentic-team verifier reads this file from its brief; it rechecks sources, recomputes numbers, checks the artifacts against each other, renders the review pages and runs the review. Fill every TODO with paths and scripts that exist in this repository.
---

# Verify this project

The verifier is read only: it edits nothing, commits nothing, checks out
nothing. Every command below runs inside the verifier's own worktree; `<worktree>`
means that folder. This file never lifts a rule in the verifier's agent
instructions or in its brief's FORBIDDEN section.

## Sources

Where the source data, inventories and requirements are.

- Source tables and inventories: TODO (paths or queries; which column holds the field name, which holds its class)
- Requirements and decisions: TODO (the documents a factual claim must point to)
- Stale when: TODO (how to tell that a source snapshot is out of date)

## Recompute

Scripts that recompute every count and coverage claim from the sources.

- Counts: TODO (the script and its arguments; what it prints; which numbers in which document it must match)
- Coverage: TODO (the script that lists each source field with its one class: added, merged, dropped or unchanged)
- DDL and migrations: TODO (how to apply and roll back on a temporary database: a container started with `--rm`, or a file database under `$(mktemp -d)`; the sample data for the constraints)

Remove the temporary database before you report. Stop only the processes this
run started, by the pid you recorded or by a working directory inside your own
worktree; never by name or by a command-line pattern. A leftover goes under
`Follow-ups:` as `leftover container: <name>` or `leftover file: <path>`.

## Consistency

The checks that the artifacts agree with each other.

- Artifacts: TODO (the ADR text, the DDL, the review page; their paths)
- Checks: TODO (a script, or the fields to compare by hand: names, counts, types)

## Render

How to build the review pages, and how to check that a built page matches its source.

- Build: TODO (the command; where the output lands)
- Match: TODO (the diff or the check that ties the built page to its source)

## Review

Which review skill and which model to use.

- Design review: TODO (the skill, in review mode, and the model; for example `architecture-design` on Fable)
- Prose review: TODO (the skill; for example `writing-editor`)
- Blocking finding: TODO (what counts: a wrong claim, a missing option, a contradiction. A finding about the decision itself is a `decision: <question>` follow-up, not a failure)
