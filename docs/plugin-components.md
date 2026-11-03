# Plugin components

Each directory under `plugins/` is installed as one Claude Code plugin. Put
components at the plugin root, beside `.claude-plugin/`, not inside it.

## Choose components by what the plugin provides

| Component | Conventional path | What it adds |
| --- | --- | --- |
| Skill | `skills/<name>/SKILL.md` | On-demand instructions, optionally invoked as a command |
| Agent | `agents/<name>.md` | A specialized subagent Claude can delegate to |
| Command | `commands/<name>.md` | A slash command |
| Hook | `hooks/hooks.json` | Commands that run on Claude Code lifecycle events |
| MCP server | `.mcp.json` | Tools from an MCP server |
| LSP server | `.lsp.json` | Language-server integration |
| Output style | `output-styles/<name>.md` | A named response style |
| Workflow | `workflows/<name>.js` | A Claude Code workflow |

Claude Code also accepts custom component paths in
`.claude-plugin/plugin.json`. Use the [plugin manifest reference](https://code.claude.com/docs/en/plugins-reference)
for current path and schema details.

## Add components to a plugin

Start with the plugin template, remove the sample skill if the plugin does not
provide one, add at least one Claude Code component, and register the plugin
in `.claude-plugin/marketplace.json`.

An agent file needs `name` and `description` frontmatter:

```markdown
---
name: reviewer
description: Review changes for correctness and regressions.
---

You are a code reviewer. Report only actionable findings.
```

A hook configuration uses Claude Code's hook schema:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/check.sh"
          }
        ]
      }
    ]
  }
}
```

Review hook commands carefully. Claude Code runs them on the user's machine
when the configured event occurs.

## What the repository validates

`scripts/validate.sh` checks conventional component paths and manifest-declared
skill and agent paths. It verifies skill names against their directories,
requires `name` and `description` on skill and agent frontmatter, and parses
`hooks/hooks.json`, `.mcp.json`, and `.lsp.json` as JSON. The installed Claude
Code CLI performs the official marketplace schema check when available. For
full component-schema validation, also run `claude plugin validate` on the
plugin directory.
