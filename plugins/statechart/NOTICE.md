# Notice: vendored code

This plugin packages the statechart skill from poteto's pstack. Most of its
files are upstream files, copied unchanged. This file records what comes from
where, what we changed, and how to update the copy.

## Source

| Item | Value |
| --- | --- |
| Repository | https://github.com/cursor/plugins |
| Path | `pstack/skills/statechart` |
| Commit | `bb68f2365eceafa0cb2d253112f675acf5f144cc` (2026-11-03) |
| Author | Lauren Tan (poteto) |
| License | MIT, "Copyright (c) 2026 Lauren Tan" (`pstack/LICENSE`) |

`LICENSE` in this folder keeps the upstream MIT text and copyright line, and
adds a copyright line for our additions.

## What is vendored

All paths are under `skills/statechart/`.

| File | Status |
| --- | --- |
| `SKILL.md` | Upstream, with additions (see below) |
| `references/render.md` | Upstream, unchanged |
| `scripts/statechart` (the runner) | Upstream, unchanged |
| `scripts/statechart.ts`, `worker.ts`, `pipeline.ts`, `ir.ts` | Upstream, unchanged |
| `scripts/run.ts` | Upstream, one type annotation (see below) |
| `scripts/frontends/`, `scripts/passes/`, `scripts/backends/` | Upstream, unchanged |
| `scripts/package.json` | Ours, replaces upstream's (see below) |
| `scripts/tsconfig.json` | Upstream, unchanged |
| `scripts/setup.sh` | Ours |
| `scripts/render.mjs` | Ours |

Left out: `scripts/test/`. It is a large test corpus, and it needs Java.
Our `scripts/package.json` therefore has no `test` script and no `fast-check`
dev dependency.

## What we changed

Two changes to upstream code, so that `tsc --noEmit` passes in CI:

- `scripts/run.ts`: `exitClass` declares its return type,
  `CheckResult["exit"]`. Without it the inferred `0 | 1 | 2` widened to
  `number` inside the result object, and `tsc` reported two errors. Behaviour
  is unchanged.
- `scripts/package.json`: a `typecheck` script (`tsc --noEmit -p .`) and the
  dev dependencies it needs, `typescript` and `@types/node`, at exact
  versions. Upstream's `test` script and `fast-check` are removed, because
  `scripts/test/` is not vendored.

Upstream's `SKILL.md` has additions:

- The frontmatter keeps the name `statechart`. It drops upstream's
  `disable-model-invocation: true`, so that Claude and other agents can pick the
  skill up, and its description says when: a change to state-machine or
  lifecycle logic, a request to model-check a flow, or a change to code that a
  repository already models with the skill.
- An attribution paragraph after the `# Statechart` heading.
- A new section "Setup without mise" after "Run". It uses the runner's own
  `TLA2TOOLS` and `JAVA` variables, and points to `scripts/setup.sh`.
- Five new sections after "Hand off": "Model code you maintain", "Peel one
  dead end per round", "Keep the state space small", "Render with the bundled
  script", and "Run it from Claude Code".

No upstream line is removed or edited. To see our additions, diff our
`SKILL.md` against the upstream file at the commit above.

Our two scripts:

- `scripts/setup.sh` downloads tla2tools.jar v1.7.4, checks the sha256 that
  upstream `scripts/run.ts` gives mise, checks for Java and a TypeScript
  runtime, and prints the `TLA2TOOLS` and `JAVA` exports.
- `scripts/render.mjs` renders a `chart.mmd` with Pele. It uses the CSS of
  `references/render.md` with the bug marks moved after `bugPath`. It
  leaves out the `bugPath` border when `report.md` says that the chart draws
  only the bug paths.

## Update the vendored copy

1. Fetch the new upstream commit with a sparse checkout, outside this repo:

   ```sh
   git clone --filter=blob:none --no-checkout https://github.com/cursor/plugins cursor-plugins
   cd cursor-plugins
   git sparse-checkout set pstack/skills/statechart pstack/LICENSE
   git checkout <new-sha>
   ```

2. Read the upstream diff since `bb68f23`, mainly for `SKILL.md`, `run.ts`
   (the TLC version and checksum), and `references/render.md` (the CSS).
3. Copy `references/render.md` and every file in `scripts/` except `test/`
   and `package.json` over ours. Leave `scripts/setup.sh` and
   `scripts/render.mjs` in place. Then make the `run.ts` change again if
   upstream has not, and run `npm install && npm run typecheck` in `scripts/`.
4. Check that only our two scripts differ:

   ```sh
   diff -r --exclude=test <upstream>/pstack/skills/statechart/scripts plugins/statechart/skills/statechart/scripts
   diff <upstream>/pstack/skills/statechart/references/render.md plugins/statechart/skills/statechart/references/render.md
   ```

   The first command must list only `setup.sh`, `render.mjs`,
   `package.json` and `run.ts` (the one `exitClass` line). The second
   must print nothing.
5. Merge the upstream `SKILL.md` changes into ours. Keep our attribution and
   sections, and check them against the new upstream text.
6. If upstream changes the TLC version or checksum in `run.ts`, change
   `scripts/setup.sh` and the "Setup without mise" section to match. If it
   changes the CSS in `references/render.md`, change `scripts/render.mjs`.
7. Update the commit and date in this file, in `README.md`, and in the
   `SKILL.md` attribution link. Bump the plugin version in
   `.claude-plugin/plugin.json` and in the marketplace entry.
