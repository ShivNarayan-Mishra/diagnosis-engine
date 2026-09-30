"""
tests/diagnosis/test_v1_univariate.py

Unit tests for UnivariateDiagnosisEngine. All in-memory — no Postgres needed,
same as tests/detection/test_ztest_detector.py. T
Deliberately does NOT use TraceGenerator — TraceRecord objects are built
directly here, so this file has no dependency on generator.py's exact API,
per the standing rule against writing code against files that weren't pasted
and confirmed.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from src.config.loader import PipelineConfig
from src.contracts.interfaces import DiagnosisEngine
from src.contracts.records import Changepoint, TraceRecord
from src.diagnosis.v1_univariate import UnivariateDiagnosisEngine

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _trace(i, outcome, factors, ts=None):
    return TraceRecord(
        request_id=f"r{i}",
        timestamp=ts or (T0 + timedelta(seconds=i)),
        outcome=outcome,
        factors=factors,
    )


def test_engine_satisfies_diagnosis_engine_abc():
    engine = UnivariateDiagnosisEngine()
    assert isinstance(engine, DiagnosisEngine)


def test_two_valued_categorical_fault_surfaces_correct_value_and_direction():
    """
    This is the exact case that caught a real bug during sandbox verification:
    for a factor with exactly two distinct values, the engine used to always
    test the alphabetically-first value regardless of which one was actually
    the injected fault, because a 2x2 chi-square p-value is identical either
    direction (only the odds ratio flips). Locking this in as a regression
    test.
    """
    rng = random.Random(42)
    traces = []
    i = 0
    for _ in range(200):
        outcome = "failure" if rng.random() < 0.05 else "success"
        traces.append(_trace(i, outcome, {"tool_version": "2.3"}))
        i += 1
    changepoint_ts = T0 + timedelta(seconds=i)
    for _ in range(200):
        if rng.random() < 0.6:
            tv, outcome = "2.4", ("failure" if rng.random() < 0.55 else "success")
        else:
            tv, outcome = "2.3", ("failure" if rng.random() < 0.05 else "success")
        traces.append(_trace(i, outcome, {"tool_version": tv}))
        i += 1

    cp = Changepoint(
        timestamp=changepoint_ts,
        signal="failure_rate",
        before_rate=0.035,
        after_rate=0.335,
        p_value=1e-10,
    )

    engine = UnivariateDiagnosisEngine()
    hyps = engine.diagnose(traces, cp)

    assert len(hyps) == 1
    assert hyps[0].factor == "tool_version=2.4"
    assert hyps[0].effect_size > 1  # risk direction, not the protective reciprocal
    assert hyps[0].cause_layer == "unknown"  # no config passed


def test_config_populates_cause_layer():
    rng = random.Random(42)
    traces = []
    i = 0
    for _ in range(200):
        outcome = "failure" if rng.random() < 0.05 else "success"
        traces.append(_trace(i, outcome, {"tool_version": "2.3"}))
        i += 1
    changepoint_ts = T0 + timedelta(seconds=i)
    for _ in range(200):
        if rng.random() < 0.6:
            tv, outcome = "2.4", ("failure" if rng.random() < 0.55 else "success")
        else:
            tv, outcome = "2.3", ("failure" if rng.random() < 0.05 else "success")
        traces.append(_trace(i, outcome, {"tool_version": tv}))
        i += 1

    cp = Changepoint(
        timestamp=changepoint_ts, signal="failure_rate",
        before_rate=0.035, after_rate=0.335, p_value=1e-10,
    )
    cfg = PipelineConfig(
        factors={"tool_version": {"type": "categorical", "layer": "tool"}}
    )
    engine = UnivariateDiagnosisEngine(config=cfg)
    hyps = engine.diagnose(traces, cp)
    assert hyps[0].cause_layer == "tool"


def test_three_valued_categorical_fault_picks_the_actual_bad_value():
    rng = random.Random(7)
    traces = []
    i = 0
    for _ in range(150):
        outcome = "failure" if rng.random() < 0.05 else "success"
        mv = rng.choice(["v1", "v2"])
        traces.append(_trace(i, outcome, {"model_version": mv}))
        i += 1
    cp_ts = T0 + timedelta(seconds=i)
    for _ in range(150):
        mv = "v3" if rng.random() < 0.5 else rng.choice(["v1", "v2"])
        outcome = "failure" if (mv == "v3" and rng.random() < 0.6) else (
            "failure" if rng.random() < 0.05 else "success"
        )
        traces.append(_trace(i, outcome, {"model_version": mv}))
        i += 1

    cp = Changepoint(
        timestamp=cp_ts, signal="failure_rate",
        before_rate=0.05, after_rate=0.3, p_value=1e-6,
    )
    engine = UnivariateDiagnosisEngine()
    hyps = engine.diagnose(traces, cp)
    assert hyps[0].factor == "model_version=v3"
    assert hyps[0].effect_size > 1


def test_continuous_factor_degradation_detected_via_mann_whitney():
    rng = random.Random(42)
    traces = []
    i = 0
    for _ in range(200):
        outcome = "failure" if rng.random() < 0.05 else "success"
        traces.append(_trace(i, outcome, {"retrieval_score": rng.gauss(0.80, 0.05)}))
        i += 1
    cp_ts = T0 + timedelta(seconds=i)
    for _ in range(200):
        score = max(0.0, rng.gauss(0.35, 0.1))
        outcome = "failure" if (score < 0.4 and rng.random() < 0.7) else (
            "failure" if rng.random() < 0.05 else "success"
        )
        traces.append(_trace(i, outcome, {"retrieval_score": score}))
        i += 1

    cp = Changepoint(
        timestamp=cp_ts, signal="failure_rate",
        before_rate=0.05, after_rate=0.3, p_value=1e-8,
    )
    engine = UnivariateDiagnosisEngine()
    hyps = engine.diagnose(traces, cp)
    assert hyps[0].factor == "retrieval_score"


def test_null_scenario_produces_no_hypotheses():
    """No fault injected — FDR correction should suppress noise, not just
    reduce it. This is the false-positive-rate case the whole benchmark
    (Phase 5/6) depends on being honest."""
    rng = random.Random(99)
    traces = []
    for i in range(400):
        outcome = "failure" if rng.random() < 0.05 else "success"
        traces.append(_trace(i, outcome, {
            "tool_version": "2.3",
            "model_version": "v2",
            "retrieval_score": rng.gauss(0.75, 0.05),
        }))
    cp = Changepoint(
        timestamp=T0 + timedelta(seconds=200), signal="failure_rate",
        before_rate=0.05, after_rate=0.05, p_value=0.9,
    )
    engine = UnivariateDiagnosisEngine()
    hyps = engine.diagnose(traces, cp)
    assert hyps == []


def test_empty_factor_bags_return_empty_list_without_crashing():
    traces = [
        _trace(0, "success", {}),
        _trace(1, "failure", {}, ts=T0 + timedelta(seconds=10)),
    ]
    cp = Changepoint(
        timestamp=T0 + timedelta(seconds=5), signal="failure_rate",
        before_rate=0.0, after_rate=1.0, p_value=0.01,
    )
    engine = UnivariateDiagnosisEngine()
    assert engine.diagnose(traces, cp) == []


def test_changepoint_with_all_traces_on_one_side_returns_empty_list():
    traces = [_trace(i, "success", {"tool_version": "2.3"}) for i in range(10)]
    cp = Changepoint(
        timestamp=T0 + timedelta(days=5), signal="failure_rate",
        before_rate=0.0, after_rate=0.0, p_value=1.0,
    )
    engine = UnivariateDiagnosisEngine()
    assert engine.diagnose(traces, cp) == []