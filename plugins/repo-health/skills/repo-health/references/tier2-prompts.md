# Tier 2 subagent briefs

One subagent per chosen dimension, started together. Each brief below is a template: fill in `<repo>`, the file list and the cap. The subagent reads only the listed files (plus what it must open to follow one call), and stops at the cap.

**Choosing files.** Start from `hotspots.json` `files` (top by score), then add entry points (`main`, CLI modules, HTTP route/controller files, `index.ts`, `lib.rs`, `cmd/*/main.go`, `Application.java`). Skip generated and vendored files. Cap: 15 files or 60k characters per dimension, whichever comes first; for repos where the user agreed to more, say the new cap in the brief. The token estimate in step 4 comes from this list.

**Every brief ends with:**

> Return only this JSON:
> `{"summary": "one line", "findings": [{"path": "file", "line": 123, "what": "one sentence", "severity": "high|medium|low"}], "recommendations": [{"title": "imperative, one line", "why": "one or two sentences citing findings", "impact": "high|medium|low", "effort": "small|medium|large", "first_step": "concrete"}], "read": ["files you read"], "stopped_early": false}`
> Every finding cites a real `path` and `line` you read. No finding without a citation. At most 10 findings and 4 recommendations: keep the ones that matter most. If the code is fine on this dimension, say so in the summary and return no findings.

## `structure`

> You review the structure of the code in `<repo>`. Read the module tree (`git ls-files` limited to source directories, or the directory list given), then these files: `<list>`.
> Judge: module boundaries (does each module have one job you can name?), layering (does low-level code import high-level code, does domain logic import the web or database layer?), dependency cycles between modules, god modules and god classes (one file or class most changes go through), duplicated logic across modules, and naming that hides what a module does.
> These files are change hotspots: they change often and are complex. A problem in a hotspot matters more than one in quiet code. Prefer findings that explain why the hotspot keeps changing.
> Do not report style, formatting or lint issues; tools cover those.

## `errors`

> You review error handling and observability in `<repo>`. Read these files: `<list>`.
> Look for: errors that are caught and dropped (empty catch, `except: pass`, `_ = err`, `.ok()` or `unwrap_or_default()` on a fallible call whose failure matters), broad catches (`except Exception`, `catch (Throwable`) that hide bugs, errors re-raised without context, `unwrap()`/`!!`/`panic` on input from outside the process, missing timeouts on network calls, retries without a limit, logging of secrets or personal data, and code paths with no log, metric or trace on failure.
> Language-normal patterns are fine: Go `if err != nil { return fmt.Errorf("...: %w", err) }`, Rust `?` with context, a top-level handler that logs and returns 500.

## `testquality`

> You review the quality of the tests in `<repo>`. Read these source files: `<hotspot list>`, and the tests that cover them: `<test list>` (find them by name and imports).
> Judge: do the tests check behaviour (outputs, state, errors) or only that code runs? Mocks that replace the thing under test; assertions on mock calls only; one huge test per function; missing edge cases for the hotspot's branches (empty input, error paths, boundaries); flaky patterns (`sleep`, real clock, real network, shared temp paths, test order); slow tests that could be unit tests.
> Name the hotspot functions that have no test at all.

## `docsaccuracy`

> You check whether the docs in `<repo>` match the code. Read `README*`, `CONTRIBUTING*`, and these build files: `<package.json, Makefile, justfile, pyproject.toml, Cargo.toml, pom.xml, build.gradle.kts as present>`.
> For every command the docs tell a reader to run (install, run, test, lint, build), check that the script, target, task or file it names exists. Check that named environment variables, config files and paths exist in the repo. Check that the documented language and tool versions match the pins (`.nvmrc`, `requires-python`, `rust-toolchain.toml`, `go.mod`).
> Do not run the commands. Report each mismatch with the doc line and the file that disagrees.
