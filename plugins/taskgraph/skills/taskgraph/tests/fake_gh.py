#!/usr/bin/env python3
"""A fake `gh api` for the taskgraph tests: one GitHub repository in a JSON file.

Run it as a program through TASKGRAPH_GH="python3 -I tests/fake_gh.py", with FAKE_GH_STATE naming the state file.
It implements only what tgstore/github sends, and copies the behaviour measured on the live test repository
(spec section 13): issue numbers shared with pull requests; comment ids that only grow; weak ETags on pages; 304 that
exits 1 with the status line on stdout, as `gh api -i` does; dependency and sub-issue calls that leave updated_at
alone; silent body truncation at 262,144 bytes; comment 422 above that; cycle and self dependency refused; a parent
blocked by its own child accepted; a 9th issue in a parent chain refused; more than 50 blockers accepted.

Faults live in the state file (see Fake.fault): fail_after, rate_limited, hide_comment_ids, delay_ms, hold_after_post,
advance (move the clock after some comment-list reads). clock_offset moves every timestamp and the Date header.
Every call appends one JSON line to <state>.log, so a test can count calls.
"""
import fcntl
import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import formatdate
from urllib.parse import parse_qs, urlsplit

BODY_LIMIT = 262144
MAX_CHAIN = 8
MAX_CHILDREN = 100


OFFSET = [0]  # seconds added to the clock; set from the state file on each call


def epoch():
    return time.time() + OFFSET[0]


