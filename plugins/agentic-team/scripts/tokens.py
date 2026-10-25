#!/usr/bin/env python3
"""Print Taskgraph meta for a finished Claude session from its transcript.

Usage:
    tokens.py <session-id-prefix> [--tz Asia/Singapore] [--label SGT] [--cwd DIR]

Prints one line of `tg edit --meta` arguments:
    ended_at="YYYY-MM-DD HH:MM SGT" tokens_output=N tokens_input=N
    tokens_cache_read=N tokens_cache_write=N

and, on stderr, the transcript's first and last message times. The counts
cover only this session's transcript; sub-agents and consultants keep their
own transcripts. Times come from the first and last message, so an idle
session shows a wider span than the work took.
"""

import argparse
import datetime
import glob
import json
import os
import re
import sys

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None


def find_transcript(prefix, cwd):
    if not re.fullmatch(r"[0-9A-Za-z-]+", prefix):
        sys.exit(f"tokens.py: invalid session id '{prefix}'")
    root = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude")), "projects")
    project_dir = os.path.join(root, re.sub(r"[^A-Za-z0-9]", "-", cwd))
    matches = glob.glob(os.path.join(project_dir, prefix + "*.jsonl"))
    if not matches:
        matches = glob.glob(os.path.join(root, "*", prefix + "*.jsonl"))
    if not matches:
        sys.exit(f"tokens.py: no transcript matches session id '{prefix}' under {root}")
    if len(matches) > 1:
        sys.exit("tokens.py: session id prefix is ambiguous:\n  " + "\n  ".join(sorted(matches)))
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session", help="session id or unique prefix (from `claude agents --json`)")
    parser.add_argument("--tz", help="IANA time zone, e.g. Asia/Singapore (default: system zone)")
    parser.add_argument("--label", help="zone label to print, e.g. SGT (default: the zone's abbreviation)")
    parser.add_argument("--cwd", default=os.getcwd(), help="project directory the session ran in (default: current)")
    args = parser.parse_args()

    if args.tz and ZoneInfo is None:
        sys.exit("tokens.py: --tz needs Python 3.9 or later")
    zone = ZoneInfo(args.tz) if args.tz else None

    usage_by_message = {}
    stamps = []
    with open(find_transcript(args.session, os.path.abspath(args.cwd))) as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("timestamp"):
                stamps.append(record["timestamp"])
            message = record.get("message") or {}
            # Streaming writes one record per content block; keep the last usage per message.
            if record.get("type") == "assistant" and message.get("usage") and message.get("id"):
                usage_by_message[message["id"]] = message["usage"]

    if not stamps:
        sys.exit("tokens.py: transcript has no timestamps")

    def fmt(stamp):
        moment = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(zone)
        return f"{moment:%Y-%m-%d %H:%M} {args.label or moment.strftime('%Z')}"

    def total(key):
        return sum(usage.get(key, 0) for usage in usage_by_message.values())

    print(f"first message {fmt(min(stamps))}; last message {fmt(max(stamps))}", file=sys.stderr)
    print(
        f'ended_at="{fmt(max(stamps))}" '
        f"tokens_output={total('output_tokens')} "
        f"tokens_input={total('input_tokens')} "
        f"tokens_cache_read={total('cache_read_input_tokens')} "
        f"tokens_cache_write={total('cache_creation_input_tokens')}"
    )


if __name__ == "__main__":
    main()
