"""
Metrics for the evaluation tasks, standard library only.

  links           precision / recall / F1 (micro over pairs, macro over source documents)
  classification  purity, inverse purity, NMI (arithmetic normalization), adjusted Rand index
  ranking         Spearman rho, Kendall tau-b (Knight's O(n log n)), NDCG@k
  uncertainty     percentile bootstrap over documents, paired bootstrap for differences

Conventions (stated once, used everywhere): precision with no prediction is 0,
recall with no gold item is undefined (the unit is skipped for macro averages),
rank correlations use average ranks for ties, NDCG breaks score ties by id so
results never depend on input order.
"""

import math
import random
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, Hashable, List, Optional, Sequence, Set, Tuple

# ----------------------------------------------------------------- links


@dataclass(frozen=True)
class LinkCounts:
    """Per-unit (source document) counts; summing them gives micro metrics."""
    tp: int
    predicted: int
    gold: int

    def __add__(self, other: "LinkCounts") -> "LinkCounts":
        return LinkCounts(self.tp + other.tp, self.predicted + other.predicted, self.gold + other.gold)


def link_counts(predicted: Set, gold: Set) -> LinkCounts:
    return LinkCounts(len(predicted & gold), len(predicted), len(gold))


def prf(counts: LinkCounts) -> Tuple[float, float, float]:
    precision = counts.tp / counts.predicted if counts.predicted else 0.0
    recall = counts.tp / counts.gold if counts.gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def micro_prf(units: Sequence[LinkCounts]) -> Tuple[float, float, float]:
    total = LinkCounts(0, 0, 0)
    for unit in units:
        total = total + unit
    return prf(total)


def macro_prf(units: Sequence[LinkCounts]) -> Tuple[float, float, float]:
    """Mean per-document precision (documents with predictions) and recall (documents with gold)."""
    precisions = [u.tp / u.predicted for u in units if u.predicted]
    recalls = [u.tp / u.gold for u in units if u.gold]
    precision = sum(precisions) / len(precisions) if precisions else 0.0
    recall = sum(recalls) / len(recalls) if recalls else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


# -------------------------------------------------------- classification


def _contingency(truth: Sequence[Hashable], clusters: Sequence[Hashable]) -> Tuple[Counter, Counter, Counter]:
    if len(truth) != len(clusters):
        raise ValueError("truth and clusters must have the same length")
    return Counter(zip(truth, clusters)), Counter(truth), Counter(clusters)


def purity(truth: Sequence[Hashable], clusters: Sequence[Hashable]) -> float:
    """Share of documents in the majority true class of their cluster (1 cluster per doc scores 1)."""
    joint, _, by_cluster = _contingency(truth, clusters)
    best: Dict[Hashable, int] = {}
    for (_, cluster), n in joint.items():
        best[cluster] = max(best.get(cluster, 0), n)
    return sum(best.values()) / len(truth) if truth else 0.0


def inverse_purity(truth: Sequence[Hashable], clusters: Sequence[Hashable]) -> float:
    """Purity with the roles swapped: penalizes splitting a class (1 cluster for all scores 1)."""
    return purity(clusters, truth)


def nmi(truth: Sequence[Hashable], clusters: Sequence[Hashable]) -> float:
    """Normalized mutual information, arithmetic-mean normalization (0 = independent, 1 = identical)."""
    n = len(truth)
    if n == 0:
        return 0.0
    joint, by_truth, by_cluster = _contingency(truth, clusters)
    mutual = sum(c / n * math.log(c * n / (by_truth[t] * by_cluster[k])) for (t, k), c in joint.items())
    entropy = lambda counts: -sum(c / n * math.log(c / n) for c in counts.values())
    h_truth, h_cluster = entropy(by_truth), entropy(by_cluster)
    if h_truth == 0 and h_cluster == 0:
        return 1.0
    denominator = (h_truth + h_cluster) / 2
    return max(0.0, mutual / denominator) if denominator else 0.0


def adjusted_rand_index(truth: Sequence[Hashable], clusters: Sequence[Hashable]) -> float:
    """Rand index corrected for chance (0 = random labelling, 1 = identical partitions)."""
    n = len(truth)
    if n < 2:
        return 1.0
    joint, by_truth, by_cluster = _contingency(truth, clusters)
    pairs = lambda x: x * (x - 1) / 2
    index = sum(pairs(c) for c in joint.values())
    a, b = sum(pairs(c) for c in by_truth.values()), sum(pairs(c) for c in by_cluster.values())
    expected = a * b / pairs(n)
    maximum = (a + b) / 2
    if maximum == expected:
        return 1.0
    return (index - expected) / (maximum - expected)


# ------------------------------------------------------------- ranking


