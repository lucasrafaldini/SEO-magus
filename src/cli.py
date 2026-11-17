"""
SEO-Magus Command Line Interface.

Settings precedence for every command: explicit flag > --config file > built-in default.
Global options (before the sub-command):
  logging   --log-level / -v / -vv / --log-file (or SEO_MAGUS_LOG_LEVEL)
  output    --unicode (box drawing and glyphs; default plain ASCII), --no-color

`crawl` and `audit` also write machine-readable output (--json FILE, --csv DIR)
and can fail a CI job with --fail-on error|warning (exit status 1).
"""

import argparse
import sys
import threading
from collections import Counter
from pathlib import Path
from typing import List, Optional

from src.benchmarks import BENCHMARKS, get_benchmark, run_benchmark
from src.benchmarks.demo import sample_crawl
from src.benchmarks.mock_sites import MockSiteServer, available_sites
from src.config import SiteConfig, load_site_config
from src.connectors.gsc_connector import GSCConnector
from src.connectors.sitemap_crawler import CrawlResult, SitemapCrawler
from src.log import configure_logging, get_logger, run_context
from src.reporting import analyze_benchmark, analyze_site, write_reports
from src.reporting.export import ExportSource, failing_issues, site_audit_of, write_csv, write_json
from src.reporting.terminal import (
    TerminalStyle, configure_terminal, get_style, print_leaderboard, print_links, print_site_audit, print_verdict,
)
from src.workflows.linking_optimizer import LinkingOptimizer
from src.workflows.site_audit import ERROR, WARNING, audit_site

logger = get_logger(__name__)
RULE = "=" * 70
FAIL_ON_SEVERITIES = (ERROR, WARNING)     # --fail-on: "error" = errors only, "warning" = errors and warnings
FAILED_ISSUES_SHOWN = 5                   # issues listed under the quality gate message


def _banner(title: str) -> None:
    print(RULE)
    print(f"   {title}")
    print(RULE)


def _site_config(config_path: Optional[str]) -> SiteConfig:
    """Thresholds, taxonomy, link rules and classifier from the config file, or built-in defaults."""
    if config_path is None:
        logger.info("No --config given: using built-in defaults (no roles, no clusters, classifier auto)")
        return SiteConfig()
    site_config = load_site_config(config_path)
    taxonomy = site_config.taxonomy
    print(f"[+] Config loaded from {config_path}: {len(taxonomy.pillars)} pillars, "
          f"{len(taxonomy.money_pages)} money pages, {len(taxonomy.clusters)} clusters, "
          f"classifier '{site_config.classifier.provider}'.")
    return site_config


def _report_paths(paths: List[Path]) -> None:
    extra = f" (+{len(paths) - 1} site pages)" if len(paths) > 1 else ""
    print(f"\n[+] HTML report: {paths[0].resolve()}{extra}")


def _exports(source: ExportSource, json_path: Optional[str], csv_dir: Optional[str] = None) -> None:
    """Machine-readable exports of a run: one JSON document and/or the CSV tables."""
    if json_path:
        print(f"[+] JSON export: {write_json(source, json_path).resolve()}")
    if csv_dir:
        paths = write_csv(source, csv_dir)
        written = ", ".join(p.name for p in paths) if paths else "no rows to export"
        print(f"[+] CSV export: {Path(csv_dir).resolve()} ({written})")


def _fail_on_status(source: Optional[ExportSource], fail_on: Optional[str]) -> int:
    """Exit status of the CI check: 1 when issues at least as severe as --fail-on were found."""
    if not fail_on:
        return 0
    if site_audit_of(source) is None:
        print(f"[!] --fail-on {fail_on}: no site audit in this run (nothing was crawled).")
        return 0
    issues = failing_issues(source, fail_on)
    if not issues:
        print(f"[+] Quality gate passed: no issue of severity '{fail_on}' or above (--fail-on {fail_on}).")
        return 0
    counts = Counter(issue.severity for issue in issues)
    found = ", ".join(f"{counts[s]} {s}(s)" for s in FAIL_ON_SEVERITIES if counts[s])
    print(f"\n[!] Quality gate failed (--fail-on {fail_on}): {found}.")
    for issue in issues[:FAILED_ISSUES_SHOWN]:
        print(f"    [{issue.severity}] {issue.code}: {issue.url}")
    if len(issues) > FAILED_ISSUES_SHOWN:
        print(f"    ... and {len(issues) - FAILED_ISSUES_SHOWN} more")
    return 1


