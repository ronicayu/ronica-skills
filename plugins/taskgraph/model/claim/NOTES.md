# The claim model

`Claim.tla` models the claim protocol of `tg start N` on a GitHub project: section 8.1 of `docs/plans/2026-11-08-taskgraph-github-backend-spec.md`. It was checked on 2026-11-09 with the statechart plugin (TLA+ and TLC), before PR 3 implemented the protocol. The first draft of section 8.1 let two Managers hold one task; the revised section 8.1 is the protocol that holds every rule here. When PR 3 or a later change touches the claim code (`tgstore/github/remote.py` `claim`), update the model and rerun every config.

## What the model holds

- One issue, two claimants (`m1`, `m2`), up to `MaxTries` runs of `tg start` each.
- `comments`: the claim comments on the issue. Each has an `id` (increasing), an `owner`, `voids` (the id of the claim it voids, or 0) and `claim` (FALSE when a loser kept only the void marker).
- `open`, `label`: the issue state and the `tg:in-progress` label.
- `aged`: the comments older than 60 s. Time is one bit per comment. `Age` makes one comment old at any moment; with `ALLOW_STALL = FALSE` only while no claimant is between its steps (no `tg start` pauses 60 s).
- `closedOver`: the comments posted before a close of the issue (GitHub: `created_at < closed_at`).
- `pc`: the step each claimant is at. `mine`: the comment of its current run. `vid`: the stale claim its next comment voids.
- Reads: `Reads(m)`. Without lag a read returns every comment. With `ALLOW_LAG` and `LAG_PREFIX` a read can miss comments newer than every comment it must hold (the spec's property 2: a read that holds my comment holds every lower id). With `ALLOW_LAG` alone it can miss any comment but my own.

## Actions and the steps they model (spec section 8.1)

| Action | Step |
|---|---|
| `Begin` | 1-6: read the claims, find the active claim, decide: held by me (5), held by another (6), or post (7) |
| `Post` | 7: one comment, voiding the stale claim if there is one |
| `Decide` | 8-9: read again; I win when the lowest unvoided claim is mine |
| `Confirm` | 10: the confirm read |
| `Patch`, `PatchFails` | 10 (and 5): PATCH open + label; the PATCH can fail and leave the claim without a label |
| `Done`, `Reopen` | the holder's `tg done` (close, label off) and `tg reopen` (label off) |
| `Retry` | a refused or failed run ends; the Manager can run `tg start` again |
| `Age` | 60 s pass for one comment |
| `PersonRemovesLabel`, `PersonCloses` | a person in the GitHub UI (`ALLOW_PERSON`) |
| `Verify` | an alternative fix, not in the spec (`FIX_VERIFY_AFTER_PATCH`) |

## Rules

| Rule | In words |
|---|---|
| `OneHolder` | At most one Manager believes it holds the task. |
| `HolderIsActive` | A Manager that believes it holds the task is the one GitHub shows as the holder (its claim is the active claim). |
| `DoubleHoldIsVisible` | When two Managers hold the task, two unvoided claims stay, so a refresh can show a claim conflict. |
| `LoserLeavesNoClaim` | A Manager that lost leaves no claim of that run behind. |
| deadlock | No state is stuck: every run of `tg start` ends. `Finished` is the end state. |

## The switches

`FIX_*` switches turn the first draft into the revised protocol, one change each:

| Switch | Change in section 8.1 | Needed |
|---|---|---|
| `FIX_STALE_NEEDS_AGE` + `FIX_CLOSE_STAMP` | step 4: stale = older than 60 s AND (no label, or closed after the claim) | yes (`regress-close-stales-at-once`) |
| `FIX_KEEP_VOID` | step 9: a loser whose comment voids a claim keeps the void | yes (`regress-loser-deletes-void`) |
| `FIX_OWNER_REUSE_YOUNG` | step 5: reuse my claim only while it is younger than 60 s | yes (`regress-owner-reuses-old-claim`) |
| `FIX_CONFIRM_ACTIVE` | step 10: the confirm read uses the step-8 check | not needed by these rules once the three above are on; kept because it is the simpler code (one check) |
| `FIX_CLOSE_PERMANENT` | a close or a label removal ends every earlier claim at once (issue events API) | not needed; tried and dropped |
| `FIX_HOLD_CONFIRM` | step 5 also does a confirm read | not needed; tried and dropped |
| `FIX_VERIFY_AFTER_PATCH` | a read after the label PATCH | does not close the 60 s pause window; dropped |

`ALLOW_*` switches turn on what the world can do: `ALLOW_LAG`, `LAG_PREFIX`, `ALLOW_AGE`, `ALLOW_STALL`, `ALLOW_PATCH_FAIL`, `ALLOW_PERSON`.

## Configs and their results (2026-11-09)

| Config | Must | Result |
|---|---|---|
| `check-nolag.cfg` | hold | every rule holds, 183,062 states, 3 runs per claimant |
| `check-lag.cfg` | hold | every rule holds, 592,300 states, 3 runs per claimant, reads with property 2 |
| `regress-spec-as-written.cfg` | break | first draft: `OneHolder`, `HolderIsActive`, `DoubleHoldIsVisible` break with no lag and no pause (path below) |
| `regress-close-stales-at-once.cfg` | break | revised protocol with step 4 as in the first draft |
| `regress-loser-deletes-void.cfg` | break | revised protocol with step 9 as in the first draft |
| `regress-owner-reuses-old-claim.cfg` | break | revised protocol with step 5 as in the first draft |
| `accepted-stall.cfg` | break | a `tg start` pauses 60 s between its claim and its PATCH; not guaranteed (spec 8.3) |
| `accepted-person.cfg` | break | a person removes the label or closes the issue; not guaranteed |
| `accepted-lag-any.cfg` | break | reads miss older comments (property 2 fails); not guaranteed |

When a `regress-*` or `accepted-*` config stops breaking, the model has gone blind: find out why before you trust a `check-*` run.

### The paths that broke the first draft

1. `regress-spec-as-written`: m1 holds, runs `tg done` (closed); m1 runs `tg start`, posts c2 voiding its own c1, passes its confirm read; m2 runs `tg start` while the issue is still closed, reads c2 as stale (step 4: "stale when the issue is closed"), posts c3 voiding c2 and wins; m1's PATCH lands. Both hold; only c3 is unvoided.
2. `regress-loser-deletes-void` (found with the close fix on): a loser deletes its comment, which also voided a stale claim; the stale claim is active again; GitHub shows its owner as holder, and that owner passes step 5 later and holds too.
3. `regress-owner-reuses-old-claim` (found with lagging reads): m1's PATCH fails; after 60 s m2 voids m1's claim and wins; m1 runs `tg start`, its read misses m2's newer comment, so m1's claim looks active and step 5 reuses it.

## Run

Setup once: `plugins/statechart/skills/statechart/scripts/setup.sh` (tla2tools.jar, Java). Then, from this folder, with a new `--out` folder per run:

```sh
RUNNER=../../../statechart/skills/statechart/scripts/statechart
for c in check-nolag check-lag regress-spec-as-written regress-close-stales-at-once regress-loser-deletes-void regress-owner-reuses-old-claim accepted-stall accepted-person accepted-lag-any; do
  TLA2TOOLS=$HOME/.cache/statechart/tla2tools.jar JAVA=/opt/homebrew/opt/openjdk/bin/java \
    $RUNNER Claim.tla --config $c.cfg --view view.mjs --out /tmp/claim-$c-1
done
```

The check configs take about a minute each. Every state count is above the chart budget (500), so the charts draw only bug paths.
