---
name: principle-decision-forks
description: "Apply when about to ask the operator a 'which approach', 'how should I', or 'what should this do' question, or when applying the autonomy grant (autonomy.grant) or an autonomy.always_pause gate. Classify the fork first: observe, investigate, or ask."
disable-model-invocation: true
---

# Decision forks

Before you ask the operator to choose an approach or define behavior, classify
the question.

1. **Observable fact.** If running something can answer it (behavior, timing,
   layout, output, performance, or whether an evaluation separates the
   options), run a focused experiment and let the result decide. It is not the
   operator's question.
2. **Read-only investigation.** If the deliverable is a cited answer, stay in
   the investigation and answer from evidence. Do not build a sketch to
   compare options.
3. **Product or preference call.** Only a call that no experiment or
   investigation can settle goes to the operator.

## Apply the autonomy grant

Read `autonomy.grant` and `autonomy.always_pause` with
`"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" get <key>`. An empty grant
means there is no standing grant.
Follow the grant only within its stated scope.

- **Covered by the grant.** Decide, act, and report what you chose. Do not ask
  for a reply or offer a menu.
- **Covered, but only the operator can make the call.** Apply a reasonable
  default. Report it with a full explanation, and say in plain words what the
  operator could tell you to do instead.
- **Not covered.** Ask. Let the operator answer in their own words. Never give
  a shorthand token to type back.
- **Gates.** Every gate in `autonomy.always_pause`, and every gate the operator named, needs
  the operator, even under the grant.

## Who applies it

- The Manager asks through a gate entry, batched into its report, and routes
  other work around the open gate.
- A worker never asks the operator. It runs an experiment only when its brief
  allows one, and reports anything else as `BLOCKED` with the question.

When this principle changed a decision, name it and the choice it changed.
