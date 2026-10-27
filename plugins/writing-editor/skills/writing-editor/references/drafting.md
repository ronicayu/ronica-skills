# Drafting a document

The gated process for a new document: purpose and audience, sources, outline, content. The method is in `SKILL.md` (pass 0) and `pyramid-principle.md`. This file adds the stages.

## Running the stages

- Stages 1 to 3 are a conversation. Ask one question at a time and give your recommended answer with it. A user corrects a wrong recommendation faster than they write an answer from nothing.
- Read the repo instead of asking when the repo can answer.
- Compress stages 1 and 2 into one confirmation when the request already gives purpose, audience and sources. Read them back, ask what is missing, move on. Never compress the approval in stage 3.
- An email runs these stages at small size. Confirm purpose, reader and sources in one message. Show the outline in the reply itself, not in a file: the subject line, the top line, and the supports in order. Write the email only after the user approves that outline. No brief block or `Status:` line is needed unless the email is long.
- Keep state in the target file, not the conversation. The brief block holds the stage 1 and 2 results and a `Status:` line. After compaction, read the file and resume from `Status:`.
- Write a large document in chunks, one section group per write.

## Stage 1: Purpose and audience

This stage is about the reader and the outcome, not the document. Settle these and write them into the brief block.

- **The question.** The one question the document answers, as one sentence ending in a question mark. If you cannot get one, you have a topic, not a document. Dig until you have the question.
- **The readers.** Real roles. "Stakeholders" is not an audience. What they already know decides what you leave out.
- **The change.** What differs after reading: a decision, an approval, a belief, an action. "Informed" is not enough. Informed enough to do what?
- **What the reader is doing.** Use pass 0 of `SKILL.md`. Record the shape it picks.
- **Technical?** For documentation, a README or an RFC, apply the technical bullet of pass 0 now. Pick the Diátaxis mode. For a tutorial, how-to or reference page, the heading forms and shape in `technical-docs.md` override message headings.
- **Scanning or following.** This sets granularity and is separate from shape. A scanning reader needs short paragraphs, visible counts and a heading every few points. A following reader needs *because*, *therefore* and *but*, which exist only in multi-sentence paragraphs. Name which sections are which now. Retrofitting granularity means rewriting.
- **Constraints and house style.** Format, deadline, a `CLAUDE.md`, a style guide, a document template or the convention of neighbouring documents. These override every default here.
- **Size.** Agree a target length now. It sets heading depth. Two pages supports two levels and three or four sections. Twenty pages supports four levels.

The brief block is the first thing in the file. Delete it before handover.

```markdown
<!-- DRAFT BRIEF, delete before handover
Question: Can Wave 1 cut over in October?
Reader: delivery lead, programme director. Know the wave plan, not the gate status.
Outcome: October date approved, or a new date set.
Reader activity: deciding -> ask first, half a page, the risk they sign for
Length: 3 pages, 2 heading levels
House style: repo CLAUDE.md (no hard wrap, mermaid)
Sources: cutover-risk sheet [authoritative]; migration-plan.md [indicative]
Gaps: no rollback rehearsal evidence; gate owner unnamed
Status: OUTLINE — not approved
-->
```

`Status:` is one of `OUTLINE — not approved`, `OUTLINE APPROVED`, `DRAFTING <section>`, `DRAFT COMPLETE`.

## Stage 2: Sources

Sources can be empty. Then say so in the brief, because it limits what stage 4 may assert.

- **Enumerate before reading.** List candidates and have the user confirm, add and cut.
- **Mark each source authoritative or indicative.** Authoritative sources settle facts. Indicative ones suggest and need a cross-check. Honour any confidence levels or corrections file the repo keeps.
- **Note what each source gives:** the claim or number you will draw from it, not a summary.
- **Write down what has no source.** This is the most valuable output of the stage. Each unsupported claim becomes a question for the user or a named gap that stage 4 marks unverified.

Invent nothing, in any stage. No figures, no citations, no attributed positions.

## Stage 3: Outline

Build the pyramid, write it into the target file as a skeleton, then interview the user on it. The mechanics are in `pyramid-principle.md`. Do not re-derive them.

### Build it

1. **Governing thought.** One declarative sentence, not a title or a topic. "Wave 1 can cut over in October" is a governing thought. "Wave 1 cutover readiness" is a filing label. It becomes the H1 or the opening line.
2. **Introduction.** Write it as Situation, Complication, Question, Answer. Pick the order for the reader: standard for a calm reader, direct for urgency, aggressive for a reader short of time or likely to resist.
3. **Supports.** Three to five, each a claim that answers the question the governing thought raises (usually *why?*, sometimes *how?*).
4. **Group type and ordering.** Name them for each group: inductive or deductive, and time, structure or degree. If you cannot name the ordering, there is none.
5. **Recurse** one level at a time, only where the target length supports it. Stop when a message needs no breakdown to be defended.
6. **A source per support**, from stage 2. A support with none carries `GAP:` now.

