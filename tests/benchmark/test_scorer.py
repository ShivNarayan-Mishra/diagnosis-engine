"""
tests/benchmark/test_scorer.py

No test file existed for scorer.py anywhere in the project's tests/ tree before
this — every other module (contracts, adapters, store, detection, diagnosis,
benchmark/scenarios) has one, this was the gap. Cases here are the same 7
hand-built scenarios verified in a throwaway sandbox script during the
scorer.py continuous-factor fix (running_log_phase6.md Entry 1), now promoted
to a real, permanent pytest file so they run as part of the project's actual
suite going forward instead of living only in chat history.
"""
from datetime import datetime, timezone

from src.contracts.records import GroundTruth, Hypothesis
from src.benchmark.scorer import score

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _gt(fault_type, affected_factor, affected_value):
    return GroundTruth(
        scenario_id=f"{fault_type}_test",
        fault_type=fault_type,
        injected_at=NOW,
        affected_factor=affected_factor,
        affected_value=affected_value,
    )


def _hyp(factor, effect_size=5.0, p_value=0.001):
    return Hypothesis(
        cause_layer="unknown",
        factor=factor,
        p_value=p_value,
        effect_size=effect_size,
        evidence={},
    )


def test_categorical_exact_match_is_top1_correct():
    result = score([_hyp("tool_version=2.4")], _gt("tool_regression", "tool_version", "2.4"))
    assert result.top1_correct is True
    assert result.key_only_correct is False


def test_categorical_wrong_value_is_key_only_correct():
    result = score([_hyp("tool_version=2.3")], _gt("tool_regression", "tool_version", "2.4"))
    assert result.top1_correct is False
    assert result.key_only_correct is True


def test_categorical_wrong_factor_is_neither():
    result = score([_hyp("model_version=v3")], _gt("tool_regression", "tool_version", "2.4"))
    assert result.top1_correct is False
    assert result.key_only_correct is False


def test_empty_hypothesis_list():
    result = score([], _gt("tool_regression", "tool_version", "2.4"))
    assert result.top1_correct is False
    assert result.key_only_correct is False
    assert result.top_factor is None


def test_continuous_exact_match_is_top1_correct():
    """
    The case the Phase 6 scorer fix specifically targets: a continuous
    hypothesis reports only the bare key (per v1_univariate.py's
    _test_continuous, there's no single discrete value for a continuous
    drift), so top1_correct has to be a bare-key match, not a "key=value"
    match. Before the fix, this exact case would have been misfiled as
    key_only_correct=True instead of top1_correct=True.
    """
    result = score(
        [_hyp("retrieval_score")],
        _gt("retrieval_degradation", "retrieval_score", "degraded_to_0.1-0.4"),
    )
    assert result.top1_correct is True
    assert result.key_only_correct is False


def test_continuous_wrong_factor():
    result = score(
        [_hyp("latency_ms")],
        _gt("retrieval_degradation", "retrieval_score", "degraded_to_0.1-0.4"),
    )
    assert result.top1_correct is False
    assert result.key_only_correct is False


def test_continuous_ground_truth_with_categorical_shaped_hypothesis_does_not_false_positive():
    """
    Edge case that shouldn't occur with the current engine (categorical
    hypotheses always contain "=", continuous ones never do) but checked
    anyway per scorer.py's own documented assumption: a "=value" suffix
    on a continuous ground truth's factor should NOT count as a match,
    since there's no basis to verify a value the ground truth never
    specified in comparable form.
    """
    result = score(
        [_hyp("retrieval_score=0.4")],
        _gt("retrieval_degradation", "retrieval_score", "degraded_to_0.1-0.4"),
    )
    assert result.top1_correct is False