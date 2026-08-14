from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

from src.benchmark.generator import TraceGenerator
from src.benchmark.scenarios.base import FaultScenario
from src.contracts.interfaces import TraceStore
from src.contracts.records import GroundTruth


class ToolRegressionScenario(FaultScenario):
    """
    Simulates a bad tool_version PARTIAL rollout — e.g. a canary deploy where only some
    fraction of traffic is routed to the new tool version.

    Mechanics: calls generator.generate() to get a normal-looking batch of traces for
    each window, then mutates the returned TraceRecords directly (they're plain mutable
    dataclass instances — this is the only public surface TraceGenerator exposes, so
    this scenario doesn't depend on any generator internals).

    Before `at`: every trace forced onto `good_value` for `factor`, outcome left as
    whatever the generator's own base_failure_rate produced (i.e. untouched).

    After `at`: each trace independently has a `bad_value_share` chance of being pushed
    onto `bad_value`. Traces pushed onto `bad_value` get their outcome re-rolled at
    `bad_failure_rate`. Traces that stay on `good_value` also get re-rolled, at
    `baseline_failure_rate`, so the "after" window's baseline-value traces are on the
    same footing as the "before" window's. The fault is tied to the factor VALUE, not to
    time by itself — that's what makes it something chi-square/odds-ratio testing
    (Phase 4) can actually find.

    Uses its own seeded RNG (`seed` param), independent of the generator's, so which
    traces get pushed to bad_value and how their outcome is re-rolled is reproducible on
    its own.
    """

    def __init__(
        self,
        factor: str = "tool_version",
        good_value: str = "2.3",
        bad_value: str = "2.4",
        baseline_failure_rate: float = 0.05,
        bad_failure_rate: float = 0.30,
        bad_value_share: float = 0.5,
        n_before: int = 200,
        n_after: int = 200,
        interval_seconds: float = 1.0,
        seed: int = 1234,
    ):
        self.factor = factor
        self.good_value = good_value
        self.bad_value = bad_value
        self.baseline_failure_rate = baseline_failure_rate
        self.bad_failure_rate = bad_failure_rate
        self.bad_value_share = bad_value_share
        self.n_before = n_before
        self.n_after = n_after
        self.interval_seconds = interval_seconds
        self._rng = random.Random(seed)

    def inject(self, generator: TraceGenerator, store: TraceStore, at: datetime) -> GroundTruth:
        scenario_id = f"tool_regression_{uuid.uuid4().hex[:8]}"

        # before window — normal traces, forced onto good_value, outcome untouched
        before_start = at - timedelta(seconds=self.interval_seconds * self.n_before)
        before_traces = generator.generate(
            n=self.n_before, start_time=before_start, interval_seconds=self.interval_seconds
        )
        for trace in before_traces:
            trace.factors[self.factor] = self.good_value
            store.write(trace)

        # after window — partial rollout of bad_value, outcome re-rolled per branch
        after_traces = generator.generate(
            n=self.n_after, start_time=at, interval_seconds=self.interval_seconds
        )
        for trace in after_traces:
            if self._rng.random() < self.bad_value_share:
                trace.factors[self.factor] = self.bad_value
                trace.outcome = "failure" if self._rng.random() < self.bad_failure_rate else "success"
            else:
                trace.factors[self.factor] = self.good_value
                trace.outcome = (
                    "failure" if self._rng.random() < self.baseline_failure_rate else "success"
                )
            trace.injected_fault_id = scenario_id
            store.write(trace)

        return GroundTruth(
            scenario_id=scenario_id,
            fault_type="tool_regression",
            injected_at=at,
            affected_factor=self.factor,
            affected_value=self.bad_value,
        )
