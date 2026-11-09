from __future__ import annotations

import calendar
import hashlib
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from tgstore.base import ClaimLost, RateLimited, RemoteError, StoreError
from tgstore.changes import DUE_KEYS
from tgstore.github import comments as cm
from tgstore.github.body import START_LINE, check_size, parse, render, size
from tgstore.github.gh import Gh, HttpError, pace
from tgstore.github.queries import EDGES_MORE, edges_query
from tgstore.remote import KEEP, ClaimOutcome, Delta, Probe, Pushed, RemoteTask, canon

IN_PROGRESS = "tg:in-progress"
REMOVED = "tg:removed"
TYPE = "tg:type:"
KINDS = set(DUE_KEYS)
COLORS = {IN_PROGRESS: "fbca04", REMOVED: "cccccc"}
PAGE = 100
EDGE_BATCH = 50


def label_names(item):
    return [l["name"] if isinstance(l, dict) else l for l in item.get("labels") or []]


def task_from_item(item, server_time=None):
    labels = label_names(item)
    notes, meta, problems = parse(item.get("body"))
    meta.pop("type", None)  # the type is a label; a stray key in the block does not count
    kinds = [l for l in labels if l.startswith(TYPE)]
    known = [l for l in kinds if l[len(TYPE):] in KINDS]
    problems += [f"type:{l}" for l in kinds if l not in known]
    parent = item.get("parent_issue_url")
    status = "done" if item["state"] == "closed" else "in_progress" if IN_PROGRESS in labels else "open"
    return RemoteTask(
        number=item["number"], db_id=item["id"], node_id=item.get("node_id", ""), title=item["title"], notes=notes, meta=meta, problems=problems,
        body=item.get("body") or "", state=item["state"], labels=labels, status=status, type=known[0][len(TYPE):] if known else "task",
        parent=int(parent.rsplit("/", 1)[1]) if parent else None, created_at=item["created_at"], updated_at=item["updated_at"],
        closed_at=item.get("closed_at"), removed=REMOVED in labels, comments=item.get("comments", 0), item=item, server_time=server_time,
    )


