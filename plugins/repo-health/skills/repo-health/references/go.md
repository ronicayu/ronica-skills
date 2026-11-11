# Go

Markers: `go.mod`. Lockfile: `go.sum`. Toolchain pin: the `go` and `toolchain` directives in `go.mod`. Several modules: `go.work`; treat each module as a subproject.

## Environment

`go vet`, `go test` and `go run <tool>@latest` build code and download modules into the module cache (`$GOPATH/pkg/mod`, outside the repo). They write nothing into the repo. `go run <module>@latest` downloads and builds the tool each time it is not cached: needs the network.

## Tools

| tool | category | config | tier 1 command | notes |
|---|---|---|---|---|
| `golangci-lint` | lint | `.golangci.yml`, `.golangci.yaml`, `.golangci.toml`, `.golangci.json` | `golangci-lint run ./...` if installed | Config `version: "2"` means golangci-lint v2; v1 configs do not load in v2. Baseline: `--new-from-rev=<base>` (or `new-from-rev` in config). Do not `go run` it: the project recommends a binary install. |
| `staticcheck` | lint | `staticcheck.conf` | `go run honnef.co/go/tools/cmd/staticcheck@latest ./...` | Already part of golangci-lint's default set. |
| `go-vet` | lint | (none) | `go vet ./...` | `go test` runs a subset of vet by itself; level 3 for types wants an explicit `go vet` in CI. |
| `gofmt` | format | (none) | `gofmt -l .` | Lists files that are not formatted; an empty list is clean. |
| `goimports` | format | (none) | `go run golang.org/x/tools/cmd/goimports@latest -l .` | |
| `gofumpt` | format | (none) | `go run mvdan.cc/gofumpt@latest -l .` | Stricter gofmt. |
| `gosec` | static | (none) | only with consent when the data is stale: `go run github.com/securego/gosec/v2/cmd/gosec@latest -quiet -fmt json ./...` | Count by severity. Also available inside golangci-lint. |
| `govulncheck` | deps_audit | (none) | only with consent when the data is stale: `go run golang.org/x/vuln/cmd/govulncheck@latest ./...` | Reports only vulnerabilities in code the module calls; needs the network. |
| `go-test` | tests | (none) | `go test ./...` | Add `-count=1` to skip the test cache. `-race` is a recommendation for concurrent code, not a tier 1 default (slower). |
| `go-cover` | coverage | (none) | `go test -count=1 -coverprofile=<scratch>/cover.out ./... && go tool cover -func=<scratch>/cover.out` | The last line is the total. |
| `deadcode` | deadcode | (none) | `go run golang.org/x/tools/cmd/deadcode@latest ./...` | Unreachable functions from `main`; libraries without `main` need `-test`. |
| `depguard` | arch | `depguard` in `.golangci.yml`/`.yaml`/`.toml` | runs inside golangci-lint | Allow or deny import lists per package. Counts when golangci-lint is blocking. |
| `go-arch-lint` | arch | `.go-arch-lint.yml` | `go run github.com/fe3dback/go-arch-lint@latest check` | Component and layer rules. |

## Suppressions

`//nolint` (a bare `//nolint` without linter names and a reason is the worst kind), `#nosec`. Ignored errors: count `_ = ` assignments of error results and `_, _ =` as a review signal for the `errors` dimension.

## First steps for recommendations

CI (GitHub Actions):

```yaml
- uses: actions/setup-go@v5
  with: { go-version-file: go.mod }
- run: test -z "$(gofmt -l .)"
- run: go vet ./...
- run: go test -race ./...
- uses: golangci/golangci-lint-action@v8   # check the latest major
```

A starting `.golangci.yml` (v2):

```yaml
version: "2"
linters:
  default: standard
  enable: [errorlint, gosec, bodyclose]
```

Vulnerabilities: `golang/govulncheck-action` in CI.

Architecture rules, with depguard in golangci-lint:

```yaml
# .golangci.yml
linters:
  enable: [depguard]
  settings:
    depguard:
      rules:
        domain:
          files: ["**/internal/domain/**"]
          deny:
            - pkg: "example.com/app/internal/http"
              desc: domain must not import the HTTP layer
```
