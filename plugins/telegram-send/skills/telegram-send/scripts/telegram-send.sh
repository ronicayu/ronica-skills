#!/usr/bin/env bash
#
# Send a Telegram message through the Bot API.
#
# Credentials live in a file, not in the environment or the command line:
#
#   ~/.config/telegram-send/credentials      (mode 600)
#     TELEGRAM_BOT_TOKEN=123456789:AAH...
#     TELEGRAM_CHAT_ID=987654321
#
# The file is parsed, never sourced — a sourced file is executable code, and a
# credential store should not be able to run commands. Only the two keys above
# are read. The token is then handed to curl through a config file on stdin, so
# it never reaches argv, where `ps` would expose it to any local process, and
# this script's own output is redacted on the way out.
#
# Usage:
#   telegram-send.sh [options] 'message text'
#   telegram-send.sh [options] -              # read text from stdin
#   telegram-send.sh --chat-ids               # list chat ids the bot can see
#
# Options:
#   --config PATH   read credentials from PATH instead of the default locations
#   --chat ID       send to this chat instead of the configured one
#   --html          text contains Telegram HTML markup; send with parse_mode=HTML
#   --silent        deliver with no push notification
#   --thread ID     post into a forum topic (message_thread_id)
#   --no-preview    suppress the link preview card
#   --dry-run       report what would be sent; send nothing
#   --chat-ids      print the chat ids visible to the bot, for first-time setup
#
# Credential search order — the first file found wins, and TELEGRAM_BOT_TOKEN or
# TELEGRAM_CHAT_ID already exported override it, so a one-off send can be pointed
# elsewhere without editing anything:
#
#   --config PATH
#   $TELEGRAM_SEND_CONFIG
#   ${XDG_CONFIG_HOME:-~/.config}/telegram-send/credentials
#   ~/.telegram-send
#
# Exit: 0 sent, 1 API or network failure, 2 usage or configuration problem.

set -uo pipefail

readonly max_chars=4096
readonly api=https://api.telegram.org

token=${TELEGRAM_BOT_TOKEN:-}
chat=${TELEGRAM_CHAT_ID:-}
config=
text=
parse_mode=
silent=false
thread=
preview=true
dry_run=false
list_chats=false

die() {
  printf 'telegram-send: %s\n' "$1" >&2
  exit "${2:-2}"
}

usage() {
  # Prints the header comment above, so there is one copy of the documentation.
  awk 'NR > 1 && /^#/ { sub(/^#[[:space:]]?/, ""); print; next } NR > 1 { exit }' "$0"
}

# Scrubs the token from anything on its way to a terminal or a transcript. Bot
# tokens are [0-9]+:[A-Za-z0-9_-]+, so | is a safe sed delimiter.
redact() {
  if [[ -n $token ]]; then
    sed "s|${token}|<token redacted>|g"
  else
    cat
  fi
}

# Reads a field out of the response body. $tmp is set before any call.
json() {
  if command -v jq >/dev/null 2>&1; then
    jq -r "$1 // empty" "$tmp/body" 2>/dev/null
  fi
}

trim() {
  local s=$1
  s=${s#"${s%%[![:space:]]*}"}
  s=${s%"${s##*[![:space:]]}"}
  printf '%s' "$s"
}

# ------------------------------------------------------------------ arguments

while [[ $# -gt 0 ]]; do
  case $1 in
    --config)     config=${2:-}; [[ -n $config ]] || die '--config needs a path'; shift 2 ;;
    --chat)       chat=${2:-}; [[ -n $chat ]] || die '--chat needs a chat id'; shift 2 ;;
    --thread)     thread=${2:-}; [[ -n $thread ]] || die '--thread needs an id'; shift 2 ;;
    --html)       parse_mode=HTML; shift ;;
    --silent)     silent=true; shift ;;
    --no-preview) preview=false; shift ;;
    --dry-run)    dry_run=true; shift ;;
    --chat-ids)   list_chats=true; shift ;;
    -h|--help)    usage; exit 0 ;;
    --)           shift; break ;;
    -)            text=$(cat); shift ;;
    -*)           die "unknown option: $1" ;;
    *)            [[ -z $text ]] || die 'more than one message given; quote the text as one argument'
                  text=$1; shift ;;
  esac
done

