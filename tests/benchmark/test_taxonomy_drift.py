
from datetime import datetime, timedelta, timezone

from src.benchmark.generator import INTENTS, TraceGenerator
from src.benchmark.scenarios.taxonomy_drift import TaxonomyDriftScenario
from src.store.in_memory import InMemoryTraceStore


def test_taxonomy_drift_injects_and_logs_ground_truth():
    generator = TraceGenerator(seed=135)
    store = InMemoryTraceStore()
    scenario = TaxonomyDriftScenario(n_before=20, n_after=20)

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    assert gt.fault_type == "taxonomy_drift"
    assert gt.affected_factor == "intent"
    assert gt.affected_value == "unrecognized_request"
    assert gt.affected_value not in INTENTS


def test_taxonomy_drift_before_window_uses_only_known_intents():
    generator = TraceGenerator(seed=246)
    store = InMemoryTraceStore()
    scenario = TaxonomyDriftScenario(n_before=20, n_after=20)

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    before_start = at - timedelta(seconds=scenario.interval_seconds * scenario.n_before)
    after_end = at + timedelta(seconds=scenario.interval_seconds * scenario.n_after)
    window = list(store.query_window(before_start, after_end))
    before = [t for t in window if t.timestamp < at]

    assert len(before) == scenario.n_before
    assert all(t.factors.get("intent") in INTENTS for t in before)


def test_taxonomy_drift_shows_visible_failure_spike():
    """
    Sanity check in the same spirit as test_tool_regression_shows_visible_failure_spike:
    the drifted-intent population should have a clearly higher failure rate than
    baseline, eyeballed directly on raw traces before trusting any statistical test.
    """
    generator = TraceGenerator(seed=357)
    store = InMemoryTraceStore()
    scenario = TaxonomyDriftScenario(
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

    assert len(before) == scenario.n_before

    before_rate = sum(1 for t in before if t.outcome == "failure") / len(before)
    after_rate = sum(1 for t in after if t.outcome == "failure") / len(after)

    assert after_rate > before_rate + 0.3