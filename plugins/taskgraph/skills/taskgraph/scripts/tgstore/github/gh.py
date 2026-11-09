from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from tgstore.base import RateLimited, RemoteError, StoreError

AUTH = "gh is not logged in for github.com; run gh auth login"


class HttpError(RemoteError):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


class Response:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body


def iso(epoch):
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pace():
    return float(os.environ.get("TASKGRAPH_GH_PACE", "1.1"))


class Gh:
    """`gh api -i`: status, headers and body as a value. A 304 is a result. $TASKGRAPH_GH replaces the program (tests)."""

    def __init__(self):
        program = os.environ.get("TASKGRAPH_GH")
        self.cmd = shlex.split(program) if program else ["gh"]
        self.debug = os.environ.get("TASKGRAPH_DEBUG") == "1"
        self.last_write = None
        self.remaining = None
        self.reset = None
        self.server_time = None  # epoch of the Date header of the last response

    def wait_for_pacing(self):
        if self.last_write is not None:
            time.sleep(max(0.0, pace() - (time.monotonic() - self.last_write)))

    def request(self, method, path, body=None, etag=None, mutation=None):
        mutation = method != "GET" if mutation is None else mutation
        if self.remaining == 0 and self.reset and self.reset > time.time():
            raise RateLimited(f"GitHub rate limit is used up; try again after {iso(self.reset)}", iso(self.reset))
        args = [*self.cmd, "api", "-i", "-X", method, path.lstrip("/")]
        if etag:
            args += ["-H", f"If-None-Match: {etag}"]
        if body is not None:
            args += ["-H", "Content-Type: application/json", "--input", "-"]
        if mutation:
            self.wait_for_pacing()
        try:
            feed = {"input": json.dumps(body)} if body is not None else {"stdin": subprocess.DEVNULL}
            done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", **feed)
        except FileNotFoundError:
            raise StoreError("gh is not installed; install the GitHub CLI and run gh auth login")
        finally:
            if mutation:
                self.last_write = time.monotonic()
        if not done.stdout.startswith("HTTP/"):
            text = (done.stderr or done.stdout).strip()
            if "auth login" in text or "not logged" in text or "authentication" in text.lower():
                raise StoreError(AUTH)
            raise RemoteError(f"cannot reach GitHub: {text or 'gh failed'}")
        head, _, raw = done.stdout.partition("\r\n\r\n") if "\r\n\r\n" in done.stdout else done.stdout.partition("\n\n")
        lines = head.splitlines()
        status = int(lines[0].split()[1])
        headers = {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in lines[1:])}
        try:
            data = json.loads(raw) if raw.strip() else None
        except ValueError:
            data = None
        if self.debug:
            print(f"gh: {method} {path} -> {status}", file=sys.stderr)
        if "date" in headers:
            self.server_time = parsedate_to_datetime(headers["date"]).timestamp()
        if "x-ratelimit-remaining" in headers:
            self.remaining = int(headers["x-ratelimit-remaining"])
            self.reset = int(headers.get("x-ratelimit-reset", 0)) or None
        return self.check(Response(status, headers, data), method, path)

    def check(self, r, method, path):
        if r.status < 400 or r.status == 304:
            return r
        message = (r.body or {}).get("message", "") if isinstance(r.body, dict) else ""
        if r.status == 401:
            raise StoreError(AUTH)
        if r.status in (403, 429) and ("retry-after" in r.headers or r.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in message.lower()):
            reset = r.headers.get("x-ratelimit-reset")
            when = iso(reset) if reset else iso(time.time() + int(r.headers.get("retry-after", 60)))
            raise RateLimited(f"GitHub rate limit reached; try again after {when}", when)
        detail = "; ".join(str(e.get("message") or e.get("code") or e) for e in (r.body or {}).get("errors", []) if isinstance(e, dict)) if isinstance(r.body, dict) else ""
        raise HttpError(f"GitHub refused {method} {path} (HTTP {r.status}{': ' + message if message else ''}{'; ' + detail if detail else ''})", r.status)

    def get(self, path, etag=None):
        return self.request("GET", path, etag=etag)

    def get_all(self, path, per_page=100):
        out, page = [], 1
        while True:
            r = self.get(f"{path}{'&' if '?' in path else '?'}per_page={per_page}&page={page}")
            out.extend(r.body or [])
            if len(r.body or []) < per_page:
                return out
            page += 1

    def post(self, path, body):
        return self.request("POST", path, body)

    def patch(self, path, body):
        return self.request("PATCH", path, body)

    def delete(self, path, body=None):
        return self.request("DELETE", path, body)

    def graphql(self, query, variables=None):
        body = {"query": query, **({"variables": variables} if variables else {})}
        r = self.request("POST", "graphql", body, mutation=query.lstrip().startswith("mutation"))
        data = r.body or {}
        if data.get("errors") and not data.get("data"):
            first = data["errors"][0]
            raise RemoteError(f"GitHub refused the GraphQL call ({first.get('type', 'error')}: {first.get('message')})")
        return data.get("data") or {}