def sha(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def fingerprint(item):
    edges = (item.get("issue_dependencies_summary"), item.get("sub_issues_summary"), item.get("parent_issue_url"))
    whole = (item.get("updated_at"), item.get("state"), item.get("state_reason"), sorted(label_names(item)), item.get("comments"), *edges, item.get("title"), item.get("body"))
    return {"all": sha(*whole), "edges": sha(*edges), "comments": item.get("comments", 0)}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def claim_rows(parsed):
    return [{"comment_id": p["id"], "token": p.get("claim", {}).get("token"), "claimant": p.get("claim", {}).get("claimant"),
             "voids": json.dumps(p["voids"]), "at": p["at"]} for p in parsed if "claim" in p or p["voids"]]


class GitHubRemote:
    def __init__(self, entry, gh=None):
        self.entry = entry
        self.gh = gh or Gh()
        self.owner, self.name = entry.repo.split("/")
        self.base = f"repos/{entry.repo}"

    # -- reading ----------------------------------------------------------------------------------------------------

    def page_path(self, page):
        return f"{self.base}/issues?labels={quote(self.entry.label)}&state=all&sort=created&direction=asc&per_page={PAGE}&page={page}"

    def probe(self, state):
        pages, info, page = {}, {}, 1
        while True:
            old = state.pages.get(page, {})
            r = self.gh.get(self.page_path(page), etag=old.get("etag"))
            if r.status == 304 and old:
                info[page] = old
            else:
                items = r.body or []
                pages[page] = items
                info[page] = {"etag": r.headers.get("etag"), "ids": [i["number"] for i in items if not i.get("pull_request")], "count": len(items)}
            if info[page]["count"] < PAGE:
                break
            page += 1
        return Probe(pages, info, bool(pages) or set(info) != set(state.pages))

    def read_edges(self, numbers):
        out = {}
        numbers = sorted(numbers)
        for i in range(0, len(numbers), EDGE_BATCH):
            batch = numbers[i: i + EDGE_BATCH]
            found = self.gh.graphql(edges_query(self.owner, self.name, batch)).get("repository") or {}
            for n in batch:
                node = found.get(f"i{n}")
                blocked = (node or {}).get("blockedBy") or {"nodes": [], "pageInfo": {}}
                blockers = [x["number"] for x in blocked["nodes"]]
                page = blocked["pageInfo"]
                while page.get("hasNextPage"):
                    more = self.gh.graphql(EDGES_MORE, {"owner": self.owner, "name": self.name, "number": n, "after": page["endCursor"]})
                    blocked = more["repository"]["issue"]["blockedBy"]
                    blockers += [x["number"] for x in blocked["nodes"]]
                    page = blocked["pageInfo"]
                out[n] = blockers
        return out

    def read_comments(self, number):
        return [p for p in map(cm.parse_comment, self.gh.get_all(f"{self.base}/issues/{number}/comments")) if p]

    def read_all_comments(self, numbers):
        wanted, found = set(numbers), {}
        for c in self.gh.get_all(f"{self.base}/issues/comments?sort=created&direction=asc"):
            n = int(c["issue_url"].rsplit("/", 1)[1])
            p = cm.parse_comment(c)
            if p and n in wanted:
                found.setdefault(n, []).append(p)
        return found

    def pull(self, state, probe, full=False, comments=False):
        delta = Delta(full=full, pages=probe.info)
        seen = {n for info in probe.info.values() for n in info["ids"]}
        want_edges, want_comments = set(), set()
        for page in probe.pages.values():
            for item in page:
                if item.get("pull_request"):
                    continue
                task, fp, old = task_from_item(item), fingerprint(item), state.fingerprints.get(item["number"])
                if task.removed:
                    delta.removed.append(task.number)
                elif old is None or old["all"] != fp["all"]:
                    delta.tasks.append(task)
                    delta.fingerprints[task.number] = fp
                    if old is None or old["edges"] != fp["edges"]:
                        want_edges.add(task.number)
                    if fp["comments"] != (old["comments"] if old else 0):
                        want_comments.add(task.number)
        gone = (state.removed | set(delta.removed))
        if full:
            want_edges = seen - gone
            delta.seen = seen
        delta.edges = self.read_edges(want_edges)
        if comments:
            by_issue = self.read_all_comments(seen - gone)
            want_comments = seen - gone
        else:
            by_issue = {n: self.read_comments(n) for n in sorted(want_comments)}
        for n in want_comments:
            parsed = by_issue.get(n, [])
            delta.results[n] = cm.join_parts(parsed)
            delta.claims[n] = claim_rows(parsed)
        return delta

    def single(self, task):
        # a task read directly (a list page can lag behind a new issue): everything a pull would hold for it
        delta = Delta(tasks=[task], fingerprints={task.number: fingerprint(task.item)})
        delta.edges = self.read_edges([task.number])
        if task.comments:
            parsed = self.read_comments(task.number)
            delta.results[task.number], delta.claims[task.number] = cm.join_parts(parsed), claim_rows(parsed)
        return delta

    def fetch(self, number):
        r = self.gh.get(f"{self.base}/issues/{number}")
        return task_from_item(r.body, self.gh.server_time)

    def login(self):
        return self.gh.get("user").body["login"]

    # -- writing ----------------------------------------------------------------------------------------------------

    def ensure_setup(self, labels):
        have = {l["name"] for l in self.gh.get_all(f"{self.base}/labels")}
        for name in sorted(set(labels) - have):
            try:
                self.gh.post(f"{self.base}/labels", {"name": name, "color": COLORS.get(name, "0e8a16" if name == self.entry.label else "5319e7")})
            except HttpError as e:
                if e.status != 422:  # 422: it exists already
                    raise

    def run(self, ops):
        applied = []
        for i, (desc, fn) in enumerate(ops):
            try:
                applied.append(fn())
            except RemoteError as e:
                left = [desc, *(d for d, _ in ops[i + 1:])]
                msg = f"{e}; applied: {', '.join(applied) or 'nothing'}; not applied: {', '.join(left)}. Run tg sync to see what GitHub holds"
                if isinstance(e, RateLimited):
                    raise RateLimited(msg, e.reset_at, applied, left) from e
                raise RemoteError(msg, applied, left) from e

    def checked(self, label, sent, answer):
        if size(answer.get("body") or "") != size(sent):
            raise RemoteError(f"GitHub kept {size(answer.get('body') or ''):,} of the {size(sent):,} bytes sent for {label}")

    def push(self, plan, fresh):
        pushed = Pushed(db_ids=dict(plan.db_ids))
        ids, base, gh = pushed.ids, self.base, self.gh
        ops = []

        def num(i):
            return ids.get(i, i)

        def db(n):
            if n not in pushed.db_ids:
                pushed.db_ids[n] = self.fetch(n).db_id
            return pushed.db_ids[n]

        def link(child, parent):
            def go():
                gh.post(f"{base}/issues/{num(parent)}/sub_issues", {"sub_issue_id": db(num(child)), "replace_parent": True})
                return f"#{num(child)} under #{num(parent)}"
            return go

        def unlink(child, parent):
            def go():
                try:
                    gh.delete(f"{base}/issues/{parent}/sub_issue", {"sub_issue_id": db(child)})
                except HttpError as e:
                    if e.status != 404:  # 404: it is not a sub-issue any more
                        raise
                return f"#{child} detached from #{parent}"
            return go

        for c in plan.created:
            labels = [self.entry.label] + ([TYPE + c.type] if c.type != "task" else [])
            body = render(c.notes, c.meta)
            check_size(f"new task {c.title!r}", body)

            def create(c=c, labels=labels, body=body):
                r = gh.post(f"{base}/issues", {"title": c.title, "body": body, "labels": labels}).body
                self.checked(f"new task {c.title!r}", body, r)
                ids[c.id] = r["number"]
                pushed.db_ids[r["number"]] = r["id"]
                pushed.node_ids[r["number"]] = r.get("node_id", "")
                pushed.meta[r["number"]] = dict(c.meta)
                return f"created #{r['number']}"

            ops.append((f"create {c.title!r}", create))
            if c.parent is not None:
                ops.append((f"put the new task under #{c.parent}", link(c.id, c.parent)))

        for e in plan.edits:
            f = fresh[e.id]
            patch, labels = {}, list(f.labels)
            if e.title is not None and e.title != f.title:
                patch["title"] = e.title
            if e.type is not None:
                labels = [l for l in labels if not l.startswith(TYPE)] + ([TYPE + e.type] if e.type != "task" else [])
            if e.status is not None:
                labels = [l for l in labels if l != IN_PROGRESS] + ([IN_PROGRESS] if e.status == "in_progress" else [])
                if (e.status == "done") != (f.state == "closed"):
                    patch["state"] = "closed" if e.status == "done" else "open"
                    if e.status == "done":
                        patch["state_reason"] = "completed"
            if set(labels) != set(f.labels):
                patch["labels"] = labels
            need_body = e.notes is not None or bool(e.meta_set) or bool(e.meta_unset)
            if "broken" in f.problems and need_body:
                raise StoreError(f"meta block on #{e.id} is broken; fix or delete it on GitHub")
            new_meta, consumed = dict(f.meta), False
            new_meta.update(e.meta_set)
            for key in e.meta_unset:
                new_meta.pop(key, None)
            if e.pending and "broken" not in f.problems and (patch or need_body or e.flush):
                consumed = True
                for row in e.pending:
                    key = row["key"]
                    if (canon(f.meta[key]) if key in f.meta else None) != row["base"]:
                        pushed.dropped.append((e.id, key))
                    elif row["op"] == "set":
                        new_meta[key] = json.loads(row["value"])
                    else:
                        new_meta.pop(key, None)
            body = None
            if "broken" not in f.problems and (need_body or new_meta != f.meta):
                body = render(e.notes if e.notes is not None else f.notes, new_meta, keep=bool(START_LINE.search(f.body)))
                check_size(f"#{e.id}", body)
                if body != f.body:
                    patch["body"] = body
            if "broken" not in f.problems:
                pushed.meta[e.id] = new_meta
            if patch:
                def update(e=e, patch=patch, consumed=consumed, body=body):
                    r = gh.patch(f"{base}/issues/{e.id}", patch).body
                    if body is not None and "body" in patch:
                        self.checked(f"#{e.id}", body, r)
                    if consumed:
                        pushed.flushed.add(e.id)
                    return f"updated #{e.id}"
                ops.append((f"update #{e.id} ({', '.join(patch)})", update))
            elif consumed:
                pushed.flushed.add(e.id)
            if e.parent is not KEEP:
                if e.parent is None and f.parent is not None:
                    ops.append((f"detach #{e.id} from #{f.parent}", unlink(e.id, f.parent)))
                elif e.parent is not None and e.parent != f.parent:
                    ops.append((f"put #{e.id} under #{e.parent}", link(e.id, e.parent)))

        for n in plan.removed:
            f = fresh[n]
            patch = {"state": "closed", "state_reason": "not_planned", "labels": [l for l in f.labels if l != IN_PROGRESS] + [REMOVED]}

            def remove(n=n, patch=patch):
                gh.patch(f"{base}/issues/{n}", patch)
                return f"closed #{n} as not planned"

            ops.append((f"remove #{n}", remove))
            if f.parent is not None and f.parent not in plan.removed:
                ops.append((f"detach #{n} from #{f.parent}", unlink(n, f.parent)))

        for task, dep in plan.edges_removed:
            def drop(task=task, dep=dep):
                try:
                    gh.delete(f"{base}/issues/{num(task)}/dependencies/blocked_by/{db(num(dep))}")
                except HttpError as e:
                    if e.status != 404:  # 404: GitHub has no such dependency
                        raise
                return f"#{task} no longer depends on #{dep}"
            ops.append((f"remove the dependency #{task} -> #{dep}", drop))
        for task, dep in plan.edges_added:
            def add(task=task, dep=dep):
                gh.post(f"{base}/issues/{num(task)}/dependencies/blocked_by", {"issue_id": db(num(dep))})
                return f"#{num(task)} depends on #{num(dep)}"
            ops.append((f"dependency #{task} -> #{dep}", add))
        self.run(ops)
        return pushed

    def post_result(self, number, row):
        at = now()
        parts = cm.render_result(row, at)
        posted = []

        def op(text):
            def go():
                posted.append(self.gh.post(f"{self.base}/issues/{number}/comments", {"body": text}).body)
                return f"comment {len(posted)} of {len(parts)}"
            return go

        self.run([(f"result comment {i} of {len(parts)}", op(t)) for i, t in enumerate(parts, 1)])
        return {"id": posted[0]["id"], "task_id": number, "at": posted[0]["created_at"], "status": row.status, "kind": row.kind, "attempt": row.attempt,
                "author": row.author, "body": row.body}


    # -- claim (spec 8, with the rules of the model check) ----------------------------------------------------------

    STALE = 60  # seconds
    DEADLINE = 30  # seconds from the claim comment to the label PATCH

    def server_now(self):
        return self.gh.server_time or time.time()

    def age(self, claim):
        return self.server_now() - calendar.timegm(time.strptime(claim["at"], "%Y-%m-%dT%H:%M:%SZ"))

    def unvoided(self, parsed):
        voided = {v for p in parsed for v in p["voids"]}
        return [p for p in sorted(parsed, key=lambda p: p["id"]) if "claim" in p and p["id"] not in voided]

    def stale(self, claim, issue):
        # older than 60 s, and the issue shows nobody works on it: no label, or closed after the claim was posted
        if self.age(claim) <= self.STALE:
            return False
        return IN_PROGRESS not in issue.labels or (issue.state == "closed" and claim["at"] < (issue.closed_at or ""))

    def abandon(self, comment_id, voids):
        # A comment that voids a stale claim keeps its void marker (deleting it would bring the stale claim back); any other is deleted.
        try:
            if voids:
                self.gh.patch(f"{self.base}/issues/comments/{comment_id}", {"body": "\n".join(cm.marker("void", {"of": v}) for v in voids)})
            else:
                self.gh.delete(f"{self.base}/issues/comments/{comment_id}")
        except RemoteError as e:
            print(f"warning: could not clean up claim comment {comment_id}: {e}", file=sys.stderr)

    def decide(self, number, comment_id):
        for attempt in range(3):
            parsed = self.read_comments(number)
            if any(p["id"] == comment_id for p in parsed):
                return parsed, self.unvoided(parsed)
            time.sleep(min(1.0, pace()))
        raise RemoteError(f"GitHub does not list the new claim comment on #{number}; run tg start again")

    def claim(self, number, claimant):
        parsed = self.read_comments(number)
        unvoided = self.unvoided(parsed)
        mine = lambda p: p["claim"]["claimant"] == claimant
        voids = []
        if unvoided:
            issue = self.fetch(number)
            voids = [p for p in unvoided if self.stale(p, issue) or (mine(p) and self.age(p) >= self.STALE)]
            left = [p for p in unvoided if p not in voids]
            if left:
                first = left[0]
                if mine(first):
                    return ClaimOutcome(False, claimant, first["id"], first["at"], [], claim_rows(parsed))
                raise ClaimLost(f"#{number} is claimed by {first['claim']['claimant']} since {first['at']}", first["claim"]["claimant"], first["id"])
        ids = [p["id"] for p in voids]
        text = cm.render_claim(uuid.uuid4().hex[:12], claimant, now(), ids)
        posted = self.gh.post(f"{self.base}/issues/{number}/comments", {"body": text}).body

        def lost(winner):
            self.abandon(posted["id"], ids)
            who = winner["claim"]["claimant"] if winner else "another claimant"
            raise ClaimLost(f"#{number} is claimed by {who}", who, winner["id"] if winner else None)

        parsed, unvoided = self.decide(number, posted["id"])
        if not unvoided or unvoided[0]["id"] != posted["id"]:
            lost(unvoided[0] if unvoided else None)
        time.sleep(pace())  # the confirm read: a lagging replica that hid a lower claim from the first read shows it now
        parsed, unvoided = self.decide(number, posted["id"])
        if not unvoided or unvoided[0]["id"] != posted["id"]:
            lost(unvoided[0] if unvoided else None)
        return ClaimOutcome(True, claimant, posted["id"], posted["created_at"], ids, claim_rows(parsed))

    def check_deadline(self, outcome, fresh):
        # called with a read that came after the confirm read, right before the label PATCH
        if outcome.comment_id is None or not outcome.won:
            return
        made = calendar.timegm(time.strptime(outcome.created_at, "%Y-%m-%dT%H:%M:%SZ"))
        if (fresh.server_time or time.time()) - made > self.DEADLINE:
            self.abandon(outcome.comment_id, outcome.voided)
            raise StoreError("claim took too long; run tg start again")
