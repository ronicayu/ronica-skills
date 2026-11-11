# repo-health

Points at an existing code repository and answers "how do we make this better?".
It measures the repository's engineering guardrails and code health, then writes
a Markdown report with ranked recommendations and prints a short summary.
Version 0.1.0 reports and recommends; it changes no project file.

Say it in plain words: "how can I improve this repo", "audit this project's
engineering practice", "does this project have lint, tests and CI?".

## Levels per dimension

"Is there a linter?" is the weak question. Each dimension gets a level, set by
`scripts/score.py` from the rules in `skills/repo-health/references/dimensions.md`
(every level names the rule that set it, so two runs on one repository agree):

| Level | Name | Meaning |
| --- | --- | --- |
| 0 | absent | No config, no tool, no tests |
| 1 | present | Configured, but nothing makes people follow it (or only some suites, languages or ecosystems are covered: "partial") |
| 2 | enforced | Runs in blocking CI on every pull request |
| 3 | effective | Enforced, and the results show it works: passing and fast tests, known coverage, strict types, few suppressions |

A fact the tools cannot see (a GitHub setting without admin access, a tier 1
count that did not run) gives `unknown`, never 0. A rule that does not fit the
repository (a lockfile for a library, coverage with no tests) gives `n/a`.
There is no overall score.

## Tiers and consent

| Tier | What it does | Asked first? |
| --- | --- | --- |
| 0 | Reads configs, CI files, file lists and git history (`detect.py`, `hotspots.py`) and, with an authenticated `gh`, CI outcomes and repository settings (`ghfacts.py`, read-only). | No |
| 1 | Runs tools: the project's lint, type and test commands, zero-config scanners, dependency audit, coverage. This executes project code and can download tools and take minutes. | Yes |
| 2 | An LLM reads code: `review` (structure and error handling) and `testquality`. Costs many tokens. | Yes, with a token estimate |

Tier 0 runs first. Then one question lists every tier 1 and tier 2 step with its
cost. Nothing selected means the report covers tier 0 and lists the rest under
"Not checked".

## Dimensions

| id | Dimension | Tier |
| --- | --- | --- |
| `lint` | Lint and formatting | 0, 1 |
| `types` | Type checking | 0, 1 |
| `static` | Static analysis and security | 0 |
| `secrets` | Secret scanning | 0 |
| `tests` | Tests (every suite, not just some) | 0, 1 |
| `coverage` | Coverage | 0 |
| `ci` | CI | 0 |
| `setup` | Setup and reproducibility | 0 |
| `docs` | Docs (README commands are checked to exist) | 0 |
| `deps` | Dependencies (update bot per ecosystem, audit, lockfile age) | 0, 1 |
| `arch` | Architecture written down and enforced | 0 |

Hotspots (churn x indentation), CI health and the two tier 2 reviews give
signals and findings, not levels.

## Output

Files go to `<repo>/.repo-health/`, named with a stamp `YYYY-MM-DDTHHMM` so two
runs on one day do not overwrite each other:

- `detect-<stamp>.json`, `hotspots-<stamp>.json`, `ghfacts-<stamp>.json`: the facts
- `score-<stamp>.json`: levels, gaps (ranked, with stable ids), profile, hotspots joined with guardrails, changes since the previous run
- `findings-<stamp>.json`: the model's recommendations (schema 2)
- `report-<stamp>.md`: the report
- `share-<stamp>.md`: at most 15 lines to paste into a pull request, issue or chat

The report starts with the conclusion and the top five actions (each with a first
step and a command that verifies it), then what changed since the previous run, a
scorecard, hotspots, evidence for the weak dimensions and what was not checked.
The skill does not edit `.gitignore`; ignore or commit the folder as you like.

## Gap ids and decisions

Every gap has a stable id, printed next to its recommendation, for example
`tests:.:missing-suite:plugins/agentic-team/tests`. To drop a gap from the
ranking, record a decision in `.repo-health/decisions.json`:

```json
{"tests:.:missing-suite:plugins/agentic-team/tests": {"status": "dismissed", "reason": "run by make ci", "date": "2026-11-10"}}
```

`status` is `dismissed` (the gap leaves the ranking and appears collapsed, with its
reason), `later` (it stays at half priority) or `done` (informational; if the gap is
detected again the report lists it as a regression). Or let the script edit the file
(it creates it, keeps the other entries and sorts the keys):

```sh
score.py decide 'tests:.:missing-suite:plugins/agentic-team/tests' --dismiss --reason "run by make ci"
```

The scripts also run by hand:

```sh
S=skills/repo-health/scripts
$S/detect.py REPO > detect.json                  # languages, tools, CI, setup, docs (JSON)
$S/hotspots.py REPO > hotspots.json              # hotspots, largest files, co-change (JSON)
$S/ghfacts.py REPO > ghfacts.json                # CI outcomes and repository settings (needs gh)
$S/score.py --detect detect.json --hotspots hotspots.json [--ghfacts ghfacts.json] [--tier1 t1.json] \
            [--previous score-old.json] -o score.json
$S/render.py findings.json [-o report.md] [--share share.md]
```

## Safety

- Read-only for project files. The only writes are the report and the findings JSON.
- Tier 1 never installs into the project: no `npm install`, no `pip install`
  into the project environment, no lockfile change. It uses ephemeral runners
  (`uvx`, `pipx run`, `npx`, `go run`) with a timeout per command.
- It never runs deploy, publish, release, migrate or `docker push` targets.
- A tool that fails to run is recorded as "not run", not as level 0.

## Languages

Python, TypeScript/JavaScript, Rust, Java, Go and Kotlin. Other languages (C#,
C/C++, Ruby, PHP, Swift, Scala) are counted by extension and listed under
"Not checked". Monorepos are split into subprojects by manifest, up to 10.

## Tests

The scripts use only the standard library and run on Python 3.9 or newer.

```sh
python3 -m unittest discover -s plugins/repo-health/tests
```

`test_consistency.py` checks that the tool names in `references/*.md` (the
`## Tools` tables) and the table in `detect.py` agree, so they cannot drift.
