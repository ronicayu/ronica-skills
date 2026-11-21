---
name: hotfix
description: A defect with a known or quickly found cause, fixed inside one area with no design choice. Repro test first, then the fix.
stages:
  - {id: impl}
  - {id: test, after: [impl]}
---
## When to use
A failing behaviour you can reproduce, in one area, with an obvious fix shape. Not when the fix
changes an interface, data model, money or permissions (hard rules), or when the cause is unknown
after a short look (use fix or figure-it-out).

## Steps
1. Put the repro in ACCEPTANCE as a test that is red at base and green at head.
2. No optional stages. A worker census that touches more than its area escalates to fix.

## Stage notes
### impl
Commit the failing test before the fix, so history shows red, then green. Ship the smallest change the evidence supports.
