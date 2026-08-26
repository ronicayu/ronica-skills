---
name: skill-name
description: What this skill does, then when to use it — the concrete asks, phrasings, and situations that should pull it in. This text is the only thing the model sees when deciding whether to load the skill, so spend it on triggers rather than philosophy. Keep it under 1024 characters.
---

# Skill Name

One sentence on what this skill gives the agent that it lacks by default.

## When to use this

- The situations that should trigger it.
- Any adjacent cases that should *not*, if the boundary is easy to get wrong.

## Process

1. First step, phrased as an instruction to the agent.
2. Second step.
3. Third step.

State gates explicitly if the skill has them — for example, "do not write body
prose until the outline is approved." Soft phrasing gets skipped.

## References

Load these only when the step calls for them, so the main file stays small:

- `references/example.md` — what it covers and when to read it.
