# Line-Editing Checklist

The sentence-and-word pass, once the structure is sound. Each entry names a fault a reviewer can point at and the fix for it.

Contents: [Clarity and precision](#clarity-and-precision) · [Concision](#concision) · [Sentence structure](#sentence-structure) · [Flow and rhythm](#flow-and-rhythm) · [Structure and narrative](#structure-and-narrative) · [Language quality](#language-quality) · [Audience awareness](#audience-awareness) · [Tells of machine-drafted prose](#tells-of-machine-drafted-prose) · [Swap tables](#swap-tables)

## Clarity and precision

**Ambiguity.** If a sentence supports two readings, the reader picks one — sometimes the wrong one, and never tells you. Ask of every clause: is there a second way to read this?

> "We will notify the team when the report is approved and the migration completes."
> Two readings: notify once, after both; or the report's approval is itself conditional on the migration.
> → "Once the migration completes and the report is approved, we will notify the team."

**Orphan references.** *This*, *that*, *these*, *it*, *they* must point at one unmistakable noun. When the antecedent is a whole preceding clause, name it.

> "The service retries and the queue drains slowly. This causes duplicate charges."
> → "The retries cause duplicate charges."

Where a bare pronoun would be ambiguous, prefer `this` plus the noun — *this delay*, *this constraint* — over a naked *this*.

**Misplaced modifiers.** A modifier attaches to whatever it sits next to.

> "We only reviewed the changes to the schema." — only reviewed, as opposed to approved?
> → "We reviewed only the changes to the schema."

A participle attaches to the subject that follows it:

> "Running overnight, the report showed three failures." — the report was not running.
> → "The overnight run produced three failures."

**Half comparisons.** *Faster*, *more reliable*, *better* need a second term. Faster than what, measured how?

**Loose word choice.** Where a distinction carries weight, keep it: *may* is permission and *might* is possibility; *fewer* counts and *less* measures; *ensure* guarantees, *insure* indemnifies, *assure* reassures. Do not write *significant* for *large*, *literally* for *figuratively*, or *impact* where *effect* or a verb is meant.

**Sentences that do not follow.** Read consecutive sentences as an argument. If sentence two does not follow from sentence one, either a step is missing or the connective is wrong. *Therefore*, *however*, and *because* make claims — check that each is true.

## Concision

**Throat-clearing.** Openings that delay the sentence: *It should be noted that*, *It is important to understand that*, *As mentioned previously*, *In order to*, *The fact that*, *What we found was that*. Delete and start with the subject.

**Pretension.** Long words chosen for weight rather than precision — see the [swap tables](#swap-tables). The test is not word length but whether the shorter word means the same thing. It usually does; when it does not, keep the long one.

**Redundancy and implied words.** *Advance planning*, *end result*, *completely eliminate*, *future plans*, *currently ongoing*, *each and every*, *first and foremost*, *close proximity*, *actual fact*, *very unique*. One word survives.

**Repeated ideas.** The same point restated in a heading, a table, and the paragraph beneath. Pick the one place the reader will look and delete the others. Duplicated content drifts apart on the next edit, and then the reader cannot tell which copy is current.

**Excess evidence.** Three examples where one carries it. A caveat already implied by the sentence. A restatement after the point is clear. Stop when the reader is convinced.

**Hedging.** *Somewhat*, *fairly*, *arguably*, *it seems*, *in some sense*, *may potentially*, *tends to generally*. A hedge that qualifies a claim honestly is fine — *in most cases*, *under load above 200 TPS* — because it says which cases. A hedge that only lowers confidence weakens the writer without informing the reader. If the claim is uncertain, say what would settle it.

**Filler intensifiers.** *Very*, *really*, *quite*, *actually*, *basically*, *essentially*, *truly*, *clearly*, *obviously*. Most add nothing; *clearly* and *obviously* often mark the spot where an argument is missing.

**Nominalization.** A verb buried inside a noun drags a weak verb and a preposition along with it.

> "The implementation of the change resulted in a reduction in latency."
> → "The change reduced latency."

Look for *-tion*, *-ment*, *-ance*, *-ity* paired with *make*, *give*, *provide*, *perform*, *conduct*, *achieve*.

## Sentence structure

**Subclause overload.** More than two subordinate clauses and the reader loses the spine. Find the main claim, give it its own sentence, and let the rest follow.

> "The batch service, which was originally designed for the legacy schema that predates the 2019 migration, cannot process the new format without changes to the parser, although a workaround exists."
> → "The batch service cannot process the new format; its parser still expects the legacy schema. A workaround exists."

**Curly sentences.** Any sentence you must reread to parse is broken, even if it is grammatical. Cut it into its clauses and reassemble in the order events actually happen.

**Double negatives.** *Not uncommon*, *not without merit*, *fails to prevent*. Use one when the litotes is deliberate; otherwise state the positive. *Not infrequently* is *often*.

**Passive voice.** Use active when an actor exists, because the passive hides who acts — and in a design or a plan, who acts is usually the point.

> "It was decided that the rollout would be deferred." Decided by whom?
> → "The steering committee deferred the rollout."

Passive is right when the actor is unknown, irrelevant, or genuinely not the subject: *the record is deleted after seven years*.

**Front-loaded openings.** A dependent clause before the subject delays the point and, repeated, makes every sentence sound the same shape. *Given the constraints described above, and in light of the timeline, the team will…* → *The team will…* Occasional inversion is good rhythm; a run of it is a tic.

**One job per sentence.** A sentence carrying two claims joined by *and* usually wants to be two sentences — or one sentence, once the weaker claim is cut.

## Flow and rhythm

**Read it aloud.** Nothing else finds the lumps as reliably. Where you stumble, the reader stumbles.

**Vary length.** A paragraph of uniform medium-length sentences reads as a drone. Follow a long sentence with a short one. Short sentences land hardest, so save them for what matters.

**Transitions.** Each sentence should hook to the one before, usually by opening with something the previous sentence established. When only a signpost will do, pick one that states the actual relation — *but*, *so*, *because*, *even so* — over the interchangeable *additionally* and *furthermore*.

**Parallelism.** Parallel ideas take parallel grammar. Lists especially: every item the same part of speech, the same tense, and either all fragments or all sentences.

> "The service must: authenticate requests, rate limiting, and it should log failures."
> → "The service must authenticate requests, rate-limit them, and log failures."

**Word echoes.** The same distinctive word twice in a sentence or three times in a paragraph is a stumble. *Use*, *provide*, *ensure*, *support*, *leverage*, *process* are the usual repeat offenders. Fix by cutting one occurrence, not by reaching for a thesaurus — a forced synonym implies a distinction that is not there. Deliberate repetition of a key term for clarity is fine; technical terms must stay consistent even when they echo.

**Sound.** Watch for accidental rhyme, three stressed syllables in a row, and unintended alliteration. If a phrase draws attention to itself rather than its meaning, it is in the way.

## Structure and narrative

The full treatment is in `pyramid-principle.md`; at the paragraph level:

- **Topic sentence first.** State the point, then support it. A paragraph that builds to its point makes the reader hold everything in suspense.
- **One point per paragraph.** Two points means two paragraphs, or one point and one deletion.
- **Order for the reader, not the author.** Chronology of the investigation is almost never the right order for the finding.
- **Sections must earn their place.** A section that answers no question the reader has is clutter, however good the prose.
- **Clutter buries the lead.** When a key idea is surrounded by qualifications, provenance, and asides, the reader misses it. Give it its own sentence and its own line.

## Language quality

**Jargon.** Two kinds. Domain terms the audience shares are precise and belong. Terms borrowed to sound expert do not. Expand any domain abbreviation on first use — *Full Term (ABBR)*, then the abbreviation — since an unexpanded one is a forward reference to a glossary the reader must go find.

**Buzzwords.** *Leverage*, *synergy*, *holistic*, *robust*, *seamless*, *best-in-class*, *utilize*, *operationalize*, *going forward*, *at the end of the day*, *paradigm shift*. Each has a plain equivalent, and most are claims without evidence: *robust* and *seamless* need a number or a mechanism.

**Clichés.** *Low-hanging fruit*, *move the needle*, *boil the ocean*, *the elephant in the room*, *a perfect storm*, *tip of the iceberg*. A dead metaphor makes the reader skim.

**Tense consistency.** Pick a frame and hold it. Standing behaviour in the present (*the service retries*), completed events in the past (*the migration ran overnight*), planned work in the future or a modal (*the team will*, *the team must*). Drifting between them makes a plan read as a report.

**Pronoun consistency.** Decide who *we* is and keep it. Do not switch between *we*, *the team*, and *one* for the same actor. Use *they* for a singular person of unstated gender rather than *he or she*, and never infer someone's pronouns from their name.

**That overuse.** Delete *that* where the sentence reads cleanly without it (*we found that the queue drained* → *we found the queue drained*), but keep it where dropping it causes a momentary misreading. Distinguish restrictive *that* from non-restrictive *which*, and use *who* for people.

**House style.** A project `CLAUDE.md`, a style guide, or the settled convention of the surrounding documents outranks every default here. Check first; consistency with neighbours beats local perfection.

## Audience awareness

**Assumed knowledge.** List what the reader must already know to parse each paragraph. Anything on that list the audience lacks is either defined, cut, or moved behind a pointer.

**Assumed agreement.** Writing that treats a contested position as settled loses a reader who does not share it. State the position, give the reason, and let the reader follow.

**Respect.** Do not explain what the audience knows — it reads as condescension. Do not skip what they do not — it reads as showing off. Where a reader's decision or work is being criticised, address the substance and not the person.

**Intent.** Return to the question the document must answer, and to what should happen after it is read. If a reader could finish it and still not know what to do, it has not done its job, however clean the prose.

**Beauty without pretension.** Aim for prose that is a pleasure to read because it is clear, well-paced, and exactly weighted — not because it is decorated. When you notice your own phrasing being admired, cut it.

## Tells of machine-drafted prose

None of these is a grammatical error, which is why the earlier passes leave them standing, and a machine reader would not care about any of them. A human notices them within two paragraphs, concludes that nobody actually wrote this, and discounts the content from there on. Run this pass last, and always on prose you drafted yourself.

**The rule of three, applied everywhere.** Three adjectives, three clauses, three bullets, whatever the subject actually has. Count the real points and use that number; two is a fine number, and so is one.

> "The design is clear, scalable, and maintainable."
> → "Each module owns one schema, so a change lands in one place."

**Not just X, but Y.** Also *It's not about X, it's about Y* and *X isn't merely Y — it's Z*. The frame promises a reversal and delivers emphasis.

> "This isn't just a migration — it's a re-architecture."
> → "The migration also replaces the scheduler."

**Signposts that signal nothing.** *It's worth noting*, *Importantly*, *Notably*, *That said*, *Ultimately*, *At its core*, *Fundamentally*. Delete. A point that matters is shown to matter by where it sits.

**Sections padded to equal length.** Every section the same size and depth, because an outline was filled in rather than an argument written. Let the section that matters run longer, and delete the one that existed for symmetry.

**Heading echo.** The first sentence restates the heading in different words, spending the most-read line in the section on nothing.

> "## Rollback is untested
> Rollback has not been tested end to end."
> → "## Rollback is untested
> The plan has been walked through on paper twice; no one has run it against a restored database."

**A summary that adds nothing.** "In summary, the three factors above…" tells a reader who just read them what they already hold. Keep a closing only when it states something new: the consequence, the decision, or who does what next.

**Emphasis inflation.** Bold on every third phrase, italics on ordinary words, em-dashes as the only punctuation between clauses. Bold marks the one thing a skimmer must not miss; four times on a page it marks nothing.

**Tables and bullets by reflex.** A table with one meaningful column, or a bulleted list of what was an argument. Prefer a list only where the items are genuinely parallel, and a table only where each row has two or more comparable columns (see *Restraint* in `SKILL.md` for why bullets cost reasoning).

**Sweeping frames.** *In today's rapidly evolving landscape*, *As organizations increasingly…*, and the matching closings about journeys, foundations, unlocking, and empowering. Cut to the specific claim, or cut the sentence.

**Hedge and hype in one sentence.** "This may potentially deliver significant improvements." Neither half survives: say what changes, by how much, and how confident you are.

**Self-praise about the document.** *Comprehensive*, *robust*, *thorough*, *carefully designed*, *rigorous*, *best practice*. These are claims about the work rather than claims in it, and the reader judges that for themselves.

**Faux precision.** "Approximately 40–60% faster", "roughly 3–5 days", where nothing was measured. Give the basis, or give the narrower range you can defend.

**Uniform rhythm.** Every sentence fifteen to twenty words, every paragraph three sentences, page after page. The fix is under [Vary length](#flow-and-rhythm), but the cause is different: assembled prose has no voice to vary.

**Restating the request.** "As requested, this document outlines…" spends the opening line on what the reader already knows. Start with the answer.

## Swap tables

### Long for short

| Instead of | Write |
|---|---|
| utilize, leverage | use |
| facilitate | help, enable |
| commence, initiate | start, begin |
| terminate | end, stop |
| endeavour, attempt to | try |
| ascertain, determine | find out, work out |
| demonstrate | show |
| sufficient | enough |
| numerous, a number of | many, some, *or a number* |
| additional | more, extra |
| approximately | about |
| currently, presently | now, *or delete* |
| subsequently | then, later |
| methodology | method |
| functionality | features, *or what it does* |
| in the event that | if |
| prior to, in advance of | before |
| subsequent to, following | after |
| in order to | to |
| due to the fact that | because |
| with regard to, in respect of | about, for |
| for the purpose of | to, for |
| in close proximity to | near |
| at this point in time | now |
| a significant proportion of | most, *or the number* |
| has the ability to | can |
| is able to, is in a position to | can |
| it is necessary that | must |
| provides support for | supports |
| in the majority of cases | usually |
| on a regular basis | regularly, *or how often* |

### Delete outright

*It should be noted that* · *It is important to note that* · *As you may be aware* · *Needless to say* · *In terms of* · *The fact that* · *There is/are … that* (usually recoverable as a verb) · *very*, *really*, *quite*, *basically*, *essentially*, *actually* · *clearly*, *obviously*, *of course* · *going forward* · *at the end of the day* · *in my opinion* (in a document that is already yours)

### Verb buried in a noun

| Instead of | Write |
|---|---|
| make a decision | decide |
| provide a summary of | summarize |
| perform an analysis of | analyse |
| conduct a review of | review |
| give consideration to | consider |
| reach a conclusion | conclude |
| take into account | consider |
| result in a reduction of | reduce |
| carry out an assessment | assess |
| is indicative of | indicates |
