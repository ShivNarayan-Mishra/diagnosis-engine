# Phase 3 — ZTestDetector (lean CLI scope)

## What's new in this zip

```
src/detection/ztest_detector.py        <- the actual deliverable: ZTestDetector
tests/detection/test_ztest_detector.py <- 4 unit tests, no DB required
scripts/run_detector_check.py          <- CLI tool to run it against real Postgres data
```

Everything else in this zip (`records.py`, `interfaces.py`, `postgres.py`, `generator.py`)
is **your existing Phase 1/2 files, copied in unchanged** — included only so the zip is
self-contained and importable on its own. Do NOT overwrite your real copies with these;
they should be byte-for-byte identical to what you already have (they were built directly
from what you pasted). If `diff` shows any difference, trust your existing files, not these.

## Install (merge, non-destructive — same pattern as Phase 1/2)

```bash
cd ~/projects/diagnosis-engine
unzip ~/Downloads/phase3_diagnosis_engine.zip -d /tmp/phase3_unzip
cp -rn /tmp/phase3_unzip/* .
```

`-n` = never overwrite existing files. The only genuinely new paths this adds are
`src/detection/ztest_detector.py`, `tests/detection/`, and `scripts/run_detector_check.py`
— nothing else should land.

## Verify — no DB needed for this part

```bash
source .venv/bin/activate
pytest tests/detection/test_ztest_detector.py -v
```

Expected: `4 passed`. These tests use your real `TraceGenerator` in-memory — no Postgres,
no Docker required to run them.

## Verify against real data — DB required

Run your usual start-of-session routine first (Docker up, port-conflict check, etc. — see
your running log's Environment Routine section). Then, once you've got some traces in the
DB spanning a known-ish shift (e.g. from a Phase 2 scenario run, or from
`scripts/seed_stable_traces.py` for a null case):

```bash
python scripts/run_detector_check.py \
    --baseline-start 2024-01-01T00:00:00+00:00 \
    --baseline-end   2024-01-01T00:05:00+00:00 \
    --recent-start   2024-01-01T00:05:00+00:00 \
    --recent-end     2024-01-01T00:10:00+00:00
```

Swap in real timestamps that bracket a scenario you already ran (check `fault_scenarios`
table for `injected_at`, or eyeball `traces` in SQLTools for where the failure rate jumps).

Two things worth checking by eye once you run this for real:
1. On a window that brackets a `ToolRegressionScenario` or `ModelSwapScenario` injection —
   should print "Changepoint detected" with `after_rate` clearly higher than `before_rate`.
2. On two windows of stable, non-faulty traffic (e.g. both from `seed_stable_traces.py`) —
   should print "No significant shift detected."

If (1) doesn't fire or (2) fires when it shouldn't, that's real signal something's off with
either the window boundaries you picked or the underlying data — not a reason to distrust
the detector math itself, which is unit-tested and passing.

## What this class deliberately does NOT do

Explained in the docstring in `ztest_detector.py`, repeating here because it's the kind of
thing worth having ready verbally: this class does **not** implement the
`ChangepointDetector` ABC from `src/contracts/interfaces.py`. That ABC's `detect()` expects
one continuous series and returns possibly-many changepoints (a rolling-scan shape).
`ZTestDetector.detect()` takes two explicit windows and returns at most one `Changepoint`.
Forcing it to inherit the ABC would mean either lying about the signature or building the
rolling scanner the lean scope explicitly cut. Left it as a standalone class instead —
still a seam in spirit (swap the statistical test inside `detect()` without touching
callers), just not literally wearing the old ABC's interface.

## Next: Phase 4

`UnivariateDiagnosisEngine` — already written and verified against a stubbed contracts
file in an earlier pass of this conversation, but **not yet re-verified against these
real pasted files** the way this Phase 3 delivery was. Recommend doing that
re-verification pass before treating Phase 4 as done — same discipline as this delivery,
not the Phase 2 Entry 2/3 mistake of shipping against a guess.
