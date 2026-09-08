# Codex and GitHub Copilot Installation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make every repository plugin discoverable and installable through the
Codex plugin marketplace and make shared skills installable with GitHub
Copilot's `gh skill` workflow.

**Architecture:** Add a Codex marketplace catalog at the repository root and a
thin Codex manifest beside each existing Claude Code and OpenClaw manifest.
All three hosts continue to load the existing `skills/<name>/SKILL.md`
directories. Extend the repository validator to enforce the new catalog and
three-way manifest agreement, then document both native install flows.

**Tech Stack:** JSON manifests, Bash, jq, awk, GitHub Actions, Codex CLI,
GitHub CLI.

---

### Task 1: Cover the Codex marketplace validator contract

**Files:**
- Create: `tests/validate-codex-marketplace.sh`
- Modify: `scripts/validate.sh`

**Step 1: Write the failing test**

Create `tests/validate-codex-marketplace.sh`. It must:

1. Create a temporary, minimal marketplace fixture with:
   - `.claude-plugin/marketplace.json`
   - `.agents/plugins/marketplace.json`
   - one plugin at `plugins/example-plugin`
   - matching `.claude-plugin/plugin.json`, `openclaw.plugin.json`, and
     `.codex-plugin/plugin.json`
   - `skills/example-skill/SKILL.md` valid frontmatter.
2. Invoke a testable validator entry point against the fixture and expect
   success.
3. Change the Codex manifest `version` to `9.9.9`, invoke the validator again,
   and require a nonzero status plus a message identifying the version
   mismatch.
4. Restore the version, replace the Codex catalog's source path with a missing
   directory, invoke the validator again, and require a nonzero status plus a
   missing-path message.
5. Clean up its temporary directory with a shell `trap`.

**Step 2: Run the test to verify it fails**

Run:

```bash
./tests/validate-codex-marketplace.sh
```

Expected: FAIL because `scripts/validate.sh` has no fixture-root argument and
does not require or validate Codex manifests/catalog entries.

**Step 3: Implement the minimal validator support**

Modify `scripts/validate.sh`:

1. Accept an optional repository-root positional argument, defaulting to its
   current repository-root behavior, so the fixture test can invoke it without
   modifying the working tree.
2. Define `.agents/plugins/marketplace.json` as the Codex marketplace.
3. Validate that catalog JSON parses, has a nonempty `name`, has a nonempty
   `interface.displayName`, and has at least one `plugins` entry.
4. For every Claude marketplace plugin, find exactly one Codex marketplace
   entry with the same name. Require its `source` to be an object with
   `source: "local"` and a `path` that begins with `./`, then resolve that path
   relative to the repository root and require it to be the same plugin
   directory.
5. In the existing per-plugin manifest loop, add
   `$dir/.codex-plugin/plugin.json` and require valid JSON, matching `name`,
   matching explicit `version`, nonempty `description`, and exactly
   `"./skills/"` in `skills`.
6. Track Codex catalog entry names and report any catalog entry that does not
   correspond to a registered Claude marketplace plugin.
7. Update the script header comments to describe the Codex checks and keep
   existing Claude/OpenClaw behavior unchanged.

**Step 4: Run the focused test to verify it passes**

Run:

```bash
./tests/validate-codex-marketplace.sh
```

Expected: PASS, including the deliberate mismatched-version and
missing-source cases being rejected.

**Step 5: Commit**

```bash
git add scripts/validate.sh tests/validate-codex-marketplace.sh
git commit -m "test: validate Codex marketplace manifests"
```

### Task 2: Add Codex marketplace metadata

**Files:**
- Create: `.agents/plugins/marketplace.json`
- Create: `plugins/write-doc/.codex-plugin/plugin.json`
- Create: `plugins/writing-editor/.codex-plugin/plugin.json`
- Create: `plugins/telegram-send/.codex-plugin/plugin.json`

**Step 1: Add the Codex marketplace catalog**

Create `.agents/plugins/marketplace.json`:

