from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

KEEP = object()  # an Edit field that does not change


@dataclass
class RemoteTask:
    # One task as the remote holds it now (a fresh read, or an item of a list page).
    number: int
    db_id: int
    node_id: str
    title: str
    notes: str
    meta: dict
    problems: list
    body: str
    state: str
    labels: list
    status: str
    type: str
    parent: int | None
    created_at: str
    updated_at: str
    closed_at: str | None
    removed: bool = False
    comments: int = 0
    item: dict = field(default_factory=dict)
    server_time: float | None = None  # the remote's clock when it answered


@dataclass
class SyncState:
    pages: dict = field(default_factory=dict)  # page -> {"etag", "ids", "count"}
    fingerprints: dict = field(default_factory=dict)  # task number -> {"all", "edges", "comments"}
    removed: set = field(default_factory=set)  # numbers of issues that carry the removed label
    comments_etag: str | None = None  # of the probe that finds created and edited comments


@dataclass
class Probe:
    pages: dict  # page -> items of the pages that changed (a 200 answer)
    info: dict  # page -> {"etag", "ids", "count"} of every page walked
    changed: bool = False


@dataclass
class Delta:
    tasks: list = field(default_factory=list)  # RemoteTask that changed
    fingerprints: dict = field(default_factory=dict)
    edges: dict = field(default_factory=dict)  # number -> blocker numbers, for the tasks whose edges were read
    results: dict = field(default_factory=dict)  # number -> result rows; replaces the cached rows of that task
    claims: dict = field(default_factory=dict)  # number -> claim rows; replaces the cached rows of that task
    removed: list = field(default_factory=list)  # numbers that now carry the removed label
    seen: set | None = None  # full pull: every issue number on the pages; a cached task not in it is gone
    pages: dict | None = None  # the page state to keep; None when the delta is not from a page walk
    full: bool = False


@dataclass
class Create:
    id: int  # provisional
    title: str
    notes: str
    type: str
    parent: int | None
    meta: dict  # the keys that go to the remote (write-through and deferred)


@dataclass
class Edit:
    id: int
    title: str | None = None
    notes: str | None = None
    status: str | None = None  # the status the task has now
    type: str | None = None  # the new type, when it changed
    parent: object = KEEP  # a task id, None to detach, KEEP
    meta_set: dict = field(default_factory=dict)  # write-through keys
    meta_unset: list = field(default_factory=list)
    pending: list = field(default_factory=list)  # deferred rows of this task: {"key", "op", "value", "base"}, all JSON text
    flush: bool = False  # send the pending rows even when nothing else changes


@dataclass
class Plan:
    # What one write command asks of the remote. The provisional ids of created tasks are negative.
    created: list = field(default_factory=list)
    edits: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    edges_added: list = field(default_factory=list)  # (task, depends_on)
    edges_removed: list = field(default_factory=list)
    db_ids: dict = field(default_factory=dict)  # task number -> remote database id
    labels: set = field(default_factory=set)  # label names the plan uses

    def __bool__(self):
        return bool(self.created or self.edits or self.removed or self.edges_added or self.edges_removed)


@dataclass
class Pushed:
    ids: dict = field(default_factory=dict)  # provisional id -> number
    db_ids: dict = field(default_factory=dict)  # number -> database id (created tasks)
    node_ids: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)  # number -> the shared meta the remote now holds, for the tasks whose body was read or written
    flushed: set = field(default_factory=set)  # numbers whose pending rows were consumed
    dropped: list = field(default_factory=list)  # (number, key): pending rows dropped because the remote has a newer value
    comments: dict = field(default_factory=dict)  # number -> comments the push added


@dataclass
class ClaimOutcome:
    won: bool  # False: the claim is mine from an earlier start, nothing was posted
    claimant: str
    comment_id: int | None
    created_at: str | None
    voided: list
    claims: list  # the claim rows of the last read, for the cache


class Remote(Protocol):
    def probe(self, state: SyncState) -> Probe: ...

    def comment_changes(self, state: SyncState, since: float | None) -> tuple: ...  # (task numbers with a created or edited comment, probe etag)

    def pull(self, state: SyncState, probe: Probe | None, full: bool = False, comments: bool = False, reread=()) -> Delta: ...

    def fetch(self, number: int) -> RemoteTask: ...

    def push(self, plan: Plan, fresh: dict) -> Pushed: ...

    def post_result(self, number: int, row) -> dict: ...

    def claim(self, number: int, claimant: str) -> ClaimOutcome: ...

    def ensure_setup(self, labels) -> None: ...


def canon(value):
    # How a meta value is written in pending rows and compared with what the remote holds.
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
