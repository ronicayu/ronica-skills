# Setup: bot token and chat id

One-time work. Two values come out of it, and both end up in one file.

## 1. Create the bot (the user does this, in Telegram)

The token can only be issued inside the Telegram app, so this step is theirs, not yours:

1. Message [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, then a display name, then a username ending in `bot`.
3. BotFather replies with a token shaped like `123456789:AAH...`.

Ask them to put it straight into the credentials file below — **not** into the chat with you. If they
paste it to you anyway, tell them plainly to revoke it with `/revoke` in BotFather and issue a new one;
a token in a transcript should be treated as public.

## 2. Store the credentials in a file

`~/.config/telegram-send/credentials`, mode 600:

```text
TELEGRAM_BOT_TOKEN=123456789:AAH...
TELEGRAM_CHAT_ID=987654321
```

Create it with the permissions already right, so the token is never briefly world-readable:

```sh
mkdir -p ~/.config/telegram-send
install -m 600 /dev/null ~/.config/telegram-send/credentials
$EDITOR ~/.config/telegram-send/credentials
```

**Have the user type or paste the token into the editor, not into a shell command.** A command line
puts the token into shell history and into `ps`; an editor puts it only in the file. The script refuses
a credential file readable beyond its owner and prints the `chmod` to fix it, so a mode mistake fails
loudly instead of quietly leaving a credential exposed.

The parser tolerates comments, blank lines, a leading `export`, spaces around `=`, and quoted values,
so a line copied out of a shell profile works unchanged. It is parsed, never sourced — this file cannot
execute anything.

Alternative locations, in the order the script looks: `--config PATH`, `$TELEGRAM_SEND_CONFIG`,
`$XDG_CONFIG_HOME/telegram-send/credentials`, `~/.telegram-send`. An exported `TELEGRAM_BOT_TOKEN` or
`TELEGRAM_CHAT_ID` overrides the file, which is handy for a one-off send to a different chat.

Do not write credentials into the repository, a `.claude/settings.json`, or a skill file. If the project
keeps secrets somewhere specific, point `--config` at that instead.

Write the token in now; the chat id comes next and gets appended to the same file.

## 3. Find the chat id

A bot can only message a chat that has contacted it or added it. There is no lookup by phone number,
and none by @username for private chats. With the token in place, the script does the lookup — nothing
needs pasting or interpolating:

```bash
scripts/telegram-send.sh --chat-ids
```

```text
-1001234567890  supergroup  Platform alerts
987654321       private     Rong Yu
```

**For a person (usually the user themselves):** they send any message to the new bot first, then run
the command above. Their chat id is the `private` row.

**For a group:** add the bot to the group, send a message there, run it again. Group ids are negative;
supergroups start `-100`. If nothing appears, privacy mode is hiding ordinary messages from the bot —
either address it as `@yourbot hello`, or turn privacy off with BotFather's `/setprivacy`.

**For a channel:** add the bot as an admin with post rights. Use `@channelusername` as the chat id for
a public channel, or the numeric `-100...` id from a forwarded post for a private one.

Nothing listed at all means either no message has been sent to the bot yet, or a webhook is registered
— a webhook and `getUpdates` are mutually exclusive. `getWebhookInfo` will show one, and it has to be
removed with `deleteWebhook` before `getUpdates` returns anything.

Put the chosen id in the credentials file as `TELEGRAM_CHAT_ID`.

## 4. Verify end to end

```bash
scripts/telegram-send.sh 'Setup check — this bot can reach you.'
```

`sent to <chat> (message_id N)` plus a message arriving means done.

To separate a token problem from a chat problem, run `--chat-ids` again: it uses the token and no chat
id, so `Unauthorized` there points at the token, while a clean listing plus a failing send points at
the chat id or at the bot's membership of that chat.

Both need `dangerouslyDisableSandbox: true` when the sandbox is on — `api.telegram.org` is outside the
default network allowlist, and the sandbox also blocks the script's `mktemp`.
