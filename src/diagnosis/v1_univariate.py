"""
Phase 6 addition, on top of the confirmed Phase 4 file: cross-factor ranking
now uses a comparable effect-size scale instead of raw |effect_size|.

THE PROBLEM THIS FIXES (found via RetrievalDegradationScenario, the first
continuous-factor scenario built -- see running_log_phase6.md Entry 3/4):
Hypothesis.effect_size is odds ratio for categorical factors (unbounded,
[0, inf)) and rank-biserial r for continuous factors (bounded [-1, 1]).
Sorting hypotheses by raw abs(effect_size) therefore isn't comparing like
with like -- a categorical factor with a middling-to-large odds ratio can
outrank a genuinely strong continuous association purely because odds
ratio has no ceiling and rank-biserial r does. Confirmed empirically: on
20 seeded RetrievalDegradationScenario runs, 5/20 had a spurious
`intent` categorical hypothesis (a factor untouched by the scenario) rank
above the correctly-detected `retrieval_score` continuous hypothesis,
purely on unbounded-vs-bounded-scale grounds, not because intent was
actually a stronger signal.

THE FIX, per established meta-analysis practice for comparing effect sizes
across different statistical test families -- don't compare heterogeneous
effect sizes directly, convert to a common scale first:
  - Categorical (odds ratio) -> Yule's Q: q = (OR - 1) / (OR + 1).
    Yule's Q is a direct, well-established transform of an odds ratio onto
    the same [-1, +1] scale rank-biserial r already uses (Yule, 1912).
    An alternative in the literature is converting OR to Cohen's d via the
    logit method (ln(OR) / 1.81, per Chinn, S. (2000), "A simple method for
    converting an odds ratio to effect size for use in meta-analysis",
    Statistics in Medicine 19(22):3127-3131) and then d to r -- Yule's Q is
    used here instead because it's a direct one-line transform of the odds
    ratio already being computed, with no intermediate logit/d step and no
    approximation of group-size correction. Both land in the same [-1, +1]
    family; see the `effectsize` R package documentation (Ben-Shachar et
    al., "Convert Between d, r, and Odds Ratio") for the general
    equivalence between these representations.
  - Continuous (rank-biserial r): already on [-1, +1] (Wendt's formula,
    r = 1 - 2U/(n1*n2)) -- used as-is, no conversion needed.

Hypothesis.effect_size ITSELF IS UNCHANGED -- it still reports odds ratio
for categorical and rank-biserial r for continuous, since those are the
interpretable numbers worth showing in evidence output ("odds ratio 14.97"
means something on its own; Yule's Q of 0.87 means less to a human reading
benchmark output). Yule's Q is computed as an internal ranking key only,
also surfaced in the evidence dict for auditability (every number in this
engine's output is supposed to be traceable back to a specific
calculation, per mentor_guide.md's transparency principle -- a hidden
ranking key that isn't visible anywhere would violate that).

Separately worth naming explicitly, since it came up while researching
this fix: "certainty" splits into two different, non-substitutable axes in
this literature -- p-value/FDR-correction answers "is this association
real," effect size answers "how strong is it." This fix only touches the
second axis; the Benjamini-Hochberg correction upstream of this ranking
step is untouched.

Also worth naming: this project's existing top-1/top-3 accuracy benchmark
methodology (from mentor_guide.md, predating this fix) already matches
current published root-cause-analysis benchmark practice -- e.g. a 2026
paper introducing NetCause (arXiv:2606.13543) evaluates with "exact match
accuracy" (top-ranked hypothesis matches ground truth) and Hits@k, capped
at k=5, which is functionally the same discipline. Not a change made here,
just confirmation the existing benchmark design isn't idiosyncratic to
this project.
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

        # (rank_key, Hypothesis) pairs -- rank_key is the comparable-scale
        # value (Yule's Q for categorical, rank-biserial r for continuous,
        # both on [-1, +1]), kept separate from Hypothesis.effect_size
        # (which stays as the interpretable odds-ratio/rank-biserial value
        # reported to the caller -- see module docstring).
        ranked = []
        for r, is_significant in zip(raw_results, reject):
            if not is_significant:
                continue
            layer = "unknown"
            if self.config is not None:
                layer = self.config.factor_layer(r["key"]) or "unknown"
            hypothesis = Hypothesis(
                cause_layer=layer,
                factor=r["factor_label"],
                p_value=r["p_value"],
                effect_size=r["effect_size"],
                evidence=r["evidence"],
            )
            ranked.append((r["rank_key"], hypothesis))

        ranked.sort(key=lambda pair: abs(pair[0]), reverse=True)
        return [hypothesis for _, hypothesis in ranked]

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

        best = None
        for candidate_value in distinct:
            built = self._build_2x2(present, key, candidate_value)
            if built is None:
                continue
            table, evidence = built
            or_value, table_used = self._odds_ratio(table)
            # Yule's Q -- one-line transform of the odds ratio onto the
            # same [-1, +1] scale rank-biserial r uses, so categorical and
            # continuous hypotheses can be ranked against each other on a
            # common scale. See module docstring for the citation trail
            # (Yule, 1912; Chinn, 2000; effectsize package docs). Q=0 at
            # OR=1 (no association), Q>0 when OR>1, Q<0 when OR<1 -- same
            # sign behavior as (OR - 1), just bounded.
            yules_q = (or_value - 1) / (or_value + 1)
            evidence = {**evidence, "yules_q": yules_q}
            try:
                _, p_value, _, _ = chi2_contingency(table_used, correction=False)
            except ValueError:
                continue
            candidate_result = {
                "key": key,
                "factor_label": f"{key}={candidate_value}",
                "p_value": p_value,
                "effect_size": or_value,
                "rank_key": yules_q,
                "evidence": evidence,
            }
            if best is None:
                best = candidate_result
                continue

            is_tied = math.isclose(
                candidate_result["p_value"], best["p_value"], rel_tol=1e-9
            )
            if is_tied:
                # Equivalent to the pre-fix condition
                # (candidate effect_size >= 1 > best effect_size), restated
                # in terms of rank_key's sign since Q=0 corresponds exactly
                # to OR=1: no behavior change here, just consistency with
                # the new comparable-scale value used everywhere else.
                if candidate_result["rank_key"] >= 0 > best["rank_key"]:
                    best = candidate_result
            elif candidate_result["p_value"] < best["p_value"]:
                best = candidate_result

        return best

    def _build_2x2(self, present, key: str, candidate_value: str):
        a = b = c = d = 0
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
            a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
            table = [[a, b], [c, d]]
        odds_ratio = (a * d) / (b * c)
        return odds_ratio, table

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
            # Already on [-1, +1] -- used directly as the comparable
            # ranking key, no conversion needed (see module docstring).
            "rank_key": rank_biserial,
            "evidence": evidence,
        }