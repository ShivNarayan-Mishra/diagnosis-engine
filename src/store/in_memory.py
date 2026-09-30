
from __future__ import annotations

from src.contracts.interfaces import TraceStore
from src.contracts.records import TraceRecord


class InMemoryTraceStore(TraceStore):
    def __init__(self) -> None:
        self._traces: list[TraceRecord] = []

    def write(self, trace: TraceRecord) -> None:
        self._traces.append(trace)

    def query_window(self, start, end, branch: str | None = None) -> list[TraceRecord]:
        return [
            t
            for t in self._traces
            if start <= t.timestamp <= end and (branch is None or t.branch == branch)
        ]