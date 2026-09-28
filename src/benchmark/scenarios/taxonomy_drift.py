"""
src/benchmark/scenarios/taxonomy_drift.py

TaxonomyDriftScenario -- the third categorical-factor fault scenario (after
ToolRegressionScenario, ModelSwapScenario), and the one that specifically tests
"drift to an unseen category" rather than "swap between two already-known
values." Per diagnosis_engine_full_plan.md's original framing: TaxonomyDriftScenario
"introduces unknown/unseen values" for `intent` -- distinct from
ToolRegressionScenario's tool_version 2.3->2.4 swap, where both values already
exist in the generator's known set. Here, the after-window's degraded population
gets an intent value ("unrecognized_request") that NEVER appears in the
generator's own INTENTS list (check_refund, check_order_status,
general_question) -- simulating a real taxonomy drift: users asking about
something the system's intent classifier was never built to recognize.

Structural choice: partial rollout, same shape as ToolRegressionScenario and
RetrievalDegradationScenario (a bad_value_share fraction of after-window traces
get the drifted value, the rest stay on the normal known-intent distribution),
not a full cutover -- closer to how a real taxonomy drift actually looks (a
growing fraction of traffic asking about something new, not every request
switching simultaneously), and it forces the diagnosis engine to find the signal
in a genuinely mixed population.

baseline_failure_rate: same None-with-fallback resolve-once pattern used by
every scenario since RetrievalDegradationScenario -- applied from the start
here, not a post-hoc fix.

cause_layer requires pipeline_config.yaml to declare intent -> categorical /
taxonomy (see running_log_phase6.md Entry 12/13 -- the existing
pipeline_config.yaml had no intent entry at all before this scenario was built;
updated alongside this file). Without that config entry, this scenario's
correctly-detected diagnoses would still work, but cause_layer would report
"unknown" instead of "taxonomy".
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

from src.benchmark.generator import INTENTS, TraceGenerator
from src.benchmark.scenarios.base import FaultScenario
from src.contracts.interfaces import TraceStore
from src.contracts.records import GroundTruth


class TaxonomyDriftScenario(FaultScenario):
    def __init__(
        self,
        factor: str = "intent",
        drifted_value: str = "unrecognized_request",
        baseline_failure_rate: float | None = None,
        bad_failure_rate: float = 0.30,
        bad_value_share: float = 0.5,
        n_before: int = 200,
        n_after: int = 200,
        interval_seconds: float = 1.0,
        seed: int = 24680,
    ):
        self.factor = factor
        self.drifted_value = drifted_value
        self.baseline_failure_rate = baseline_failure_rate
        self.bad_failure_rate = bad_failure_rate
        self.bad_value_share = bad_value_share
        self.n_before = n_before
        self.n_after = n_after
        self.interval_seconds = interval_seconds
        self._rng = random.Random(seed)

    def inject(self, generator: TraceGenerator, store: TraceStore, at: datetime) -> GroundTruth:
        scenario_id = f"taxonomy_drift_{uuid.uuid4().hex[:8]}"

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
            # Explicitly redrawn from the known-intent set -- same
            # explicitness convention every other scenario follows, even
            # though the generator's own default draw already lands here.
            # Keeps behavior from silently depending on the generator's
            # INTENTS list matching this scenario's notion of "known" if
            # either ever changes independently of the other.
            trace.factors[self.factor] = self._rng.choice(INTENTS)
            trace.outcome = "failure" if self._rng.random() < baseline_rate else "success"
            store.write(trace)

        after_traces = generator.generate(
            n=self.n_after, start_time=at, interval_seconds=self.interval_seconds
        )
        for trace in after_traces:
            if self._rng.random() < self.bad_value_share:
                trace.factors[self.factor] = self.drifted_value
                trace.outcome = (
                    "failure" if self._rng.random() < self.bad_failure_rate else "success"
                )
            else:
                trace.factors[self.factor] = self._rng.choice(INTENTS)
                trace.outcome = "failure" if self._rng.random() < baseline_rate else "success"
            trace.injected_fault_id = scenario_id
            store.write(trace)

        return GroundTruth(
            scenario_id=scenario_id,
            fault_type="taxonomy_drift",
            injected_at=at,
            affected_factor=self.factor,
            affected_value=self.drifted_value,
        )