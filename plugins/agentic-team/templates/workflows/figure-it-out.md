---
name: figure-it-out
description: Work no other workflow fits, or that is large, cross-cutting or unclear. A short investigation designs the remaining stages first.
stages:
  - {id: investigate, decides: true, estimate: 2}
---
## When to use
Any of: (a) one PR or one timebox cannot hold it; (b) acceptance cannot be written as
checkable behaviour without code facts; (c) a design trade-off is open; (d) two or more tasks
need the same census. Also every pick where both answers were `unsure`.

## Steps
1. The investigate stage is read only. It ends with a `workflow-plan` block (below).
2. At its approval, run `run.py stage <inst> expand --from-row <row>`. Prefer a plan that names
   an existing workflow. A list of library stages is an ad-hoc workflow, reported in the
   next brief.
3. A plan that needs a stage type the library does not have is a decision for the owner,
   the only question this workflow may raise.

## Stage notes
### investigate
Define done as a falsifiable check, size the work, and list the riskiest unknown first. End
your report with:

    ```workflow-plan
    workflow: fix            # or: stages: [{id: spec}, {id: impl, after: [spec], split: true}]
    why: <one line>
    ```
