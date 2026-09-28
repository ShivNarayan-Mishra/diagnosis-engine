"""
tests/benchmark/test_null_scenario.py

Rewritten after a real bug found on the real machine (running_log_phase6.md
Entry 14): the original version used PostgresTraceStore and queried the shared,
persistent `traces` table by raw wall-clock timestamp range for before-window
traces (which are deliberately left untagged, same convention every scenario
uses). Within one pytest session, multiple scenario tests all write to that same
real table within seconds of each other -- the timestamp-range query had no way
to tell "my before-window traces" apart from "some other test's traces that
happened to land nearby in time," and silently vacuumed up both. Confirmed by
watching the failing count itself GROW across consecutive real runs (182, then
385, then 579) -- the signature of a shared, ever-growing table, not random
noise.

Fix: these tests check scenario INJECTION LOGIC in isolation, not real database
integration (that's test_postgres.py's job) -- they don't need PostgresTraceStore
at all. Switched to InMemoryTraceStore, the same store run_benchmark.py already
uses and for the same underlying reason (a fresh, isolated store per run, immune
to cross-run pollution by construction, per running_log_phase5.md Entry 3's
original reasoning for introducing it). Tests that already filtered by the
unique injected_fault_id (test_null_scenario_traces_are_written_and_queryable,
test_null_scenario_does_not_mutate_factors) were never actually broken by this,
but switched too for consistency and because there's no reason left to touch
real Postgres from this file at all.
"""
from datetime import datetime, timedelta, timezone

from src.benchmark.generator import TraceGenerator
from src.benchmark.scenarios.null import NullScenario, NO_FAULT_INJECTED
from src.store.in_memory import InMemoryTraceStore


def test_null_scenario_injects_and_logs_ground_truth():
    generator = TraceGenerator(seed=321)
    store = InMemoryTraceStore()
    scenario = NullScenario(n_before=20, n_after=20)

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    assert gt.fault_type == "null"
    assert gt.affected_factor == NO_FAULT_INJECTED
    assert gt.affected_value == NO_FAULT_INJECTED
    assert gt.scenario_id.startswith("null_")


def test_null_scenario_traces_are_written_and_queryable():
    generator = TraceGenerator(seed=654)
    store = InMemoryTraceStore()
    scenario = NullScenario(n_before=20, n_after=20, interval_seconds=1.0)

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    before_start = at - timedelta(seconds=scenario.interval_seconds * scenario.n_before)
    after_end = at + timedelta(seconds=scenario.interval_seconds * scenario.n_after)
    window = list(store.query_window(before_start, after_end))

    tagged = [t for t in window if t.injected_fault_id == gt.scenario_id]
    assert len(tagged) == scenario.n_after


def test_null_scenario_does_not_mutate_factors():
    generator = TraceGenerator(seed=987)
    store = InMemoryTraceStore()
    scenario = NullScenario(n_before=20, n_after=20)

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    before_start = at - timedelta(seconds=scenario.interval_seconds * scenario.n_before)
    after_end = at + timedelta(seconds=scenario.interval_seconds * scenario.n_after)
    window = list(store.query_window(before_start, after_end))

    tool_versions = {t.factors.get("tool_version") for t in window if t.injected_fault_id == gt.scenario_id}
    model_versions = {t.factors.get("model_version") for t in window if t.injected_fault_id == gt.scenario_id}
    assert tool_versions == {"2.3"}
    assert model_versions == {"v2"}


def test_null_scenario_shows_no_visible_failure_spike():
    """
    Sanity check in the same spirit as
    test_tool_regression_shows_visible_failure_spike (engineer_handbook.md):
    eyeball the raw rates before trusting any statistical test built on top
    of them. Here the expectation is the OPPOSITE of that test -- before and
    after should look statistically indistinguishable, since nothing was
    injected. Uses a fixed baseline_failure_rate so both windows are drawn
    from a known, identical rate, not left to the generator's own default
    variability.

    Now uses an isolated InMemoryTraceStore, so before/after only ever
    contain THIS scenario's own traces -- the exact-timestamp-range query is
    safe here in a way it wasn't against the shared real Postgres table.
    """
    generator = TraceGenerator(seed=111)
    store = InMemoryTraceStore()
    scenario = NullScenario(n_before=100, n_after=100, baseline_failure_rate=0.10)

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    before_start = at - timedelta(seconds=scenario.interval_seconds * scenario.n_before)
    after_end = at + timedelta(seconds=scenario.interval_seconds * scenario.n_after)
    window = list(store.query_window(before_start, after_end))

    before = [t for t in window if t.timestamp < at]
    after = [t for t in window if t.timestamp >= at]

    assert len(before) == scenario.n_before
    assert len(after) == scenario.n_after

    before_rate = sum(1 for t in before if t.outcome == "failure") / len(before)
    after_rate = sum(1 for t in after if t.outcome == "failure") / len(after)

    assert abs(before_rate - after_rate) < 0.15