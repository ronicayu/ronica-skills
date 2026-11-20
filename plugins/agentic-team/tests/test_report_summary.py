"""Tests for scripts/report_summary.py: the short summary of a result row, with no model. Run: "$PY" plugins/agentic-team/tests/run_parallel.py"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from report_summary import summarize  # noqa: E402

SHA = "c9c6c29" + "0" * 33
WORKER_PASS = (f"Task: 7\nStatus: PASS\nBranch: worktree-task-7\nHead: {SHA}\nWorktree: /w\n"
               "Ran: make test: 21 passed\nmake lint: ok\n```\nStatus: ISSUES\n```\n"
               "Evidence: tests pass -> make test: 21 passed\nsecond evidence line\n"
               "Files: src/a.py, src/b.py\n`src/c.py`\nIssues: None\nDeviations: None\nCheckpoint: 2026-11-20 10:00 UTC - done\n")
WORKER_ISSUES = ("Task: 7\nStatus: ISSUES\nHead: abc\nIssues: - the parser drops the last row\nsecond issue\n"
                 "Asked: #12, #15\nCheckpoint: x\n")
VERIFY_FAILED = ("Task: 7\nStatus: ISSUES\nVerdict: verify-failed\nHead: " + SHA + "\n"
                 "Issues: blocking: the export drops the header row\n"
                 "Issues: blocking[test]: " + "x" * 200 + "\n"
                 "Issues: blocking: a third finding\nIssues: a note that does not block\nCheckpoint: x\n")


class SummaryTest(unittest.TestCase):
    def test_a_worker_pass_counts_files_and_commands_and_quotes_the_first_evidence_line(self):
        self.assertEqual(summarize("task", "PASS", WORKER_PASS),
                         "✅ PASS · head c9c6c29 · 3 files changed · 2 commands ran\n"
                         "Evidence: tests pass -> make test: 21 passed")

    def test_a_worker_pass_in_chinese(self):
        self.assertEqual(summarize("task", "PASS", WORKER_PASS, "zh").splitlines()[0],
                         "✅ 通过 · 提交 c9c6c29 · 改了 3 个文件 · 跑了 2 条命令")

    def test_one_file_and_one_command_are_singular_and_missing_fields_are_left_out(self):
        text = summarize("task", "PASS", f"Task: 1\nStatus: PASS\nHead: {SHA}\nRan: make\nFiles: a.py\n")
        self.assertEqual(text, "✅ PASS · head c9c6c29 · 1 file changed · 1 command ran")
        self.assertEqual(summarize("task", "PASS", "Task: 1\nStatus: PASS\nHead: None\nRan: None\nFiles: None\n"), "✅ PASS")

    def test_issues_and_blocked_name_the_first_issue_and_the_asks(self):
        self.assertEqual(summarize("task", "ISSUES", WORKER_ISSUES),
                         "⚠️ ISSUES · the parser drops the last row\nAsked: #12, #15")
        self.assertEqual(summarize("task", "BLOCKED", "Status: BLOCKED\nIssues: None\nAsked: none: no ask left\n"),
                         "⚠️ BLOCKED\nAsked: none: no ask left")
        self.assertEqual(summarize("task", "ISSUES", WORKER_ISSUES, "zh"),
                         "⚠️ 有问题 · the parser drops the last row\n已提问: #12, #15")

    def test_verify_failed_counts_the_blocking_findings_and_cuts_the_first_two(self):
        lines = summarize("verify", "ISSUES", VERIFY_FAILED).splitlines()
        self.assertEqual(lines[0], "❌ verify-failed · 3 blocking findings")
        self.assertEqual(lines[1], "- the export drops the header row")
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[2].startswith("- xxx") and lines[2].endswith("…") and len(lines[2]) == 2 + 120)
        self.assertEqual(summarize("verify", "ISSUES", VERIFY_FAILED, "zh").splitlines()[0],
                         "❌ 验证未通过 · 3 条阻塞问题")

    def test_a_passing_verdict_names_the_verdict_and_the_head(self):
        body = f"Task: 7\nStatus: PASS\nVerdict: artifact-verified\nHead: {SHA}\nCheckpoint: x\n"
        self.assertEqual(summarize("verify", "PASS", body), "✅ artifact-verified · head c9c6c29")
        self.assertEqual(summarize("verify", "PASS", body, "zh"), "✅ artifact-verified · 提交 c9c6c29")
        self.assertEqual(summarize("verify", "PASS", "Status: PASS\n"), "✅ PASS")

    def test_a_blocked_verifier_gives_its_first_issue(self):
        body = "Status: BLOCKED\nVerdict: verify-blocked\nIssues: the CI ref was never built\n"
        self.assertEqual(summarize("verify", "BLOCKED", body), "⚠️ verify-blocked · the CI ref was never built")

    def test_a_revision_mark(self):
        body = "Revision: 2\nFrom: verify #41\nHead: abc\n"
        self.assertEqual(summarize("revise", "OPEN", body), "🔁 revision 2 from verify #41")
        self.assertEqual(summarize("revise", "OPEN", body, "zh"), "🔁 第 2 轮修订，来自验证 #41")
        self.assertEqual(summarize("revise", "OPEN", "no fields"), "")

    def test_an_ask_or_answer_gets_a_summary_only_when_it_is_long(self):
        self.assertEqual(summarize("ask", "OPEN", "Question: short?\nDefault: yes\n"), "")
        self.assertEqual(summarize("answer", "SENT", "yes"), "")
        ask = "Question: " + "which endpoint " * 20 + "?\nDefault: v2\nWhy: " + "because " * 40
        text = summarize("ask", "OPEN", ask)
        self.assertTrue(text.startswith("❓ which endpoint which endpoint") and text.endswith("…"))
        self.assertEqual(len(text), 2 + 120)
        answer = summarize("answer", "SENT", "Use v2.\n" + "Details. " * 60)
        self.assertEqual(answer, "💬 Use v2.")

    def test_rows_without_a_summary_form_give_nothing(self):
        for kind, status in (("task", "STOPPED"), ("task", "DIED"), ("ack", "SEEN"), ("steer", "SENT"), ("check", "PASS"), ("verify", "DIED")):
            self.assertEqual(summarize(kind, status, "Status: PASS\nHead: abc\n"), "", (kind, status))

    def test_an_unknown_language_reads_as_english(self):
        self.assertEqual(summarize("task", "PASS", "Status: PASS\n", "fr"), "✅ PASS")


if __name__ == "__main__":
    unittest.main()
