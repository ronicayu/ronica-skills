#!/usr/bin/env bash
#
# Validate the ronica-skills marketplace.
#
# Checks:
#   1. .claude-plugin/marketplace.json parses and has the required fields.
#   2. Every marketplace entry's source resolves to a real plugin directory.
#   3. Every plugin has a Claude Code manifest with a matching name and version.
#   4. Every plugin ships at least one supported Claude Code component.
#   5. Skills and agents have the required frontmatter; hook, MCP, and LSP
#      configuration files contain valid JSON.
#   6. Every directory under plugins/ is registered in marketplace.json.
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

  skill_files=("$dir"/skills/*/SKILL.md)
  agent_files=("$dir"/agents/*.md)
  command_files=("$dir"/commands/*.md)
  output_style_files=("$dir"/output-styles/*.md)
  workflow_files=("$dir"/workflows/*.js)
  has_components=false

  if [[ -f ${skill_files[0]} ]]; then
    has_components=true
  fi
  if [[ -f ${agent_files[0]} || -f ${command_files[0]} ||
        -f ${output_style_files[0]} || -f ${workflow_files[0]} ||
        -f "$dir/hooks/hooks.json" || -f "$dir/.mcp.json" ||
        -f "$dir/.lsp.json" ]]; then
    has_components=true
  fi

  entry_version=$(json_get "$marketplace" ".plugins[$i].version")
  [[ -n $entry_version ]] || err "$entry_name: marketplace entry has no version"
  [[ -n $(json_get "$marketplace" ".plugins[$i].description") ]] ||
    err "$entry_name: marketplace entry has no description"

  # -- manifests --------------------------------------------------------

  claude_manifest="$dir/.claude-plugin/plugin.json"

  for manifest in "$claude_manifest"; do
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

    if jq -e '
      [
        .skills,
        .commands,
        .agents,
        .hooks,
        .mcpServers,
        .lspServers,
        .outputStyles,
        .workflows,
        .experimental.themes
      ]
      | any(.[]; . != null and . != [] and . != {} and . != "")
    ' "$manifest" >/dev/null 2>&1; then
      has_components=true
    fi

    while IFS= read -r component_path; do
      [[ -n $component_path ]] || continue
      component_path=${component_path#./}
      component_path="$dir/$component_path"
      if [[ -f $component_path/SKILL.md ]]; then
        skill_seen=false
        for existing in "${skill_files[@]}"; do
          [[ $existing == "$component_path/SKILL.md" ]] && skill_seen=true
        done
        [[ $skill_seen == true ]] || skill_files+=("$component_path/SKILL.md")
      elif [[ -d $component_path ]]; then
        custom_skill_files=("$component_path"/*/SKILL.md "$component_path"/*/*/SKILL.md)
        for custom_skill in "${custom_skill_files[@]}"; do
          [[ -f $custom_skill ]] || continue
          skill_seen=false
          for existing in "${skill_files[@]}"; do
            [[ $existing == "$custom_skill" ]] && skill_seen=true
          done
          [[ $skill_seen == true ]] || skill_files+=("$custom_skill")
        done
      else
        err "$entry_name: declared skills path '$component_path' does not exist"
      fi
    done < <(jq -r '
      if (.skills | type) == "string" then .skills
      elif (.skills | type) == "array" then .skills[]
      else empty
      end
    ' "$manifest")

    while IFS= read -r component_path; do
      [[ -n $component_path ]] || continue
      component_path=${component_path#./}
      component_path="$dir/$component_path"
      if [[ ! -f $component_path ]]; then
        err "$entry_name: declared agent path '$component_path' does not exist"
        continue
      fi
      agent_seen=false
      for existing in "${agent_files[@]}"; do
        [[ $existing == "$component_path" ]] && agent_seen=true
      done
      [[ $agent_seen == true ]] || agent_files+=("$component_path")
    done < <(jq -r '
      if (.agents | type) == "string" then .agents
      elif (.agents | type) == "array" then .agents[]
      else empty
      end
    ' "$manifest")
  done

  [[ $has_components == true ]] ||
    err "$entry_name: no supported plugin components found"

  # -- component files --------------------------------------------------

  for component in "${skill_files[@]}" "${agent_files[@]}"; do
    [[ -f $component ]] || continue
    component_dir=$(basename "$(dirname "$component")")
    component_name=$(basename "$component" .md)
    component_label="$entry_name/$component_name"
    [[ $component == */SKILL.md ]] && component_label="$entry_name/$component_dir"
    block=$(frontmatter "$component")

    if [[ -z $block ]]; then
      err "$component_label: $component has no YAML frontmatter"
      continue
    fi

    frontmatter_name=$(printf '%s\n' "$block" | fm_value name)
    frontmatter_desc=$(printf '%s\n' "$block" | fm_value description)

    if [[ -z $frontmatter_name ]]; then
      err "$component_label: frontmatter is missing name"
    elif [[ $component == */SKILL.md && $frontmatter_name != "$component_dir" ]]; then
      err "$component_label: frontmatter name '$frontmatter_name' != directory name"
    fi

    if [[ -z $frontmatter_desc ]]; then
      err "$component_label: frontmatter is missing description"
    elif [[ $component == */SKILL.md && ${#frontmatter_desc} -gt $max_description ]]; then
      err "$component_label: description is ${#frontmatter_desc} chars (max $max_description)"
    fi
  done

  for json_file in "$dir/hooks/hooks.json" "$dir/.mcp.json" "$dir/.lsp.json"; do
    [[ -f $json_file ]] || continue
    if ! jq empty "$json_file" 2>/dev/null; then
      err "$entry_name: $json_file is not valid JSON"
    fi
  done

  if [[ $failures -eq $failures_before ]]; then
    skill_count=0
    agent_count=0
    for component in "${skill_files[@]}"; do
      [[ -f $component ]] && skill_count=$((skill_count + 1))
    done
    for component in "${agent_files[@]}"; do
      [[ -f $component ]] && agent_count=$((agent_count + 1))
    done
    ok "$entry_name: manifest and $skill_count skill(s), $agent_count agent(s) valid"
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
