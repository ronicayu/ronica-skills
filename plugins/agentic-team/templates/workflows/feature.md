---
name: feature
description: New user-visible behaviour or a new capability that needs product scope and a design before code. Several tasks, possibly parallel.
stages:
  - {id: prd}
  - {id: ux, optional: true, after: [prd]}
  - {id: spec, after: [prd, ux]}
  - {id: impl, after: [spec], split: true}
  - {id: test, after: [impl]}
---
## When to use
The request names an outcome, not a change: "users can ...", a new page, a new API surface, a
new integration. Not for a change whose scope is already decided (change) or a defect (fix).

## Steps
1. Include `ux` when the work decides an interaction flow, user path or information architecture.
   Skip it for layout and style that follow an existing design.
2. The prd states the outcome as behaviour and acceptance; it never names files.
3. At the spec approval, split impl along the spec's phase table: one part per phase, its
   files as SCOPE, with the spec path and commit in the notes. Do not split by estimate alone.
   Give each part its own files; where parts share files, record the order as a dependency.
4. Each user-visible part lists the states to screenshot and adds one hour to its estimate.

## Stage notes
### spec
Name each phase's files or directories and a check that fails when the phase is wrong.
### test
Exercise every instance acceptance line on the real surface; paste the evidence.
