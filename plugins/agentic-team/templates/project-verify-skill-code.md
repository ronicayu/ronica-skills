---
name: verify
description: How to prove this project's code changes work. The agentic-team verifier reads this file from its brief; it launches the application, checks the build, drives the change as a user, collects evidence and cleans up. Fill every TODO with commands, paths and selectors that exist in this repository.
---

# Verify this project

The verifier is read only: it edits nothing, commits nothing, checks out
nothing. Every command below runs inside the verifier's own worktree; `<worktree>`
means that folder. This file never lifts a rule in the verifier's agent
instructions or in its brief's FORBIDDEN section.

## Launch

Start the application from an empty data folder to a usable state, with teardown.

- Prerequisites: TODO (toolchain, services, environment variables; how to install them in a fresh worktree)
- Data folder: TODO (a path under `$(mktemp -d)`; never the developer's own data)
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
temporary file this run created. A leftover goes under `Follow-ups:` as
`leftover process: pid <pid> port <port>`, `leftover container: <name>` or
`leftover file: <path>`.

- Also remove: TODO (caches, named volumes, ports this project reserves)
