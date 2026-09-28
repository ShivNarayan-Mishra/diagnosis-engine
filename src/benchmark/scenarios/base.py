#base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.benchmark.generator import TraceGenerator
from src.contracts.interfaces import TraceStore
from src.contracts.records import GroundTruth


class FaultScenario(ABC):
    """
    The seam for fault scenarios. Anything that implements this can be run by the
    benchmark runner (Phase 5) or the confounded-scenario composer (Phase 6) without
    those callers needing to know which specific fault it is.

    Placement note: confirmed against the real interfaces.py that it currently defines
    only IngestAdapter, TraceStore, ChangepointDetector, DiagnosisEngine — no
    FaultScenario. Defined here instead. If you later want it living next to the other
    four ABCs, move this class into interfaces.py and change the import in
    tool_regression.py / model_swap.py accordingly. No behavior difference either way.
    """

    @abstractmethod
    def inject(self, generator: TraceGenerator, store: TraceStore, at: datetime) -> GroundTruth:
        """
        Generate before/after traces around timestamp `at`, write them to `store`, and
        return a GroundTruth describing exactly what was injected. The engine (built in
        later phases) never sees this GroundTruth before it produces its own diagnosis —
        it's only used afterward, to score the diagnosis.
        """
        ...
