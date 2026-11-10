---
name: repo-health
description: Measure how well an existing code repository is guarded and where it needs work, then write a ranked Markdown report of recommendations. Scripts check lint, formatting, type checking, static analysis and secret scanning, tests and coverage, CI enforcement, setup and lockfiles, docs, dependencies, file sizes and git hotspots, for Python, TypeScript/JavaScript, Rust, Java, Go and Kotlin; each dimension gets a level from absent to effective. Cheap checks run at once; running tools or test suites and LLM code reading (structure, error handling, test quality) run only after the user agrees. Use when asked how to improve a repo, for a code health or engineering-practice audit, or whether a project has lint, tests, CI or static analysis. Reports only; it changes no project file. For a debt list from reading code, use a tech-debt skill; for reviewing a diff, use code review.
---

# Repo health

Measure a repository's guardrails and code health, then write a report that says what to do first. This skill reports and recommends. It changes no project file; the only files it writes are the report and its findings JSON.

## The question behind every dimension

"Is there a linter?" is the weak question. Ask whether the guardrail works. Each dimension gets a level:

| Level | Name | Meaning |
|---|---|---|
| 0 | absent | No config, no tool, no tests |
| 1 | present | Configured, but nothing makes people follow it: not in CI, not in a pre-commit hook |
| 2 | enforced | Runs in CI (or a pre-commit hook) on every change |
| 3 | effective | Enforced, and the results show it works: few or no open warnings, tests pass in a reasonable time, few suppressions |

There is no overall score. A single number hides which dimension is weak. The rules for each level, per dimension, are in `references/dimensions.md`.

## Cost tiers and consent

| Tier | What runs | Consent |
|---|---|---|
| 0 | `detect.py` and `hotspots.py`: configs, CI files, file lists, git log. One network read: `gh api` for branch protection, only when `gh` is already signed in. | None. Always runs. |
| 1 | Tools: the project's own lint, type and test commands, zero-config scanners, dependency audit, coverage. | Asked. |
| 2 | Code reading by subagents: structure, error handling, test quality, docs accuracy. | Asked, with a token estimate. |

The rule from the skill's owner: checks that cost many tokens need consent. Tier 1 costs few tokens, but it runs project code (tests, build scripts), downloads tools and can take minutes. That is why it is asked too. Say this in one line when you ask.

Ask **once**, after tier 0 has finished, so each choice carries its real cost (see step 4). If the session cannot ask (non-interactive, or the user said "just do the cheap part"), run tier 0 only and list every skipped step under "Not checked" with the command to run it.

When the user names dimensions ("only lint and tests"), check exactly those, and ask only about their tier 1 and tier 2 steps.

## Steps

### 1. Find the repository and the output path

The repository is the current directory, or the path the user gives. The output goes to `<repo>/.repo-health/report-<YYYY-MM-DD>.md` and `findings-<YYYY-MM-DD>.json`, or to a path the user gives. If `.repo-health/` does not exist yet, the step 4 question names the path, so the user knows where files will go.

Write all scratch output (tool logs) to your scratchpad or a temp folder, never into the repo.

### 2. Tier 0: run the scripts

```sh
python3 ${CLAUDE_PLUGIN_ROOT}/skills/repo-health/scripts/detect.py <repo>   > <scratch>/detect.json
python3 ${CLAUDE_PLUGIN_ROOT}/skills/repo-health/scripts/hotspots.py <repo> > <scratch>/hotspots.json
```

Both need Python 3.9 or later and nothing else. Read the JSON. For each language in `detect.json`, read its reference file: `references/python.md`, `typescript.md`, `rust.md`, `java.md`, `go.md`, `kotlin.md`, and always `references/shared.md`. Read only the files for languages found. Languages outside these six go under "Not checked".

Branch protection: if `gh auth status` succeeds and the repo has a GitHub remote, run `gh api repos/<owner>/<repo>/rules/branches/<default branch>` (rulesets; readable without admin). Then try `gh api repos/<owner>/<repo>/branches/<default branch>/protection`. A 403 or 404 there means "not visible", not "absent". Record what was visible.

### 3. Set tier 0 levels

Use `references/dimensions.md`. A dimension whose level needs a tier 1 result (level 3 needs a warning count, for example) gets the highest level the tier 0 evidence proves, and the summary says what would decide level 3.

Reading `detect.json`:
- CI, hook and script matches (`ci.files[].tools`, `precommit.tools`) are not filtered by language: `mvn verify` lists `junit`, `testng` and `kotest` together, and `jest --coverage` also lists `coverage.py`. Every row has `language`; count only rows for the subproject's languages, and check the subproject's dependencies before crediting a test framework.
- Tools with no config file (`unittest`, `cargo-test`, `go-test`, `go-vet`) appear only in the CI, hook and script matches, never under `subprojects[].categories`.
- A row with `via` was reached through a script or make target that CI runs (`npm run lint`, `make test`); it counts as run in CI.
- A config row with `inherited_from` sits in a parent directory and covers this subproject.

