"""
Unit tests for ZTestDetector. No Postgres required — uses TraceGenerator
directly, in-memory, mutating outcomes to simulate a known failure-rate shift.
This is the same "generate baseline, generate recent, mutate recent's
outcomes toward failure" pattern the Phase 2 scenarios already use, just
without persisting to the DB or logging GroundTruth — this file only tests
the detector's math, not the injection/persistence machinery.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from src.benchmark.generator import TraceGenerator
from src.detection.ztest_detector import ZTestDetector


def _bump_failure_rate(traces, target_rate: float, seed: int = 7):
    """Re-roll each trace's outcome independently at `target_rate`.
    Local RNG, separate from the generator's own — same pattern used
    elsewhere in this project to avoid reaching into TraceGenerator internals.
    """
    rng = random.Random(seed)
    for t in traces:
        t.outcome = "failure" if rng.random() < target_rate else "success"
    return traces


def test_detects_obvious_shift():
    gen = TraceGenerator(seed=1, base_failure_rate=0.05)
    now = datetime.now(timezone.utc)

    baseline = gen.generate(n=200, start_time=now)
    recent = gen.generate(n=200, start_time=now + timedelta(seconds=300))
    recent = _bump_failure_rate(recent, target_rate=0.30)

    detector = ZTestDetector(alpha=0.05)
    result = detector.detect(baseline, recent)

    assert result is not None
    assert result.signal == "failure_rate"
    assert result.before_rate < result.after_rate
    assert result.p_value < 0.05


def test_does_not_fire_on_stable_traffic():
    gen = TraceGenerator(seed=2, base_failure_rate=0.05)
    now = datetime.now(timezone.utc)

    baseline = gen.generate(n=300, start_time=now)
    recent = gen.generate(n=300, start_time=now + timedelta(seconds=400))
    # no mutation — both windows drawn from the same underlying rate

    detector = ZTestDetector(alpha=0.05)
    result = detector.detect(baseline, recent)

    assert result is None


def test_raises_on_empty_window():
    detector = ZTestDetector()
    with pytest.raises(ValueError):
        detector.detect([], [])


def test_changepoint_timestamp_is_earliest_in_recent_window():
    gen = TraceGenerator(seed=3, base_failure_rate=0.05)
    now = datetime.now(timezone.utc)

    baseline = gen.generate(n=150, start_time=now)
    recent_start = now + timedelta(seconds=500)
    recent = gen.generate(n=150, start_time=recent_start)
    recent = _bump_failure_rate(recent, target_rate=0.40)

    detector = ZTestDetector()
    result = detector.detect(baseline, recent)

    assert result is not None
    assert result.timestamp == min(t.timestamp for t in recent)
