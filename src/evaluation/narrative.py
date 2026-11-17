"""
The automatically written "at a glance" summary, shared by report.md and report.html.

Each point is (title, text) in plain language: what counts as evidence, how many
claims are established, the best system per task, whether the winner depends on
the methodology, and which methodological factor moves the product's score most.
"""

from typing import Dict, List, Tuple

from src.evaluation.analysis import headline

Point = Tuple[str, str]


def at_a_glance(report: dict, analysis: dict) -> List[Point]:
    corpora = report.get("corpora", [])
    if not corpora and not analysis["describe"]:
        return []
    points: List[Point] = []
    evidence = [c["name"] for c in corpora if "evidence" in c.get("evidence", {}).values()]
    if evidence:
        points.append(("Evidence", f"{len(evidence)} of {len(corpora)} corpora count as evidence ({', '.join(evidence)})."))
    else:
        points.append(("Evidence", f"none of the {len(corpora)} corpora counts as evidence about real-world quality "
                                   "(synthetic: code validation and per-style behaviour; tiny: too small). The points "
                                   "below describe the method and the synthetic data only."))
    claims = report.get("summary", {}).get("claims", [])
    if claims:
        count = lambda prefix: sum(1 for c in claims if c["status"].startswith(prefix))
        points.append(("Claims", f"{count('supported')} supported on every real source, {count('contradicted')} "
                                 f"contradicted, {count('not established')} not established, {count('untested')} "
                                 f"untested on real data (of {len(claims)})."))
    for task in ("links", "classification", "ranking"):
        top = headline(analysis, task)
        if not top:
            continue
        best = next(iter(top["average_rank"]))
        tied = [s for s in top["tied_with_best"] if s != best]
        points.append((task, f"best average rank over {top['cells']} methodology cells: {best} "
                             f"({top['average_rank'][best]:.2f})"
                             + (f", statistically tied with {', '.join(tied)}." if tied else ", ahead of every other system.")))
    unstable = [a for a in analysis["agreement"] if not a["same_winner"]]
    if unstable:
        points.append(("Methodology sensitivity", "the winner changes with " + "; ".join(
            f"the {a['factor']} for {a['task']} (W {a['kendall_w']:.2f})" for a in unstable) + "."))
    stable: Dict[str, List[dict]] = {}
    for a in analysis["agreement"]:
        if a["same_winner"]:
            stable.setdefault(a["task"], []).append(a)
    if stable:
        points.append(("Methodology agreement", "same winner under every level of " + "; ".join(
            f"{task}: {', '.join(a['factor'] for a in members)} (W >= {min(a['kendall_w'] for a in members):.2f})"
            for task, members in stable.items()) + "."))
    for entry in analysis["sensitivity"]:
        if entry["kind"] == "product" and entry["system"] in ("seo-magus", "pagerank") and entry["sd"] > 1e-9:
            shares = {f: entry[f"eta2_{f}"] for f in ("corpus", "protocol", "sampler", "seed")}
            top_factor = max(shares, key=shares.get)
            points.append((f"What moves {entry['system']} ({entry['task']})",
                           f"the {top_factor} explains {shares[top_factor]:.0%} of its score variance; " + ", ".join(
                               f"{f} {v:.0%}" for f, v in shares.items() if f != top_factor) + "."))
    return points
