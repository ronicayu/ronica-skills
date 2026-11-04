---
name: writing-editor
description: "Write, review and edit prose as an expert editor: structure by Barbara Minto's Pyramid Principle, then reader load, sourcing, line quality and machine-drafted tells; technical docs, PRs and commits also get Diátaxis, Google style, STE and Global English. Use whenever the user asks to write or draft a report, proposal, memo, brief, email or other document, even if they only say 'write the report': drafting runs through gated stages (purpose, sources, an approved outline, then content). Also use to review, edit, proofread, tighten or critique any text, including text you drafted."
---

# Writing Editor

Work in the order a good editor works: the shape of the argument, then what the reader has to hold and trust, then paragraphs, then sentences, then words. Polishing a sentence in the wrong section is wasted work, because the fix to the structure deletes it.

## The reader is a person

A person reads unevenly, in a hurry, holding only a few things at once. A draft can be accurate and complete and still fail. Four tests run through every pass. Could the reader stop a third of the way in and still have the point? Could they follow the argument without scrolling back? Could they tell what is proven from what is proposed? Could they act without asking what was meant?

Depth on structure, order and openings is in `references/pyramid-principle.md`.

## Pick a mode before touching anything

- **Review**: the user wants feedback, comments or a critique. Report findings. Leave the text alone.
- **Rewrite**: the user wants it edited, tightened, fixed or simplified. Change the text, then say what changed and why. If the fix would move or delete sections, stop before any line edit. Report the structural finding and offer a rebuild through `references/drafting.md`, from the outline gate. Tightening a wrong structure makes it harder to rebuild.
- **Draft**: the user is writing something new. See Draft mode.

If the request is ambiguous, ask when the text is long. Otherwise review text the user wrote (their voice is theirs to keep) and rewrite text you wrote. Anything you drafted gets a rewrite pass before you hand it over.

## Draft mode

- **A very casual message** (a quick reply, a chat message, an informal note): write it, then run the editing passes on it.
- **Any other email:** the stages at small size, without opening `references/drafting.md`. Confirm purpose, reader and sources in one message. Show the outline in the reply: the subject line, the governing thought, and the supports in order. Write the email only after the user approves that outline.
- **A document** (report, design doc, ADR, assessment, proposal, memo, brief, spec, anything over about a page, or an existing draft that needs rebuilding from its structure up): read `references/drafting.md` and follow it.
- **The gate, for everything except a very casual message:** write no body prose until the user approves the outline. A request to "write the report" asks for the stages, not for a skipped outline. In a non-interactive session, ask the first questions and stop. If the user explicitly says to skip the outline, say once what it costs ("the structure gets decided in the drafting, and rework lands on you"), then comply.
- A file that opens with a `DRAFT BRIEF` block is a draft in progress. Read `references/drafting.md` and resume from its `Draft stage:` line.

## The passes

### 0. Read it whole, and name the job

Read the entire piece before changing a word. A local fix made blind to the ending is usually wrong. Then answer, in one short block at the top of your reply:

- **Who reads this, and what do they already know?**
- **What should happen after they read it?** A decision, an approval, a change of belief, an action.
- **What question is this document the answer to?** If you cannot state it in one sentence, that is the first finding and the biggest.
- **What is the reader doing while they read?** This selects the shape:
  - **Approving or deciding**: the ask, what they accept, what they own afterwards, the risk they sign for. Answer first and short. They read the first half page.
  - **Implementing**: precision, edge cases, enough to work from without coming back. Answer first, then depth in the order the work happens.
  - **Evaluating a design**: the problem, the ranked goals and the trade-offs between them, the options, then the design, so they reach the conclusion themselves. Each key decision sits where it shapes the design and names the alternative it rejected. This is the answer-first exception in `references/pyramid-principle.md`, which also gives the shape for an architecture presented for review.
  - **Auditing or assuring**: traceability. Which requirement, control and evidence, and what is not yet proven.
  - **Orienting**: a map before any detail. The parts, how they connect, where to go next.

When one document serves two of these, write the body for the primary reader and give the other their own section. Classify by what the reader does while reading, not by the meeting the document goes to. A design sent to a review is read by evaluators, not approvers.

- **Does a template set the shape?** If the document follows a template, check it against the template in pass 1. Flag template sections that do not fit the subject. Do not fill them with placeholders.
- **How long may it be?** Set a length from the reader's job above. A piece far over that length carries more than one document. So does a piece that needs a reading guide or an ID key before the reader can start.

- **Is the text technical?** For documentation, a README, a design document, an RFC, a PR description, a commit message or an issue, read `references/technical-docs.md` now. It says which of its rules apply and in which pass.

### 1. Structure

