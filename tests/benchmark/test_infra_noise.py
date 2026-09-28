"""
tests/benchmark/test_infra_noise.py

Standalone test file, same reasoning as test_null_scenario.py and
test_taxonomy_drift.py (running_log_phase6.md Entry 10/13): the real
tests/benchmark/test_scenarios.py content hasn't been pasted into this chat,
so this isn't merged into it blind.

Uses InMemoryTraceStore from the start, not PostgresTraceStore -- per the real
bug found and fixed in Entry 14 (cross-test contamination against the shared,
persistent real table when querying untagged before-window traces by raw
timestamp), there's no reason to repeat that mistake in a brand-new file.
"""
from datetime import datetime, timedelta, timezone

from src.benchmark.generator import TraceGenerator
from src.benchmark.scenarios.infra_noise import InfraNoiseScenario
from src.store.in_memory import InMemoryTraceStore


def test_infra_noise_injects_and_logs_ground_truth():
    generator = TraceGenerator(seed=468)
    store = InMemoryTraceStore()
    scenario = InfraNoiseScenario(n_before=20, n_after=20)

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    assert gt.fault_type == "infra_noise"
    assert gt.affected_factor == "error_type"
    assert gt.affected_value == "Timeout"


def test_infra_noise_before_window_has_baseline_error_type_only():
    generator = TraceGenerator(seed=579)
    store = InMemoryTraceStore()
    scenario = InfraNoiseScenario(n_before=20, n_after=20)

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    before_start = at - timedelta(seconds=scenario.interval_seconds * scenario.n_before)
    after_end = at + timedelta(seconds=scenario.interval_seconds * scenario.n_after)
    window = list(store.query_window(before_start, after_end))
    before = [t for t in window if t.timestamp < at]

    assert len(before) == scenario.n_before
    assert all(t.factors.get("error_type") == "none" for t in before)


def test_infra_noise_latency_ms_not_mirrored_into_factors():
    """
    The core architectural decision this scenario was built around (see
    infra_noise.py's module docstring): latency_ms is mutated on the
    TraceRecord's top-level field for realism, but deliberately never copied
    into `factors` -- doing so would make it independently testable by
    v1_univariate.py, turning this into a confounded scenario (two real,
    simultaneously-significant signals), which diagnosis_engine_full_plan.md
    explicitly cuts from this project's scope.
    """
    generator = TraceGenerator(seed=680)
    store = InMemoryTraceStore()
    scenario = InfraNoiseScenario(n_before=20, n_after=20)

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    before_start = at - timedelta(seconds=scenario.interval_seconds * scenario.n_before)
    after_end = at + timedelta(seconds=scenario.interval_seconds * scenario.n_after)
    window = list(store.query_window(before_start, after_end))

    assert all("latency_ms" not in t.factors for t in window)
    assert all(t.latency_ms is not None for t in window)


def test_infra_noise_shows_visible_failure_spike():
    generator = TraceGenerator(seed=791)
    store = InMemoryTraceStore()
    scenario = InfraNoiseScenario(
        n_before=50,
        n_after=50,
        bad_failure_rate=0.9,
        baseline_failure_rate=0.05,
        bad_value_share=1.0,
    )

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    before_start = at - timedelta(seconds=scenario.interval_seconds * scenario.n_before)
    after_end = at + timedelta(seconds=scenario.interval_seconds * scenario.n_after)
    window = list(store.query_window(before_start, after_end))

    before = [t for t in window if t.timestamp < at]
    after = [t for t in window if t.timestamp >= at and t.injected_fault_id == gt.scenario_id]

    before_rate = sum(1 for t in before if t.outcome == "failure") / len(before)
    after_rate = sum(1 for t in after if t.outcome == "failure") / len(after)

    assert after_rate > before_rate + 0.3