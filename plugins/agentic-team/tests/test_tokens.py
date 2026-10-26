"""Tests for scripts/tokens.py. Run: "$PY" -m unittest discover plugins/agentic-team/tests"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOKENS = os.path.join(os.path.dirname(HERE), "scripts", "tokens.py")


def transcript(output_tokens):
    records = [
        {"type": "user", "timestamp": "2026-10-26T01:00:00Z", "message": {"content": "hi"}},
        {"type": "assistant", "timestamp": "2026-10-26T01:05:00Z",
         "message": {"id": "m1", "usage": {"output_tokens": output_tokens, "input_tokens": 3,
                                           "cache_read_input_tokens": 5, "cache_creation_input_tokens": 7}}},
    ]
    return "".join(json.dumps(r) + "\n" for r in records)


class TokensTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.abspath(self._tmp.name)
        self.projects = os.path.join(self.home, ".claude", "projects")
        self.env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        self.env["HOME"] = self.home

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, cwd, name, output_tokens):
        folder = os.path.join(self.projects, re.sub(r"[^A-Za-z0-9]", "-", cwd))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "w") as fh:
            fh.write(transcript(output_tokens))

    def run_tokens(self, *args):
        return subprocess.run([sys.executable, TOKENS, *args], capture_output=True, text=True, env=self.env)

    def test_finds_transcript_under_encoded_cwd(self):
        self.put("/work/wt/task-1-1", "abc123-full-id.jsonl", 11)
        out = self.run_tokens("abc123", "--cwd", "/work/wt/task-1-1", "--tz", "UTC", "--label", "UTC")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('ended_at="2026-10-26 01:05 UTC"', out.stdout)
        self.assertIn("tokens_output=11 tokens_input=3 tokens_cache_read=5 tokens_cache_write=7", out.stdout)

    def test_does_not_fall_back_to_other_project_folders(self):
        self.put("/work/other-project", "abc123-full-id.jsonl", 99)
        out = self.run_tokens("abc123", "--cwd", "/work/wt/task-1-1")
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(out.stdout, "")
        self.assertIn("no transcript", out.stderr)
        self.assertIn("-work-wt-task-1-1", out.stderr)

    def test_cwd_is_required(self):
        out = self.run_tokens("abc123")
        self.assertEqual(out.returncode, 2)
        self.assertIn("--cwd", out.stderr)

    def test_ambiguous_prefix_is_refused(self):
        self.put("/work/wt/task-1-1", "abc123-a.jsonl", 1)
        self.put("/work/wt/task-1-1", "abc123-b.jsonl", 2)
        out = self.run_tokens("abc123", "--cwd", "/work/wt/task-1-1")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("ambiguous", out.stderr)


if __name__ == "__main__":
    unittest.main()
