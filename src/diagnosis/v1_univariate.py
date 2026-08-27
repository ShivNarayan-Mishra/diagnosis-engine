"""
src/diagnosis/v1_univariate.py

Phase 4 — UnivariateDiagnosisEngine.

Implements the real DiagnosisEngine ABC (confirmed from the actual pasted
interfaces.py, not the earlier guessed sketch mentioned in session_wrapup.md):

    def diagnose(self, traces: list[TraceRecord], changepoint: Changepoint) -> list[Hypothesis]

Design notes / deliberate deviations from the original plan doc's phrasing,
stated explicitly rather than buried:

1. Before/after split.
   The ABC hands this engine one flat trace list plus a single Changepoint —
   not two pre-split windows. Split here is:
       before = t.timestamp <  changepoint.timestamp
       after  = t.timestamp >= changepoint.timestamp
   This matches how ZTestDetector picks its own changepoint timestamp
   (min(t.timestamp for t in recent)) — so "after" here is exactly the set
   ZTestDetector called "recent", by construction. If diagnose() is ever
   called with a Changepoint that didn't come from ZTestDetector run over
   the same trace list, this assumption should be re-checked.

2. Per-factor "which value counts as the candidate" selection.
   The plan doc says categorical factors get "chi-square on a 2x2 table
   (dominant value vs rest)" without defining "dominant." Picking "most
   frequent value overall" would, in a realistic isolated-fault scenario
   (large before-window, partial after-window rollout), often just re-select
   the untouched baseline value as "dominant" — that would make the engine
   blind to the actual injected fault by construction, which defeats the
   point. So instead: every distinct value of the factor is tested against
   "everything else," and the value with the strongest raw signal (smallest
   p-value) is kept as that factor's one representative Hypothesis.

   CONFIRMED BUG, CAUGHT DURING SANDBOX VERIFICATION, NOW FIXED: an earlier
   version of this method only tested every distinct value when there were
   more than two of them, and for the common two-value case (e.g.
   tool_version has exactly "2.3" and "2.4") just picked
   sorted(distinct)[0] — the alphabetically-first value — as the only
   candidate, with no regard for which one was actually the injected fault.
   That's a real problem specifically because a 2x2 chi-square test gives
   the IDENTICAL p-value regardless of which value is labeled "present"
   (only the odds ratio flips, to its reciprocal) — so "alphabetically
   first" was silently deciding the outcome 100% of the time in the
   two-value case, independent of the data. Caught in Scenario A of the
   sandbox verification: with tool_version injected as "2.3" -> "2.4", the
   engine reported "tool_version=2.3" (odds ratio 0.028, i.e. protective)
   as the top hypothesis instead of "tool_version=2.4" (the actual fault).
   Statistically not wrong — 2.3 being protective and 2.4 being harmful are
   the same underlying fact — but backwards for the interview-facing
   labeling, and would have silently mislabeled every two-valued categorical
   fault in the benchmark.

   Fix: every distinct value is always tested (not just when there are more
   than two). Selection is by smallest p-value first; ties (which the
   two-value case will always produce, since both directions share one
   p-value) are broken by preferring the direction with odds_ratio > 1 — the
   "this value increases failure risk" framing, which is what a Hypothesis
   is supposed to communicate.

3. Only `factors` dict keys are scanned — not `branch` / `latency_ms`
   directly. Matches the original plan's "iterate factors.keys() dynamically"
   language. branch/latency_ms are first-class TraceRecord fields, not part
   of the open bag; out of scope here unless a pipeline logs them into
   `factors` itself.

4. FDR correction scope.
   Benjamini-Hochberg is applied across one p-value per factor key (the
   representative value chosen per note 2), not across every individual
   value tested while searching for that representative. Testing multiple
   values to pick the best one is a selection step, not multiple separate
   hypotheses being reported — only the hypothesis that actually gets
   surfaced per factor enters the correction. This keeps the correction
   sized to the number of claims actually being made, which is the FDR-
   correction stated in mentor_guide.md, but it's a specific choice worth
   being able to name in an interview.

5. cause_layer defaults to "unknown" when no pipeline_config.yaml is present
   or a factor key isn't declared in it. No hardcoded name-pattern guessing
   (e.g. no special-casing "tool_version" -> "tool") — that would silently
   reintroduce pipeline-specific logic into what's supposed to be a
   pipeline-agnostic engine.
"""
from __future__ import annotations

import math

from scipy.stats import chi2_contingency, mannwhitneyu
from statsmodels.stats.multitest import multipletests

from src.config.loader import PipelineConfig
from src.contracts.interfaces import DiagnosisEngine
from src.contracts.records import Changepoint, Hypothesis, TraceRecord

_MISSING = object()


