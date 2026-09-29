
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Make the project root importable regardless of how this script is invoked.
# `python scripts/run_detector_check.py` only puts scripts/ on sys.path, not
# the project root — so `from src...` fails with ModuleNotFoundError unless
# something adds the root explicitly. pytest and uvicorn both do this for you
# automatically; a plain `python scripts/foo.py` invocation does not.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.detection.ztest_detector import ZTestDetector
from src.store.postgres import PostgresTraceStore


def parse_iso(value: str) -> datetime:
    # Accept a trailing "Z" the same way Phase 1's StructuredRowAdapter does,
    # since datetime.fromisoformat() doesn't understand "Z" natively on
    # every Python version this project might run under.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ZTestDetector against real Postgres traces.")
    parser.add_argument("--baseline-start", required=True, type=parse_iso)
    parser.add_argument("--baseline-end", required=True, type=parse_iso)
    parser.add_argument("--recent-start", required=True, type=parse_iso)
    parser.add_argument("--recent-end", required=True, type=parse_iso)
    parser.add_argument("--branch", default=None)
    parser.add_argument("--alpha", type=float, default=0.05)
    args = parser.parse_args()

    store = PostgresTraceStore()

    baseline = list(store.query_window(args.baseline_start, args.baseline_end, args.branch))
    recent = list(store.query_window(args.recent_start, args.recent_end, args.branch))

    print(f"Baseline window: {len(baseline)} traces "
          f"({args.baseline_start} to {args.baseline_end}, branch={args.branch or 'any'})")
    print(f"Recent window:   {len(recent)} traces "
          f"({args.recent_start} to {args.recent_end}, branch={args.branch or 'any'})")

    if not baseline or not recent:
        print("\nOne or both windows are empty — nothing to compare. "
              "Check your time bounds against what's actually in the traces table.")
        return 1

    detector = ZTestDetector(alpha=args.alpha)
    result = detector.detect(baseline, recent)

    print()
    if result is None:
        print(f"No significant shift detected (alpha={args.alpha}).")
        baseline_rate = sum(1 for t in baseline if t.outcome == "failure") / len(baseline)
        recent_rate = sum(1 for t in recent if t.outcome == "failure") / len(recent)
        print(f"  baseline failure rate: {baseline_rate:.3f}")
        print(f"  recent failure rate:   {recent_rate:.3f}")
    else:
        print("Changepoint detected:")
        print(f"  signal:       {result.signal}")
        print(f"  timestamp:    {result.timestamp}")
        print(f"  before_rate:  {result.before_rate:.3f}")
        print(f"  after_rate:   {result.after_rate:.3f}")
        print(f"  p_value:      {result.p_value:.6g}")

    return 0


if __name__ == "__main__":
    sys.exit(main())