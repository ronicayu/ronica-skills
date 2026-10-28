Then check the real document against its sources, not the worker's summary
of it. Report every failure you can prove, not only the first.

### Method: design-doc

1. Sources: each factual claim (a requirement, the current state, a number)
   points to a source. Open each source and confirm the claim. An unsourced
   or wrong claim is an issue.
2. Completeness: the document has a problem statement with measurable
   outcomes and ranked goals; options with their trade-offs, including "do
   nothing"; for each decision, the alternative it rejected; failure modes;
   migration. Name each missing part.
3. Contradictions: none inside the document, and none with the other
   documents of the project that it names or depends on.
4. Compare with the base commit named in CONTEXT: `git diff <base> <head>`
   shows what changed. Flag every file or decision that changed outside SCOPE
   under `Issues:`.
5. Boundary: you do not judge whether a decision is right. That belongs to
   the operator or the design review. A finding about a decision itself is
   not an issue and does not lower the verdict. Write it under `Follow-ups:`
   as `decision: <the question, one line>`; the Manager turns it into a
   Taskgraph decision.

Verdict levels for this kind:
- `artifact-verified`: every source check is done, the document is complete,
  and no blocking finding remains. This is the only level that closes a
  design-doc task.
- `test-verified`: VERIFY passes, but the source checks are not done. It does
  not close the task.
- `check-only`: a read-through without the source checks.
- `verify-blocked`: a source could not be opened; name it.
- `verify-failed`: a claim is wrong, a required part is missing, or the
  document contradicts itself or another document.
