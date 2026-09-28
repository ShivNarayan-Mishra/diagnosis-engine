"""
src/store/in_memory.py

In-memory implementation of the TraceStore ABC. Used only by the Phase 5 benchmark
runner (scripts/run_benchmark.py), not anywhere else in the project. PostgresTraceStore
remains the store for everything that touches real data.

Why this exists: FaultScenario.inject() requires a TraceStore to write to -- that's
baked into the ABC signature. Running N=20+ repetitions per scenario type through the
real PostgresTraceStore would write thousands of synthetic benchmark rows into the same
traces table used for everything else in this project, on every benchmark run. Nothing
downstream of Phase 5 needs those rows to persist -- the benchmark scores each run and
discards the data. An in-memory store avoids the write volume and the DB round-trip
entirely, and keeps repeated benchmark runs fast and side-effect-free.

See running_log_phase5.md, Entry 3, for the full reasoning.
"""
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