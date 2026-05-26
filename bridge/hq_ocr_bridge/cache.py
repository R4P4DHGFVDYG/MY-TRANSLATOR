from __future__ import annotations

from collections import OrderedDict
import time
from typing import Hashable


class TTLCache:
    def __init__(self, capacity: int = 80, ttl_seconds: int = 600) -> None:
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self._items: OrderedDict[Hashable, tuple[float, object]] = OrderedDict()

    def get(self, key: Hashable) -> object | None:
        self._prune()
        item = self._items.get(key)
        if item is None:
            return None

        created_at, value = item
        if created_at < time.monotonic() - self.ttl_seconds:
            self._items.pop(key, None)
            return None

        self._items.move_to_end(key)
        return value

    def set(self, key: Hashable, value: object) -> None:
        self._prune()
        self._items[key] = (time.monotonic(), value)
        self._items.move_to_end(key)

        while len(self._items) > self.capacity:
            self._items.popitem(last=False)

    def _prune(self) -> None:
        expired_before = time.monotonic() - self.ttl_seconds
        expired = [
            key for key, (created_at, _value) in self._items.items() if created_at < expired_before
        ]
        for key in expired:
            self._items.pop(key, None)
