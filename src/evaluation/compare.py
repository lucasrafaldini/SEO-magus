"""
Comparing evaluation reports (code versions, protocol versions, settings, sources).

The first report is the reference; every other one is compared to it.

  direct    same protocol hash and, for every shared corpus, the same data fingerprint:
            cells (corpus, task, protocol, sampler, seed) are paired, each system's change is
            tested with the Wilcoxon signed-rank test over paired cells, Holm-corrected
            over the systems of the comparison
  indirect  different protocol or data: raw metric values are not comparable cell by cell,
            so only scale-free quantities are compared - mean chance-normalized skill and the
            average rank of each system - and the reasons are listed; no significance is claimed

In both cases the ordering of systems per task is compared with Kendall's tau:
do the two evaluations agree on which system is better?
"""

import statistics
from typing import Dict, List, Sequence

from src.evaluation.analysis import ranks
from src.evaluation.metrics import kendall_tau_b
from src.evaluation.protocol import holm
from src.evaluation.results import PRIMARY, Row, group
from src.evaluation.stats import wilcoxon_signed_rank

EPSILON = 1e-9


def compatibility(reference: Sequence[Row], other: Sequence[Row]) -> Dict[str, object]:
    reasons: List[str] = []
    hashes = ({r.protocol_hash for r in reference}, {r.protocol_hash for r in other})
    if hashes[0] != hashes[1]:
        reasons.append(f"protocol differs ({', '.join(sorted(hashes[0]))} vs {', '.join(sorted(hashes[1]))})")
    prints = ({r.corpus: r.fingerprint for r in reference}, {r.corpus: r.fingerprint for r in other})
    shared = sorted(set(prints[0]) & set(prints[1]))
    for corpus in shared:
        if prints[0][corpus] != prints[1][corpus]:
            reasons.append(f"data of {corpus} differs ({prints[0][corpus]} vs {prints[1][corpus]})")
    only = sorted(set(prints[0]) ^ set(prints[1]))
    if not shared:
        reasons.append("no corpus in common")
    # Differences that keep cells pairable but change the methodology: reported, so a paired change
    # is read as the effect of that choice (e.g. sample size) rather than of the code.
    notes: List[str] = []
    units = lambda rows: {(r.corpus, r.task, r.protocol, r.sampler, r.seed): r.units for r in rows}
    a, b = units(reference), units(other)
    different = sorted({(a[k], b[k]) for k in set(a) & set(b) if a[k] != b[k]})
    if different:
        notes.append("documents per run differ (" + ", ".join(f"{x} vs {y}" for x, y in different[:4]) + ")")
    cells = (set(a), set(b))
    if cells[0] != cells[1]:
        notes.append(f"{len(cells[0] & cells[1])} methodology cells in common ({len(cells[0] - cells[1])} only in the "
                     f"reference, {len(cells[1] - cells[0])} only in the other)")
    return {"mode": "direct" if not reasons else "indirect", "reasons": reasons, "notes": notes,
            "shared_corpora": shared, "corpora_in_one_report_only": only}


def _rank_agreement(reference: Sequence[Row], other: Sequence[Row]) -> List[dict]:
    out = []
    a = {r["task"]: r for r in ranks(reference, "all")}
    b = {r["task"]: r for r in ranks(other, "all")}
    for task in sorted(set(a) & set(b)):
        systems = sorted(set(a[task]["average_rank"]) & set(b[task]["average_rank"]))
        if len(systems) < 2:
            continue
        x = [a[task]["average_rank"][s] for s in systems]
        y = [b[task]["average_rank"][s] for s in systems]
        out.append({"task": task, "systems": len(systems), "kendall_tau": kendall_tau_b(x, y),
                    "best_reference": min(a[task]["average_rank"], key=a[task]["average_rank"].get),
                    "best_other": min(b[task]["average_rank"], key=b[task]["average_rank"].get)})
    return out


def _direct(reference: Sequence[Row], other: Sequence[Row], metric_of=lambda task: PRIMARY[task]) -> List[dict]:
    key = lambda r: (r.corpus, r.task, r.protocol, r.sampler, r.seed, r.system)
    ref = {key(r): r.value for r in reference if r.metric == metric_of(r.task)}
    changes: Dict[tuple, List[float]] = {}
    for r in other:
        if r.metric == metric_of(r.task) and key(r) in ref:
            changes.setdefault((r.task, r.protocol, r.system, r.kind), []).append(r.value - ref[key(r)])
    out = []
    for (task, protocol, system, kind), deltas in sorted(changes.items()):
        test = wilcoxon_signed_rank(deltas)
        out.append({"task": task, "protocol": protocol, "system": system, "kind": kind, "metric": metric_of(task),
                    "cells": len(deltas), "mean_change": statistics.fmean(deltas),
                    "improved": sum(d > EPSILON for d in deltas), "worsened": sum(d < -EPSILON for d in deltas),
                    "unchanged": sum(abs(d) <= EPSILON for d in deltas), "p_value": test["p_value"]})
    # Systems whose every cell is unchanged cannot be tested: they stay out of the Holm family.
    testable = {i: entry["p_value"] for i, entry in enumerate(out) if entry["improved"] + entry["worsened"]}
    rejected = holm(testable) if testable else {}
    for i, entry in enumerate(out):
        significant = rejected.get(i, False)
        entry["verdict"] = ("unchanged" if entry["improved"] == entry["worsened"] == 0 else
                            ("better" if entry["mean_change"] > 0 else "worse") if significant else "not significant")
    return out


