"""
Topic clustering of pages without configuration, standard library only.

Two methods that use unrelated signals (so agreement between them means something):

  content    TF-IDF vectors of the page text, spherical k-means (cosine),
             k-means++ seeding; deterministic for a given seed
  structure  label propagation over the undirected link graph (pages that
             link to each other end up together); uses no text at all

Both return {page id: cluster name}. They can feed SiteTaxonomy(assignments=...)
so the link flow uses topic boundaries on sites without a hand-written taxonomy.
"""

import math
import random
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.engines.text import is_content_token, tokenize

Vector = Dict[str, float]


def tfidf_vectors(texts: Sequence[str], min_df: int = 2, max_df_ratio: float = 0.5,
                  max_terms: int = 60) -> List[Vector]:
    """
    L2-normalized TF-IDF vectors (sublinear tf, smooth idf). Terms in fewer than
    min_df documents or in more than max_df_ratio of them are dropped; each vector
    keeps its max_terms heaviest terms (bounds the cost of k-means on long pages).
    """
    counts = [Counter(t for t in tokenize(text) if is_content_token(t) and len(t) > 2) for text in texts]
    df = Counter(term for c in counts for term in c)
    n = len(texts)
    ceiling = max(min_df, max_df_ratio * n)
    idf = {term: math.log((1 + n) / (1 + d)) + 1 for term, d in df.items() if min_df <= d <= ceiling}
    vectors = []
    for c in counts:
        weights = {t: (1 + math.log(f)) * idf[t] for t, f in c.items() if t in idf}
        top = dict(sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[:max_terms])
        norm = math.sqrt(sum(w * w for w in top.values()))
        vectors.append({t: w / norm for t, w in top.items()} if norm else {})
    return vectors


def _dot(a: Vector, b: Vector) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(t, 0.0) for t, w in a.items())


def _normalize(vector: Vector) -> Vector:
    norm = math.sqrt(sum(w * w for w in vector.values()))
    return {t: w / norm for t, w in vector.items()} if norm else {}


CENTROID_TERMS = 200   # centroids keep their heaviest terms (sparse centroids: standard for large text sets)


def _truncate(vector: Vector, size: int = CENTROID_TERMS) -> Vector:
    if len(vector) <= size:
        return vector
    return _normalize(dict(sorted(vector.items(), key=lambda kv: (-kv[1], kv[0]))[:size]))


def spherical_kmeans(vectors: Sequence[Vector], k: int, seed: int = 0, iterations: int = 25) -> List[int]:
    """
    Cluster index per vector; empty vectors go to cluster 0. Assignment scores all
    centroids at once through an inverted index of the (sparse) centroids.
    """
    n = len(vectors)
    if n == 0:
        return []
    k = max(1, min(k, n))
    rng = random.Random(seed)
    # k-means++ seeding on cosine distance.
    centers = [dict(vectors[rng.randrange(n)])]
    nearest = [1.0 - _dot(v, centers[0]) for v in vectors]
    while len(centers) < k:
        total = sum(d * d for d in nearest)
        if total <= 0:
            break
        pick, acc = rng.random() * total, 0.0
        chosen = n - 1
        for i, d in enumerate(nearest):
            acc += d * d
            if acc >= pick:
                chosen = i
                break
        centers.append(dict(vectors[chosen]))
        nearest = [min(old, 1.0 - _dot(v, centers[-1])) for old, v in zip(nearest, vectors)]
    centers = [_truncate(c) for c in centers]
    assignment = [-1] * n
    for _ in range(iterations):
        postings: Dict[str, List[Tuple[int, float]]] = defaultdict(list)
        for c, center in enumerate(centers):
            for t, w in center.items():
                postings[t].append((c, w))
        changed = False
        for i, v in enumerate(vectors):
            scores = [0.0] * len(centers)
            for t, w in v.items():
                for c, cw in postings.get(t, ()):
                    scores[c] += w * cw
            best = max(range(len(centers)), key=lambda c: (scores[c], -c))
            if best != assignment[i]:
                assignment[i], changed = best, True
        if not changed:
            break
        sums: List[Dict[str, float]] = [defaultdict(float) for _ in centers]
        for i, v in enumerate(vectors):
            for t, w in v.items():
                sums[assignment[i]][t] += w
        centers = [_truncate(_normalize(s)) if s else centers[c] for c, s in enumerate(sums)]
    return assignment


def content_clusters(texts: Mapping[str, str], k: int, seed: int = 0) -> Dict[str, str]:
    """{page id: "topic-<n>"} from the page texts (see spherical_kmeans)."""
    ids = list(texts)
    labels = spherical_kmeans(tfidf_vectors([texts[i] for i in ids]), k, seed)
    return {page: f"topic-{label}" for page, label in zip(ids, labels)}


def label_propagation(nodes: Sequence[str], edges: Iterable[Tuple[str, str]], seed: int = 0,
                      max_rounds: int = 30) -> Dict[str, str]:
    """
    Community of each node by asynchronous label propagation (Raghavan et al. 2007)
    on the undirected graph; ties are broken at random with a fixed seed.
    Isolated nodes keep their own community.
    """
    neighbours: Dict[str, Counter] = {node: Counter() for node in nodes}
    for a, b in edges:
        if a in neighbours and b in neighbours and a != b:
            neighbours[a][b] += 1
            neighbours[b][a] += 1
    label = {node: node for node in nodes}
    rng = random.Random(seed)
    order = list(nodes)
    for _ in range(max_rounds):
        rng.shuffle(order)
        changed = False
        for node in order:
            if not neighbours[node]:
                continue
            votes: Counter = Counter()
            for other, weight in neighbours[node].items():
                votes[label[other]] += weight
            top = max(votes.values())
            candidates = sorted(l for l, v in votes.items() if v == top)
            if label[node] in candidates:
                continue
            label[node] = rng.choice(candidates)
            changed = True
        if not changed:
            break
    names: Dict[str, str] = {}
    return {node: names.setdefault(label[node], f"community-{len(names)}") for node in nodes}


def suggested_k(n: int, minimum: int = 2, maximum: int = 50) -> int:
    """Rule-of-thumb number of topics when nothing else is known: sqrt(n / 2)."""
    return max(minimum, min(maximum, int(round(math.sqrt(n / 2)))))


def assignments_for(clusters: Mapping[str, str], prefix: Optional[str] = None) -> Tuple[Tuple[str, str], ...]:
    """SiteTaxonomy.assignments from a {page: cluster} mapping."""
    return tuple((page, f"{prefix}{name}" if prefix else name) for page, name in clusters.items())
