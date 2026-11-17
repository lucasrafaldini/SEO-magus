"""
Calculations over tidy results (results.py): simple ones to read at a glance,
complex ones to compare systems across methodologies without over-reading them.

Simple
  describe      per (task, protocol, corpus, system): runs, mean, median, sd, min, max of the
                primary metric and of `skill` (chance-normalized, comparable across tasks)
  wins          per (task, protocol, corpus, system, baseline): cells won / tied / lost,
                mean difference, share of runs significant after correction
Complex
  ranks         Friedman test over methodology cells (corpus x protocol x sampler x seed), average
                rank per system, Nemenyi critical difference, systems tied with the best
  agreement     for each methodological factor (corpus, protocol, sampler, seed): the system
                ranking under each level, their concordance (Kendall's W) and the winner per
                level - do different methodologies tell the same story?
  sensitivity   share of the variance of each system's score explained by each factor (eta²):
                which methodological choice moves the numbers most
  meta          random-effects pooling (DerSimonian-Laird) of each product-vs-baseline difference
                across corpora, with heterogeneity I²; real sources and all sources separately

Every output is plain data (dicts and lists), ready for JSON, CSV, Markdown or HTML.
"""


import statistics
from typing import Dict, List, Optional, Sequence

from src.evaluation.results import PRIMARY, Row, group
from src.evaluation.stats import (
    eta_squared, friedman, kendall_w, nemenyi_cd, pairwise_tau, random_effects, se_from_ci,
)

FACTORS = ("corpus", "protocol", "sampler", "seed")
EVIDENCE = "evidence"


def _stats(values: Sequence[float]) -> Dict[str, float]:
    values = list(values)
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean": statistics.fmean(values), "median": statistics.median(values),
            "sd": statistics.stdev(values) if len(values) > 1 else 0.0, "min": min(values), "max": max(values)}


def _primary(rows: Sequence[Row]) -> List[Row]:
    return [r for r in rows if r.metric == PRIMARY.get(r.task)]


# ------------------------------------------------------------------ simple


def describe(rows: Sequence[Row]) -> List[dict]:
    out = []
    primary = _primary(rows)
    skill = group([r for r in rows if r.metric == "skill"], "task", "protocol", "corpus", "system")
    for (task, protocol, corpus, system), members in sorted(group(primary, "task", "protocol", "corpus", "system").items()):
        entry = {"task": task, "protocol": protocol, "corpus": corpus, "system": system, "kind": members[0].kind,
                 "evidence": members[0].evidence, "metric": PRIMARY[task], **_stats([r.value for r in members])}
        skills = skill.get((task, protocol, corpus, system), [])
        entry["skill"] = statistics.fmean(r.value for r in skills) if skills else None
        out.append(entry)
    return out


def wins(rows: Sequence[Row]) -> List[dict]:
    """Head-to-head of every product/oracle system against every baseline, cell by cell."""
    out = []
    by_cell = group(_primary(rows), "task", "protocol", "corpus")
    significant = {(r.task, r.protocol, r.corpus, r.sampler, r.seed, r.system, r.metric): r.value
                   for r in rows if r.metric.startswith("significant[")}
    for (task, protocol, corpus), members in sorted(by_cell.items()):
        cells = group(members, "sampler", "seed")
        systems = sorted({r.system: r.kind for r in members}.items())
        for system, kind in systems:
            if kind == "baseline":
                continue
            for baseline, base_kind in systems:
                if base_kind != "baseline":
                    continue
                won = tied = lost = 0
                differences, flags = [], []
                for (sampler, seed), cell in cells.items():
                    score = {r.system: r.value for r in cell}
                    if system not in score or baseline not in score:
                        continue
                    d = score[system] - score[baseline]
                    differences.append(d)
                    won, tied, lost = won + (d > 1e-12), tied + (abs(d) <= 1e-12), lost + (d < -1e-12)
                    flag = significant.get((task, protocol, corpus, sampler, seed, system, f"significant[{baseline}]"))
                    if flag is not None:
                        flags.append(flag)
                if not differences:
                    continue
                out.append({"task": task, "protocol": protocol, "corpus": corpus, "system": system,
                            "baseline": baseline, "cells": len(differences), "won": won, "tied": tied, "lost": lost,
                            "win_rate": (won + tied / 2) / len(differences),
                            "mean_difference": statistics.fmean(differences),
                            "significant_share": statistics.fmean(flags) if flags else None,
                            "evidence": members[0].evidence})
    return out


# ------------------------------------------------------------------- ranks


def _score_table(members: Sequence[Row], systems: Sequence[str]) -> List[List[float]]:
    """Rows = methodology cells with every system present, columns = systems."""
    table = []
    for _, cell in sorted(group(members, "corpus", "protocol", "sampler", "seed").items()):
        score = {r.system: r.value for r in cell}
        if all(s in score for s in systems):
            table.append([score[s] for s in systems])
    return table


