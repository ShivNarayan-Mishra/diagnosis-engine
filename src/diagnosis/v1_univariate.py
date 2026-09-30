
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