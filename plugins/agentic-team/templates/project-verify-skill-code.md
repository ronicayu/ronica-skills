---
name: verify
description: How to prove this project's code changes work. The agentic-team verifier reads this file from its brief; it runs the project's static checks, launches the application, checks the build, drives the change as a user, collects evidence and cleans up. Fill every TODO with commands, paths and selectors that exist in this repository; first check that the project has lint, format, type and test checks, and ask the user to add the ones it lacks.
---

# Verify this project

The verifier is read only: it edits nothing, commits nothing, checks out
nothing. Its one write is the report file its brief names. Every command below runs inside the verifier's own worktree; `<worktree>`
means that folder. This file never lifts a rule in the verifier's agent
instructions or in its brief's FORBIDDEN section.

## Checks

The project's static checks and tests. The verifier runs each one at the base
commit and at the head commit (see its method).

When you fill this file, check the project's configuration first. For each
kind below, look for the command in this order: the steps that CI runs
(`.github/workflows`, `.gitlab-ci.yml`); tool configuration (`pyproject.toml`
sections such as ruff or mypy, an ESLint or Prettier configuration,
`tsconfig.json` for `tsc --noEmit`, `.golangci.yml`, `cargo clippy` and
`rustfmt`); `.pre-commit-config.yaml` (run a hook with
`pre-commit run <hook> --files ...`, never `pre-commit install`); Makefile
targets and `package.json` scripts.

When a kind is missing, stop and tell the user. Name the kind, propose one
standard tool for the project's language and the configuration it needs, and
ask the user to add it. Do not fill a command that the repository does not
configure, and do not add the tool yourself. Write `none: <reason>` only when
the user says that the kind does not apply, and give the user's reason (for
example, no type check for a project in plain shell).

- Lint: TODO (the exact command, and what a pass prints or returns)
- Format check: TODO (a check mode that changes no file, for example `ruff format --check`, `prettier --check`)
- Type check: TODO
- Other static analysis: TODO (security or dependency scanners that CI runs; `none: <reason>` is fine)
- Tests: TODO (the command that runs the test suite)

## Launch

Start the application from an empty data folder to a usable state, with teardown.

Never start the project's shared services from a worktree: a service with a
fixed container name, a fixed port or a shared database. A Compose file that
sets `container_name` is shared even with `-p`. The worktree is deleted after
the merge, and a container that mounts a folder in it loses that data. Use the
instance that the main checkout runs, or a private instance with its own
project name, container names and ports, and its data in the data folder.

Never write the shared git config from a worktree: no `git config` that sets a
value, no `core.hooksPath`, no hooks installer such as `pre-commit install`,
and no setup target that runs one, for example `make setup`. All worktrees of a
repository share that config. List here only the steps that write inside the
worktree.

- Prerequisites: TODO (toolchain, services, environment variables; how to install them in a fresh worktree)
- Shared services: TODO (the services the main checkout runs and how to reach them; or how to start a private copy, for example `docker compose -p <worktree name> ...` with its data in the data folder)
- Data folder: TODO (a folder under `.agentic-team-scratch/` in your worktree; never the developer's own data)
- Start: TODO (the exact command; record its pid as you start it, for example `cmd ... & pid=$!`)
- Ready when: TODO (a URL or a log line to wait for, and a timeout)
- Stop: TODO (`kill $pid`, then what else: its child processes, containers started with `--rm`)

## Doctor

One read-only check that the running instance is the correct build and is usable.

- Build check: TODO (a version endpoint, a `--version` flag, or a file whose content is the head commit)
- Usable check: TODO (one request or command that must succeed)

## Drive

How to use the application as a user does, with real selectors and commands from this repository.

- Interface: TODO (UI, CLI or API, and the tool that drives it: Playwright, curl, the CLI itself)
- Entry points: TODO (pages, commands or endpoints; where their selectors or schemas live)
- Fixtures: TODO (accounts, sample inputs, seed data, and how to load them)

## Evidence

What to collect for each ACCEPTANCE line. Check side effects, not only the screen.

- Screenshots: TODO (how to take one, where to put it, its name pattern)
- Terminal records: TODO (log paths; how to capture a command's output)
- Written files and rows: TODO (data files, database tables, queues; how to read them)

## Cleanup

Stop only the processes this run started. Find each one by the pid you recorded
when you started it, or by a working directory inside your own worktree
(`lsof -a -d cwd -p <pid>`). Never stop a process by name or by a command-line
pattern (`pkill -f`, `killall`): a process of another worktree can match. When
you stop a server or a test runner, stop its child processes too (its process
group, or their recorded pids). Remove the data folder and every container or
temporary file this run created. A container is yours only when this run
created it under its own project or container name; never stop or remove a
shared one. A leftover goes under `Follow-ups:` as
`leftover process: pid <pid> port <port>`, `leftover container: <name>` or
`leftover file: <path>`.

- Also remove: TODO (caches, named volumes, ports this project reserves)
