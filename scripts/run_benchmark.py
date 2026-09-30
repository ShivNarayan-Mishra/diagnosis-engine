
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tabulate import tabulate

from src.benchmark.generator import TraceGenerator
from src.benchmark.scenarios.infra_noise import InfraNoiseScenario  # Phase 6 addition (Step 5)
from src.benchmark.scenarios.model_swap import ModelSwapScenario
from src.benchmark.scenarios.null import NullScenario  # Phase 6 addition (Step 3)
from src.benchmark.scenarios.retrieval_degradation import RetrievalDegradationScenario  # Phase 6 addition
from src.benchmark.scenarios.taxonomy_drift import TaxonomyDriftScenario  # Phase 6 addition (Step 4)
from src.benchmark.scenarios.tool_regression import ToolRegressionScenario
from src.benchmark.scorer import ScoredRun, score
from src.config.loader import load_pipeline_config
from src.detection.ztest_detector import ZTestDetector
from src.diagnosis.v1_univariate import UnivariateDiagnosisEngine
from src.store.in_memory import InMemoryTraceStore

SCENARIOS = {
    "tool_regression": ToolRegressionScenario,
    "model_swap": ModelSwapScenario,
    "retrieval_degradation": RetrievalDegradationScenario,  # Phase 6 addition
    "null": NullScenario,  # Phase 6 addition (Step 3)
    "taxonomy_drift": TaxonomyDriftScenario,  # Phase 6 addition (Step 4)
    "infra_noise": InfraNoiseScenario,  # Phase 6 addition (Step 5)
}

# Offset so a run's scenario seed never numerically matches its generator seed.
# The two are already independent random.Random instances, consumed for different
# things -- a matching seed wouldn't actually correlate their output -- but keeping
# them visibly distinct removes any doubt about it when eyeballing a specific run.
SCENARIO_SEED_OFFSET = 100_000

# Fixed anchor timestamp for every run. Only relative spacing between traces matters,
# not wall-clock time, since each run gets its own fresh InMemoryTraceStore -- there's
# no shared window to collide with across runs the way there would be against a real,
# persistent Postgres table.
ANCHOR = datetime(2024, 1, 1, tzinfo=timezone.utc)


def run_one(scenario_cls, run_index: int, base_seed: int, engine: UnivariateDiagnosisEngine) -> ScoredRun:
    generator_seed = base_seed + run_index
    scenario_seed = generator_seed + SCENARIO_SEED_OFFSET

    generator = TraceGenerator(seed=generator_seed)
    store = InMemoryTraceStore()
    scenario = scenario_cls(seed=scenario_seed)

    ground_truth = scenario.inject(generator, store, at=ANCHOR)

    # Recover the two windows exactly, using the scenario's own n_before/n_after/
    # interval_seconds -- no min/max-timestamp inference needed here (unlike
    # run_diagnosis_check.py's --fault-id convenience mode against real Postgres data),
    # since this script controls exactly how the data was generated.
    before_start = ANCHOR - timedelta(seconds=scenario.interval_seconds * scenario.n_before)
    after_end = ANCHOR + timedelta(seconds=scenario.interval_seconds * scenario.n_after)

    # Boundary sits halfway between the last before-trace (ANCHOR - interval_seconds)
    # and the first after-trace (exactly ANCHOR). query_window's bounds are inclusive
    # on both ends, so querying [ANCHOR, ANCHOR] on both windows would double-count
    # the first after-trace -- this split avoids that without needing an exclusive-
    # bound version of query_window.
    boundary = ANCHOR - timedelta(seconds=scenario.interval_seconds / 2)

    baseline = list(store.query_window(before_start, boundary))
    recent = list(store.query_window(boundary, after_end))

    detector = ZTestDetector()
    changepoint = detector.detect(baseline, recent)

    if changepoint is None:
        return score([], ground_truth)

    all_traces = baseline + recent
    hypotheses = engine.diagnose(all_traces, changepoint)
    return score(hypotheses, ground_truth)


def summarize(fault_type: str, runs: list[ScoredRun]) -> dict:
    n = len(runs)
    if fault_type == "null":
        # top1_correct/key_only_correct are the wrong question here -- there's
        # no true factor for a null run to match, so scorer.py correctly (and
        # unavoidably) reports top1_correct=False for every one of these runs
        # regardless of whether the engine behaved correctly. The actual
        # metric that matters: did the engine fire ANY hypothesis when nothing
        # was injected. 
        false_positives = sum(1 for r in runs if r.n_hypotheses > 0)
        return {
            "fault_type": fault_type,
            "n_runs": n,
            "top1_acc": None,
            "key_only_correct": None,
            "no_hypothesis_runs": n - false_positives,
            "false_positive_rate": (false_positives / n) if n else float("nan"),
        }

    top1 = sum(1 for r in runs if r.top1_correct)
    key_only = sum(1 for r in runs if r.key_only_correct)
    no_hyp = sum(1 for r in runs if r.n_hypotheses == 0)
    return {
        "fault_type": fault_type,
        "n_runs": n,
        "top1_acc": (top1 / n) if n else float("nan"),
        "key_only_correct": key_only,
        "no_hypothesis_runs": no_hyp,
        "false_positive_rate": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=20, help="runs per scenario type")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS.keys()),
        default=None,
        help="run only this scenario type; default runs all",
    )
    parser.add_argument("--base-seed", type=int, default=1000)
    parser.add_argument("--config", default="pipeline_config.yaml")
    parser.add_argument("--verbose", action="store_true", help="print each run's result")
    args = parser.parse_args()

    config = load_pipeline_config(args.config)
    engine = UnivariateDiagnosisEngine(config=config)
    if config is not None:
        print(f"(loaded {args.config}: '{config.name}')")
    else:
        print(f"(no {args.config} found -- cause_layer will report 'unknown' throughout)")

    scenario_names = [args.scenario] if args.scenario else sorted(SCENARIOS.keys())

    summary_rows = []
    for name in scenario_names:
        scenario_cls = SCENARIOS[name]
        runs = [run_one(scenario_cls, i, args.base_seed, engine) for i in range(args.n)]

        if args.verbose:
            print(f"\n{name}:")
            for r in runs:
                if r.fault_type == "null":
                    status = "FALSE POSITIVE" if r.n_hypotheses > 0 else "quiet (correct)"
                    print(f"  {r.scenario_id}  n_hypotheses={r.n_hypotheses}  [{status}]")
                else:
                    status = "OK" if r.top1_correct else ("KEY-ONLY" if r.key_only_correct else "MISS")
                    print(f"  {r.scenario_id}  expected={r.expected_factor}  got={r.top_factor}  [{status}]")

        summary_rows.append(summarize(name, runs))

    table = [
        [
            r["fault_type"],
            f"{r['top1_acc']:.2f}" if r["top1_acc"] is not None else "N/A",
            r["key_only_correct"] if r["key_only_correct"] is not None else "N/A",
            r["no_hypothesis_runs"],
            f"{r['false_positive_rate']:.2f}" if r["false_positive_rate"] is not None else "-",
            r["n_runs"],
        ]
        for r in summary_rows
    ]
    print()
    print(
        tabulate(
            table,
            headers=["Fault Type", "Top-1 Acc", "Key-Only Correct", "No-Hypothesis Runs", "FP Rate", "N Runs"],
            tablefmt="github",
        )
    )


if __name__ == "__main__":
    main()