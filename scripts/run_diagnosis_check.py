
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Same sys.path fix as run_detector_check.py (Phase 3) — a plain
# `python scripts/foo.py` invocation only adds scripts/ to sys.path, not the
# project root, so `from src...` fails without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from src.config.loader import load_pipeline_config  # noqa: E402
from src.detection.ztest_detector import ZTestDetector  # noqa: E402
from src.diagnosis.v1_univariate import UnivariateDiagnosisEngine  # noqa: E402
from src.store.postgres import PostgresTraceStore  # noqa: E402

load_dotenv()


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _windows_from_fault_id(fault_id: str):
    """Raw SQL, deliberately bypassing PostgresTraceStore — see module
    docstring for why."""
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "diagnosisdb"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM traces "
                "WHERE injected_fault_id = %s",
                (fault_id,),
            )
            recent_start, recent_end, n = cur.fetchone()
    finally:
        conn.close()

    if n == 0 or recent_start is None:
        raise SystemExit(
            f"No traces found with injected_fault_id = {fault_id!r}. "
            "Check the value with: SELECT DISTINCT injected_fault_id FROM traces;"
        )

    span = recent_end - recent_start
    baseline_end = recent_start
    baseline_start = recent_start - span
    return baseline_start, baseline_end, recent_start, recent_end, n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fault-id", help="injected_fault_id to look up windows from")
    parser.add_argument("--baseline-start")
    parser.add_argument("--baseline-end")
    parser.add_argument("--recent-start")
    parser.add_argument("--recent-end")
    parser.add_argument(
        "--config",
        default="pipeline_config.yaml",
        help="path to pipeline_config.yaml (optional, default: ./pipeline_config.yaml)",
    )
    args = parser.parse_args()

    if args.fault_id:
        b_start, b_end, r_start, r_end, n = _windows_from_fault_id(args.fault_id)
        print(f"Derived windows from injected_fault_id={args.fault_id!r} ({n} tagged traces):")
    elif all([args.baseline_start, args.baseline_end, args.recent_start, args.recent_end]):
        b_start = _parse_ts(args.baseline_start)
        b_end = _parse_ts(args.baseline_end)
        r_start = _parse_ts(args.recent_start)
        r_end = _parse_ts(args.recent_end)
        print("Using explicit windows:")
    else:
        parser.error(
            "Either --fault-id, or all four of --baseline-start/--baseline-end/"
            "--recent-start/--recent-end are required."
        )
        return

    print(f"  baseline: {b_start}  ->  {b_end}")
    print(f"  recent:   {r_start}  ->  {r_end}")

    store = PostgresTraceStore()
    baseline_traces = list(store.query_window(b_start, b_end))
    recent_traces = list(store.query_window(r_start, r_end))
    print(f"\nPulled {len(baseline_traces)} baseline traces, {len(recent_traces)} recent traces.")

    if not baseline_traces or not recent_traces:
        raise SystemExit("One or both windows returned zero traces — nothing to diagnose.")

    detector = ZTestDetector()
    changepoint = detector.detect(baseline_traces, recent_traces)

    if changepoint is None:
        print("\nNo significant changepoint detected (p >= alpha). Nothing to diagnose.")
        return

    print(
        f"\nChangepoint detected: before_rate={changepoint.before_rate:.3f} "
        f"-> after_rate={changepoint.after_rate:.3f}, p={changepoint.p_value:.3e}"
    )

    config = load_pipeline_config(args.config)
    if config is None:
        print(f"(no pipeline_config.yaml found at {args.config!r} — cause_layer will be 'unknown')")
    else:
        print(f"(loaded pipeline_config.yaml: {config.name!r})")

    engine = UnivariateDiagnosisEngine(config=config)
    all_traces = baseline_traces + recent_traces
    hypotheses = engine.diagnose(all_traces, changepoint)

    print(f"\n{len(hypotheses)} hypotheses (ranked by |effect_size|):")
    for h in hypotheses:
        print(
            f"  {h.factor:30s}  p={h.p_value:.3e}  effect_size={h.effect_size:.3f}  "
            f"layer={h.cause_layer}"
        )
        print(f"      evidence: {h.evidence}")


if __name__ == "__main__":
    main()