- **Answer early.** The opening gives the recommendation, finding or main claim, not a tour of the background.
- **Message headings.** Headings state a message, not a category ("Background", "Next Steps"). Read alone, they carry the argument; with the title and opening, they give the answer and the ask. Keep each heading short enough to cite in a sentence, about eight words. The section's first sentence carries the rest.
- **Vertical logic.** Each section answers the question its parent raises, and nothing else.
- **Horizontal logic: MECE.** The items in a group are the same kind of thing and do not overlap. A group that claims to cover the whole leaves nothing out; a list of examples says "such as", and a partial list names its scope. If one case, or one piece of evidence, fits two items, they overlap.
- **Ordering.** By time, structure or degree, chosen on purpose. The chronology of the investigation is almost never the right order for the finding.
- **The sum holds.** If every support is true, the governing thought follows. For a claim the document depends on, ask what could still make it false: the answer is a missing support, an unstated assumption, or a claim that overreaches.
- **Current final state.** The body states what is true now. It holds no review-round history, agent actions, intermediate corrections, prior counts, superseded wording, or account of how the document evolved, including which draft, run, agent or input each idea came from. Text whose job is the change (changelog, release notes, PR description, commit message, decision log, an ADR's status or history section) is exempt. History that must stay goes in its own section or a linked record.

Fix this layer first. In review mode, say plainly that the structure needs reshaping before you give line notes.

### 2. Load: what the reader has to hold

The reader learns each name and fact once:

- **Nothing is used before it is defined.**
- **Expand every domain abbreviation on first use:** *Full Term (ABBR)*, then the abbreviation alone. Industry-universal terms are exempt. If it would belong in a glossary, expand it.
- **One name per concept**, in the document and its neighbours. A synonym for variety reads as a second thing.
- **Each fact is stated once, and the copies agree.** Elsewhere, point to it instead of restating it. Where a summary, table, glossary or log repeats the body, check counts, lists, statuses and scopes against the body. Copies drift apart, and a line edit does not see it. A percentage keeps one base wherever it appears, so a share of requests never turns into a share of users.
- **Identifiers stay out of the argument.** Requirement, story, control and ticket IDs go in tables and traceability sections. An argued sentence carries at most one. If a sentence cannot be understood without a lookup, rewrite it in words.

Everything sits where the reader needs it, in groups they can hold:

- **A section reads completely without the sections below or after it.** Where it depends on one, state the result once and point to the detail: "Rollback is ruled out; section 5 gives the test that failed." "See section 5" alone makes the reader carry an open question. Drop a pointer the reader needs nothing from.
- **Groups stay at five or fewer.** Nine items are nine things to hold. Two groups of four with named summaries are two.
- **Detail goes where the question arises**, not where it was discovered. Test each inline detail: does it answer a question the reader already had, or open a new one? A detail that opens a question the section never answers fails, even in a sentence at the right level. Parentheticals and inline expansions fail this most often, because they look like clarifications. Cut the detail to the named concept, or keep the name and point to where it is defined.
- **An idea the reader must carry gets one concrete case where it first appears.** A term or a claim the rest of the document builds on is easier to hold once the reader has seen one instance, such as a real input or a measured number. Where none exists, name the gap; do not supply one. Cut extra examples, never the only one.

### 3. Claims: what the reader has to trust

- **Load-bearing claims show their source** (a document, a person, a measurement, a run), in line and brief. A source supports a claim. The draft or agent that first proposed an idea is not a source. Tag claims, not sections.
- **Uncertainty is marked, with what would settle it.** "Unverified: no one has run the rollback end to end." A hedge that only lowers the temperature does not count.
- **Decided is distinguishable from proposed.**
- **Numbers carry a basis:** measured, estimated or assumed, and as of when.

Where a claim lacks support, name the gap. Do not supply the support.

### 4. Paragraphs

- One point per paragraph, stated in its first sentence, then supported.
- Cut paragraphs that restate a neighbour. Duplicates drift apart.
- Split what is dense. Fold what is thin into the point it serves.
- Check the seams. Does each paragraph follow from the one before?

### 5. Sentences and words

Open `references/line-editing-checklist.md` now and work through its sections in order. The order is clarity, concision, sentence structure, flow, language, audience.

### 6. Strip the tells of machine-drafted prose

Run this last, and without exception on anything you drafted. Open the *Tells of machine-drafted prose* section of the checklist now, check the five most common, then scan the rest. On text the user wrote, report a tell only as a pattern of three or more, and voice wins over tells 21 and 24.

## Reporting a review

Every finding has three parts: quote the text, name the problem in one line, give the replacement.

> **"It should be noted that the migration will need to be completed prior to Wave 2."**
> Throat-clearing, and *prior to* for *before*.
> → "The migration must finish before Wave 2."

Order findings by cost to the reader: structure, then ambiguity, then bloat, then rhythm and polish. Lead with the two or three that help most. Name a recurring pattern once, with examples and a count, not forty entries. If the draft is good, say so and give only what would still help.

## Restraint

- **Preserve voice.** Distinctive phrasing that works is not an error. Edit for comprehension, not toward a house average. For technical text, `references/technical-docs.md` takes precedence over voice.
- **Cut repetition before meaning.** Compress in this order: duplication, long-windedness, examples (never the only one; see pass 2), explanation. Flag any loss of content.
- **Do not bullet by reflex.** Bullets lose *because*, *therefore* and *but*. Use them for parallel items and prose for an argument. A table needs two or more comparable columns.
- **Invent nothing.** Editing adds no facts, figures, citations or claims.
- **Keep the doc's own terms.** Renaming a concept mid-edit splits it.
- **House style wins.** A project `CLAUDE.md`, style guide or established convention overrides these defaults. Check for one first.
- **Preserve the technical content.** Never trade accuracy for a shorter sentence. Find a shorter accurate one.
