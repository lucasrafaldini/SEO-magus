"""
Machine-readable exports: JSON and CSV.

The terminal tables and the HTML report are for humans; this module writes the
same run as data, so CI jobs, dashboards and spreadsheets can consume it:

  * `write_json(source, path)`  - one JSON document with the site audit issues,
    the page ranking and the proposed links (see `export_document`);
  * `write_csv(source, directory)` - `issues.csv`, `pages.csv` and `links.csv`
    (only the files the run has data for);
  * `failing_issues(source, severity)` - the issues at least as severe as
    `severity`, used by the CLI `--fail-on` exit-code check.

`source` is either a `SiteAuditReport` (the `crawl` command, audit only) or a
`SiteAnalysis` (the `audit` command: audit + ranking + proposed links), so both
commands export the same document shape; sections with no data are empty.
Everything is plain JSON/CSV data (no objects), sorted deterministically, so
two runs of the same crawl produce the same file except for `generated_at`.
"""

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from src.log import get_logger
from src.reporting.analysis import SiteAnalysis
from src.workflows.site_audit import SEVERITY_ORDER, SeoIssue, SiteAuditReport

logger = get_logger(__name__)

SCHEMA = "seo-magus/audit"
SCHEMA_VERSION = 1

#: Accepted export sources: the site audit alone, or the full analysis.
ExportSource = Union[SiteAuditReport, SiteAnalysis]
PathLike = Union[str, Path]

ISSUE_FIELDS = ("severity", "code", "url", "detail", "affected_pages")
PAGE_FIELDS = (
    "rank_after", "rank_before", "rank_change", "url", "label", "role", "cluster", "pagerank_before",
    "pagerank_after", "cheirank", "weighted_pagerank", "click_depth", "inbound_before", "inbound_after",
    "outbound_after", "new_inbound", "new_outbound", "navigation_inbound", "crawled", "indexable",
    "orphan_before", "orphan_after", "page2", "gsc_query", "gsc_position", "gsc_impressions",
)
LINK_FIELDS = (
    "source_url", "target_url", "anchor_text", "relevance_score", "confidence", "classifier", "cluster",
    "page2_query", "page2_impressions", "rationale", "original_sentence", "updated_sentence",
)
CSV_FILES = ("issues", "pages", "links")


# ------------------------------------------------------------------ row builders

def site_audit_of(source: Optional[ExportSource]) -> Optional[SiteAuditReport]:
    """The SiteAuditReport of either export source (None when the run has no crawl)."""
    if isinstance(source, SiteAuditReport):
        return source
    return getattr(source, "site_audit", None)


def _analysis_of(source: Optional[ExportSource]) -> Optional[SiteAnalysis]:
    """The SiteAnalysis of the source (None for an audit-only export: no ranking, no proposals)."""
    return source if isinstance(source, SiteAnalysis) else None


def issue_rows(source: Optional[ExportSource]) -> List[Dict[str, Any]]:
    """Audit issues, most severe first (the order of the report)."""
    audit = site_audit_of(source)
    if audit is None:
        return []
    return [
        {
            "severity": issue.severity,
            "code": issue.code,
            "url": issue.url,
            "detail": issue.detail,
            "affected_pages": sorted(issue.affected_pages),
        }
        for issue in audit.issues
    ]


def page_rows(source: Optional[ExportSource]) -> List[Dict[str, Any]]:
    """Page ranking rows, best first (PageRank after the proposed links)."""
    analysis = _analysis_of(source)
    if analysis is None:
        return []
    rows = []
    for page in analysis.pages:
        data = asdict(page)
        data.update(rank_change=page.rank_change, orphan_before=page.orphan_before, orphan_after=page.orphan_after)
        rows.append({name: data[name] for name in PAGE_FIELDS})
    return rows


def link_rows(source: Optional[ExportSource]) -> List[Dict[str, Any]]:
    """Proposed internal links, page 2 boosting links first (the order of the report)."""
    analysis = _analysis_of(source)
    if analysis is None:
        return []
    rows = []
    for result in analysis.report.results:
        data = asdict(result)
        rows.append({name: data[name] for name in LINK_FIELDS})
    return rows


def site_audit_summary(audit: SiteAuditReport) -> Dict[str, Any]:
    """Site health counters of one audit (the numbers printed above the issue table)."""
    return {
        "start_url": audit.start_url,
        "max_click_depth": audit.max_click_depth,
        "health": round(audit.health, 6),
        "pages": len(audit.pages),
        "healthy_pages": len(audit.healthy_pages),
        "unhealthy_pages": len(audit.unhealthy_pages),
        "non_indexable_pages": len(audit.non_indexable),
        "issues": len(audit.issues),
        "counts_by_severity": dict(audit.by_severity),
        "counts_by_code": dict(sorted(audit.counts.items())),
    }


