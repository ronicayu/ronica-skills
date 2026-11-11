# Dimensions and level rules

`scripts/score.py` applies these rules to `detect.json`, `hotspots.json` and `ghfacts.json` (and tier 1 results when they exist) and writes `score.json`. The model does not set tier 0 levels by hand. It may override a level only with an `override_reason` that cites evidence the script cannot see; the report shows every override.

Each rule has an id (`tests.2`, `ci.3a`). `score.json` names the rule that set each level, so two runs on the same repository give the same levels and a rerun's ↑ ↓ reflects the repository, not the model.

## Terms

- **Blocking CI row**: a CI row for the tool, in a job that runs on pull requests (`pull_request` true, or `"push-default"` for CI systems that build every branch), and not `non_blocking`. A pre-commit hook alone is not blocking; `pre-commit run` in CI is.
- **The subproject's languages**: rows count only when their `language` is one of the subproject's languages, or `shared`.
- **Partial**: the guardrail covers some of what it should (some test suites, some languages, some ecosystems). A partial guardrail gets the lower level and a `partial: {covered, total, missing}` field; the report says "CI runs 2 of 4 test suites".
- **Unknown**: the fact that decides the level is not visible (a GitHub setting without admin access, a tier 1 count that did not run). Status `unknown`, level null, `needs`: what would decide it. Unknown is never scored as 0.
- **Profile** (from detect, hotspots, ghfacts): `solo` (one active author in 12 months), `team`; `public`, `private`, `unknown`; `application` or `library` (a library publishes a package and has no deploy target; a repo of standard-library scripts is `scripts`).

## Guardrails (levels 0–3)

### lint (lint and format)
- `lint.0`: no linter config, script or CI row for any of the subproject's languages.
- `lint.1`: configured (config, package script, hook), but no blocking CI row. Partial when some languages have a linter and others none.
- `lint.2`: a blocking CI row runs the linter for every language of the subproject.
- `lint.3`: `lint.2`, a formatter check runs in blocking CI, suppressions are under 2 per 1,000 lines, and the tier 1 count is zero errors. Without the tier 1 count: level 2, `needs: tier 1 lint count`.

### types
- Python and TypeScript:
  - `types.0`: no mypy/pyright config; TypeScript files and no `tsconfig.json`.
  - `types.1`: configured, no blocking CI row (a bundler build does not check types).
  - `types.2`: blocking CI runs mypy, pyright or `tsc --noEmit` (or a build script that runs `tsc`).
  - `types.3`: `types.2` with a strictness fact (mypy strict or `disallow_untyped_defs`, pyright strict, tsconfig `strict`) and a tier 1 count of zero; without the count, level 2 with `needs`.
- Rust, Go, Java, Kotlin:
  - `types.1c`: no CI job builds the code.
  - `types.2c`: CI builds it (any blocking build or test row).
  - `types.3c`: warnings fail the build in CI: clippy `-D warnings` or `RUSTFLAGS=-Dwarnings`, `-Werror`, `allWarningsAsErrors`, `go vet` as a blocking row.

### static (security analysis)
- `static.0`: none of semgrep, CodeQL, SonarQube, bandit, gosec, SpotBugs, Error Prone, cargo-deny.
- `static.1`: configured, not blocking in CI.
- `static.2`: blocking in CI (a CodeQL workflow on pull requests, or GitHub default setup reported by ghfacts).
- `static.3`: `static.2` and ghfacts shows no open high or critical code-scanning alert; alerts not visible → level 2, `needs`.

### secrets
- `secrets.2g`: ghfacts shows secret scanning and push protection on.
- `secrets.2`: gitleaks or trufflehog is a blocking CI row (or `pre-commit run` in CI runs it).
- `secrets.1`: configured locally only.
- `secrets.3`: push protection on, and a scanner in blocking CI.
- No local scanner and the GitHub setting not visible → unknown. No local scanner and the setting visibly off → `secrets.0`.

### tests
- `tests.0`: no test files.
- `tests.1`: test files, no blocking CI row that runs them.
- `tests.1p` (partial): CI runs some test suites and not others. A suite is a folder of test files under one subproject or workspace member; a CI command covers a suite when it runs the whole subproject (`pytest`, `npm test`, `cargo test --workspace`, `go test ./...`, `mvn test`) or names the suite's path or member. List the suites CI misses, hottest first.
- `tests.2`: blocking CI runs every suite.
- `tests.3`: `tests.2`, and on the default branch ghfacts shows a pass rate of 90% or more over the last 50 completed runs and a re-run rate of 10% or less; or a tier 1 run passed in under 10 minutes. Neither available → level 2, `needs`.

### coverage
- `coverage.0`: no coverage config, flag or CI step.
- `coverage.1`: configured, not measured in blocking CI.
- `coverage.2`: blocking CI measures it.
- `coverage.3`: a threshold fails the build (`fail_under`, `--cov-fail-under`, jacoco rules, kover `minBound`, vitest `thresholds`, jest `coverageThreshold`) or a Codecov patch target.

