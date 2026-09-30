

from __future__ import annotations

from scipy.stats import chi2_contingency

from src.contracts.records import Changepoint, TraceRecord


class ZTestDetector:
    """
    Two-proportion test on failure rate between two explicit windows of traces.

    Implemented via scipy's chi2_contingency on the 2x2 table
        [[failures_baseline, successes_baseline],
         [failures_recent,   successes_recent]]
    rather than hand-rolling the z formula, because chi2_contingency on a 2x2
    table is mathematically equivalent to a two-proportion z-test (z^2 == chi2)
    and is less error-prone to implement correctly. Worth deriving the z
    formula by hand once (see mentor_guide.md Part 3) to confirm the
    equivalence yourself, then trust this.
    """

    def __init__(self, alpha: float = 0.05):
        self.alpha = alpha

    def detect(
        self,
        baseline: list[TraceRecord],
        recent: list[TraceRecord],
    ) -> Changepoint | None:
        if not baseline or not recent:
            raise ValueError("Both baseline and recent windows must be non-empty.")

        n_baseline = len(baseline)
        n_recent = len(recent)

        failures_baseline = sum(1 for t in baseline if t.outcome == "failure")
        failures_recent = sum(1 for t in recent if t.outcome == "failure")

        successes_baseline = n_baseline - failures_baseline
        successes_recent = n_recent - failures_recent

        table = [
            [failures_baseline, successes_baseline],
            [failures_recent, successes_recent],
        ]

        # correction=False so this matches a hand-rolled two-proportion
        # z-test exactly. scipy's default (Yates' continuity correction)
        # would make this more conservative and break the z^2 == chi2 identity.
        _, p_value, _, _ = chi2_contingency(table, correction=False)

        before_rate = failures_baseline / n_baseline
        after_rate = failures_recent / n_recent

        if p_value >= self.alpha:
            return None

        # "Approximately when" is enough — see mentor_guide.md's discussion of
        # why the diagnosis engine doesn't need the changepoint to the
        # millisecond. Using the earliest timestamp in `recent` as a stand-in.
        changepoint_ts = min(t.timestamp for t in recent)

        return Changepoint(
            timestamp=changepoint_ts,
            signal="failure_rate",
            before_rate=before_rate,
            after_rate=after_rate,
            p_value=p_value,
        )
