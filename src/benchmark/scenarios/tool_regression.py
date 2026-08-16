from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

from src.benchmark.generator import TraceGenerator
from src.benchmark.scenarios.base import FaultScenario
from src.contracts.interfaces import TraceStore
from src.contracts.records import GroundTruth


class ToolRegressionScenario(FaultScenario):
    def __init__(
        self,
        factor: str = "tool_version",
        good_value: str = "2.3",
        bad_value: str = "2.4",
        baseline_failure_rate: float | None = None,
        bad_failure_rate: float = 0.30,
        bad_value_share: float = 0.5,
        n_before: int = 200,
        n_after: int = 200,
        interval_seconds: float = 1.0,
        seed: int = 1234,
    ):
        """
        baseline_failure_rate: rate used for the "unaffected" population — the whole
        before-window, and the after-window traces that stay on good_value. Defaults to
        None, meaning "match whatever generator.base_failure_rate is" at inject() time.
        Pass an explicit value only when you deliberately want this scenario's baseline
        to differ from the generator's own default — e.g. a benchmark sweep that varies
        baseline noise while reusing one shared generator instance. See the running log
        (Entry 10) for why this exists as an explicit, resolvable override rather than
        being silently derived from generator.base_failure_rate.
        """
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

        # Resolve the baseline rate ONCE, so the before-window and the after-window's
        # unaffected traces are guaranteed to use the same number — no silent mismatch
        # if the caller constructed the generator with a non-default base_failure_rate.
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
            # Re-rolled at baseline_rate rather than left as whatever the generator's own
            # draw happened to be — that's what made the old version silently inconsistent
            # whenever baseline_failure_rate was overridden away from the generator's rate.
            trace.outcome = "failure" if self._rng.random() < baseline_rate else "success"
            store.write(trace)

        after_traces = generator.generate(
            n=self.n_after, start_time=at, interval_seconds=self.interval_seconds
        )
        for trace in after_traces:
            if self._rng.random() < self.bad_value_share:
                trace.factors[self.factor] = self.bad_value
                trace.outcome = "failure" if self._rng.random() < self.bad_failure_rate else "success"
            else:
                trace.factors[self.factor] = self.good_value
                trace.outcome = "failure" if self._rng.random() < baseline_rate else "success"
            trace.injected_fault_id = scenario_id
            store.write(trace)

        return GroundTruth(
            scenario_id=scenario_id,
            fault_type="tool_regression",
            injected_at=at,
            affected_factor=self.factor,
            affected_value=self.bad_value,
        )