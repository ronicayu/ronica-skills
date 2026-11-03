#!/usr/bin/env bash
#
# Print the absolute path of a Python 3.11 or later interpreter.
#
# Resolution order:
#   1. $AGENTIC_TEAM_PYTHON, when it names a Python 3.11 or later. An invalid
#      value is reported on stderr and skipped.
#   2. python3.13, python3.12, python3.11 on PATH.
#   3. python3 on PATH, when it is 3.11 or later.
#
# Exits 2 with the fix when none qualifies.
#
# Usage: python-path.sh. The scripts/run, scripts/config, and scripts/tg
# wrappers call it and run their script with the result.

set -euo pipefail

# ok_python COMMAND — succeeds when COMMAND runs and is Python 3.11 or later.
ok_python() {
  "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1
}

# emit COMMAND — prints COMMAND's absolute path and succeeds when it qualifies.
emit() {
  local found
  found=$(command -v "$1" 2>/dev/null) || return 1
  [[ $found == /* ]] || return 1
  ok_python "$found" || return 1
  printf '%s\n' "$found"
}

if [[ -n ${AGENTIC_TEAM_PYTHON:-} ]]; then
  emit "$AGENTIC_TEAM_PYTHON" && exit 0
  printf 'python-path.sh: ignoring AGENTIC_TEAM_PYTHON=%s: not Python 3.11 or later\n' \
    "$AGENTIC_TEAM_PYTHON" >&2
fi

for name in python3.13 python3.12 python3.11 python3; do
  emit "$name" && exit 0
done

printf 'python-path.sh: no Python 3.11 or later found. Install Python 3.11 or later, or set AGENTIC_TEAM_PYTHON to its path.\n' >&2
exit 2