def _indirect(reference: Sequence[Row], other: Sequence[Row]) -> List[dict]:
    def skill_means(rows):
        return {k: statistics.fmean(r.value for r in v)
                for k, v in group([r for r in rows if r.metric == "skill"], "task", "protocol", "system").items()}
    a, b = skill_means(reference), skill_means(other)
    rank_a = {(r["task"], s): v for r in ranks(reference, "all") for s, v in r["average_rank"].items()}
    rank_b = {(r["task"], s): v for r in ranks(other, "all") for s, v in r["average_rank"].items()}
    out = []
    for key in sorted(set(a) & set(b)):
        task, protocol, system = key
        out.append({"task": task, "protocol": protocol, "system": system, "skill_reference": a[key],
                    "skill_other": b[key], "skill_change": b[key] - a[key],
                    "rank_reference": rank_a.get((task, system)), "rank_other": rank_b.get((task, system))})
    return out


def compare_reports(reports: Dict[str, Sequence[Row]]) -> dict:
    labels = list(reports)
    if len(labels) < 2:
        raise ValueError("compare needs at least two reports")
    reference = labels[0]
    comparisons = []
    for label in labels[1:]:
        check = compatibility(reports[reference], reports[label])
        entry = {"reference": reference, "other": label, **check,
                 "ranking_agreement": _rank_agreement(reports[reference], reports[label]),
                 "skill": _indirect(reports[reference], reports[label])}
        if check["mode"] == "direct":
            entry["changes"] = _direct(reports[reference], reports[label])
            entry["skill_changes"] = _direct(reports[reference], reports[label], metric_of=lambda task: "skill")
        comparisons.append(entry)
    return {"reports": labels, "reference": reference, "comparisons": comparisons}


# ----------------------------------------------------------------- exports

CSV_COLUMNS = ("reference", "other", "mode", "task", "protocol", "system", "kind", "metric", "cells", "mean_change",
               "improved", "worsened", "unchanged", "p_value", "verdict", "skill_reference", "skill_other",
               "rank_reference", "rank_other")


def _fmt(value, digits: int = 3) -> str:
    return "-" if value is None else (f"{value:.{digits}f}" if isinstance(value, float) else str(value))


def render_markdown(result: dict) -> str:
    lines = ["# Comparison of evaluation reports", "",
             f"Reference: **{result['reference']}**; compared: {', '.join(result['reports'][1:])}.", "",
             "*direct*: same protocol and data - paired cells, Wilcoxon signed-rank per system, Holm-corrected. "
             "*indirect*: the methodology or the data differ - only chance-normalized skill and average ranks are "
             "compared, without significance.", ""]
    for c in result["comparisons"]:
        lines += [f"## {c['reference']} -> {c['other']} ({c['mode']})", ""]
        if c["reasons"]:
            lines += ["Not directly comparable: " + "; ".join(c["reasons"]) + ".", ""]
        if c.get("notes"):
            lines += ["Methodology differences (cells still paired; changes measure their effect): "
                      + "; ".join(c["notes"]) + ".", ""]
        if c["corpora_in_one_report_only"]:
            lines += ["Corpora in one report only (left out): " + ", ".join(c["corpora_in_one_report_only"]) + ".", ""]
        if c["ranking_agreement"]:
            lines += ["Do both evaluations rank the systems the same way?", "",
                      "| task | systems | Kendall tau of average ranks | best (reference) | best (other) |",
                      "| :--- | ---: | ---: | :--- | :--- |"]
            lines += [f"| {a['task']} | {a['systems']} | {a['kendall_tau']:.3f} | {a['best_reference']} | "
                      f"{a['best_other']} |" for a in c["ranking_agreement"]]
            lines.append("")
        if c.get("changes"):
            lines += ["Paired changes of the primary metric (other - reference):", "",
                      "| task | protocol | system | metric | cells | mean change | improved / worsened / unchanged | p | verdict |",
                      "| :--- | :--- | :--- | :--- | ---: | ---: | :---: | ---: | :--- |"]
            lines += [f"| {x['task']} | {x['protocol']} | {x['system']} | {x['metric']} | {x['cells']} | "
                      f"{x['mean_change']:+.4f} | {x['improved']} / {x['worsened']} / {x['unchanged']} | "
                      f"{x['p_value']:.2g} | **{x['verdict']}** |" for x in c["changes"]]
            lines.append("")
        lines += ["Chance-normalized skill (mean over cells) and average rank:", "",
                  "| task | protocol | system | skill (reference) | skill (other) | change | rank (reference) | rank (other) |",
                  "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |"]
        lines += [f"| {x['task']} | {x['protocol']} | {x['system']} | {x['skill_reference']:.3f} | {x['skill_other']:.3f} | "
                  f"{x['skill_change']:+.3f} | {_fmt(x['rank_reference'], 2)} | {_fmt(x['rank_other'], 2)} |"
                  for x in c["skill"]]
        lines.append("")
    return "\n".join(lines) + "\n"


def write_comparison(result: dict, out_dir) -> List:
    import csv
    import json
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "compare.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "compare.md").write_text(render_markdown(result), encoding="utf-8")
    with (out / "compare.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for c in result["comparisons"]:
            changes = {(x["task"], x["protocol"], x["system"]): x for x in c.get("changes", [])}
            for s in c["skill"]:
                x = changes.get((s["task"], s["protocol"], s["system"]), {})
                values = [c["reference"], c["other"], c["mode"], s["task"], s["protocol"], s["system"], x.get("kind"),
                          x.get("metric"), x.get("cells"), x.get("mean_change"), x.get("improved"), x.get("worsened"),
                          x.get("unchanged"), x.get("p_value"), x.get("verdict", "not tested (indirect)"),
                          s["skill_reference"], s["skill_other"], s["rank_reference"], s["rank_other"]]
                writer.writerow(["" if v is None else (round(v, 6) if isinstance(v, float) else v) for v in values])
    return [out / "compare.md", out / "compare.csv", out / "compare.json"]