class UnivariateDiagnosisEngine(DiagnosisEngine):
    def __init__(
        self,
        config: PipelineConfig | None = None,
        alpha: float = 0.05,
    ) -> None:
        self.config = config
        self.alpha = alpha

    def diagnose(
        self, traces: list[TraceRecord], changepoint: Changepoint
    ) -> list[Hypothesis]:
        before = [t for t in traces if t.timestamp < changepoint.timestamp]
        after = [t for t in traces if t.timestamp >= changepoint.timestamp]

        if not before or not after:
            return []

        combined = before + after

        factor_keys: set[str] = set()
        for t in combined:
            factor_keys.update(t.factors.keys())

        raw_results = []
        for key in sorted(factor_keys):
            factor_type = self._resolve_type(key, combined)
            if factor_type == "categorical":
                result = self._test_categorical(key, combined)
            elif factor_type == "continuous":
                result = self._test_continuous(key, combined)
            else:
                result = None
            if result is not None:
                raw_results.append(result)

        if not raw_results:
            return []

        pvalues = [r["p_value"] for r in raw_results]
        reject, _, _, _ = multipletests(pvalues, alpha=self.alpha, method="fdr_bh")

        hypotheses = []
        for r, is_significant in zip(raw_results, reject):
            if not is_significant:
                continue
            layer = "unknown"
            if self.config is not None:
                layer = self.config.factor_layer(r["key"]) or "unknown"
            hypotheses.append(
                Hypothesis(
                    cause_layer=layer,
                    factor=r["factor_label"],
                    p_value=r["p_value"],
                    effect_size=r["effect_size"],
                    evidence=r["evidence"],
                )
            )

        hypotheses.sort(key=lambda h: abs(h.effect_size), reverse=True)
        return hypotheses

    # ---- type resolution ---------------------------------------------------

    def _resolve_type(self, key: str, combined: list[TraceRecord]) -> str | None:
        if self.config is not None:
            declared = self.config.factor_type(key)
            if declared is not None:
                return declared

        for t in combined:
            v = t.factors.get(key, _MISSING)
            if v is _MISSING or v is None:
                continue
            if isinstance(v, bool):
                return "categorical"
            if isinstance(v, (int, float)):
                return "continuous"
            return "categorical"
        return None

    # ---- categorical factors ------------------------------------------------

    def _test_categorical(self, key: str, combined: list[TraceRecord]) -> dict | None:
        present = [
            (t, t.factors.get(key, _MISSING))
            for t in combined
        ]
        present = [(t, v) for t, v in present if v is not _MISSING and v is not None]
        if len(present) < 4:
            return None

        distinct = sorted({str(v) for _, v in present})
        if len(distinct) < 2:
            return None

        # Always test every distinct value — see note 2 in the module
        # docstring for why short-circuiting the 2-value case was a bug.
        best = None
        for candidate_value in distinct:
            built = self._build_2x2(present, key, candidate_value)
            if built is None:
                continue
            table, evidence = built
            or_value, table_used = self._odds_ratio(table)
            try:
                _, p_value, _, _ = chi2_contingency(table_used, correction=False)
            except ValueError:
                continue
            candidate_result = {
                "key": key,
                "factor_label": f"{key}={candidate_value}",
                "p_value": p_value,
                "effect_size": or_value,
                "evidence": evidence,
            }
            if best is None:
                best = candidate_result
                continue

            # Smallest p-value wins. "Tied" is checked with a relative
            # tolerance, not `==` — two complementary directions on the same
            # 2x2 table produce p-values equal in theory but not bit-for-bit
            # equal in floating point (confirmed during sandbox verification:
            # 1.9629191563990977e-24 vs 1.9629191563991113e-24 for the same
            # underlying counts, same data, opposite direction). An exact
            # `==` check silently never fires, and "smallest wins" then
            # picks whichever side floating-point noise happens to favor —
            # which is exactly the bug this tie-break exists to prevent, so
            # it has to tolerate the noise, not just check for identical
            # values.
            is_tied = math.isclose(
                candidate_result["p_value"], best["p_value"], rel_tol=1e-9
            )
            if is_tied:
                if candidate_result["effect_size"] >= 1 > best["effect_size"]:
                    best = candidate_result
                # else: keep current best (already >=1, or neither is >=1)
            elif candidate_result["p_value"] < best["p_value"]:
                best = candidate_result

        return best

    def _build_2x2(self, present, key: str, candidate_value: str):
        a = b = c = d = 0  # failure|present, success|present, failure|absent, success|absent
        for t, v in present:
            is_candidate = str(v) == candidate_value
            is_failure = t.outcome == "failure"
            if is_candidate and is_failure:
                a += 1
            elif is_candidate and not is_failure:
                b += 1
            elif not is_candidate and is_failure:
                c += 1
            else:
                d += 1

        if (a + b) == 0 or (c + d) == 0:
            return None

        table = [[a, b], [c, d]]
        evidence = {
            "factor": key,
            "value": candidate_value,
            "failures_with_value": a,
            "successes_with_value": b,
            "failures_without_value": c,
            "successes_without_value": d,
        }
        return table, evidence

    def _odds_ratio(self, table: list[list[float]]) -> tuple[float, list[list[float]]]:
        a, b = table[0]
        c, d = table[1]
        if 0 in (a, b, c, d):
            # Haldane-Anscombe correction — only when a zero cell would
            # otherwise make the ratio divide-by-zero/undefined. Not applied
            # unconditionally since it slightly biases every ratio toward 1.
            a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
            table = [[a, b], [c, d]]
        odds_ratio = (a * d) / (b * c)
        return odds_ratio, table

    # ---- continuous factors --------------------------------------------------

    def _test_continuous(self, key: str, combined: list[TraceRecord]) -> dict | None:
        failure_vals = []
        success_vals = []
        for t in combined:
            v = t.factors.get(key, _MISSING)
            if v is _MISSING or v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if t.outcome == "failure":
                failure_vals.append(v)
            else:
                success_vals.append(v)

        if len(failure_vals) < 2 or len(success_vals) < 2:
            return None

        try:
            u_stat, p_value = mannwhitneyu(
                failure_vals, success_vals, alternative="two-sided"
            )
        except ValueError:
            return None

        n1, n2 = len(failure_vals), len(success_vals)
        rank_biserial = 1 - (2 * u_stat) / (n1 * n2)

        evidence = {
            "factor": key,
            "n_failure": n1,
            "n_success": n2,
            "median_failure": sorted(failure_vals)[n1 // 2],
            "median_success": sorted(success_vals)[n2 // 2],
        }

        return {
            "key": key,
            "factor_label": key,
            "p_value": p_value,
            "effect_size": rank_biserial,
            "evidence": evidence,
        }