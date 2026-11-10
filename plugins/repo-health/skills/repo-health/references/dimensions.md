# Dimensions and level rules

Levels: 0 absent, 1 present, 2 enforced, 3 effective. "In CI" means a CI file runs the tool in a job that triggers on pull requests (or merge requests), or on every push to the default branch. A pre-commit hook counts as enforced only together with CI; alone it is level 1 plus a note, because hooks can be skipped.

When `detect.json` finds several subprojects, set levels per subproject. A tool configured at the repo root counts for every subproject it covers.

## Guardrail dimensions

### `lint`: lint and formatting (tier 0, tier 1)

- 0: no linter config and no linter in CI, hooks or package scripts.
- 1: a linter is configured (config file or `package.json` script), but CI does not run it.
- 2: CI runs it.
- 3: CI runs it, the tier 1 run shows zero errors (warnings under ~1 per 1,000 lines), and suppressions are under ~1 per 500 lines. A formatter check (`--check`) in CI is part of level 3.
- Evidence: `detect.json` `subprojects[].lint`, `.format`, `ci`, `precommit`, `suppressions`; tier 1 counts.

### `types`: type checking (tier 0, tier 1)

Python and TypeScript have optional checkers; the compiled languages always type-check, so their levels measure strictness.
- Python, TypeScript
  - 0: no mypy/pyright config; TypeScript files with no `tsconfig.json`.
  - 1: config present but not in CI. For TypeScript, `tsc` runs only as part of a bundler build that ignores type errors (Vite, esbuild and SWC strip types without checking).
  - 2: CI runs mypy, pyright or `tsc --noEmit` (or a build that runs `tsc`).
  - 3: enforced, with strict settings (mypy `strict = true` or `disallow_untyped_defs`; pyright `strict`; tsconfig `"strict": true`), and the tier 1 run shows zero errors.
- Rust, Go, Java, Kotlin
  - 2: the default. CI builds the code.
  - 3: warnings fail the build: Rust `-D warnings` (in clippy or `RUSTFLAGS`) or `[lints]` set to deny; Java `-Werror`; Kotlin `allWarningsAsErrors`; Go `go vet` in CI.
  - 1: no CI builds the code.

### `static`: static analysis and security (tier 0, tier 1)