### ci
- `ci.0`: no CI config.
- `ci.1`: CI exists, nothing runs on pull requests.
- `ci.2`: pull requests run the tests (`tests` at 1p or above).
- `ci.3`: `ci.2`, lint also runs, and ghfacts shows required status checks on the default branch (`ci.3a`). Protection not visible → level 2, `needs`. A `solo` repository reaches 3 without required checks when the default branch pass rate is 90% or more (`ci.3s`).

### setup
- Lockfile rule by profile: `application` needs a lockfile per ecosystem; `library` and `scripts` do not, and the summary says so.
- `setup.0`: none of: lockfile (when needed), toolchain pin, task entry (Makefile, justfile, package scripts, Taskfile, tox/nox, a script CI or the README runs).
- `setup.1`: one or two of the three.
- `setup.2`: all three.
- `setup.3`: `setup.2`, and CI installs from the lockfile (a locked-install fact), or a devcontainer exists.

### deps
- `deps.0`: no lockfile and no update bot.
- `deps.1`: lockfile, no bot and no audit in CI.
- `deps.1p` (partial): a bot that misses an ecosystem present in the repo (GitHub Actions counts when workflows exist).
- `deps.2`: a bot covering every ecosystem, or an audit as a blocking CI row.
- `deps.3`: `deps.2`, and every lockfile changed in the last 90 days (lockfile age), or a tier 1 audit with no high or critical advisory.

### docs
- `docs.0`: no README.
- `docs.1`: a README with no development command a reader can run, or one or more README commands that do not exist (`docs.commands[].check == "missing"`). A wrong command ranks above a missing one: list each.
- `docs.2`: the README gives commands to install, run and test, and every checkable command exists.
- `docs.3`: `docs.2` and a CONTRIBUTING file or a development section that also gives the lint command.

### arch (architecture written down and enforced)
- Facts: `architecture_docs[]` (`ARCHITECTURE.md` at the root or in `docs/`, `docs/architecture*`, and a README section headed "Architecture"), each with `last_commit`. ADRs and C4 models do not count; and rule tools in the `arch` category (ArchUnit, Spring Modulith, Konsist, import-linter, tach, pytestarch, dependency-cruiser, eslint-plugin-boundaries, Nx module boundaries, depguard, go-arch-lint).
- `arch.na`: profile `scripts`, or a subproject under 3,000 source lines: status `not_applicable`, summary says why.
- `arch.0`: no architecture doc and no rule tool.
- `arch.1`: an architecture doc exists, or a rule tool is configured but not run by blocking CI.
- `arch.2`: architecture rules run in blocking CI. A CLI tool (`lint-imports`, `tach check`, `depcruise`, `go-arch-lint`) needs its own blocking row. A tool that runs inside the tests (ArchUnit, Spring Modulith, Konsist, pytestarch) counts when CI runs the suite that holds its tests. A linter plugin (eslint-plugin-boundaries, Nx module boundaries, depguard) counts when its host linter has a blocking row. Rust: a Cargo workspace of two or more member crates counts, because the compiler rejects a dependency the manifest does not declare.
- `arch.3`: `arch.2`, and an architecture doc changed in the last 12 months.

## Signals (no level)

### hotspots
From `hotspots.json`: the top files by commits × indent complexity, their size, authors and top-author share; co-change pairs; size buckets; files over 1,000 lines. `score.py` joins each hotspot with its guardrails: is it under a test suite CI runs, its suppressions, whether its language has a blocking linter. A hotspot with no CI-run tests, or with a top-author share of 0.9 or more in a `team` repository, becomes a gap.

### ci_health
From ghfacts: default-branch pass rate, median duration, re-run rate, last failure, per workflow; median time to merge and the share of PRs merged with no review (`team` only). These feed `tests.3`, `ci.3s` and gaps (a pass rate under 80% is a gap of its own: a red main teaches people to ignore CI).

## Tier 2 reviews (no level)

- `review`: one reader with two lenses, structure (boundaries, layering, cycles, god modules) and error handling (swallowed errors, broad catches, missing context, unbounded retries, secrets in logs).
- `testquality`: do the tests of the top hotspots check behaviour; mocks, missing edge cases, flaky patterns.

Each finding cites `path:line`. See `tier2-prompts.md`.

## Gaps and ranking

`score.py` turns every level under 3, every partial and every hotspot gap into a gap with a stable `id` (`<dimension>:<subproject>:<rule or slug>`), the facts that caused it, and a `priority`:

1. Weight by dimension: tests 10, ci 9, lint 7, types 6, secrets 6 (public) or 3 (private), coverage 4, setup 4, deps 4, static 3, docs 3, arch 3.
2. Times the hotspot factor: 2 when the gap covers one of the top 5 hotspots (a missing suite that holds a hotspot, a hotspot's language without a linter), 1.5 for the top 15, 1 otherwise.
3. Times the effort factor: 1.5 when an existing tool only needs to move into CI or block (enforce, not add), 1 otherwise, 0.7 for a large change.
4. Times 0 when the profile makes the advice moot (required reviews in a `solo` repo, a lockfile for a `library`), and the gap is listed under "Not applicable" instead.
5. A gap whose id is `dismissed` in `.repo-health/decisions.json` drops out of the ranking and appears once, collapsed, with its reason.

The model writes recommendations for the top gaps in this order. It may reorder only with a reason in the recommendation.
