#!/usr/bin/env bash
#
# Print the absolute path of the installed Taskgraph CLI (tg.py).
#
# Resolution order:
#   1. $TASKGRAPH_TG, when it names an existing file.
#   2. The taskgraph@ronica-skills entry in Claude Code's plugin registry,
#      preferring user scope, then project, then any other scope.
#   3. A sibling taskgraph plugin next to this plugin (source checkout).
#
# Usage: TG=$(tg-path.sh) && python3 "$TG" --project <name> <cmd>

set -euo pipefail

if [[ -n ${TASKGRAPH_TG:-} && -f $TASKGRAPH_TG ]]; then
  printf '%s\n' "$TASKGRAPH_TG"
  exit 0
fi

registry="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/installed_plugins.json"
if [[ -f $registry ]]; then
  path=$(python3 - "$registry" 2>/dev/null <<'PY'
import json, os, sys

with open(sys.argv[1]) as fh:
    entries = json.load(fh).get("plugins", {}).get("taskgraph@ronica-skills", [])
rank = {"user": 0, "project": 1, "local": 2}
for entry in sorted(entries, key=lambda e: rank.get(e.get("scope"), 9)):
    tg = os.path.join(entry.get("installPath", ""), "skills", "taskgraph", "scripts", "tg.py")
    if os.path.isfile(tg):
        print(tg)
        break
PY
) || path=""
  if [[ -n $path ]]; then
    printf '%s\n' "$path"
    exit 0
  fi
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sibling="$script_dir/../../taskgraph/skills/taskgraph/scripts/tg.py"
if [[ -f $sibling ]]; then
  (cd "$(dirname "$sibling")" && printf '%s/tg.py\n' "$(pwd)")
  exit 0
fi

printf 'tg-path.sh: taskgraph plugin not found. Install taskgraph@ronica-skills or set TASKGRAPH_TG.\n' >&2
exit 1