Evidence must point at something checkable: `path:line`, or `command → result`. No evidence, no claim.

### 4. Ask once about tier 1 and tier 2

Build the list of possible tier 1 and tier 2 steps for the dimensions in scope, from the reference files and the tier 0 evidence. Give each step its cost:

- Tier 1: the command, a time guess, whether it downloads tools, whether it runs project code, whether it needs an environment that does not exist yet (for example, `node_modules` missing means `npm ci` first, which writes `node_modules/` into the repo; ask about that as its own cost).
- Tier 2: the files it will read (from hotspots and entry points) and a token estimate: the total characters of those files / 4, times 1.5 for reasoning and output, rounded up to the next 5k.

Ask with AskUserQuestion, in the user's language, `multiSelect: true`. One question for tools (up to 4 options: lint and types; tests and coverage; dependency audit and secrets; dead code) and one for code reading (up to 4 options: structure, error handling, test quality, docs accuracy). Leave out options that do not apply. Put the cost in each option's description. Recommended defaults: lint and types, dependency audit; no code reading unless the repo is small (under ~20k tokens per review).

### 5. Tier 1: run the chosen tools

Rules:
- Never install into the project. No `npm install`, no `pip install` into the project's environment, no lockfile change. Exception: an environment setup the user agreed to in step 4.
- Ephemeral runners only for tools the project does not have: `uvx`, `pipx run`, `npx --yes`, `go run <module>@latest`.
- Versions: use the version the project declares (lockfile, pre-commit `rev`, build plugin version). Otherwise run unpinned and record the version the tool printed.
- A timeout on each command: 300 s, and 900 s for a test suite. Run in the repo directory.
- Only lint, type, test, coverage, audit and scan commands. Never deploy, publish, release, migrate, or push.
- Send output to a scratch file and read counts from it (`--statistics`, JSON output and `jq`, `grep -c`). Do not paste whole tool output into the context.
- Secret scanners: always use the redact option. Report rule, file and line only. Never print a secret value.
- A tool that fails to run is "not run" with the reason, not level 0.

### 6. Tier 2: code reading

One subagent per chosen dimension, all started in one message so they run in parallel. Each gets its brief from `references/tier2-prompts.md`, the hotspot list, the file list it may read, and the cap. Each returns the JSON shape in that file. Check that every finding cites `path:line`; drop findings that do not.

### 7. Write findings.json

Shape (schema 1):

```json
{
  "schema": 1,
  "repo": "name", "commit": "sha or null", "date": "YYYY-MM-DD",
  "headline": "one or two sentences: the state of the repo and the single most valuable change",
  "subprojects": [{"path": ".", "languages": ["python"]}],
  "dimensions": [
    {"id": "lint", "subproject": ".", "tier": 0, "status": "checked|not_run|skipped",
     "level": 0, "summary": "one line", "evidence": ["path:line or command → result"],
     "not_run_reason": null}
  ],
  "recommendations": [
    {"id": "r1", "dimension": "lint", "subproject": ".", "title": "imperative, one line",
     "why": "one or two sentences with the evidence",
     "impact": "high|medium|low", "effort": "small|medium|large",
     "first_step": "the exact command or config snippet"}
  ],
  "not_checked": [{"what": "...", "why": "...", "how_to_run": "..."}]
}
```

`level` is null for metric and review dimensions (`size`, `hotspots`, `structure`, `errors`, `testquality`, `docsaccuracy`); their summary carries the result.

Write prose fields in the user's language. Keep tool names, commands and paths as they are.

### 8. Render and report

```sh
python3 ${CLAUDE_PLUGIN_ROOT}/skills/repo-health/scripts/render.py <findings.json> -o <report.md>
```

`render.py` compares with the newest older `findings-*.json` beside the input, if one exists, and shows each dimension's change.

In the terminal, print: the headline, the top 5 actions (title and first step), the report path. On a first run, add one line: `.repo-health/` is new; add it to `.gitignore` or commit it, the user's choice.

## Ranking recommendations

Each recommendation gets impact and effort. `render.py` puts high impact and small effort first. Rules for setting them:

1. **Guardrails before rewrites.** A missing or unenforced lint, test or CI gate ranks above a structure change: it stops new damage cheaply.
2. **Enforce before add.** Moving an existing tool into CI is small effort and high impact. Recommend it before adding a new tool.
3. **Hotspots decide where.** Structure, test and error-handling recommendations name hotspot files. A messy file nobody changes is low impact.
4. **Baseline, then ratchet.** For a repo with many existing warnings, recommend checking new and changed code only (baseline file, `--new-from-rev`, per-directory config) instead of "fix 2,000 warnings". The reference files name each tool's way to do this.
5. **One tool per job, the ecosystem's usual one.** Do not recommend a second linter where one already covers the job.
6. **First step is concrete.** A command, a config snippet or a CI step for this ecosystem, ready to paste. Not "consider adding linting".

Usually 5–15 recommendations. Fewer good ones beat many weak ones.
