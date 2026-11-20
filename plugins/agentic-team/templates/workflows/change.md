---
name: change
description: A change to existing behaviour whose scope is already decided: a rule, a limit, a rename, a flow tweak. Product scope first, then code.
stages:
  - {id: prd}
  - {id: impl, after: [prd]}
  - {id: test, after: [impl]}
---
## When to use
The outcome is known and small, and only the exact behaviour needs writing down. Not when it needs
a new interaction flow or a design choice (feature), and not for a defect (fix or hotfix).

## Steps
1. The prd states the new behaviour as acceptance lines; it never names files.
2. Merge small same-area changes into one instance; a lone one-line change goes through hotfix.
3. Add a `spec` stage with `--with spec` only if the prd turns up a design question. A change that
   needs one is usually a feature.
