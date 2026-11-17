"""
Reporting: per-page ranking analysis rendered as a self-contained HTML report
(semantic cluster map, ranking leaderboard, authority/hub plane, links), as
terminal tables, and as machine-readable JSON / CSV exports for CI and
dashboards (src/reporting/export.py).
"""

from src.reporting.analysis import PageMetrics, SiteAnalysis, analyze_benchmark, analyze_site
from src.reporting.export import (
    export_document, failing_issues, issue_rows, link_rows, page_rows, site_audit_of, to_json, write_csv, write_json,
)
from src.reporting.html import render_index, render_site_report, write_reports

__all__ = [
    "PageMetrics",
    "SiteAnalysis",
    "analyze_benchmark",
    "analyze_site",
    "export_document",
    "failing_issues",
    "issue_rows",
    "link_rows",
    "page_rows",
    "render_index",
    "render_site_report",
    "site_audit_of",
    "to_json",
    "write_csv",
    "write_json",
    "write_reports",
]