def _optimization_summary(analysis: SiteAnalysis) -> Dict[str, Any]:
    report = analysis.report
    return {
        "pages_evaluated": report.total_pages_evaluated,
        "classifier": report.classifier,
        "classifier_calls": report.candidate_pairs_checked,
        "classifier_fallbacks": report.classifier_fallbacks,
        "estimated_cost_usd": round(report.estimated_cost_usd, 6),
        "duration_seconds": report.duration_seconds,
        "links_proposed": report.links_approved,
        "page2_pages_boosted": len(report.page2_pages_boosted),
        "orphan_pages_before": sum(1 for p in analysis.pages if p.crawled and p.orphan_before),
        "orphan_pages_after": sum(1 for p in analysis.pages if p.crawled and p.orphan_after),
        "decisions_by_reason": dict(sorted(report.decisions_by_reason.items())),
    }


# ------------------------------------------------------------------- documents

def export_document(source: Optional[ExportSource], name: Optional[str] = None, key: Optional[str] = None) -> Dict[str, Any]:
    """
    The whole run as one JSON-serializable document:

        schema, schema_version, generated_at (UTC, ISO 8601)
        site            key, name, url
        site_audit      health counters and counts (null without a crawl)
        optimization    classifier, cost and decision counters (null for `crawl`)
        issues          audit issues, most severe first
        pages           page ranking, best first (empty for `crawl`)
        links           proposed links (empty for `crawl`)
    """
    audit, analysis = site_audit_of(source), _analysis_of(source)
    url = audit.start_url if audit is not None else ""
    site = {
        "key": key or (analysis.key if analysis is not None else "crawl"),
        "name": name or (analysis.name if analysis is not None else url),
        "url": url,
    }
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "site": site,
        "site_audit": site_audit_summary(audit) if audit is not None else None,
        "optimization": _optimization_summary(analysis) if analysis is not None else None,
        "issues": issue_rows(source),
        "pages": page_rows(source),
        "links": link_rows(source),
    }


def to_json(source: Optional[ExportSource], name: Optional[str] = None, indent: int = 2) -> str:
    """The export document as a JSON string (UTF-8 text, not escaped to ASCII)."""
    return json.dumps(export_document(source, name=name), indent=indent, ensure_ascii=False, sort_keys=False)


def write_json(source: Optional[ExportSource], path: PathLike, name: Optional[str] = None) -> Path:
    """Write the export document to `path` (parent directories are created)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(source, name=name) + "\n", encoding="utf-8")
    logger.info("JSON export written: %s (%d issues, %d pages, %d links)",
                path, len(issue_rows(source)), len(page_rows(source)), len(link_rows(source)))
    return path


# ------------------------------------------------------------------------ CSV

def _write_csv_file(path: Path, fields: Sequence[str], rows: List[Dict[str, Any]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _csv_value(v) for k, v in row.items()})
    return path


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, set, frozenset)):
        return " ".join(str(v) for v in value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def write_csv(source: Optional[ExportSource], directory: PathLike) -> List[Path]:
    """
    Write `issues.csv`, `pages.csv` and `links.csv` into `directory`.

    Only the files with data are written (a `crawl` run has issues only);
    returns the written paths.
    """
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    tables = {
        "issues": (ISSUE_FIELDS, issue_rows(source)),
        "pages": (PAGE_FIELDS, page_rows(source)),
        "links": (LINK_FIELDS, link_rows(source)),
    }
    written = []
    for stem in CSV_FILES:
        fields, rows = tables[stem]
        if not rows:
            continue
        written.append(_write_csv_file(out / f"{stem}.csv", fields, rows))
        logger.info("CSV export written: %s (%d rows)", written[-1], len(rows))
    return written


# ------------------------------------------------------- exit-code check (CI)

def failing_issues(source: Optional[ExportSource], severity: Optional[str]) -> List[SeoIssue]:
    """
    Issues at least as severe as `severity`, in report order.

    "error" matches errors only, "warning" errors and warnings, "notice" every
    issue (the CLI `--fail-on` only offers error and warning). Returns an empty
    list when `severity` is falsy or unknown, or when the run has no site audit
    (nothing was crawled).
    """
    audit = site_audit_of(source)
    if audit is None or not severity or severity not in SEVERITY_ORDER:
        return []
    limit = SEVERITY_ORDER[severity]
    return [issue for issue in audit.issues if SEVERITY_ORDER[issue.severity] <= limit]
