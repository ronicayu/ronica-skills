# Design critique

Whether the design is right, not whether the document is complete. Run the steps in order. Each step produces an output the reader can check. Think inside each step; do not turn it into a list of boxes ticked.

Security is out of scope here. It has its own review.

## Rules for every step

- **Depth follows risk.** The top-ranked goals, the irreversible decisions and the paths that touch money, data loss or users get a full trace. A low-ranked goal gets a line.
- **Every finding names the scenario that breaks the design**: the input, the load, the failure or the sequence of events, and what goes wrong.
- **Mark each finding verified or suspected.** Verified: shown by arithmetic on the document's own numbers, or by a path traced through the document's own mechanisms. Suspected: plausible, but needs evidence; say which evidence would settle it. A fact from outside the document (a product's limit, a transport's guarantee) makes a finding suspected until the document or a source confirms it.
- **Rate the consequence.** **Design fails**: a goal or NFR is not met, or two parts contradict. **Risky**: the design depends on something fragile, or a failure is unhandled. Completeness gaps belong to the review checklist, not here. But if the document is silent on a step 3 or 4 question for a main flow, the finding is risky and suspected, and the evidence needed is the answer. The checklist counts failure modes; step 4 tests each one.
- **Challenges are the reviewer's.** You may raise a risk, an alternative or a simpler design, labelled as your challenge. Never write it into the document as fact, and never invent figures: where a number is missing, the finding is that it is missing.

## Step 0: Is it solving the right problem?

Compare the problem statement with the request and the sources: the requirements, the brief, the owner's own words. Then check that the outcomes trace to that problem, and that the design serves the outcomes.

**Wrong** needs a contradiction with a source. A cause or a smaller scope you suspect, but the sources do not name, is a challenge for the report, not a stop. The problem is wrong when any of these holds:

- The design solves a different problem from the one the sources state.
- It treats a symptom, and the sources point to a cause it leaves alone.
- The scope is wrong: smaller than the problem needs.
- No problem is stated, and none can be recovered from the sources.
- The design serves none of the outcomes.

**If the problem is wrong, stop.** Report what you found, with the evidence on both sides, and ask the user to confirm the problem. Run no later step.

**If the problem is unclear but plausible** (no source contradicts it, but none states it), state the problem you assume at the top of the report, ask the user to confirm it, and continue.

**If it holds**, say so in one line and continue.

## Step 1: Trace each goal to its mechanism

One row per ranked goal and per Committed or Blocking NFR:

| Goal or NFR | Target or measuring NFR | Mechanism that delivers it | Scenario walked | Verdict |
| --- | --- | --- | --- | --- |

- **Mechanism**: the specific parts of the design that deliver the goal, not the goal restated.
- **Scenario**: the stated peak workload, plus one realistic failure. Walk it through the mechanism step by step.
- **Verdict**: **holds** only when shown by arithmetic or a traced path, as for a verified finding; **fails** (and the scenario); otherwise **can't tell** (and the missing evidence).
- **Check the arithmetic** wherever the document gives numbers: capacity against peak load; the latency budget summed along the path; quotas and rate limits against throughput; cache lifetimes and polling intervals against freshness or stop-time targets; batch size times per-item time against deadlines; storage growth against retention; cost at the stated volume.

A goal with no mechanism fails. A mechanism that delivers no goal is a completeness finding (checklist: every element traces).

## Step 2: Look for contradictions

Read across sections for claims that cannot all be true:

- A constraint that a decision quietly breaks.
- A guarantee that holds for one option or mode but is stated for all.
- Two sections that describe the same flow, owner or limit differently.
- An assumption that, if false, breaks a goal: name the goal and what fails.

Each finding cites both places.

## Step 3: Check the structure

- **Ownership.** Each piece of data has one writer. Shared tables, or two parts writing the same record, are findings.
- **Coupling.** Find synchronous call chains and cycles between parts. A chain of synchronous calls multiplies latency and failure; a cycle makes independent deployment impossible.
- **Invariants and transactions.** For each business rule that must always hold, find where it is enforced. A rule that spans two transaction boundaries needs a saga, a reservation or a reconciliation, and the design must say which.
- **Consistency.** Each read that drives a decision (send, charge, delete, approve) must see data fresh enough for that decision. Eventual consistency is fine for a report and wrong for a guard.
- **Blast radius.** For each shared component (database, queue, cache, identity provider, platform service), say what stops when it stops.

## Step 4: Check failure behaviour

For each main flow, and for each dependency it calls:

- **Slow, down, at quota.** What happens in each case, how it is detected, and what the user sees.
- **Retries.** Bounded, with backoff and jitter? Can retries from many callers make an outage worse?
- **Idempotency.** Can every retried operation run twice safely? Where is the key, and how long is it kept?
- **Ordering and duplicates.** Does anything assume ordered or exactly-once delivery that the transport does not give?
- **Poison messages.** Does one bad message block a queue, and where does it go?
- **Backpressure.** When input outruns processing, what queues, what is shed, and what is the limit?
- **Recovery.** Can backup, replay or failover meet the stated RPO and RTO? What is lost at the RPO?
- **Cutover.** After the new system has written data, can rollback keep it, and does the dual-run comparison catch drift before decommission?

## Step 5: Check the decisions

- **Under the ranking, is the chosen option best?** Re-run the comparison with the stated goal order. A choice that only wins under a different order is a finding.
- **Was the rejected option real?** A strawman alternative means the real choice was not made in the document.
- **Is there a simpler design** that meets the top goals? Name it as your challenge.
- **What is hard to reverse?** Data models, public contracts, vendor commitments and identity schemes. Each needs stronger evidence than a reversible choice.

## Step 6: Can this team deliver and run it?

Compare the design with the team's stated size, skills and timeline, and with who will run it. Count the moving parts to build, operate and be on call for. A design that only a larger or more experienced team could run is risky, whatever its other merits. If the team is not stated, the output is can't tell, and the evidence needed is the team.

## The report

1. **Step 0 verdict**, in one line, or the stop and the question.
2. **The goal trace table.**
3. **Substance findings**, grouped by step, design fails before risky, each with its scenario, verified or suspected, and the fix or the evidence needed. A step with no finding gets one line naming what was walked.
4. **Completeness findings** from the review checklist.
5. **Polish**, handed to `writing-editor`.
