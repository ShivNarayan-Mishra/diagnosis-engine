from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from src.contracts.records import TraceRecord
from src.store.postgres import PostgresTraceStore


def test_write_then_query_window_roundtrip():
    store = PostgresTraceStore()

    now = datetime.now(timezone.utc)
    record = TraceRecord(
        request_id=f"test-{uuid.uuid4()}",
        timestamp=now,
        outcome="success",
        branch="rag",
        latency_ms=123.4,
        factors={"tool_version": "2.3", "retrieval_score": 0.87},
    )

    store.write(record)

    results = list(
        store.query_window(now - timedelta(seconds=1), now + timedelta(seconds=1))
    )
    matches = [r for r in results if r.request_id == record.request_id]

    assert len(matches) == 1
    fetched = matches[0]
    assert fetched.outcome == "success"
    assert fetched.branch == "rag"
    assert fetched.factors["tool_version"] == "2.3"
    assert fetched.factors["retrieval_score"] == 0.87