# A trailing positional after --, e.g. telegram-send.sh --html -- '<b>hi</b>'
if [[ -z $text && $# -gt 0 ]]; then
  text=$1
fi

# ---------------------------------------------------------------- credentials

# Parses KEY=value lines. Deliberately not `source`: this file holds a
# credential and must not be able to execute anything. Blank lines, comments,
# a leading `export`, and surrounding quotes are all tolerated so a line copied
# out of a shell profile works unchanged.
read_credentials() {
  local file=$1 line key value mode

  mode=$(stat -f '%Lp' "$file" 2>/dev/null || stat -c '%a' "$file" 2>/dev/null)
  if [[ -n $mode && $mode != 600 && $mode != 400 ]]; then
    die "$file is mode $mode, readable beyond its owner — run: chmod 600 $file"
  fi

  while IFS= read -r line || [[ -n $line ]]; do
    line=$(trim "$line")
    [[ -z $line || ${line:0:1} == '#' ]] && continue
    line=${line#export }
    [[ $line == *=* ]] || continue

    key=$(trim "${line%%=*}")
    value=$(trim "${line#*=}")

    # Strip one matching pair of surrounding quotes.
    if [[ ${#value} -ge 2 ]]; then
      case ${value:0:1}${value: -1} in
        '""' | "''") value=${value:1:${#value}-2} ;;
      esac
    fi

    case $key in
      TELEGRAM_BOT_TOKEN) [[ -z $token ]] && token=$value ;;
      TELEGRAM_CHAT_ID)   [[ -z $chat ]] && chat=$value ;;
      *) printf 'telegram-send: ignoring unknown key %s in %s\n' "$key" "$file" >&2 ;;
    esac
  done <"$file"
}

if [[ -n $config ]]; then
  [[ -f $config ]] || die "no credential file at $config"
  read_credentials "$config"
else
  for candidate in \
    "${TELEGRAM_SEND_CONFIG:-}" \
    "${XDG_CONFIG_HOME:-$HOME/.config}/telegram-send/credentials" \
    "$HOME/.telegram-send"; do
    if [[ -n $candidate && -f $candidate ]]; then
      config=$candidate
      read_credentials "$candidate"
      break
    fi
  done
fi

# ----------------------------------------------------------------- validation

if [[ -z $token ]]; then
  die "no bot token: put TELEGRAM_BOT_TOKEN in ${XDG_CONFIG_HOME:-$HOME/.config}/telegram-send/credentials (mode 600) — see references/setup.md"
fi

# ------------------------------------------------------------- --chat-ids

# First-time setup: report the chats the bot can see, so a chat id never has to
# be dug out by hand. Only chats that have messaged the bot appear.
if $list_chats; then
  tmp=$(mktemp -d) || die 'cannot create a temp directory'
  trap 'rm -rf "$tmp"' EXIT

  printf 'url = %s/bot%s/getUpdates\n' "$api" "$token" |
    curl --silent --show-error --config - --output "$tmp/body" 2>"$tmp/err" || {
      printf 'telegram-send: getUpdates failed\n' >&2
      redact <"$tmp/err" >&2
      exit 1
    }

  if ! command -v jq >/dev/null 2>&1; then
    printf 'telegram-send: jq is not installed; raw response follows\n' >&2
    redact <"$tmp/body"
    exit 0
  fi

  if [[ $(json '.ok') != true ]]; then
    printf 'telegram-send: getUpdates rejected: %s\n' "$(json '.description')" >&2
    exit 1
  fi

  count=$(jq '[.result[] | (.message // .channel_post) | select(. != null)] | length' "$tmp/body")
  if [[ $count -eq 0 ]]; then
    printf 'no chats visible yet. Either nobody has messaged the bot, or a webhook is\n' >&2
    printf 'registered — getUpdates and a webhook are mutually exclusive. Check with getWebhookInfo.\n' >&2
    exit 1
  fi

  jq -r '[.result[] | (.message // .channel_post) | select(. != null) | .chat
         | "\(.id)\t\(.type)\t\(.title // .username // ([.first_name, .last_name] | map(select(.)) | join(" ")))"]
         | unique | .[]' "$tmp/body"
  exit 0
fi

[[ -n $text ]] || die 'no message text (pass it as an argument, or - to read stdin)'

if [[ -z $chat ]]; then
  die "no chat id: add TELEGRAM_CHAT_ID to ${config:-${XDG_CONFIG_HOME:-$HOME/.config}/telegram-send/credentials}, or pass --chat"
fi

# Approximate: wc -m counts characters in a UTF-8 locale and bytes under LC_ALL=C,
# so a non-ASCII message can be refused slightly early. The API's own
# "message is too long" is the backstop and is reported verbatim below.
chars=$(printf '%s' "$text" | wc -m | tr -d '[:space:]')
if [[ $chars -gt $max_chars ]]; then
  die "message is $chars characters, over Telegram's $max_chars limit — send the outcome and a pointer to the detail, not the whole log"
fi

# ------------------------------------------------------------------- assemble

curl_args=(--silent --show-error --request POST)
curl_args+=(--data-urlencode "chat_id=${chat}")
curl_args+=(--data-urlencode "text=${text}")
[[ -n $parse_mode ]] && curl_args+=(--data-urlencode "parse_mode=${parse_mode}")
[[ -n $thread ]] && curl_args+=(--data-urlencode "message_thread_id=${thread}")
$silent && curl_args+=(--data-urlencode 'disable_notification=true')
$preview || curl_args+=(--data-urlencode 'link_preview_options={"is_disabled":true}')

if $dry_run; then
  printf 'dry run — nothing sent\n  credentials: %s\n  chat_id:     %s\n  parse_mode:  %s\n  chars:       %s\n' \
    "${config:-environment}" "$chat" "${parse_mode:-none (plain text)}" "$chars"
  $silent && printf '  silent:      no push notification\n'
  $preview || printf '  preview:     link card suppressed\n'
  [[ -n $thread ]] && printf '  thread:      %s\n' "$thread"
  printf '\n%s\n' "$text"
  exit 0
fi

tmp=$(mktemp -d) || die 'cannot create a temp directory'
trap 'rm -rf "$tmp"' EXIT

# ----------------------------------------------------------------------- send

# The URL is the only secret-bearing argument, so it is the only thing in the
# config file. Unquoted config values run to end of line, which sidesteps
# curl's backslash-escaping rules; the token contains no spaces.
send() {
  printf 'url = %s/bot%s/sendMessage\n' "$api" "$token" |
    curl "${curl_args[@]}" --config - \
      --output "$tmp/body" --write-out '%{http_code}' 2>"$tmp/err"
}

attempt=1
while :; do
  http=$(send)
  curl_status=$?

  if [[ $curl_status -ne 0 ]]; then
    printf 'telegram-send: curl failed (exit %d)\n' "$curl_status" >&2
    redact <"$tmp/err" >&2
    [[ $curl_status -eq 6 || $curl_status -eq 7 ]] &&
      printf 'telegram-send: if a sandbox is active, api.telegram.org needs to be reachable\n' >&2
    exit 1
  fi

  # Rate limited: honour one bounded retry, then stop rather than hammer.
  retry_after=$(json '.parameters.retry_after')
  if [[ $http == 429 && $attempt -eq 1 && -n $retry_after && $retry_after -le 30 ]]; then
    printf 'telegram-send: rate limited, retrying in %ss\n' "$retry_after" >&2
    sleep "$retry_after"
    attempt=2
    continue
  fi
  break
done

if command -v jq >/dev/null 2>&1; then
  ok=$(json '.ok')
else
  ok=false
  grep -q '"ok":[[:space:]]*true' "$tmp/body" && ok=true
fi

if [[ $ok != true ]]; then
  description=$(json '.description')
  printf 'telegram-send: send failed (HTTP %s)\n' "$http" >&2
  if [[ -n $description ]]; then
    printf '  %s\n' "$description" >&2
  else
    redact <"$tmp/body" >&2
    printf '\n' >&2
  fi
  case $http in
    401) printf '  the token is wrong or revoked — this is not a chat problem\n' >&2 ;;
    400) printf '  check the chat id, and that the recipient has messaged the bot at least once\n' >&2 ;;
    403) printf '  the bot is blocked, or is not a member of that group or channel\n' >&2 ;;
  esac
  exit 1
fi

message_id=$(json '.result.message_id')
printf 'sent to %s%s\n' "$chat" "${message_id:+ (message_id ${message_id})}"
