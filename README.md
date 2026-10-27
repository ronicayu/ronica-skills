# ronica-skills

A marketplace of Claude Code plugins.

## Plugins

| Plugin | What it does |
| --- | --- |
| [`writing-editor`](plugins/writing-editor) | Writes, reviews and edits prose as an expert editor: argument structure via Barbara Minto's Pyramid Principle, then cognitive load, claim sourcing, line quality, and the tells of machine-drafted text. New documents are drafted through gated stages: purpose, sources, an approved outline, then content. Also covers technical documentation: docs, READMEs, RFCs, PR descriptions, commit messages, and issues, using Diátaxis, Google developer style, STE, and Global English. |
| [`architecture-design`](plugins/architecture-design) | Drafts and reviews architecture design documents and ADRs for a design review. Critiques the design itself (right problem first, then each goal traced to its mechanism, contradictions, structure, failure behaviour, decisions, and whether the team can run it), and checks the content a prose editor cannot: problem and measurable outcomes, ranked goals, trade-offs that name the losing goal, options including doing nothing, decisions with the alternative they rejected, failure modes, migration, and the review record. Ships a design document template, an ADR template and a reviewer checklist; a project's own template wins. Works best with `writing-editor` installed. |
| [`taskgraph`](plugins/taskgraph) | Tracks project tasks and dependencies in a SQLite DAG. Plan backwards from a goal, `ready` shows what can start now, and `graph` opens an interactive view with hover path highlighting and task details. |
| [`agentic-team`](plugins/agentic-team) | Provides a manager agent that assigns Taskgraph tasks to Claude sessions, monitors progress, and verifies results. |
| [`telegram-send`](plugins/telegram-send) | Sends a Telegram message from the terminal — notifications, status updates, and completion summaries that reach a phone. Ships a wrapper script that reads credentials from a mode-600 file, keeps the bot token out of argv and the transcript, guards the 4096-character limit, and reports what the API's errors actually mean. |

## Install

### Claude Code

```text
/plugin marketplace add ronicayu/ronica-skills
/plugin install writing-editor@ronica-skills
/plugin install architecture-design@ronica-skills
/plugin install agentic-team@ronica-skills
/plugin install telegram-send@ronica-skills
/plugin install taskgraph@ronica-skills
```

Skills then trigger on their own descriptions, or explicitly via
`/writing-editor`, `/architecture-design`, `/telegram-send`, and `/taskgraph`.
After installing `agentic-team`, select `agentic-team:manager` in the agent
picker, invoke it with `@agent-agentic-team:manager`, or type
`/agentic-team:manager` in an existing session. In each repository
where you use the Manager, run `/agentic-team:setup` to create its
`.agentic-team.toml` project config. See the
[agentic-team README](plugins/agentic-team/README.md) for configuration,
prompt templates, and model choices.

`telegram-send` reads its bot token and chat id from
`~/.config/telegram-send/credentials` (mode 600); its `references/setup.md`
walks through creating the bot and finding the chat id.

## Layout

```text
ronica-skills/
├── .claude-plugin/marketplace.json      # Claude Code catalog
├── plugins/<plugin>/
│   ├── .claude-plugin/plugin.json       # Claude Code manifest
│   ├── skills/<skill>/SKILL.md          # Claude Code skills
│   ├── agents/<agent>.md                # Claude Code subagents
│   ├── commands/<command>.md           # Claude Code commands
│   ├── hooks/hooks.json                # Claude Code lifecycle hooks
│   ├── .mcp.json / .lsp.json           # Claude Code tool servers
│   ├── output-styles/<style>.md        # Claude Code output styles
│   └── workflows/<workflow>.js         # Claude Code workflows
├── scripts/validate.sh
└── docs/                                # design notes
```

## Plugin components

Claude Code plugins can bundle skills, subagents, commands, hooks, MCP and LSP
servers, output styles, and workflows. A plugin can contain any combination of
these components, including no skills.

Use the conventional paths in the layout above, or declare custom component
paths in `.claude-plugin/plugin.json`. See
[plugin-components.md](docs/plugin-components.md) for examples, validation
scope, and notes on adding a component-only plugin.

Plugin sources in `marketplace.json` are bare names, resolved under
`metadata.pluginRoot` (`./plugins`). That resolution needs Claude Code 2.1.239
or newer; on older versions, spell sources out as `./plugins/<plugin>`.

## Adding a plugin

1. Copy the template:

   ```sh
   cp -R templates/plugin-template plugins/my-plugin
   ```

2. Add the components the plugin provides. Remove the sample skill if your
   plugin does not provide one.
3. For each skill, set its frontmatter `name` to match its directory. For each
   Claude Code agent, include `name` and `description` in its frontmatter.
4. Fill in `name`, `description`, and `version` in the Claude Code manifest.
   The plugin name and version must agree with the `marketplace.json` entry.
5. Register the plugin in `.claude-plugin/marketplace.json` with
   `"source": "my-plugin"`.
6. Run `./scripts/validate.sh`.

Write descriptions to say *when to use the skill*, not just what it is — that
text is the whole basis on which the model decides to load it. Keep it under
1024 characters.

## Validation

```sh
./scripts/validate.sh
```

Checks that the catalog parses, every `source` resolves, Claude Code manifests
are valid, required frontmatter is present, supported JSON configuration files
parse, and no plugin directory is left unregistered. Runs in CI on pushes and
PRs to `main`.

## License

MIT — see [LICENSE](LICENSE).
