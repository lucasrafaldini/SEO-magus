"""
The three quality tasks. Each returns plain data (dicts) for the report.

links           remove human links from the sampled pages, ask every system to
                propose links, compare with what was removed (link recovery).
                Also: recall per difficulty stratum, lenient precision against every
                human link layer, reader-validated precision (clickstream), planted
                style recall and valid-unlinked share (synthetic), and how well the
                proposals rebuild the editors' PageRank distribution.
classification  cluster every page, score the sampled pages against their primary label.
ranking         score every page, correlate with external popularity on the sampled pages.

Difficulty strata (computed the same way for every source, from the anchor the
human wrote and the target's title):
  names-2+   the anchor names >= 2 words of the target title  - reachable by anchor-based linking
  names-1    exactly one title word (Wikipedia's "Paris" for "Paris, France")
  names-0    no title word (synonyms, pronouns, "click here")
The share of names-2+ gold links is the recall ceiling of any approach that
needs the target's name in the text - reported so low recall is not misread.
"""

import math
import random
from typing import Dict, List, Optional, Sequence, Set

from src.engines.link_graph import LinkGraph
from src.engines.text import content_tokens, tokens_match
from src.evaluation.corpus import Corpus, Pair
from src.evaluation.metrics import (
    LinkCounts, adjusted_rand_index, compare_from, estimate_from, inverse_purity, kendall_tau_b, link_counts,
    macro_prf, micro_prf, ndcg_at_k, nmi, purity, resamples, spearman,
)
from src.evaluation.protocol import PROTOCOL
from src.evaluation.sources.synthetic import style_of
from src.evaluation.systems import CLUSTERERS, LINK_SYSTEMS, SCORERS, LinkSystem, site_graph

STRATA = ("names-2+", "names-1", "names-0")


def mention_stratum(anchor: str, target_title: str) -> str:
    title = content_tokens(target_title)
    named = {t for t in title if any(tokens_match(t, w) for w in content_tokens(anchor))}
    return STRATA[0] if len(named) >= 2 else (STRATA[1] if named else STRATA[2])


def _uncertainty(n: int, stats: Dict[str, callable], kinds: Dict[str, str], seed: int):
    """
    CI of every system's statistic and paired comparisons of every product/oracle
    system against every baseline, all from the SAME bootstrap draws.
    stats[name](indices) computes the statistic on a list of unit indices.
    """
    draws = resamples(n, PROTOCOL["bootstrap_resamples"], seed)
    everyone = list(range(n))
    values = {name: stat(everyone) for name, stat in stats.items()}
    samples = {name: [stat(idx) for idx in draws] for name, stat in stats.items()}
    confidence = PROTOCOL["confidence"]
    cis = {name: estimate_from(values[name], samples[name], confidence).as_dict() for name in stats}
    comparisons = {}
    for system, kind in kinds.items():
        if kind == "baseline":
            continue
        for baseline, base_kind in kinds.items():
            if base_kind == "baseline":
                comparisons[f"{system} vs {baseline}"] = compare_from(
                    values[system], values[baseline], samples[system], samples[baseline], confidence).as_dict()
    return cis, comparisons


def _f1_statistic(units: List[LinkCounts]):
    tp, predicted, gold = [u.tp for u in units], [u.predicted for u in units], [u.gold for u in units]

    def f1(idx: List[int]) -> float:
        t, p, g = sum(tp[i] for i in idx), sum(predicted[i] for i in idx), sum(gold[i] for i in idx)
        return 2 * t / (p + g) if p + g else 0.0     # = harmonic mean of micro precision and recall
    return f1


# ------------------------------------------------------------------- links


def remove_links(corpus: Corpus, sample: Sequence[str], share: float, seed: int) -> Set[Pair]:
    rng = random.Random(seed)
    removed: Set[Pair] = set()
    for source in sample:
        targets = sorted(corpus.get(source).link_targets)
        rng.shuffle(targets)
        removed |= {(source, t) for t in targets[:math.ceil(len(targets) * share)]}
    return removed