def optimizer_site_config(optimizer: LinkingOptimizer, base: Optional[SiteConfig] = None) -> SiteConfig:
    """The effective configuration of an optimizer (after CLI overrides)."""
    return SiteConfig(thresholds=optimizer.thresholds, taxonomy=optimizer.taxonomy, link_rules=optimizer.link_rules,
                      classifier=(base or SiteConfig()).classifier)


def _crawl(url: str, site_config: SiteConfig, crawl_overrides: Optional[dict], sitemap: Optional[str]) -> CrawlResult:
    config = site_config.crawler.with_overrides(**(crawl_overrides or {}))
    depth = "unlimited" if config.max_depth is None else config.max_depth
    print(f"\n[*] Crawling {url} (robots.txt, sitemaps, links; max {config.max_pages} pages, depth {depth}, "
          f"{config.concurrency} parallel requests)...")
    crawl = SitemapCrawler(url, config=config).crawl(sitemap_url=sitemap)
    print(f"[+] Crawled {len(crawl.pages)} pages in {crawl.duration_seconds}s "
          f"({len(crawl.statuses)} internal URLs requested, {len(crawl.broken_urls)} broken, "
          f"{len(crawl.redirects)} redirects, {len(crawl.robots_blocked)} blocked by robots.txt"
          + (f", {len(crawl.excluded)} excluded" if crawl.excluded else "")
          + (", stopped at max pages" if crawl.truncated else "") + ").")
    return crawl


def run_crawl(url: str, config_path: Optional[str] = None, crawl_overrides: Optional[dict] = None,
              sitemap: Optional[str] = None, save_crawl: Optional[str] = None, limit: int = 25,
              json_path: Optional[str] = None, csv_dir: Optional[str] = None):
    """Crawl + site audit only (no link classifier calls)."""
    _banner("SEO-MAGUS: CRAWL AND SITE AUDIT")
    site_config = _site_config(config_path)
    crawl = _crawl(url, site_config, crawl_overrides, sitemap)
    if save_crawl:
        print(f"[+] Crawl saved to {crawl.save(save_crawl)}")
    audit = audit_site(crawl, site_config.thresholds.max_click_depth, site_config.thresholds.slow_page_ms)
    print_site_audit(_AuditOnly(audit), limit=limit)
    if crawl.external_statuses:
        print(f"  External links checked: {len(crawl.external_statuses)} ({len(crawl.broken_external_urls)} broken)")
    _exports(audit, json_path, csv_dir)
    return crawl, audit


class _AuditOnly:
    """Minimal stand-in for SiteAnalysis when only the site audit is printed."""

    def __init__(self, site_audit):
        self.site_audit = site_audit


