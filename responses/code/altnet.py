"""Alternative internet written by the Lumen coding agent.

No DNS. A name is the hash of the bytes. Nodes keep a store and a neighbor list.
A get walks neighbors until the hash is found or the hop budget runs out.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def name_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


@dataclass
class Node:
    node_id: str
    store: dict[str, bytes] = field(default_factory=dict)
    neighbors: list[Node] = field(default_factory=list)

    def publish(self, payload: bytes) -> str:
        key = name_of(payload)
        self.store[key] = payload
        return key

    def get(self, key: str, hops: int = 4, seen: set[str] | None = None) -> bytes | None:
        seen = seen if seen is not None else set()
        if self.node_id in seen or hops < 0:
            return None
        seen.add(self.node_id)
        if key in self.store:
            return self.store[key]
        for peer in self.neighbors:
            found = peer.get(key, hops - 1, seen)
            if found is not None:
                self.store[key] = found
                return found
        return None


def demo() -> str:
    a, b, c = Node("a"), Node("b"), Node("c")
    a.neighbors = [b]
    b.neighbors = [a, c]
    c.neighbors = [b]
    key = c.publish(b"hello from the other net")
    got = a.get(key)
    return got.decode() if got else "miss"
