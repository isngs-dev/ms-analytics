"""Answers of the read-only analytics endpoints, kept until the data behind them changes.

The dashboard fires a dozen heavy aggregate queries on every page, and the same filters are asked for again and
again (each viewer, each hover, every 20 seconds when the sync chip refreshes). A cached answer is exactly what the
queries would return as long as nothing was written to the tables they read, so the cache is emptied on every commit
that wrote to one of those tables (forms, escalations, people, projects, status map ...). The sync writes constantly
while it runs and rarely when nothing changed in Drive, so the dashboard is quick whenever Drive is quiet.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from datetime import date
from functools import wraps
from typing import Any, Callable

from sqlalchemy import event
from sqlalchemy.engine import Engine

MAX_ENTRIES = 400
# tables whose content the analytics read; writes to any other table (sync log, issues, settings...) keep the cache
WATCHED = ("forms", "rework", "escalations", "dim_client", "dim_project", "dim_person", "dim_error_category",
           "status_map", "client_alias", "person_alias", "src_file", "src_sheet")

_lock = threading.Lock()
_store: "OrderedDict[tuple, Any]" = OrderedDict()
SYNC_TTL = 60.0  # while a sync is writing, an answer is trusted for this many seconds instead of being thrown away at every write
_local = threading.local()
_syncing = 0
_sync_wrote = False
_dirty: set[int] = set()  # connections that wrote to a watched table and have not committed yet
hits = misses = 0


def begin_sync() -> None:
    """Called by the sync thread: its writes no longer empty the cache one by one (see SYNC_TTL)."""
    global _syncing, _sync_wrote
    _local.in_sync = True
    with _lock:
        _syncing += 1
        _sync_wrote = False


def end_sync() -> None:
    global _syncing
    _local.in_sync = False
    with _lock:
        _syncing = max(0, _syncing - 1)
        wrote = _sync_wrote
    if wrote:
        clear()  # one clean cut when a sync that changed data is over, so the finished data shows at once


def clear() -> None:
    with _lock:
        _store.clear()


def _freeze(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return tuple(_freeze(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _freeze(x)) for k, x in v.items()))
    return v


def cached(name: str) -> Callable:
    """Cache an endpoint by its arguments (the database session is not part of the key)."""
    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            global hits, misses
            # the date is part of the key: running weeks / months and "last 30 days" move with the calendar
            key = (name, date.today(), _freeze(args), _freeze({k: v for k, v in kwargs.items() if k != "db"}))
            try:
                hash(key)
            except TypeError:
                return fn(*args, **kwargs)
            with _lock:
                if key in _store:
                    stored_at, value = _store[key]
                    if not _syncing or time.monotonic() - stored_at < SYNC_TTL:
                        _store.move_to_end(key)
                        hits += 1
                        return value
            misses += 1
            value = fn(*args, **kwargs)
            with _lock:
                _store[key] = (time.monotonic(), value)
                while len(_store) > MAX_ENTRIES:
                    _store.popitem(last=False)
            return value
        return wrapper
    return deco


_WRITE = ("insert", "update", "delete")


@event.listens_for(Engine, "after_cursor_execute")
def _note_write(conn, cursor, statement, parameters, context, executemany):
    head = statement.lstrip()[:40].lower()
    if head.startswith(_WRITE) and any(f" {t} " in f" {head.replace('(', ' ').replace('\"', '')} " for t in WATCHED):
        if getattr(_local, "in_sync", False):
            global _sync_wrote
            _sync_wrote = True
            return  # the sync clears everything once, when it ends
        _dirty.add(id(conn.connection))
        clear()  # readers must not keep an answer that is already out of date


@event.listens_for(Engine, "commit")
def _after_commit(conn):
    if id(conn.connection) in _dirty:
        _dirty.discard(id(conn.connection))
        clear()  # a reader may have cached the old data between the write and the commit


@event.listens_for(Engine, "rollback")
def _after_rollback(conn):
    _dirty.discard(id(conn.connection))
