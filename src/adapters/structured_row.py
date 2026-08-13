"""
StructuredRowAdapter — the trivial case. Input JSON already matches the
TraceRecord shape almost exactly, so normalize() just maps field names across.
Exists as a real adapter (not a special case in the router) so that when a
messier adapter (StackTraceAdapter, InfraLogAdapter) shows up later, this one
doesn't need special-casing either — they're all equal citizens.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from src.contracts.interfaces import IngestAdapter
from src.contracts.records import TraceRecord


class StructuredRowAdapter(IngestAdapter):
    def can_handle(self, raw: Any) -> bool:
        # Handles any dict that already has the mandatory TraceRecord fields.
        return (
            isinstance(raw, dict)
            and "request_id" in raw
            and "timestamp" in raw
            and "outcome" in raw
        )

    def normalize(self, raw: Any) -> TraceRecord:
        timestamp = raw["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        return TraceRecord(
            request_id=raw["request_id"],
            timestamp=timestamp,
            outcome=raw["outcome"],
            branch=raw.get("branch"),
            latency_ms=raw.get("latency_ms"),
            factors=raw.get("factors", {}),
            injected_fault_id=raw.get("injected_fault_id"),
        )
