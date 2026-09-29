from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.loader import load_pipeline_config
from src.contracts.records import TraceRecord
from src.detection.ztest_detector import ZTestDetector
from src.diagnosis.v1_univariate import UnivariateDiagnosisEngine


def parse_timestamp(raw: str) -> datetime:
    """
    The export's timestamps have no timezone marker (e.g.
    "2026-09-09 18:14:28.584073"). Assumed UTC -- a reasonable default for a
    backend logging pipeline, but genuinely an assumption, not confirmed from
    the file itself. Attached explicitly rather than left naive, since every
    other datetime in this project (Changepoint.timestamp, generator output)
    is timezone-aware, and mixing aware/naive datetimes raises at comparison
    time rather than failing cleanly up front.
    """
    dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f")
    return dt.replace(tzinfo=timezone.utc)


def row_to_trace(row: dict, column_map: dict) -> TraceRecord | None:
    outcome_map = column_map["outcome"]["map"]
    raw_outcome = row[column_map["outcome"]["source_column"]]
    if raw_outcome not in outcome_map:
        # Fail loudly rather than silently mis-mapping an outcome value this
        # config doesn't know about -- a new guardrail_outcome value showing
        # up in future data should be a visible surprise, not a quiet
        # miscategorization.
        raise ValueError(
            f"Unrecognized guardrail_outcome value {raw_outcome!r} -- "
            f"add it to offline_config.yaml's column_map.outcome.map"
        )

    latency_raw = row.get(column_map["latency_ms"], "")
    latency_ms = float(latency_raw) if latency_raw else None

    factors: dict = {}

    # Direct column pass-throughs. Empty-string values (category/intent are
    # blank for out-of-domain queries that never got classified) are mapped
    # to "missing" rather than a literal "" category -- the
    # keyword_gate_rejected boolean below already captures that exact signal
    # cleanly; keeping "" as its own category too would just double-count
    # the same underlying event through two different factors.
    for factor_key, source_column in [
        ("category", "category"),
        ("intent", "intent"),
        ("valid_json", "valid_json"),
        ("in_taxonomy", "in_taxonomy"),
    ]:
        raw_value = row.get(source_column, "")
        if raw_value != "":
            factors[factor_key] = raw_value

    # Derived factors -- see offline_config.yaml's comment on why these exist
    # instead of storing fallback_reason verbatim.
    fallback_reason = row.get("fallback_reason", "")
    factors["keyword_gate_rejected"] = fallback_reason == "out_of_domain_keyword_gate"
    factors["fabricated_id_detected"] = fallback_reason.startswith("fabricated_id")

    return TraceRecord(
        request_id=row[column_map["request_id"]],
        timestamp=parse_timestamp(row[column_map["timestamp"]]),
        outcome=outcome_map[raw_outcome],
        branch=row.get(column_map["branch"]) or None,
        latency_ms=latency_ms,
        factors=factors,
    )


def find_largest_gap_index(traces: list[TraceRecord]) -> int:
    """
    Splits at the largest real time gap in the data, rather than an
    arbitrary fixed row count -- makes this reusable on a different export
    with a different natural break point, instead of hardcoding a number
    specific to one file. Returns the index such that traces[:idx] is
    "before" and traces[idx:] is "after".
    """
    if len(traces) < 2:
        raise ValueError("Need at least 2 traces to find a gap.")
    gaps = [
        (traces[i + 1].timestamp - traces[i].timestamp, i + 1)
        for i in range(len(traces) - 1)
    ]
    _, split_index = max(gaps, key=lambda pair: pair[0])
    return split_index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="path to the static CSV export")
    parser.add_argument("--config", default="offline_config.yaml")
    parser.add_argument(
        "--split-index",
        type=int,
        default=None,
        help="override the auto-detected before/after split point (row index after sorting by time)",
    )
    args = parser.parse_args()

    import yaml

    with open(args.config) as f:
        raw_config = yaml.safe_load(f)
    column_map = raw_config["column_map"]

    pipeline_config = load_pipeline_config(args.config)
    print(f"(loaded {args.config}: '{pipeline_config.name}')")

    with open(args.csv, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f"Read {len(rows)} rows from {args.csv}")

    traces = [row_to_trace(row, column_map) for row in rows]
    traces.sort(key=lambda t: t.timestamp)

    if args.split_index is not None:
        split_index = args.split_index
    else:
        split_index = find_largest_gap_index(traces)
        gap = traces[split_index].timestamp - traces[split_index - 1].timestamp
        print(f"Auto-detected largest gap: {gap} at index {split_index}")

    before = traces[:split_index]
    after = traces[split_index:]

    before_failures = sum(1 for t in before if t.outcome == "failure")
    after_failures = sum(1 for t in after if t.outcome == "failure")
    print(
        f"before: n={len(before)} failures={before_failures} "
        f"({before_failures/len(before):.1%})  "
        f"[{before[0].timestamp} .. {before[-1].timestamp}]"
    )
    print(
        f"after:  n={len(after)} failures={after_failures} "
        f"({after_failures/len(after):.1%})  "
        f"[{after[0].timestamp} .. {after[-1].timestamp}]"
    )

    detector = ZTestDetector()
    changepoint = detector.detect(before, after)

    if changepoint is None:
        print()
        print(
            "No statistically significant changepoint detected between these "
            "two windows -- the failure-rate difference above is consistent "
            "with random sampling noise at this sample size. This is a valid, "
            "honest result, not a failure of the script: it means the engine "
            "correctly declined to raise an alarm on a shift too small to "
            "trust, rather than overclaiming a cause from ~40 rows."
        )
        return

    print()
    print(
        f"Changepoint detected: before_rate={changepoint.before_rate:.3f} "
        f"after_rate={changepoint.after_rate:.3f} p={changepoint.p_value:.3e}"
    )

    engine = UnivariateDiagnosisEngine(config=pipeline_config)
    hypotheses = engine.diagnose(before + after, changepoint)

    if not hypotheses:
        print("No factor survived FDR correction as a significant explanation.")
        return

    print()
    print("Ranked hypotheses:")
    for h in hypotheses:
        print(
            f"  {h.factor:30s} p={h.p_value:.3e} effect_size={h.effect_size:.3f} "
            f"layer={h.cause_layer}"
        )
        print(f"    evidence: {h.evidence}")


if __name__ == "__main__":
    main()