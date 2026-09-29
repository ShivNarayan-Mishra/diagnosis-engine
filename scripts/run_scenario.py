

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import sys
import os

# Adds the parent directory of the script to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now the script can find 'src'
from src.benchmark.generator import TraceGenerator
from src.benchmark.generator import TraceGenerator
from src.benchmark.scenarios.model_swap import ModelSwapScenario
from src.benchmark.scenarios.tool_regression import ToolRegressionScenario
from src.store.ground_truth_store import write_ground_truth
from src.store.postgres import PostgresTraceStore

SCENARIOS = {
    "tool_regression": ToolRegressionScenario,
    "model_swap": ModelSwapScenario,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=sorted(SCENARIOS.keys()), required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    generator = TraceGenerator(seed=args.seed)
    store = PostgresTraceStore()
    scenario = SCENARIOS[args.scenario]()

    at = datetime.now(timezone.utc)
    ground_truth = scenario.inject(generator, store, at=at)
    write_ground_truth(ground_truth)

    print("GroundTruth logged:")
    print(f"  scenario_id:     {ground_truth.scenario_id}")
    print(f"  fault_type:      {ground_truth.fault_type}")
    print(f"  injected_at:     {ground_truth.injected_at.isoformat()}")
    print(f"  affected_factor: {ground_truth.affected_factor}")
    print(f"  affected_value:  {ground_truth.affected_value}")


if __name__ == "__main__":
    main()
