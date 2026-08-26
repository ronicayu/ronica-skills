---
name: write-doc
description: Author a document through four gated stages — purpose and audience, sources, a stress-tested Minto pyramid outline, then content. Use when the user asks to write, draft, create, produce, or put together a document, report, design paper, ADR, assessment, proposal, memo, brief, or spec that does not exist yet, or when an existing draft needs rebuilding from its structure up. Body prose is never written before the outline is signed off.
---

# Write Doc

A document fails long before the sentences. It fails when nobody agreed what question it answers, who reads it, or what shape the argument takes — and the writer discovered all three while drafting, in the draft.

This skill front-loads that agreement. Four stages, each gated: purpose and audience, sources, outline, content. The gate before content is the point of the whole thing.

**Do not write body prose until the user has approved the outline.** Not one paragraph, not a "quick example section", not "just to show the shape". A section written before the structure is settled is work you will delete, and worse, it anchors the user on wording when the argument is still wrong. When you catch yourself wanting to draft, go back to the outline and make it more specific instead.

This skill builds documents. It does not edit them — `writing-editor` does that, and this skill calls it in stage 4 rather than restating its rules. Read `references/skeleton-format.md` before stage 3 for the skeleton spec and a worked example.

## How to run the stages

Stages 1 to 3 are a conversation. Ask **one question at a time** and give your recommended answer with each one — a question with a recommendation attached is answerable in three words, and the user will correct a wrong recommendation faster than they will compose an answer from nothing. Anything you can settle by reading the repo, read the repo instead of asking.

Compress stages 1 and 2 into a single confirmation when the user's opening request already supplies purpose, audience, and sources — read them back, ask what's missing, move on. Never compress stage 3's approval.

If the user says to skip the outline, say once what it costs — "then the structure gets decided in the drafting, and rework lands on you" — and comply. It is their document.

Persist state in the target file, not in the conversation. The brief block written in stage 1 carries purpose, audience, shape, sources and a `Status:` line. If the session is compacted, read the target file and resume from `Status:`.

## Stage 1 — Purpose and audience

Nothing here is about the document. It is all about the reader and the outcome.

Settle these, then write them into the target file's brief block:

- **The one question this document answers.** One sentence, ending in a question mark. If you cannot get one, you do not yet have a document — you have a topic. Say so and dig until you have the question.
- **Who reads it, and what they already know.** Name real roles. "Stakeholders" is not an audience. What they already know determines what you can leave out, which matters more than what you put in.
- **What should be different after they read it** — a decision made, an approval given, a belief changed, an action taken. If the honest answer is "they'll be informed", push: informed enough to do what?
- **What the reader is doing while they read.** This picks the shape, and the same facts want a different arrangement for each:
  - *Deciding or approving* — the ask first, then what they are accepting and the risk they are signing for. They will read the first half page.
  - *Implementing* — the answer first, then depth in the order the work happens, complete enough that they don't come back to ask.
  - *Evaluating a design* — problem, options, comparison, recommendation. A technical reader must be able to reach the conclusion themselves. This is the one place answer-first yields.
  - *Auditing* — traceability. Which requirement, which control, which evidence, what is not yet proven.
  - *Orienting* — a map before any detail: the parts, how they connect, where to go next.
- **Whether the reader is scanning or following.** This sets granularity, and it is a separate decision from shape. A scanning reader wants short paragraphs, visible counts, and a heading every few points; a reader who has to follow an argument needs the connectives — *because*, *therefore*, *but* — and those only exist inside multi-sentence paragraphs. Most documents have some of each; name which sections are which now, because retrofitting granularity means rewriting.
- **Constraints** — target length, format, deadline, and the house style in force. Check for a `CLAUDE.md`, style guide, or established convention in neighbouring documents; it overrides every default in this skill and in `writing-editor`.

When one document serves two reader activities, write the body for the primary reader and give the other their own section. Prose serving both serves neither — flag it and pick the primary.

**Sizing.** Agree a target length now. Two pages supports two levels of heading and three or four sections; twenty supports four levels. Deciding this late is how documents grow a level of nesting nobody needed.

