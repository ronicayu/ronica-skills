---
name: setup
description: "Create or complete the Agentic Team project config (.agentic-team.toml) for this repository. Use when setting up the Manager in a project, when .agentic-team.toml is missing, or when `config.py check` reports problems such as TODO values."
---

# Set up an Agentic Team project

Create or complete `.agentic-team.toml` in the repository root so the Manager
can run. Key meanings are in the plugin README under Configuration:
`${CLAUDE_PLUGIN_ROOT}/README.md`. Check the config at any point with:

```sh
"${CLAUDE_PLUGIN_ROOT}/scripts/config" check
```

If it exits 2 with "no Python 3.11 or later found", tell the user to install
Python 3.11 or later, or to set `AGENTIC_TEAM_PYTHON` to its path.

## Steps

1. **Start from the template.** If `.agentic-team.toml` does not exist, copy
   `${CLAUDE_PLUGIN_ROOT}/templates/agentic-team.toml` to it. If it exists,
   keep it and fill in only what `"${CLAUDE_PLUGIN_ROOT}/scripts/config" check` reports. Do not overwrite
   values that are already set.
2. **Edit the text, one key at a time.** Change each value in place with a
   text edit and keep the comments; they are the inline help. To set a key
   the template has commented out, uncomment its line. Omit a key to use its
   default (`"${CLAUDE_PLUGIN_ROOT}/scripts/config" show` prints the defaults). Write `""` or `[]` when an
   item does not apply.
3. **Fill what the repository shows.** Do not guess.
   - `taskgraph.project`: run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/tg" projects`. If one project matches this repository,
     suggest it. Otherwise ask the user.
   - `constraints.forbidden`: suggest items from lockfiles and version files
     the repository already has ("do not change the pinned versions in ..."),
     then ask the user to confirm them.
4. **Ask how the repository merges.** Ask whether it merges only through
   pull or merge requests. If yes, set `[merge] mode = "pr"`. Set `host` only
   when the `origin` URL is a self-managed GitLab. Ask for `method` (`merge`,
   `squash`, `rebase`). Confirm that `gh auth status` or `glab auth status`
   passes; if it does not, say the operator runs the login.
5. **Ask for the rest.** Ask the user one question for the remaining `"TODO"`,
   `forbidden`. It affects safety, so do not set it to `[]` unless the user
   confirms that nothing applies.
6. **Keep private values and run state out of git.** Put machine-specific or
   private values in `.agentic-team.local.toml`, with the same tables and
   only the keys that override. Its keys win; a list there replaces the
   tracked list. Add `.agentic-team.local.toml`, `.agentic-team/` (the
   Manager's run directory for briefs and standing orders), and
   `.claude/worktrees/` (where each worker's git worktree lives) to
   `.gitignore` if they are not already ignored.
7. **Trust the workspace.** `claude --bg` refuses to start in a workspace that
   is not trusted. A trusted parent folder does not count. Tell the user to
   run `claude` once in the repository and accept the trust prompt.
8. **Check for the project verify skill.** The verifier reads
   `.claude/skills/verify/SKILL.md` from the repository: it says how to prove
   this project's artifacts (how to launch and drive the application, or where
   the sources are and which script recomputes a count). Run
   `test -f .claude/skills/verify/SKILL.md`. If the file exists, leave it. If
   it is missing, tell the user, and offer to create it from the skeleton for
   the project's verify kind (`"${CLAUDE_PLUGIN_ROOT}/scripts/config" get verify.kind`):
   - `code`: copy `${CLAUDE_PLUGIN_ROOT}/templates/project-verify-skill-code.md`
     to `.claude/skills/verify/SKILL.md`. Its sections are Launch, Doctor,
     Drive, Evidence and Cleanup.
   - `schema` or `design-doc`: copy
     `${CLAUDE_PLUGIN_ROOT}/templates/project-verify-skill-document.md` to the
     same path. Its sections are Sources, Recompute, Consistency, Render and
     Review.

   Then fill each `TODO` from what the repository shows: real commands, paths,
   selectors and scripts. Do not invent a command; when you cannot find one,
   leave the `TODO` and say so. A project with tasks of both kinds keeps both
   section sets in the one file. Keep the Cleanup rule as the skeleton states
   it: stop only processes the run started, by recorded pid or by a working
   directory inside the worktree, never by name or pattern. The file is
   repository content: commit it only when the user asks. The verifier reads
   it from the commit under review, or from the main checkout when that commit
   has none, so an uncommitted file still counts. Without the file the
   verifier still runs; it reports the highest level it can prove and names
   the method step it could not carry out. When this skill runs inside a
   Manager session, the Manager does not write the file: it reports the gap
   to the operator.
9. **Check the result.** Run `"${CLAUDE_PLUGIN_ROOT}/scripts/config" check`. Setup is done only when it
   prints `ok`; otherwise fix each problem it lists and run it again. Make
   sure neither file holds a credential or secret. Show the user the final
   file and `"${CLAUDE_PLUGIN_ROOT}/scripts/config" show`, and say which keys use their defaults.

Do not commit the config unless the user asks.
