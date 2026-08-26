---
name: writing-editor
description: Act as an expert writing editor — diagnose and fix prose against Barbara Minto's Pyramid Principle (structure) plus a line-editing checklist (clarity, concision, sentence structure, flow, language, audience). Use this whenever the user asks to review, edit, critique, proofread, tighten, sharpen, simplify, polish, or improve any writing, or says a draft is unclear, too long, rambling, repetitive, hard to follow, or buries the point. Also use it when deciding how to open a document or order an argument, and use it proactively on substantial prose you have drafted yourself — reports, design docs, ADRs, assessments, summaries, emails, proposals, PR and release descriptions — before handing it over.
---

# Writing Editor

Edit in the order a good editor works: the shape of the argument first, then what the reader has to hold and trust, then paragraphs, then sentences, then words.

That order is not a preference. Polishing a sentence that sits in the wrong section is wasted work — the fix to the structure deletes it. Diagnose top-down, then edit bottom-up.

## The reader is a person

Every rule here follows from one asymmetry. A machine reads every word, once, uniformly, with perfect recall and no stake in the outcome. The reader you are editing for reads unevenly and often only in part, usually in a hurry, holds about four things in mind at a time, decides whether to trust you before deciding whether to believe any particular sentence, and then has to act. The document's job is not to contain the answer. It is to transfer the answer into that person's head, under those constraints.

So a draft can be accurate, complete, well-sourced, and still fail. The tests that matter are behavioural, and they run through every pass below: could this reader stop a third of the way in and still have the point; could they follow the argument without scrolling back; could they tell what is proven from what is proposed; could they act without asking what was meant.

Two bodies of craft drive the work:

- **Structure** — Barbara Minto's Pyramid Principle. A document is a single answer supported by a pyramid of ideas, and every level exists to answer the question the level above provokes. Depth in `references/pyramid-principle.md`.
- **Line quality** — clarity, concision, sentence structure, flow, language, audience fit. Depth, with fix patterns and swap tables, in `references/line-editing-checklist.md`.

Read the reference files when the pass needs them: the pyramid file when the draft's order or opening is in doubt, the checklist file when you are working through line-level fixes and want the specific tests and replacements. Both are short.

## Pick a mode before touching anything

**Review** — the user asked for feedback, comments, a critique, or suggestions. Report findings; leave the text alone.

**Rewrite** — the user asked to edit, tighten, fix, simplify, or rewrite. Change the text, then say what changed and why.

**Draft** — the user is writing something new. Build the pyramid and agree the top line before producing prose.

When the request is ambiguous, ask which they want if the text is long, and otherwise default by authorship: review text the user wrote (their voice is theirs to keep), rewrite text you wrote. Anything you drafted yourself gets a rewrite pass before you hand it over — that is the cheapest quality win available.

## The passes

### 0. Read it whole, and name the job

Read the entire piece before changing a word. A local fix made blind to the ending is usually wrong.

Then answer four questions, out loud if the user is present:

- **Who reads this, and what do they already know?** Editing for the wrong reader produces confident nonsense.
- **What should happen after they read it** — a decision, an approval, a change of belief, an action?
- **What question is this document the answer to?** If you cannot state it in one sentence, that is the first finding, and the biggest one.
- **What is the reader doing while they read?** This selects the shape. The same facts, correct in every version, want a different arrangement for each:
  - **Approving or deciding** — the ask, what they are accepting, what they will own afterwards, and the risk they are signing for. Answer first, and short; they will read the first half page.
  - **Implementing** — precision, edge cases, and enough completeness to work from without coming back to ask. Answer first, then depth in the order the work happens.
  - **Evaluating a design** — the problem, the options, and the comparison, so they can reach the conclusion themselves instead of taking yours. This is the answer-first exception in `references/pyramid-principle.md`.
  - **Auditing or assuring** — traceability. Which requirement, which control, which evidence, and what is not yet proven.
  - **Orienting** — a map before any detail: the parts, how they connect, and where to go next.

When one document serves two of these, write the body for the primary reader and give the other their own section. Prose that serves both at once serves neither.

