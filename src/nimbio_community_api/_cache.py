"""The client-side ETag store behind transparent conditional GETs.

The Nimbio API is built for polling, and most of its GETs answer a repeated
read with ``304 Not Modified`` when nothing changed — which costs no bandwidth
*and refunds the caller's monthly quota*. This module holds the small amount of
state that lets the transport take that deal automatically.

Three properties are deliberate and worth keeping:

**Opportunistic, not a route list.** Nothing here knows which paths are
cacheable. If a GET response carries an ``ETag`` we keep it; if it does not, we
keep nothing. The client therefore configures itself from what the server
actually sends and cannot drift out of date when the API adds or drops a
conditional route.

**Never a substitute for asking.** ``Cache-Control``/``max-age`` is ignored
entirely; a stored entry is only ever an ``If-None-Match`` value plus the body
to reuse *if the server says 304*. Two consequences fall out of that, and
together they are what make caching safe to leave on by default: the cache can
never serve stale data, and no write-invalidation is needed — a POST/PATCH/
DELETE cannot strand a stale entry, because the next read revalidates anyway.

**One tenant per cache.** The cache is owned by a client instance, and a client
holds exactly one API key for its whole life. That satisfies the API's
``Vary: Authorization`` requirement structurally rather than by convention:
there is no code path by which one key's entry can be read under another key.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from ._sse import STREAM_PATH

# An unbounded cache on a long-lived polling client is a slow memory leak, so
# the store is an LRU with a bound. 256 comfortably covers a dashboard polling
# every read it has, including paged logs.
DEFAULT_CACHE_SIZE = 256

# Never cached, whatever the response looks like. The event stream is an
# unbounded SSE body the API explicitly excludes from conditional handling;
# opportunistic storage would skip it anyway (it carries no ETag), but relying
# on that would make a server-side change to the stream's headers our problem.
UNCACHEABLE_PATHS = frozenset({STREAM_PATH})


@dataclass(frozen=True)
class CacheStats:
    """A snapshot of one client's conditional-request cache.

    ``hits`` counts responses the server answered ``304 Not Modified`` — each
    one is a refunded monthly-quota unit. ``misses`` counts every other
    response to a cacheable GET, so ``hits + misses`` is the number of reads
    that went through the cache at all. ``entries`` is how many bodies are
    currently stored (never more than the client's ``cache_size``).
    """

    hits: int
    misses: int
    entries: int


def cache_key(method: str, path: str,
              params: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The cache key for a request, or ``None`` if it must not be cached.

    Keyed on method + path + normalised query params. The API key is
    deliberately *not* part of the key — see the module docstring on tenancy.
    """
    if method.upper() != "GET":
        return None
    if path in UNCACHEABLE_PATHS:
        return None
    if not params:
        return f"GET {path}"
    # Sorted so two callers passing the same params in a different order share
    # one entry rather than fighting over two.
    query = "&".join(f"{k}={v}" for k, v in
                     sorted((str(k), str(v)) for k, v in params.items()))
    return f"GET {path}?{query}"


class ETagCache:
    """A bounded, thread-safe LRU of ``(etag, response body)`` by cache key.

    Bodies are stored as the raw response **bytes**, not as decoded objects.
    That is what lets a 304 be re-decoded and re-parsed from scratch on every
    hit, so no two callers are ever handed the same object graph — a caller
    who mutates a result (or the ``.raw`` payload hanging off it) cannot
    corrupt anybody else's later read.

    The lock is a plain :class:`threading.Lock` held only for dict operations,
    never across I/O. It guards the sync client shared between threads and the
    async client with many in-flight tasks equally.
    """

    def __init__(self, max_entries: int = DEFAULT_CACHE_SIZE) -> None:
        self.max_entries = max(1, int(max_entries))
        self._entries: "OrderedDict[str, Tuple[str, bytes]]" = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def etag_for(self, key: str) -> Optional[str]:
        """The ``If-None-Match`` value to send, if we hold one."""
        with self._lock:
            entry = self._entries.get(key)
            return entry[0] if entry is not None else None

    def store(self, key: str, etag: str, body: bytes) -> None:
        with self._lock:
            self._entries[key] = (etag, body)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def discard(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def hit(self, key: str, etag: Optional[str] = None) -> Optional[bytes]:
        """Record a 304 and return the body to replay, or ``None``.

        ``None`` means the entry was evicted between sending the conditional
        header and the 304 arriving; the caller must then re-ask
        unconditionally, because it has nothing to return.

        A 304 may restate the ``ETag``; if it names a different one, adopt it.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if etag and etag != entry[0]:
                entry = (etag, entry[1])
                self._entries[key] = entry
            self._entries.move_to_end(key)
            self._hits += 1
            return entry[1]

    def record_miss(self) -> None:
        with self._lock:
            self._misses += 1

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(hits=self._hits, misses=self._misses,
                              entries=len(self._entries))
