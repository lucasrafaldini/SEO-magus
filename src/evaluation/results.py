"""
Tidy results: every number of a report as one flat row.

One row = one metric of one system in one methodology cell:

  report, protocol_version, protocol_hash          which evaluation (code + protocol) produced it
  corpus, source, language, fingerprint, evidence  on which data, and what it may prove
  task, protocol, sampler, seed                    the methodology cell
  system, kind                                     what was measured (product / oracle / baseline)
  metric, value, ci_low, ci_high, units            the number and its uncertainty

Metrics: the task's primary metric (f1 / ari / spearman, with its bootstrap CI), `skill`
(below), the secondary metrics, recall per stratum `recall[names-2+]` and per planted
style `recall[style:full]`, and the paired comparisons of the run:
`difference[<baseline>]` (with the CI of the paired difference) and
`significant[<baseline>]` (1 = significant after the run's Holm correction).

Every export (CSV, JSON lines, Markdown, HTML) and every calculation reads
these rows, so results of different methodologies, sources and reports share
one schema and can be filtered, grouped and compared the same way.

Derived metric `skill` puts every task on one scale: the share of the way from
chance (the `random` baseline of the same cell) to a perfect score,
    skill = (value - random) / (1 - random)
so F1, ARI and Spearman become comparable (0 = chance level, 1 = perfect,
negative = worse than chance).
"""

import csv
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from src.evaluation.protocol import PROTOCOL

PRIMARY = {"links": "f1", "classification": "ari", "ranking": "spearman"}
CHANCE_SYSTEM = "random"
# Secondary metrics exported per task (besides the primary one); nested ones are flattened below.
SECONDARY = {
    "links": ("precision", "recall", "macro_precision", "macro_recall", "macro_f1", "predicted", "lenient_precision",
              "reader_validated_precision", "false_positives_planted_valid", "false_positives_with_reader_demand",
              "pagerank_rebuilt_rho", "pagerank_stripped_rho"),
    "classification": ("nmi", "purity", "inverse_purity", "clusters"),
    "ranking": ("kendall_tau_b", "ndcg@10", "ndcg@100"),
}


@dataclass(frozen=True)
class Row:
    report: str
    protocol_version: str
    protocol_hash: str
    corpus: str
    source: str
    language: str
    fingerprint: str
    evidence: str
    task: str
    protocol: str
    sampler: str
    seed: int
    system: str
    kind: str
    metric: str
    value: float
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    units: int = 0

    @property
    def cell(self) -> Tuple[str, str, str, str, int]:
        """The methodology cell: everything that defines one measurement except the system."""
        return (self.corpus, self.task, self.protocol, self.sampler, self.seed)


FIELDS = [f.name for f in fields(Row)]


