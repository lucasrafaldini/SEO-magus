"""
Runs the protocol over every corpus and consolidates the verdicts.

For each corpus, every task its layers allow is run under every sampler and
every seed (and, for links, every removal protocol). A comparison "system
beats baseline" is then judged:

  per run         paired bootstrap CI of the difference in the primary metric and its
                  one-sided p-value, Holm-Bonferroni corrected over the comparisons of
                  that run (alpha and the reasons for this family in protocol.py)
  per corpus      "robust"    significant after correction in every sampler x seed run
                  "mixed"     significant in some runs only
                  "no"        significant in none
                  "worse"     the baseline is significantly better in some run
  across sources  a claim is supported only when it is "robust" on every real
                  corpus that has the layer; synthetic corpora never count as evidence
                  for classification and ranking (their answers are defined by the
                  generator) and only per link style for links
"""

import time
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from src.evaluation import tasks
from src.evaluation.corpus import Corpus
from src.evaluation.protocol import PROTOCOL, holm, protocol_hash
from src.evaluation.sampling import SAMPLERS
from src.evaluation.systems import LINK_SYSTEMS

TASK_LAYERS = {"links": "links", "classification": "labels", "ranking": "popularity"}
PRIMARY = PROTOCOL["primary_metric"]


def evidence_role(corpus: Corpus, task: str) -> str:
    if corpus.provenance.source == "synthetic":
        return "by construction, per link style" if task == "links" else "code validation only"
    if len(corpus) < PROTOCOL["min_units"]:
        return "too small for evidence"
    return "evidence"


def _primary_value(result: dict, system: str) -> Optional[float]:
    metric = {"links": "f1", "classification": "ari", "ranking": "spearman"}[result["task"]]
    return result["systems"].get(system, {}).get(metric)


def evaluate(corpora: Sequence[Corpus], task_names: Iterable[str] = ("links", "classification", "ranking"),
             samplers: Optional[Sequence[str]] = None, seeds: Optional[Sequence[int]] = None,
             sample_size: Optional[int] = None, link_protocols: Optional[Sequence[str]] = None,
             link_systems=None, progress: Callable[[str], None] = lambda message: None) -> dict:
    samplers = list(samplers or PROTOCOL["samplers"])
    seeds = list(seeds or PROTOCOL["seeds"])
    sample_size = sample_size or PROTOCOL["sample_size"]
    link_protocols = list(link_protocols or PROTOCOL["link_protocols"])
    link_systems = link_systems or LINK_SYSTEMS
    task_names = list(task_names)
    started = time.time()
    runs: List[dict] = []
    corpora_info = []
    for corpus in corpora:
        layers = corpus.layers
        corpora_info.append({
            "name": corpus.name, "fingerprint": corpus.fingerprint(), "documents": len(corpus),
            "layers": sorted(layers), "provenance": vars(corpus.provenance),
            "evidence": {t: evidence_role(corpus, t) for t in task_names if TASK_LAYERS[t] in layers},
        })
        for task in task_names:
            if TASK_LAYERS[task] not in layers:
                progress(f"{corpus.name}: {task} skipped (no {TASK_LAYERS[task]} layer)")
                continue
            for sampler in samplers:
                for seed in seeds:
                    sample = SAMPLERS[sampler](corpus, sample_size, seed)
                    variants = link_protocols if task == "links" else [None]
                    for protocol in variants:
                        t0 = time.time()
                        if task == "links":
                            result = tasks.link_task(corpus, sample, protocol, seed, link_systems)
                        elif task == "classification":
                            result = tasks.classification_task(corpus, sample, seed)
                        else:
                            result = tasks.ranking_task(corpus, sample, seed)
                        runs.append({"corpus": corpus.name, "task": task, "sampler": sampler, "seed": seed,
                                     "protocol": protocol, "result": result})
                        progress(f"{corpus.name}: {task}{'/' + protocol if protocol else ''} {sampler} seed {seed} "
                                 f"({time.time() - t0:.1f}s)")
    _correct(runs)
    return {
        "protocol": PROTOCOL, "protocol_hash": protocol_hash(),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seconds": round(time.time() - started, 1),
        "settings": {"tasks": task_names, "samplers": samplers, "seeds": seeds, "sample_size": sample_size,
                     "link_protocols": link_protocols},
        "corpora": corpora_info, "runs": runs,
        "summary": summarize(runs, corpora_info),
    }


