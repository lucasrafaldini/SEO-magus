"""
Scale: how cost grows with site size.

Synthetic sites of increasing size (topics grow with the site, sqrt(n)/2, as
real sites add sections) are run through the link flow. Reported per size:
seconds, classifier calls (the paid part with an API classifier), links,
process peak memory. Up to `brute_max` pages the exhaustive flow (prune=False)
also runs and must produce identical links; the fitted exponent of
time ~ n^b shows whether growth is linear (b ~ 1) or quadratic (b ~ 2).
"""

import math
import resource
import time
import warnings
from typing import Callable, List, Sequence

from src.engines.classifiers import HeuristicClassifier
from src.evaluation.sources.synthetic import SyntheticSpec, generate
from src.workflows.linking_optimizer import LinkingOptimizer


def _links(report) -> List[tuple]:
    return [(r.source_url, r.target_url, r.anchor_text) for r in report.results]


def _run(pages, prune: bool):
    optimizer = LinkingOptimizer(classifier=HeuristicClassifier(), prune=prune)
    started = time.perf_counter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        report = optimizer.run_optimization(pages)
    return report, time.perf_counter() - started


def loglog_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    points = [(math.log(x), math.log(y)) for x, y in zip(xs, ys) if x > 0 and y > 0]
    if len(points) < 2:
        return float("nan")
    mx = sum(p[0] for p in points) / len(points)
    my = sum(p[1] for p in points) / len(points)
    sxx = sum((p[0] - mx) ** 2 for p in points)
    return sum((p[0] - mx) * (p[1] - my) for p in points) / sxx if sxx else float("nan")


def scale_task(sizes: Sequence[int], preset: str = "encyclopedia", seed: int = 0, brute_max: int = 300,
               progress: Callable[[str], None] = lambda message: None) -> dict:
    rows = []
    for n in sizes:
        corpus = generate(SyntheticSpec(pages=n, topics=max(4, round(math.sqrt(n) / 2)), seed=seed, preset=preset))
        pages = corpus.to_pages()
        report, seconds = _run(pages, prune=True)
        row = {
            "pages": n, "seconds": round(seconds, 3), "classifier_calls": report.candidate_pairs_checked,
            "links": report.links_approved, "pairs": n * (n - 1),
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        }
        if n <= brute_max:
            brute, brute_seconds = _run(pages, prune=False)
            row.update(exhaustive_seconds=round(brute_seconds, 3), exhaustive_calls=brute.candidate_pairs_checked,
                       identical_links=_links(brute) == _links(report))
        rows.append(row)
        progress(f"scale {n} pages: {row['seconds']}s, {row['classifier_calls']} classifier calls, {row['links']} links"
                 + (f" | exhaustive {row['exhaustive_seconds']}s, identical: {row['identical_links']}"
                    if "exhaustive_seconds" in row else ""))
    return {
        "task": "scale", "preset": preset, "seed": seed, "rows": rows,
        "time_exponent": loglog_slope([r["pages"] for r in rows], [r["seconds"] for r in rows]),
        "calls_exponent": loglog_slope([r["pages"] for r in rows], [r["classifier_calls"] for r in rows]),
    }
