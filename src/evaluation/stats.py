"""
Statistics for comparing systems across methodologies, standard library only.

  distributions      normal CDF, chi-square survival function (regularized gamma)
  many systems       Friedman test over methodology cells, Nemenyi critical difference
                     (Demsar 2006, the standard way to compare k systems over N datasets)
  agreement          Kendall's W: do different methodologies rank the systems the same way?
  paired cells       Wilcoxon signed-rank test (exact for small n, normal approximation above)
  sensitivity        eta squared of each methodological factor (share of variance it explains)
  pooling sources    DerSimonian-Laird random-effects meta-analysis with I² heterogeneity

Each function documents its reference; tests check them against published values.
"""

import math
from itertools import combinations
from typing import Dict, Hashable, List, Optional, Sequence, Tuple

from src.evaluation.metrics import average_ranks

# --------------------------------------------------------------- distributions


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _gamma_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) (Numerical Recipes: series for x < a + 1, else continued fraction)."""
    if x <= 0:
        return 1.0
    log_prefix = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1:
        term = total = 1.0 / a
        n = a
        for _ in range(500):
            n += 1
            term *= x / n
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return max(0.0, 1.0 - total * math.exp(log_prefix))
    tiny = 1e-300
    b = x + 1 - a
    c = 1 / tiny
    d = 1 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-15:
            break
    return min(1.0, math.exp(log_prefix) * h)


def chi2_sf(x: float, df: int) -> float:
    """P(X >= x) for a chi-square variable with df degrees of freedom."""
    return _gamma_q(df / 2.0, x / 2.0)


# ------------------------------------------------------ many systems, N cells

# Critical values q_0.05 of the studentized range divided by sqrt(2), k = 2..10 (Demsar 2006, table 5a).
NEMENYI_Q05 = {2: 1.960, 3: 2.343, 4: 2.569, 5: 2.728, 6: 2.850, 7: 2.949, 8: 3.031, 9: 3.102, 10: 3.164}


def rank_matrix(scores: Sequence[Sequence[float]]) -> List[List[float]]:
    """Rows = cells (datasets/methodologies), columns = systems; rank 1 = best (highest score), ties averaged."""
    out = []
    for row in scores:
        ascending = average_ranks([-v for v in row])          # highest score -> rank 1
        out.append(ascending)
    return out


def friedman(scores: Sequence[Sequence[float]]) -> Dict[str, float]:
    """
    Friedman test that all k systems perform alike over N cells (with the tie correction),
    plus the Iman-Davenport F refinement. Returns average ranks and p-values.
    """
    n, k = len(scores), len(scores[0]) if scores else 0
    if n < 2 or k < 2:
        return {"cells": n, "systems": k, "chi2": 0.0, "p_value": 1.0, "average_ranks": []}
    ranks = rank_matrix(scores)
    average = [sum(r[j] for r in ranks) / n for j in range(k)]
    sum_sq = sum(x ** 2 for r in ranks for x in r)
    # Tie-corrected statistic (Conover): (k-1) * (sum R_j^2 - N k (k+1)^2 / 4) / (sum r_ij^2 - N k (k+1)^2 / 4)
    totals = [sum(r[j] for r in ranks) for j in range(k)]
    c = n * k * (k + 1) ** 2 / 4
    denominator = sum_sq - c
    chi2 = (k - 1) * (sum(t ** 2 for t in totals) / n - c) / (denominator / n) if denominator > 0 else 0.0
    p = chi2_sf(chi2, k - 1)
    return {"cells": n, "systems": k, "chi2": chi2, "p_value": p, "average_ranks": average}


def nemenyi_cd(k: int, n: int) -> Optional[float]:
    """Critical difference of average ranks at alpha 0.05 (None outside the tabulated k = 2..10)."""
    q = NEMENYI_Q05.get(k)
    return None if q is None or n < 1 else q * math.sqrt(k * (k + 1) / (6.0 * n))


def kendall_w(rankings: Sequence[Sequence[float]]) -> float:
    """
    Kendall's coefficient of concordance W of m rankings (raters) of the same k items,
    tie-corrected: 0 = no agreement, 1 = identical rankings. Rows = raters (methodologies).
    """
    m, k = len(rankings), len(rankings[0]) if rankings else 0
    if m < 2 or k < 2:
        return 1.0
    ranked = [average_ranks(list(r)) for r in rankings]
    totals = [sum(r[j] for r in ranked) for j in range(k)]
    mean_total = m * (k + 1) / 2
    s = sum((t - mean_total) ** 2 for t in totals)
    ties = 0.0
    for r in ranked:
        counts: Dict[float, int] = {}
        for value in r:
            counts[value] = counts.get(value, 0) + 1
        ties += sum(t ** 3 - t for t in counts.values())
    denominator = m ** 2 * (k ** 3 - k) - m * ties
    return 12 * s / denominator if denominator else 1.0


# ------------------------------------------------------------ paired cells


def wilcoxon_signed_rank(differences: Sequence[float]) -> Dict[str, float]:
    """
    Two-sided Wilcoxon signed-rank test that paired differences are centred on 0
    (zeros dropped). Exact null distribution for n <= 25 - with ties too: average
    ranks are halves at worst, so doubled ranks are integers and the distribution of
    their signed sums is enumerated - normal approximation with tie correction above.
    """
    values = [d for d in differences if d != 0]
    n = len(values)
    if n == 0:
        return {"n": 0, "w_plus": 0.0, "p_value": 1.0}
    ranks = average_ranks([abs(d) for d in values])
    w_plus = sum(r for r, d in zip(ranks, values) if d > 0)
    total = n * (n + 1) / 2
    if n <= 25:
        doubled = [int(round(2 * r)) for r in ranks]
        top = sum(doubled)
        counts = [1] + [0] * top                            # sign assignments giving each doubled W+
        for r in doubled:
            for s in range(top, r - 1, -1):
                counts[s] += counts[s - r]
        observed = int(round(2 * w_plus))
        extreme = min(observed, top - observed)
        tail = sum(counts[: extreme + 1]) / 2 ** n
        p = min(1.0, 2 * tail)
    else:
        mean = total / 2
        tie_groups: Dict[float, int] = {}
        for r in ranks:
            tie_groups[r] = tie_groups.get(r, 0) + 1
        variance = n * (n + 1) * (2 * n + 1) / 24 - sum(t ** 3 - t for t in tie_groups.values()) / 48
        z = (w_plus - mean) / math.sqrt(variance) if variance > 0 else 0.0
        p = min(1.0, 2 * (1 - normal_cdf(abs(z))))
    return {"n": n, "w_plus": w_plus, "p_value": p}


# ------------------------------------------------------------- sensitivity


def eta_squared(values: Sequence[float], factors: Dict[str, Sequence[Hashable]]) -> Dict[str, float]:
    """
    Share of the variance of `values` explained by each factor on its own
    (SS_between / SS_total, main effects). In a balanced design the shares of
    independent factors add up to at most 1; the rest is interaction and noise.
    """
    n = len(values)
    if n < 2:
        return {name: 0.0 for name in factors}
    mean = sum(values) / n
    total = sum((v - mean) ** 2 for v in values)
    shares = {}
    for name, levels in factors.items():
        groups: Dict[Hashable, List[float]] = {}
        for level, value in zip(levels, values):
            groups.setdefault(level, []).append(value)
        between = sum(len(g) * (sum(g) / len(g) - mean) ** 2 for g in groups.values())
        shares[name] = between / total if total > 0 else 0.0
    return shares


# ------------------------------------------------------------- meta-analysis


def random_effects(estimates: Sequence[float], variances: Sequence[float]) -> Dict[str, float]:
    """
    DerSimonian-Laird random-effects pooling of per-source effects (e.g. F1 difference
    between two systems on each corpus). Returns the pooled effect, its 95% CI, the
    between-source variance tau² and the heterogeneity I² (share of variation due to
    real differences between sources rather than sampling error).
    """
    k = len(estimates)
    if k == 0:
        return {"sources": 0, "pooled": 0.0, "ci_low": 0.0, "ci_high": 0.0, "tau2": 0.0, "i2": 0.0, "q": 0.0, "p_value": 1.0}
    variances = [max(v, 1e-12) for v in variances]
    weights = [1 / v for v in variances]
    fixed = sum(w * e for w, e in zip(weights, estimates)) / sum(weights)
    q = sum(w * (e - fixed) ** 2 for w, e in zip(weights, estimates))
    c = sum(weights) - sum(w ** 2 for w in weights) / sum(weights)
    tau2 = max(0.0, (q - (k - 1)) / c) if k > 1 and c > 0 else 0.0
    re_weights = [1 / (v + tau2) for v in variances]
    pooled = sum(w * e for w, e in zip(re_weights, estimates)) / sum(re_weights)
    se = math.sqrt(1 / sum(re_weights))
    i2 = max(0.0, (q - (k - 1)) / q) if k > 1 and q > 0 else 0.0
    z = pooled / se if se > 0 else 0.0
    return {"sources": k, "pooled": pooled, "ci_low": pooled - 1.959964 * se, "ci_high": pooled + 1.959964 * se,
            "tau2": tau2, "i2": i2, "q": q, "p_value": 2 * (1 - normal_cdf(abs(z)))}


def se_from_ci(low: float, high: float, confidence: float = 0.95) -> float:
    """Standard error implied by a symmetric normal CI (used for bootstrap CIs of paired differences)."""
    z = {0.95: 1.959964, 0.9: 1.644854, 0.99: 2.575829}.get(confidence, 1.959964)
    return max(0.0, (high - low) / (2 * z))


def pairwise_tau(rankings: Dict[str, Sequence[float]]) -> Dict[Tuple[str, str], float]:
    """Kendall tau-b between every pair of named rankings of the same items."""
    from src.evaluation.metrics import kendall_tau_b
    return {(a, b): kendall_tau_b(rankings[a], rankings[b]) for a, b in combinations(sorted(rankings), 2)}
