# Spec: architecture-design plugin 0.1.0

**Status:** Approved by the owner on 2026-10-27.

## 1. Summary

A new plugin, `architecture-design`, with one skill. It drafts and reviews architecture design documents that go to a design review. It owns the content: problem, ranked goals, trade-offs, options, the design, failure modes, migration, decisions, risks and open questions. It does not own the prose. Finished text goes through the `writing-editor` skill.

It closes the gap that a rewrite of a real architecture document exposed: decisions stated without the alternative they rejected, unranked goals, design-shaping requirements left unclear, and facts that drift between sections. `writing-editor` 2.1.0 knows the order of a design document, but it cannot tell whether a failure mode or a trade-off is missing.

User-visible changes:

- `/architecture-design` in two modes: **draft** a design document, or **review** one.
- A generalised architecture template, used when the project has none.
- A reviewer checklist that review mode runs and draft mode runs before handover.

## 2. Files

```
plugins/architecture-design/
├── .claude-plugin/plugin.json          version 0.1.0
└── skills/architecture-design/
    ├── SKILL.md                        ≤ 110 lines
    └── references/
        ├── template.md                 ≤ 400 lines: the generalised design document template
        ├── adr-template.md             ≤ 90 lines: the ADR form
        ├── section-guide.md            ≤ 150 lines: how to fill each section well
        └── review-checklist.md         ≤ 80 lines: the checks, grouped by severity
```

Also: an entry in `.claude-plugin/marketplace.json`, a row and install line in the root `README.md`. No scripts and no hooks.

## 3. SKILL.md

Frontmatter `description`: drafts and reviews architecture design documents for a design review, checking problem, ranked goals, trade-offs, options, failure modes, migration and decisions; prose is handed to `writing-editor`. Model-invocable.

Sections, in order:

1. **What this skill owns.** Content and completeness. It does not restate any `writing-editor` rule. It points to `writing-editor` for the drafting gate (`references/drafting.md`) and for the prose passes.
2. **Pick the template.** Search the repository first: `docs/**/templates/*architecture*`, `templates/*design*`, `**/adr/`, a `CLAUDE.md` pointer. Ask the user if more than one matches. A project template wins. Otherwise use `references/template.md`. Pick the variant: **system** (several contexts or services) or **module** (one part of a larger system).
3. **Find prior decisions.** Search the repository for earlier ADRs and design documents on the same system, and list them as sources. If a knowledge-base connector is available, search it too.
4. **Draft mode.** Follow `writing-editor`'s `references/drafting.md` stages and its outline gate, with these additions:
   - **Stage 1 interview**, one question at a time with a recommended answer, in this order: functional requirements; non-functional requirements; constraints (team size, skills, timeline, budget, mandated technology); the quality goals, ranked; the options the user already has in mind, named even if they lean one way; assumptions nobody has confirmed.
   - **Stage 3 outline** is the template's section list with one `msg:` line per section. Template sections that do not fit the subject are proposed for removal, with one line of reason. They are not kept as placeholders.
   - **Before handover**, run `references/review-checklist.md` on the draft and fix what it finds. Then run `writing-editor` passes 2 to 6.
5. **Review mode.** Run `references/review-checklist.md`. Report findings in three groups: **blocks the review**, **weakens the design case**, **polish**. Each finding quotes or points to the text, names the gap in one line, and says what would close it. Invent no design content: where a rejected alternative or a failure mode is missing, name the gap; do not supply one. Then offer a `writing-editor` review of the prose.
6. **Key decisions.** A key decision is written in the section it shapes, with the fields in section 5 of this spec. The "Decisions inside this design" table is an index: one row and a section link per decision, never a restatement.
7. **Split out an ADR** when a decision is contested, hard to reverse, or shared with other teams. Write it with `references/adr-template.md`. The design document keeps one line and the link.

## 4. references/template.md

An RFC frame around an architecture body. The frame (summary, problem and outcomes, options, decisions, review record) comes from the owner's RFC template. The body comes from the owner's module architecture template. It carries no organisation-specific names, paths or programmes. Section order follows `writing-editor`'s design-review shape in `references/pyramid-principle.md`.