def rows_from_report(report: dict, label: str = "report") -> List[Row]:
    """Flatten a report (runner.evaluate output, or a loaded report.json) into tidy rows."""
    corpora = {c["name"]: c for c in report.get("corpora", [])}
    version = str(report.get("protocol", PROTOCOL).get("version", "?"))
    digest = str(report.get("protocol_hash", "?"))
    rows: List[Row] = []
    for run in report.get("runs", []):
        result = run["result"]
        if "systems" not in result:
            continue
        task = run["task"]
        info = corpora.get(run["corpus"], {})
        provenance = info.get("provenance", {})
        base = dict(report=label, protocol_version=version, protocol_hash=digest, corpus=run["corpus"],
                    source=provenance.get("source", "?"), language=provenance.get("language", "") or "",
                    fingerprint=info.get("fingerprint", ""), evidence=info.get("evidence", {}).get(task, "?"),
                    task=task, protocol=run.get("protocol") or "-", sampler=run["sampler"], seed=int(run["seed"]))
        units = int(result.get("units", 0))
        primary = PRIMARY[task]
        chance = result["systems"].get(CHANCE_SYSTEM, {}).get(primary)
        for system, values in result["systems"].items():
            common = dict(base, system=system, kind=values.get("kind", "?"), units=units)
            ci = values.get(f"{primary}_ci") or {}
            rows.append(Row(**common, metric=primary, value=float(values[primary]),
                            ci_low=ci.get("ci_low"), ci_high=ci.get("ci_high")))
            if chance is not None and chance < 1:
                rows.append(Row(**common, metric="skill", value=(values[primary] - chance) / (1 - chance)))
            for metric in SECONDARY[task]:
                if values.get(metric) is not None:
                    rows.append(Row(**common, metric=metric, value=float(values[metric])))
            for stratum, entry in values.get("recall_by_stratum", {}).items():
                rows.append(Row(**common, metric=f"recall[{stratum}]", value=float(entry["recall"])))
            for style, entry in values.get("recall_by_planted_style", {}).items():
                rows.append(Row(**common, metric=f"recall[style:{style}]", value=float(entry["recall"])))
        kinds = {name: values.get("kind", "?") for name, values in result["systems"].items()}
        for name, comparison in result.get("comparisons", {}).items():
            system, baseline = name.split(" vs ", 1)
            common = dict(base, system=system, kind=kinds.get(system, "?"), units=units)
            rows.append(Row(**common, metric=f"difference[{baseline}]", value=float(comparison["value"]),
                            ci_low=comparison.get("ci_low"), ci_high=comparison.get("ci_high")))
            rows.append(Row(**common, metric=f"significant[{baseline}]",
                            value=1.0 if comparison.get("significant_after_correction") else 0.0))
        if task == "links":
            rows.append(Row(**dict(base, system="(gold)", kind="gold", units=units), metric="anchor_ceiling",
                            value=float(result.get("anchor_ceiling", 0.0))))
    return rows


def select(rows: Iterable[Row], **criteria) -> List[Row]:
    """Rows matching every criterion (a value, or a collection of accepted values)."""
    def accepts(row: Row) -> bool:
        for key, wanted in criteria.items():
            value = getattr(row, key)
            if isinstance(wanted, (list, tuple, set, frozenset)):
                if value not in wanted:
                    return False
            elif value != wanted:
                return False
        return True
    return [row for row in rows if accepts(row)]


def group(rows: Iterable[Row], *keys: str) -> Dict[tuple, List[Row]]:
    groups: Dict[tuple, List[Row]] = {}
    for row in rows:
        groups.setdefault(tuple(getattr(row, k) for k in keys), []).append(row)
    return groups


# ----------------------------------------------------------------- storage


def write_csv(rows: Sequence[Row], path: Union[str, Path], columns: Sequence[str] = tuple(FIELDS)) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            data = asdict(row)
            writer.writerow(["" if data[c] is None else (round(data[c], 6) if isinstance(data[c], float) else data[c])
                             for c in columns])
    return path


def write_jsonl(rows: Sequence[Row], path: Union[str, Path]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
    return path


def read_rows(path: Union[str, Path]) -> List[Row]:
    """Rows back from results.jsonl or runs.csv (e.g. to compare reports without their report.json)."""
    path = Path(path)
    if path.suffix == ".jsonl":
        return [Row(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = []
    with path.open(encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            data: Dict[str, object] = dict(record)
            data["seed"] = int(data["seed"])
            data["units"] = int(data["units"] or 0)
            data["value"] = float(data["value"])
            for key in ("ci_low", "ci_high"):
                data[key] = float(data[key]) if data[key] not in ("", None) else None
            rows.append(Row(**data))
    return rows


def load_rows(path: Union[str, Path], label: Optional[str] = None) -> List[Row]:
    """Rows of a report.json, results.jsonl or runs.csv; `label` names the report in comparisons."""
    path = Path(path)
    if path.suffix == ".json":
        return rows_from_report(json.loads(path.read_text(encoding="utf-8")), label or path.parent.name or path.stem)
    rows = read_rows(path)
    if label:
        rows = [Row(**{**asdict(r), "report": label}) for r in rows]
    return rows
