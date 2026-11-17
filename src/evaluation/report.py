"""
Evaluation report and exports, at two levels.

Simple (read them, open them in a spreadsheet):
  report.md     the report: at a glance, claims matrix, scores, ranks, methodologies,
                meta-analysis, diagnostics, crawl and scale
  summary.csv   one row per task x protocol x corpus x system: runs, mean, median, sd,
                min, max, chance-normalized skill, rank within the corpus, result
                against the strongest baseline
  claims.csv    one row per claim: status and the verdict on every corpus

Full (everything, for analysis, dashboards and comparisons between reports):
  report.json   the raw report (source of every other file; re-export with `export`)
  runs.csv      tidy rows: every metric of every system in every methodology cell
  results.jsonl the same rows as JSON lines
  analysis.json every calculation of analysis.py (descriptive, wins, ranks, agreement,
                sensitivity, meta-analysis)
  report.html   self-contained visual report (charts, no JavaScript)

Numbers are means over sampler x seed runs with their min-max range, so
instability is visible next to every value.
"""

import csv
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from src.evaluation.analysis import analyze
from src.evaluation.html_report import render_html
from src.evaluation.narrative import at_a_glance
from src.evaluation.protocol import PROTOCOL
from src.evaluation.results import PRIMARY, Row, rows_from_report, write_csv, write_jsonl

LEVELS = ("simple", "full")
SIMPLE_FILES = ("report.json", "report.md", "summary.csv", "claims.csv")
FULL_FILES = SIMPLE_FILES + ("runs.csv", "results.jsonl", "analysis.json", "report.html")


