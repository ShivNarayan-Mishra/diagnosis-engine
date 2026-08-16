from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

from src.benchmark.generator import TraceGenerator
from src.benchmark.scenarios.base import FaultScenario
from src.contracts.interfaces import TraceStore
from src.contracts.records import GroundTruth


class ModelSwapScenario(FaultScenario):
    def __init__(
        self,
        factor: str = "model_version",
        good_value: str = "v2",
        bad_value: str = "v3",
        baseline_failure_rate: float | None = None,
        bad_failure_rate: float = 0.22,
        n_before: int = 200,
        n_after: int = 200,
        interval_seconds: float = 1.0,
        seed: int = 5678,
    ):
        """
        baseline_failure_rate: rate used for the before-window (there's no "unaffected
        after-window" population here, since this scenario is a 100% cutover — every
        after-trace switches). Defaults to None, meaning "match whatever
        generator.base_failure_rate is" at inject() time. Previously this parameter was
        accepted but never actually used in inject() — a dead parameter that silently
        did nothing if you passed it. Now wired in. See running log Entry 10.
        """
        self.factor = factor
        self.good_value = good_value
        self.bad_value = bad_value
        self.baseline_failure_rate = baseline_failure_rate
        self.bad_failure_rate = bad_failure_rate
        self.n_before = n_before
        self.n_after = n_after
        self.interval_seconds = interval_seconds
        self._rng = random.Random(seed)

    def inject(self, generator: TraceGenerator, store: TraceStore, at: datetime) -> GroundTruth:
        scenario_id = f"model_swap_{uuid.uuid4().hex[:8]}"

        baseline_rate = (
            self.baseline_failure_rate
            if self.baseline_failure_rate is not None
            else generator.base_failure_rate
        )

        before_start = at - timedelta(seconds=self.interval_seconds * self.n_before)
        before_traces = generator.generate(
            n=self.n_before, start_time=before_start, interval_seconds=self.interval_seconds
        )
        for trace in before_traces:
            trace.factors[self.factor] = self.good_value
            trace.outcome = "failure" if self._rng.random() < baseline_rate else "success"
            store.write(trace)

        after_traces = generator.generate(
            n=self.n_after, start_time=at, interval_seconds=self.interval_seconds
        )
        for trace in after_traces:
            trace.factors[self.factor] = self.bad_value
            trace.outcome = "failure" if self._rng.random() < self.bad_failure_rate else "success"
            trace.injected_fault_id = scenario_id
            store.write(trace)

        return GroundTruth(
            scenario_id=scenario_id,
            fault_type="model_swap",
            injected_at=at,
            affected_factor=self.factor,
            affected_value=self.bad_value,
        )