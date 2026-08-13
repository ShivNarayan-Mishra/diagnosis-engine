from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class IngestRequest(BaseModel):
    request_id: str
    timestamp: str
    outcome: str
    branch: str | None = None
    latency_ms: float | None = None
    factors: dict[str, Any] = {}
    injected_fault_id: str | None = None