def _pagerank_spearman(reference: Dict[str, float], graph: LinkGraph, ids: Sequence[str]) -> float:
    scores = graph.compute_pagerank()
    return spearman([reference.get(i, 0.0) for i in ids], [scores.get(i, 0.0) for i in ids])


def _stripped_graph(corpus: Corpus, removed: Set[Pair]) -> LinkGraph:
    return site_graph(corpus, exclude=removed)


def link_task(corpus: Corpus, sample: Sequence[str], protocol: str, seed: int,
              systems: Sequence[LinkSystem] = LINK_SYSTEMS) -> dict:
    share = PROTOCOL["link_protocols"][protocol]
    removed = remove_links(corpus, sample, share, seed)
    gold: Dict[str, Set[str]] = {s: set() for s in sample}
    for source, target in removed:
        gold[source].add(target)
    kept = {s: set(corpus.get(s).link_targets) - gold[s] for s in sample}
    strata: Dict[Pair, str] = {}
    for source in sample:
        doc = corpus.get(source)
        for link in doc.links:
            if (source, link.target) in removed:
                strata.setdefault((source, link.target), mention_stratum(link.anchor, corpus.get(link.target).title))
    human = {s: set(corpus.get(s).link_targets) | set(corpus.get(s).extra_links) for s in sample}
    planted_styles = style_of(corpus) if corpus.provenance.source == "synthetic" else {}
    valid_unlinked = {s: set(corpus.get(s).meta.get("unlinked_mentions", [])) for s in sample}
    full_rank = site_graph(corpus).compute_pagerank()
    stripped_rho = _pagerank_spearman(full_rank, _stripped_graph(corpus, removed), corpus.ids)

    units_by_system: Dict[str, List[LinkCounts]] = {}
    results: Dict[str, dict] = {}
    for system in systems:
        predictions = system.predict(corpus, removed, sample, seed)
        predicted = {s: set(predictions.get(s, [])) - kept[s] - {s} for s in sample}
        units = [link_counts(predicted[s], gold[s]) for s in sample]
        units_by_system[system.name] = units
        p, r, f = micro_prf(units)
        mp, mr, mf = macro_prf(units)
        result = {
            "kind": system.kind, "precision": p, "recall": r, "f1": f,
            "macro_precision": mp, "macro_recall": mr, "macro_f1": mf,
            "predicted": sum(u.predicted for u in units),
            "recall_by_stratum": _recall_by(predicted, strata),
        }
        pairs = {(s, t) for s in sample for t in predicted[s]}
        if pairs and corpus.layers & {"extra_links"}:
            result["lenient_precision"] = sum(t in human[s] for s, t in pairs) / len(pairs)
        if pairs and "clickstream" in corpus.layers:
            wanted = {pair for pair in pairs if sum(corpus.clickstream.get(pair, {}).values())
                      >= PROTOCOL["clickstream_min_clicks"]}
            false_positives = {(s, t) for s, t in pairs if t not in gold[s]}
            result["reader_validated_precision"] = len({(s, t) for s, t in pairs if t in gold[s]} | wanted) / len(pairs)
            result["false_positives_with_reader_demand"] = (
                len(false_positives & wanted) / len(false_positives) if false_positives else 0.0)
        if planted_styles:
            result["recall_by_planted_style"] = _recall_by(predicted, {k: v for k, v in planted_styles.items() if k in removed})
            false_positives = [(s, t) for s, t in pairs if t not in gold[s]]
            result["false_positives_planted_valid"] = (
                sum(t in valid_unlinked[s] for s, t in false_positives) / len(false_positives) if false_positives else 0.0)
        rebuilt = _stripped_graph(corpus, removed)
        for s in sample:
            for t in predicted[s]:
                rebuilt.add_link(s, t)
        result["pagerank_rebuilt_rho"] = _pagerank_spearman(full_rank, rebuilt, corpus.ids)
        result["pagerank_stripped_rho"] = stripped_rho
        results[system.name] = result

    kinds = {s.name: s.kind for s in systems}
    cis, comparisons = _uncertainty(len(sample), {n: _f1_statistic(u) for n, u in units_by_system.items()}, kinds, seed)
    for name, ci in cis.items():
        results[name]["f1_ci"] = ci
    counts = {stratum: sum(1 for v in strata.values() if v == stratum) for stratum in STRATA}
    total = sum(counts.values())
    return {
        "task": "links", "protocol": protocol, "units": len(sample), "gold_links": total,
        "gold_by_stratum": counts,
        "anchor_ceiling": counts[STRATA[0]] / total if total else 0.0,
        "systems": results,
        "comparisons": comparisons,
    }