def run_audit(
    demo: bool = True,
    min_score: Optional[float] = None,
    min_conf: Optional[float] = None,
    config_path: Optional[str] = None,
    html_dir: Optional[str] = None,
    url: Optional[str] = None,
    sitemap: Optional[str] = None,
    max_pages: Optional[int] = None,
    top: int = 10,
    crawl_overrides: Optional[dict] = None,
    from_crawl: Optional[str] = None,
    save_crawl: Optional[str] = None,
    json_path: Optional[str] = None,
    csv_dir: Optional[str] = None,
):
    """
    Crawl (or load) a site, audit it, propose links and rank the pages.

    Returns the SiteAnalysis of the run, or the SiteAuditReport alone when no
    page could be crawled; both can be exported and checked with --fail-on.
    """
    _banner("SEO-MAGUS: SITE AUDIT AND INTERNAL LINKING")
    site_config = _site_config(config_path)
    crawl = site_audit = None
    name = url or "Demo audit"
    crawl_overrides = dict(crawl_overrides or {}, **({"max_pages": max_pages} if max_pages else {}))
    if url or from_crawl:
        if from_crawl:
            crawl = CrawlResult.load(from_crawl)
            url = name = crawl.start_url
            print(f"\n[+] Loaded saved crawl of {url}: {len(crawl.pages)} pages (no network access).")
        else:
            crawl = _crawl(url, site_config, crawl_overrides, sitemap)
            if save_crawl:
                print(f"[+] Crawl saved to {crawl.save(save_crawl)}")
        pages, gsc_data = crawl.pages, []
        site_audit = audit_site(crawl, site_config.thresholds.max_click_depth, site_config.thresholds.slow_page_ms)
        if not pages:
            print("[!] No HTML page could be crawled: check the URL.")
            _exports(site_audit, json_path, csv_dir)
            return site_audit
    elif demo:
        # A small recorded site: the same pages as SitemapCrawler.get_sample_site_pages() plus the
        # links, headings and sitemap a crawler records, so the demo also runs the site audit.
        crawl = sample_crawl()
        pages, gsc_data = crawl.pages, GSCConnector.get_sample_dataset()
        site_audit = audit_site(crawl, site_config.thresholds.max_click_depth, site_config.thresholds.slow_page_ms)
        print(f"\n[+] Demo dataset: {len(pages)} pages of a sample site (site audit included) and {len(gsc_data)} "
              "Search Console queries (use --url to crawl your site).")
    else:
        pages, gsc_data = [], []

    optimizer = LinkingOptimizer.from_config(site_config, min_score=min_score, min_confidence=min_conf)
    print(f"[*] Classifier: {optimizer.classifier.describe()}")
    print(f"[*] Gate: score >= {optimizer.min_score}, confidence >= {optimizer.min_confidence}")
    report = optimizer.run_optimization(pages, gsc_data)

    print(f"\n[+] Link optimization complete in {report.duration_seconds}s")
    print(f"[*] Classifier calls           : {report.candidate_pairs_checked}"
          + (f" ({report.classifier_fallbacks} answered by the fallback)" if report.classifier_fallbacks else ""))
    print(f"[*] Estimated cost (USD)       : ${report.estimated_cost_usd:.4f}")
    print(f"[*] Links proposed             : {report.links_approved}")
    print(f"[*] Page 2 pages boosted       : {len(report.page2_pages_boosted)}")

    analysis = analyze_site(
        "audit", name, pages, optimizer.baseline_graph, optimizer.link_graph, report,
        optimizer_site_config(optimizer, site_config), gsc_data,
    )
    analysis.site_audit = site_audit
    orphans = [p for p in analysis.pages if p.crawled and p.orphan_before]
    fixed = [p for p in orphans if not p.orphan_after]
    print(f"[*] Orphan pages               : {len(orphans)} ({len(fixed)} get inbound links from the proposals)\n")
    print_site_audit(analysis)
    print_links(analysis)
    print()
    print_leaderboard(analysis, limit=top)
    if html_dir:
        _report_paths(write_reports([analysis], html_dir))
    _exports(analysis, json_path, csv_dir)
    return analysis


def run_boost_page2(
    min_pos: Optional[float] = None,
    max_pos: Optional[float] = None,
    min_impressions: Optional[int] = None,
    config_path: Optional[str] = None,
):
    thresholds = _site_config(config_path).thresholds.with_overrides(
        page2_min_position=min_pos, page2_max_position=max_pos, min_impressions=min_impressions
    )
    _banner(f"SERP PAGE 2 OPPORTUNITIES (Positions {thresholds.page2_min_position} to "
            f"{thresholds.page2_max_position}, >= {thresholds.min_impressions} impressions)")
    gsc = GSCConnector()
    dataset = gsc.get_sample_dataset()
    opps = gsc.get_page2_opportunities(
        dataset,
        min_position=thresholds.page2_min_position,
        max_position=thresholds.page2_max_position,
        min_impressions=thresholds.min_impressions,
    )
    print(f"{'Query':<30} | {'Avg Pos':<8} | {'Impressions':<12} | {'Clicks'}")
    print("-" * 70)
    for o in opps:
        print(f"{o.query:<30} | {o.position:<8.1f} | {o.impressions:<12} | {o.clicks}")
    print(RULE)


