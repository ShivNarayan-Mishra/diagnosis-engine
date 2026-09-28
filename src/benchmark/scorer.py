"""
src/benchmark/scorer.py

Scores a diagnosis engine's output against the GroundTruth logged at injection time.
The engine never sees GroundTruth before producing its hypotheses -- this module is
the only place the two ever get compared, and it only runs after diagnose() has
already returned.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.contracts.records import GroundTruth, Hypothesis


@dataclass
class ScoredRun:
    scenario_id: str
    fault_type: str
    expected_factor: str  # "tool_version=2.4" for categorical GroundTruth, or just
                           # "retrieval_score" for continuous -- see comparison note below
    top1_correct: bool  # rank-0 hypothesis correctly names the fault (see note)
    key_only_correct: bool  # categorical only: right factor name, wrong value --
                             # diagnostic aid, not the headline metric. Always False
                             # for continuous ground truth (see below).
    n_hypotheses: int
    top_factor: str | None  # None if the engine returned nothing (or detector found no changepoint)


def score(hypotheses: list[Hypothesis], ground_truth: GroundTruth) -> ScoredRun:
    """
    Comparison branches on whether the rank-0 hypothesis is categorical-shaped
    or continuous-shaped, using the exact same signal v1_univariate.py itself
    uses to distinguish them: categorical hypotheses always look like
    "key=value" (built in _test_categorical's factor_label), continuous
    hypotheses are always just the bare key (_test_continuous sets
    factor_label = key, since there's no single discrete value to name for a
    continuous factor's drift).

    Categorical branch (top_factor contains "="):
        Unchanged from before this fix. Exact "key=value" match required for
        top1_correct. This exists specifically because Phase 4 had a real bug
        where the engine named the right factor but the wrong value/direction
        (running_log_phase4.md, Entry 1) -- scoring on the factor name alone
        would make a regression of exactly that bug invisible. key_only_correct
        captures "close but wrong value" as a non-scoring diagnostic.

    Continuous branch (top_factor has no "="):
        There is no discrete value component to verify -- v1_univariate.py
        never attaches one for continuous factors, by design. So correctness
        here is just "did it name the right factor," full stop.
        key_only_correct is always False in this branch: it would just
        duplicate top1_correct's own meaning (there's no separate
        "right factor, wrong value" state to distinguish when there's no
        value being reported at all).

    Known assumption, not currently a problem: this logic trusts the SHAPE of
    top_factor (does it contain "=") to tell categorical and continuous apart,
    rather than looking up the ground truth's declared type. Given the
    confirmed real v1_univariate.py, categorical hypotheses always contain
    "=" and continuous ones never do, so this holds today. If a future engine
    version ever reports a categorical hypothesis without a "=value" suffix,
    this would need to look up the factor's type explicitly instead (e.g. via
    pipeline_config.yaml) -- flagging here so it isn't a silent surprise.
    """
    top_factor = hypotheses[0].factor if hypotheses else None

    if top_factor is None:
        expected_factor = f"{ground_truth.affected_factor}={ground_truth.affected_value}"
        top1_correct = False
        key_only_correct = False
    elif "=" in top_factor:
        expected_factor = f"{ground_truth.affected_factor}={ground_truth.affected_value}"
        top1_correct = top_factor == expected_factor
        key_only_correct = (
            not top1_correct
            and top_factor.split("=")[0] == ground_truth.affected_factor
        )
    else:
        expected_factor = ground_truth.affected_factor
        top1_correct = top_factor == ground_truth.affected_factor
        key_only_correct = False

    return ScoredRun(
        scenario_id=ground_truth.scenario_id,
        fault_type=ground_truth.fault_type,
        expected_factor=expected_factor,
        top1_correct=top1_correct,
        key_only_correct=key_only_correct,
        n_hypotheses=len(hypotheses),
        top_factor=top_factor,
    )