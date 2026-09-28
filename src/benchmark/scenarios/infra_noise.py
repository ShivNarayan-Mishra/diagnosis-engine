"""
src/benchmark/scenarios/infra_noise.py

InfraNoiseScenario -- the last scenario in Phase 6's original scope. Per
diagnosis_engine_full_plan.md: "latency_ms spikes + error_type=Timeout appears",
cause_layer="infra".

TWO REAL DESIGN DECISIONS, made deliberately, not discovered by accident:

1. latency_ms is mutated but NOT the testable signal, and NOT mirrored into
   factors. TraceRecord.latency_ms is a first-class field, not part of the open
   factor bag (see records.py) -- v1_univariate.py's diagnose() only ever scans
   factors.keys() (its own module docstring, design decision #3: "branch/
   latency_ms are first-class TraceRecord fields, not part of the open bag").
   Two consequences follow, and both were worth deciding explicitly:
     a. If latency_ms were the ONLY thing mutated, this fault would be
        architecturally invisible to the diagnosis engine -- a scenario that
        can never be diagnosed isn't a useful addition to the benchmark.
     b. Mirroring latency_ms into factors WOULD make it independently
        testable -- but then this single scenario would produce two
        simultaneously-significant real signals (error_type AND
        factors["latency_ms"]), which is functionally a confounded scenario.
        diagnosis_engine_full_plan.md explicitly cuts ConfoundedScenario from
        this project's scope (see its "What NOT to build" section). Silently
        recreating that dynamic through a side door here would contradict a
        decision already made on purpose elsewhere in the project.
   Resolution: error_type (in the factor bag) is the one clean, testable
   signal -- keeps this an isolated fault, consistent with every other Phase
   5/6 scenario. latency_ms is still mutated on the real TraceRecord field,
   for realism and manual/eyeball inspection (a real infra incident really
   would show elevated latency), but deliberately left out of factors, so it
   stays invisible to the engine rather than becoming an accidental second
   signal.

2. error_type needs an explicit baseline value, not just "absent for normal
   traces." If only the injected-fault traces ever had this key at all,
   _test_categorical's `distinct` set would contain exactly one value
   ("Timeout") and the `len(distinct) < 2` guard would make the factor
   untestable -- the same failure mode as a categorical factor that only ever
   has one real-world value. Every trace (before-window, and the unaffected
   share of after-window) gets an explicit good_value ("none", meaning no
   error occurred) -- same good_value/bad_value shape as
   ToolRegressionScenario, not a present/absent distinction.

Structural choice otherwise: same partial-rollout shape as every categorical
scenario since ToolRegressionScenario -- a bad_value_share fraction of
after-window traces get the bad error_type + elevated failure rate, the rest
stay on the baseline value + baseline rate. Same resolve-once
baseline_failure_rate pattern.

cause_layer requires pipeline_config.yaml to declare error_type -> categorical
/ infra (added alongside this file, same as taxonomy_drift.py needed an
`intent` entry).
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

from src.benchmark.generator import TraceGenerator
from src.benchmark.scenarios.base import FaultScenario
from src.contracts.interfaces import TraceStore
from src.contracts.records import GroundTruth


class InfraNoiseScenario(FaultScenario):
    def __init__(
        self,
        factor: str = "error_type",
        good_value: str = "none",
        bad_value: str = "Timeout",
        baseline_failure_rate: float | None = None,
        bad_failure_rate: float = 0.85,
        bad_value_share: float = 0.5,
        normal_latency_mean: float = 220.0,
        normal_latency_stdev: float = 40.0,
        spiked_latency_mean: float = 1500.0,
        spiked_latency_stdev: float = 300.0,
        n_before: int = 200,
        n_after: int = 200,
        interval_seconds: float = 1.0,
        seed: int = 13579,
    ):
        self.factor = factor
        self.good_value = good_value
        self.bad_value = bad_value
        self.baseline_failure_rate = baseline_failure_rate
        self.bad_failure_rate = bad_failure_rate
        self.bad_value_share = bad_value_share
        self.normal_latency_mean = normal_latency_mean
        self.normal_latency_stdev = normal_latency_stdev
        self.spiked_latency_mean = spiked_latency_mean
        self.spiked_latency_stdev = spiked_latency_stdev
        self.n_before = n_before
        self.n_after = n_after
        self.interval_seconds = interval_seconds
        self._rng = random.Random(seed)

    def inject(self, generator: TraceGenerator, store: TraceStore, at: datetime) -> GroundTruth:
        scenario_id = f"infra_noise_{uuid.uuid4().hex[:8]}"

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
            trace.latency_ms = round(self._rng.gauss(self.normal_latency_mean, self.normal_latency_stdev), 1)
            trace.outcome = "failure" if self._rng.random() < baseline_rate else "success"
            store.write(trace)

        after_traces = generator.generate(
            n=self.n_after, start_time=at, interval_seconds=self.interval_seconds
        )
        for trace in after_traces:
            if self._rng.random() < self.bad_value_share:
                trace.factors[self.factor] = self.bad_value
                trace.latency_ms = round(
                    self._rng.gauss(self.spiked_latency_mean, self.spiked_latency_stdev), 1
                )
                trace.outcome = (
                    "failure" if self._rng.random() < self.bad_failure_rate else "success"
                )
            else:
                trace.factors[self.factor] = self.good_value
                trace.latency_ms = round(self._rng.gauss(self.normal_latency_mean, self.normal_latency_stdev), 1)
                trace.outcome = "failure" if self._rng.random() < baseline_rate else "success"
            trace.injected_fault_id = scenario_id
            store.write(trace)

        return GroundTruth(
            scenario_id=scenario_id,
            fault_type="infra_noise",
            injected_at=at,
            affected_factor=self.factor,
            affected_value=self.bad_value,
        )