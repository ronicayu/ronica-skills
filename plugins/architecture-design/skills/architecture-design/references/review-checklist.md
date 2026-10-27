# Review checklist

Run every item. Report each failure in its group, quoting or pointing to the text, with what would close it. Where the document follows a project template, check the template's own checklist too.

## Blocks the review

The reviewers cannot judge the design until these are fixed.

- [ ] The problem statement names no solution.
- [ ] Every outcome has a measure, a baseline and a target.
- [ ] The quality goals are ranked.
- [ ] The summary and context name no class, table, queue, field, state or ID. A low-level fact that the high-level design depends on is stated once as a named constraint, with a pointer to where it is defined.
- [ ] Every design-shaping requirement is Committed, or marked Blocking. Every Blocking NFR is also an open question with an owner and a date.
- [ ] The fundamental options include doing nothing, or say why that is not possible.
- [ ] Every key decision names the alternative it rejected.
- [ ] The runtime view covers at least three failure modes, each with detection, recovery and user-visible impact.
- [ ] Migration and cutover are present, or greenfield is shown with evidence.
- [ ] Every compliance control the design cannot meet alone has an owner.
- [ ] Every review log entry has a response. Everyone asked appears in the log or in the declined list.

## Weakens the design case

The design can be judged, but a reviewer will challenge these.

- [ ] Every trade-off names the losing goal and the compromise, and traces to a decision.
- [ ] Every key decision states the goal it serves, what becomes easier and harder, and a measurable revisit condition.
- [ ] The options comparison uses the ranked goals as its columns.
- [ ] Every design element traces to a requirement, goal, NFR or constraint. An element with none is flagged as proposed beyond the requirements, or removed.
- [ ] Requirements say what and why, never how. A requirement that names a technology is a design decision, and is argued as one.
- [ ] Every quality claim ("scalable", "fast", "secure", "resilient") has a number, a mechanism, or a pointer to where it is proven. Otherwise it is cut.
- [ ] Sections follow the design's dependencies: requirements and goals, then decisions, then the elements that rely on them. Each section descends one level of detail, and no section sends the reader back up.
- [ ] Every element in a diagram has a responsibility entry. No element appears in a later section before the building block view introduces it.
- [ ] Every boundary-crossing arrow has a trust entry.
- [ ] Every workload number and NFR names its source and its workload assumption.
- [ ] Assumptions are listed, each with who can confirm it.
- [ ] The decisions table, summary and glossary agree with the body: counts, statuses, scopes and names.
- [ ] A decision that contradicts an accepted ADR says so and supersedes it.
- [ ] Build detail is linked from a one-line summary, not inlined.
- [ ] Every ADR lists ranked criteria before its options, includes doing nothing where possible, and has a "Revisit when".
- [ ] Standards are named and linked, not explained.

## Polish

Hand to `writing-editor` when it is installed: structure, reader load, sourcing, sentences, and the tells of machine-drafted prose.
