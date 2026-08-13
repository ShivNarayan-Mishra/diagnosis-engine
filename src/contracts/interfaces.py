"""
The four seams. Each ABC defines WHAT a component does. The concrete classes
elsewhere in the project define HOW. Nothing outside contracts/ is imported here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from src.contracts.records import Changepoint, Hypothesis, TraceRecord


class IngestAdapter(ABC):
    """Converts one raw input shape into a TraceRecord."""

    @abstractmethod
    def can_handle(self, raw: Any) -> bool:
        """Return True if this adapter knows how to normalize `raw`."""
        ...

    @abstractmethod
    def normalize(self, raw: Any) -> TraceRecord:
        """Convert raw input into the canonical TraceRecord shape."""
        ...


class TraceStore(ABC):
    """Persists and queries TraceRecords. Today: Postgres. Swappable later."""

    @abstractmethod
    def write(self, trace: TraceRecord) -> None:
        ...

    @abstractmethod
    def query_window(
        self, start: datetime, end: datetime, branch: str | None = None
    ) -> Iterable[TraceRecord]:
        ...


class ChangepointDetector(ABC):
    """Detects whether/when a signal (e.g. failure_rate) shifted significantly."""

    @abstractmethod
    def detect(self, series: list[TraceRecord]) -> list[Changepoint]:
        ...


class DiagnosisEngine(ABC):
    """Attributes a detected changepoint to a root-cause factor."""

    @abstractmethod
    def diagnose(
        self, traces: list[TraceRecord], changepoint: Changepoint
    ) -> list[Hypothesis]:
        ...