**Depth rule.** The document holds the design at the level a reviewer needs in order to review it. Each section is marked in its HTML comment as **core** (always in the document) or **build detail** (may live in a companion document, linked from a one-line summary). Build detail: resource sizing, runbooks, the full data mapping, the full API and message specifications, Level 2 component diagrams beyond the first, and the per-boundary trust tables beyond a summary.

Header: Title (states the design's main idea), Status (Draft, Proposed, Accepted, Superseded), Scope (system or module), Owner (name, team), Date opened, Review window closes, Last updated, Related ADRs and RFCs, Migration mode (replacement or greenfield), Owned data domains.

Body:

1. **Summary** (core). Three to five sentences: what the system is, its main design idea, and what the review must do.
2. **Context** (core). Who uses it and its boundary. System context diagram (Mermaid C4). Main business flows. Workload and traffic, each number with its source.
3. **Problem, outcomes and goals** (core). Problem statement (≤ 5 sentences, no solution). **Outcomes**: what will be better, each with how it will be measured. Ranked quality goals, each with why and what it drives. Trade-offs: the goal that wins, the goal that loses, the compromise, and the decision it traces to. Non-goals. Measurable NFRs as quality scenarios, each with a status: Committed, Provisional (who confirms, by when) or Blocking (also an open question). Constraints: technical, business and regulatory. **Assumptions**: what the design takes as true that nobody has confirmed, each with who can confirm it.
4. **Fundamental options** (core). The few top-level shapes considered, **including doing nothing** where that is possible. A comparison table with one column per ranked goal, plus complexity, cost and team familiarity. The choice, and why.
5. **Building block view** (core; Level 2 is build detail). Level 1: contexts or containers. A responsibility entry for every element in the diagram: what it does, the data it owns, its outbound calls, the transactions it holds. Trust boundaries: one entry per boundary-crossing arrow (auth, identity propagation, encryption, input validation, audit, rate limiting). Level 2 only for containers that own durable state, an external protocol or a cross-team contract.
6. **Runtime view** (core). The happy path, plus at least three failure modes, each with detection, recovery and user-visible impact. The failure list covers both kinds of runtime: store unreachable; downstream timeout against permanent failure; partial commit or orphaned write; message lag or redelivery; resource exhaustion (pools, concurrency limits, throttling or quota).
7. **Cross-cutting concerns** (core). One table: concern, approach, standard it conforms to (or "no standard yet"), where it is described. The concerns: authentication, authorisation, error handling, transactions, idempotency, caching, versioning, resilience, async work, rate limits, observability, audit, secrets, time.
8. **Data model** (core: logical model and ownership; build detail: indexes, partitioning). Logical model, storage decisions, reference data.
9. **API and message contracts** (core: groups and guarantees; build detail: the full specification). Sync endpoints by group; async contracts with direction, payload, idempotency key and delivery guarantee.
10. **Deployment** (core: topology and failure modes; build detail: sizing). A diagram, then one of two variants: **containers** (resources, replicas, scaling trigger, health checks) or **serverless** (concurrency limits per function group, queues, quotas, account or environment topology). Then for both: shared-platform failure modes, network and access, config and secrets, backup and DR.
11. **Security and compliance** (core). Data classification, encryption, the compliance regime and the position against it, with every control the design cannot meet alone named as blocking, with an owner.
12. **Operations** (build detail). Dashboards, alerts, on-call, top failure scenarios with runbooks.
13. **Testing** (core: architecture tests and their thresholds; build detail: the rest). Unit, integration, end to end, architecture tests (fitness functions), performance, security verification.
14. **Migration and cutover** (mandatory; core: strategy, rollback, decommission criteria; build detail: the data mapping). Strategy, traffic shifting, environment sequencing, dual-run and comparison, rollback, communications, decommission criteria; data migration source, target, mapping, approach, reconciliation, dry run, archival. A greenfield design replaces it with one paragraph that shows there is no predecessor and no data to move.
15. **Decisions inside this design** (core). One table: Decision, Section, ADR, Status. Each row points to where the decision is argued. It is an index, never a restatement.
16. **Risks and open questions** (core). Blocking questions first. Each with impact, resolution path, owner and date. Risks with likelihood × impact.
17. **Review** (core). The review record from the owner's RFC template:
    - **Affected parties and experts**: who has been asked to review, and why each.
    - **Review log**: ID, Reviewer, Team or role, Date, Review comment and reasoning, Source (conversation, comment, forum). Entries are added, never edited. One entry per comment.
    - **Declined or no response**: Person, Date asked, Outcome.
    - **Response to review**: Review ID, Taken (Yes, Partly, No), Response and reasons.
    - **Review asks**: what the review must decide, accept or assign.

Appendices: A glossary, B traceability (requirements, controls), C reviewer checklist sign-off.

The review record and the decision table are history sections. `writing-editor`'s current-final-state rule exempts them.

Every section carries a one-line HTML comment saying what it must contain and whether it is core or build detail. The comments are deleted before handover, like `writing-editor`'s `msg:` lines.

### The ADR form

The owner's ADR template, with four changes. It lives in its own file, `references/adr-template.md`.

```
# ADR-NNNN Title written as the decision

- Status: Draft | Proposed | Accepted | Rejected | Withdrawn | Superseded
- Decision owner: Name, team
- Date proposed / Review window closes / Date accepted
- Supersedes / superseded by: links
- Related: RFCs, design documents, spikes, other ADRs, code

## Context        forces and constraints: cost, skills, deadlines, other teams
## Criteria       ranked; what matters most in choosing          (moved before Options)
## Options considered
   One table: option × criterion, then benefits and costs per option.
   Include "Do nothing" where that is possible.                    (added)
## Decision       "We will ..." in one to three sentences
## Consequences   Good; Harder (merged from "Bad" and "What becomes harder");
                  Revisit when: the measurable condition that reopens it   (added)
## Review         reviewers asked and why; review log (append-only, with Source);
                  declined or no response
## Response to review
```

The four changes: Criteria come before Options and are ranked, so the options are judged against them instead of justified after the choice. "Do nothing" is an option where possible. "Revisit when" replaces the optional review date, and "Bad" merges into "Harder". Status adds Rejected and Withdrawn, so decisions not taken stay on record.

## 5. Key decision fields

Each key decision, in the section it shapes:

- **Decision** and **status**: Proposed, Accepted, Rejected, Withdrawn or Superseded (by which decision), the same values as the ADR form.
- **Serves**: the ranked goal it protects.
- **Alternative rejected**, and why.
- **Easier**: what the decision makes easier.
- **Harder**: what it costs.
- **Revisit when**: the measurable trigger that reopens it ("segment count p95 over 5 s at 1M contacts").
- **ADR**: a link, or none. Each decision also gets one row in the "Decisions inside this design" table.

## 6. references/section-guide.md

For each template section: what "good" looks like in two or three lines, the most common failure, and one short example. It includes:

- A goal that changes no decision is not a goal.
- "We balance X and Y" is not a trade-off.
- A Provisional NFR that is design-shaping is Blocking.
- Name a standard and link it; describe only the deviation (the owner's "reference standards, don't restate them" rule).
- In diagrams, use role names unless the technology is the decision.
- Diagrams in Mermaid; split a diagram that does not fit one screen.

## 7. references/review-checklist.md

**Blocks the review**

- The problem statement names no solution.
- Every outcome has a measure.
- Goals are ranked.
- The fundamental options include doing nothing, or say why it is not possible.
- Every review log entry has a response. Everyone asked appears in the log or in the declined list.
- Every Blocking NFR is also an open question with an owner and a date.
- Every key decision names the alternative it rejected.
- Migration and cutover are present, or greenfield is shown.
- At least three failure modes, each with detection, recovery and impact.
- Security and compliance: every control the design cannot meet alone has an owner.

**Weakens the design case**

- Every trade-off names the losing goal and traces to a decision.
- Every key decision has a revisit trigger, and easier and harder consequences.
- The options comparison uses the ranked goals as columns.
- Every element in a diagram has a responsibility entry. No element appears in a later section before the building block view introduces it.
- Every workload number and NFR names its source and its workload assumption.
- Assumptions are listed, each with who can confirm it.
- The decision table, summary and glossary agree with the body (counts, statuses, scopes, names).
- Build detail is linked from a one-line summary, not inlined.
- Every ADR lists its criteria before its options and has a "Revisit when".

**Changes made during the build:**

- The ADR form is in its own file, `references/adr-template.md` (owner's request), at 81 lines.
- Stage 1 adds a question on outcomes (what will be better, and how it is measured), because the template has an Outcomes table. The questions follow writing-editor's own stage 1 items, and any the request or repository answers are skipped.
- When an ADR is split out, the design document keeps the decision's fields in short form, not only one line, so the section still reads without the ADR.
- Draft mode adds a stop after Fundamental options: the user agrees the high-level choice before the design sections are written.
- Key decision status adds Draft.

**Added after approval (owner's layering rules, 2026-10-27):**

- Blocks the review: the summary and context name no class, table, queue, field, state or ID; a load-bearing low-level fact is a named constraint with a pointer.
- Weakens the design case: every design element traces to a requirement, goal, NFR or constraint; requirements say what and why, never how; every quality claim has a number, a mechanism or a pointer, or is cut; sections follow the design's dependencies and descend one level at a time.
- The owner's rule "every decision goes in an ADR" was weighed against this spec. The owner kept this spec's rule: decisions live in the section they shape, and an ADR is split out only when a decision is contested, hard to reverse or shared.

**Polish**: hand to `writing-editor`.

## 8. Done when

- `bash scripts/validate.sh`, `claude plugin validate .` and `claude plugin validate plugins/architecture-design` pass. `git diff --check` is clean.
- `git grep` finds no organisation-specific name or path from the source template in the plugin.
- Line budgets in section 2 hold.
- A manual review-mode run on a real architecture document finds at least: decisions without a rejected alternative, unranked goals, design-shaping requirements not marked Blocking, and drift between the decision table and the body. The document is not committed.
- A manual draft-mode run on a small invented system stops at the outline gate and asks the stage 1 questions in order.

## 9. Owner decisions

1. **Publishing the templates.** Templates derived from the owner's work templates (module architecture, RFC, ADR) go into this public repository only after the generalisation removes every organisation-specific name, path and programme.
2. **Name:** `architecture-design`.
3. **Dependency on `writing-editor`:** soft. SKILL.md and the README say it works best with `writing-editor` installed. Without it, draft mode uses the stage list in SKILL.md and skips the prose passes.
4. **Taskgraph filing:** no. The skill does not file tasks.
5. **Who builds it:** Opus implements; Fable reviews the diff and the two manual checks in section 8.

## 10. 0.2.0: design critique

The owner found that review mode checked only completeness, not the design's substance. 0.2.0 adds `references/design-critique.md`, a fixed procedure run before the completeness checklist:

- **Step 0, right problem.** If the design solves the wrong problem (a contradiction with a source), the review stops and asks the user. If the problem is unclear but plausible, it states the assumed problem, asks the user to confirm it, and continues.
- **Steps 1 to 6:** trace each goal to its mechanism (a table with a verdict per row, arithmetic checked), contradictions, structure, failure behaviour, decisions, and whether the team can deliver and run it.
- Every finding names its breaking scenario, is marked verified or suspected, and is rated design fails or risky.
- The reviewer may raise risks and alternatives as labelled challenges, never as the document's facts.
- Draft mode runs the critique on its own design before handover.
- Security is out of scope (owner's decision): it has its own review.

Done when, for 0.2.0: a headless review of a real design excerpt produces the goal trace table and substance findings from the procedure; a headless review of a design that solves the wrong problem stops at step 0 and asks.
