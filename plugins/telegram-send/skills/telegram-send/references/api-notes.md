# Bot API notes

Background for extending `scripts/telegram-send.sh` or diagnosing something it does not handle. For
ordinary sending, use the script — it already does all of this.

## The raw call

```bash
printf 'url = https://api.telegram.org/bot%s/sendMessage\n' "$token" |
  curl -sS --config - --request POST \
    --data-urlencode "chat_id=${chat}" \
    --data-urlencode 'text=Tests pass — 214/214.'
```

`$token` and `$chat` come from the credentials file the script parses; they are shell variables inside
the script, not exported environment variables.

Three details that are easy to get wrong:

- **The token goes in the config file on stdin, not on the command line.** It sits in the URL *path*,
  so an interpolated URL puts a live credential in argv, readable through `ps` by any local process
  for the life of the request. Unquoted config values run to end of line, which avoids curl's
  backslash-escaping rules; the token contains no spaces, so it needs no quoting.
- **Message text belongs in `--data-urlencode`, as an argument.** It is not a credential, and keeping
  it out of the config file sidesteps the escaping rules that quoted config values impose. Never
  string-interpolate text into a query string: newlines, `&`, and `#` all mangle, truncating silently
  at the `#`.
- **`curl` exits 0 on an HTTP 403.** Success is `"ok":true` in the body, nothing else.

## Errors

| Response | What it means |
| --- | --- |
| `401 Unauthorized` | Token is wrong, revoked, or has stray whitespace. Not a chat problem. |
| `400 chat not found` | Wrong chat id, or the user has never messaged the bot. A bot cannot open a conversation first. |
| `403 bot was blocked by the user` | They blocked it. Nothing to retry. |
| `403 bot is not a member of the ... chat` | Add the bot to the group, or as an admin for a channel. |
| `400 message is too long` | Over 4096 characters. |
| `400 can't parse entities` | Bad HTML markup, usually an unsupported tag or an unescaped `<`. |
| `429` + `parameters.retry_after` | Rate limited. Sleep that many seconds; do not hammer. |

## Parameters the script exposes

`chat_id`, `text`, `parse_mode`, `disable_notification`, `message_thread_id`,
`link_preview_options`. It also calls `getUpdates` for `--chat-ids` and `--wait`.

## Reading replies with getUpdates

`--wait` polls `getUpdates` with three parameters: `offset` (the first update id you have not
acknowledged), `timeout` (server-side long poll, capped at 50 seconds), and
`allowed_updates=["message"]`.

The offset is the part that bites:

- Requesting an offset **acknowledges every update below it**. Advance it past everything you have
  seen, matching or not, or the same updates come back forever and the loop never progresses.
- The script takes its baseline *before* sending, with `offset=-1` — which returns only the most recent
  update — and then polls from `last + 1`. Messages are additionally filtered on `date` against the
  send time, which covers the case of a bot with no history at all, where there is no id to skip past.
- Updates Telegram cannot deliver are dropped after 24 hours.

Two ways it fails, both `409`:

- `terminated by other getUpdates request` — something else is polling the same bot. Telegram permits
  exactly one consumer, so a second `--wait`, or an unrelated bot process, breaks both.
- a registered webhook disables `getUpdates` entirely. `getWebhookInfo` shows it; `deleteWebhook`
  clears it.

A bot does not receive its own messages, so the sent message never comes back as a reply. Note that
`edited_message` is a separate update type and is not matched — an edit to an earlier message does not
count as a reply.

## Parameters it does not

Worth knowing if you extend it:

- `reply_parameters={"message_id":N}` — reply to a specific message, threading the conversation.
- `protect_content=true` — blocks forwarding and saving.
- `entities` — explicit formatting offsets instead of `parse_mode`. Note the offsets are UTF-16 code
  units, so anything outside the BMP (most emoji) counts as 2.
- Other methods on the same endpoint pattern: `sendPhoto`, `sendDocument`, `editMessageText`,
  `deleteMessage`. All take the same `bot<token>/<method>` shape.

The 4096-character limit is on characters after entity parsing. The script's pre-flight count uses
`wc -m`, which counts bytes rather than characters under `LC_ALL=C`, so a heavily non-ASCII message can
be refused slightly early; the API's own rejection is the backstop.

Full reference: <https://core.telegram.org/bots/api#sendmessage>
