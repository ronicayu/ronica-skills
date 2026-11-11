# Tools for every language

## CI systems

`detect.py` reads GitHub Actions (`.github/workflows/*.yml`), GitLab CI (`.gitlab-ci.yml`), Jenkins (`Jenkinsfile`), CircleCI (`.circleci/config.yml`), Azure Pipelines (`azure-pipelines.yml`), Buildkite (`.buildkite/`), Bitbucket (`bitbucket-pipelines.yml`). A workflow that calls a reusable workflow or a composite action from another repo hides its steps: say "steps not visible" instead of "not run".

Pull request triggers: GitHub `pull_request`, `pull_request_target`, `merge_group`; GitLab `merge_request_event` or `rules:` with `$CI_PIPELINE_SOURCE == "merge_request_event"`; Bitbucket `pull-requests:`. Jenkins and Buildkite usually run on every branch by server setup; say "trigger set on the server, not visible".

## Tools

| tool | category | config | tier 1 command | notes |
|---|---|---|---|---|
| `semgrep` | static | `.semgrep.yml`, `.semgrep.yaml`, `.semgrep/` | not run (config only) |  |
| `codeql` | static | a workflow with `github/codeql-action` | not run (config only); `gh api repos/<o>/<r>/code-scanning/alerts?state=open --paginate` is a ghfacts read of open alerts (needs security read access) | GitHub's default setup has no workflow file: then `gh api repos/<o>/<r>/code-scanning/default-setup` shows it. |
| `sonarqube` | static | `sonar-project.properties`, `sonarqube` in the build | not run (config only) |  |
| `gitleaks` | secrets | `.gitleaks.toml`, `.gitleaksignore` | not run (config only) |  |
| `trufflehog` | secrets | (none) | not run (config only) |  |
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
