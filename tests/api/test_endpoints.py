from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone


def test_ingest_returns_ok(client):
    now = datetime.now(timezone.utc)
    payload = {
        "request_id": f"test-{uuid.uuid4()}",
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "outcome": "success",
        "branch": "rag",
        "factors": {"tool_version": "2.3", "retrieval_score": 0.87},
    }

    response = client.post("/ingest", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ingested_trace_appears_in_diagnose_window(client):
    now = datetime.now(timezone.utc)
    payload = {
        "request_id": f"test-{uuid.uuid4()}",
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "outcome": "failure",
        "branch": "rag",
        "factors": {"tool_version": "2.4"},
    }
    client.post("/ingest", json=payload)

    start = (now - timedelta(seconds=5)).isoformat()
    end = (now + timedelta(seconds=5)).isoformat()
    response = client.get(
        "/diagnose", params={"start": start, "end": end, "branch": "rag"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trace_count"] >= 1
    assert body["hypotheses"] == []
