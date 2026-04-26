# Ronica Skills Marketplace — Design

Date: 2026-04-26

## Goal
Use this repo as a single skill marketplace that works for both Claude Code and OpenClaw, with one source of truth for skill content.

## Approach
Dual-manifest layout. `SKILL.md` files are shared; each ecosystem reads its own thin manifest.

```
ronica-skills/
├── .claude-plugin/
│   └── marketplace.json              # Claude Code catalog
├── plugins/
│   └── <plugin>/
│       ├── .claude-plugin/plugin.json    # Claude Code plugin manifest
│       ├── openclaw.plugin.json          # OpenClaw plugin manifest
│       └── skills/<skill>/SKILL.md       # shared content
├── scripts/validate.sh
├── .github/workflows/validate.yml
├── README.md
└── LICENSE
```

## Manifests

`.claude-plugin/marketplace.json` — `name: ronica-skills`, owner, `metadata.pluginRoot: ./plugins`, one entry per plugin (name + bare source path + description + tags).

`<plugin>/.claude-plugin/plugin.json` — `name`, `description`, explicit `version`, author, homepage, license.

`<plugin>/openclaw.plugin.json` — `name`, `version`, `description`, `skills: ["skills"]`.

`SKILL.md` — minimal frontmatter (`name`, `description`) + markdown body. OpenClaw-specific keys go under `metadata.openclaw.*` when needed; Claude Code ignores unknown keys.

## v1 contents
One example plugin `hello-skill` with one skill, used as the template for new plugins.

## Validation
`scripts/validate.sh` (jq + awk, no extra deps) checks every plugin has both manifests with matching `name`, every `skills/*/SKILL.md` has required frontmatter, and every `marketplace.json` `source` resolves. Wired into a GitHub Actions check on PRs to `main`.

## Install
- Claude Code: `/plugin marketplace add ronicayu/ronica-skills` → `/plugin install <name>@ronica-skills`
- OpenClaw: reference via `openclaw.plugin.json`, or `clawhub sync` to publish individual skills

## Out of scope (YAGNI)
Payments, ratings, web UI, search backend, ClawHub publishing automation, multi-skill example plugin. Add when needed.
