
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import sys
import os

# Adds the parent directory of the script to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now the script can find 'src'
from src.benchmark.generator import TraceGenerator
from src.benchmark.generator import TraceGenerator
from src.store.postgres import PostgresTraceStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=200, help="number of traces to write")
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--failure-rate", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    # base_failure_rate is a constructor arg on the real TraceGenerator, not a per-call arg
    generator = TraceGenerator(seed=args.seed, base_failure_rate=args.failure_rate)
    store = PostgresTraceStore()

    end = datetime.now(timezone.utc)
    start = end - timedelta(seconds=args.interval_seconds * args.n)

    traces = generator.generate(
        n=args.n,
        start_time=start,
        interval_seconds=args.interval_seconds,
    )
    for trace in traces:
        store.write(trace)

    print(f"wrote {len(traces)} stable traces from {start.isoformat()} to {end.isoformat()}")


if __name__ == "__main__":
    main()