Security-focused analysis beyond the linter: semgrep, CodeQL, SonarQube, bandit, gosec, SpotBugs, Error Prone, cargo-deny.
- 0: none.
- 1: configured, not in CI.
- 2: CI runs it (CodeQL counts as level 2 when its workflow exists and triggers on pull requests).
- 3: enforced, and the tier 1 run (or the tool's last CI result, if visible) shows no high-severity finding.

### `secrets`: secret scanning (tier 0, tier 1)

- 0: no gitleaks/trufflehog config or CI step.
- 1: configured, not in CI.
- 2: CI or a pre-commit hook runs it.
- 3: enforced, and a redacted tier 1 scan of the working tree finds nothing.
- GitHub's own secret scanning and push protection are repository settings that `detect.py` cannot see. If `gh` is signed in, `gh api repos/<o>/<r>` shows `security_and_analysis` only to admins; otherwise say "not visible".

### `tests`: tests (tier 0, tier 1)

- 0: no test files.
- 1: test files exist, CI does not run them, or CI runs only some of the test suites. The summary names the suites CI skips (compare the folders in `ci.files[].tools[].commands` with the test folders on disk).
- 2: CI runs all of them.
- 3: enforced, and the tier 1 run passes, finishes in under ~10 minutes, and no test was skipped without a reason. Report the test-to-source file ratio and the 5 slowest tests if the runner shows them.
- A suite that fails on a clean checkout is level 2 with a high-impact recommendation: a red suite trains people to ignore it.

### `coverage`: coverage (tier 1, presence at tier 0)

- 0: no coverage config or step.
- 1: configured (coverage.py config, `--cov`, jacoco, kover, c8, vitest coverage), not in CI.
- 2: CI measures it.
- 3: CI fails below a threshold (`fail_under`, `--cov-fail-under`, jacoco `violationRules`, kover `minBound`, vitest `thresholds`), or a coverage service checks patch coverage on pull requests (Codecov or Coveralls config with a patch target).
- Tier 1 reports the total line coverage and the coverage of the top 5 hotspot files. Low coverage on a hotspot matters more than the total.

### `ci`: CI (tier 0)

- 0: no CI config.
- 1: CI exists but does not run on pull requests (push to the default branch only, or manual).
- 2: CI runs on pull requests and runs at least the tests (all suites, or the summary says which it skips).
- 3: CI runs on pull requests, runs tests and lint, and the default branch requires the checks to pass (branch protection or a ruleset, if visible). When protection is not visible, the most that can be proven is level 2; say so.
- List which of lint, format, types, static, tests, coverage each CI file runs.

### `setup`: setup and reproducibility (tier 0)

- 0: no lockfile for an ecosystem that has one (applications; libraries may skip lockfiles by choice, so say so instead of scoring 0), no toolchain pin, no documented setup.
- A repo of scripts with no third-party dependencies (standard library only) needs no lockfile: judge it on the toolchain pin and the one-command tasks, and say so in the summary.
- One-command tasks include shell scripts that CI or the README runs (`scripts/test.sh`, `scripts/validate.sh`), not only Makefile, justfile or `package.json` scripts.
- 1: a lockfile exists.
- 2: a lockfile, a toolchain pin (`.python-version`, `requires-python`, `.nvmrc`/`engines`/`packageManager`, `rust-toolchain.toml`, Maven/Gradle wrapper, the `go` directive, `.tool-versions`, `mise.toml`), and one-command tasks (Makefile, justfile, Taskfile, `package.json` scripts, `tox`/`nox`).
- 3: level 2, and CI installs from the lockfile (`npm ci`, `pnpm install --frozen-lockfile`, `uv sync --locked`, `poetry install` with `poetry check --lock`, `cargo build --locked`, `go mod verify`), or a devcontainer exists.

### `docs`: docs (tier 0)

- 0: no README.
- 1: a README without install, run or test instructions.
- 2: the README tells a developer how to set up, run and check the code. Commands count wherever they are; heading names do not matter (a "Validation" section that runs `./scripts/validate.sh` is the test instruction). For a library or plugin, "install" can be installing it for use, but the developer must still find how to run its checks.
- 3: level 2, and a CONTRIBUTING file or a developer guide, and architecture notes or ADRs for a codebase over ~20k lines.

### `deps`: dependencies (tier 0, tier 1)

- 0: no lockfile and no update bot.
- 1: a lockfile, no update bot and no audit.
- 2: Dependabot or Renovate config, or an audit step in CI.
- 3: level 2, and the tier 1 audit shows no known vulnerability of high or critical severity.
- Tier 1 also counts outdated direct dependencies where it is cheap (`npm outdated --json`, `uv pip list --outdated` in an existing env, `go list -m -u all`, `cargo outdated` if installed).

### `deadcode`: dead code (tier 1)

- Level null when tier 1 did not run; when it ran: 1 if the count is high (over ~1 per 1,000 lines at the tool's high-confidence setting), 2 if a tool runs in CI, 3 if it runs in CI and finds little.
- Report the count and 5 samples with `path:line`. Dead-code tools have false positives (reflection, dependency injection, public APIs, framework entry points); say so and do not recommend deleting by count alone.

## Metric dimensions (level null)

### `size`: size and structure metrics (tier 0)

From `detect.json` and `hotspots.json`: LOC per language, `size_buckets`, the largest files, the number of files over 500 and 1,000 lines. The summary says whether size is concentrated in a few files. Recommend splitting only files that are also hotspots.

### `hotspots`: change hotspots (tier 0)

From `hotspots.json`: the top files by commits × indent complexity, and the top co-change pairs. A hotspot with low coverage, no tests or many suppressions is where the first structure or test recommendation goes. A co-change pair across two modules suggests a hidden dependency. A shallow clone or no git history gives no hotspots; say so.

## Review dimensions (tier 2, level null)

`structure`, `errors`, `testquality`, `docsaccuracy`: see `tier2-prompts.md`. The summary gives the main finding. Every finding cites `path:line`.