def run_benchmark_suite(target: str = "all", html_dir: Optional[str] = None, top: int = 10):
    _banner("SEO-MAGUS BENCHMARK SUITE")
    style = get_style()
    selected = list(BENCHMARKS.values()) if target == "all" else [get_benchmark(target)]
    analyses = []
    for site in selected:
        how = "crawled over HTTP from mock_sites/" if site.build_crawl else "fixture pages"
        print(f"\n{style.sym('section')} {site.name} ({how}, config: config/sites/{site.config_path.name})")
        # Fresh optimizer per site, configured by that site's own config file.
        run = run_benchmark(site)
        report = run.report
        print(f"  Processed in {report.duration_seconds}s | {len(run.pages)} pages | links proposed: "
              f"{report.links_approved} | classifier calls: {report.candidate_pairs_checked} "
              f"| cost: ${report.estimated_cost_usd:.4f}")
        analysis = analyze_benchmark(run)
        print_site_audit(analysis, limit=8)
        print_verdict(analysis)
        print_leaderboard(analysis, limit=top)
        analyses.append(analysis)
    print("\n" + RULE)
    if html_dir:
        _report_paths(write_reports(analyses, html_dir))


def run_serve_mock(site: str, port: int):
    with MockSiteServer(site, port) as server:
        print(f"Serving mock site '{site}' at {server.base_url}/  (Ctrl+C to stop)")
        print(f"Audit it with: python -m src.cli audit --url {server.base_url}/ --config config/sites/greenleaf.yaml")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\nStopped.")


def _add_crawl_arguments(parser: argparse.ArgumentParser) -> None:
    """Crawler options (override the config's `crawler` section)."""
    group = parser.add_argument_group("crawler (overrides the config 'crawler' section)")
    group.add_argument("--sitemap", default=None, help="Sitemap URL (default: robots.txt declaration or /sitemap.xml)")
    group.add_argument("--max-pages", type=int, default=None, help="Maximum number of HTML pages (default 500)")
    group.add_argument("--max-depth", type=int, default=None, help="Maximum clicks from the start page")
    group.add_argument("--concurrency", type=int, default=None, help="Parallel requests (default 4)")
    group.add_argument("--delay", type=float, default=None, help="Seconds between requests (robots Crawl-delay wins if larger)")
    group.add_argument("--include", action="append", default=None, metavar="REGEX", help="Only crawl matching URL paths (repeatable)")
    group.add_argument("--exclude", action="append", default=None, metavar="REGEX", help="Skip matching URL paths (repeatable)")
    group.add_argument("--check-external", action="store_true", default=None, help="Also check external links for errors")
    group.add_argument("--ignore-robots", action="store_true", help="Ignore robots.txt (only for sites you own)")
    group.add_argument("--save-crawl", default=None, metavar="FILE", help="Save the crawl as JSON (re-audit with --from-crawl)")


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    """Machine-readable output and the CI exit-code check (crawl and audit)."""
    group = parser.add_argument_group("machine-readable output (CI)")
    group.add_argument("--json", default=None, metavar="FILE", dest="json_path",
                       help="Write the run as one JSON document (issues, page ranking, proposed links)")
    group.add_argument("--csv", default=None, metavar="DIR", dest="csv_dir",
                       help="Write issues.csv, pages.csv and links.csv to this directory")
    group.add_argument("--fail-on", choices=list(FAIL_ON_SEVERITIES), default=None,
                       help="Exit with status 1 when the audit finds issues of this severity or above")


def _crawl_overrides(args) -> dict:
    return {
        "max_pages": args.max_pages, "max_depth": args.max_depth, "concurrency": args.concurrency,
        "delay": args.delay, "include": tuple(args.include) if args.include else None,
        "exclude": tuple(args.exclude) if args.exclude else None, "check_external": args.check_external,
        "respect_robots": False if args.ignore_robots else None,
    }


