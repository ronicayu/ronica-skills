---
name: fix
description: A defect whose cause is known or findable, where the fix may touch an interface or need a short design. A spec stage is added when the fix changes a contract.
stages:
  - {id: spec, optional: true}
  - {id: impl, after: [spec]}
  - {id: test, after: [impl]}
---
## When to use
A defect that is larger than a hotfix: the fix crosses areas, changes an interface or a data shape,
or the cause needs a design choice. Not for a defect with an obvious one-area fix (hotfix), and not
for new behaviour (change or feature).

## Steps
1. Include `spec` when the fix changes an interface, a data model, or the way two parts talk to each
   other. Skip it when the cause and the fix are both clear from the repro.
2. Put the repro in ACCEPTANCE as a test that is red at base and green at head.
3. Merge small same-area fixes into one instance; many tiny PRs cost more than they save.
