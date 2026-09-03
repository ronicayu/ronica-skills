---
name: telegram-send
description: Send a Telegram message from the terminal — notifications, status updates, and completion summaries that reach a phone — through a bundled script that keeps the bot token out of argv and out of the transcript. Use when the user asks to send, post, or push a message to Telegram, to be notified or pinged on Telegram, or to be told there when something finishes — "telegram me when the build passes", "send that to my Telegram", "ping the team channel", "notify me on Telegram when done". Also use when a long-running or background job finishes and the user has asked to hear about it on Telegram, and when reporting a blocker they need to see away from the terminal. Covers bot setup, finding a chat id, HTML formatting, the 4096-character limit, and what the API's error responses actually mean.
---

# Send a Telegram Message

Use the bundled script. It is the whole interface:

```bash
scripts/telegram-send.sh 'Tests pass — 214/214, 38s. Pushed to main as a1b3f9c.'
```

Success prints `sent to <chat> (message_id N)` and exits 0. Any failure exits non-zero with the API's
own reason, so **you do not need to inspect the response** — check the exit status and report it.

`scripts/` is relative to this skill's directory, not to the working directory. Resolve it against
wherever this SKILL.md was loaded from — as an installed Claude Code plugin that is
`${CLAUDE_PLUGIN_ROOT}/skills/telegram-send/scripts/telegram-send.sh`. Do not assume the shell's cwd.

## Never handle the token yourself

Credentials live in a file, `~/.config/telegram-send/credentials` at mode 600:

```text
TELEGRAM_BOT_TOKEN=123456789:AAH...
TELEGRAM_CHAT_ID=987654321
```

The script reads it, refuses it if it is readable beyond its owner, and hands the token to curl through
a stdin config file so it never reaches the command line — where `ps` exposes it to any local process.
Its own output is redacted before printing. The file is parsed, never sourced: a credential store
should not be able to execute anything.

That protection is only worth something if you leave the token alone:

- **Never `cat`, `grep`, or `echo` the credentials file, and never run `env | grep TELEGRAM`** to debug
  a failure. That copies the credential into the transcript, which is the leak this design exists to
  prevent. The script's errors already distinguish a token problem from a chat problem, and
  `--chat-ids` tests the token without touching a chat id.
- **Never** interpolate the token into a URL, a `curl` command, or a commit.
- **Never** write credentials into the repo, `.claude/settings.json`, or a skill file. To use a
  different store, point `--config PATH` at it.
- If a token does reach the transcript, say so and tell the user to revoke it with `/revoke` in
  @BotFather. Treat it as public from that moment.

If the file is missing the script says so and exits 2. Read `references/setup.md` then — it covers
creating the bot, writing the file, and finding the chat id with `--chat-ids`. Never guess a chat id;
there is no way to derive one.

**Calls need `dangerouslyDisableSandbox: true`** when the sandbox is on. `api.telegram.org` is not in
the default network allowlist, and the sandbox also blocks the script's `mktemp`, so a sandboxed run
fails on a permissions error that looks nothing like an auth problem. Mention `/sandbox` if the user
wants to manage that.

## Options

| Flag | Effect |
| --- | --- |
| `--chat ID` | Send somewhere other than the configured chat — another person, a group, a channel. |
| `--config PATH` | Read credentials from somewhere other than the default locations. |
| `--chat-ids` | List the chat ids the bot can see. First-time setup, and a token check. |
| `--html` | Text carries Telegram HTML markup (see below). |
| `--silent` | Delivers with no push notification. Right for a routine FYI at 2am. |
| `--no-preview` | Suppresses the link card, which otherwise dominates a short message. |
| `--thread ID` | Posts into a forum topic in a supergroup. |
| `--dry-run` | Prints what would be sent and sends nothing. Use it to check wording. |
| `-` | Reads the message from stdin instead of an argument. |

The script also guards the 4096-character limit before spending a request, and retries once on a
`429` when Telegram supplies a short `retry_after`.

## Formatting

Plain text is the default and usually right. With `--html` a small tag set applies —
`<b> <i> <u> <s> <code> <pre> <a href> <blockquote> <tg-spoiler>` and nothing else. An unknown tag
rejects the whole message with `can't parse entities`; on that error resend as plain text rather than
debugging markup.

```bash
scripts/telegram-send.sh --html --no-preview '<b>Deploy failed</b> — staging, step <code>migrate</code>.
<a href="https://ci.example.com/42">Build 42</a>'
```

In HTML mode you must escape `&`, `<`, and `>` in anything you did not write as markup. Log lines,
diffs, and error output are where this bites — send those as plain text.

## Write the first line as the whole message

A push notification shows the opening line and little else, and that is often all it gets read.

- **Lead with the outcome, not the activity.** `Tests pass — 214/214` beats `Finished running tests`.
  `Blocked — needs your VPN login` beats `Update on the deploy`.
- Keep it to a few lines: what happened, where it lives (path, branch, PR, URL), and the next command
  if one is needed. Detail stays in the terminal.
- Never dump a log or a file into a message — the API rejects over 4096 characters rather than
  truncating. Send the verdict and a pointer to the detail.
- No credentials, tokens, customer data, or contents of confidential documents. This leaves the
  machine and lands in a chat history you do not control.

## When to send, when not

Send when the user asked to be notified, when a background job they walked away from finishes (once,
at the end), when you are blocked and need them, or when something surfaced they would want before
reading the transcript.

Do not send progress updates mid-task, one message per step, or a notification for work the user is
watching live in the terminal.

After sending, say in the transcript that you sent it and what the first line was, so the terminal
record matches what landed on their phone.

## References

- `references/setup.md` — create the bot, find a chat id for a person, group, or channel, and store
  the credentials. Read it once, when the environment variables are missing.
- `references/api-notes.md` — the raw `sendMessage` call and its error codes. Read it only when
  extending the script or diagnosing something it does not cover.
