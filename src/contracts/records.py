"""
The permanent data shapes for this project.

Rule: this file imports from nothing else in the project. Every other module
imports FROM here. 
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TraceRecord:
    """One row describing what happened on one request, from any AI pipeline."""

    # Mandatory — every pipeline must be able to produce these three
    request_id: str
    timestamp: datetime
    outcome: str  # "success" | "failure"

    # Common but optional — not every pipeline logs these
    branch: str | None = None
    latency_ms: float | None = None

    # The open factor bag. Whatever a pipeline logs beyond the above lands here.
    # e.g. {"model_version": "v2", "tool_version": "2.4", "retrieval_score": 0.61}
    factors: dict[str, Any] = field(default_factory=dict)

    # Only ever set during benchmark runs. None in real production traffic.
    injected_fault_id: str | None = None


@dataclass
class Hypothesis:
    """One candidate root-cause explanation, produced by a DiagnosisEngine."""

    cause_layer: str  # "model" | "retrieval" | "tool" | "taxonomy" | "infra" | "unknown"
    factor: str  # e.g. "tool_version=2.4"
    p_value: float
    effect_size: float  # odds ratio (categorical) or rank-biserial r (continuous)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Changepoint:
    """A detected shift in a signal (usually failure_rate) at approximately time T."""

    timestamp: datetime
    signal: str  # which metric shifted, e.g. "failure_rate"
    before_rate: float
    after_rate: float
    p_value: float


@dataclass
class GroundTruth:
    """What the benchmark's fault injector actually did — logged BEFORE the
    engine runs, so the engine's output can be scored blind against this."""

    scenario_id: str
    fault_type: str  # "tool_regression" | "model_swap" | "retrieval_degradation" | ...
    injected_at: datetime
    affected_factor: str  # e.g. "tool_version"
    affected_value: str  # e.g. "2.4"