def _correct(runs: List[dict]) -> None:
    """Holm-Bonferroni over the comparisons of each run (see protocol.py for the family choice)."""
    for run in runs:
        comparisons = run["result"].get("comparisons", {})
        rejected = holm({name: c["p_not_better"] for name, c in comparisons.items()}) if comparisons else {}
        for name, significant in rejected.items():
            comparison = comparisons[name]
            comparison["significant_after_correction"] = significant and comparison["verdict"] == "better"
            if comparison["verdict"] == "better" and not significant:
                comparison["verdict"] = "not significant after correction"


def _group_key(run: dict) -> tuple:
    return run["corpus"], run["task"], run["protocol"]


def summarize(runs: List[dict], corpora_info: List[dict]) -> dict:
    """Per (corpus, task, protocol): metric ranges per system and consolidated verdicts."""
    groups: Dict[tuple, List[dict]] = {}
    for run in runs:
        if "systems" in run["result"]:
            groups.setdefault(_group_key(run), []).append(run)
    evidence = {info["name"]: info["evidence"] for info in corpora_info}
    summary = []
    for (corpus, task, protocol), members in groups.items():
        systems: Dict[str, dict] = {}
        for name in members[0]["result"]["systems"]:
            values = [v for v in (_primary_value(r["result"], name) for r in members) if v is not None]
            systems[name] = {"kind": members[0]["result"]["systems"][name]["kind"], "mean": sum(values) / len(values),
                             "min": min(values), "max": max(values), "runs": len(values)}
        verdicts: Dict[str, str] = {}
        for name in members[0]["result"].get("comparisons", {}):
            outcomes = [r["result"]["comparisons"][name] for r in members]
            better = sum(1 for o in outcomes if o.get("significant_after_correction"))
            worse = sum(1 for o in outcomes if o["verdict"] == "worse")
            small = members[0]["result"].get("units", 0) < PROTOCOL["min_units"]
            verdicts[name] = ("insufficient data" if small else "worse" if worse else
                              "robust" if better == len(outcomes) else "mixed" if better else "no")
        summary.append({"corpus": corpus, "task": task, "protocol": protocol, "metric": PRIMARY[task],
                        "evidence": evidence.get(corpus, {}).get(task, "?"), "systems": systems,
                        "verdicts": verdicts, "runs": len(members)})
    return {"groups": summary, "claims": _claims(summary)}


def _claims(summary: List[dict]) -> List[dict]:
    """Cross-source view: each product-vs-baseline claim on every corpus that can test it."""
    claims: Dict[tuple, Dict[str, str]] = {}
    for group in summary:
        for name, verdict in group["verdicts"].items():
            key = (group["task"], group["protocol"], name)
            claims.setdefault(key, {})[group["corpus"]] = f"{verdict} ({group['evidence']})"
    out = []
    for (task, protocol, name), by_corpus in sorted(claims.items(), key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2])):
        real = {c: v for c, v in by_corpus.items() if "(evidence)" in v}
        if not real:
            status = "untested on real data"
        elif all(v.startswith("robust") for v in real.values()):
            status = "supported on every real source"
        elif any(v.startswith(("worse",)) for v in real.values()):
            status = "contradicted on some real source"
        else:
            status = "not established"
        out.append({"task": task, "protocol": protocol, "claim": name, "status": status, "by_corpus": by_corpus})
    return out
