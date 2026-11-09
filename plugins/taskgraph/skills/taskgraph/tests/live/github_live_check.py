#!/usr/bin/env python3
"""Live check for the taskgraph GitHub backend (spec 12.4). Not collected by pytest.

Part 1, C1-C11: what GitHub does (capabilities the design relies on). Part 2, E1-E12 (and E13, E14): tg itself, end to end,
through a temporary .taskgraph.toml that maps project tgcheck to the test repository, with temporary cache files.

Writes ONLY to ronicayu/taskgraph-backend-test (any other --repo needs --yes). Every issue title starts with "tgcheck:".
Every issue it creates is closed at the end (state_reason not_planned), also when a step fails.

  python3 -I tests/live/github_live_check.py [--skip-bulk] [--only C1,C4,E1-E14] [--python python3.11]

tg needs Python 3.11 when a config file exists, so the E steps run tg with --python (default: python3.11 on PATH, else
/opt/homebrew/bin/python3.11); this script itself runs on any Python 3. TASKGRAPH_GH_PACE is not set: writes keep their 1.1 s pace.

One line per step: "<id> PASS|FAIL <verdict> <detail>". PASS means the step found what the spec section 13 records (a
capability that is REFUTED there, such as "a dependency bumps updated_at", passes when it is refuted again). The JSON-lines log
(--log, default in the temp folder) holds each gh call and its important response fields.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

REPO = "ronicayu/taskgraph-backend-test"
TG = Path(__file__).resolve().parents[2] / "scripts" / "tg.py"
LOG = None
CREATED = []  # issue numbers to close at the end
RESULTS = []


def log(entry):
    LOG.write(json.dumps(entry, ensure_ascii=False) + "\n")
    LOG.flush()


def gh(args, input=None, check=True):
    """Run gh; return (status, headers, body) for `gh api -i` calls."""
    cmd = ["gh", "api", "-i", *args]
    p = subprocess.run(cmd, input=input, capture_output=True, text=True)
    out = p.stdout
    head, _, body = out.partition("\r\n\r\n") if "\r\n\r\n" in out else out.partition("\n\n")
    lines = head.splitlines()
    status = int(lines[0].split()[1]) if lines and lines[0].startswith("HTTP") else None
    headers = {}
    for line in lines[1:]:
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()
    try:
        data = json.loads(body) if body.strip() else None
    except ValueError:
        data = body
    log({"cmd": " ".join(a if len(a) < 300 else a[:300] + "..." for a in cmd), "status": status,
         "ratelimit_used": headers.get("x-ratelimit-used"), "resource": headers.get("x-ratelimit-resource"),
         "stderr": p.stderr.strip()[:500]})
    if check and (status is None or status >= 400):
        raise RuntimeError(f"gh {' '.join(args[:3])} -> {status}: {p.stderr.strip()[:300]} {str(data)[:300]}")
    return status, headers, data


def gql(query, **variables):
    args = ["graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-F" if isinstance(v, (int, bool)) else "-f", f"{k}={json.dumps(v) if isinstance(v, bool) else v}"]
    status, headers, data = gh(args, check=False)
    if status != 200 or (isinstance(data, dict) and data.get("errors")):
        raise RuntimeError(f"graphql -> {status}: {json.dumps(data)[:600]}")
    return data["data"]


def pause():
    time.sleep(1.1)  # GitHub: wait at least one second between mutative requests


def result(cid, verdict, detail, expect="CONFIRMED"):
    # expect: what spec section 13 records for this step; GitHub behaviour that the design relies on NOT existing is expect="REFUTED"
    ok = verdict == expect
    RESULTS.append((cid, "PASS" if ok else "FAIL", verdict, detail))
    print(f"{cid} {'PASS' if ok else 'FAIL'} {verdict} {detail}", flush=True)
    log({"check": cid, "verdict": verdict, "expect": expect, "detail": detail})


def owner_name():
    return REPO.split("/")


def repo_id():
    o, n = owner_name()
    return gql("query($o:String!,$n:String!){repository(owner:$o,name:$n){id}}", o=o, n=n)["repository"]["id"]


def ensure_label(name, color="ededed"):
    status, _, _ = gh([f"repos/{REPO}/labels/{name.replace(':', '%3A')}"], check=False)
    if status == 404:
        gh([f"repos/{REPO}/labels", "-X", "POST", "-f", f"name={name}", "-f", f"color={color}"])
        pause()


def create_issue(title, body="", labels=("taskgraph",)):
    args = [f"repos/{REPO}/issues", "-X", "POST", "-f", f"title=tgcheck: {title}", "-f", f"body={body}"]
    for label in labels:
        args += ["-f", f"labels[]={label}"]
    _, _, data = gh(args)
    CREATED.append(data["number"])
    pause()
    return {"number": data["number"], "id": data["id"], "node_id": data["node_id"], "updated_at": data["updated_at"]}


def issue(number):
    return gh([f"repos/{REPO}/issues/{number}"])[2]


def node_updated(number):
    o, n = owner_name()
    q = "query($o:String!,$n:String!,$k:Int!){repository(owner:$o,name:$n){issue(number:$k){updatedAt lastEditedAt}}}"
    return gql(q, o=o, n=n, k=number)["repository"]["issue"]


PROBE = None


def probe_url():
    return f"repos/{REPO}/issues?labels=taskgraph&state=all&sort=created&direction=asc&per_page=100"


def probe(etag=None):
    args = [probe_url()] + (["-H", f"If-None-Match: {etag}"] if etag else [])
    status, headers, _ = gh(args, check=False)
    return status, headers.get("etag"), headers.get("x-ratelimit-used")


def comments_probe(etag=None):
    url = f"repos/{REPO}/issues/comments?sort=updated&direction=desc&per_page=1"
    status, headers, _ = gh([url] + (["-H", f"If-None-Match: {etag}"] if etag else []), check=False)
    return status, headers.get("etag"), headers.get("x-ratelimit-used")


# ---------------------------------------------------------------- checks

def c1_labels():
    for name, color in (("taskgraph", "0e8a16"), ("tg:in-progress", "fbca04"), ("tg:removed", "b60205"),
                        ("tg:type:milestone", "5319e7"), ("tg:type:decision", "1d76db")):
        ensure_label(name, color)
    _, _, labels = gh([f"repos/{REPO}/labels", "-X", "GET", "-f", "per_page=100"])
    names = {l["name"] for l in labels}
    ok = {"taskgraph", "tg:in-progress", "tg:type:milestone"} <= names
    result("C1-labels", "CONFIRMED" if ok else "REFUTED", f"labels with ':' create and read back: {sorted(n for n in names if n.startswith('tg') or n == 'taskgraph')}")


def c2_body_block(state):
    block = ('<!-- taskgraph:meta v1\n{"estimate": 2, "lane": "core", "sessions": [{"id": "x"}], "note": "a -- b --> c"}\n'
             'taskgraph:end -->')
    body = "Why it is needed.\n\n- [ ] Exit test: `make check`\n\n" + block + "\n"
    a = create_issue("body block round trip", body)
    back = issue(a["number"])["body"]
    exact = back == body
    crlf = "\r\n" in (back or "")
    result("C2-body-roundtrip", "CONFIRMED" if exact else "REFUTED",
           f"body read back byte-equal={exact}, contains CRLF={crlf}, len={len(back or '')}")
    state["A"] = a


def gh_json(path, method, payload, check=False):
    """gh api with a JSON body on stdin (large bodies do not fit on a command line)."""
    return gh([path, "-X", method, "--input", "-"], input=json.dumps(payload), check=check)


def c3_sizes(state):
    """Limits are 262144 UTF-8 bytes. Issue bodies over it are TRUNCATED with HTTP 200; comments get HTTP 422."""
    a = state["A"]
    url = f"repos/{REPO}/issues/{a['number']}"
    for text, label in (("x" * 262144, "262144 ASCII"), ("x" * 262145, "262145 ASCII"), ("\u00e9" * 131073, "131073 x U+00E9 = 262146 bytes")):
        status, _, _ = gh_json(url, "PATCH", {"body": text})
        back = issue(a["number"])["body"] or ""
        truncated = len(back.encode()) < len(text.encode())
        expect_trunc = len(text.encode()) > 262144
        result(f"C3-issue-body {label}", "CONFIRMED" if status == 200 and truncated == expect_trunc else "REFUTED",
               f"PATCH -> HTTP {status}; read back {len(back.encode())} bytes; silently truncated={truncated}")
        pause()
    for text, label in (("y" * 262144, "262144 ASCII"), ("y" * 262145, "262145 ASCII"), ("\u00e9" * 131073, "262146 bytes")):
        status, _, data = gh_json(f"{url}/comments", "POST", {"body": text})
        ok = (status == 201) == (len(text.encode()) <= 262144)
        result(f"C3-comment-body {label}", "CONFIRMED" if ok else "REFUTED",
               f"POST comment -> HTTP {status} {'' if status == 201 else str(data)[:160]}")
        pause()
    gh([url, "-X", "PATCH", "-f", "body=size checks done"])
    pause()


def c4_dependencies_and_updated_at(state):
    o, n = owner_name()
    b = create_issue("dependency target B")
    c = create_issue("dependency source C")
    state["B"], state["C"] = b, c
    time.sleep(2)
    _, etag, used0 = probe()
    _, cetag, _ = comments_probe()
    before_b, before_c = node_updated(b["number"]), node_updated(c["number"])
    time.sleep(2)
    # REST: C is blocked by B. issue_id is the database id of B.
    status, _, data = gh([f"repos/{REPO}/issues/{c['number']}/dependencies/blocked_by", "-X", "POST", "-F", f"issue_id={b['id']}"], check=False)
    result("C4-rest-add-blocked-by", "CONFIRMED" if status == 201 else "REFUTED",
           f"POST .../issues/{c['number']}/dependencies/blocked_by issue_id=<database id of #{b['number']}> -> HTTP {status}")
    pause()
    time.sleep(3)
    after_b, after_c = node_updated(b["number"]), node_updated(c["number"])
    bumped_c = after_c["updatedAt"] != before_c["updatedAt"]
    bumped_b = after_b["updatedAt"] != before_b["updatedAt"]
    result("C4-dep-bumps-updatedAt", "CONFIRMED" if bumped_c and bumped_b else "REFUTED",
           f"after addBlockedBy: blocked issue updatedAt {before_c['updatedAt']} -> {after_c['updatedAt']}; "
           f"blocking issue {before_b['updatedAt']} -> {after_b['updatedAt']}", expect="REFUTED")
    st, _, used1 = probe(etag)
    result("C4-probe-sees-dep", "CONFIRMED" if st == 200 else "REFUTED",
           f"conditional probe after addBlockedBy -> HTTP {st} (200 = probe notices the change)")
    q = ("query($o:String!,$n:String!,$k:Int!){repository(owner:$o,name:$n){issue(number:$k){"
         "blockedBy(first:10){nodes{number}} issueDependenciesSummary{totalBlockedBy}}}}")
    got = gql(q, o=o, n=n, k=c["number"])["repository"]["issue"]
    result("C4-graphql-blockedBy", "CONFIRMED" if [x["number"] for x in got["blockedBy"]["nodes"]] == [b["number"]] else "REFUTED",
           f"GraphQL blockedBy of #{c['number']} = {got}")
    # GraphQL remove, then add back through GraphQL.
    gql("mutation($i:ID!,$b:ID!){removeBlockedBy(input:{issueId:$i,blockingIssueId:$b}){issue{number}}}", i=c["node_id"], b=b["node_id"])
    pause()
    gql("mutation($i:ID!,$b:ID!){addBlockedBy(input:{issueId:$i,blockingIssueId:$b}){issue{number}}}", i=c["node_id"], b=b["node_id"])
    pause()
    result("C4-graphql-add-remove", "CONFIRMED", "removeBlockedBy and addBlockedBy mutations accepted with node ids")
    # Cycle: B blocked by C while C is blocked by B.
    try:
        gql("mutation($i:ID!,$b:ID!){addBlockedBy(input:{issueId:$i,blockingIssueId:$b}){issue{number}}}", i=b["node_id"], b=c["node_id"])
        result("C4-cycle", "REFUTED", "GitHub ACCEPTED a dependency cycle B<->C; tg must tolerate cycles in pulled data")
        gql("mutation($i:ID!,$b:ID!){removeBlockedBy(input:{issueId:$i,blockingIssueId:$b}){issue{number}}}", i=b["node_id"], b=c["node_id"])
    except RuntimeError as e:
        result("C4-cycle", "CONFIRMED", f"GitHub rejects a dependency cycle: {str(e)[:200]}")
    pause()
    try:
        gql("mutation($i:ID!,$b:ID!){addBlockedBy(input:{issueId:$i,blockingIssueId:$b}){issue{number}}}", i=b["node_id"], b=b["node_id"])
        result("C4-self", "REFUTED", "GitHub accepted a self dependency")
    except RuntimeError as e:
        result("C4-self", "CONFIRMED", f"self dependency rejected: {str(e)[:160]}")
    pause()
    # comment bumps updatedAt and the issue probe
    _, etag2, _ = probe()
    before = node_updated(b["number"])
    time.sleep(2)
    gh([f"repos/{REPO}/issues/{b['number']}/comments", "-X", "POST", "-f", "body=probe comment"])
    pause()
    time.sleep(2)
    after = node_updated(b["number"])
    st2, _, _ = probe(etag2)
    st3, _, _ = comments_probe(cetag)
    # The probe answer depends on how fresh GitHub's list is (spec G16: 304 once, 200 another time); the design does not use this probe.
    result("C4-comment-bumps", "CONFIRMED" if after["updatedAt"] != before["updatedAt"] else "REFUTED",
           f"comment: updatedAt {before['updatedAt']} -> {after['updatedAt']}; sort=updated probe HTTP {st2} (lag dependent); comments probe HTTP {st3}")
    _, etag3, _ = probe()
    used2 = gh(["rate_limit"])[2]["resources"]["core"]["used"]
    sts = [probe(etag3)[0] for _ in range(5)]
    used3 = gh(["rate_limit"])[2]["resources"]["core"]["used"]
    result("C4-304-free", "CONFIRMED" if sts == [304] * 5 and used3 == used2 else "REFUTED",
           f"5 unchanged conditional probes -> {sts}; core used {used2} -> {used3} (GET /rate_limit is free)")


def c10_page_probe_sees_edges(state):
    """Dependency and sub-issue changes do not bump updatedAt, but the REST page JSON carries
    issue_dependencies_summary, sub_issues_summary and parent_issue_url, so the page ETag changes."""
    x, y, w, z = (create_issue(t) for t in ("old X", "old Y", "old W", "newer Z"))

    def after(label, fn):
        _, et, _ = probe()
        time.sleep(1)
        fn()
        time.sleep(1.5)
        st, _, _ = probe(et)
        result(f"C10-{label}", "CONFIRMED" if st == 200 else "REFUTED", f"page probe after {label} -> HTTP {st}")

    dep = lambda a, b: gh([f"repos/{REPO}/issues/{a['number']}/dependencies/blocked_by", "-X", "POST", "-F", f"issue_id={b['id']}"])
    undep = lambda a, b: gh([f"repos/{REPO}/issues/{a['number']}/dependencies/blocked_by/{b['id']}", "-X", "DELETE"])
    after("dep-on-older-issues", lambda: dep(x, y))
    pause()
    after("blocker-swap", lambda: (undep(x, y), pause(), dep(x, w)))
    pause()
    after("sub-issue-add", lambda: gh([f"repos/{REPO}/issues/{y['number']}/sub_issues", "-X", "POST", "-F", f"sub_issue_id={z['id']}"]))
    pause()


def c5_sub_issues(state):
    o, n = owner_name()
    p = create_issue("parent P")
    k = create_issue("child K")
    before_p, before_k = node_updated(p["number"]), node_updated(k["number"])
    _, etag, _ = probe()
    time.sleep(2)
    status, _, _ = gh([f"repos/{REPO}/issues/{p['number']}/sub_issues", "-X", "POST", "-F", f"sub_issue_id={k['id']}"], check=False)
    result("C5-rest-add-sub-issue", "CONFIRMED" if status == 201 else "REFUTED",
           f"POST .../issues/{p['number']}/sub_issues sub_issue_id=<database id> -> HTTP {status}")
    pause()
    time.sleep(3)
    after_p, after_k = node_updated(p["number"]), node_updated(k["number"])
    st, _, _ = probe(etag)
    result("C5-sub-bumps-updatedAt", "CONFIRMED" if after_k["updatedAt"] != before_k["updatedAt"] else "REFUTED",
           f"addSubIssue: child updatedAt {before_k['updatedAt']} -> {after_k['updatedAt']}; parent {before_p['updatedAt']} -> {after_p['updatedAt']}; probe HTTP {st}", expect="REFUTED")
    got = gql("query($o:String!,$n:String!,$k:Int!){repository(owner:$o,name:$n){issue(number:$k){parent{number}}}}",
              o=o, n=n, k=k["number"])["repository"]["issue"]
    result("C5-parent-field", "CONFIRMED" if (got["parent"] or {}).get("number") == p["number"] else "REFUTED",
           f"Issue.parent of #{k['number']} = {got['parent']}")
    # createIssue with parentIssueId in one call
    rid = repo_id()
    labels = gql("query($o:String!,$n:String!){repository(owner:$o,name:$n){label(name:\"taskgraph\"){id}}}", o=o, n=n)
    made = gql('mutation($r:ID!,$p:ID!,$l:ID!){createIssue(input:{repositoryId:$r,title:"tgcheck: created as child",'
               'parentIssueId:$p,labelIds:[$l]}){issue{number parent{number}}}}',
               r=rid, p=p["node_id"], l=labels["repository"]["label"]["id"])["createIssue"]["issue"]
    CREATED.append(made["number"])
    pause()
    result("C5-create-with-parent", "CONFIRMED" if (made["parent"] or {}).get("number") == p["number"] else "REFUTED",
           f"createIssue(parentIssueId) -> #{made['number']} parent {made['parent']}")
    # dependency between parent and its own child
    try:
        gql("mutation($i:ID!,$b:ID!){addBlockedBy(input:{issueId:$i,blockingIssueId:$b}){issue{number}}}", i=p["node_id"], b=k["node_id"])
        result("C5-dep-on-own-child", "REFUTED", "GitHub accepted parent blocked by its own sub-issue; tg rejects this, so pulled data can break tg rules", expect="REFUTED")
        gql("mutation($i:ID!,$b:ID!){removeBlockedBy(input:{issueId:$i,blockingIssueId:$b}){issue{number}}}", i=p["node_id"], b=k["node_id"])
    except RuntimeError as e:
        result("C5-dep-on-own-child", "CONFIRMED", f"rejected: {str(e)[:160]}")
    pause()
    state["P"] = p


def c6_bulk_limits(state):
    """50 blockers per issue, and 8 levels of sub-issues. Creates 52 issues (paced, about 2 minutes)."""
    o, n = owner_name()
    target = create_issue("limit target T")
    blockers = [create_issue(f"limit blocker {i}") for i in range(1, 52)]
    ok_count, first_fail = 0, None
    for i, b in enumerate(blockers, 1):
        try:
            gql("mutation($i:ID!,$b:ID!){addBlockedBy(input:{issueId:$i,blockingIssueId:$b}){issue{number}}}", i=target["node_id"], b=b["node_id"])
            ok_count += 1
        except RuntimeError as e:
            first_fail = (i, str(e)[:240])
            break
        finally:
            pause()
    total = gql("query($o:String!,$n:String!,$k:Int!){repository(owner:$o,name:$n){issue(number:$k){blockedBy(first:100){totalCount}}}}",
                o=o, n=n, k=target["number"])["repository"]["issue"]["blockedBy"]["totalCount"]
    # Docs (changelog 2025-08-21) say 50 per relationship type; on 2026-11-08 GitHub accepted and stored 51.
    result("C6-blocked-by-limit", "CONFIRMED" if ok_count >= 50 and total == ok_count else "REFUTED",
           f"{ok_count} blockers accepted, {total} stored; first failure {first_fail} (limit is at least {ok_count})")
    # depth: chain blockers[0] <- [1] <- ... as parent -> child
    depth_ok, fail = 1, None
    for i in range(1, 10):
        parent, child = blockers[i - 1], blockers[i]
        status, _, data = gh([f"repos/{REPO}/issues/{parent['number']}/sub_issues", "-X", "POST", "-F", f"sub_issue_id={child['id']}"], check=False)
        pause()
        if status != 201:
            fail = (i + 1, status, str(data)[:200])
            break
        depth_ok = i + 1
    # Docs: "up to eight levels" = a chain of 8 issues (root + 7 layers). The 9th issue must fail with 422.
    result("C6-sub-issue-depth", "CONFIRMED" if depth_ok == 8 and fail and fail[0] == 9 else "REFUTED",
           f"chain of {depth_ok} issues accepted (levels = issues in chain); first failure {fail}")
    state["T"] = target


def c7_claim_race(state, rounds=10):
    """Two claimers post a claim comment at the same moment, then list comments; the lowest claim id after the
    newest release marker wins. Check: each claimer sees its own comment, and both name the same winner."""
    issue_ = create_issue("claim race")
    num = issue_["number"]
    agree = see_own = both_win = 0
    detail = []
    for r in range(rounds):
        barrier = threading.Barrier(2)
        views = {}

        def claimer(name):
            token = uuid.uuid4().hex[:12]
            barrier.wait()
            _, _, made = gh([f"repos/{REPO}/issues/{num}/comments", "-X", "POST", "-f",
                             f"body=Claimed by {name}.\n<!-- taskgraph:claim v1 token={token} by={name} round={r} -->"])
            _, _, rows = gh([f"repos/{REPO}/issues/{num}/comments", "-X", "GET", "-f", "per_page=100"])
            ids = [c["id"] for c in rows]
            release = max((c["id"] for c in rows if "taskgraph:release" in c["body"]), default=0)
            claims = [c for c in rows if "taskgraph:claim v1" in c["body"] and c["id"] > release]
            winner = min(claims, key=lambda c: c["id"]) if claims else None
            views[name] = {"mine": made["id"], "sees_own": made["id"] in ids, "winner": winner["id"] if winner else None,
                           "sorted": ids == sorted(ids)}

        threads = [threading.Thread(target=claimer, args=(nm,)) for nm in ("A", "B")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        a, b = views.get("A"), views.get("B")
        if a and b:
            agree += a["winner"] == b["winner"]
            see_own += a["sees_own"] and b["sees_own"]
            both_win += a["winner"] == a["mine"] and b["winner"] == b["mine"]
            detail.append((a["mine"], b["mine"], a["winner"], b["winner"], a["sorted"] and b["sorted"]))
        time.sleep(1.5)
        gh([f"repos/{REPO}/issues/{num}/comments", "-X", "POST", "-f", f"body=Released.\n<!-- taskgraph:release v1 round={r} -->"])
        pause()
    result("C7-claim-race", "CONFIRMED" if agree == rounds and see_own == rounds and both_win == 0 else "REFUTED",
           f"{rounds} rounds: both saw own comment {see_own}, agreed on winner {agree}, both thought they won {both_win}; "
           f"(idA, idB, winnerA, winnerB, ascending) = {detail}")


def c8_close_reasons(state):
    o, n = owner_name()
    x = create_issue("close not planned with label")
    lid = gql("query($o:String!,$n:String!){repository(owner:$o,name:$n){label(name:\"tg:removed\"){id}}}", o=o, n=n)["repository"]["label"]["id"]
    gql("mutation($i:ID!,$l:ID!){addLabelsToLabelable(input:{labelableId:$i,labelIds:[$l]}){clientMutationId}}", i=x["node_id"], l=lid)
    pause()
    got = gql("mutation($i:ID!){closeIssue(input:{issueId:$i,stateReason:NOT_PLANNED}){issue{state stateReason}}}", i=x["node_id"])["closeIssue"]["issue"]
    pause()
    result("C8-close-not-planned", "CONFIRMED" if got == {"state": "CLOSED", "stateReason": "NOT_PLANNED"} else "REFUTED", f"closeIssue -> {got}")
    # updateIssue sets state and labels in one call
    y = create_issue("state and labels in one updateIssue")
    status, _, data = gh([f"repos/{REPO}/issues/{y['number']}", "-X", "PATCH", "-f", "state=closed", "-f", "state_reason=completed",
                          "-f", "labels[]=taskgraph", "-f", "body=closed with labels in one PATCH"], check=False)
    result("C8-one-patch", "CONFIRMED" if status == 200 and data["state"] == "closed" else "REFUTED",
           f"PATCH state+labels+body in one request -> HTTP {status}, state={data.get('state') if isinstance(data, dict) else None}")
    pause()


def c9_costs(state):
    o, n = owner_name()
    snap = ("query($o:String!,$n:String!,$c:String){rateLimit{cost remaining}repository(owner:$o,name:$n){"
            "issues(first:100,after:$c,labels:[\"taskgraph\"],states:[OPEN,CLOSED]){pageInfo{hasNextPage endCursor} totalCount "
            "nodes{number id databaseId title body state stateReason createdAt updatedAt closedAt "
            "labels(first:20){nodes{name}} parent{number} blockedBy(first:50){nodes{number}}}}}}")
    t0 = time.time()
    d = gql(snap, o=o, n=n)
    full = time.time() - t0
    inc = ("query($o:String!,$n:String!,$s:DateTime!){rateLimit{cost remaining}repository(owner:$o,name:$n){"
           "issues(first:100,filterBy:{since:$s,labels:[\"taskgraph\"]},states:[OPEN,CLOSED]){totalCount "
           "nodes{number updatedAt labels(first:20){nodes{name}} parent{number} blockedBy(first:50){nodes{number}}}}}}")
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300))
    t1 = time.time()
    e = gql(inc, o=o, n=n, s=since)
    incr = time.time() - t1
    com = ("query($o:String!,$n:String!){rateLimit{cost}repository(owner:$o,name:$n){issues(first:50,labels:[\"taskgraph\"]){"
           "nodes{number comments(first:100){nodes{databaseId createdAt body}}}}}}")
    f = gql(com, o=o, n=n)
    result("C9-costs", "CONFIRMED",
           f"full snapshot page: cost {d['rateLimit']['cost']}, {d['repository']['issues']['totalCount']} issues, {full:.2f}s; "
           f"incremental since {since}: cost {e['rateLimit']['cost']}, {e['repository']['issues']['totalCount']} changed, {incr:.2f}s; "
           f"comments page (50 issues x 100): cost {f['rateLimit']['cost']}")


def c11_title_length(state):
    status, _, data = gh([f"repos/{REPO}/issues", "-X", "POST", "-f", "title=tgcheck: " + "t" * 291, "-f", "labels[]=taskgraph"], check=False)
    if status == 201:
        CREATED.append(data["number"])
        pause()
        got = len(issue(data["number"])["title"])
        result("C11-title-300", "CONFIRMED", f"a 300-character title is accepted (HTTP 201), read back {got} characters")
    else:
        result("C11-title-300", "CONFIRMED", f"a 300-character title is refused: HTTP {status} {str(data)[:200]}")


# ---------------------------------------------------------------- end to end: tg itself

class Tg:
    """Runs tg.py as a user would: a temporary config that maps project tgcheck to the test repository, one cache file per machine."""

    def __init__(self, python, folder):
        self.python, self.folder = python, Path(folder)
        self.configs = {}
        for who in ("m1", "m2"):
            path = self.folder / f"{who}.toml"
            path.write_text(
                f'version = 1\n\n[projects.tgcheck]\nbackend = "github"\nrepo = "{REPO}"\ncache = "{self.folder / (who + ".db")}"\n\n'
                '[projects.tgcheck.meta]\nlocal = ["sessions", "session", "cleanup_kept", "host_rebase"]\ndeferred = ["tokens", "model", "started_at"]\n',
                encoding="utf-8")
            self.configs[who] = path

    def env(self, who, debug=False):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TASKGRAPH_", "FAKE_GH"))}
        env.update(TASKGRAPH_CONFIG=str(self.configs[who]), TASKGRAPH_PROJECT="tgcheck", TASKGRAPH_CLAIMANT=who)
        if debug:
            env["TASKGRAPH_DEBUG"] = "1"
        return env

    def popen(self, who, *args, debug=False):
        return subprocess.Popen([self.python, str(TG), "--json", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env(who, debug))

    def run(self, who, *args, debug=False, input=None):
        p = subprocess.run([self.python, str(TG), "--json", *args], capture_output=True, text=True, env=self.env(who, debug), input=input)
        log({"tg": " ".join(args)[:300], "who": who, "code": p.returncode, "stderr": p.stderr.strip()[:600]})
        time.sleep(1.1)  # every write sleeps after it
        return p

    def ok(self, who, *args, debug=False):
        p = self.run(who, *args, debug=debug)
        if p.returncode != 0:
            raise RuntimeError(f"tg {' '.join(args)[:80]} -> exit {p.returncode}: {p.stderr.strip()[:300]}")
        return json.loads(p.stdout) if p.stdout.strip() else None


def gql_issue(number, fields):
    o, n = owner_name()
    return gql("query($o:String!,$n:String!,$k:Int!){repository(owner:$o,name:$n){issue(number:$k){%s}}}" % fields, o=o, n=n, k=number)["repository"]["issue"]


def block_of(body):
    m = re.search(r"<!-- taskgraph:meta v1\n(.*)\ntaskgraph:end -->", body or "")
    return json.loads(m[1]) if m else None


def labels_of(number):
    return sorted(l["name"] for l in issue(number)["labels"])


def tgcheck_count():
    return len(gh([f"repos/{REPO}/issues?labels=taskgraph&state=all&per_page=100&page=1"])[2])


def track(number):
    CREATED.append(number)
    return number


def e_steps(tg, only, state):
    """E1-E14. Each step is independent where it can be; ids flow through `state`."""
    def step(sid, fn):
        if only and sid not in only:
            return
        try:
            fn()
        except Exception as e:
            result(sid, "ERROR", str(e)[:500])

    def e1():
        g = tg.ok("m1", "add", "tgcheck: goal", "--type", "milestone")
        state["G"] = track(g["id"])
        got = labels_of(g["id"])
        result("E1", "CONFIRMED" if got == ["taskgraph", "tg:type:milestone"] else "REFUTED", f"tg add --type milestone -> #{g['id']}, labels {got}")

    def e2():
        a = tg.ok("m1", "add", "tgcheck: A", "--blocks", str(state["G"]), "--meta", "estimate=2", "lane=core")
        state["A"] = track(a["id"])
        g_blockers = [x["number"] for x in gql_issue(state["G"], "blockedBy(first:20){nodes{number}}")["blockedBy"]["nodes"]]
        a_blockers = gql_issue(state["A"], "blockedBy(first:20){totalCount}")["blockedBy"]["totalCount"]
        block = block_of(issue(state["A"])["body"])
        ok = g_blockers == [state["A"]] and a_blockers == 0 and block == {"estimate": 2, "lane": "core"}
        result("E2", "CONFIRMED" if ok else "REFUTED", f"G blockedBy {g_blockers}, A blockedBy count {a_blockers}, A block {block}")

    def e3():
        before = tgcheck_count()
        p = tg.run("m1", "add", "tgcheck: B", "--parent", str(state["A"]), "--depends", str(state["A"]))
        after = tgcheck_count()
        ok = p.returncode == 1 and "ancestor or descendant" in p.stderr and before == after
        result("E3", "CONFIRMED" if ok else "REFUTED", f"exit {p.returncode}, stderr {p.stderr.strip()[:120]!r}, issues {before} -> {after}")

    def e4():
        c = tg.ok("m1", "add", "tgcheck: C", "--parent", str(state["A"]))
        state["C"] = track(c["id"])
        parent = (gql_issue(state["C"], "parent{number}")["parent"] or {}).get("number")
        result("E4", "CONFIRMED" if parent == state["A"] else "REFUTED", f"C #{state['C']} parent on GitHub: {parent}")

    def e5():
        body = issue(state["A"])["body"]
        block = body[body.index("<!-- taskgraph:meta v1"):]
        gh_json(f"repos/{REPO}/issues/{state['A']}", "PATCH", {"body": "edited by hand in the browser\n\n" + block}, check=True)
        pause()
        shown = tg.ok("m1", "--fresh", "show", str(state["A"]))
        ok = shown["notes"] == "edited by hand in the browser" and shown["meta"] == {"estimate": 2, "lane": "core"}
        result("E5", "CONFIRMED" if ok else "REFUTED", f"notes {shown['notes']!r}, meta {shown['meta']}")

    def e6():
        p = tg.run("m1", "edit", str(state["A"]), "--meta", 'sessions=[{"id":"x"}]', 'tokens="1/2"', 'verify="make"', debug=True)
        assert p.returncode == 0, p.stderr
        patches = [l for l in p.stderr.splitlines() if l.startswith("gh: PATCH")]
        block = block_of(issue(state["A"])["body"])
        shown = tg.ok("m1", "show", str(state["A"]))["meta"]
        ok = len(patches) == 1 and block == {"estimate": 2, "lane": "core", "verify": "make"} and set(shown) == {"estimate", "lane", "sessions", "tokens", "verify"}
        result("E6", "CONFIRMED" if ok else "REFUTED", f"PATCH calls {len(patches)}, block {block}, tg show meta keys {sorted(shown)}")

    def e13():
        tg.ok("m1", "edit", str(state["C"]), "--no-parent")
        tg.ok("m1", "dep", "rm", str(state["G"]), str(state["A"]))
        parent = gql_issue(state["C"], "parent{number}")["parent"]
        blockers = gql_issue(state["G"], "blockedBy(first:20){totalCount}")["blockedBy"]["totalCount"]
        tg.ok("m1", "edit", str(state["C"]), "--parent", str(state["A"]))
        tg.ok("m1", "dep", "add", str(state["G"]), str(state["A"]))
        again = gql_issue(state["G"], "blockedBy(first:20){totalCount}")["blockedBy"]["totalCount"]
        ok = parent is None and blockers == 0 and again == 1
        result("E13", "CONFIRMED" if ok else "REFUTED", f"after edit --no-parent: parent {parent}; after dep rm: G blockers {blockers}; added back: {again} (DELETE with a JSON body works)")

    def e7():
        rounds, good, detail = 10, 0, []
        for r in range(rounds):
            t = track(tg.ok("m1", "add", f"tgcheck: race {r}")["id"])
            procs = {who: tg.popen(who, "start", str(t)) for who in ("m1", "m2")}
            out = {who: (p.wait(), p.stdout.read(), p.stderr.read()) for who, p in procs.items()}
            codes = sorted(c for c, _, _ in out.values())
            winner = next((w for w, (c, _, _) in out.items() if c == 0), None)
            loser = next((w for w, (c, _, _) in out.items() if c == 1), None)
            comments = gh([f"repos/{REPO}/issues/{t}/comments?per_page=100"])[2]
            claims = [c for c in comments if "taskgraph:claim v1" in c["body"]]
            named = loser is not None and f"claimed by {winner}" in out[loser][2]
            clean = len(claims) == 1 and f'"claimant":"{winner}"' in claims[0]["body"]
            good += codes == [0, 1] and named and clean
            detail.append((codes, winner, named, clean))
            state[f"race{r}"] = t
        result("E7", "CONFIRMED" if good == rounds else "REFUTED", f"{good} of {rounds} rounds had exactly one exit 0, a loser that names the winner, and no loser comment left; {detail}"
                                                               + ("" if good == rounds else f"; last loser stderr {out[loser][2].strip()[:200]!r}" if loser else ""))
        tg.ok("m1", "start", str(state["C"]))

    def e8():
        big = ("x" * 99 + "\n") * 6000  # 600,000 bytes
        path = tg.folder / "big.txt"
        path.write_text(big, encoding="utf-8")
        row = tg.ok("m1", "result", "add", str(state["C"]), "--status", "PASS", "--attempt", "1", "--by", "tgcheck", "--body-file", str(path))
        parts = [c for c in gh([f"repos/{REPO}/issues/{state['C']}/comments?per_page=100"])[2] if "taskgraph:result v1" in c["body"]]
        tg.ok("m2", "sync", "--full")  # the other machine builds the result from the comments
        a = tg.ok("m1", "result", "ls", str(state["C"]))[0]["body"]
        b = tg.ok("m2", "result", "ls", str(state["C"]))[0]["body"]
        result("E8", "CONFIRMED" if len(parts) == 3 and a == big and b == big else "REFUTED", f"{len(parts)} comments; body equal on the posting machine {a == big} and on the other machine {b == big}; result id {row['id']}")

    def e9():
        tg.ok("m1", "edit", str(state["C"]), "--meta", 'tokens="42"')
        tg.ok("m1", "done", str(state["C"]))
        i = issue(state["C"])
        ready = [t["id"] for t in tg.ok("m1", "ready")]
        ok = i["state"] == "closed" and i["state_reason"] == "completed" and "tg:in-progress" not in labels_of(state["C"]) and (block_of(i["body"]) or {}).get("tokens") == "42" and state["C"] not in ready
        result("E9", "CONFIRMED" if ok else "REFUTED", f"state {i['state']}/{i['state_reason']}, labels {labels_of(state['C'])}, block {block_of(i['body'])}, in ready: {state['C'] in ready}")

    def e10():
        gh([f"repos/{REPO}/issues/{state['A']}", "-X", "PATCH", "-f", "state=closed", "-f", "state_reason=completed"])
        pause()
        done = [t["id"] for t in tg.ok("m1", "--fresh", "ls", "--status", "done")]
        result("E10", "CONFIRMED" if state["A"] in done else "REFUTED", f"done after closing A by hand: {state['A'] in done}")

    def e11():
        tg.ok("m1", "rm", str(state["G"]))
        i = issue(state["G"])
        listed = [t["id"] for t in tg.ok("m1", "ls", "--status", "open", "ready", "blocked", "done")]
        ok = i["state"] == "closed" and i["state_reason"] == "not_planned" and "tg:removed" in labels_of(state["G"]) and state["G"] not in listed
        result("E11", "CONFIRMED" if ok else "REFUTED", f"state {i['state']}/{i['state_reason']}, labels {labels_of(state['G'])}, listed: {state['G'] in listed}")

    def e12():
        tg.ok("m1", "sync", "--full")
        p = tg.run("m1", "sync", "--full", debug=True)
        assert p.returncode == 0, p.stderr
        pages = [l for l in p.stderr.splitlines() if l.startswith("gh: GET") and "/issues?labels=" in l]
        used = {re.search(r"used=(\d+)", l)[1] for l in pages}
        all304 = bool(pages) and all("-> 304" in l for l in pages)
        result("E12", "CONFIRMED" if all304 and len(used) == 1 else "REFUTED", f"{len(pages)} page probes, all 304: {all304}, x-ratelimit-used values across them: {sorted(used)} (the full pull then re-reads edges and comments, which count)")

    def e14():
        gone = [track(tg.ok("m1", "add", f"tgcheck: sweep {i}")["id"]) for i in range(1)]
        shown = tg.ok("m2", "--fresh", "show", str(gone[0]))
        result("E14", "CONFIRMED" if shown["title"] == "tgcheck: sweep 0" else "REFUTED", "a task made on machine m1 shows on machine m2 after --fresh")

    for sid, fn in (("E1", e1), ("E2", e2), ("E3", e3), ("E4", e4), ("E5", e5), ("E6", e6), ("E13", e13), ("E7", e7), ("E8", e8), ("E9", e9), ("E14", e14), ("E10", e10), ("E11", e11), ("E12", e12)):
        step(sid, fn)


def cleanup():
    # every issue this script made, plus any open "tgcheck:" issue that tg made and the script did not see (a failed step)
    mine = set(CREATED)
    try:
        for item in gh([f"repos/{REPO}/issues?labels=taskgraph&state=open&per_page=100"], check=False)[2] or []:
            if isinstance(item, dict) and item.get("title", "").startswith("tgcheck:") and "pull_request" not in item:
                mine.add(item["number"])
    except Exception as e:
        print(f"cleanup: could not list open issues: {e}", flush=True)
    closed = []
    for num in sorted(mine):
        status, _, _ = gh([f"repos/{REPO}/issues/{num}", "-X", "PATCH", "-f", "state=closed", "-f", "state_reason=not_planned"], check=False)
        if status == 200:
            closed.append(num)
        time.sleep(1.1)
    print(f"closed {len(closed)} issues: {closed}", flush=True)
    return sorted(mine), closed


def find_python(given):
    for candidate in (given, shutil.which("python3.11"), "/opt/homebrew/bin/python3.11"):
        if candidate and shutil.which(candidate):
            out = subprocess.run([candidate, "-c", "import sys; print(sys.version_info >= (3, 11))"], capture_output=True, text=True).stdout.strip()
            if out == "True":
                return candidate
    sys.exit("the E steps need Python 3.11 or later for tg (pass --python); use --only C1,...,C11 to run the capability part alone")


def main():
    global REPO, LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--only", default="", help="comma separated step ids, for example C1,C4,E1")
    ap.add_argument("--skip-bulk", action="store_true", help="leave out C6 (52 issues, about 4 minutes)")
    ap.add_argument("--log", default=str(Path(tempfile.gettempdir()) / "tg_live_check.log.jsonl"))
    ap.add_argument("--python", default=None)
    ap.add_argument("--no-cleanup", action="store_true")
    ap.add_argument("--yes", action="store_true", help="allow a repository other than the test repository")
    a = ap.parse_args()
    REPO = a.repo
    if REPO != "ronicayu/taskgraph-backend-test" and not a.yes:
        sys.exit("refusing: this script writes to the repository; pass ronicayu/taskgraph-backend-test, or --yes for another one")
    only = set(filter(None, a.only.split(",")))
    wants_e = not only or any(x.startswith("E") for x in only)
    python = find_python(a.python) if wants_e else None
    LOG = open(a.log, "a", encoding="utf-8")
    state = {}
    checks = [("C1", c1_labels), ("C2", c2_body_block), ("C3", c3_sizes), ("C4", c4_dependencies_and_updated_at),
              ("C5", c5_sub_issues), ("C6", c6_bulk_limits), ("C7", c7_claim_race), ("C8", c8_close_reasons), ("C9", c9_costs),
              ("C10", c10_page_probe_sees_edges), ("C11", c11_title_length)]
    with tempfile.TemporaryDirectory(prefix="tgcheck-") as folder:
        try:
            for cid, fn in checks:
                if only and cid not in only:
                    continue
                if cid == "C6" and a.skip_bulk:
                    continue
                try:
                    fn() if cid == "C1" else fn(state)
                except Exception as e:  # one step failing must not stop the others
                    result(cid, "ERROR", str(e)[:400])
            if wants_e:
                ensure_labels = [c1_labels] if not only or "C1" not in only else []
                for fn in ensure_labels:
                    fn()
                e_steps(Tg(python, folder), {x for x in only if x.startswith("E")}, state)
        finally:
            created, closed = ([], [])
            if not a.no_cleanup:
                created, closed = cleanup()
    bad = [r for r in RESULTS if r[1] != "PASS"]
    print(f"{len(RESULTS) - len(bad)} PASS, {len(bad)} FAIL; issues touched {created}; closed {closed}")


if __name__ == "__main__":
    main()
