# Section guide

What a good section looks like, its most common failure, and a short example. Use it in stage 4 of draft mode and to explain findings in review mode.

## Summary

**Good:** a reader who stops here knows what the system is, its main idea and what the review must do.
**Failure:** a summary that lists the sections, or needs a glossary to read.
**Example:** "Orders runs as three services that each own their data, with order intake separated from fulfilment so a fulfilment backlog never blocks new orders. The review must accept the service split and decide the message broker."

## Context

**Good:** the highest level: purpose, users, the major parts and how they connect. A reader can stop here and know what the system is.
**Failure:** low-level names in the opening sections: a table, a queue, a state such as `PENDING`, a requirement ID. Each one opens a question the section cannot answer. Name the concept instead ("each recipient is claimed before sending"), and point to the section that defines it.

## Problem and outcomes

**Good:** the problem is stated without a solution. Each outcome has a measure, a baseline and a target.
**Failure:** "We need a new event-driven platform." That is a solution.
**Example:** problem: "Orders placed during the monthly peak wait up to 40 minutes for confirmation (telemetry, March)." Outcome: "Confirmation within 1 minute at peak; baseline 40 minutes."

## Quality goals and trade-offs

**Good:** goals are ranked, and each names the decisions it drives. Each trade-off names the goal that loses and the compromise.
**Failure:** an unranked list of every "-ility". A goal that changes no decision is not a goal.
**Example:** "Data integrity over responsiveness: under peak load we queue requests rather than skip the durable write. Users may wait; no order is lost."

## Measurable NFRs

**Good:** a quality scenario with a stimulus, a response and a target, plus its workload assumption and its status.
**Failure:** "The system must be fast and highly available." Also: a Provisional NFR that the design depends on. That one is Blocking.
**Example:** "A user submits an order at 50 requests per second; p95 response under 800 ms. Verified by load test. Committed."

## Assumptions

**Good:** each assumption names what it affects and who can confirm it.
**Failure:** assumptions hidden in the design text ("the provider allows 1,000 sends per second").
**Example:** "The email provider grants 1,000 sends per second. Affects throughput and fan-out design. Confirm with the provider account manager."

## Requirements and design elements

**Good:** requirements say what and why; the design says how. Every design element traces back to a requirement, goal, NFR or constraint.
**Failure:** "The system must use a message queue." That is a design decision written as a requirement. Also: a component that no requirement asks for. Flag it as proposed beyond the requirements, or remove it.

## Fundamental options

**Good:** two to four real shapes, including doing nothing where possible, rated against the ranked goals plus complexity, cost and team familiarity.
**Failure:** one real option and two strawmen. Also: a comparison whose criteria are not the stated goals.
**Example:** "Do nothing: the backlog grows 20% a year and peak waits reach 1 hour by next year. Rejected on goal 1."

## Key decisions

**Good:** each decision sits in the section it shapes, with the goal it serves, the alternative it rejected, what becomes easier and harder, and a measurable revisit condition.
**Failure:** "Decision: use per-purpose tables. Why: best practice." No alternative, no cost, no trigger.
**Example:** "One table per purpose, one writer each. Serves integrity. Rejected: a single shared table, because one hot path would throttle the others. Harder: cross-entity reports need a read model. Revisit when a report query over 1M rows exceeds p95 5 s."

## Building block view

**Good:** every element in the diagram has a responsibility row. Every boundary-crossing arrow has a trust row.
**Failure:** a box in the diagram that no text explains, or a later section that names an element the diagram never showed.

## Runtime view

**Good:** the happy path of each main flow, and at least three failure modes, each with detection, recovery and what the user sees.
**Failure:** only happy paths. Also: "we retry" with no limit and no terminal state.
**Example:** "Downstream timeout: circuit opens after 5 failures in 30 s; requests queue; the user sees 'confirmation delayed'; an alert fires at 10 minutes."

## Cross-cutting concerns

**Good:** one row per concern, linking the standard and stating only deviations.
**Failure:** explaining how OAuth 2 works. Name the standard and link it.

## Deployment, operations and testing

**Good:** topology and failure modes in the document; sizing, runbooks and full test plans linked.
**Failure:** three pages of resource limits that no reviewer will judge.

## Security and compliance

**Good:** the compliance position stated plainly, with every control the design cannot meet alone named, owned and dated.
**Failure:** "Compliant with the security policy." Nothing is compliant until checked.

## Migration and cutover

**Good:** a strategy chosen against alternatives, a rollback with an authoriser and a mechanism, and decommission criteria.
**Failure:** "N/A" for a replacement system. Also: a cutover with no comparison between old and new.

## Risks and open questions

**Good:** blocking questions first, each with what it blocks, how it gets resolved, an owner and a date.
**Failure:** thirty questions with equal weight. Also: an owner written as "TBD".

## Review record

**Good:** everyone asked appears in the log or in the declined list, with the reason they were asked. Every comment has a response: taken, partly or not, with reasons.
**Failure:** editing past comments, or answering them in the body without a response row.
