# Codex and GitHub Copilot Installation Design

## Goal

Make the existing skill marketplace installable through Codex's native plugin
marketplace and GitHub Copilot's native skill installation workflow without
duplicating skill content.

## Architecture

The existing `plugins/<plugin>/skills/<skill>/SKILL.md` directories remain the
single source of truth for every skill, including scripts and references.

Codex support adds:

- `.agents/plugins/marketplace.json` at the repository root, cataloging the
  plugins in `./plugins/`.
- `.codex-plugin/plugin.json` in every plugin folder, pointing to its existing
  `./skills/` directory.

The Codex marketplace will be added using:

```sh
codex plugin marketplace add ronicayu/ronica-skills
```

Users then open `/plugins`, select this marketplace, install a plugin, and
start a new session.

GitHub Copilot already recognizes the Agent Skills `SKILL.md` layout. Users
will install skills through GitHub CLI:

```sh
gh skill install ronicayu/ronica-skills <skill-name>
```

`gh skill` selects the correct Copilot skill location and preserves provenance
metadata for updates. The README will also document interactive installation
and the required GitHub CLI version.

## Validation

Extend `scripts/validate.sh` to require a Codex manifest for every registered
plugin, verify its name and version agree with the existing Claude Code and
OpenClaw manifests, and verify every Codex marketplace entry resolves to a
plugin directory. CI continues to run that single validator.

## Constraints

- Do not fork or relocate `SKILL.md` content.
- Do not add package-manager dependencies.
- Preserve existing Claude Code and OpenClaw installation workflows.
- Include only manifests, documentation, and validation needed for these two
  additional distribution paths.