## Stage 2 — Sources

Sources can be empty. A document written from the user's head alone is legitimate — but then say so in the brief, because it changes what stage 4 may assert.

- **Enumerate before reading.** List candidate sources and have the user confirm, add, and cut. Cheaper than reading the wrong five files.
- **Mark each one authoritative or indicative.** Authoritative sources settle facts; indicative ones suggest and must be cross-checked. Where the repo records its own confidence levels or a corrections file, honour them.
- **Read them, and note what each one gives you** — the claim or number you will draw from it, not a summary. You are collecting the evidence the outline's supports will rest on.
- **Write down what has no source.** This is the highest-value output of the stage. Every claim the document needs but no source supports becomes either a question for the user, or a named gap that stage 4 marks as unverified. Both beat a confident sentence with nothing behind it.

Invent nothing, in this stage or any later one. No figures, no citations, no attributed positions. A gap named as a gap is usable by a reader; a plausible fabrication is a trap for them.

## Stage 3 — Outline

Build the pyramid, write it into the target file as a skeleton, then have it grilled. The pyramid mechanics — the three rules, SCQA, inductive versus deductive grouping, the three orderings, message-not-category headings — are in `references/pyramid-principle.md`. Read it; do not re-derive it.

### Build it

1. **Write the governing thought as one declarative sentence.** Not a title, not a topic. "Wave 1 can cut over in October" is a governing thought; "Wave 1 cutover readiness" is a filing label. This sentence becomes the document's H1 or its opening line, and everything below exists to earn it.
2. **Draft the introduction as Situation, Complication, Question, Answer.** Order it for the reader: standard for a calm reader, direct to convey urgency, aggressive when they are short on time or will resist. Nothing arguable belongs in the introduction — it reminds, it does not persuade.
3. **Break the governing thought into three to five supports.** Each support is a message, phrased as a claim. Each answers the question the governing thought provokes in this reader's mind — usually *why?*, sometimes *how?*, occasionally *what exactly?*
4. **Name the group type and the ordering, out loud, per group.** Inductive or deductive; time, structure, or degree. If you cannot name the ordering, the group does not have one and the reader will feel it as a list.
5. **Recurse one level at a time**, only where the target length supports it. Stop when a section's message needs no further breakdown to be defended.
6. **Attach a source to every support**, from stage 2. A support with no source is a gap; mark it as one now rather than discovering it mid-draft.

### Write the skeleton

Write it into the real target file — headings plus a one-line intended message per heading, per `references/skeleton-format.md`. Not a separate outline document. The messages become the section lead sentences in stage 4, so the outline is not a plan for the document; it is the document, at low resolution.

**Keep each heading short enough to cite inside a sentence.** A message-carrying heading still has to be referable, so test it by writing the reference: if *Section &lt;heading&gt;* cannot sit in a sentence without derailing it, the heading is too long. This binds hardest where the house style forbids section numbers, because the heading is then the document's only handle. Shorten the heading rather than collect references you cannot phrase.

Set `Status: OUTLINE — not approved` in the brief block.

### Grill it

Invoke the `grill-me` skill and interview the user on the structure. Scope the interview to the outline — this is not the time for implementation questions or wording. Work down the tree, one question at a time, recommendation attached, and update the skeleton in the file as each answer lands so the artefact and the conversation never diverge.

The questions worth grilling, in the order that catches the most:

- Does the governing thought follow if every support is true — with nothing left over and nothing missing? An overreaching top line is the most common and most expensive failure.
- Is each group the same kind of thing? Reasons mixed with risks mixed with steps means the thinking is not finished.
- Is each group MECE — no overlap, no gap? Overlap double-counts evidence; a gap breaks the conclusion.
- Does each section answer a question raised above it? A section that answers a question nobody asked is clutter, however true it is.
- Read the headings alone. Do they carry the argument? Any that names a category rather than a message is a heading that has not done its job.
- Would a reader who stops after the introduction have the answer and the ask?
- Which supports rest on gaps, and can the document still make its claim with those gaps marked?
- What did the user leave out because it was inconvenient? Ask directly.

