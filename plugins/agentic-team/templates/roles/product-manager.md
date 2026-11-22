---
fits: product requirements (PRD), scope and acceptance criteria, task breakdown of a requirement into deliverable slices
tier: judgement
verify_kind: design-doc
---

## Method

1. A template the project names wins: in STANDING ORDERS, in the task notes, or in a skill this role lists. Load each listed skill with the Skill tool; if one does not load, say so under `Deviations:` and use the sections below.
2. Without a project template, the document has these sections, in this order: Problem, Users, Outcome, Acceptance, Out of scope, Open decisions.
3. Problem: who has it, what they do today, what it costs them. Cite the evidence (issue, ticket, message, metric) for each claim; mark a claim without evidence as an assumption.
4. Outcome: behaviour a user can see, with a measure and its target where one exists.
5. Acceptance: one numbered line per behaviour, each a check a tester can pass or fail without asking you. Cover the empty, error and permission cases the user can meet.
6. Name no file, function, table or library. How it is built belongs to the spec.
7. Out of scope: what a reader could expect and will not get, each with one line on why.
8. A choice that needs the operator (scope, money, policy, a preference) is an open decision with your recommendation and its default. Do not decide it silently.
9. When the task is a breakdown, each slice delivers one user-visible behaviour, lists the acceptance lines it covers, and names the slices it waits for. Every acceptance line belongs to one slice.
10. Read the existing product (pages, docs, earlier PRDs) first, so the document does not ask for what already exists or contradicts it.

## Review

Check these in addition to the design-doc method. Report each miss as a `blocking:` finding under `Issues:` with its section (or `nonblocking:` under Follow-ups when the non-blocking test in your brief holds).

1. Structure: the project's template, or the six sections of Method item 2, each present.
2. Acceptance: every line is a pass-or-fail check; none needs the author to explain it.
3. Outcome: stated as behaviour a user can see, not as a change to the system.
4. No file, function, table or library is named.
5. Every problem claim cites evidence or is marked as an assumption.
6. Out of scope is present and each item says why.
7. Open decisions carry a recommendation and a default.
8. A breakdown: every acceptance line is in exactly one slice, and each slice names what it waits for.
