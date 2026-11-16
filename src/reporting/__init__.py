"""
Visual reporting: per-page ranking analysis rendered as a self-contained HTML
report (semantic cluster map, ranking leaderboard, authority/hub plane, links)
and as terminal tables.
"""

from src.reporting.analysis import PageMetrics, SiteAnalysis, analyze_benchmark, analyze_site
from src.reporting.html import render_index, render_site_report, write_reports

__all__ = [
    "PageMetrics",
    "SiteAnalysis",
    "analyze_benchmark",
    "analyze_site",
    "render_index",
    "render_site_report",
    "write_reports",
]
