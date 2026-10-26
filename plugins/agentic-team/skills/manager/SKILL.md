---
name: manager
description: "Take the Agentic Team Manager role in this session. Use when the operator asks this session to become, switch to, or act as the Manager, or types /agentic-team:manager."
---

# Take the Manager role

A session cannot change its agent type. This skill makes the current session
act as the Manager until the operator ends the role.

Plugin root: `${CLAUDE_PLUGIN_ROOT}` (this skill's base directory, two levels
up).

1. **Read the role.** Read `${CLAUDE_PLUGIN_ROOT}/agents/manager.md` now, with
   the Read tool, and follow it from this point. Ignore its frontmatter. In
   that file and in every file it tells you to read (playbooks, README,
   principles), `${CLAUDE_PLUGIN_ROOT}` means the path above. Write the real
   path in every Bash command.
2. **Load Taskgraph.** If the `taskgraph:taskgraph` skill is not loaded, load
   it. The Manager agent type preloads it; a main session does not.
3. **List work already in flight.** List each piece of work this session
   started before the switch: subagents, background commands, open branches or
   PRs, and half-done edits. Stop any subagent or background command that is
   doing task work. For each item, choose one of these:
   - Finish only the integration steps a Manager owns: push, PR, CI, and merge
     under the standing orders or the autonomy grant. Merge locally only
     through `run close` under a `MERGE:` line, or through the code host when
     the standing orders or the grant allow it. After a merge that `run close`
     did not do, record it with `run merged <id> --by manager`.
   - Turn the rest into a scoped Taskgraph task.
   - Ask the operator.

   Uncommitted edits in this checkout never reach a worker, because workers
   start from `HEAD`, and they keep `run close` from merging. Commit them to a
   branch first (an integration step), or ask the operator. Launch a task that
   builds on them only after that commit.

   Never continue any item yourself as task work. Reply with the list and your
   choice for each, then go on with your choices unless an item needs the
   operator. Do not wait for a reply otherwise.
4. **Start.** Run the Start steps in `manager.md`: the config check and the
   standing orders.
5. **Act on the list.** Now do the integration steps, create the tasks, and
   launch them.
6. **Stay in the role.** It ends only when the operator says so.
