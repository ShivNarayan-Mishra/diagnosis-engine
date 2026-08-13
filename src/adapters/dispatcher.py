"""
AdapterDispatcher — the router in front of every IngestAdapter.

Adding a new input shape later (OTEL spans, a raw stack trace string) means:
write a new IngestAdapter subclass, register it here. Nothing else in the
project ever needs to change.
"""
from __future__ import annotations

from typing import Any

from src.contracts.interfaces import IngestAdapter
from src.contracts.records import TraceRecord


class AdapterDispatcher:
    def __init__(self, adapters: list[IngestAdapter]) -> None:
        self._adapters = adapters

    def normalize(self, raw: Any) -> TraceRecord:
        for adapter in self._adapters:
            if adapter.can_handle(raw):
                return adapter.normalize(raw)
        raise ValueError(
            f"No registered adapter could handle input of type {type(raw)}: {raw!r}"
        )
