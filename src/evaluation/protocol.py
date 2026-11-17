"""
The evaluation protocol, fixed before any result is seen (pre-registration).

Every methodological choice is a named constant here; its hash is written into
every report, so two reports are comparable only when their protocol hashes
match. Changing anything below after looking at results requires bumping
VERSION and saying why in docs/EVALUATION.md ("Protocol changes").
"""

import hashlib
import json

VERSION = "1.0"

PROTOCOL = {
    "version": VERSION,
    # Link recovery: share of each evaluated page's human links taken out.
    #   cold     all of them (a page written without links)
    #   holdout  half of them; the other half stay as existing links (a page with missing links)
    "link_protocols": {"cold": 1.0, "holdout": 0.5},
    "sample_size": 200,                      # documents evaluated per (corpus, sampler, seed)
    "seeds": [1, 2, 3],                      # every run is repeated; stability across seeds is reported
    "samplers": ["random", "snowball", "label", "popularity"],
    "bootstrap_resamples": 1000,
    "confidence": 0.95,
    # Holm-corrected within each run (family = that run's system-vs-baseline comparisons, at most 16).
    # Chance wins across the many runs are controlled by replication instead: a claim is "robust" only if
    # significant in EVERY sampler x seed run, and "supported" only if robust on every real source.
    # (A report-wide family of ~2,000 comparisons would need p < 2.5e-5, finer than 1,000 bootstrap
    # resamples can resolve: significance would silently mean "p = 0 exactly".)
    "alpha": 0.05,
    "correction_family": "run",
    # Classification uses the chance-corrected ARI: NMI rewards many clusters even at random
    # (a random 22-cluster labelling scored NMI 0.35 on 200 documents while designing this protocol).
    "primary_metric": {"links": "micro_f1", "classification": "ari", "ranking": "spearman"},
    "min_units": 30,                         # fewer evaluated documents: "insufficient data", no verdict
    "max_label_ratio": 0.34,                 # more distinct labels than this share of documents: too fine, skipped
    "clickstream_min_clicks": 10,            # reader demand for a pair
    "ndcg_k": [10, 100],
    "compare": "every product/oracle system against every baseline, paired bootstrap on the primary metric",
}


def protocol_hash() -> str:
    return hashlib.sha256(json.dumps(PROTOCOL, sort_keys=True).encode()).hexdigest()[:12]


def holm(p_values: dict, alpha: float = PROTOCOL["alpha"]) -> dict:
    """
    Holm-Bonferroni step-down: {name: p} -> {name: rejected?}. Controls the chance
    of any false "better" verdict across all comparisons of a report - the price of
    benchmarking in many ways at once.
    """
    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(ordered)
    rejected, still = {}, True
    for i, (name, p) in enumerate(ordered):
        still = still and p <= alpha / (m - i)
        rejected[name] = still
    return rejected
