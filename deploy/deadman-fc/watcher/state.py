from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ObjectStore(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, data: bytes) -> None: ...


@dataclass(frozen=True)
class State:
    last_ping: datetime
    alerted: bool


def _key(job: str) -> str:
    return f"state/{job}.json"


def put_ping(store: ObjectStore, job: str, now: datetime) -> None:
    store.put(_key(job), json.dumps({"last_ping": now.isoformat(), "alerted": False}).encode())


def read_state(store: ObjectStore, job: str) -> State | None:
    raw = store.get(_key(job))
    if raw is None:
        return None
    d = json.loads(raw)
    return State(datetime.fromisoformat(d["last_ping"]), d["alerted"])


def mark_alerted(store: ObjectStore, job: str) -> None:
    st = read_state(store, job)
    if st is None:
        return
    store.put(_key(job), json.dumps({"last_ping": st.last_ping.isoformat(), "alerted": True}).encode())
