"""
TraceGenerator — Phase 1 version. Emits believable NORMAL traffic only.
No fault injection here yet (that's Phase 2's ToolRegressionScenario etc,
which will wrap/mutate what this generator produces).

Always seed it. Reproducibility matters more than "real" randomness here —
you want to be able to re-run the exact same synthetic scenario later.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from src.contracts.records import TraceRecord

BRANCHES = ["rag", "direct", "infra"]
TOOL_VERSIONS = ["2.3"]
MODEL_VERSIONS = ["v2"]
INTENTS = ["check_refund", "check_order_status", "general_question"]


class TraceGenerator:
    def __init__(self, seed: int = 42, base_failure_rate: float = 0.05) -> None:
        self._rng = random.Random(seed)
        self.base_failure_rate = base_failure_rate

    def generate(
        self, n: int, start_time: datetime | None = None, interval_seconds: float = 1.0
    ) -> list[TraceRecord]:
        start_time = start_time or datetime.now(timezone.utc)
        traces = []
        for i in range(n):
            failed = self._rng.random() < self.base_failure_rate
            traces.append(
                TraceRecord(
                    request_id=str(uuid.uuid4()),
                    timestamp=start_time + timedelta(seconds=i * interval_seconds),
                    outcome="failure" if failed else "success",
                    branch=self._rng.choice(BRANCHES),
                    latency_ms=round(self._rng.gauss(220, 40), 1),
                    factors={
                        "tool_version": self._rng.choice(TOOL_VERSIONS),
                        "model_version": self._rng.choice(MODEL_VERSIONS),
                        "retrieval_score": round(self._rng.uniform(0.55, 0.95), 3),
                        "intent": self._rng.choice(INTENTS),
                    },
                )
            )
        return traces
