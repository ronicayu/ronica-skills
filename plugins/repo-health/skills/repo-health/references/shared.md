# Tools for every language

## CI systems

`detect.py` reads GitHub Actions (`.github/workflows/*.yml`), GitLab CI (`.gitlab-ci.yml`), Jenkins (`Jenkinsfile`), CircleCI (`.circleci/config.yml`), Azure Pipelines (`azure-pipelines.yml`), Buildkite (`.buildkite/`), Bitbucket (`bitbucket-pipelines.yml`). A workflow that calls a reusable workflow or a composite action from another repo hides its steps: say "steps not visible" instead of "not run".

Pull request triggers: GitHub `pull_request`, `pull_request_target`, `merge_group`; GitLab `merge_request_event` or `rules:` with `$CI_PIPELINE_SOURCE == "merge_request_event"`; Bitbucket `pull-requests:`. Jenkins and Buildkite usually run on every branch by server setup; say "trigger set on the server, not visible".

## Tools

| tool | category | config | tier 1 command | notes |
|---|---|---|---|---|
| `semgrep` | static | `.semgrep.yml`, `.semgrep.yaml`, `.semgrep/` | `uvx semgrep scan --config p/default --metrics off --json -o <scratch>/semgrep.json` | Downloads rules from the Semgrep registry (network). With a project config, use `--config <that file>`. `--config auto` needs metrics on; do not use it. |
| `codeql` | static | a workflow with `github/codeql-action` | not run locally (needs the CodeQL CLI and a build); with `gh` signed in, `gh api repos/<o>/<r>/code-scanning/alerts?state=open --paginate` counts open alerts (needs security read access) | GitHub's default setup has no workflow file: then `gh api repos/<o>/<r>/code-scanning/default-setup` shows it. |
| `sonarqube` | static | `sonar-project.properties`, `sonarqube` in the build | not run locally (needs the server); report the config | |
| `gitleaks` | secrets | `.gitleaks.toml`, `.gitleaksignore` | `gitleaks dir . --redact --no-banner --report-format json --report-path <scratch>/gitleaks.json` if installed (v8.19+; older versions: `gitleaks detect --no-git --redact ...`) | Scan the working tree only in tier 1. A history scan (`gitleaks git`) is slower; offer it as its own option for repos that were ever public. Never print secret values. |
| `trufflehog` | secrets | (none) | `trufflehog filesystem . --no-update --json` if installed | Prints secret values unless filtered: write to a scratch file and report only detector, file and line. |
| `dependabot` | deps_bot | `.github/dependabot.yml`, `.github/dependabot.yaml` | (none) | List which ecosystems it covers; an ecosystem in the repo that it does not list is a gap. |
| `renovate` | deps_bot | `renovate.json`, `renovate.json5`, `.github/renovate.json*`, `.renovaterc*`, `renovate` in `package.json` | (none) | |
| `pre-commit` | hooks | `.pre-commit-config.yaml` | (none: running it changes files) | List hook ids and their `rev`s. Also a source of declared tool versions. |
| `husky` | hooks | `.husky/` | (none) | Read the hook scripts for the commands they run. |
| `lefthook` | hooks | `lefthook.yml`, `lefthook.yaml`, `.lefthook.yml` | (none) | |

## First steps for recommendations

Secret scanning in CI (GitHub Actions):

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- uses: gitleaks/gitleaks-action@v2
```

On GitHub, also turn on secret scanning and push protection in the repository settings (free for public repos).

Dependency updates, `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "<pip|npm|cargo|gomod|maven|gradle>"
    directory: "/"
    schedule: { interval: "weekly" }
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "weekly" }
```

Require checks before merge: GitHub repository settings → Rules → a ruleset on the default branch with "Require status checks to pass".

Architecture doc: a short `ARCHITECTURE.md` at the root (about one page): the problem the code solves, a map of the top-level modules with one line each on what they own, the rules between them (what may import what), and where to start reading. A doc a rule tool enforces stays true; a doc alone drifts.
