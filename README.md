# ronica-skills

A skill marketplace for Claude Code and OpenClaw. `SKILL.md` content is shared;
each ecosystem reads its own thin manifest.

## Plugins

| Plugin | What it does |
| --- | --- |
| [`write-doc`](plugins/write-doc) | Authors a document through four gated stages — purpose and audience, sources, a stress-tested Minto pyramid outline, then content. Body prose is never written before the outline is signed off. |
| [`writing-editor`](plugins/writing-editor) | Edits and reviews prose as an expert editor: argument structure via Barbara Minto's Pyramid Principle, then cognitive load, claim sourcing, line quality, and the tells of machine-drafted text. |

## Install

### Claude Code

```text
/plugin marketplace add ronicayu/ronica-skills
/plugin install write-doc@ronica-skills
/plugin install writing-editor@ronica-skills
```

Skills then trigger on their own descriptions, or explicitly via `/write-doc`
and `/writing-editor`.

### OpenClaw

Reference a plugin through its `openclaw.plugin.json`, or publish individual
skills with `clawhub sync`.

## Layout

```text
ronica-skills/
├── .claude-plugin/marketplace.json      # Claude Code catalog
├── plugins/<plugin>/
│   ├── .claude-plugin/plugin.json       # Claude Code manifest
│   ├── openclaw.plugin.json             # OpenClaw manifest
│   └── skills/<skill>/SKILL.md          # shared content
├── scripts/validate.sh
└── docs/                                # design notes
```

Plugin sources in `marketplace.json` are bare names, resolved under
`metadata.pluginRoot` (`./plugins`). That resolution needs Claude Code 2.1.239
or newer; on older versions, spell sources out as `./plugins/<plugin>`.

## Adding a plugin

1. Copy the template:

   ```sh
   cp -R templates/plugin-template plugins/my-plugin
   ```

2. Rename `skills/skill-name/` to your skill's name, and set the same name in
   `SKILL.md` frontmatter — the validator requires them to match.
3. Fill in `name`, `description`, and `version` in both manifests. All three
   must agree with the `marketplace.json` entry.
4. Register the plugin in `.claude-plugin/marketplace.json` with
   `"source": "my-plugin"`.
5. Run `./scripts/validate.sh`.

Write descriptions to say *when to use the skill*, not just what it is — that
text is the whole basis on which the model decides to load it. Keep it under
1024 characters.

## Validation

```sh
./scripts/validate.sh
```

Checks that the catalog parses, every `source` resolves, each plugin carries
both manifests with a matching name and version, every `SKILL.md` has valid
frontmatter whose name matches its directory, and no plugin directory is left
unregistered. Runs in CI on pushes and PRs to `main`.

## License

MIT — see [LICENSE](LICENSE).
