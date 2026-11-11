# TypeScript and JavaScript

Markers: `package.json`, `tsconfig.json`, `deno.json`. Lockfiles: `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock`, `bun.lockb`, `deno.lock`. Toolchain pin: `.nvmrc`, `.node-version`, `engines.node`, `packageManager` in `package.json`, `volta`. Workspaces: `workspaces` in `package.json`, `pnpm-workspace.yaml`, `turbo.json`, `nx.json`; treat the workspace root as one subproject and list its packages.

Package manager: from the lockfile (`pnpm-lock.yaml` → pnpm, `yarn.lock` → yarn, `bun.lock*` → bun, else npm). Use it for every command (`pnpm exec`, `yarn`, `npx`).

## Environment

ESLint (its config imports plugins), `tsc`, test runners and knip need `node_modules/`. If it is missing, `npm ci` (or `pnpm install --frozen-lockfile`, `yarn install --immutable`) writes `node_modules/` into the repo and downloads every dependency: ask about it as its own cost in step 4. Without it, run only the zero-install tools (biome, oxlint, prettier) and mark the rest "not run: no node_modules".

## Tools

| tool | category | config | tier 1 command | notes |
|---|---|---|---|---|
| `eslint` | lint | `eslint.config.*`, `.eslintrc*`, `eslintConfig` in `package.json` | `npx eslint . -f json -o <scratch>/eslint.json` (needs `node_modules`) | Count `errorCount` and `warningCount`. Baseline: ESLint 9.24+ bulk suppressions (`--suppress-all`, then `eslint-suppressions.json`), or `--max-warnings <current>` as a ratchet. `.eslintrc*` is the legacy format; ESLint 9 uses flat config. |
| `biome` | lint | `biome.json`, `biome.jsonc` | `npx --yes @biomejs/biome lint .` (the last line gives the counts) | Also formats (`biome format`, `biome check`). Works without `node_modules`. |
| `oxlint` | lint | `.oxlintrc.json` | `npx --yes oxlint .` | Zero-config and fast: good for estimating warnings when no linter is configured. |
| `prettier` | format | `.prettierrc*`, `prettier.config.*`, `prettier` in `package.json` | `npx --yes prettier --check . --log-level warn` | Lists files that would change; plugins in config need `node_modules`. |
| `biome-format` | format | `formatter` in `biome.json(c)` | `npx --yes @biomejs/biome format .` | `biome check` and `biome ci` also check formatting. |
| `dprint` | format | `dprint.json`, `.dprint.json` | `npx --yes dprint check` | |
| `tsc` | types | `tsconfig.json` | `npx tsc --noEmit -p <tsconfig>` (needs `node_modules`) | Count `error TS` lines. Record `strict`. In a monorepo use the root `tsconfig` with `references` and `tsc -b --noEmit` where the project uses it. Vite, esbuild, SWC and Bun strip types without checking: a passing build proves nothing about types. |
| `jest` | tests | `jest.config.*`, `jest` in `package.json` | the project's test script: `npm test -- --ci` | |
| `vitest` | tests | `vitest.config.*`, `vitest.workspace.*`, `test` in `vite.config.*` | `npx vitest run` | |
| `mocha` | tests | `.mocharc*` | the project's test script | |
| `playwright` | tests | `playwright.config.*` | do not run in tier 1 by default: it starts browsers and often a dev server; list it under "not checked" unless the user asks | |
| `c8` | coverage | `.c8rc*` | `npx c8 --reporter=text-summary <test command>` | Vitest: `npx vitest run --coverage` needs `@vitest/coverage-v8` installed. Jest: `--coverage`. |
| `nyc` | coverage | `.nycrc*` | `npx nyc --reporter=text-summary <test command>` | |
| `vitest-coverage` | coverage | `coverage:` in `vitest.config.*` or `vite.config.*`; CI `vitest ... --coverage` | `npx vitest run --coverage` (needs `@vitest/coverage-v8` or `-istanbul`) | `test.coverage.thresholds` fails the run below the bar. |
| `jest-coverage` | coverage | `collectCoverage: true` in `jest.config.*` or `package.json`; CI `jest --coverage` | `npm test -- --ci --coverage` | `coverageThreshold` fails the run below the bar. |
| `npm-audit` | deps_audit | (none) | npm: `npm audit --json --omit=dev`; pnpm: `pnpm audit --json --prod`; yarn 1: `yarn audit --json`; yarn 2+: `yarn npm audit --json` | Needs the network and the lockfile; no `node_modules` needed for npm 7+. Count high and critical. |
| `knip` | deadcode | `knip.json*`, `.knip.json`, `knip.config.*` | `npx knip --reporter json` (needs `node_modules`) | Finds unused files, exports and dependencies. |

## Suppressions

`eslint-disable` (count `eslint-disable-next-line` and file-wide `/* eslint-disable */` apart: file-wide is worse), `@ts-ignore`, `@ts-expect-error`, `@ts-nocheck`, `biome-ignore`. Also count explicit `any` in `.ts` files (`: any`, `as any`) as a type-safety signal.

## First steps for recommendations

A linter for a repo without one: Biome (one tool, lint and format, no plugin setup) or ESLint flat config when the project needs framework plugins (React hooks, Vue, Angular).

```sh
npx --yes @biomejs/biome init
```

Type check in CI (and in `package.json`):

```json
"scripts": { "typecheck": "tsc --noEmit" }
```

```yaml
- run: npm ci
- run: npm run typecheck && npx eslint . && npm test
```

Strictness ratchet: turn on `"strict": true` and fix per folder, or enable single flags first (`noImplicitAny`, then `strictNullChecks`).

Coverage gate in Vitest:

```ts
test: { coverage: { thresholds: { lines: 70 } } }
```
