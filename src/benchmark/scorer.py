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