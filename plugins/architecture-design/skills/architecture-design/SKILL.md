---
name: architecture-design
description: "Draft and review architecture design documents and ADRs that go to a design review. Critiques the design itself (is it solving the right problem, does each mechanism meet its goal, contradictions, structure, failure behaviour, decisions, whether the team can run it) and checks the content a prose editor cannot: problem and measurable outcomes, ranked quality goals, trade-offs that name the losing goal, options including doing nothing, decisions with the alternative they rejected, failure modes, migration, blocking requirements, and the review record. Use to write a system or module architecture document, an RFC or an ADR, or to review one before a design review. Works best with the writing-editor skill, which handles the prose."
---

# Architecture Design

This skill owns the content of an architecture document: whether the design is right, and whether it is complete and argued well enough to review. It does not own the prose. For the prose, use the `writing-editor` skill when it is installed. This skill does not restate writing-editor's rules, except the few under Restraint that must hold without it.

The reader of an architecture document is evaluating a design. They must be able to test each choice against what it has to achieve. So the document shows the problem, the ranked goals and the options before it argues for the design, and every key decision names what it rejected.

## Pick the mode

- **Draft**: the user is writing a new design document, RFC or ADR, or rebuilding one from its structure up.
- **Review**: the user wants a critique of an existing one. Report findings. Change nothing.

If the request is ambiguous, ask.

## Pick the template

1. **Search the repository first.** Look for an architecture, design, RFC or ADR template: `**/templates/*.md`, `docs/**/*template*`, `**/adr/**`, and any pointer in a `CLAUDE.md`. If more than one matches, ask which. A project template always wins.
2. **Otherwise use the bundled templates.** `references/template.md` for a design document or RFC, `references/adr-template.md` for an ADR.
3. **Pick the scope.** **System**: several contexts or services. **Module**: one part of a larger system. The template marks where they differ.

## Find what was decided before

Search the repository for earlier ADRs, RFCs and design documents on the same system. List them as sources. A new design that contradicts an accepted ADR must say so and supersede it. If a knowledge-base connector is available, search it too.

## Draft mode

**The gate comes first.** Your first reply in draft mode asks the stage 1 questions. It is never a document, an outline or a design. Write no body prose until the user approves the outline. A request to "write the design doc" asks for the stages, not for a skipped outline. If the user explicitly says to skip the outline, say once what it costs, then comply. This holds in a non-interactive session too: ask, then stop.

**Stages.** Before anything else, if the `writing-editor` skill is in your skill list, invoke it and follow its Draft mode (its `references/drafting.md` stages and outline gate), with the additions below. Without it, run the same four stages: purpose and readers, sources, an outline the user approves, then content.

**Stage 1 interview.** Ask these after writing-editor's own stage 1 items. One question at a time, each with your recommended answer. Skip any that the request or the repository already answers, and read that answer back instead. In this order:

1. Functional requirements: what the system must do.
2. Non-functional requirements: scale, latency, availability, cost, retention, compliance.
3. Constraints: team size and skills, timeline, budget, mandated technology, other teams.
4. The quality goals, ranked. The ranking is the tie-breaker for every trade-off.
5. The outcomes: what will be better, and how it will be measured.
6. The options the user already has in mind. Ask them to name each one, even if they lean one way.
7. Assumptions nobody has confirmed, and who could confirm each.

**Stage 3 outline.** Use the template's section list, with one message line under each heading. Propose removing template sections that do not fit the subject, with one line of reason. Do not keep them as placeholders. Mark each section core or build detail (see the depth rule in `references/template.md`). The template's section names stand, because a template sets the section names. The message goes in the comment under each heading and becomes the section's first sentence.

**Stage 4 content.** Write each section to the bar in `references/section-guide.md`. The layering items in `references/review-checklist.md` apply while drafting. After Fundamental options, stop and get the user to agree the choice before writing the design sections.

**Before handover.** Run `references/design-critique.md` on the draft. Fix what it finds, or bring a finding to the user when the fix changes a decision they agreed. A challenge that proposes a new option goes to the user, not into the draft. Then run `references/review-checklist.md` and fix what it finds. Then, if `writing-editor` is installed, invoke it and run its passes 2 to 6.

## Review mode

Two lenses, substance first. Substance is whether the design is right; completeness is whether the document lets reviewers judge it.

1. Read the whole document and its sources. Identify the template it follows, or should follow.
2. **Substance.** Run `references/design-critique.md`, steps 0 to 6, in order. Step 0 asks whether the design solves the right problem. If it does not, stop there: report the evidence and ask the user to confirm the problem. Run nothing else.
3. **Completeness.** Run `references/review-checklist.md`. Report its findings in two groups:
   - **Blocks the review**: the reviewers cannot judge the design until this is fixed.
   - **Weakens the design case**: the design can be judged, but a reviewer will challenge this.
4. Report in the order `references/design-critique.md` gives.
5. Each finding quotes or points to the text, names the problem in one line, and says what would close it.
6. Offer a `writing-editor` review of the prose, if it is installed.

## Key decisions

A key decision is written in the section it shapes, not in a separate list. It has these fields:

- **Decision** and **status**: Draft, Proposed, Accepted, Rejected, Withdrawn or Superseded (by which decision).
- **Serves**: the ranked goal it protects.
- **Alternative rejected**, and why.
- **Easier**: what the decision makes easier.
- **Harder**: what it costs.
- **Revisit when**: the measurable condition that reopens it. A date is not a condition.
- **ADR**: a link, or none.

The "Decisions inside this design" table is an index: one row and a section link per decision. It never restates the reasoning. Where it repeats a status or a name, it must match the body.

## Split out an ADR

Write a separate ADR when a decision is contested, hard to reverse, or shared with other teams. Use `references/adr-template.md`, or the project's own. The design document keeps the decision's fields in short form and links the ADR.

## Restraint

- **Invent nothing in the document.** No figures, owners, failure modes or alternatives the sources do not give. Mark gaps as gaps. In a review you may raise risks, alternatives and simpler designs, labelled as your challenge; never present them as the document's facts.
- **Keep the project's terms and template.** House style wins over this skill's defaults.
- **Depth to review, not to build.** Build detail goes in companion documents, linked from a one-line summary.
- **History stays in its sections.** The review record and the decisions table are history by design. The rest of the body states the current design.
