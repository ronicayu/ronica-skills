#!/usr/bin/env bash
#
# Set up the statechart runner without mise.
#
# Usage: setup.sh [CACHE_DIR]
#
# Downloads tla2tools.jar v1.7.4 to CACHE_DIR (default ~/.cache/statechart),
# checks its sha256, and prints the TLA2TOOLS and JAVA export lines on stdout.
# It also checks for Java 11 or later and for a runtime that can run the
# runner's TypeScript. It installs nothing else. Messages go to stderr.
#
# Exit status: 0 when every check passes, 1 when any check fails.
# Part of ronica-skills; not from upstream pstack (see NOTICE.md).

set -euo pipefail

TLC_VERSION=1.7.4
TLC_URL="https://github.com/tlaplus/tlaplus/releases/download/v${TLC_VERSION}/tla2tools.jar"
TLC_SHA256=936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88

cache_dir=${1:-"$HOME/.cache/statechart"}
jar="$cache_dir/tla2tools.jar"
failed=0

say() { printf '%s\n' "$*" >&2; }

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    say "FAIL  need shasum or sha256sum to check the jar"
    exit 1
  fi
}

# version_of CMD — prints MAJOR*1000000 + MINOR*1000 + PATCH from `CMD --version`,
# or 0 when CMD is missing. The same rule as the runner (scripts/statechart).
version_of() {
  command -v "$1" >/dev/null 2>&1 || { echo 0; return; }
  "$1" --version 2>/dev/null |
    sed -n '1s/[^0-9]*\([0-9]*\)\.\([0-9]*\)\.\([0-9]*\).*/\1 \2 \3/p' | {
      read -r major minor patch || true
      echo $((${major:-0} * 1000000 + ${minor:-0} * 1000 + ${patch:-0}))
    } || true
}

# ------------------------------------------------------------------ TLC jar

mkdir -p "$cache_dir"
if [[ -f $jar && $(sha256_of "$jar") == "$TLC_SHA256" ]]; then
  say "ok    tla2tools.jar v$TLC_VERSION already in $cache_dir"
else
  tmp=$(mktemp "$cache_dir/tla2tools.jar.XXXXXX")
  trap 'rm -f "$tmp"' EXIT
  say "...   downloading $TLC_URL"
  if ! curl -fsSL -o "$tmp" "$TLC_URL"; then
    say "FAIL  could not download tla2tools.jar"
    exit 1
  fi
  got=$(sha256_of "$tmp")
  if [[ $got != "$TLC_SHA256" ]]; then
    say "FAIL  tla2tools.jar sha256 is $got, expected $TLC_SHA256"
    exit 1
  fi
  mv "$tmp" "$jar"
  trap - EXIT
  say "ok    tla2tools.jar v$TLC_VERSION saved to $jar (sha256 checked)"
fi

# --------------------------------------------------------------------- Java

java=""
for candidate in "${JAVA:-}" /opt/homebrew/opt/openjdk/bin/java /usr/local/opt/openjdk/bin/java; do
  if [[ -n $candidate && -x $candidate ]]; then
    java=$candidate
    break
  fi
done
if [[ -z $java ]] && command -v java >/dev/null 2>&1; then
  java=$(command -v java)
fi

java_major=0
if [[ -n $java ]]; then
  # `java -version` prints e.g. `openjdk version "25.0.1"` or `"1.8.0_402"`.
  # The macOS /usr/bin/java stub fails here when no JDK is installed.
  if java_out=$("$java" -version 2>&1) &&
     [[ $java_out =~ version\ \"([0-9]+)(\.([0-9]+))? ]]; then
    java_major=${BASH_REMATCH[1]}
    [[ $java_major == 1 ]] && java_major=${BASH_REMATCH[3]:-0}
  fi
fi

if [[ $java_major -ge 11 ]]; then
  say "ok    Java $java_major at $java"
else
  if [[ -n $java ]]; then
    say "FAIL  $java is not a working Java 11 or later"
  else
    say "FAIL  no Java found"
  fi
  say "      Install Java 11 or later. On macOS: brew install openjdk"
  say "      (keg-only: JAVA=/opt/homebrew/opt/openjdk/bin/java)"
  failed=1
fi

# --------------------------------------------------- TypeScript runtime

node=$(version_of node)
if [[ $node -ge 23006000 ]] || { [[ $node -ge 22018000 ]] && [[ $node -lt 23000000 ]]; }; then
  say "ok    node $(node --version) runs the TypeScript"
elif [[ $(version_of bun) -ge 1001005 ]]; then
  say "ok    bun $(bun --version) runs the TypeScript"
elif [[ $(version_of deno) -ge 2000000 ]]; then
  say "ok    deno runs the TypeScript"
else
  say "FAIL  the runner needs Node 22.18 to 22.x, Node 23.6 or later, Bun 1.1.5 or later, or Deno 2.0 or later"
  failed=1
fi

# ------------------------------------------------------------------ exports

printf 'export TLA2TOOLS=%q\n' "$jar"
if [[ $java_major -ge 11 ]]; then
  printf 'export JAVA=%q\n' "$java"
else
  printf 'export JAVA=%q\n' /opt/homebrew/opt/openjdk/bin/java
fi

exit "$failed"
