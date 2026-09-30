"""
SEO-Magus Command Line Interface.
Supports both standard library argparse and rich/typer if available.
"""

import sys
import argparse
from src.connectors.sitemap_crawler import SitemapCrawler
from src.connectors.gsc_connector import GSCConnector
from src.workflows.linking_optimizer import LinkingOptimizer
from tests.fixtures.famous_sites_data import (
    get_mailchimp_pages,
    get_stripe_pages,
    get_shopify_pages,
    get_github_pages,
)


def run_audit(demo: bool = True, min_score: float = 7.0, min_conf: float = 0.80):
    print("=" * 70)
    print("   SEO-MAGUS: HIGH-SPEED SEO SUITE (TypeSafe Jev + Auxiliary AI)   ")
    print("=" * 70)

    pages = SitemapCrawler.get_sample_site_pages() if demo else []
    gsc_data = GSCConnector.get_sample_dataset() if demo else []

    print(f"\n[+] Ingested {len(pages)} pages and {len(gsc_data)} Search Console queries.")
    print("[*] Running parallel Jev System 1 evaluation cascade...")

    optimizer = LinkingOptimizer(min_jev_score=min_score, min_jev_confidence=min_conf)
    report = optimizer.run_optimization(pages, gsc_data)

    print(f"\n[✓] Audit Complete in {report.duration_seconds}s!")
    print(f"[*] Candidate Pairs Evaluated : {report.candidate_pairs_checked}")
    print(f"[*] Estimated Jev Cost (USD)   : ${report.estimated_cost_usd:.4f}")
    print(f"[*] Links Approved & Placed    : {report.links_approved}")
    print(f"[*] Pages Refused (No fit)     : {report.pages_refused}")

    print("\n" + "-" * 70)
    print(f"{'Source Page':<24} | {'Target Page':<24} | {'Anchor Text':<16}")
    print("-" * 70)
    for r in report.results:
        src = r.source_url.split("/")[-1]
        tgt = r.target_url.split("/")[-1]
        print(f"{src:<24} | {tgt:<24} | {r.anchor_text:<16}")
        print(f"  ↳ Proposed Sentence: {r.updated_sentence}")
        print(f"  ↳ Score: {r.jev_relevance_score}/10 (Conf: {int(r.jev_confidence * 100)}%) - {r.rationale}\n")

    if report.orphan_pages:
        print(f"[!] Warning: Orphan pages detected: {report.orphan_pages}")
    print("-" * 70)


def run_boost_page2(min_pos: float = 11.0, max_pos: float = 20.0):
    print("=" * 70)
    print("   SERP PAGE 2 OPPORTUNITIES (Positions 11.0 to 20.0)   ")
    print("=" * 70)

    gsc = GSCConnector()
    dataset = gsc.get_sample_dataset()
    opps = gsc.get_page2_opportunities(dataset, min_position=min_pos, max_position=max_pos)

    print(f"{'Query':<30} | {'Avg Pos':<8} | {'Impressions':<12} | {'Clicks'}")
    print("-" * 70)
    for o in opps:
        print(f"{o.query:<30} | {o.position:<8.1f} | {o.impressions:<12} | {o.clicks}")
    print("=" * 70)


def run_benchmark(target: str = "all"):
    print("=" * 70)
    print("   SEO-MAGUS FAMOUS SITES BENCHMARK SUITE   ")
    print("=" * 70)

    benchmarks = {
        "mailchimp": ("Mailchimp", get_mailchimp_pages()),
        "stripe": ("Stripe", get_stripe_pages()),
        "shopify": ("Shopify", get_shopify_pages()),
        "github": ("GitHub", get_github_pages()),
    }

    selected = benchmarks.items() if target == "all" else [(target, benchmarks[target])]

    optimizer = LinkingOptimizer(min_jev_score=7.0, min_jev_confidence=0.75)

    for key, (name, pages) in selected:
        print(f"\n▶ Running Benchmark on {name} ({len(pages)} pages)...")
        report = optimizer.run_optimization(pages)
        print(f"  ✓ Processed in {report.duration_seconds}s | Approved: {report.links_approved} | Cost: ${report.estimated_cost_usd:.4f}")
        for r in report.results[:2]:  # Show top 2 for brevity
            src = r.source_url.split("/")[-2] or r.source_url.split("/")[-1]
            tgt = r.target_url.split("/")[-2] or r.target_url.split("/")[-1]
            print(f"    ↳ [{r.anchor_text}]: {src} -> {tgt}")
            print(f"      \"{r.updated_sentence}\"")
    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="SEO-Magus CLI")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    audit_parser = subparsers.add_parser("audit", help="Run link optimization audit")
    audit_parser.add_argument("--demo", action="store_true", default=True, help="Run with demo dataset")
    audit_parser.add_argument("--min-score", type=float, default=7.0, help="Minimum Jev score threshold")
    audit_parser.add_argument("--min-conf", type=float, default=0.80, help="Minimum Jev confidence threshold")

    boost_parser = subparsers.add_parser("boost-page2", help="Find Page 2 queries to boost")
    boost_parser.add_argument("--min-pos", type=float, default=11.0, help="Min SERP position")
    boost_parser.add_argument("--max-pos", type=float, default=20.0, help="Max SERP position")

    bench_parser = subparsers.add_parser("benchmark", help="Run benchmarks on famous sites")
    bench_parser.add_argument("--site", choices=["all", "mailchimp", "stripe", "shopify", "github"], default="all")

    args = parser.parse_args()

    if args.command == "audit" or args.command is None:
        run_audit()
    elif args.command == "boost-page2":
        run_boost_page2(args.min_pos, args.max_pos)
    elif args.command == "benchmark":
        run_benchmark(args.site)


if __name__ == "__main__":
    main()
