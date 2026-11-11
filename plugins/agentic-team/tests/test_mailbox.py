"""Tests for scripts/mailbox.py, the worker's side of the mailbox. Run: "$PY" plugins/agentic-team/tests/run_parallel.py (all tests, in parallel)

Each test builds a temporary Taskgraph database with the real tg.py and a context file as run.py writes it. Nothing
here reaches a real session or socket.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.dirname(os.path.dirname(HERE))
MAILBOX = os.path.join(os.path.dirname(HERE), "scripts", "mailbox.py")
TG = os.path.join(PLUGINS, "taskgraph", "skills", "taskgraph", "scripts", "tg.py")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import mailbox  # noqa: E402


class MailboxTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.realpath(self._tmp.name)
        self.inbox = os.path.join(self.dir, "inbox")
        self.db = os.path.join(self.dir, "tasks.db")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "TASKGRAPH_"))}
        self.env["HOME"] = self.dir
        self.task = self.tg("add", "Sweep", "--notes", "Why: x", "--meta", 'scope="src/"')["id"]
        self.tg("start", str(self.task))
        self.ctx_path = os.path.join(self.dir, "ctx.json")
        self.write_ctx()

    def tearDown(self):
        self._tmp.cleanup()

    # --- helpers

    def tg(self, *args, stdin=None):
        out = subprocess.run([sys.executable, TG, "--db", self.db, "--project", "demo", "--json", *args], input=stdin,
                             capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def write_ctx(self, **change):
        ctx = {"python": sys.executable, "tg": TG, "db": self.db, "project": "demo", "task": self.task, "attempt": 1,
               "by": "task-1-1", "asks_cap": 3, "scope": "src/", "inbox_dir": self.inbox,
               "lock": os.path.join(self.dir, "locks", "task-1.lock")}
        ctx.update(change)
        with open(self.ctx_path, "w") as fh:
            json.dump(ctx, fh)

    def mb(self, *args, stdin=None, env=None):
        return subprocess.run([sys.executable, MAILBOX, "--ctx", self.ctx_path, *args], input=stdin, capture_output=True,
                              text=True, env=env or self.env)

    def question(self, name="q.md", text="Question: Which endpoint?\nOptions: v1, v2\nDefault: v2\nBlocking: yes\nWhy: both exist\n"):
        path = os.path.join(self.dir, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def rows(self, kind=None):
        return [r for r in self.tg("result", "ls", str(self.task)) if kind is None or r["kind"] == kind]

    def message(self, kind, body, attempt=1, by="manager", status="SENT", listed=True):
        """A row as run.py files it, with its id in the `mailbox` meta unless `listed` is false."""
        row = self.tg("result", "add", str(self.task), "--kind", kind, "--attempt", str(attempt), "--by", by,
                      "--status", status, "--body-file", "-", stdin=body)
        if listed:
            table = self.tg("show", str(self.task))["meta"].get("mailbox") or {}
            table[str(row["id"])] = {"kind": kind, "attempt": attempt, "via": "pending"}
            self.tg("edit", str(self.task), "--meta", "mailbox=" + json.dumps(table))
        return row["id"]

    # --- T1: ask

    def test_t1_ask_files_an_open_row_for_this_task_attempt_and_author(self):
        out = self.mb("ask", "--file", self.question())
        self.assertEqual(out.returncode, 0, out.stderr)
        (row,) = self.rows("ask")
        self.assertEqual((row["task_id"], row["attempt"], row["author"], row["status"]),
                         (self.task, 1, "task-1-1", "OPEN"))
        self.assertIn("Question: Which endpoint?", row["body"])
        self.assertIn(f"ask #{row['id']} filed (1 of 3 asks this attempt)", out.stdout)
        self.assertIn(f"End your turn now with one line: Waiting for answer to ask #{row['id']}", out.stdout)

    def test_t1_a_non_blocking_ask_goes_on_with_its_default(self):
        out = self.mb("ask", "--file", self.question(text="Question: q\nDefault: d\nBlocking: no\n"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("go on with your Default", out.stdout)
        self.assertNotIn("End your turn", out.stdout)

    def test_t1_a_missing_default_or_question_or_a_bad_blocking_value_is_refused(self):
        for text, why in (("Question: q\nBlocking: yes\n", "no `Default:` line"),
                          ("Default: d\n", "no `Question:` line"),
                          ("Question: q\nDefault:   \n", "no `Default:` line"),
                          ("Question: q\nDefault: d\nBlocking: maybe\n", "`Blocking:` must be yes or no")):
            with self.subTest(text):
                out = self.mb("ask", "--file", self.question(text=text))
                self.assertEqual(out.returncode, 2)
                self.assertIn(why, out.stderr)
        self.assertEqual(self.rows("ask"), [])
        self.assertEqual(self.mb("ask", "--file", os.path.join(self.dir, "missing.md")).returncode, 2)

    def test_t1_the_cap_counts_the_asks_of_this_attempt_only(self):
        self.write_ctx(asks_cap=2)
        for _ in range(2):
            self.assertEqual(self.mb("ask", "--file", self.question()).returncode, 0)
        out = self.mb("ask", "--file", self.question())
        self.assertEqual(out.returncode, 2)
        self.assertIn("you have filed 2 of 2 asks this attempt", out.stderr)
        self.assertEqual(len(self.rows("ask")), 2)
        self.write_ctx(asks_cap=2, attempt=2, by="task-1-2")  # the next attempt starts again
        self.assertEqual(self.mb("ask", "--file", self.question()).returncode, 0)

    def test_t1_a_cap_of_zero_refuses_every_ask(self):
        self.write_ctx(asks_cap=0)
        out = self.mb("ask", "--file", self.question())
        self.assertEqual(out.returncode, 2)
        self.assertIn("allows no asks", out.stderr)
        self.assertEqual(self.rows("ask"), [])

    def test_t2_ask_posts_to_no_socket_itself(self):
        """The Manager's doorbell is the worker's SendMessage step in the brief (run.py's tests cover its `to`); the
        script never connects to a socket, even with an address file and the notify-to switch in its folder."""
        with open(os.path.join(self.dir, "manager.addr"), "w") as fh:
            json.dump({"socket": os.path.join(self.dir, "none.sock")}, fh)
        with open(os.path.join(self.dir, "notify-to"), "w") as fh:
            fh.write("manager-7\n")
        out = self.mb("ask", "--file", self.question())
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("doorbell", out.stdout)
        self.assertEqual(len(self.rows("ask")), 1)

    # --- T8d: checkin

    def test_t8d_checkin_writes_the_session_id_and_the_socket_from_the_environment(self):
        env = dict(self.env, CLAUDE_CODE_MESSAGING_SOCKET="/tmp/cc-socks/none.sock", CLAUDE_CODE_MESSAGING_TOKEN="tok")
        before = time.time()
        out = self.mb("checkin", stdin=json.dumps({"session_id": "uuid-1", "source": "startup"}), env=env)
        self.assertEqual((out.returncode, out.stdout), (0, ""), out.stderr)
        path = os.path.join(self.inbox, f"{self.task}-1.addr")
        with open(path) as fh:
            addr = json.load(fh)
        self.assertEqual({k: addr[k] for k in ("socket", "session_id", "token")},
                         {"socket": "/tmp/cc-socks/none.sock", "session_id": "uuid-1", "token": "tok"})
        self.assertGreaterEqual(addr["at"], before)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        # a resume checks in again with a new process, a new socket and the same session id
        env["CLAUDE_CODE_MESSAGING_SOCKET"] = "/tmp/cc-socks/two.sock"
        self.mb("checkin", stdin=json.dumps({"session_id": "uuid-1", "source": "resume"}), env=env)
        with open(path) as fh:
            self.assertEqual(json.load(fh)["socket"], "/tmp/cc-socks/two.sock")

    def test_t8d_checkin_without_a_socket_or_a_session_id_writes_nothing_and_still_exits_0(self):
        out = self.mb("checkin", stdin=json.dumps({"session_id": "uuid-1"}))
        self.assertEqual(out.returncode, 0)
        self.assertIn("nothing written", out.stderr)
        env = dict(self.env, CLAUDE_CODE_MESSAGING_SOCKET="/tmp/cc-socks/none.sock")
        for stdin in ("", "not json", "{}"):
            self.assertEqual(self.mb("checkin", stdin=stdin, env=env).returncode, 0)
        self.assertFalse(os.path.exists(self.inbox))

    # --- T11: the hook

    def hook(self, flag):
        return subprocess.run([sys.executable, "-S", MAILBOX, "hook", "--flag", flag], capture_output=True, text=True,
                              env=self.env)

    def test_t11_hook_prints_additional_context_only_while_the_flag_exists(self):
        flag = os.path.join(self.inbox, f"task-{self.task}.flag")
        out = self.hook(flag)
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "", ""))
        os.makedirs(self.inbox)
        pointer = "agentic-team: task 1 attempt 1 has message #9 (steer). Run: inbox"
        with open(flag, "w") as fh:
            fh.write(pointer + "\n")
        out = self.hook(flag)
        self.assertEqual(out.returncode, 0)
        self.assertEqual(json.loads(out.stdout), {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                                          "additionalContext": pointer}})
        os.remove(flag)
        self.assertEqual(self.hook(flag).stdout, "")
        self.assertEqual(subprocess.run([sys.executable, "-S", MAILBOX, "hook"], capture_output=True, text=True).returncode, 0)

    def test_t11_hook_runs_in_under_50_ms(self):
        flag = os.path.join(self.dir, "flag")
        with open(flag, "w") as fh:
            fh.write("pointer\n")
        best = min(self.timed(flag) for _ in range(5))  # the best of five: a loaded machine slows single runs
        self.assertLess(best, 0.05, f"{best * 1000:.0f} ms")

    def timed(self, flag):
        start = time.perf_counter()
        subprocess.run([sys.executable, "-S", MAILBOX, "hook", "--flag", flag], capture_output=True, env=self.env)
        return time.perf_counter() - start

    # --- inbox and ack

    def test_inbox_prints_the_open_messages_of_this_attempt_and_ack_closes_them(self):
        ask = self.message("ask", "Question: q\nDefault: d\n", by="task-1-1", status="OPEN", listed=False)
        answer = self.message("answer", f"Re: #{ask}\nAnswer: use v2\nSource: manager\n", status="ANSWERED")
        steer = self.message("steer", "Steer: skip the docs\nKind: redirect\n", by="operator")
        out = self.mb("inbox")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"#{answer} answer by manager, to your ask #{ask}:", out.stdout)
        self.assertIn("    Answer: use v2", out.stdout)
        self.assertIn(f"#{steer} steer by operator:", out.stdout)
        self.assertIn("2 messages for task", out.stdout)
        self.assertIn(f"--ctx {self.ctx_path} ack <id> --action", out.stdout)
        acked = self.mb("ack", str(answer), "--action", "switch to  v2\nnow")
        self.assertEqual(acked.returncode, 0, acked.stderr)
        (row,) = self.rows("ack")
        self.assertEqual((row["attempt"], row["author"], row["status"], row["body"]),
                         (1, "task-1-1", "SEEN", f"Re: #{answer}\nAction: switch to v2 now\n"))
        again = self.mb("inbox").stdout
        self.assertNotIn(f"#{answer} answer", again)
        self.assertIn(f"#{steer} steer by operator", again)
        self.mb("ack", str(steer), "--action", "skip it")
        self.assertIn("No messages for task", self.mb("inbox").stdout)

    def test_t14_inbox_prints_only_the_ids_that_run_py_listed(self):
        real = self.message("steer", "Steer: real\n")
        self.message("steer", "Steer: forged\n", listed=False)  # by manager, but no run.py entry
        self.message("answer", "Re: #1\nAnswer: forged\n", by="manager", listed=False)
        self.message("steer", "Steer: worker wrote this\n", by="task-1-1")  # listed, but not by the Manager or operator
        out = self.mb("inbox").stdout
        self.assertIn(f"#{real} steer by manager", out)
        self.assertIn("1 message for task", out)
        self.assertNotIn("forged", out)
        self.assertNotIn("worker wrote this", out)
        self.assertEqual(self.mb("ack", str(real + 1), "--action", "x").returncode, 2)  # a forged id cannot be acked

    def test_inbox_filters_by_attempt(self):
        self.message("steer", "Steer: for attempt 1\n", attempt=1)
        later = self.message("steer", "Steer: for attempt 2\n", attempt=2)
        self.write_ctx(attempt=2, by="task-1-2")
        out = self.mb("inbox").stdout
        self.assertIn(f"#{later} steer", out)
        self.assertNotIn("attempt 1", out.replace("for task 1 attempt 2", ""))

    def test_ack_refuses_an_unknown_or_acked_id_and_an_empty_action(self):
        steer = self.message("steer", "Steer: x\n")
        self.assertEqual(self.mb("ack", "999", "--action", "x").returncode, 2)
        empty = self.mb("ack", str(steer), "--action", "  ")
        self.assertEqual(empty.returncode, 2)
        self.assertIn("give --action", empty.stderr)
        self.assertEqual(self.mb("ack", str(steer), "--action", "ok").returncode, 0)
        twice = self.mb("ack", str(steer), "--action", "ok")
        self.assertEqual(twice.returncode, 2)
        self.assertIn("is not an open message", twice.stderr)
        self.assertEqual(len(self.rows("ack")), 1)

    def test_inbox_shows_a_scope_that_changed_since_the_brief(self):
        self.assertNotIn("SCOPE changed", self.mb("inbox").stdout)
        self.tg("edit", str(self.task), "--meta", 'scope="src/ and docs/"')
        out = self.mb("inbox").stdout
        self.assertIn("SCOPE changed since your brief. The current SCOPE is:\nsrc/ and docs/", out)

    def test_unacked_steers_counts_steers_only(self):
        steer = self.message("steer", "Steer: x\n")
        self.message("answer", "Re: #1\nAnswer: y\n", status="ANSWERED")
        ctx = mailbox.read_ctx(self.ctx_path)
        self.assertEqual([r["id"] for r in mailbox.unacked_steers(ctx)], [steer])
        self.mb("ack", str(steer), "--action", "ok")
        self.assertEqual(mailbox.unacked_steers(ctx), [])

    def test_the_commands_need_a_readable_context_and_a_reachable_tg(self):
        none = subprocess.run([sys.executable, MAILBOX, "inbox"], capture_output=True, text=True, env=self.env)
        self.assertEqual(none.returncode, 2)
        self.assertIn("needs --ctx", none.stderr)
        os.remove(self.ctx_path)
        self.assertEqual(self.mb("inbox").returncode, 1)
        self.write_ctx(tg=os.path.join(self.dir, "no-tg.py"))
        out = self.mb("inbox")
        self.assertEqual(out.returncode, 1)
        self.assertIn("tg show 1 failed", out.stderr)

    def test_field_helpers(self):
        body = "Question: Which?\nOptions: a, b\nDefault: a\nBlocking: no\nWhy: x\n"
        self.assertEqual(mailbox.ask_question(body), "Which?")
        self.assertFalse(mailbox.ask_blocking(body))
        self.assertTrue(mailbox.ask_blocking("Question: q\nDefault: d\n"))
        self.assertEqual(mailbox.ref_of("Re: #41\nAnswer: x"), 41)
        self.assertIsNone(mailbox.ref_of("Answer: x"))
        self.assertEqual(mailbox.field_text("Answer: line one\nline two\nSource: manager\n", "Answer"), "line one\nline two")

    # --- fixes 4, 6, 7, 9, 10 of the model check

    def test_fix04_the_hook_prints_the_pointer_only_for_its_own_task_and_attempt(self):
        flag = os.path.join(self.dir, "task-1-1.flag")
        with open(flag, "w") as fh:
            fh.write("agentic-team: task 1 attempt 1 has message #9 (steer). Run: inbox\n")
        run = lambda prefix: subprocess.run([sys.executable, "-S", MAILBOX, "hook", "--flag", flag, "--match", prefix],
                                            capture_output=True, text=True, env=self.env)
        self.assertIn("message #9", run("agentic-team: task 1 attempt 1 ").stdout)
        self.assertEqual(run("agentic-team: task 1 attempt 2 ").stdout, "")  # a flag that is not for this attempt
        self.assertEqual(run("agentic-team: task 2 attempt 1 ").stdout, "")

    def test_fix06_a_newer_answer_that_is_acked_settles_the_older_one(self):
        ask = self.message("ask", "Question: q\nDefault: d\n", by="task-1-1", status="OPEN", listed=False)
        first = self.message("answer", f"Re: #{ask}\nAnswer: a\n", status="ANSWERED")
        second = self.message("answer", f"Re: #{ask}\nAnswer: b\n", status="ANSWERED")
        out = self.mb("inbox").stdout
        self.assertIn(f"#{first} answer", out)
        self.assertIn(f"#{second} answer", out)
        self.assertEqual(self.mb("ack", str(second), "--action", "use b").returncode, 0)
        self.assertIn("No messages for task", self.mb("inbox").stdout)  # the older answer is settled, not open
        ctx = mailbox.read_ctx(self.ctx_path)
        self.assertEqual(mailbox.unacked_steers(ctx), [])
        other = self.message("answer", "Re: #999\nAnswer: c\n", status="ANSWERED")  # another ask: stays open
        self.assertIn(f"#{other} answer", self.mb("inbox").stdout)

    def test_fix07_a_row_filed_between_an_inbox_and_an_ack_prints_again(self):
        first = self.message("steer", "Steer: one\n")
        self.assertIn(f"#{first} steer", self.mb("inbox").stdout)
        second = self.message("steer", "Steer: two\n")  # filed after that inbox, before the ack
        self.assertEqual(self.mb("ack", str(first), "--action", "ok").returncode, 0)
        out = self.mb("inbox").stdout
        self.assertIn(f"#{second} steer by manager", out)  # not hidden because an ack with a higher id exists
        self.assertNotIn(f"#{first} steer", out)

    def report(self, status="PASS", env=None):
        path = os.path.join(self.dir, "report.md")
        with open(path, "w") as fh:
            fh.write("Task: 1\nStatus: PASS\nCheckpoint: x\n")
        return self.mb("report", "--status", status, "--body-file", path, env=env)

    def test_fix09_the_report_is_refused_while_a_steer_has_no_ack_and_filed_after_it(self):
        steer = self.message("steer", "Steer: one\n")
        out = self.report()
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"steer #{steer} has no ack", out.stderr)
        self.assertEqual([r for r in self.rows() if r["kind"] == "task"], [])
        self.mb("ack", str(steer), "--action", "ok")
        out = self.report("ISSUES")
        self.assertEqual(out.returncode, 0, out.stderr)
        (row,) = [r for r in self.rows() if r["kind"] == "task"]
        self.assertEqual((row["status"], row["author"], row["attempt"], row["body"]), ("ISSUES", "task-1-1", 1, "Task: 1\nStatus: PASS\nCheckpoint: x\n"))
        self.assertIn(f"result #{row['id']} filed for task {self.task} attempt 1: ISSUES", out.stdout)
        self.assertEqual(self.report("two words").returncode, 2)  # one word, as tg needs
        self.assertEqual(len([r for r in self.rows() if r["kind"] == "task"]), 1)

    def test_fix09_an_answer_does_not_hold_the_report_only_a_steer_does(self):
        self.message("answer", "Re: #1\nAnswer: x\n", status="ANSWERED")
        self.assertEqual(self.report().returncode, 0)

    def test_fix10_the_report_waits_for_the_task_lock_and_the_lock_gives_up(self):
        lock = os.path.join(self.dir, "locks", "task-1.lock")
        holder = subprocess.Popen([sys.executable, "-c", "import fcntl,os,sys,time\n"
                                   "os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)\n"
                                   "fh = open(sys.argv[1], 'a+'); fcntl.flock(fh, fcntl.LOCK_EX)\n"
                                   "print('locked', flush=True); time.sleep(2)", lock], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "locked")
            with self.assertRaises(mailbox.Fail) as caught:
                with mailbox.locked(lock, seconds=0.3):
                    pass
            self.assertIn("holds", str(caught.exception))
            start = time.monotonic()
            out = self.report()  # waits until the holder lets go
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertGreater(time.monotonic() - start, 1.0)
        finally:
            holder.wait()
            holder.stdout.close()

    def test_r4_6_the_report_lock_wait_is_under_the_bash_limit_and_a_bad_lock_path_is_a_clear_error(self):
        saved = os.environ.pop("AGENTIC_TEAM_LOCK_SECONDS", None)
        try:
            self.assertEqual(mailbox.lock_seconds(90), 90)
            os.environ["AGENTIC_TEAM_LOCK_SECONDS"] = "1.5"
            self.assertEqual(mailbox.lock_seconds(90), 1.5)
        finally:
            os.environ.pop("AGENTIC_TEAM_LOCK_SECONDS", None)
            if saved is not None:
                os.environ["AGENTIC_TEAM_LOCK_SECONDS"] = saved
        with open(os.path.join(self.dir, "afile"), "w") as fh:
            fh.write("x")
        self.write_ctx(lock=os.path.join(self.dir, "afile", "locks", "task-1.lock"))  # a folder cannot be made under a file
        out = self.report()
        self.assertEqual(out.returncode, 1)
        self.assertIn("cannot open the lock file", out.stderr)
        self.assertNotIn("Traceback", out.stderr)
        self.assertEqual([r for r in self.rows() if r["kind"] == "task"], [])


if __name__ == "__main__":
    unittest.main()