def _recall_by(predicted: Dict[str, Set[str]], groups: Dict[Pair, str]) -> Dict[str, dict]:
    totals: Dict[str, List[int]] = {}
    for (source, target), group in groups.items():
        hit = target in predicted.get(source, set())
        entry = totals.setdefault(group, [0, 0])
        entry[0] += hit
        entry[1] += 1
    return {g: {"recall": hits / n if n else 0.0, "gold": n} for g, (hits, n) in sorted(totals.items())}


# ---------------------------------------------------------- classification


def classification_task(corpus: Corpus, sample: Sequence[str], seed: int) -> Optional[dict]:
    labelled = [s for s in sample if corpus.get(s).labels]
    truth_all = {d.id: d.labels[0] for d in corpus.documents if d.labels}
    k = len(set(truth_all.values()))
    if k > PROTOCOL["max_label_ratio"] * max(1, len(truth_all)) or k < 2:
        return {"task": "classification", "skipped": f"{k} distinct primary labels for {len(truth_all)} documents: "
                "labels too fine-grained or absent (sample by category/collection/tag to get comparable labels)"}
    clusterings = {name: (kind, fn(corpus, k, seed)) for name, (kind, fn) in CLUSTERERS.items()}
    truth = [truth_all[s] for s in labelled]
    results, stats = {}, {}
    for name, (kind, clusters) in clusterings.items():
        predicted = [clusters.get(s, "?") for s in labelled]
        stats[name] = (lambda idx, p=predicted: adjusted_rand_index([truth[i] for i in idx], [p[i] for i in idx]))
        results[name] = {
            "kind": kind, "nmi": nmi(truth, predicted), "ari": adjusted_rand_index(truth, predicted),
            "purity": purity(truth, predicted), "inverse_purity": inverse_purity(truth, predicted),
            "clusters": len(set(clusters.values())),
        }
    kinds = {name: kind for name, (kind, _) in clusterings.items()}
    cis, comparisons = _uncertainty(len(labelled), stats, kinds, seed)
    for name, ci in cis.items():
        results[name]["ari_ci"] = ci
    return {"task": "classification", "units": len(labelled), "true_labels": k, "systems": results,
            "comparisons": comparisons}


# ----------------------------------------------------------------- ranking


def ranking_task(corpus: Corpus, sample: Sequence[str], seed: int) -> Optional[dict]:
    scored = [s for s in sample if corpus.get(s).popularity is not None]
    if len(scored) < 2:
        return {"task": "ranking", "skipped": "no popularity layer"}
    popularity = [corpus.get(s).popularity for s in scored]
    gains = [math.log1p(max(0.0, p)) for p in popularity]
    results, stats, kinds = {}, {}, {}
    for name, (kind, scorer) in SCORERS.items():
        scores = scorer(corpus, seed)
        values = [scores.get(s, 0.0) for s in scored]
        stat = (lambda idx, v=values: spearman([v[i] for i in idx], [popularity[i] for i in idx]))
        stats[name], kinds[name] = stat, kind
        results[name] = {
            "kind": kind, "spearman": spearman(values, popularity), "kendall_tau_b": kendall_tau_b(values, popularity),
            **{f"ndcg@{k}": ndcg_at_k(scored, values, gains, k) for k in PROTOCOL["ndcg_k"]},
        }
    cis, comparisons = _uncertainty(len(scored), stats, kinds, seed)
    for name, ci in cis.items():
        results[name]["spearman_ci"] = ci
    return {"task": "ranking", "units": len(scored), "systems": results, "comparisons": comparisons}