def now():
    return datetime.fromtimestamp(epoch(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cut(text, size):
    return text.encode("utf-8")[:size].decode("utf-8", "ignore")


class Resp:
    def __init__(self, status, body=None, headers=None, counted=True, hold=None):
        self.status, self.body, self.headers, self.counted, self.hold = status, body, headers or {}, counted, hold


def error(status, message, errors=None):
    body = {"message": message}
    if errors:
        body["errors"] = errors
    return Resp(status, body)


class Fake:
    def __init__(self, path):
        self.path = str(path)
        self.log_path = self.path + ".log"

    @classmethod
    def create(cls, path, repo="o/demo", login="tester"):
        state = {
            "repo": repo, "login": login, "next_number": 1, "next_db_id": 5000, "next_comment_id": 100000, "issues": {}, "comments": {},
            "labels": [], "blocked_by": {}, "parent": {}, "writes": 0, "used": 0, "fail_after": None, "rate_limited": False,
            "hide_comment_ids": None, "delay_ms": 0, "hold_after_post": None, "advance": None, "clock_offset": 0,
        }
        with open(path, "w") as f:
            json.dump(state, f)
        open(str(path) + ".log", "w").close()
        return cls(path)

    # -- state access for tests -------------------------------------------------------------------------------------

    @contextmanager
    def locked(self):
        with open(self.path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            state = json.load(f)
            yield state
            f.seek(0)
            f.truncate()
            json.dump(state, f)

    def state(self):
        with self.locked() as s:
            return json.loads(json.dumps(s))

    def calls(self):
        with open(self.log_path) as f:
            return [json.loads(line) for line in f if line.strip()]

    def clear_log(self):
        open(self.log_path, "w").close()

    def fault(self, **switches):
        with self.locked() as s:
            s.update(switches)

    def new_issue(self, s, title, body="", labels=(), pull_request=False, created_at=None):
        number = s["next_number"]
        s["next_number"] += 1
        s["next_db_id"] += 1
        stamp = created_at or now()
        for name in labels:
            if name not in s["labels"]:
                s["labels"].append(name)
        s["issues"][str(number)] = {
            "number": number, "id": s["next_db_id"], "node_id": f"I_{s['next_db_id']}", "title": title, "body": body, "state": "open",
            "state_reason": None, "labels": list(labels), "created_at": stamp, "updated_at": stamp, "closed_at": None,
            "pull_request": pull_request, "user": "someone",
        }
        return s["issues"][str(number)]

    def add_issue(self, title, body="", labels=("taskgraph",), pull_request=False):
        with self.locked() as s:
            return json.loads(json.dumps(self.new_issue(s, title, body, labels, pull_request)))

    def edit_issue(self, number, **fields):
        # a person's edit in the browser: updated_at moves like GitHub's
        with self.locked() as s:
            issue = s["issues"][str(number)]
            issue.update(fields)
            if "state" in fields:
                issue["closed_at"] = now() if fields["state"] == "closed" else None
            issue["updated_at"] = fields.get("updated_at") or now()
            for name in issue["labels"]:
                if name not in s["labels"]:
                    s["labels"].append(name)

    def add_blocker(self, number, blocker):
        # a dependency added in the browser: updated_at of neither issue moves (G4)
        with self.locked() as s:
            s["blocked_by"].setdefault(str(number), []).append(blocker)

    def set_parent(self, child, parent):
        with self.locked() as s:
            s["parent"][str(child)] = parent

    def add_comment(self, number, body, user="someone"):
        with self.locked() as s:
            return json.loads(json.dumps(self.new_comment(s, number, body, user)))

    def new_comment(self, s, number, body, user):
        s["next_comment_id"] += 1
        c = {"id": s["next_comment_id"], "issue": number, "body": body, "created_at": now(), "updated_at": now(), "user": user}
        s["comments"][str(c["id"])] = c
        return c

    def age_comment(self, comment_id, seconds):
        with self.locked() as s:
            c = s["comments"][str(comment_id)]
            then = datetime.strptime(c["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() - seconds
            c["created_at"] = datetime.fromtimestamp(then, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def issue(self, number):
        return self.state()["issues"][str(number)]

    def comments(self, number):
        return [c for c in self.state()["comments"].values() if c["issue"] == number]

    # -- JSON shapes ------------------------------------------------------------------------------------------------

    def issue_json(self, s, issue):
        n = str(issue["number"])
        blockers = s["blocked_by"].get(n, [])
        blocking = [m for m, bs in s["blocked_by"].items() if issue["number"] in bs]
        kids = [int(c) for c, p in s["parent"].items() if p == issue["number"]]
        open_blockers = [b for b in blockers if s["issues"][str(b)]["state"] == "open"]
        done = [k for k in kids if s["issues"][str(k)]["state"] == "closed"]
        parent = s["parent"].get(n)
        out = {
            "number": issue["number"], "id": issue["id"], "node_id": issue["node_id"], "title": issue["title"], "body": issue["body"],
            "state": issue["state"], "state_reason": issue["state_reason"], "labels": [{"name": name} for name in issue["labels"]],
            "comments": sum(1 for c in s["comments"].values() if c["issue"] == issue["number"]), "created_at": issue["created_at"],
            "updated_at": issue["updated_at"], "closed_at": issue["closed_at"], "user": {"login": issue["user"]},
            "issue_dependencies_summary": {"blocked_by": len(open_blockers), "blocking": len(blocking), "total_blocked_by": len(blockers), "total_blocking": len(blocking)},
            "sub_issues_summary": {"total": len(kids), "completed": len(done), "percent_completed": int(100 * len(done) / len(kids)) if kids else 0},
            "parent_issue_url": f"https://api.github.com/repos/{s['repo']}/issues/{parent}" if parent else None,
        }
        if issue["pull_request"]:
            out["pull_request"] = {"url": f"https://api.github.com/repos/{s['repo']}/pulls/{issue['number']}"}
        return out

    def comment_json(self, s, c):
        return {"id": c["id"], "body": c["body"], "created_at": c["created_at"], "updated_at": c["updated_at"], "user": {"login": c["user"]},
                "issue_url": f"https://api.github.com/repos/{s['repo']}/issues/{c['issue']}"}

    # -- the API ----------------------------------------------------------------------------------------------------

    def page(self, items, query):
        per = int(query.get("per_page", ["30"])[0])
        page = int(query.get("page", ["1"])[0])
        return items[(page - 1) * per: page * per]

    def etag_response(self, body, headers):
        tag = 'W/"' + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:32] + '"'
        if headers.get("if-none-match") == tag:
            return Resp(304, None, {"etag": tag}, counted=False)
        return Resp(200, body, {"etag": tag})

    def dispatch(self, s, method, url, headers, body):
        parts = urlsplit(url)
        path, query = parts.path.strip("/"), parse_qs(parts.query)
        repo = s["repo"]
        if s["rate_limited"]:
            reset = s["rate_limited"] if isinstance(s["rate_limited"], int) and s["rate_limited"] > 10**9 else int(time.time()) + 3600
            return Resp(403, {"message": "API rate limit exceeded"}, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)})
        if method != "GET":
            s["writes"] += 1
            if s["fail_after"]:
                s["fail_after"] -= 1
                if s["fail_after"] == 0:
                    s["fail_after"] = None
                    return Resp(502, {"message": "Server Error"})
        if path == "user" and method == "GET":
            return Resp(200, {"login": s["login"]})
        if path == "graphql" and method == "POST":
            return self.graphql(s, body or {})
        m = re.fullmatch(rf"repos/{re.escape(repo)}/(.*)", path)
        if not m:
            return error(404, "Not Found")
        rest = m[1]
        if rest == "issues":
            return self.issues_collection(s, method, query, body)
        if rest == "issues/comments" and method == "GET":
            return self.repo_comments(s, query)
        if (m := re.fullmatch(r"issues/comments/(\d+)", rest)) and method == "DELETE":
            if m[1] not in s["comments"]:
                return error(404, "Not Found")
            del s["comments"][m[1]]
            return Resp(204)
        if (m := re.fullmatch(r"issues/(\d+)(?:/(.*))?", rest)):
            n = m[1]
            if n not in s["issues"]:
                return error(404, "Not Found")
            return self.issue_route(s, method, int(n), m[2] or "", query, headers, body)
        if rest == "labels":
            if method == "GET":
                return Resp(200, [{"name": name} for name in self.page(s["labels"], query)])
            if body["name"] in s["labels"]:
                return error(422, "Validation Failed", [{"code": "already_exists"}])
            s["labels"].append(body["name"])
            return Resp(201, {"name": body["name"]})
        return error(404, "Not Found")

    def issues_collection(self, s, method, query, body):
        if method == "POST":
            labels = body.get("labels", [])
            issue = self.new_issue(s, body["title"], cut(body.get("body") or "", BODY_LIMIT), labels)
            return Resp(201, self.issue_json(s, issue))
        wanted = [x for x in query.get("labels", [""])[0].split(",") if x]
        state = query.get("state", ["open"])[0]
        found = [i for i in s["issues"].values() if all(w in i["labels"] for w in wanted) and state in ("all", i["state"])]
        found.sort(key=lambda i: i["number"], reverse=query.get("direction", ["desc"])[0] == "desc")
        return self.etag_response([self.issue_json(s, i) for i in self.page(found, query)], {"if-none-match": self.header})

    def repo_comments(self, s, query):
        since = query.get("since", [None])[0]
        found = [c for c in s["comments"].values() if not since or c["updated_at"] >= since]
        found.sort(key=lambda c: c["id"], reverse=query.get("direction", ["asc"])[0] == "desc")
        return Resp(200, [self.comment_json(s, c) for c in self.page(found, query)])

    def issue_route(self, s, method, n, rest, query, headers, body):
        issue = s["issues"][str(n)]
        if rest == "":
            if method == "GET":
                return self.etag_response(self.issue_json(s, issue), headers)
            if method == "PATCH":
                return self.patch(s, issue, body)
        if rest == "comments":
            if method == "GET":
                hide = s["hide_comment_ids"]
                found = sorted((c for c in s["comments"].values() if c["issue"] == n), key=lambda c: c["id"])
                if hide and hide["reads"] > 0:
                    hide["reads"] -= 1
                    found = [c for c in found if c["id"] not in hide["ids"]]
                move = s["advance"]
                if move:
                    move["reads"] -= 1
                    if move["reads"] <= 0:
                        s["clock_offset"] += move["seconds"]
                        s["advance"] = None
                return Resp(200, [self.comment_json(s, c) for c in self.page(found, query)])
            if method == "POST":
                if len((body.get("body") or "").encode("utf-8")) > BODY_LIMIT:
                    return error(422, "Validation Failed", [{"resource": "IssueComment", "code": "custom", "field": "body", "message": "Body is too long (maximum is 65536 characters)"}])
                c = self.new_comment(s, n, body["body"], s["login"])
                hold = s["hold_after_post"]
                return Resp(201, self.comment_json(s, c), hold=(n, hold) if hold else None)
        if rest == "dependencies/blocked_by":
            if method == "POST":
                return self.add_blocker_route(s, n, body["issue_id"])
            if method == "GET":
                return Resp(200, [self.issue_json(s, s["issues"][str(b)]) for b in s["blocked_by"].get(str(n), [])])
        if (m := re.fullmatch(r"dependencies/blocked_by/(\d+)", rest)) and method == "DELETE":
            blocker = self.by_db_id(s, int(m[1]))
            if blocker is None or blocker not in s["blocked_by"].get(str(n), []):
                return error(404, "Not Found")
            s["blocked_by"][str(n)].remove(blocker)
            return Resp(200, self.issue_json(s, issue))
        if rest == "sub_issues" and method == "POST":
            return self.add_sub_issue(s, n, body)
        if rest == "sub_issue" and method == "DELETE":
            child = self.by_db_id(s, body["sub_issue_id"])
            if child is None or s["parent"].get(str(child)) != n:
                return error(404, "Not Found")
            del s["parent"][str(child)]
            return Resp(200, self.issue_json(s, issue))
        return error(404, "Not Found")

    def by_db_id(self, s, db_id):
        return next((i["number"] for i in s["issues"].values() if i["id"] == db_id), None)

    def patch(self, s, issue, body):
        if "title" in body:
            issue["title"] = body["title"]
        if "body" in body:
            issue["body"] = cut(body["body"] or "", BODY_LIMIT)  # silent truncation, HTTP 200 (G10)
        if "labels" in body:
            issue["labels"] = list(body["labels"])
            for name in issue["labels"]:
                if name not in s["labels"]:
                    s["labels"].append(name)
        if "state" in body and body["state"] != issue["state"]:
            issue["state"] = body["state"]
            issue["closed_at"] = now() if body["state"] == "closed" else None
            issue["state_reason"] = body.get("state_reason") or ("completed" if body["state"] == "closed" else "reopened")
        issue["updated_at"] = now()
        return Resp(200, self.issue_json(s, issue))

    def reaches(self, s, start, target):
        seen, stack = set(), [start]
        while stack:
            n = stack.pop()
            if n == target:
                return True
            if n not in seen:
                seen.add(n)
                stack.extend(s["blocked_by"].get(str(n), []))
        return False

    def add_blocker_route(self, s, n, db_id):
        blocker = self.by_db_id(s, db_id)
        if blocker is None:
            return error(404, "Not Found")
        invalid = lambda why: Resp(422, {"message": "Validation Failed", "errors": [{"type": "VALIDATION", "message": why}]})
        if blocker == n:
            return invalid("an issue cannot depend on itself")
        if self.reaches(s, blocker, n):
            return invalid("this would create a dependency cycle")
        if blocker in s["blocked_by"].get(str(n), []):
            return invalid("dependency already exists")
        s["blocked_by"].setdefault(str(n), []).append(blocker)  # no updated_at change (G4); more than 50 are accepted (G2)
        return Resp(201, self.issue_json(s, s["issues"][str(n)]))

    def chain_above(self, s, n):
        count = 0
        while str(n) in s["parent"]:
            n = s["parent"][str(n)]
            count += 1
        return count

    def height_below(self, s, n):
        kids = [int(c) for c, p in s["parent"].items() if p == n]
        return 1 + max((self.height_below(s, k) for k in kids), default=0)

    def add_sub_issue(self, s, n, body):
        child = self.by_db_id(s, body["sub_issue_id"])
        if child is None:
            return error(404, "Not Found")
        invalid = lambda why: Resp(422, {"message": why})
        if child == n or n in self.descendants(s, child):
            return invalid("A sub-issue cannot be its own ancestor")
        if str(child) in s["parent"] and not body.get("replace_parent"):
            return invalid("Issue already has a parent")
        s["parent"].pop(str(child), None)
        if sum(1 for p in s["parent"].values() if p == n) >= MAX_CHILDREN:
            return invalid("You can't add more than 100 sub-issues")
        if self.chain_above(s, n) + 1 + self.height_below(s, child) > MAX_CHAIN:
            return invalid("You can’t add more than 7 layers of sub-issues. To add a sub-issue, remove a parent issue at any level.")
        s["parent"][str(child)] = n
        return Resp(201, self.issue_json(s, s["issues"][str(n)]))

    def descendants(self, s, n):
        found = []
        for c, p in s["parent"].items():
            if p == n:
                found += [int(c), *self.descendants(s, int(c))]
        return found

    def graphql(self, s, body):
        query = body.get("query", "")
        op = (re.match(r"\s*(?:query|mutation)\s+(\w+)", query) or [None, None])[1]
        variables = body.get("variables") or {}
        if op == "Edges":
            out = {}
            for alias, number in re.findall(r"(i\d+): issue\(number: (\d+)\)", query):
                blockers = s["blocked_by"].get(number) if number in s["issues"] else None
                out[alias] = None if number not in s["issues"] else {"blockedBy": self.connection(blockers or [], 0)}
            return Resp(200, {"data": {"repository": out}})
        if op == "EdgesMore":
            number = str(variables["number"])
            blockers = s["blocked_by"].get(number, [])
            return Resp(200, {"data": {"repository": {"issue": {"blockedBy": self.connection(blockers, int(variables["after"]))}}}})
        return Resp(200, {"errors": [{"message": f"fake gh does not know the operation {op}"}]})

    def connection(self, blockers, start):
        chunk = blockers[start:start + 100]
        more = start + 100 < len(blockers)
        return {"totalCount": len(blockers), "pageInfo": {"hasNextPage": more, "endCursor": str(start + 100) if more else None},
                "nodes": [{"number": b} for b in chunk]}

    # -- the program ------------------------------------------------------------------------------------------------

    def run(self, argv, stdin_text):
        args = list(argv)
        assert args[:1] == ["api"], f"fake gh only knows `api`, got {args}"
        method, url, headers, has_input, i = "GET", None, {}, False, 1
        while i < len(args):
            a = args[i]
            if a == "-X":
                method, i = args[i + 1], i + 1
            elif a == "-H":
                key, _, value = args[i + 1].partition(":")
                headers[key.strip().lower()], i = value.strip(), i + 1
            elif a == "--input":
                has_input, i = True, i + 1
            elif not a.startswith("-"):
                url = a
            i += 1
        body = json.loads(stdin_text) if has_input and stdin_text.strip() else None
        self.header = headers.get("if-none-match")
        hold = None
        with self.locked() as s:
            OFFSET[0] = s["clock_offset"]
            delay = s["delay_ms"]
            resp = self.dispatch(s, method, url, headers, body)
            if resp.counted and resp.status != 429:
                s["used"] += 1
            used = s["used"]
            hold = resp.hold
            with open(self.log_path, "a") as log:
                op = re.match(r"\s*(?:query|mutation)\s+(\w+)", (body or {}).get("query", "")) if url == "graphql" else None
                log.write(json.dumps({"method": method, "path": url, "status": resp.status, "counted": resp.counted, "op": op[1] if op else None}) + "\n")
        if delay:
            time.sleep(delay / 1000)
        if hold:
            number, wanted = hold
            end = time.time() + 15
            while time.time() < end:
                with self.locked() as s:
                    if sum(1 for c in s["comments"].values() if c["issue"] == number) >= wanted:
                        break
                time.sleep(0.02)
        reason = {200: "OK", 201: "Created", 204: "No Content", 304: "Not Modified", 403: "Forbidden", 404: "Not Found", 422: "Unprocessable Entity", 502: "Bad Gateway"}.get(resp.status, "")
        head = [f"HTTP/2.0 {resp.status} {reason}", f"X-Ratelimit-Used: {used}", f"Date: {formatdate(epoch(), usegmt=True)}"]
        head += [f"X-Ratelimit-Remaining: {5000 - used}"] if "x-ratelimit-remaining" not in resp.headers else []
        head += [f"{k}: {v}" for k, v in resp.headers.items()]
        out = "\r\n".join(head) + "\r\n\r\n" + (json.dumps(resp.body) if resp.body is not None else "")
        err = "" if resp.status < 300 else f"gh: {(resp.body or {}).get('message', 'HTTP ' + str(resp.status))} (HTTP {resp.status})\n"
        if resp.status == 304:
            err = "gh: HTTP 304\n"
        return (0 if resp.status < 300 else 1), out, err


def main():
    fake = Fake(os.environ["FAKE_GH_STATE"])
    code, out, err = fake.run(sys.argv[1:], "" if sys.stdin.isatty() else sys.stdin.read())
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code


if __name__ == "__main__":
    sys.exit(main())