def _log_level(args) -> Optional[str]:
    if args.log_level:
        return args.log_level
    return {0: None, 1: "INFO"}.get(args.verbose, "DEBUG")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description="SEO-Magus CLI")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING (default) or ERROR; env SEO_MAGUS_LOG_LEVEL")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="-v = INFO, -vv = DEBUG (every decision)")
    parser.add_argument("--log-file", default=None, help="Also write logs to this file")
    parser.add_argument("--unicode", action="store_true", default=None,
                        help="Use box-drawing characters and glyphs (default: plain ASCII; env SEO_MAGUS_UNICODE=1)")
    parser.add_argument("--no-color", action="store_true", help="Disable colours (also: NO_COLOR environment variable)")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")
    config_help = "YAML site config (thresholds, taxonomy, link_rules, classifier), e.g. config/config.example.yaml"
    html_help = "Write the visual HTML report (semantic map, ranking leaderboard, site health) to this directory"

    audit_parser = subparsers.add_parser("audit", help="Crawl a site (--url) or use the demo dataset, then audit and optimize links")
    audit_parser.add_argument("--url", default=None, help="Start URL of the site to crawl (e.g. https://example.com/)")
    audit_parser.add_argument("--from-crawl", default=None, metavar="FILE", help="Audit a crawl saved with --save-crawl")
    _add_crawl_arguments(audit_parser)
    audit_parser.add_argument("--demo", action="store_true", default=True, help="Use the demo dataset when --url is not given")
    audit_parser.add_argument("--min-score", type=float, default=None, help="Minimum classifier score (overrides config; default 7.0)")
    audit_parser.add_argument("--min-conf", type=float, default=None, help="Minimum classifier confidence (overrides config; default 0.80)")
    audit_parser.add_argument("--config", default=None, help=config_help)
    audit_parser.add_argument("--html", default=None, metavar="DIR", help=html_help)
    audit_parser.add_argument("--top", type=int, default=10, help="Pages shown in the terminal leaderboard")
    _add_output_arguments(audit_parser)

    boost_parser = subparsers.add_parser("boost-page2", help="Find Page 2 queries to boost")
    boost_parser.add_argument("--min-pos", type=float, default=None, help="Min SERP position (overrides config; default 11.0)")
    boost_parser.add_argument("--max-pos", type=float, default=None, help="Max SERP position (overrides config; default 20.0)")
    boost_parser.add_argument("--min-impressions", type=int, default=None, help="Min impressions (overrides config; default 50)")
    boost_parser.add_argument("--config", default=None, help=config_help)

    bench_parser = subparsers.add_parser("benchmark", help="Run benchmark sites (each uses its config/sites/*.yaml)")
    bench_parser.add_argument("--site", choices=["all", *BENCHMARKS], default="all")
    bench_parser.add_argument("--html", default=None, metavar="DIR", help=html_help)
    bench_parser.add_argument("--top", type=int, default=10, help="Pages shown in each terminal leaderboard")

    crawl_parser = subparsers.add_parser("crawl", help="Crawl a site and run the site audit (no link classifier calls)")
    crawl_parser.add_argument("--url", required=True, help="Start URL of the site to crawl")
    crawl_parser.add_argument("--config", default=None, help=config_help)
    crawl_parser.add_argument("--issues", type=int, default=25, help="Issues shown in the terminal")
    _add_crawl_arguments(crawl_parser)
    _add_output_arguments(crawl_parser)

    serve_parser = subparsers.add_parser("serve-mock", help="Serve a mock site from mock_sites/ on localhost")
    serve_parser.add_argument("site", choices=available_sites())
    serve_parser.add_argument("--port", type=int, default=8000)

    return parser


def main(argv: Optional[List[str]] = None):
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # never crash on a console that cannot encode page text
    configure_logging(_log_level(args), args.log_file)
    configure_terminal(TerminalStyle.detect(unicode=args.unicode, color=False if args.no_color else None))
    logger.info("Command: %s%s", args.command or "audit (default)", run_context())
    status = 0

    try:
        if args.command is None:
            run_audit()
        elif args.command == "audit":
            analysis = run_audit(min_score=args.min_score, min_conf=args.min_conf, config_path=args.config,
                                 html_dir=args.html, url=args.url, sitemap=args.sitemap, top=args.top,
                                 crawl_overrides=_crawl_overrides(args), from_crawl=args.from_crawl,
                                 save_crawl=args.save_crawl, json_path=args.json_path, csv_dir=args.csv_dir)
            status = _fail_on_status(analysis, args.fail_on)
        elif args.command == "crawl":
            _, audit = run_crawl(args.url, config_path=args.config, crawl_overrides=_crawl_overrides(args),
                                 sitemap=args.sitemap, save_crawl=args.save_crawl, limit=args.issues,
                                 json_path=args.json_path, csv_dir=args.csv_dir)
            status = _fail_on_status(audit, args.fail_on)
        elif args.command == "boost-page2":
            run_boost_page2(args.min_pos, args.max_pos, args.min_impressions, config_path=args.config)
        elif args.command == "benchmark":
            run_benchmark_suite(args.site, html_dir=args.html, top=args.top)
        elif args.command == "serve-mock":
            run_serve_mock(args.site, args.port)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        sys.exit(2)
    if status:
        sys.exit(status)


if __name__ == "__main__":
    main()