### Write the skeleton

Write it in the real target file, not a separate outline. Each heading states a message. Under it goes one HTML comment with `msg:` (one point, the intent) and `src:`. A comment under the H1 names the intro order, the group type and the ordering. If a heading and its message differ, the heading is wrong. No prose goes below a heading while `Status` is `OUTLINE — not approved`. Stage 4 turns each message into the section's first sentence, so the approved structure is the one that ships.

Keep each heading short enough to cite in a sentence. If *Section `<heading>`* cannot sit in a sentence, shorten the heading. This matters most where house style forbids section numbers.

```markdown
# Wave 1 can cut over in October, once two gates close

<!-- OUTLINE, expand only when Status says APPROVED. Intro: direct (C-S-Q-A), the reader is worried about the date.
     Body: inductive, 3 supports, ordered by degree (most binding first). -->

## The DCS gate is the binding one, and its owner is unnamed
<!-- msg: this gate decides the date, and no one is working it.
     src: cutover-risk sheet, row 14. GAP: owner unnamed. -->

## Rollback is ruled out, so the gate becomes a rehearsal gate
<!-- msg: with no rollback, the only assurance is a rehearsed forward path.
     src: TNO minutes 2026-08-12. GAP: no rehearsal evidence. -->

## Everything else on the critical path has landed
<!-- msg: the reassuring support, which earns the "can" in the top line.
     src: migration-plan.md, Wave 1 sequencing. -->
```

The skeleton shows the argument before any prose exists. The top line says *can*, hedged by *once*. The first two supports earn the hedge and the third earns the *can*. Both gaps are on the page.

### Interview the user on the structure

Scope it to the outline, not implementation or wording. Work down the tree, one question at a time, with a recommendation. Update the skeleton in the file as each answer lands. When an answer weakens the top line, change the top line. A governing thought narrowed to the evidence beats one propped up by a support that fails. Ask in this order:

1. Does the governing thought follow if every support is true, with nothing left over and nothing missing?
2. Is each group the same kind of thing? Reasons mixed with risks mixed with steps mean the thinking is not done.
3. Is each group MECE, with no overlap and no gap?
4. Does each section answer a question raised above it?
5. Read the headings alone. Do they carry the argument? Does any name a category?
6. Would a reader who stops after the introduction have the answer and the ask?
7. Which supports rest on gaps, and can the document still make its claim with them marked?
8. What did the user leave out because it was inconvenient? Ask directly.

### Gate

Show the skeleton and ask in plain words: *this is the structure. Approved, or what changes?* On approval, set `Status: OUTLINE APPROVED`. Silence is not approval. Neither is the answer to the last question.

## Stage 4: Content

Write section by section in document order, setting `Status: DRAFTING <section>` as you go.

- **Open each section with its skeleton message,** as a sentence. If expanding it needs a fact you lack, stop and ask. Do not improvise.
- **Delete each `<!-- msg: -->` comment as you expand it.**
- **State the conclusion before the reasoning, and name the answer the reader will have thought of.** Where an obvious alternative exists, name it and dispose of it first. Otherwise the reader argues with their own answer and stops listening.
- **A list shows a count. Prose shows a relation.** Use a list when the items are parallel and their number is the point. Use prose when the point is how they differ, because a list asserts they are equivalent. One idea per line makes a document scannable and doubles its length. Do it where the reader scans, not where they follow.
- **Use a diagram** where it carries the content better than prose: interactions, flows, sequences, state. Follow the house format.

Set `Status: DRAFT COMPLETE`. Then run passes 2 to 6 of `SKILL.md` on the draft. You wrote it, so you are its worst reader. Finally, check four things. No `msg:` comment remains. The target length held, or you can say why it moved. The brief block is deleted. The body states the current final state, with no trace of the outline rounds or of earlier wording.

## Failure modes

- **Drafting during stage 3.** Prose in the outline stage means the gate did not hold. When you want to draft, make the outline more specific instead.
- **A governing thought that is a topic.** "X readiness" or "an overview of Z" cannot be wrong, so it cannot be useful.
- **Category headings surviving the interview.** "Background" and "Analysis" look like a document is supposed to look.
- **Skipping sources because the user seems to know it all.** Stage 4 then asserts what nobody can trace.
- **Copying the last document's structure.** The template answers a question this reader may not ask.
- **Nine supports under one heading.** Group them and find the summaries. That is the analytical work.
- **Outline and file drifting apart.** Write each resolved answer into the skeleton at once.
- **Headings that cannot be cited.** Sentence-length headings leave cross-references unphraseable, then wrong.
- **Granularity by habit.** One idea per line costs the connectives. Dense paragraphs lose a scanning reader.
