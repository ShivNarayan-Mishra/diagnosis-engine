"""
src/benchmark/scenarios/null.py

NullScenario -- injects nothing. Same generator, same resolved baseline failure
rate, applied identically to both the before-window and after-window traces, no
factor mutation anywhere. This is not a placeholder or degenerate scenario -- it
exists specifically to measure the diagnosis pipeline's FALSE-POSITIVE rate: how
often the engine claims a cause exists when nothing was actually wrong. Both
mentor_guide.md and diagnosis_engine_full_plan.md call this the headline number to
lead with in interviews, ahead of any accuracy number on real faults -- a system
that fires false alarms is worse than no system at all.

GroundTruth sentinel convention (see running_log_phase6.md Entry 9 for the full
back-and-forth): affected_factor and affected_value are both set to the
module-level NO_FAULT_INJECTED sentinel ("no_fault_injected"), deliberately NOT
"none" or "unknown". This states a known, positive fact -- nothing was injected,
by design -- not an absence of information or a fetch failure. Conflating those
two ideas would make a genuine data problem (e.g. a broken real-data replay in a
later phase) indistinguishable from a deliberate null scenario in stored
GroundTruth records. fault_type="null" is the actual scenario-type marker
scorer.py and run_benchmark.py key off of; the sentinel values only exist because
GroundTruth's fields are required strings with no None-friendly variant.

No changes needed to scorer.py for this -- confirmed by tracing both of its
branches by hand: "no_fault_injected" never matches any real factor name the
generator or pipeline_config.yaml can ever produce, so a false-positive hypothesis
can never accidentally score as top1_correct against this sentinel.

After-window traces ARE still tagged with injected_fault_id = scenario_id, even
though nothing was mutated -- this labels "these are the after-window traces from
this benchmark run" for manual inspection later (e.g. run_diagnosis_check.py's
--fault-id mode against real Postgres data), without implying anything was
actually injected. before-window traces stay untagged, same convention every
other scenario already uses.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

from src.benchmark.generator import TraceGenerator
from src.benchmark.scenarios.base import FaultScenario
from src.contracts.interfaces import TraceStore
from src.contracts.records import GroundTruth

NO_FAULT_INJECTED = "no_fault_injected"


class NullScenario(FaultScenario):
    def __init__(
        self,
        baseline_failure_rate: float | None = None,
        n_before: int = 200,
        n_after: int = 200,
        interval_seconds: float = 1.0,
        seed: int = 9999,
    ):
        self.baseline_failure_rate = baseline_failure_rate
        self.n_before = n_before
        self.n_after = n_after
        self.interval_seconds = interval_seconds
        self._rng = random.Random(seed)

    def inject(self, generator: TraceGenerator, store: TraceStore, at: datetime) -> GroundTruth:
        scenario_id = f"null_{uuid.uuid4().hex[:8]}"

        # Same resolve-once pattern as every other scenario, for consistency and
        # to support an explicit override in a future benchmark sweep -- even
        # though under default settings this re-roll doesn't change anything
        # statistically versus leaving the generator's own draw untouched, since
        # baseline_rate defaults to generator.base_failure_rate anyway.
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
            # No factor mutation at all -- factors stay exactly whatever the
            # generator's own random draw produced. Only outcome is re-rolled,
            # and only to honor an explicit baseline_failure_rate override.
            trace.outcome = "failure" if self._rng.random() < baseline_rate else "success"
            store.write(trace)

        after_traces = generator.generate(
            n=self.n_after, start_time=at, interval_seconds=self.interval_seconds
        )
        for trace in after_traces:
            trace.outcome = "failure" if self._rng.random() < baseline_rate else "success"
            trace.injected_fault_id = scenario_id
            store.write(trace)

        return GroundTruth(
            scenario_id=scenario_id,
            fault_type="null",
            injected_at=at,
            affected_factor=NO_FAULT_INJECTED,
            affected_value=NO_FAULT_INJECTED,
        )