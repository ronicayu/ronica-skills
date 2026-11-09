from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Protocol


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StoreError(Exception):
    # tg.py prints it as "error: <message>" and exits 1, like Fail
    pass


class RemoteError(StoreError):
    # the remote refused or failed; `applied` and `not_applied` say what it did and did not take
    def __init__(self, message, applied=(), not_applied=()):
        super().__init__(message)
        self.applied = tuple(applied)
        self.not_applied = tuple(not_applied)


class RateLimited(RemoteError):
    def __init__(self, message, reset_at, applied=(), not_applied=()):
        super().__init__(message, applied, not_applied)
        self.reset_at = reset_at  # UTC ISO time; tg prints when to try again


class ClaimLost(StoreError):
    def __init__(self, message, winner, winner_comment_id):
        super().__init__(message)
        self.winner = winner
        self.winner_comment_id = winner_comment_id


@dataclass(frozen=True)
class Capabilities:
    cross_project_deps: bool  # SQLite True, GitHub False
    claim: bool  # SQLite False (start never refuses), GitHub True
    history: str  # "full" (SQLite) or "cache" (from the first pull on this machine)
    baselines: str  # "local" for both in v1
    soft_delete: bool  # GitHub True: rm closes the issue, it does not delete it
    max_blockers: int | None  # GitHub 50, SQLite None
    max_depth: int | None  # GitHub 8 issues in a parent chain, SQLite None
    max_children: int | None  # GitHub 100, SQLite None


@dataclass(frozen=True)
class ResultInput:
    status: str
    kind: str
    attempt: int | None
    author: str | None
    body: str


class Store(Protocol):
    name: str  # "sqlite" or "github"
    caps: Capabilities

    def connect(self, *, fresh: bool = False, mode: str = "read") -> sqlite3.Connection: ...  # mode: "read", "write" (always refresh) or "none"

    @contextmanager
    def write(self, conn: sqlite3.Connection, *, journal: bool = True) -> Iterator[None]: ...

    def new_id(self, conn) -> int: ...

    def resolve_id(self, provisional: int) -> int: ...

    def add_result(self, conn, task_id: int, row: ResultInput) -> dict: ...

    def claim(self, conn, task_id: int) -> None: ...

    def claimant_of(self, conn, task_id: int) -> str | None: ...  # who holds an in-progress task (GitHub); None for the local store

    def sync(self, *, full: bool = False) -> dict: ...

    def version(self, conn) -> int | str: ...

    def path(self) -> str: ...  # for serve: identity of the data
