# AI Pipeline Regression Diagnosis Engine

Statistical tool that figures out *why* an AI pipeline's failure rate spiked —
was it the model, retrieval, a tool call, the taxonomy, or infra — using
actual hypothesis testing instead of asking an LLM to eyeball some traces and
guess. Most "AI observability" stuff does the guess-and-summarize thing with
no real accuracy number attached. This one does chi-square/Mann-Whitney tests
on injected faults and reports how often it's actually right, including how
often it cries wolf when nothing's wrong.

## What it actually does

Feed it traces (request_id, timestamp, success/fail, plus a free-form
`factors` dict — whatever your pipeline logs). It watches for a shift in
failure rate between two windows, and if it finds one, tests every factor in
that bag to see which one correlates with the failures. Categorical stuff
(tool_version, model_version) gets chi-square + odds ratio. Continuous stuff
(retrieval_score) gets Mann-Whitney since you can't chi-square a float
without making up bucket boundaries. Everything gets Benjamini-Hochberg
correction because testing 20 factors at once and NOT correcting for that is
just p-hacking yourself by accident.

```
raw traces
   |
   v
IngestAdapter  ->  TraceStore  ->  ChangepointDetector  ->  DiagnosisEngine
                                                                  |
                                                                  v
                                                        ranked list[Hypothesis]
                                                     (p-value, effect_size, layer)
```

Four seams, each one an ABC you can swap the implementation behind. Small
honest asterisk: the detector I actually built (`ZTestDetector`) takes two
windows and compares them directly instead of scanning a rolling series like
the original interface wanted — I changed my mind on the design partway
through and just didn't force it to pretend to implement the old signature.
It says so right in its own docstring instead of me hiding it.

## Results

Ran 20 seeded scenarios per fault type:

| Fault Type              | Top-1 Acc | Key-Only | No-Hyp | FP Rate | N  |
|--------------------------|-----------|----------|--------|---------|----|
| infra_noise              | 1.00      | 0        | 0      | –       | 20 |
| model_swap               | 1.00      | 0        | 0      | –       | 20 |
| null (no fault)          | N/A       | N/A      | 20     | 0.00    | 20 |
| retrieval_degradation    | 1.00      | 0        | 0      | –       | 20 |
| taxonomy_drift           | 1.00      | 0        | 0      | –       | 20 |
| tool_regression          | 1.00      | 0        | 0      | –       | 20 |

The null row matters more than the five perfect scores above it. A tool that
nails every real fault but also screams at random noise half the time is
useless. At n=200 the detector on its own fires on pure noise about 6% of the
time (that's just alpha=0.05 doing its thing, not a bug) but zero of those
turned into an actual reported hypothesis, because FDR correction catches it
downstream. I'm not going to pretend that means the true false-positive rate
is literally zero forever — the synthetic generator only has a couple of
factors that could even produce a spurious hit right now — but it's a real
number from a real run, not something I made up to look good.

## A bug that actually got me

Chi-square on a two-value factor gives you the identical p-value no matter
which value you call "the bad one" — only the odds ratio flips upside down.
First version of the diagnosis engine picked whichever value sorted
alphabetically first as "the cause," which meant for `tool_version` going
2.3→2.4 it confidently told me 2.3 was the problem. Backwards. Fixed it to
test both directions and pick by p-value... except then a tie-break using
`==` on two p-values that were mathematically identical but not
bit-identical floating point (yeah, that's a thing) kept silently breaking
the same way. `math.isclose()` fixed it for real. Twice-broken bug, learned
the float-equality lesson the annoying way.

Also had a fun one where two brand new test files kept getting a growing
number of "extra" traces every time I re-ran them (182, then 385, then 579)
— turned out they were querying the real Postgres table by timestamp only,
and every other test in the same pytest run was writing traces into that
same table around the same wall-clock time. Swapped those tests to an
in-memory store instead of tightening the assertion, since tightening it
would've just meant it breaks again later once the table's bigger.

More debugging war stories (a genuinely dumb four-round saga with a rogue
Postgres process squatting on port 5432) are in `tools_explained.md` if you
care.

## Does it work on real data, not just data I made up?

Ran it against an actual 40-row export from a real customer-support pipeline
I'd built earlier. Failure rate roughly doubled across a real ~2-hour gap in
traffic (10% → 23%) but the engine correctly said "not significant" (p≈0.45)
— because honestly, with 10 traces on one side, that gap could easily be
noise. I'd rather it stay quiet than make something up from 10 data points.

Real data is messier than synthetic data, obviously. This export had a
`fallback_reason` column where hallucinated-order-ID failures each had a
different specific fake ID embedded in the string, so every single one
looked like its own unique category to a naive mapping — useless for a
chi-square test with n=1 each. Had to derive it down into a plain boolean
(did this response hallucinate an ID: yes/no) before it meant anything
statistically.

## What I cut

Started this bigger than it ended up. Cut, and why:

- HTTP API (`/diagnose`, `/benchmark/run` routes) — became CLI scripts, way
  less to maintain, same statistical content
- confounded-fault scenarios (two faults injected at once) — real, harder
  problem, didn't have time to do it properly
- a v2 logistic-regression engine — existed specifically to fix confounding,
  so once confounded scenarios got cut there was nothing for it to prove
- stack-trace parsing adapter — assume error_type comes in clean
- LLM narration on top of the output — was always a "maybe at the end" thing
- `ruptures` fallback detector — was a fallback for a rolling detector I
  ended up not building

Kept the FDR correction on purpose even though everything else statistical
got trimmed, because the null scenario benchmark is meaningless without it —
you can't publish a false-positive rate you didn't actually control for.

None of the cut stuff is structurally hard to add back later — the seams are
built so a v2 engine, a confounded scenario, whatever, plugs in the same way
the five existing fault scenarios did (new class, one import, one registry
line). Cutting scope meant not building it yet, not that the code fights you
if you want to.

## Complexity

Ingest is O(1) per event. Diagnosis is O(window size), not O(how much history
you have — there's a Postgres index on (timestamp, branch) doing the actual
work there, so a 1-hour query costs the same whether the table has 10k rows
or 10 million.

## Running it

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d

pytest tests/ -v
python scripts/run_benchmark.py --n 20
python scripts/replay_offline_logs.py --csv full_db_dump.csv
```

## What's still open

- v2 engine for confounded faults, whenever that scenario type exists
- an actual rolling-window detector alongside the two-window one
- LLM narration wrapping the finished hypothesis in a sentence, not computing
  anything itself
- re-checking the offline replay config once a real export with retrieval
  data actually exists (this one's retrieval columns were all empty — that
  instrumentation isn't wired up yet on the source pipeline's side)