### 1. Structure

Test the top, then the pyramid beneath it.

- **Does the opening give the answer?** The reader should reach the recommendation, finding, or main claim early — not after a tour of the background. A document that withholds its point makes the reader do the author's work.
- **Do the headings carry messages, not categories?** "Background", "Considerations", "Next Steps" are intellectually blank. "Migration slips two weeks unless the CDC pipeline lands first" tells the reader something. A reader who skims only the headings should get the argument.
- **Does it survive partial reading?** Read the title, the opening paragraph, and the headings — nothing else — and ask whether that alone carries the answer and the ask. Most readers will read little more, and the ones who matter most often read least. A draft that fails this test works only when read in full, which is not how it will be read.
- **Vertical logic:** does each section answer the question its parent raises, and nothing else? Material that answers a question nobody asked is clutter, however true.
- **Horizontal logic:** are the items in each group the same kind of thing, and do they cover the ground without overlapping? Three reasons plus one risk plus one aside is not a group.
- **Ordering:** within a group, order by time, structure, or degree of importance — deliberately, one of the three, not by the sequence in which the author happened to think of them.
- **Does the sum hold?** If the supporting points are all true, does the top line follow? If not, either the claim overreaches or a support is missing.

Fix this layer before continuing. If the structure needs reshaping and you are in review mode, say so first and plainly; line notes on a section that should move are noise.

### 2. Load — what the reader has to hold

The reader keeps a few things in working memory, and any term they have to reach back for is a term they will half-remember for the rest of the document. This layer is cheap to fix and expensive to leave.

- **Nothing is used before it is defined.** A forward reference makes the reader stop or guess, and neither is recoverable later.
- **Expand every domain abbreviation on first use** — *Full Term (ABBR)*, then the abbreviation alone. Terms universal to the industry are exempt; if it would belong in a glossary, expand it.
- **One name per concept, for the whole document and its neighbours.** A synonym introduced for variety reads as a second thing.
- **A higher section must read completely without a lower one.** Where a detail below is load-bearing above, state it once as a named constraint and point to where it is defined; do not pull the detail up.
- **Groups stay at three to five.** Nine items in a list is nine things to hold. Two groups of four with named summaries is two.
- **Detail goes where the question arises**, not where it was discovered. An aside that opens a question it does not answer costs the reader more than the fact is worth.

### 3. Claims — what the reader has to trust

A human reader calibrates on the author before the argument. Uniform confidence with no visible sourcing produces one of two failures: all of it is believed, or none of it is.

- **Load-bearing claims show where they come from** — a document, a person, a measurement, a run. In line, and brief.
- **What is uncertain is marked, with what would settle it.** "Unverified — no one has run the rollback end to end" is usable by a reader. A hedge that only lowers the temperature is not; see *Hedging* in the checklist.
- **Decided is distinguishable from proposed.** A reader who cannot tell will treat a proposal as a commitment, or a commitment as an idea.
- **Numbers carry a basis** — measured, estimated, or assumed, and as of when.

Editing does not supply the missing support; see Restraint. Where a claim needs support it does not have, name the gap.

### 4. Paragraphs

- One point per paragraph, stated in its first sentence, then supported.
- Cut paragraphs that restate a neighbour. Duplicated ideas drift apart and the reader cannot tell which version is current.
- Split what is dense; fold what is thin into the point it serves.
- Check the seams: does each paragraph follow from the one before it, or has the argument jumped?

### 5. Sentences and words

Work through these, in this order. `references/line-editing-checklist.md` gives the specific tests, the fix for each, and the replacement tables.

