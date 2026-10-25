---
name: setup
description: "Create or complete the Agentic Team project config (.agentic-team.toml) for this repository. Use when setting up the Manager in a project, when .agentic-team.toml is missing, or when `config.py check` reports problems such as TODO values."
---

# Set up an Agentic Team project

Create or complete `.agentic-team.toml` in the repository root so the Manager
can run. Key meanings are in the plugin README under Configuration:
`${CLAUDE_PLUGIN_ROOT}/README.md`. Check the config at any point with:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" check
```

## Steps

1. **Start from the template.** If `.agentic-team.toml` does not exist, copy
   `${CLAUDE_PLUGIN_ROOT}/templates/agentic-team.toml` to it. If it exists,
   keep it and fill in only what `config.py check` reports. Do not overwrite
   values that are already set.
2. **Edit the text, one key at a time.** Change each value in place with a
   text edit and keep the comments; they are the inline help. To set a key
   the template has commented out, uncomment its line. Omit a key to use its
   default (`config.py show` prints the defaults). Write `""` or `[]` when an
   item does not apply.
3. **Fill what the repository shows.** Do not guess.
   - `taskgraph.project`: run
     `TG=$("${CLAUDE_PLUGIN_ROOT}/scripts/tg-path.sh")` and then
     `python3 "$TG" projects`. If one project matches this repository,
     suggest it. Otherwise ask the user.
   - `taskgraph.plan`: suggest a plan file only if the repository has an
     obvious one, such as `PLAN.md`. Otherwise leave it commented out.
   - `constraints.pinned_versions`: suggest values from lockfiles or version
     files the repository already has, then ask the user to confirm them.
4. **Ask for the rest.** Ask the user, one question at a time, for each
   remaining `"TODO"`. The `constraints` keys affect safety, so do not set
   one to `""` unless the user confirms that nothing applies.
5. **Keep private values and run state out of git.** Put machine-specific or
   private values in `.agentic-team.local.toml`, with the same tables and
   only the keys that override. Its keys win; a list there replaces the
   tracked list. Add `.agentic-team.local.toml` and `.agentic-team/` (the
   Manager's run directory for briefs, reports, standing orders, and gates)
   to `.gitignore` if they are not already ignored.
6. **Check the result.** Run `config.py check`. Setup is done only when it
   prints `ok`; otherwise fix each problem it lists and run it again. Make
   sure neither file holds a credential or secret. Show the user the final
   file and `config.py show`, and say which keys use their defaults.

Do not commit the config unless the user asks.
