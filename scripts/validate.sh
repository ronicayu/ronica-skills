#!/usr/bin/env bash
#
# Validate the ronica-skills marketplace.
#
# Checks:
#   1. .claude-plugin/marketplace.json parses and has the required fields.
#   2. Every marketplace entry's source resolves to a real plugin directory.
#   3. Every plugin has both manifests (Claude Code + OpenClaw) with a matching
#      name and version.
#   4. Every plugin ships at least one skills/<name>/SKILL.md with valid
#      frontmatter, and the frontmatter name matches its directory.
#   5. Every directory under plugins/ is registered in marketplace.json.
#
# Dependencies: bash, jq, awk. Exits non-zero on the first failing category.

set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

marketplace=".claude-plugin/marketplace.json"
# Claude Code caps skill descriptions; keep them loadable.
max_description=1024
failures=0

err() {
  printf 'FAIL  %s\n' "$*" >&2
  failures=$((failures + 1))
}

ok() {
  printf 'ok    %s\n' "$*"
}

warn() {
  printf 'warn  %s\n' "$*"
}

command -v jq >/dev/null 2>&1 || {
  printf 'validate.sh needs jq on PATH\n' >&2
  exit 2
}

# json_get FILE FILTER — prints the value, or empty string for null/missing.
json_get() {
  jq -r "$2 // empty" "$1" 2>/dev/null
}

# frontmatter FILE — prints the YAML block between the leading and closing ---.
frontmatter() {
  awk 'NR==1 && $0 != "---" { exit } NR==1 { next } /^---[[:space:]]*$/ { exit } { print }' "$1"
}

# fm_value KEY — reads a frontmatter block on stdin, prints the key's value.
fm_value() {
  awk -v key="$1" '
    $0 ~ "^" key ":" {
      sub("^" key ":[[:space:]]*", "")
      sub("[[:space:]]+$", "")
      print
      exit
    }'
}

# ---------------------------------------------------------------- marketplace

if [[ ! -f $marketplace ]]; then
  err "$marketplace is missing"
  exit 1
fi

if ! jq empty "$marketplace" 2>/dev/null; then
  err "$marketplace is not valid JSON"
  exit 1
fi

market_name=$(json_get "$marketplace" '.name')
[[ -n $market_name ]] || err "$marketplace: .name is required"
[[ -n $(json_get "$marketplace" '.owner.name') ]] || err "$marketplace: .owner.name is required"

plugin_count=$(jq '.plugins | length' "$marketplace")
if [[ $plugin_count -eq 0 ]]; then
  err "$marketplace: .plugins is empty"
  exit 1
fi
ok "$marketplace: marketplace '$market_name' with $plugin_count plugin(s)"

