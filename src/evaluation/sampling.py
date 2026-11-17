"""
Which documents are evaluated. Each sampler has a known bias, so the protocol
runs several and reports them side by side; a conclusion only holds if it
holds under all of them.

  random      uniform over documents                 unbiased, but dominated by the most common kind of page
  snowball    breadth-first over links from a seed   realistic "site section", over-represents hubs
  label       equal share per primary label          every topic counts, including small ones
  popularity  equal share per popularity quartile    long tail and head count equally

All samplers are deterministic for a given seed and fall back to random
sampling when the corpus lacks the layer they stratify on.
"""

import random
from collections import deque
from typing import Callable, Dict, List

from src.evaluation.corpus import Corpus


def sample_random(corpus: Corpus, size: int, seed: int) -> List[str]:
    ids = sorted(corpus.ids)
    random.Random(seed).shuffle(ids)
    return ids[:size]


def sample_snowball(corpus: Corpus, size: int, seed: int) -> List[str]:
    rng = random.Random(seed)
    neighbours: Dict[str, List[str]] = {d.id: sorted(set(d.link_targets) | set(d.extra_links)) for d in corpus.documents}
    ids = sorted(corpus.ids)
    chosen: List[str] = []
    seen = set()
    while len(chosen) < min(size, len(ids)):
        start = rng.choice([i for i in ids if i not in seen])       # new seed when a component is exhausted
        queue = deque([start])
        seen.add(start)
        while queue and len(chosen) < size:
            node = queue.popleft()
            chosen.append(node)
            for nxt in neighbours.get(node, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
    return chosen


def _stratified(groups: Dict[str, List[str]], size: int, seed: int) -> List[str]:
    rng = random.Random(seed)
    pools = {key: sorted(members) for key, members in groups.items()}
    for members in pools.values():
        rng.shuffle(members)
    chosen: List[str] = []
    # Round-robin over strata: equal shares, small strata exhausted first.
    while len(chosen) < size and any(pools.values()):
        for key in sorted(pools):
            if pools[key] and len(chosen) < size:
                chosen.append(pools[key].pop())
    return chosen


def sample_by_label(corpus: Corpus, size: int, seed: int) -> List[str]:
    if "labels" not in corpus.layers:
        return sample_random(corpus, size, seed)
    groups: Dict[str, List[str]] = {}
    for doc in corpus.documents:
        groups.setdefault(doc.labels[0] if doc.labels else "(none)", []).append(doc.id)
    return _stratified(groups, size, seed)


def sample_by_popularity(corpus: Corpus, size: int, seed: int, bins: int = 4) -> List[str]:
    scored = sorted((d.popularity, d.id) for d in corpus.documents if d.popularity is not None)
    if len(scored) < bins:
        return sample_random(corpus, size, seed)
    groups: Dict[str, List[str]] = {}
    for rank, (_, doc_id) in enumerate(scored):
        groups.setdefault(f"q{rank * bins // len(scored)}", []).append(doc_id)
    return _stratified(groups, size, seed)


SAMPLERS: Dict[str, Callable[[Corpus, int, int], List[str]]] = {
    "random": sample_random,
    "snowball": sample_snowball,
    "label": sample_by_label,
    "popularity": sample_by_popularity,
}
