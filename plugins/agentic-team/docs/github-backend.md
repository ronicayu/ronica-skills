# Taskgraph GitHub backend

What changes when Taskgraph keeps the plan on GitHub issues (`.taskgraph.toml` with `backend = "github"`): which meta keys and result kinds stay in this machine's cache, what is lost with the cache, and how issue comments get a summary.

## Meta keys and the local cache

Keep the run state of this machine in its cache, and send the keys that change often and that nobody needs live with
the next write: the `local` and `deferred` lists. The [reference](reference.md#meta-keys-on-the-taskgraph-github-backend)
lists every key with its class and gives the block to add to `.taskgraph.toml`.

`config.py check` prints a warning (and still exits 0) for each key of the
`local` and `deferred` rows that the project's entry lists in neither. Put the
block in place before `run.py` first writes on the GitHub backend: a value that
an issue already holds stays in its meta block when the key becomes `local`, and
tg shows that old value whenever the cache has none. To drop it, delete the key
from the issue's meta block on GitHub.

## When the local cache is lost

The `local` keys exist only in this machine's cache (by default
`~/.taskgraph/cache/github/<owner>/<repo>.db`). On a new machine, or after the
cache is deleted, tg reads each task from GitHub without them, and a `deferred`
value that was not sent yet is gone too. What `run.py` does then:

| Key | After the loss |
|-----|----------------|
| `sessions` | Rebuilt. The first command that acts on a task in progress with an attempt and no `sessions` (`record`, `launch`, `adopt`, `verify`, `close`, `stop`, `abandon`, `answer`, `steer`) rebuilds it from this machine's `claude agents` rows, under every `[profiles]` profile, and prints `sessions-restored`. A row counts when it is in the task's worktree folder, or when its session name is `task-<id>-<attempt>[-<keyword>]` or `verify-<id>-<attempt>[-<k>]` and its folder is this repository's root (where `claude stop` leaves a row) or that worktree. When no row is found, an attempt that has a worker result gets an empty list: nothing then depends on a session. An attempt with no result and no row is left as it is: `record` prints `sessions-lost` and the other commands refuse, because its worker may run on another machine and must not be filed DIED. The rebuilt entries do not have the role, tier and verify kind stored at launch, so `verify` uses the role the task names now. A session whose row was removed (`claude rm`) cannot be resumed. A merged task's rows are matched by name for its cleanup, with no write. |
| `session` | Rebuilt with `sessions`: the name of the current attempt's newest worker row. |
| `mailbox`, `mailbox_ids` | Lost. `run.py` cannot tell its own answer and steer rows from rows a worker filed `--by manager`, so it does not rebuild the lists, and no earlier answer or steer counts. An ask they answered reads as open again and `record` prints it as `asked`: answer it again. A steer the worker had not acked no longer shows in its inbox: steer again (`run.py inbox <id>` lists the rows). A later brief carries no answer or steer of an earlier attempt. |
| `cleanup_kept` | Lost; `record` prints each kept folder's `kept` line once more. |
| `host_rebase` | Lost. A request whose head the host rebased after a `close` reads as `pr-changed`, not `pr-rebased`; its next step names the `tg edit <id> --meta host_rebase=<pushed>` that lets `close` check and take the host's head. |

What you do:

1. Before you move to another machine or delete the cache: let the workers
   finish or `run.py stop` them, and run `tg sync` to send the deferred values.
2. After the loss, run `run.py record`. For each `sessions-lost` line: if the
   worker runs on another machine, finish it there; if it is gone,
   `tg edit <id> --meta sessions='[]'` and `run.py record`, which salvages its
   report from the worktree or files DIED.
3. Answer again the asks that `record` prints, and steer again what a worker
   had not acked.

The run folder `.agentic-team/` (the standing orders, the `notify-to` session,
the inbox files, the list of stopped sessions) and the worktrees are not in
Taskgraph either: they stay on the old machine. Copy the standing orders and run
`run.py notify-to` again on the new one.

## Result kinds on the Taskgraph GitHub backend

