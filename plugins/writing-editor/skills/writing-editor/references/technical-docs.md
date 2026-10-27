# Technical docs

Extra rules for technical text. They apply to product and developer documentation (tutorials, how-tos, reference, explanation), READMEs, RFCs, PR descriptions, commit messages, and issues. They do not apply to other prose. There, the defaults in `SKILL.md` hold, including "preserve voice". For technical text, these rules take precedence over voice. Where this file and `references/line-editing-checklist.md` differ, this file wins for technical text.

Contents: [Pick the mode first](#pick-the-mode-first-diátaxis) · [Sentences to the reader](#sentences-to-the-reader-google-developer-style) · [One statement at a time](#one-statement-at-a-time-ste) · [No double readings](#no-double-readings-global-english) · [The codebase is the word list](#the-codebase-is-the-word-list) · [PRs, commits, and issues](#prs-commits-and-issues) · [Convention for issues, PRs, and commit message bodies](#convention-for-issues-prs-and-commit-message-bodies) · [Worked example](#worked-example)

Pick the mode (for documentation) in pass 0, before you change any text. Apply the shape and heading rules in pass 1 of `SKILL.md`, and the sentence rules in passes 4 and 5.

## Pick the mode first (Diátaxis)

One document has one mode. Two questions pick it.

- Does the content inform action (doing) or understanding (thinking)?
- Does it serve learning or work?

The answers give four modes:

- Action and learning: **tutorial**.
- Action and work: **how-to**.
- Understanding and work: **reference**.
- Understanding and learning: **explanation**.

Ask the two questions of a whole document or of one sentence. A sentence in the wrong mode is the one to move.

**Tutorial: learning by doing.** The writer owns the learner's success. Open by saying what the learner will build, not what they will "learn". Make every step produce a visible result, early and often. Say what the learner should see: the output, the prompt change, the log line. Cut explanation to one clause and a link. Stay concrete. Write "we" and commands: "First, run x. Now, run y."

**How-to: steps to a goal.** Solve a problem a person has, not an operation the machine can do. Assume the reader is competent and do not teach. Give action only. Leave out digressions, background, and completeness for its own sake. Link to them instead. Allow forks and judgment: "If you want x, do y." Name the guide by its task: "How to rotate an API key", not "API key rotation".

**Reference: facts for lookup.** Describe and nothing else. No instruction, no persuasion, no opinion. Be dry, complete, and sure. State facts, options, limits, and errors without hedging. Mirror the structure of the thing described, so the reader can move through code and docs together. Put each fact where the reader expects it. Generate the text from the code where you can.

**Explanation: understanding and why.** Cover one bounded topic that a reader can read away from the product. Each title should tolerate an implicit "About..." in front. Anchor the text on a real why question. Give context: decisions, history, constraints, alternatives. Of the four modes, only explanation allows opinion. Say what you make of the trade-offs instead of listing pros and cons. Be specific over sterile: "a column rename fails the build", not "schema changes can cause issues".

Do not mix modes. No reference tables in a tutorial. No tutorial hand-holding in reference. No arguing in a how-to. Split the document and link the parts instead.

**How the mode combines with the pyramid.** Pick the mode first. Explanation uses the pyramid: answer first, then the reasons. A how-to states the goal, then gives the steps in time order. A tutorial runs in time order, with a visible result for each step. Reference mirrors the structure of the thing it describes. Reports, proposals, and design docs are not Diátaxis docs. They use the pyramid alone. RFCs are design docs. Skip the mode step for them.

## Sentences to the reader (Google developer style)

- Talk to the reader as "you", in the present tense. Use "will" only for things that happen later.
- Say who does what: "the compiler checks the file", not "the file is checked". The passive is fine only when the actor is unknown or does not matter.
- Write instructions as commands: "Click **Submit**." State facts plainly. Never write "should be done".
- Put the condition before the instruction: "To delete the document, click **Delete**."
- Put the common case first and the exceptions after it.
- Sound like a knowledgeable friend. Use no buzzwords and no figurative language. Never write "please" in an instruction. Never write "simply", "easy", or "quickly" in a procedure. If the task were simple, the reader would not be reading.
- Do not pre-announce ("we will soon support..."). Do not start consecutive sentences with the same phrase.
- Make link text say where the link goes: the page title or a short description. Never write "click here". Prefer one sentence of context on the page over a link off it.
- Write a task heading as a bare verb phrase in sentence case: "Create an instance". Write a concept heading as a noun phrase. Use one h1 per page. Skip no heading levels. (Headings that carry a message are covered in pass 1 of `SKILL.md`. In a tutorial, how-to, or reference page, the standard heading forms above win.)
- Use a numbered list for a sequence and a bulleted list for other parallel items. Keep reasoning in prose. Introduce a list with a full sentence. Keep the items parallel.
- Put code in code font and UI elements in bold. Use serial commas. Do not write "etc.". Say up front that a list is partial.

## One statement at a time (STE)

- Give one instruction per sentence. Give one thought per sentence everywhere else.
- Split an instruction that is longer than about 20 words. Split any other sentence that is longer than about 25.
- Put the warning or the condition before the step it guards: "If hot oil touches your skin, injuries can occur."
- Keep "the" and "a". "Remove backup file" reads two ways. "Remove the backup file" reads one way.
- Give each word one meaning and one job, and keep them. If "check" means inspect, do not also use it to mean restrain.
- Use one word per action. Write "start" every time, not "start" in one place and "initiate" in another.
- Write a procedure as direct commands. Never use the passive and never use narration: "Install the component", not "The component must be installed".
- Avoid "-ing" forms where you can.

## No double readings (Global English)

- Keep "only" and "not" next to the word they change. "It fails only on growth" and "It only fails on growth" say different things.
- Break up a noun string. "The cache eviction timeout script" becomes "the script that sets the cache eviction timeout".
- Make every "it", "they", and "this" point at one thing. Repeat the noun when in doubt. Never use "this" or "which" to point at a whole clause.
- Do not drop verbs. "Phase 1 moves the converters and Phase 2 the runtime" leaves Phase 2 without a verb. Give it one.
- Keep the small words that show structure, such as "that" in "Ensure that the switch is off". Do not trade clarity for word count.
- Repeat the article in a series when that prevents a misread. Write "the client and the host", not "the client and host", when they are two things.
- Say which parts "and" or "or" joins when a sentence can group two ways. "Both...and", "either...or", and "if...then" remove the doubt.
- Use periods, not semicolons. Do not use em dashes. Write a new sentence instead.
- Make text in parentheses a full unit or its own sentence. Never form a plural with "(s)".
- Do not use slashes. Write "a, b, or both", not "a/b" or "and/or".
- Give each thing one name, everywhere. The rule is in pass 2 of `SKILL.md`.
- Do not use idioms, colloquialisms, Latin abbreviations, or metaphors.

## The codebase is the word list

Write the real symbol, file, flag, or command name. Do not write a synonym for it or a description of it.

Do not invent jargon. Use the words a developer would say out loud: "move" and "delete", not "evacuate". A named pattern is fine when the text defines it the first time it appears.

## PRs, commits, and issues

Every section of this file applies to them, except Diátaxis. These are not documentation modes, so skip the mode step.

- A PR body is a briefing that a reviewer reads in under a minute. Link logs, SHA lists, and metric tables. Do not paste them.
- Make every count or tree claim true at the commit that lands it. Include the command that regenerates it.
- Product UI strings are not documentation. Use the product's copy guidelines for them.

## Convention for issues, PRs, and commit message bodies

Write these in ASD-STE100 sentences, structured as a Minto pyramid.

- **Conclusion first.** The title states the conclusion. The first lines of the body repeat it in full.
- **Headings state their own conclusion.** "Rollback has never run against a restored database", not "Rollback".
- **Order below the conclusion:** grouped reasons, then evidence, then actions.
- **Short sentences,** about 20 words (stricter than the 25 words above). Use the active voice and simple tenses. Use no contractions.
- **Action items are imperative.** Write "must", not "should", for a requirement.
- **Code identifiers and paths stay verbatim.** Do not rephrase them. Put them in code font.

## Worked example

**Before**: a buried actor, a passive procedure, a noun string, and a misplaced "only".

> The cache eviction timeout and `max_size` configuration file parameters are set in `cache.toml` by the service. It is important to remember that the `--purge` flag, which deletes every cached entry, should only be used when the disk is full. If it is exceeded, requests will fail.

**After**:

> The service reads the eviction timeout and `max_size` from `cache.toml`. If the cache size exceeds `max_size`, requests fail. `cache --purge` deletes every cached entry. Run it only when the disk is full.

The edit makes these changes:

- The service is now the actor of the first sentence. In the Before, the passive "are set" put the actor at the end.
- The noun string "configuration file parameters" became the two values the service reads, named once.
- "It" in "If it is exceeded" could point at the flag, the disk, or the cache. The new sentence names `max_size`.
- The procedure is one direct command. The sentence that states the risk comes before it.
- "Only" now sits next to "when the disk is full", the words it limits.
- "Should only be used" became "Run it only when", a command instead of a passive.
