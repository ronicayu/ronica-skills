#!/usr/bin/env bash
#
# Print the absolute path of the Python interpreter cr should use.
#
# Resolution order:
#   1. $CODEBASE_RESEARCH_PYTHON, when it names Python 3.10 or later. An
#      invalid value is reported on stderr and skipped.
#   2. The private virtual environment `cr deps` creates, which has
#      tree-sitter: ${CODEBASE_RESEARCH_HOME:-${XDG_CACHE_HOME:-~/.cache}/codebase-research}/venv.
#   3. python3.13, python3.12, python3.11, python3.10 on PATH.
#   4. python3 on PATH, when it is 3.10 or later.
#
# Exits 2 with the fix when none qualifies.

set -euo pipefail

# ok_python COMMAND — succeeds when COMMAND runs and is Python 3.10 or later.
ok_python() {
  "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1
}

# emit COMMAND — prints COMMAND's absolute path and succeeds when it qualifies.
emit() {
  local found
  found=$(command -v "$1" 2>/dev/null) || return 1
  [[ $found == /* ]] || return 1
  ok_python "$found" || return 1
  printf '%s\n' "$found"
}

if [[ -n ${CODEBASE_RESEARCH_PYTHON:-} ]]; then
  emit "$CODEBASE_RESEARCH_PYTHON" && exit 0
  printf 'python-path.sh: ignoring CODEBASE_RESEARCH_PYTHON=%s: not Python 3.10 or later\n' \
    "$CODEBASE_RESEARCH_PYTHON" >&2
fi

home=${CODEBASE_RESEARCH_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/codebase-research}
if [[ -x $home/venv/bin/python ]]; then
  emit "$home/venv/bin/python" && exit 0
fi

for name in python3.13 python3.12 python3.11 python3.10 python3; do
  emit "$name" && exit 0
done

printf 'python-path.sh: no Python 3.10 or later found. Install Python 3.10 or later, or set CODEBASE_RESEARCH_PYTHON to its path.\n' >&2
exit 2