def _fmt(value: Optional[float], digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def write_report(report: dict, out_dir: Union[str, Path], extra: Optional[Dict[str, dict]] = None,
                 level: str = "full", label: Optional[str] = None) -> List[Path]:
    """Write the report and its exports (see the module docstring); returns the written paths."""
    if level not in LEVELS:
        raise ValueError(f"export level must be one of {LEVELS}, got {level!r}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if extra:
        report = {**report, **extra}
    rows = rows_from_report(report, label or out.name or "report")
    analysis = analyze(rows)
    written = []
    path = out / "report.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    written.append(path)
    path = out / "report.md"
    path.write_text(render_markdown(report, rows, analysis, level), encoding="utf-8")
    written.append(path)
    written.append(write_summary_csv(analysis, out / "summary.csv"))
    written.append(write_claims_csv(report, out / "claims.csv"))
    if level == "full":
        written.append(write_csv(rows, out / "runs.csv"))
        written.append(write_jsonl(rows, out / "results.jsonl"))
        path = out / "analysis.json"
        path.write_text(json.dumps(analysis, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        written.append(path)
        path = out / "report.html"
        path.write_text(render_html(report, rows, analysis), encoding="utf-8")
        written.append(path)
    return written


# ------------------------------------------------------------ simple CSV

SUMMARY_COLUMNS = ("task", "protocol", "corpus", "evidence", "system", "kind", "metric", "runs", "mean", "median",
                   "sd", "min", "max", "skill", "rank_in_corpus", "best_baseline", "win_rate_vs_best_baseline",
                   "mean_difference_vs_best_baseline", "significant_share_vs_best_baseline")


def write_summary_csv(analysis: dict, path: Union[str, Path]) -> Path:
    ranks = {(r["task"], r["protocol"], r["corpus"]): r["average_rank"] for r in analysis["ranks"] if r["corpus"] != "(all)"}
    best_baseline: Dict[tuple, str] = {}
    for entry in analysis["describe"]:
        if entry["kind"] == "baseline" and entry.get("n"):
            key = (entry["task"], entry["protocol"], entry["corpus"])
            current = best_baseline.get(key)
            means = {e["system"]: e["mean"] for e in analysis["describe"]
                     if (e["task"], e["protocol"], e["corpus"]) == key and e["kind"] == "baseline"}
            if current is None or means[entry["system"]] > means[current]:
                best_baseline[key] = entry["system"]
    wins = {(w["task"], w["protocol"], w["corpus"], w["system"], w["baseline"]): w for w in analysis["wins"]}
    path = Path(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SUMMARY_COLUMNS)
        for e in analysis["describe"]:
            if not e.get("n"):
                continue
            key = (e["task"], e["protocol"], e["corpus"])
            baseline = best_baseline.get(key, "")
            w = wins.get(key + (e["system"], baseline), {})
            rank = ranks.get((e["task"], e["protocol"], e["corpus"]), {}).get(e["system"])
            values = [e["task"], e["protocol"], e["corpus"], e["evidence"], e["system"], e["kind"], e["metric"], e["n"],
                      e["mean"], e["median"], e["sd"], e["min"], e["max"], e.get("skill"), rank, baseline,
                      w.get("win_rate"), w.get("mean_difference"), w.get("significant_share")]
            writer.writerow(["" if v is None else (round(v, 6) if isinstance(v, float) else v) for v in values])
    return path


def write_claims_csv(report: dict, path: Union[str, Path]) -> Path:
    corpora = [c["name"] for c in report.get("corpora", [])]
    path = Path(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["task", "protocol", "claim", "status"] + corpora)
        for claim in report.get("summary", {}).get("claims", []):
            writer.writerow([claim["task"], claim["protocol"] or "-", claim["claim"], claim["status"]]
                            + [claim["by_corpus"].get(c, "").split(" (")[0] for c in corpora])
    return path


# -------------------------------------------------------------- Markdown


def render_markdown(report: dict, rows: Optional[Sequence[Row]] = None, analysis: Optional[dict] = None,
                    level: str = "full") -> str:
    rows = rows_from_report(report) if rows is None else rows
    analysis = analyze(rows) if analysis is None else analysis
    lines: List[str] = ["# SEO-Magus evaluation report", ""]
    settings = report.get("settings", {})
    if settings:
        lines += [
            f"Protocol v{report.get('protocol', PROTOCOL)['version']} (hash `{report.get('protocol_hash', '?')}`), "
            f"generated {report.get('generated_at', '?')} in {report.get('seconds', '?')} s. "
            f"Samplers: {', '.join(settings.get('samplers', []))}; seeds: {settings.get('seeds')}; "
            f"{settings.get('sample_size')} documents per run; link protocols: "
            f"{', '.join(settings.get('link_protocols', []))}.", ""]
    lines += _glance(report, analysis)
    lines += _claims(report) + _corpora(report) + _checklist(report) + _scores(analysis) + _skipped(report)
    lines += _ranks(analysis)
    lines += _methodologies(analysis) + _meta(analysis) + _link_diagnostics(report)
    if "crawl" in report:
        lines += _crawl(report["crawl"])
    if "scale" in report:
        lines += _scale(report["scale"])
    lines += _files(level)
    return "\n".join(lines) + "\n"


def _glance(report: dict, analysis: dict) -> List[str]:
    points = at_a_glance(report, analysis)
    return (["## At a glance", ""] + [f"* **{title}**: {text}" for title, text in points] + [""]) if points else []


def _abbreviations(report: dict) -> Dict[str, str]:
    return {c["name"]: f"C{i + 1}" for i, c in enumerate(report.get("corpora", []))}


def _claims(report: dict) -> List[str]:
    claims = report.get("summary", {}).get("claims", [])
    if not claims:
        return []
    short = _abbreviations(report)
    columns = list(short)
    lines = ["## Claims", "",
             "Does each system beat each baseline? One column per corpus (key below). `robust` = significant "
             "(Holm-corrected within the run) in every sampler x seed run; `mixed` = in some; `no` = in none; `worse` = "
             "the baseline is significantly better somewhere; `too small` = fewer documents than the protocol's minimum; "
             "`supported` = robust on every real source.",
             "", "| task | protocol | claim | status | " + " | ".join(short[c] for c in columns) + " |",
             "| :--- | :--- | :--- | :--- | " + " | ".join(":---:" for _ in columns) + " |"]
    for claim in claims:
        cells = [claim["by_corpus"].get(c, "·").split(" (")[0].replace("insufficient data", "too small")
                 for c in columns]
        lines.append(f"| {claim['task']} | {claim['protocol'] or '-'} | {claim['claim']} | **{claim['status']}** | "
                     + " | ".join(cells) + " |")
    lines += ["", "Corpus key: " + "; ".join(f"{short[c]} = {c}" for c in columns) + ".", ""]
    return lines


def _corpora(report: dict) -> List[str]:
    lines = ["## Corpora", "", "| corpus | source / access path | documents | ground-truth layers | evidence role | fingerprint |",
             "| :--- | :--- | ---: | :--- | :--- | :--- |"]
    for c in report.get("corpora", []):
        roles = "; ".join(f"{t}: {r}" for t, r in c["evidence"].items())
        lines.append(f"| {c['name']} | {c['provenance']['source']} / {c['provenance']['method']} | {c['documents']} | "
                     f"{', '.join(c['layers'])} | {roles} | `{c['fingerprint']}` |")
    return lines + [""]


def _checklist(report: dict) -> List[str]:
    corpora = report.get("corpora", [])
    real = [c for c in corpora if c["provenance"]["source"] != "synthetic"]
    sources = sorted({c["provenance"]["source"] for c in corpora})
    methods = sorted({c["provenance"]["method"] for c in corpora})
    settings = report.get("settings", {})
    checks = [
        ("independent real sources", len({c["provenance"]["source"] for c in real}) >= 2,
         f"{len(real)} real corpora from {sorted({c['provenance']['source'] for c in real}) or 'none'}"),
        ("several access paths", len(methods) >= 2, ", ".join(methods)),
        ("several samplers", len(settings.get("samplers", [])) >= 3, ", ".join(settings.get("samplers", []))),
        ("repeated seeds", len(settings.get("seeds", [])) >= 3, str(settings.get("seeds"))),
        ("baselines in every task", True, "random + naive alternatives (see docs/EVALUATION.md)"),
        ("multiple-comparison correction", True, "Holm-Bonferroni per run + replication across every run and source"),
        ("pre-registered protocol", True, f"hash {report.get('protocol_hash')}"),
        ("gold incompleteness measured", any("clickstream" in c["layers"] or c["provenance"]["source"] == "synthetic"
                                              for c in corpora), "clickstream and/or planted valid mentions"),
        ("more than one language", len({c["provenance"].get("language") for c in corpora} - {""}) > 1,
         ", ".join(sorted({c["provenance"].get("language") or "unknown" for c in corpora}))),
    ]
    lines = ["## Bias checklist", "", "| control | met | detail |", "| :--- | :---: | :--- |"]
    for name, met, detail in checks:
        lines.append(f"| {name} | {'yes' if met else '**NO**'} | {detail} |")
    if not real:
        lines += ["", "> **No real corpus in this report.** Synthetic results validate the code and measure behaviour "
                      "per link style; they are not evidence of real-world quality. Fetch real sources "
                      "(docs/EVALUATION.md) before drawing conclusions."]
    return lines + ["", f"Sources: {', '.join(sources)}.", ""]


def _scores(analysis: dict) -> List[str]:
    entries = analysis["describe"]
    if not entries:
        return []
    lines = ["## Scores", "", "Primary metric, mean over sampler x seed runs [min-max]; *skill* = chance-normalized "
             "score averaged over corpora (0 = random baseline, 1 = perfect), comparable across tasks.", ""]
    by_group: Dict[tuple, List[dict]] = {}
    for e in entries:
        by_group.setdefault((e["task"], e["protocol"]), []).append(e)
    for (task, protocol), members in sorted(by_group.items()):
        corpora = sorted({e["corpus"] for e in members})
        systems = sorted({e["system"]: e["kind"] for e in members}.items(), key=lambda kv: (kv[1] != "product", kv[0]))
        cell = {(e["system"], e["corpus"]): e for e in members}
        title = f"### {task} ({PRIMARY[task]}{'' if protocol == '-' else ', ' + protocol})"
        lines += [title, "", "| system | kind | " + " | ".join(corpora) + " | skill |",
                  "| :--- | :--- | " + " | ".join("---:" for _ in corpora) + " | ---: |"]
        for system, kind in systems:
            values = []
            skills = []
            for corpus in corpora:
                e = cell.get((system, corpus))
                if e and e.get("n"):
                    values.append(f"{_fmt(e['mean'])} [{_fmt(e['min'], 2)}-{_fmt(e['max'], 2)}]")
                    if e.get("skill") is not None:
                        skills.append(e["skill"])
                else:
                    values.append("-")
            skill = sum(skills) / len(skills) if skills else None
            lines.append(f"| {system} | {kind} | " + " | ".join(values) + f" | {_fmt(skill)} |")
        lines.append("")
    return lines


def _skipped(report: dict) -> List[str]:
    """Tasks a corpus could not answer, and why (a missing layer is reported, never scored as zero)."""
    skipped = sorted({(r["corpus"], r["task"], r["result"]["skipped"]) for r in report.get("runs", [])
                      if "skipped" in r["result"]})
    if not skipped:
        return []
    return ["Skipped:", ""] + [f"* {corpus}: {task} skipped - {why}" for corpus, task, why in skipped] + [""]


def _ranks(analysis: dict) -> List[str]:
    overall = [r for r in analysis["ranks"] if r["corpus"] == "(all)"]
    if not overall:
        return []
    lines = ["## Ranks across methodologies", "",
             "Average rank over every methodology cell (corpus x protocol x sampler x seed; 1 = best). Friedman tests "
             "\"all systems alike\"; systems within the Nemenyi critical difference (CD) of the best are not "
             "significantly different from it.", ""]
    for r in overall:
        cd = r["critical_difference"]
        lines += [f"### {r['task']}: {r['cells']} cells, Friedman chi2 {r['chi2']:.1f}, p {r['p_value']:.2g}, "
                  f"CD {_fmt(cd, 2)}", "", "| rank | system | kind | average rank | tied with best |",
                  "| ---: | :--- | :--- | ---: | :---: |"]
        for i, (system, value) in enumerate(r["average_rank"].items(), start=1):
            lines.append(f"| {i} | {system} | {r['kind'].get(system, '?')} | {value:.2f} | "
                         f"{'yes' if system in r['tied_with_best'] else ''} |")
        lines.append("")
    per_corpus = [r for r in analysis["ranks"] if r["corpus"] != "(all)"]
    if per_corpus:
        lines += ["Best system per corpus (average rank over its sampler x seed cells):", "",
                  "| task | protocol | corpus | best | tied with best | Friedman p |",
                  "| :--- | :--- | :--- | :--- | :--- | ---: |"]
        for r in per_corpus:
            best = next(iter(r["average_rank"]))
            lines.append(f"| {r['task']} | {r['protocol']} | {r['corpus']} | {best} | "
                         f"{', '.join(s for s in r['tied_with_best'] if s != best) or '-'} | {r['p_value']:.2g} |")
        lines.append("")
    return lines


def _methodologies(analysis: dict) -> List[str]:
    if not analysis["agreement"] and not analysis["sensitivity"]:
        return []
    lines = ["## Methodologies compared", "",
             "Would another methodology tell another story? Systems are ranked under each level of each factor; "
             "Kendall's W is the agreement of those rankings (1 = identical).", "",
             "| task | factor | levels | Kendall's W | same winner | winner per level |",
             "| :--- | :--- | ---: | ---: | :---: | :--- |"]
    for a in analysis["agreement"]:
        winners = "; ".join(f"{level}: {system}" for level, system in a["winner_by_level"].items())
        lines.append(f"| {a['task']} | {a['factor']} | {a['levels']} | {a['kendall_w']:.3f} | "
                     f"{'yes' if a['same_winner'] else '**no**'} | {winners} |")
    lines += ["", "Share of each system's score variance explained by each factor alone (eta squared):", "",
              "| task | system | kind | runs | sd | corpus | protocol | sampler | seed |",
              "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for s in analysis["sensitivity"]:
        lines.append(f"| {s['task']} | {s['system']} | {s['kind']} | {s['runs']} | {s['sd']:.3f} | "
                     + " | ".join(f"{s[f'eta2_{f}']:.0%}" for f in ("corpus", "protocol", "sampler", "seed")) + " |")
    return lines + [""]


def _meta(analysis: dict) -> List[str]:
    entries = [m for m in analysis["meta"] if m["kind"] != "baseline" and m.get("all")]
    if not entries:
        return []
    lines = ["## Meta-analysis across sources", "",
             "Paired difference of the primary metric (system minus baseline) per corpus, pooled with random effects "
             "(DerSimonian-Laird). I² = share of the variation due to real differences between corpora; a high I² "
             "means the advantage depends on the source. *Real only* pools the corpora that count as evidence.", "",
             "| task | protocol | system | baseline | corpora | pooled [95% CI] | I² | real only |",
             "| :--- | :--- | :--- | :--- | ---: | :--- | ---: | :--- |"]
    for m in entries:
        pooled, real = m["all"], m.get("real")
        real_text = f"{real['pooled']:+.3f} [{real['ci_low']:+.3f}, {real['ci_high']:+.3f}]" if real else "no real source"
        lines.append(f"| {m['task']} | {m['protocol']} | {m['system']} | {m['baseline']} | {pooled['sources']} | "
                     f"{pooled['pooled']:+.3f} [{pooled['ci_low']:+.3f}, {pooled['ci_high']:+.3f}] | "
                     f"{pooled['i2']:.0%} | {real_text} |")
    return lines + [""]


def _files(level: str) -> List[str]:
    simple = [("report.md", "this report"), ("summary.csv", "one row per task x protocol x corpus x system"),
              ("claims.csv", "one row per claim, one column per corpus"),
              ("report.json", "the raw report (re-export with `python -m src.evaluation export`)")]
    full = [("report.html", "visual report: heatmaps, rank diagrams, forest plots"),
            ("runs.csv / results.jsonl", "tidy rows: every metric of every system in every methodology cell"),
            ("analysis.json", "every calculation behind this report")]
    lines = ["## Files", "", "Simple exports:", ""] + [f"* `{n}` - {d}" for n, d in simple]
    if level == "full":
        lines += ["", "Full exports:", ""] + [f"* `{n}` - {d}" for n, d in full]
    return lines + [""]


def _mean(values: List[float]) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _link_diagnostics(report: dict) -> List[str]:
    runs = [r for r in report.get("runs", []) if r["task"] == "links" and "systems" in r["result"]]
    if not runs:
        return []
    lines = ["## Link diagnostics", "", "Means over runs.", "",
             "* *ceiling*: share of removed links whose anchor names >= 2 words of the target title (reachable by "
             "anchor-based linking);",
             "* *lenient P*: precision against every human link layer;",
             "* *reader P*: precision counting reader-demanded pairs (clickstream) as correct;",
             "* *FP valid*: share of false positives that are planted valid mentions (synthetic);",
             "* *PR rebuilt*: Spearman between the editors' PageRank and the PageRank after adding the proposals.", ""]
    for corpus in sorted({r["corpus"] for r in runs}):
        for protocol in sorted({r["protocol"] for r in runs if r["corpus"] == corpus}):
            members = [r["result"] for r in runs if r["corpus"] == corpus and r["protocol"] == protocol]
            ceiling = _mean([m["anchor_ceiling"] for m in members])
            stripped = _mean([m["systems"][next(iter(m["systems"]))]["pagerank_stripped_rho"] for m in members])
            lines += [f"### {corpus} / {protocol} (ceiling {_fmt(ceiling)}, PageRank without the removed links "
                      f"{_fmt(stripped)})", "",
                      "| system | P | R | F1 | R names-2+ | R names-1 | R names-0 | lenient P | reader P | FP valid | PR rebuilt |",
                      "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
            for system in members[0]["systems"]:
                rows = [m["systems"][system] for m in members]
                strata = [_fmt(_mean([r["recall_by_stratum"].get(s, {}).get("recall") for r in rows]))
                          for s in ("names-2+", "names-1", "names-0")]
                lines.append(
                    f"| {system} | {_fmt(_mean([r['precision'] for r in rows]))} | {_fmt(_mean([r['recall'] for r in rows]))} | "
                    f"{_fmt(_mean([r['f1'] for r in rows]))} | " + " | ".join(strata) + " | "
                    f"{_fmt(_mean([r.get('lenient_precision') for r in rows]))} | "
                    f"{_fmt(_mean([r.get('reader_validated_precision') for r in rows]))} | "
                    f"{_fmt(_mean([r.get('false_positives_planted_valid') for r in rows]))} | "
                    f"{_fmt(_mean([r['pagerank_rebuilt_rho'] for r in rows]))} |")
            styles = sorted({s for m in members for r in m["systems"].values() for s in r.get("recall_by_planted_style", {})})
            if styles:
                lines += ["", "Recall by planted link style:", "",
                          "| system | " + " | ".join(styles) + " |", "| :--- | " + " | ".join("---:" for _ in styles) + " |"]
                for system in members[0]["systems"]:
                    values = [_fmt(_mean([m["systems"][system]["recall_by_planted_style"].get(s, {}).get("recall")
                                          for m in members])) for s in styles]
                    lines.append(f"| {system} | " + " | ".join(values) + " |")
            lines.append("")
    return lines


def _crawl(results: List[dict]) -> List[str]:
    lines = ["## Crawl fidelity", "", "| corpus | documents | coverage | titles | paragraphs | link recall | "
             "link precision | nav leaks | pages/s (lower bound) |", "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in results:
        lines.append(f"| {r.get('corpus', '?')} | {r['documents']} | {_fmt(r['coverage'])} | {_fmt(r['title_exact'])} | "
                     f"{_fmt(r['paragraphs_exact'])} | {_fmt(r['link_recall'])} | {_fmt(r['link_precision'])} | "
                     f"{r['navigation_leaks']} | {r['pages_per_second']} |")
    return lines + [""]


def _scale(result: dict) -> List[str]:
    lines = [f"## Scale ({result['preset']}, seed {result['seed']})", "",
             f"Fitted growth: time ~ n^{result['time_exponent']:.2f}, classifier calls ~ n^{result['calls_exponent']:.2f}.", "",
             "| pages | seconds | classifier calls | links | exhaustive seconds | exhaustive calls | identical links |",
             "| ---: | ---: | ---: | ---: | ---: | ---: | :---: |"]
    for row in result["rows"]:
        lines.append(f"| {row['pages']} | {row['seconds']} | {row['classifier_calls']} | {row['links']} | "
                     f"{row.get('exhaustive_seconds', '-')} | {row.get('exhaustive_calls', '-')} | "
                     f"{'yes' if row.get('identical_links') else ('-' if 'identical_links' not in row else '**NO**')} |")
    return lines + [""]