def ranks(rows: Sequence[Row], scope: str = "all") -> List[dict]:
    """
    Friedman + Nemenyi per task (scope "all": every cell of every corpus and protocol;
    scope "corpus": one analysis per task x protocol x corpus). Systems whose average
    rank is within the critical difference of the best are reported as `tied_with_best`.
    """
    out = []
    keys = ("task",) if scope == "all" else ("task", "protocol", "corpus")
    for key, members in sorted(group(_primary(rows), *keys).items()):
        systems = sorted({r.system for r in members})
        table = _score_table(members, systems)
        if len(table) < 2:
            continue
        test = friedman(table)
        average = dict(zip(systems, test["average_ranks"]))
        cd = nemenyi_cd(len(systems), len(table))
        best = min(average.values())
        kinds = {r.system: r.kind for r in members}
        entry = {"task": key[0], "protocol": key[1] if scope == "corpus" else "(all)",
                 "corpus": key[2] if scope == "corpus" else "(all)", "cells": len(table),
                 "systems": len(systems), "chi2": test["chi2"], "p_value": test["p_value"],
                 "critical_difference": cd,
                 "average_rank": dict(sorted(average.items(), key=lambda kv: kv[1])),
                 "kind": kinds,
                 "tied_with_best": sorted(s for s, r in average.items() if cd is not None and r - best <= cd),
                 "evidence": sorted({r.evidence for r in members})}
        out.append(entry)
    return out


# -------------------------------------------------------------- agreement


def agreement(rows: Sequence[Row]) -> List[dict]:
    """
    For each task and each methodological factor: rank the systems by mean primary
    metric under every level of the factor (e.g. every sampler), then measure how
    much those rankings agree (Kendall's W; 1 = every level ranks the systems the same).
    """
    out = []
    for (task,), members in sorted(group(_primary(rows), "task").items()):
        systems = sorted({r.system for r in members})
        for factor in FACTORS:
            levels = group(members, factor)
            if len(levels) < 2:
                continue
            means: Dict[str, Dict[str, float]] = {}
            for (level,), level_rows in sorted(levels.items(), key=lambda kv: str(kv[0])):
                by_system = group(level_rows, "system")
                means[str(level)] = {s: statistics.fmean(r.value for r in by_system[(s,)])
                                     for s in systems if (s,) in by_system}
            complete = {lvl: m for lvl, m in means.items() if len(m) == len(systems)}
            if len(complete) < 2:
                continue
            vectors = {lvl: [m[s] for s in systems] for lvl, m in complete.items()}
            winners = {lvl: max(m, key=m.get) for lvl, m in complete.items()}
            out.append({
                "task": task, "factor": factor, "levels": len(complete),
                "kendall_w": kendall_w(list(vectors.values())),
                "winner_by_level": winners,
                "same_winner": len(set(winners.values())) == 1,
                "pairwise_tau": {f"{a} | {b}": tau for (a, b), tau in pairwise_tau(vectors).items()},
                "means": complete,
            })
    return out


# ------------------------------------------------------------ sensitivity


def sensitivity(rows: Sequence[Row]) -> List[dict]:
    """eta² of each factor for each system's primary metric (which choice moves the number)."""
    out = []
    for (task, system), members in sorted(group(_primary(rows), "task", "system").items()):
        if len(members) < 3:
            continue
        values = [r.value for r in members]
        shares = eta_squared(values, {f: [getattr(r, f) for r in members] for f in FACTORS})
        out.append({"task": task, "system": system, "kind": members[0].kind, "runs": len(members),
                    "sd": statistics.stdev(values), **{f"eta2_{f}": v for f, v in shares.items()}})
    return out


# ------------------------------------------------------------------- meta


def meta(rows: Sequence[Row]) -> List[dict]:
    """
    Pool each system-vs-baseline difference across corpora. Per corpus the effect is the
    mean paired difference over its runs and its variance the mean squared standard error
    of those runs (runs of one corpus overlap, so they are not counted as independent).
    """
    out = []
    differences = [r for r in rows if r.metric.startswith("difference[") and r.ci_low is not None]
    for (task, protocol, system, metric), members in sorted(group(differences, "task", "protocol", "system", "metric").items()):
        baseline = metric[len("difference["):-1]
        per_corpus = []
        for (corpus,), runs in sorted(group(members, "corpus").items()):
            effect = statistics.fmean(r.value for r in runs)
            variance = statistics.fmean(se_from_ci(r.ci_low, r.ci_high) ** 2 for r in runs)
            per_corpus.append({"corpus": corpus, "evidence": runs[0].evidence, "effect": effect,
                               "variance": variance, "runs": len(runs)})
        entry = {"task": task, "protocol": protocol, "system": system, "baseline": baseline, "kind": members[0].kind,
                 "per_corpus": per_corpus}
        for scope, chosen in (("all", per_corpus), ("real", [c for c in per_corpus if c["evidence"] == EVIDENCE])):
            entry[scope] = random_effects([c["effect"] for c in chosen], [c["variance"] for c in chosen]) \
                if chosen else None
        out.append(entry)
    return out


def analyze(rows: Sequence[Row]) -> dict:
    return {
        "describe": describe(rows),
        "wins": wins(rows),
        "ranks": ranks(rows, "all") + ranks(rows, "corpus"),
        "agreement": agreement(rows),
        "sensitivity": sensitivity(rows),
        "meta": meta(rows),
        "notes": {
            "skill": "(value - random baseline of the same cell) / (1 - random): 0 = chance, 1 = perfect",
            "ranks": "Friedman over methodology cells; Nemenyi CD at alpha 0.05 (Demsar 2006)",
            "agreement": "Kendall's W of the system rankings under each level of a factor (1 = same ranking)",
            "sensitivity": "eta²: share of a system's score variance explained by the factor alone",
            "meta": "DerSimonian-Laird random effects over corpora; per-corpus variance = mean squared SE of its "
                    "runs (runs overlap, so not treated as independent); 'real' = corpora whose evidence role is "
                    "'evidence'",
        },
    }


def headline(analysis: dict, task: str = "links") -> Optional[dict]:
    """The overall ranking of one task (all cells), for summaries."""
    return next((r for r in analysis["ranks"] if r["task"] == task and r["corpus"] == "(all)"), None)
