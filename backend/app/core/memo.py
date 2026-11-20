"""A small thread-safe, size- and age-bounded in-process cache (Milestone 7).

For derived, non-personal data that is expensive to compute and identical for every user, such
as a genre's ranked tracks under a published popularity version. Keys must include the model
versions the value depends on; the age bound covers catalogue changes that do not publish a new
version. Each process has its own copy; nothing personal may be stored here.
"""

import threading
import time
from collections import OrderedDict
from collections.abc import Hashable
from typing import Generic, TypeVar

from app.core import metrics

V = TypeVar("V")


class TimedCache(Generic[V]):
    def __init__(self, name: str, size: int, ttl_seconds: float) -> None:
        self.name = name
        self.size = size
        self.ttl = ttl_seconds
        self._items: OrderedDict[Hashable, tuple[float, V]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> V | None:
        now = time.monotonic()
        with self._lock:
            entry = self._items.get(key)
            if entry is not None and now - entry[0] > self.ttl:
                del self._items[key]
                entry = None
            if entry is not None:
                self._items.move_to_end(key)
        metrics.cache_lookup(self.name, hit=entry is not None)
        return None if entry is None else entry[1]

    def put(self, key: Hashable, value: V) -> None:
        with self._lock:
            self._items[key] = (time.monotonic(), value)
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
