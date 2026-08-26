# The skeleton format

The outline is written into the real target file, not a separate plan. Headings carry the messages; an HTML comment under each carries the intent and the source. Stage 4 expands each comment into prose and deletes it.

Why in the target file: the outline survives context compaction, the user can edit it directly in their editor, and the messages become the section lead sentences — so nothing is transcribed from plan to document, and the structure the user approved is the structure that ships.

## The brief block

First thing in the file, deleted before handover. This is the skill's memory: if the session is compacted, reading this block restores the stage.

```markdown
<!-- WRITE-DOC BRIEF — delete before handover
Question: Can Wave 1 cut over in October?
Reader: TNO delivery lead, TNR programme director. Know the wave plan; do not know gate status.
Outcome: October date approved, or a new date set.
Reader activity: deciding -> shape: ask first, half a page, risk they are signing for
Length: 3 pages, 2 heading levels
House style: tn5-architecture/CLAUDE.md (no hard wrap, mermaid, no section symbol)
Sources: cutover-risk sheet [authoritative]; data-migration-plan.md [indicative]; TNO minutes 2026-08-12 [authoritative]
Gaps: no rollback rehearsal evidence; DCS gate owner unnamed
Status: OUTLINE — not approved
-->
```

`Status:` takes one of `OUTLINE — not approved`, `OUTLINE APPROVED`, `DRAFTING <section>`, or `DRAFT COMPLETE`.

## The skeleton

The H1 is the governing thought as a declarative sentence. Each group of sections carries a comment naming its group type and ordering — the two things a reviewer cannot check without being told, and the two the writer most often has not decided.

```markdown
# Wave 1 can cut over in October, once two gates close

<!-- OUTLINE — expand only when Status says APPROVED.
     Intro: direct (C-S-Q-A) — the reader is already worried about the date.
     Body group: inductive, 3 supports, ordered by degree (most binding first). -->

## Two gates stand between today and an October cutover
<!-- msg: the complication, stated as the ask. Names both gates, no detail on either.
     src: TNO minutes 2026-08-12 -->

## The DCS gate is the binding one, and its owner is unnamed
<!-- msg: this gate decides the date; it has no owner, so it cannot be worked.
     src: cutover-risk sheet, row 14. GAP: owner unnamed — mark unverified. -->

## Rollback is ruled out, so the reversibility gate becomes a rehearsal gate
<!-- msg: with no rollback, the only assurance left is a rehearsed forward path.
     src: TNO decision, minutes 2026-08-12. GAP: no rehearsal evidence exists. -->

## Everything else on the critical path has landed
<!-- msg: the reassuring support — earns the "can" in the top line.
     src: data-migration-plan.md, Wave 1 sequencing -->

## What we are asking for
<!-- msg: name the DCS gate owner by 5 Sept; book the rehearsal for week of 15 Sept. -->
```

Note what the skeleton makes visible before a word of prose exists: the top line says *can*, hedged by *once*, and the third support is what earns the hedge. The two gaps are on the page. A reviewer can attack the argument here, in five minutes, instead of after three pages are written.

## Expanding a section

The message becomes the first sentence. The comment goes.

Skeleton:

```markdown
## The DCS gate is the binding one, and its owner is unnamed
<!-- msg: this gate decides the date; it has no owner, so it cannot be worked.
     src: cutover-risk sheet, row 14. GAP: owner unnamed — mark unverified. -->
```

Expanded:

```markdown
## The DCS gate is the binding one, and its owner is unnamed

Of the two open gates, the Declaration Control Service (DCS) gate is the one that sets the date: the other can close in parallel with cutover preparation, and this one cannot. It has no named owner, which means no one is currently working it.

The cutover risk register records the gate but leaves the owner field empty (cutover-risk sheet, row 14) — unverified, and the fastest thing on this page to settle. Naming an owner does not close the gate, but nothing closes it until someone is named.
```

The message survived as the opening sentence, the gap is marked rather than papered over, and the section answers only the question its heading raises.

## Rules

- One `msg:` comment per heading, one point per message. Two points means two sections.
- A heading states a message, never a category. If the heading and the message differ, the heading is the one that is wrong.
- Sources go in the comment during stage 3, in the prose during stage 4. A support with no source carries `GAP:`.
- Nest only as deep as the target length supports. Three pages is two levels.
- No prose below a heading while `Status` is `OUTLINE`. The skeleton is headings and comments only.
