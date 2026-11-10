---
fits: design documents, ADRs, specs, interface contracts, data models, migration plans
tier: judgement
verify_kind: design-doc
skills: [architecture-design:architecture-design, writing-editor:writing-editor]
---

## Method

1. Read the code, data and documents the design touches before you write. Every statement about how the system works today cites `path:line` or a document section that says so.
2. State the problem with measurable outcomes, then the goals in rank order, the non-goals, and the constraints.
3. Give at least two options, one of them the smallest change or doing nothing. For each, name the goal it serves and the goal it gives up.
4. Decide, and name the alternatives you rejected and why. A choice that needs the operator (product, money, a preference no evidence settles) is not yours: write it as an open decision with your recommendation and its default.
5. Specify every interface the design adds or changes: inputs, outputs, errors, who calls it, and how it is versioned.
6. For each external call, state change and concurrent path, say what happens when it fails, times out, retries or runs twice. A lifecycle with concurrency, retries or money gets a Mermaid statechart and a transition table.
7. Say how the change is rolled out and rolled back, what existing data or behaviour changes, and what to measure afterwards.
8. Draw the overview and the main flow as Mermaid diagrams, and check that each one renders.
9. Trace each goal to the part of the design that delivers it, in a short table at the end.

## Review

Check these in addition to the design-doc method. Report each miss as an issue with the section it is in.

1. Goal trace: every ranked goal maps to a named mechanism in the design. A goal with no mechanism, or a mechanism that serves no goal, is an issue.
2. Interfaces: each added or changed interface lists inputs, outputs and errors. A missing error case is an issue.
3. Failure behaviour: each external call, state change and concurrent path named in the design has its failure behaviour stated. Name each one that is missing.
4. Lifecycle: a lifecycle with concurrency, retries or money has a statechart and a transition table, and every transition in the table appears in the chart.
5. Diagrams: each Mermaid block renders. A block that does not render is an issue.
6. Open decisions: each choice that needs the operator is listed as open, with a recommendation and a default, not decided silently in the text.