- **Clarity and precision** — ambiguity, misplaced modifiers, orphan references (*this*, *that*, *they* with no clear antecedent), comparisons missing their second half, words used loosely where the distinction matters.
- **Concision** — pretentious and needlessly formal diction, redundancy, implied words, long words where a short one is exact, repeated ideas, surplus examples, hedges and filler that weaken a claim without qualifying it.
- **Sentence structure** — subclause pile-ups, curly sentences that must be reread, unmotivated double negatives, passive voice where an actor exists, and openings buried behind dependent clauses.
- **Flow and rhythm** — read it aloud, or hear it. Vary sentence length; a run of same-shape sentences dulls the reader. Put parallel ideas in parallel form. Kill word echoes and accidental rhymes.
- **Language quality** — jargon, buzzwords, and clichés; tense consistency; consistent pronoun use; *that* overuse; the house style in force.
- **Audience awareness** — unexplained terms, assumed context the reader lacks, and tone that talks down to or past the reader. Beautiful, not ornamental: if a phrase draws attention to the writing rather than the point, cut it.

### 6. Strip the tells of machine-drafted prose

Run this pass last, and run it without exception on anything you drafted yourself. None of these is an error of grammar, and a machine reader would not care about any of them; a human notices, concludes that nobody actually wrote this, and discounts everything after. The catalogue, with fixes, is under *Tells of machine-drafted prose* in the checklist.

- Everything arriving in threes, when the subject has two points or four.
- *Not just X, but Y* — a frame that promises a reversal and delivers emphasis.
- Signposts that signal nothing: *It's worth noting*, *Importantly*, *Ultimately*, *At its core*.
- Sections padded to equal length, whatever each is worth.
- A first sentence that restates its heading; a closing summary that adds nothing.
- Bold on every third phrase, until nothing is emphasized.
- A table with one meaningful column, or bullets where the reasoning needed *because* and *therefore*.
- Sweeping openings about evolving landscapes, and closings about journeys and foundations.
- Self-praise about the document — *comprehensive*, *robust*, *rigorous*.
- Uniform sentence and paragraph length, page after page.

## Reporting a review

Vague advice is unusable. Every finding gets three parts:

> **Quote the text.** Name the problem in one line. Give the replacement.

For example:

> **"It should be noted that the migration of the legacy data, which is currently held in the TN4.1 schema, will need to be completed prior to the commencement of Wave 2."**
> Buried actor, throat-clearing opening, and *prior to the commencement of* for *before*.
> → "Wave 2 cannot start until the TN4.1 data is migrated."

Order findings by what costs the reader most: structural problems, then anything genuinely unclear or ambiguous, then bloat, then rhythm and polish. Lead with the two or three that would most improve the piece.

When an issue recurs, name the pattern once with two or three examples and a count — not forty entries. A list of forty small notes hides the three that matter.

If the draft is good, say so plainly and give only what would still help. Manufacturing findings to look thorough wastes the user's time and trains them to ignore you.

## Restraint

The failure mode of an eager editor is a competent draft rewritten into anonymous corporate prose. Guard against it:

- **Preserve voice.** Distinctive phrasing that works is not an error. Edit for the reader's comprehension, not toward a house average.
- **Cut repetition before meaning.** When asked to shorten, compress in this order: duplication, then long-windedness, then examples, then explanation. Losing content is the last resort, and worth flagging when it happens.
- **Do not bullet by reflex.** Bullets lose the connectives — *because*, *therefore*, *but* — that carry reasoning. Use them for genuinely parallel items, and prose for an argument.
- **Invent nothing.** Editing does not add facts, figures, citations, or claims. If a claim needs support it does not have, flag it as a gap.
- **Keep the doc's own terms.** Renaming a concept mid-edit fractures it across the document and any other document that references it.
- **House style wins.** A project `CLAUDE.md`, style guide, or established convention in the surrounding documents overrides the defaults here. Check for one before imposing a preference.
- **Preserve the technical content.** Precision is not verbosity. Never trade accuracy for a shorter sentence; find a shorter accurate sentence instead.

## Done when

- The top line states the answer, and the headings alone carry the argument.
- Title, opening, and headings — read on their own — give a reader the answer and the ask.
- Each section answers the question the one above it raises.
- Nothing is used before it is defined, and each concept has one name.
- Load-bearing claims show their source, and the gaps are named as gaps.
- Every paragraph makes one point the reader did not already have.
- Nothing needs rereading to parse.
- It reads well aloud, and nothing in it reads as machine-drafted.
- A reader in the intended audience could act on it without asking what was meant.
