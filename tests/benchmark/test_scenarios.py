from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import psycopg2

from src.benchmark.generator import TraceGenerator
from src.benchmark.scenarios.model_swap import ModelSwapScenario
from src.benchmark.scenarios.tool_regression import ToolRegressionScenario
from src.store.ground_truth_store import write_ground_truth
from src.store.postgres import PostgresTraceStore


def _fetch_fault_scenario(scenario_id: str):
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "diagnosisdb"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fault_type, affected_factor, affected_value
                FROM fault_scenarios WHERE scenario_id = %s
                """,
                (scenario_id,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def test_tool_regression_injects_and_logs_ground_truth():
    generator = TraceGenerator(seed=123)
    store = PostgresTraceStore()
    scenario = ToolRegressionScenario(n_before=20, n_after=20)

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    assert gt.fault_type == "tool_regression"
    assert gt.affected_factor == "tool_version"
    assert gt.affected_value == "2.4"

    write_ground_truth(gt)
    row = _fetch_fault_scenario(gt.scenario_id)
    assert row is not None
    assert row[0] == "tool_regression"
    assert row[1] == "tool_version"
    assert row[2] == "2.4"


def test_model_swap_injects_and_logs_ground_truth():
    generator = TraceGenerator(seed=456)
    store = PostgresTraceStore()
    scenario = ModelSwapScenario(n_before=20, n_after=20)

    at = datetime.now(timezone.utc)
    gt = scenario.inject(generator, store, at=at)

    assert gt.fault_type == "model_swap"
    assert gt.affected_factor == "model_version"
    assert gt.affected_value == "v3"

    write_ground_truth(gt)
    row = _fetch_fault_scenario(gt.scenario_id)
    assert row is not None
    assert row[0] == "model_swap"
    assert row[1] == "model_version"
    assert row[2] == "v3"


def test_tool_regression_shows_visible_failure_spike():
    """Sanity check from engineer_handbook.md: the failure rate after injection should be
    visibly higher than before, just looking at raw traces. If this doesn't hold, no
    statistical test built in later phases will find anything real either — this has to
    pass first."""
    generator = TraceGenerator(seed=789)
    store = PostgresTraceStore()
    scenario = ToolRegressionScenario(
        n_before=50,
        n_after=50,
        bad_failure_rate=0.9,
        baseline_failure_rate=0.05,
        bad_value_share=1.0,
    )
    at = datetime.now(timezone.utc)
    scenario.inject(generator, store, at=at)

    before = list(store.query_window(at - timedelta(seconds=60), at))
    after = list(store.query_window(at, at + timedelta(seconds=60)))

    assert len(before) > 0
    assert len(after) > 0

    before_rate = sum(1 for t in before if t.outcome == "failure") / len(before)
    after_rate = sum(1 for t in after if t.outcome == "failure") / len(after)

    assert after_rate > before_rate