```json
{
  "name": "ronica-skills",
  "interface": {
    "displayName": "Ronica Skills"
  },
  "plugins": [
    {
      "name": "write-doc",
      "source": {
        "source": "local",
        "path": "./plugins/write-doc"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    },
    {
      "name": "writing-editor",
      "source": {
        "source": "local",
        "path": "./plugins/writing-editor"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    },
    {
      "name": "telegram-send",
      "source": {
        "source": "local",
        "path": "./plugins/telegram-send"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

**Step 2: Add the three Codex manifests**

Create one `.codex-plugin/plugin.json` per plugin using its existing matching
name, version, and description:

```json
{
  "name": "<existing-plugin-name>",
  "version": "1.0.0",
  "description": "<existing-plugin-description>",
  "skills": "./skills/"
}
```

Use the description from that plugin's existing
`.claude-plugin/plugin.json`; do not change its wording.

**Step 3: Run the marketplace validator**

Run:

```bash
./scripts/validate.sh
```

Expected: PASS and report all three plugins as valid across Claude Code,
OpenClaw, and Codex manifests.

**Step 4: Inspect the catalog paths**

Run:

```bash
jq -r '.plugins[].source.path' .agents/plugins/marketplace.json |
  while IFS= read -r path; do test -d "${path#./}"; done
```

Expected: exit status 0.

**Step 5: Commit**

```bash
git add .agents/plugins plugins/*/.codex-plugin/plugin.json
git commit -m "feat: add Codex plugin marketplace"
```

### Task 3: Document Codex and Copilot installation

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-04-26-skill-marketplace-design.md`

**Step 1: Update the repository summary and install section**

In `README.md`:

1. State that the marketplace supports Claude Code, OpenClaw, Codex, and
   GitHub Copilot.
2. Add a **Codex** section after Claude Code that documents:

   ```text
   codex plugin marketplace add ronicayu/ronica-skills
   ```

   Then instruct users to run `/plugins`, choose **Ronica Skills**, install the
   wanted plugin, and begin a new session.
3. Add a **GitHub Copilot** section that requires GitHub CLI 2.90.0 or later,
   recommends `gh skill preview ronicayu/ronica-skills <skill-name>` before
   installation, and documents:

   ```text
   gh skill install ronicayu/ronica-skills <skill-name>
   ```

   Explain that `gh skill install ronicayu/ronica-skills` provides an
   interactive choice and that GitHub CLI installs into Copilot's appropriate
   skill location.
4. Update the layout tree to include the Codex catalog and each plugin's Codex
   manifest.
5. Update validation and plugin-authoring text to require three matching
   manifests and registration in both catalogs.

**Step 2: Update the existing marketplace design note**

Amend `docs/superpowers/specs/2026-04-26-skill-marketplace-design.md` to
describe Codex and GitHub Copilot as supported hosts, add their manifest and
installation paths, and revise its validation statement to include Codex.
Preserve the historical design's intent and its Claude/OpenClaw details.

**Step 3: Verify documented commands and paths**

Run:

```bash
rg -n 'codex plugin marketplace add ronicayu/ronica-skills|/plugins|gh skill (preview|install) ronicayu/ronica-skills|\.agents/plugins/marketplace\.json|\.codex-plugin/plugin\.json' README.md docs/superpowers/specs/2026-04-26-skill-marketplace-design.md
```

Expected: every required command and manifest path is present.

**Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-04-26-skill-marketplace-design.md
git commit -m "docs: document Codex and Copilot installation"
```

### Task 4: Run repository validation

**Files:**
- Verify: `scripts/validate.sh`
- Verify: `tests/validate-codex-marketplace.sh`
- Verify: `.github/workflows/validate.yml`

**Step 1: Run the focused validator test**

Run:

```bash
./tests/validate-codex-marketplace.sh
```

Expected: PASS.

**Step 2: Run the full repository validator**

Run:

```bash
./scripts/validate.sh
```

Expected: PASS with no failed checks. A warning that the Claude CLI is not on
`PATH` remains acceptable because the validator already treats that external
tool as optional.

**Step 3: Check the final working tree**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and only intentionally uncommitted changes, if
any.

**Step 4: Commit any validation-only correction**

If validation required a correction, commit only that correction:

```bash
git add <corrected-files>
git commit -m "fix: align Codex marketplace metadata"
```