plugin_root=$(json_get "$marketplace" '.metadata.pluginRoot')
plugin_root=${plugin_root:-.}
plugin_root=${plugin_root#./}
plugin_root=${plugin_root%/}
[[ -d $plugin_root ]] || err "$marketplace: metadata.pluginRoot '$plugin_root' is not a directory"

# ------------------------------------------------------------------- plugins

registered=""

for i in $(seq 0 $((plugin_count - 1))); do
  entry_name=$(json_get "$marketplace" ".plugins[$i].name")
  if [[ -z $entry_name ]]; then
    err "$marketplace: plugins[$i] has no name"
    continue
  fi

  failures_before=$failures

  source_type=$(jq -r ".plugins[$i].source | type" "$marketplace")
  if [[ $source_type != string ]]; then
    warn "$entry_name: remote source ($source_type), skipping local checks"
    continue
  fi

  source=$(json_get "$marketplace" ".plugins[$i].source")
  if [[ $source == ./* || $source == /* ]]; then
    dir=${source#./}
  else
    # Bare name — resolved under metadata.pluginRoot.
    dir="$plugin_root/$source"
  fi

  if [[ ! -d $dir ]]; then
    err "$entry_name: source '$source' does not resolve to a directory ($dir)"
    continue
  fi
  registered="$registered $dir"

  entry_version=$(json_get "$marketplace" ".plugins[$i].version")
  [[ -n $entry_version ]] || err "$entry_name: marketplace entry has no version"
  [[ -n $(json_get "$marketplace" ".plugins[$i].description") ]] ||
    err "$entry_name: marketplace entry has no description"

  # -- manifests --------------------------------------------------------

  claude_manifest="$dir/.claude-plugin/plugin.json"
  openclaw_manifest="$dir/openclaw.plugin.json"
  claude_version=""
  openclaw_version=""

  for manifest in "$claude_manifest" "$openclaw_manifest"; do
    if [[ ! -f $manifest ]]; then
      err "$entry_name: $manifest is missing"
      continue
    fi
    if ! jq empty "$manifest" 2>/dev/null; then
      err "$entry_name: $manifest is not valid JSON"
      continue
    fi

    manifest_name=$(json_get "$manifest" '.name')
    if [[ $manifest_name != "$entry_name" ]]; then
      err "$entry_name: $manifest declares name '$manifest_name'"
    fi

    manifest_version=$(json_get "$manifest" '.version')
    if [[ -z $manifest_version ]]; then
      err "$entry_name: $manifest has no explicit version"
    elif [[ $manifest_version != "$entry_version" ]]; then
      err "$entry_name: $manifest version '$manifest_version' != marketplace '$entry_version'"
    fi

    [[ -n $(json_get "$manifest" '.description') ]] ||
      err "$entry_name: $manifest has no description"

    if [[ $manifest == "$claude_manifest" ]]; then
      claude_version=$manifest_version
    else
      openclaw_version=$manifest_version
    fi
  done

  # Both manifests are already compared against the marketplace entry, so this
  # only adds signal when the entry itself carries no version.
  if [[ -z $entry_version && -n $claude_version && -n $openclaw_version &&
        $claude_version != "$openclaw_version" ]]; then
    err "$entry_name: manifest versions disagree ($claude_version vs $openclaw_version)"
  fi

  openclaw_skills=$(jq -c '.skills // empty' "$openclaw_manifest" 2>/dev/null)
  [[ -n $openclaw_skills ]] ||
    err "$entry_name: $openclaw_manifest has no skills array"

  # -- skills -----------------------------------------------------------

  skill_files=("$dir"/skills/*/SKILL.md)
  if [[ ! -f ${skill_files[0]} ]]; then
    err "$entry_name: no skills/<name>/SKILL.md found"
    continue
  fi

  for skill in "${skill_files[@]}"; do
    skill_dir=$(basename "$(dirname "$skill")")
    block=$(frontmatter "$skill")

    if [[ -z $block ]]; then
      err "$entry_name/$skill_dir: SKILL.md has no YAML frontmatter"
      continue
    fi

    skill_name=$(printf '%s\n' "$block" | fm_value name)
    skill_desc=$(printf '%s\n' "$block" | fm_value description)

    if [[ -z $skill_name ]]; then
      err "$entry_name/$skill_dir: frontmatter is missing name"
    elif [[ $skill_name != "$skill_dir" ]]; then
      err "$entry_name/$skill_dir: frontmatter name '$skill_name' != directory name"
    fi

    if [[ -z $skill_desc ]]; then
      err "$entry_name/$skill_dir: frontmatter is missing description"
    elif [[ ${#skill_desc} -gt $max_description ]]; then
      err "$entry_name/$skill_dir: description is ${#skill_desc} chars (max $max_description)"
    fi
  done

  if [[ $failures -eq $failures_before ]]; then
    ok "$entry_name: manifests and ${#skill_files[@]} skill(s) valid"
  fi
done

# ------------------------------------------------- unregistered plugin dirs

for dir in "$plugin_root"/*/; do
  dir=${dir%/}
  [[ -d $dir ]] || continue
  case " $registered " in
    *" $dir "*) ;;
    *) err "$dir is not registered in $marketplace" ;;
  esac
done

# ------------------------------------------------- official schema validation

# Catches manifest schema drift this script doesn't know about. Skipped in CI,
# where the CLI isn't installed.
if command -v claude >/dev/null 2>&1; then
  if cli_output=$(claude plugin validate . 2>&1); then
    ok "claude plugin validate: marketplace schema clean"
  else
    printf '%s\n' "$cli_output" >&2
    err "claude plugin validate rejected $marketplace"
  fi
else
  warn "claude CLI not on PATH, skipping official schema validation"
fi

# ------------------------------------------------------------------- verdict

if [[ $failures -gt 0 ]]; then
  printf '\n%d check(s) failed\n' "$failures" >&2
  exit 1
fi

printf '\nall checks passed\n'
