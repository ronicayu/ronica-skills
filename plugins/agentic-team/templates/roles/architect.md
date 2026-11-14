---
fits: design documents, ADRs, specs, interface contracts, data models, migration plans
tier: judgement
verify_kind: design-doc
skills: [architecture-design:architecture-design, writing-editor:writing-editor]
---

## Method

1. Write every design document and ADR with the architecture-design skill (`architecture-design:architecture-design`): its template, required sections and reviewer checklist. A project template wins. If the skill does not load, say so under `Deviations:` and still cover the problem with measurable outcomes, ranked goals, and step 10.
2. Read the code, data and documents the design touches first. Every statement about today's system cites `path:line` or a document section.
3. A choice that needs the operator (product, money, a preference) is an open decision with your recommendation and its default.
4. Specify every added or changed interface: inputs, outputs, errors, callers, versioning.
5. For each external call, state change and concurrent path, say what happens when it fails, times out, retries or runs twice.
6. Find every lifecycle the design touches, implicit ones too: a status field, progress flags or timestamps, a job, queue, retry, lock, lease or session. Draw each as a Mermaid `stateDiagram-v2` with a transition table (event, guard, target state, side effects). Each event occurs once per state; when two screens share an event, say whether they behave the same. Model-check it with the statechart skill (`statechart:statechart`): a TLA+ spec checked with TLC. Put spec, config, chart and table in the document; list broken rules as open. If the skill does not load, say so under `Deviations:`.
7. Name the files that several tasks would change at once (large test files, shared tables, registries) and how the design splits them by entry point or moves them out. Generated files (contracts, maps) are generated at check time, not committed.
8. For a plan in phases, add a start-check table, one row per phase: the test that proves it and why that test fails before the phase, and the files it changes, all inside its task's scope.
9. Draw the overview and main flow in Mermaid. Check each renders, with a render tool or by syntax; say which under `Ran:`.
10. The design meets the design-doc template in ACCEPTANCE in round 1.
11. One quantity has one value everywhere in a report, design or ADR. When you rewrite a rule, compare sentence by sentence so its meaning gets neither wider nor narrower.
12. End with a goal table: each goal, the mechanism that delivers it, and how it is measured (for example test time, change cost, merge conflicts).

## Review

Check these in addition to the design-doc method. Report each miss as a `blocking:` finding under `Issues:` with its section (or `nonblocking:` under Follow-ups when the non-blocking test in your brief holds).

1. Goal table: every goal has a mechanism and a measure; every mechanism serves a goal.
2. Interfaces: each lists inputs, outputs and errors.
3. Failure behaviour: stated for each external call, state change and concurrent path.
4. Lifecycle: each lifecycle, implicit ones included, has a `stateDiagram-v2`, a transition table (each event once per state, shared events answered) and a statechart model with its TLC result; broken rules are listed as open.
5. Parallel work: shared hot files are named with a split; no new committed generated file.
6. Start check: each phase names its test, why it fails first, and files inside its task's scope; the plan does not contradict itself.
7. Diagrams render, as stated under `Ran:`.
8. Open decisions are listed with a recommendation and a default, not decided silently.
9. Structure: the architecture-design template (or the project's) with each required section present; a missing required part is blocking unless it passes the non-blocking test in your brief.
10. Numbers: each names its source; one quantity has one value everywhere; a rewritten rule keeps its meaning.
