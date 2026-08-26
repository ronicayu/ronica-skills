# The Pyramid Principle

Barbara Minto's method for structuring thought, condensed for editing use. Read this when a draft's opening, order, or grouping is in doubt.

Contents: [Why a pyramid](#why-a-pyramid) · [The three rules](#the-three-rules) · [The introduction: SCQA](#the-introduction-scqa) · [Grouping: inductive and deductive](#grouping-inductive-and-deductive) · [Ordering within a group](#ordering-within-a-group) · [Summarize the message, not the category](#summarize-the-message-not-the-category) · [Showing the structure](#showing-the-structure) · [Diagnostic questions](#diagnostic-questions) · [Common failures](#common-failures) · [Worked example](#worked-example) · [Limits](#limits)

## Why a pyramid

A reader can hold only a few ideas at once, and will look for a structure whether or not the writer supplied one. Given an unsorted list, the reader invents an order — usually the wrong one, and always at a cost the writer never sees.

So a document should present a single governing thought at the top, supported by a small group of ideas beneath it, each supported in turn. The reader gets the answer first and then, only if they want it, the reasoning. Sorting the ideas before writing is also how the writer discovers whether the argument holds.

## The three rules

Every level of the pyramid obeys three rules:

1. **Each idea summarizes the ideas grouped below it.** A parent is the conclusion drawn from its children, not a label for them.
2. **Ideas in a group are the same kind of thing.** Three reasons; four steps; two risks. Not two reasons, a step, and an observation.
3. **Ideas in a group are logically ordered.** By time, by structure, or by degree — chosen, not accidental.

If a group breaks rule 1, the argument does not actually support its claim. If it breaks rule 2, the writer has not finished thinking.

**Vertical relationship — question and answer.** Each statement provokes a question in the reader's mind, and the level below answers it. "We should consolidate the three regional platforms" provokes *why?* — and the section below answers *why*, nothing else. Material that answers an unasked question is clutter, however accurate.

**Horizontal relationship — the group holds together.** Each group is either inductive or deductive, never a mix.

**Group size.** Three to five ideas per group. If you have nine, they belong in two or three groups with their own summaries — and finding those summaries is the analytical work, not busywork.

## The introduction: SCQA

The introduction's job is to make the reader want the answer, and it does that by telling them a story they already agree with:

- **Situation** — an uncontested statement about the reader's world, establishing time and place.
- **Complication** — what changed or went wrong; what disturbed the situation.
- **Question** — the question the complication raises. Usually implied rather than written.
- **Answer** — the governing thought. This is the top of the pyramid.

The four elements can be ordered for effect:

- **Standard** (S–C–Q–A) — the default; calm, expected.
- **Direct** (C–S–Q–A) — opens on the problem; conveys urgency.
- **Concerned** (Q–S–C–A) — opens on the question; for a reader already asking it.
- **Aggressive** (A–S–C) — answer first, then justification; for a reader short on time, or one who will resist the conclusion and must be shown it is already grounded.

Everything the reader must accept before the answer belongs in the introduction. Nothing arguable does: the introduction reminds, it does not persuade.

**Answer-first has one common exception.** A technical reader evaluating a design must be able to reach the conclusion independently, so a design document often runs problem → options → comparison → recommendation. That is still a pyramid; the governing thought is still stated early, in a summary, and the body earns it. See the sibling skill `writing-and-reviewing-documentation` for the document-type split.

## Grouping: inductive and deductive

**Inductive** — a set of ideas of the same kind, from which the summary is inferred. The group can be named with a plural noun: *three reasons*, *four symptoms*, *two prerequisites*. The summary states what the group implies.

> Warsaw's forces were crushed. → Lodz's forces were crushed. → Krakow's forces were crushed.
> ∴ Poland's military position has collapsed.

**Deductive** — a chain: a statement about a situation, a statement about something related to it, and the implication of the two together.

> Batch settlement runs before the ledger closes. → The ledger now closes an hour earlier. → ∴ Batch settlement must move an hour earlier.

Deduction is easier to write and harder to read: it forces the reader through every step before the point. Keep chains to about four steps, and prefer induction at the top of a document. If a section reads as a forced march, it is probably a deductive chain that should be an inductive group.

## Ordering within a group

Pick one of three, and be consistent inside the group:

- **Time order** — cause then effect, first step then next. Use when the group describes a process or a sequence.
- **Structural order** — the parts of a whole: by system, region, function, org unit. Requires the division to be **MECE** — Mutually Exclusive (no overlap) and Collectively Exhaustive (nothing missing). Overlap means double-counting; a gap means the conclusion does not follow.
- **Degree order** — ranked by size, severity, or importance, most significant first. Use when the items share a property held in differing amounts.

If you cannot name which order a group uses, it has none, and the reader will feel it as a list.

## Summarize the message, not the category

The most common structural failure is the intellectually blank assertion: a heading or lead sentence that names a container instead of stating its content.

| Blank | Says something |
|---|---|
| The company has three problems | Margin, attrition, and lead time are all worsening quarter on quarter |
| Considerations | Two constraints rule out an in-place upgrade |
| Next steps | Nothing can start until the data owner is named |
| Findings from the review | The rollback plan has never been tested end to end |

The test: could a reader who read only the headings reconstruct the argument? If the headings are category names, they cannot, and the document only works when read in full — which is not how it will be read.

## Showing the structure

Make the pyramid visible so the reader can enter at any depth:

- Headings mirror the pyramid levels; parallel levels get parallel grammatical form.
- Introduce a group by saying how many and what kind — *three reasons* — then keep them together and in the promised order.
- Use numbering for sequence and dependency; plain bullets for genuinely unordered sets.
- Close a long section by restating what it established, and pick that thread up at the start of the next.

## Diagnostic questions

Run these against any draft:

1. What single sentence is this document the answer to? Is it in the first paragraph?
2. Read the headings alone. Do they tell the story? Do any name a category rather than a message?
3. For each section: which question raised above does it answer? If none, why is it here?
4. For each group: same kind of thing? MECE? Which of the three orders?
5. If every support is true, does the parent follow — with nothing left over and nothing missing?
6. Does the introduction contain anything the reader might dispute? Move it into the body.
7. Is any group larger than five items, or reliant on a deductive chain longer than four steps?

## Common failures

- **Laundry list** — items in the order they occurred to the writer, joined by nothing.
- **Category headings** — "Background", "Analysis", "Considerations" carrying no message.
- **No question** — a document that reports activity instead of answering something.
- **Buried answer** — the recommendation on page 6, after the reasoning.
- **Mixed group** — reasons and risks and steps under one heading.
- **Overreaching summary** — a top line the supports do not add up to.
- **False MECE** — a structural split whose categories overlap, so evidence gets counted twice.
- **Arguable introduction** — persuasion smuggled into the setup, so the reader is already resisting.

## Worked example

**Before** — activity in the order it happened, answer nowhere:

> We held workshops with the operations and finance teams in March and April. Several themes emerged. The current reconciliation process involves manual steps. Volumes have grown 40% since the platform launched. Staff have raised concerns about overtime. We also reviewed the vendor's roadmap. There is a scheduled deprecation of the batch API in Q3. Options were discussed, including automation, additional headcount, and renegotiating the vendor contract. Further analysis is recommended.

**After** — answer first, one inductive group of three, ordered by degree:

> **Automate reconciliation before Q3, or month-end close will fail.**
>
> Manual reconciliation has been sustainable until now. Three things have changed:
>
> **The vendor deprecates the batch API in Q3**, and the manual process depends on it. This is a hard date, not a preference.
>
> **Volumes have grown 40%** since launch, and the process scales only with hours worked.
>
> **The team is already absorbing the growth as overtime**, which caps how much further it can stretch.
>
> Automation is the only option that survives all three; headcount fails on the API date, and a contract renegotiation fails on volume. [Comparison follows.]

What changed: the governing thought moved to the top; the workshops became provenance rather than content; three same-kind pressures were grouped and ordered by how binding they are; the summary now follows from the group; and "further analysis is recommended" — a non-answer — became a recommendation that can be argued with.

## Limits

The pyramid organizes an argument. It does not fix a document with nothing to say. If the diagnostic questions produce no answer sentence, the problem is the thinking, and no restructuring will hide it — say so.
