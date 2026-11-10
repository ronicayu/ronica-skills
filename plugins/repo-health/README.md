# repo-health

Points at an existing code repository and answers "how do we make this better?".
It measures the repository's engineering guardrails and code health, then writes
a Markdown report with ranked recommendations and prints a short summary.
Version 0.1.0 reports and recommends; it changes no project file.

Say it in plain words: "how can I improve this repo", "audit this project's
engineering practice", "does this project have lint, tests and CI?".

## Three levels per dimension

"Is there a linter?" is the weak question. Each dimension gets a level:

| Level | Name | Meaning |
| --- | --- | --- |
| 0 | absent | No config, no tool, no tests |
| 1 | present | Configured, but nothing makes people follow it |
| 2 | enforced | Runs in CI or a pre-commit hook on every change |
| 3 | effective | Enforced, and the results show it works: few warnings, passing and fast tests, known coverage, few suppressions |

There is no overall score. A single number invites gaming and hides which
dimension is weak. A rerun compares each dimension with the previous report.

## Tiers and consent

| Tier | What it does | Asked first? |
| --- | --- | --- |
| 0 | Reads configs, CI files, file lists and git history through `detect.py` and `hotspots.py`. Small output. | No |
| 1 | Runs tools: the project's lint, type and test commands, zero-config scanners, dependency audit, coverage. This executes project code and can download tools and take minutes. | Yes |
| 2 | An LLM reads code: structure, error handling, test quality, docs accuracy. Costs many tokens. | Yes, with a token estimate |

Tier 0 runs first. Then one question lists every tier 1 and tier 2 step with its
cost. Nothing selected means the report covers tier 0 and lists the rest under
"Not checked". You can also name dimensions ("only lint and tests").

## Dimensions

| id | Dimension | Tier |
| --- | --- | --- |
| `lint` | Lint and formatting | 0, 1 |
| `types` | Type checking | 0, 1 |
| `static` | Static analysis and security | 0, 1 |
| `tests` | Tests | 0, 1 |
| `coverage` | Coverage | 1 |
| `ci` | CI | 0 |
| `setup` | Setup and reproducibility | 0 |
| `docs` | Docs | 0 |
| `deps` | Dependencies | 0, 1 |
| `size` | Size and structure metrics | 0 |
| `hotspots` | Hotspots (churn x size x indentation) | 0 |
| `deadcode` | Dead code | 1 |
| `structure` | Structure review | 2 |
| `errors` | Error handling and observability | 2 |
| `testquality` | Test quality | 2 |
| `docsaccuracy` | Docs accuracy | 2 |

## Output

`<repo>/.repo-health/report-<YYYY-MM-DD>.md` and
`findings-<YYYY-MM-DD>.json` (or a path you give). The report starts with the
conclusion and the top five actions, then a scorecard with the change since the
previous run, details per dimension, and what was not checked. The skill does
not edit `.gitignore`; ignore or commit the folder as you like.

The scripts also run by hand:

```sh
skills/repo-health/scripts/detect.py REPO      # languages, tools, CI, setup, docs (JSON)
skills/repo-health/scripts/hotspots.py REPO    # hotspots, largest files, co-change (JSON)
skills/repo-health/scripts/render.py findings.json [--previous OLD.json] [-o report.md]
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