On the GitHub backend every result row is an issue comment, and GitHub's secondary rate limits on creating comments
(per minute and per hour) are shared by every session on one `gh` login: the Manager, each worker and each verifier.
The mailbox handshake adds rows fast (a steer and its ack for each message), so keep those kinds in this machine's
Taskgraph cache with Taskgraph 1.21.0 or later (#133). `check` (the dependency-check answer, 0.28.0) is there too: its body is the
subagent's long answer, and a retro on this machine reads it from the cache. `triage` rows are short and stay issue comments. The [reference](reference.md#meta-keys-on-the-taskgraph-github-backend) gives the `results` block to add next to the meta block.

Keep `revise` off this list. A `revise` row marks the start of a revision, and the `revision` meta (which is on the issue) counts them; a machine that has the meta but not the rows (a lost cache, or a second Manager machine) cannot tell the revision's rows from the old ones, so `run.py` refuses the task there (see [When the local cache is lost](#when-the-local-cache-is-lost)). The row carries a one-line summary, so it adds little noise. A row of a `local` kind is never posted; `tg result add` and `tg result ls` work as before, and the worker's
`mailbox.py`, which runs `tg` on the same machine, reads the same cache: tg finds the main checkout's
`.taskgraph.toml` (or the worktree's committed copy) and reads a relative `cache` path from the main checkout's folder,
so the default `~/.taskgraph/cache/...` path and a relative one are shared by every worktree; an absolute path must be
the same for all of them. `config.py check` prints a warning (and still
exits 0) for each of these kinds that the project's entry does not list. `ask` and `answer` stay on the issue by
default: they hold the worker's question and the Manager's decision, which a person or another machine may want to
read. A project may add them to `local` too; then a lost cache also loses the questions and the answers, and an answer
that came from a `decision` task stays in that task's notes.

## Issue comment summaries

On the GitHub backend an issue comment is the full machine body of a result row: for a worker `PASS` that is the `Status:`, `Head:` and `Ran:` fields and the command logs, often several thousand characters, and `run.py` needs all of it. With Taskgraph 1.22.0 or later, each report is also filed with a short summary that `tg result add --summary` puts above the full body. The comment shows the hidden meta line, the summary in Markdown, and the full report inside a collapsed `<details><summary>Full result</summary>` block. `tg result ls` still returns the exact body, and returns the summary as `summary`. A row with no summary is a comment as before.

The summary says what behaviour changed, and the author writes it:

- **Worker and verifier reports** have a required `Summary:` line (1-3 lines, plain words): what behaviour changed, as a user or developer would notice it, ideally `before -> now`; no statistics, no file lists. For `ISSUES` or `BLOCKED` it says what is wrong. A verifier's `Summary:` says whether the change is confirmed and, on `verify-failed`, the main problem. `check-report` (and `check-report --verifier`) refuses a report with no `Summary:` text. The text goes to `tg result add --summary` as written.
- **`[report] summary_lang`** (`en`, the default, or `zh`) only tells the worker and the verifier which language to write the `Summary:` line in; the brief says it in English (`Write the Summary: line in Chinese.`). `run.py` itself has no translated text.
- **Fallback.** A report with no `Summary:` (a salvaged report from `run.py record`, `DIED`, `STOPPED`) gets a short English text built from its fields, with no model: `✅ PASS · head c9c6c29 · 12 files changed · 21 commands ran` for a worker `PASS`, `⚠️ ISSUES · <first issue line>` for `ISSUES` or `BLOCKED`, `❌ verify-failed · 2 blocking findings` and the first two findings for a failed verdict (`N findings` when no line starts with `blocking:`), `⚠️ verify-blocked`, `✅ test-verified · head c9c6c29`.
- **`revise`** rows get `🔁 revision 2 from verify #41`. A long `ask` or `answer` (over 300 characters) gets `❓ <question>` or `💬 <first line>`. `ack`, `steer`, `check` and `STOPPED` rows have no summary.

The visible summary has `&`, `<` and `>` escaped, so a `<!--` in it cannot hide the rest of the comment; `tg result ls` returns the exact text. A summary has at most 2,000 characters. The summary reaches `tg result add` from `Run.add_result`, `mailbox.py report`, `mailbox.py ask` and `mailbox.py file-verify`. A report that you file by hand with `tg result add` has none, unless you pass `--summary`.

**Taskgraph version.** Every worker and verifier report passes `--summary`, so with a Taskgraph older than 1.22.0 each one fails with "unrecognized arguments". `config.py check` runs `tg result add --help` and fails, with the upgrade instruction, when it does not list `--summary`. Upgrade Taskgraph on every machine that runs the project, and upgrade Taskgraph before agentic-team.

A project on the GitHub backend that wants fewer comments, as in a project with many tasks, should put `ack`, `steer` and `check` in `results.local` (see above): those rows are the most frequent and nobody reads them on the issue.

When the cache is lost (see [When the local cache is lost](#when-the-local-cache-is-lost)), the local rows go with it:
the handshake history, which `run.py inbox` showed, and the evidence behind the `steer-seen` and `answer-seen` lines.
`record` still works, because every place that reads a steer or an ack starts from the ids in the `mailbox` and
`mailbox_ids` meta, which are local keys and are lost at the same time: with no listed steer, no steer waits for an
ack, so nothing holds a report, a salvage or a `DIED` row. What remains to do is what the table in
[When the local cache is lost](#when-the-local-cache-is-lost) already says: answer again the asks that `record` prints, and steer again what a worker had not acked.
Local ids start again at 1000000000000001 in a new cache, so a `steer #<id>` that an older report on the issue names
may match a new steer.

A project that still lists `revise` in `results.local` has one more loss. The `revision` meta stays on the issue and
the `revise` rows go, so a task in revision N has no `revise` row on the new machine, and the old `verify-failed` rows
would read as the current ones. `run.py` compares the two: every command that acts on a task in progress refuses it
with `is in revision N, but this machine has M revise row(s)`. Run `run.py` on the machine that ran `revise`, or finish
the task by hand, and take `revise` out of `results.local` so that new revisions are on the issue. A revision that
started before you did so stays refused on any other machine.
