# Line-Editing Checklist

The sentence-and-word pass, once the structure is sound. Each entry names a fault a reviewer can point at and the fix for it.

Contents: [Clarity and precision](#clarity-and-precision) · [Concision](#concision) · [Sentence structure](#sentence-structure) · [Flow and rhythm](#flow-and-rhythm) · [Language quality](#language-quality) · [Audience awareness](#audience-awareness) · [Tells of machine-drafted prose](#tells-of-machine-drafted-prose) · [Swap tables](#swap-tables)

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

**Numbers that do not compare.** Numbers the reader must compare share a unit, a precision and a base, and sit next to each other. A reader who converts milliseconds to seconds, or a percentage to a count, is doing the writer's arithmetic. Round to what the decision needs. When the comparison is the point, state it. Arithmetic the stated figures fix, such as a count from a percentage and its base or the ratio of two values, is not an invented figure; any other new number is. Three or more numbers compared on two or more attributes go in a table.

> "Latency rose from 1,247 ms last quarter to 3.9 s after the change, affecting 18% of the 2,140 requests."
> → "After the change, latency rose from 1.2 s to 3.9 s, more than three times last quarter's figure. The rise affected 385 of 2,140 requests (18%)."

**Loose word choice.** Where a distinction carries weight, keep it: *may* is permission and *might* is possibility; *fewer* counts and *less* measures; *ensure* guarantees, *insure* indemnifies, *assure* reassures. Do not write *significant* for *large*, *literally* for *figuratively*, or *impact* where *effect* or a verb is meant.

**Sentences that do not follow.** Read consecutive sentences as an argument. If sentence two does not follow from sentence one, either a step is missing or the connective is wrong. *Therefore*, *however*, and *because* make claims — check that each is true.

## Concision

**Throat-clearing.** Openings that delay the sentence: *It should be noted that*, *It is important to understand that*, *As mentioned previously*, *In order to*, *The fact that*, *What we found was that*, *It's worth noting*, *Importantly*, *Notably*, *That said*, *Ultimately*, *At its core*, *Fundamentally*. Delete and start with the subject.

**Pretension.** Long words chosen for weight rather than precision — see the [swap tables](#swap-tables). The test is not word length but whether the shorter word means the same thing. It usually does; when it does not, keep the long one.

**Redundancy and implied words.** *Advance planning*, *end result*, *completely eliminate*, *future plans*, *currently ongoing*, *each and every*, *first and foremost*, *close proximity*, *actual fact*, *very unique*. One word survives.

**Buried lead.** A key idea surrounded by qualifications, provenance and asides gets missed. Give it its own sentence and its own line.

**Excess evidence.** Three examples where one carries it (cut to one, never to none; see pass 2 of `SKILL.md`). A caveat already implied by the sentence. A restatement after the point is clear. Stop when the reader is convinced.

**Hedging.** Hedge and hype in one sentence ("may potentially deliver significant improvements") fail twice. *Somewhat*, *fairly*, *arguably*, *it seems*, *in some sense*, *may potentially*, *tends to generally*. A hedge that qualifies a claim honestly is fine — *in most cases*, *under load above 200 TPS* — because it says which cases. A hedge that only lowers confidence weakens the writer without informing the reader. If the claim is uncertain, say what would settle it.

**Filler intensifiers.** *Very*, *really*, *quite*, *actually*, *basically*, *essentially*, *truly*, *clearly*, *obviously*. An adverb propping up a weak verb ("significantly improves") wants the number or a stronger verb. Most add nothing; *clearly* and *obviously* often mark the spot where an argument is missing.

**Nominalization.** A verb buried inside a noun drags a weak verb and a preposition along with it.

> "The implementation of the change resulted in a reduction in latency."
> → "The change reduced latency."

Look for *-tion*, *-ment*, *-ance*, *-ity* paired with *make*, *give*, *provide*, *perform*, *conduct*, *achieve*.

## Sentence structure

**Long sentences.** Outside technical text there is no hard limit; a long sentence can be built to read well. Check every sentence over about 30 words. Keep it if it runs in reading order or is a list the reader can count. Split it if it fails one of the entries below: Subclause overload, Front-loaded openings or Subject far from its verb. Technical text keeps the limits in `technical-docs.md`.

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

**Subject far from its verb.** The reader holds the subject in mind until the verb arrives. Keep the two close. Move a long modifier after the verb, or into its own sentence.

> "The migration, which the platform team scheduled after the vendor's audit closed and the second-wave budget was approved, starts on 3 November."
> → "The migration starts on 3 November. The platform team scheduled it after the vendor's audit closed and the second-wave budget was approved."

**Weak ending.** Readers weight the end of a sentence. Open on what the reader already has, as the subject (see [Transitions](#flow-and-rhythm)), and close on what is new. A sentence that ends on its source or a hedge spends its strongest position on its weakest part.

> "The pilot cut cost by 40%, according to finance's March figures."
> → "Finance's March figures show the pilot cut cost by 40%."

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

## Language quality

**Jargon.** Two kinds. Domain terms the audience shares are precise and belong. Terms borrowed to sound expert do not.

**Buzzwords.** *Leverage*, *synergy*, *holistic*, *robust*, *seamless*, *best-in-class*, *utilize*, *operationalize*, *going forward*, *at the end of the day*, *paradigm shift*. Each has a plain equivalent, and most are claims without evidence: *robust* and *seamless* need a number or a mechanism. Self-praise (*comprehensive*, *thorough*, *rigorous*, *carefully designed*, *best practice*) claims something about the work, not in it.

**Clichés.** *Low-hanging fruit*, *move the needle*, *boil the ocean*, *the elephant in the room*, *a perfect storm*, *tip of the iceberg*. A dead metaphor makes the reader skim.

**Tense consistency.** Pick a frame and hold it. Standing behaviour in the present (*the service retries*), completed events in the past (*the migration ran overnight*), planned work in the future or a modal (*the team will*, *the team must*). Drifting between them makes a plan read as a report.

**Pronoun consistency.** Decide who *we* is and keep it. Do not switch between *we*, *the team*, and *one* for the same actor. Use *they* for a singular person of unstated gender rather than *he or she*, and never infer someone's pronouns from their name.

**That overuse.** Delete *that* where the sentence reads cleanly without it (*we found that the queue drained* → *we found the queue drained*), but keep it where dropping it causes a momentary misreading. Distinguish restrictive *that* from non-restrictive *which*, and use *who* for people.

## Audience awareness

**Assumed agreement.** Writing that treats a contested position as settled loses a reader who does not share it. State the position, give the reason, and let the reader follow.

**Respect.** Do not explain what the audience knows — it reads as condescension. Do not skip what they do not — it reads as showing off. Where a reader's decision or work is being criticised, address the substance and not the person.

**Beauty without pretension.** Aim for prose that is a pleasure to read because it is clear, well-paced, and exactly weighted — not because it is decorated. When you notice your own phrasing being admired, cut it.

## Tells of machine-drafted prose

None of these is a grammatical error, which is why the earlier passes leave them standing, and a machine reader would not care about any of them. A human notices them within two paragraphs, concludes that nobody actually wrote this, and discounts the content from there on. Run this pass last, and always on prose you drafted yourself.

The numbers are stable IDs. Other skills cite them as *writing-editor tell N*. A removed tell leaves a gap, and a new tell takes the next free number.

Retired numbers, each covered elsewhere: 6 (Throat-clearing), 11 (*Restraint* in `SKILL.md`), 13 (*Current final state* in `SKILL.md`), 14 (Hedging), 15 (Buzzwords), 16 and 27 (*Claims* in `SKILL.md`), 17 (Vary length), 18 (*Answer early* in `SKILL.md`), 26 (Filler intensifiers).

### The five most common, with examples

**1. The rule of three, applied everywhere.** Three adjectives, three clauses, three bullets, whatever the subject actually has. Count the real points and use that number; two is a fine number, and so is one.

> "The design is clear, scalable, and maintainable."
> → "Each module owns one schema, so a change lands in one place."

**2. Not just X, but Y.** Also *It's not about X, it's about Y* and *X isn't merely Y — it's Z*. The frame promises a reversal and delivers emphasis.

> "This isn't just a migration — it's a re-architecture."
> → "The migration also replaces the scheduler."

**3. Heading echo.** The first sentence restates the heading in different words, spending the most-read line in the section on nothing.

> "## Rollback is untested
> Rollback has not been tested end to end."
> → "## Rollback is untested
> The plan has been walked through on paper twice; no one has run it against a restored database."

**4. A sentence that could be anywhere.** It names a feeling instead of a mechanism. The test: if the sentence could appear unchanged in another project's documents, it says nothing about this one. Ask what it tells the reader to do or know, and write that as a mechanism, a fact or a number. If you cannot, cut it.

> "The query layer keeps SQL close at hand and easy to read."
> → "`.toSQL()` returns the exact string sent to the database."

**5. Over-compression.** Arrows, symbol-speak, dropped articles, verbless fragments, and private abbreviations that make the reader decode instead of read. Common in table cells and bullets.

> "Parser rejects bad date → exit 2, no write."
> → "The parser rejects a bad date, exits with code 2, and writes nothing."

### The rest, one line each

**7. Sections padded to equal length.** An outline filled in rather than an argument written. Let the section that matters run longer, and delete the one that exists for symmetry.

**8. A summary that adds nothing.** "In summary, the three factors above…" Keep a closing only when it states something new: the consequence, the decision, or who does what next.

**9. Emphasis inflation.** Bold on every third phrase, italics on ordinary words, em dashes as the only punctuation between clauses. Bold marks the one thing a skimmer must not miss.

**10. Inline-header lists.** A bold label and a colon that restate the line: "**Performance:** Performance improved…". Write it as prose. A bold lead-in that ends in a period, names the item and is followed by new detail is fine.

**12. Sweeping frames.** *In today's rapidly evolving landscape*, *As organizations increasingly…*, and closings about journeys, foundations, unlocking and empowering. Cut to the specific claim, or cut the sentence.

**19. Machine vocabulary.** *Delve*, *tapestry*, *pivotal*, *underscore*, *testament*, *intricate*, *garner*, *crucial*, *vibrant*, *interplay*, *landscape* used abstractly, *Additionally* to open a sentence. Use the plain word.

**20. Abstract metaphor nouns.** *Substrate*, *surface* (as in "API surface"), *primitive*, *harness*, *vector*, *wedge*, *locus*, *nexus*, *scaffolding*, *ratchet*, *north star*, *flywheel*, *endgame*. They sound technical and name nothing. Use the concrete word: base, add, method, the mechanism's real name.

**21. Mannered prose.** Aphorisms ("wire it or delete it"), fragments for effect, personified code ("the plan holds it"), figurative verbs ("rides along", "stands on"). Say it literally.

**22. A fancy way to say "is".** *Serves as*, *stands as*, *boasts*, *features*. Write "is" or "has".

**23. A trailing -ing phrase.** "…, highlighting the need for…", "…, ensuring that…", "…, reflecting…". Cut it, or make it a sentence with a subject and a source.

**24. A colon as a connector.** A colon belongs before a list, an example or a definition. Mid-sentence, as a hinge between two clauses, it is a crutch. Make two sentences.

**25. False ranges.** "From X to Y" where X and Y sit on no real scale. List the items.

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
