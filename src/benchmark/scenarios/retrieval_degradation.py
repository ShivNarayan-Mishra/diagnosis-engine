"""

src/benchmark/scenarios/retrieval_degradation.py

RetrievalDegradationScenario — the first CONTINUOUS-factor fault scenario in
the project. ToolRegressionScenario and ModelSwapScenario both mutate a
categorical factor (a string swapping between fixed values); retrieval_score
is a float, so there's no single "bad_value" to swap in — instead this
mutates the SAMPLING RANGE retrieval_score is drawn from, for a share of the
after-window traces.

Structural choice: mirrors ToolRegressionScenario's partial-rollout shape
(a bad_value_share fraction of after-window traces get pushed into the
degraded range, the rest stay on the normal range), not ModelSwapScenario's
full 100% cutover. Same reasoning as the original tool_regression/model_swap
split documented in running_log_phase2.md: this looks like a real partial
retrieval-index regression or partial reranker rollout, and it forces the
diagnosis engine (specifically _test_continuous's Mann-Whitney path in
v1_univariate.py) to find the signal in a genuinely mixed population rather
than a clean before/after cutover.

baseline_failure_rate: same None-with-fallback pattern as
ToolRegressionScenario, applied here from the start rather than fixed
post-hoc (that fix's reasoning is in session_wrapup.md Sec 4 and
what_we_built_today.md Part 1 -- not repeating the mistake here, resolving
once at the top of inject() and using the same resolved rate for the
before-window and the after-window's unaffected traces).

good_range: matches the real TraceGenerator's own default retrieval_score
distribution, uniform(0.55, 0.95), confirmed directly from generator.py --
not copied from a description, read from the actual pasted file. This means
the "unaffected" population in this scenario looks statistically identical
to ordinary generated traffic, not just superficially similar.

affected_value on the returned GroundTruth: there's no single discrete value
for a continuous drift, so this is a descriptive string
("degraded_to_<low>-<high>") rather than a number. scorer.py's continuous
branch (see running_log_phase6.md Entry 1) only ever compares
ground_truth.affected_factor for continuous ground truth -- affected_value
here is informational/for evidence display only, never used in scoring.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

from src.benchmark.generator import TraceGenerator
from src.benchmark.scenarios.base import FaultScenario
from src.contracts.interfaces import TraceStore
from src.contracts.records import GroundTruth


class RetrievalDegradationScenario(FaultScenario):
    def __init__(
        self,
        factor: str = "retrieval_score",
        good_range: tuple[float, float] = (0.55, 0.95),
        bad_range: tuple[float, float] = (0.10, 0.40),
        baseline_failure_rate: float | None = None,
        bad_failure_rate: float = 0.35,
        bad_value_share: float = 0.5,
        n_before: int = 200,
        n_after: int = 200,
        interval_seconds: float = 1.0,
        seed: int = 5678,
    ):
        self.factor = factor
        self.good_range = good_range
        self.bad_range = bad_range
        self.baseline_failure_rate = baseline_failure_rate
        self.bad_failure_rate = bad_failure_rate
        self.bad_value_share = bad_value_share
        self.n_before = n_before
        self.n_after = n_after
        self.interval_seconds = interval_seconds
        self._rng = random.Random(seed)

    def inject(self, generator: TraceGenerator, store: TraceStore, at: datetime) -> GroundTruth:
        scenario_id = f"retrieval_degradation_{uuid.uuid4().hex[:8]}"

        # Resolved ONCE — same discipline as ToolRegressionScenario's fix.
        # Before-window and the after-window's unaffected traces both use
        # this single resolved number, so there's no way for them to
        # silently disagree if the caller constructed the generator with a
        # non-default base_failure_rate.
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
            # Explicitly resampled from good_range rather than left as
            # whatever the generator's own default draw produced — matches
            # ToolRegressionScenario's pattern of always setting the factor
            # explicitly, so behavior doesn't silently depend on the
            # generator's internal defaults matching this scenario's
            # good_range if someone ever changes one without the other.
            trace.factors[self.factor] = round(self._rng.uniform(*self.good_range), 3)
            trace.outcome = "failure" if self._rng.random() < baseline_rate else "success"
            store.write(trace)

        after_traces = generator.generate(
            n=self.n_after, start_time=at, interval_seconds=self.interval_seconds
        )
        for trace in after_traces:
            if self._rng.random() < self.bad_value_share:
                trace.factors[self.factor] = round(self._rng.uniform(*self.bad_range), 3)
                trace.outcome = (
                    "failure" if self._rng.random() < self.bad_failure_rate else "success"
                )
            else:
                trace.factors[self.factor] = round(self._rng.uniform(*self.good_range), 3)
                trace.outcome = "failure" if self._rng.random() < baseline_rate else "success"
            trace.injected_fault_id = scenario_id
            store.write(trace)

        return GroundTruth(
            scenario_id=scenario_id,
            fault_type="retrieval_degradation",
            injected_at=at,
            affected_factor=self.factor,
            affected_value=f"degraded_to_{self.bad_range[0]}-{self.bad_range[1]}",
        )