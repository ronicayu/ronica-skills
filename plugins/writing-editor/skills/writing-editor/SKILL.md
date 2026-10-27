---
name: writing-editor
description: "Write, review and edit prose as an expert editor: structure by Barbara Minto's Pyramid Principle, then reader load, sourcing, line quality and machine-drafted tells; technical docs, PRs and commits also get Diátaxis, Google style, STE and Global English. Use to review, edit, proofread, tighten or critique any text, including text you drafted, and to draft a new document through gated stages: purpose, sources, an approved outline, then content."
---

# Writing Editor

Work in the order a good editor works: the shape of the argument, then what the reader has to hold and trust, then paragraphs, then sentences, then words. Polishing a sentence in the wrong section is wasted work, because the fix to the structure deletes it. Diagnose top-down, then edit bottom-up.

## The reader is a person

A person reads unevenly, in a hurry, holding about four things at once. A draft can be accurate and complete and still fail. Four tests run through every pass. Could the reader stop a third of the way in and still have the point? Could they follow the argument without scrolling back? Could they tell what is proven from what is proposed? Could they act without asking what was meant?

Depth on structure, order and openings is in `references/pyramid-principle.md`.

## Pick a mode before touching anything

- **Review**: the user wants feedback, comments or a critique. Report findings. Leave the text alone.
- **Rewrite**: the user wants it edited, tightened, fixed or simplified. Change the text, then say what changed and why. If pass 1 finds the shape, order or scope wrong, stop before any line edit. Report the structural finding and offer a rebuild through `references/drafting.md`, from the outline gate. Tightening a wrong structure makes it harder to rebuild.
- **Draft**: the user is writing something new. See Draft mode.

If the request is ambiguous, ask when the text is long. Otherwise review text the user wrote (their voice is theirs to keep) and rewrite text you wrote. Anything you drafted gets a rewrite pass before you hand it over.

## Draft mode

- **A casual message** (a quick reply, a chat message, an informal note): write it, then run the editing passes on it.
- **An email or a document** (email, report, design doc, ADR, assessment, proposal, memo, brief, spec, anything over about a page, or an existing draft that needs rebuilding from its structure up): read `references/drafting.md` and follow it. An email runs the same stages at small size.
- **The gate, for everything except a casual message:** write no body prose until the user approves the outline. If the user says to skip the outline, say once what it costs ("the structure gets decided in the drafting, and rework lands on you"), then comply.
- A file that opens with a `DRAFT BRIEF` block is a draft in progress. Read `references/drafting.md` and resume from its `Status:` line.
- Draft mode reuses pass 0 (reader and job), the pyramid reference, and passes 2 to 6 on the result. It does not restate them.

## The passes

### 0. Read it whole, and name the job

Read the entire piece before changing a word. A local fix made blind to the ending is usually wrong. Then answer, out loud if the user is present:

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
- **How long may it be?** Set a length for the reader's job (Size in `references/drafting.md`). A piece far over that length carries more than one document. So does a piece that needs a reading guide or an ID key before the reader can start.

- **Is the text technical?** For documentation, a README, an RFC, a PR description, a commit message or an issue, read `references/technical-docs.md`. Pick the Diátaxis mode, apply its shape and heading rules in pass 1, and its sentence rules in passes 4 and 5.

### 1. Structure

- **Answer early.** The opening gives the recommendation, finding or main claim, not a tour of the background.
- **Message headings.** Headings state a message, not a category ("Background", "Next Steps"). The headings alone should carry the argument. Keep each one short enough to cite in a sentence, about eight words. The section's first sentence carries the rest.
- **Partial reading.** The title, opening and headings alone give the answer and the ask.
- **Vertical logic.** Each section answers the question its parent raises, and nothing else.
- **Horizontal logic.** The items in a group are the same kind of thing and cover the ground without overlap.
- **Ordering.** By time, structure or degree, chosen on purpose. The chronology of the investigation is almost never the right order for the finding.
- **The sum holds.** If every support is true, the top line follows. If not, the claim overreaches or a support is missing.
- **Current final state.** The body states what is true now. It holds no review-round history, agent actions, intermediate corrections, prior counts, superseded wording, or account of how the document evolved, including which draft, run, agent or input each idea came from. Text whose job is the change (changelog, release notes, PR description, commit message, decision log, an ADR's status or history section) is exempt. History that must stay goes in its own section or a linked record.

Fix this layer first. In review mode, say plainly that the structure needs reshaping before you give line notes.

### 2. Load: what the reader has to hold

- **Nothing is used before it is defined.**
- **Expand every domain abbreviation on first use:** *Full Term (ABBR)*, then the abbreviation alone. Industry-universal terms are exempt. If it would belong in a glossary, expand it.
- **One name per concept**, in the document and its neighbours. A synonym for variety reads as a second thing.
- **Each fact is stated once, and the copies agree.** Elsewhere, point to it instead of restating it. Where a summary, table, glossary or log repeats the body, check counts, lists, statuses and scopes against the body. Copies drift apart, and a line edit does not see it.
- **Identifiers stay out of the argument.** Requirement, story, control and ticket IDs go in tables and traceability sections. An argued sentence carries at most one. If a sentence cannot be understood without a lookup, rewrite it in words.
- **A higher section reads completely without a lower one.** Where a lower detail is load-bearing, state it once as a named constraint and point to its definition.
- **Groups stay at three to five.** Nine items are nine things to hold. Two groups of four with named summaries are two.
- **Detail goes where the question arises**, not where it was discovered.

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

Run this last, and without exception on anything you drafted. Open the *Tells of machine-drafted prose* section of the checklist now and check each tell. The most common three are everything in threes, signposts like "It's worth noting", and a first sentence that restates its heading.

## Reporting a review

Every finding has three parts: quote the text, name the problem in one line, give the replacement.

> **"It should be noted that the migration will need to be completed prior to Wave 2."**
> Throat-clearing, and *prior to* for *before*.
> → "The migration must finish before Wave 2."

Order findings by cost to the reader: structure, then ambiguity, then bloat, then rhythm and polish. Lead with the two or three that help most. Name a recurring pattern once, with examples and a count, not forty entries. If the draft is good, say so and give only what would still help.

## Restraint

- **Preserve voice.** Distinctive phrasing that works is not an error. Edit for comprehension, not toward a house average. For technical text, `references/technical-docs.md` takes precedence over voice.
- **Cut repetition before meaning.** Compress in this order: duplication, long-windedness, examples, explanation. Flag any loss of content.
- **Do not bullet by reflex.** Bullets lose *because*, *therefore* and *but*. Use them for parallel items and prose for an argument.
- **Invent nothing.** Editing adds no facts, figures, citations or claims.
- **Keep the doc's own terms.** Renaming a concept mid-edit splits it.
- **House style wins.** A project `CLAUDE.md`, style guide or established convention overrides these defaults. Check for one first.
- **Preserve the technical content.** Never trade accuracy for a shorter sentence. Find a shorter accurate one.