def average_ranks(values: Sequence[float]) -> List[float]:
    """1-based ranks, ties get the average of the ranks they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else 0.0


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    return pearson(average_ranks(x), average_ranks(y))


def _merge_count(values: List[float]) -> int:
    """Sort in place (merge sort) and return the number of strict inversions."""
    if len(values) < 2:
        return 0
    mid = len(values) // 2
    left, right = values[:mid], values[mid:]
    swaps = _merge_count(left) + _merge_count(right)
    i = j = k = 0
    while i < len(left) and j < len(right):
        if right[j] < left[i]:
            values[k] = right[j]
            swaps += len(left) - i
            j += 1
        else:
            values[k] = left[i]
            i += 1
        k += 1
    values[k:] = left[i:] + right[j:]
    return swaps


def kendall_tau_b(x: Sequence[float], y: Sequence[float]) -> float:
    """Kendall's tau-b (tie-corrected) with Knight's O(n log n) algorithm."""
    n = len(x)
    if n < 2:
        return 0.0
    pairs = sorted(zip(x, y))
    total = n * (n - 1) // 2

    def tied(values) -> int:
        return sum(c * (c - 1) // 2 for c in Counter(values).values())

    ties_x, ties_y, ties_xy = tied(x), tied(y), tied(pairs)
    ys = [b for _, b in pairs]
    # Within runs of equal x, y must be sorted so those pairs do not count as discordant.
    i = 0
    while i < n:
        j = i
        while j + 1 < n and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        ys[i:j + 1] = sorted(ys[i:j + 1])
        i = j + 1
    discordant = _merge_count(ys)
    concordant_minus_discordant = total - ties_x - ties_y + ties_xy - 2 * discordant
    denominator = math.sqrt((total - ties_x) * (total - ties_y))
    return concordant_minus_discordant / denominator if denominator else 0.0


def ndcg_at_k(ids: Sequence[str], scores: Sequence[float], relevance: Sequence[float], k: int) -> float:
    """NDCG@k of ranking `ids` by `scores` (descending, ties by id) against graded `relevance` >= 0."""
    if not ids:
        return 0.0
    order = sorted(range(len(ids)), key=lambda i: (-scores[i], ids[i]))
    dcg = sum(relevance[i] / math.log2(rank + 2) for rank, i in enumerate(order[:k]))
    ideal = sorted(relevance, reverse=True)[:k]
    idcg = sum(rel / math.log2(rank + 2) for rank, rel in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


# ---------------------------------------------------------- uncertainty


@dataclass(frozen=True)
class Estimate:
    value: float
    low: float
    high: float

    def __str__(self) -> str:
        return f"{self.value:.3f} [{self.low:.3f}, {self.high:.3f}]"

    def as_dict(self) -> Dict[str, float]:
        return {"value": round(self.value, 6), "ci_low": round(self.low, 6), "ci_high": round(self.high, 6)}


def _percentile(sorted_values: List[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    position = q * (len(sorted_values) - 1)
    low, high = math.floor(position), math.ceil(position)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def bootstrap(units: Sequence, statistic: Callable[[Sequence], float], resamples: int = 1000,
              seed: int = 0, confidence: float = 0.95) -> Estimate:
    """Percentile bootstrap CI of statistic(units), resampling units with replacement."""
    value = statistic(units)
    if len(units) < 2 or resamples <= 0:
        return Estimate(value, value, value)
    rng = random.Random(seed)
    n = len(units)
    draws = sorted(statistic([units[rng.randrange(n)] for _ in range(n)]) for _ in range(resamples))
    tail = (1 - confidence) / 2
    return Estimate(value, _percentile(draws, tail), _percentile(draws, 1 - tail))


@dataclass(frozen=True)
class Comparison:
    difference: Estimate          # statistic(A) - statistic(B)
    p_not_better: float           # share of resamples where A does not beat B (one-sided)

    @property
    def verdict(self) -> str:
        if self.difference.low > 0:
            return "better"
        if self.difference.high < 0:
            return "worse"
        return "not significant"

    def as_dict(self) -> Dict[str, object]:
        return {**self.difference.as_dict(), "p_not_better": round(self.p_not_better, 4), "verdict": self.verdict}


def paired_bootstrap(units: Sequence, statistic_a: Callable[[Sequence], float],
                     statistic_b: Callable[[Sequence], float], resamples: int = 1000, seed: int = 0,
                     confidence: float = 0.95) -> Comparison:
    """
    Difference of two systems evaluated on the same units: both statistics are
    computed on each resample, so unit difficulty cancels out (paired design).
    """
    value = statistic_a(units) - statistic_b(units)
    if len(units) < 2 or resamples <= 0:
        return Comparison(Estimate(value, value, value), 0.0 if value > 0 else 1.0)
    rng = random.Random(seed)
    n = len(units)
    draws = []
    for _ in range(resamples):
        sample = [units[rng.randrange(n)] for _ in range(n)]
        draws.append(statistic_a(sample) - statistic_b(sample))
    draws.sort()
    tail = (1 - confidence) / 2
    return Comparison(Estimate(value, _percentile(draws, tail), _percentile(draws, 1 - tail)), _p_value(draws))


def _p_value(differences: Sequence[float]) -> float:
    """One-sided bootstrap p-value of "A beats B": (resamples where A does not + 1) / (resamples + 1), never 0."""
    return (sum(1 for d in differences if d <= 0) + 1) / (len(differences) + 1)


# Shared resamples ("common random numbers"): every system is evaluated on the same
# bootstrap draws, so CIs and paired differences come from one pass and the paired
# differences have lower variance than with independent draws.


def resamples(n: int, count: int, seed: int) -> List[List[int]]:
    rng = random.Random(seed)
    return [[rng.randrange(n) for _ in range(n)] for _ in range(count)] if n >= 2 else []


def estimate_from(value: float, draws: Sequence[float], confidence: float = 0.95) -> Estimate:
    if not draws:
        return Estimate(value, value, value)
    ordered = sorted(draws)
    tail = (1 - confidence) / 2
    return Estimate(value, _percentile(ordered, tail), _percentile(ordered, 1 - tail))


def compare_from(value_a: float, value_b: float, draws_a: Sequence[float], draws_b: Sequence[float],
                 confidence: float = 0.95) -> Comparison:
    differences = [a - b for a, b in zip(draws_a, draws_b)]
    value = value_a - value_b
    if not differences:
        return Comparison(Estimate(value, value, value), 0.0 if value > 0 else 1.0)
    return Comparison(estimate_from(value, differences, confidence), _p_value(differences))


def label_of(labels: Optional[Sequence[str]]) -> Optional[str]:
    """Primary label of a document (first listed), None when it has none."""
    return labels[0] if labels else None