Where the user's answer weakens the top line, change the top line. A governing thought narrowed to what the evidence supports is a better document than one propped up by a support that does not hold.

### Gate

Show the skeleton and ask for approval in plain words: *this is the structure — approved, or what changes?* On approval, set `Status: OUTLINE APPROVED` and only then continue. Silence is not approval, and neither is the user answering the last grill question.

## Stage 4 — Content

Now write, and only now. Section by section, in document order, updating `Status: DRAFTING <section>` as you go. Large documents get written in chunks — one section group per write — per the house rule.

- **Each section opens with its skeleton message**, as a sentence. If expanding the message needs a fact you do not have, stop and go back to the user — do not improvise around it.
- **Delete each `<!-- msg: -->` comment as you expand it.** A leftover comment at the end means a section never got written.
- **Keep a higher section readable without a lower one.** Where a detail below is load-bearing above, name it once as a constraint and point to where it is defined. Do not pull the detail up.
- **Show sources in line, briefly, for load-bearing claims.** Mark what is uncertain along with what would settle it. Keep decided distinguishable from proposed; a reader who cannot tell will read a proposal as a commitment.
- **State each conclusion before its reasoning, and name the answer the reader will have thought of.** Where an obvious alternative exists, name it and dispose of it first, then explain. Otherwise the reader weighs their own answer while you build your case and stops listening before the conclusion lands. Withholding a conclusion until the argument is complete reads as suspense, which spends attention the document needs elsewhere.
- **A list shows a count; prose shows a relation.** Convert to a list when the items are genuinely parallel and their number is the point — a reader sees "seven incompatible values" without parsing. Keep prose when what matters is how the items differ, because a list silently asserts they are equivalent. Splitting one idea per line makes a document scannable and doubles its length; do it where the reader is scanning, not where they are following.
- **Nothing before it is defined.** Expand every domain abbreviation on first use as *Full Term (ABBR)*, then the abbreviation alone. One name per concept, for the whole document.
- **Diagram where a diagram carries it better than prose** — system interactions, flows, sequences, state. Follow the house style for diagram format.

Then run `writing-editor` over what you drafted: the load, claims, paragraph, sentence, and machine-tells passes. This is not optional politeness. You wrote it, so you are the worst reader of it, and the machine-tells pass in particular catches what you cannot see from inside the draft.

Finally, delete the brief block, and check:

- Title, opening, and headings — read alone — give the answer and the ask.
- Every skeleton message survived as a real section, and no `msg:` comment remains.
- Each section answers the question the one above raises, and nothing else.
- Gaps are marked as gaps; nothing is asserted that no source supports.
- The target length held, or you can say why it moved.
- A reader in the intended audience could act on it without asking what was meant.

## Failure modes

- **Drafting during stage 3.** The single most common way this skill gets wasted. Prose in the outline stage means the gate did not hold.
- **A governing thought that is a topic.** "X readiness", "Y considerations", "an overview of Z" — no claim, so nothing below can support or contradict it, and the document cannot be wrong. It also cannot be useful.
- **Category headings surviving the grill.** "Background", "Analysis", "Next Steps" are containers. They pass unnoticed because they look like a document is supposed to look.
- **Skipping stage 2 because the user seems to know it all.** Then stage 4 asserts things nobody can trace, and the first reviewer finds them.
- **Structure copied from the last document of this type.** The template answers a question this reader may not be asking. Build the pyramid from this document's question.
- **Nine supports under one heading.** Nine things to hold. Group them and find the summaries — that grouping *is* the analytical work, not overhead before it.
- **Letting the outline and the file drift.** Every resolved grill question gets written into the skeleton immediately, or the approved structure is one that only exists in the transcript.
- **Headings that cannot be cited.** Sentence-length headings leave a document unable to refer to itself. The cross-references come out unphraseable, then wrong, once the headings are revised and the references are not.
- **Granularity chosen by habit rather than by reader.** One idea per line reads as clarity and costs the connectives that carry an argument; dense paragraphs read as rigour and lose a reader who is scanning. Either is right somewhere in most documents, and neither is right everywhere in one.
