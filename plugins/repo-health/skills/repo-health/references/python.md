# Python

Markers: `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements*.txt`, `Pipfile`. Lockfiles: `uv.lock`, `poetry.lock`, `pdm.lock`, `Pipfile.lock`, pinned `requirements.txt` (every line `==`). Toolchain pin: `.python-version`, `requires-python`.

## Environment

Most tier 1 tools run without the project's dependencies (ruff, bandit, vulture, pip-audit on a requirements file). Type checkers and tests need them.
- An existing environment: `.venv/` or `venv/` in the repo, or the active `VIRTUAL_ENV`. Use it: `.venv/bin/python -m pytest`.
- `uv.lock`: `uv run --frozen <cmd>` creates `.venv/` in the repo if missing. That writes into the repo; ask about it in step 4.
- `poetry.lock`: `poetry run <cmd>` (needs `poetry install` first: ask).
- No environment and no consent to make one: run type checks with `--ignore-missing-imports` and mark counts as approximate; do not run tests.

## Tools

| tool | category | config | tier 1 command | notes |
|---|---|---|---|---|
| `ruff` | lint | `ruff.toml`, `.ruff.toml`, `[tool.ruff]` | `uvx ruff check --statistics .` | Zero-config: also useful to estimate warnings when no linter is configured (`--select E,F,B` keeps it to likely bugs). Baseline: `ruff check --add-noqa` (edits files; recommend, do not run). |
| `ruff-format` | format | `[tool.ruff.format]` | `uvx ruff format --check .` | Counts files that would change. |
| `flake8` | lint | `.flake8`, `[flake8]` in `setup.cfg`/`tox.ini` | `uvx flake8 --count --statistics .` | Plugins listed in config need `--with`: `uvx --with flake8-bugbear flake8 ...`. |
| `pylint` | lint | `.pylintrc`, `pylintrc`, `[tool.pylint.*]` | in the project env: `python -m pylint <pkg> --output-format=parseable` | Without the deps it reports import errors; count only other messages. |
| `black` | format | `[tool.black]` | `uvx black --check .` | |
| `isort` | format | `.isort.cfg`, `[tool.isort]` | `uvx isort --check-only .` | |
| `mypy` | types | `mypy.ini`, `.mypy.ini`, `[mypy]`, `[tool.mypy]` | in the project env: `python -m mypy .` (or the paths in config) | Error count from the last line `Found N errors`. Gradual: per-module `[[tool.mypy.overrides]]`. |
| `pyright` | types | `pyrightconfig.json`, `[tool.pyright]` | `npx --yes pyright --outputjson` (point `--pythonpath` at the env's python) | `basedpyright` is a fork; treat it as pyright. Baseline: basedpyright `--writebaseline`. |
| `bandit` | static | `.bandit`, `[tool.bandit]` | `uvx bandit -r <src> -q -f json` | Count by severity; skip test folders (`-x tests`). |
| `pytest` | tests | `pytest.ini`, `conftest.py`, `[tool.pytest.ini_options]`, `[tool:pytest]` | in the project env: `python -m pytest -q --durations=5` | Add `-p no:cacheprovider` so it writes no `.pytest_cache` into the repo. |
| `unittest` | tests | (none) | in the project env: `python -m unittest discover -s <tests dir>` | |
| `tox` | tests | `tox.ini` | prefer running pytest in an existing env; `tox` builds its own envs under `.tox/` | Ask before running tox: it installs. |
| `nox` | tests | `noxfile.py` | as tox | |
| `coverage.py` | coverage | `.coveragerc`, `[tool.coverage.*]`, `[coverage:*]` | in the project env: `python -m coverage run -m pytest -q -p no:cacheprovider && python -m coverage report --format=total` | Writes `.coverage` into the repo: set `COVERAGE_FILE=<scratch>/.coverage`. Gate: `fail_under` in `[tool.coverage.report]`. |
| `pip-audit` | deps_audit | (none) | `uvx pip-audit -r <requirements file>`; with `uv.lock`: `uv export --frozen --format requirements-txt --no-hashes -o <scratch>/req.txt` then `uvx pip-audit -r <scratch>/req.txt`; in an env: `uvx pip-audit` with that env active | Needs the network (PyPI advisory data). |
| `vulture` | deadcode | `[tool.vulture]` | `uvx vulture <src> --min-confidence 80` | False positives: framework entry points, `__all__`, plugins. A whitelist file is the baseline. |

## Suppressions

`# noqa`, `# type: ignore`, `# pylint: disable`, `# pragma: no cover`. A `# type: ignore` without an error code (`[attr-defined]`) hides every error on the line.

## First steps for recommendations

Lint and format, with ruff (one tool for both):

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
[tool.ruff.lint]
select = ["E", "F", "B", "I", "UP"]
```

CI step (GitHub Actions):

```yaml
- uses: astral-sh/setup-uv@v5   # check the latest major
- run: uvx ruff check . && uvx ruff format --check .
```

Types: start with `mypy` on the hotspot packages only, then widen:

```toml
[tool.mypy]
files = ["src/pkg/core"]
disallow_untyped_defs = true
```

Coverage gate:

```toml
[tool.coverage.report]
fail_under = 70   # the measured value, rounded down, then raise it
```

Pre-commit: `.pre-commit-config.yaml` with the `astral-sh/ruff-pre-commit` hooks `ruff` and `ruff-format`.
