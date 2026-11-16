"""
Benchmark sites for SEO-Magus.

Every benchmark is an ordinary site: a list of crawled pages plus a site config
(config/sites/<key>.yaml) with thresholds and taxonomy, run through the same
LinkingOptimizer flow as any user site. Each benchmark documents where its
expected links come from:

  * reference - ground truth known by construction (exhaustive; see reference.py)
  * greenleaf-good / greenleaf-scrambled - real HTTP crawls of the mock sites in
    mock_sites/ (exhaustive: the good site needs no new link, the scrambled site
    must get exactly the good site's missing links; see mock_sites.py)
  * canivete, zazazine - links approved in their case-study reports (reports/)
  * mailchimp, stripe, shopify, github - "key links" in the README benchmark table

For non-exhaustive benchmarks only recall is meaningful: other approved links
are not necessarily wrong, they just were not documented.
"""

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

from src.config import SiteConfig, load_site_config
from src.connectors.gsc_connector import GSCQueryRow
from src.connectors.sitemap_crawler import ParsedPage
from src.engines.link_graph import LinkGraph
from src.workflows.linking_optimizer import REASON_CLASSIFIER_GATE, AuditReport, LinkingOptimizer

from src.benchmarks import mock_sites, reference
from src.connectors.sitemap_crawler import CrawlResult
from src.workflows.site_audit import SiteAuditReport, audit_site
from src.log import get_logger
from src.benchmarks.canivete import build_canivete_pages
from src.benchmarks.famous_sites import get_github_pages, get_mailchimp_pages, get_shopify_pages, get_stripe_pages
from src.benchmarks.zazazine import build_zazazine_pages

logger = get_logger(__name__)

SITES_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "sites"

Link = Tuple[str, str]


@dataclass(frozen=True)
class BenchmarkSite:
    key: str
    name: str
    build_pages: Optional[Callable[[], List[ParsedPage]]]
    expected_links: FrozenSet[Link]
    expectation_source: str
    exhaustive: bool = False  # True: any link outside expected_links is a false positive
    build_gsc_rows: Optional[Callable[[], List[GSCQueryRow]]] = None
    # Expected links the current flow does not produce -> the gate that refuses
    # them (a REASON_* constant of the optimizer). Tests assert this exactly, so a
    # fix or a regression both show up and this record must be updated.
    known_gaps: Dict[Link, str] = field(default_factory=dict)
    # Sites crawled over HTTP (mock sites): returns the crawl and the requested paths.
    build_crawl: Optional[Callable[[], "mock_sites.MockCrawl"]] = None
    expected_issues: Optional[FrozenSet[Tuple[str, str]]] = None   # (code, absolute URL) for the site audit
    config_name: Optional[str] = None                              # config/sites/<name>.yaml, default: key

    @property
    def config_path(self) -> Path:
        return SITES_CONFIG_DIR / f"{self.config_name or self.key}.yaml"

    def pages(self) -> List[ParsedPage]:
        return self.build_crawl().result.pages if self.build_crawl else self.build_pages()

    def load_config(self) -> SiteConfig:
        return load_site_config(self.config_path)


@dataclass
class BenchmarkRun:
    site: BenchmarkSite
    config: SiteConfig
    pages: List[ParsedPage]
    report: AuditReport
    link_graph: LinkGraph                     # after optimization
    baseline_graph: LinkGraph                 # crawl links only
    optimizer: LinkingOptimizer               # for explain_link()
    taxonomy_warnings: List[str] = field(default_factory=list)
    crawl: Optional[CrawlResult] = None       # crawled sites only
    crawl_requests: List[str] = field(default_factory=list)
    site_audit: Optional[SiteAuditReport] = None

    @property
    def approved_links(self) -> FrozenSet[Link]:
        return frozenset((r.source_url, r.target_url) for r in self.report.results)

    @property
    def found_links(self) -> FrozenSet[Link]:
        return self.approved_links & self.site.expected_links

    @property
    def missing_links(self) -> FrozenSet[Link]:
        return self.site.expected_links - self.approved_links

    @property
    def unexpected_links(self) -> FrozenSet[Link]:
        """Approved links outside the expectations (false positives only if exhaustive)."""
        return self.approved_links - self.site.expected_links

    @property
    def recall(self) -> float:
        expected = self.site.expected_links
        return len(self.found_links) / len(expected) if expected else 1.0

    @property
    def precision(self) -> Optional[float]:
        """Only defined for exhaustive benchmarks."""
        if not self.site.exhaustive:
            return None
        approved = self.approved_links
        return len(self.found_links) / len(approved) if approved else 1.0


def run_benchmark(site: BenchmarkSite, optimizer: Optional[LinkingOptimizer] = None) -> BenchmarkRun:
    """
    Run one benchmark site through the standard flow. By default the optimizer
    is configured by the site's own config file (config/sites/<key>.yaml).
    """
    config = site.load_config()
    optimizer = optimizer or LinkingOptimizer.from_config(config)
    crawl, requests, site_audit = None, [], None
    if site.build_crawl:
        mock_crawl = site.build_crawl()
        crawl, requests = mock_crawl.result, mock_crawl.requests
        site_audit = audit_site(crawl, config.thresholds.max_click_depth, config.thresholds.slow_page_ms)
        pages = crawl.pages
    else:
        pages = site.build_pages()
    logger.info("Benchmark %s: %d pages, expected links from %s", site.key, len(pages), site.expectation_source)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        report = optimizer.run_optimization(pages, site.build_gsc_rows() if site.build_gsc_rows else None)
    for warning in caught:  # re-emit, but keep taxonomy problems visible to callers
        warnings.warn_explicit(warning.message, warning.category, warning.filename, warning.lineno)
    run = BenchmarkRun(
        site=site,
        config=config,
        pages=pages,
        report=report,
        link_graph=optimizer.link_graph,
        baseline_graph=optimizer.baseline_graph,
        optimizer=optimizer,
        taxonomy_warnings=[str(w.message) for w in caught if w.category.__name__ == "TaxonomyWarning"],
        crawl=crawl,
        crawl_requests=requests,
        site_audit=site_audit,
    )
    logger.info(
        "Benchmark %s: %d/%d expected links found (recall %.0f%%%s), %d missing",
        site.key, len(run.found_links), len(site.expected_links), 100 * run.recall,
        "" if run.precision is None else f", precision {100 * run.precision:.0f}%", len(run.missing_links),
    )
    return run


def _links(base: str, *pairs: Tuple[str, str]) -> FrozenSet[Link]:
    return frozenset((base + source, base + target) for source, target in pairs)


_README = "README benchmark table (expected key links)"

BENCHMARKS: Dict[str, BenchmarkSite] = {
    site.key: site
    for site in [
        BenchmarkSite(
            key="reference",
            name="Ledgerly (ground-truth reference)",
            build_pages=reference.build_reference_pages,
            expected_links=reference.EXPECTED_LINKS,
            expectation_source="ground truth by construction (src/benchmarks/reference.py)",
            exhaustive=True,
            build_gsc_rows=reference.build_reference_gsc_rows,
        ),
        BenchmarkSite(
            key=mock_sites.GOOD_SITE,
            name="GreenLeaf (mock site, good SEO)",
            build_pages=None,
            build_crawl=lambda: mock_sites.crawl_mock_site(mock_sites.GOOD_SITE),
            config_name="greenleaf",
            expected_links=frozenset(),
            expectation_source="mock site ground truth: a well-linked site needs no new link (src/benchmarks/mock_sites.py)",
            exhaustive=True,
            expected_issues=frozenset(),
        ),
        BenchmarkSite(
            key=mock_sites.SCRAMBLED_SITE,
            name="GreenLeaf (mock site, scrambled SEO)",
            build_pages=None,
            build_crawl=lambda: mock_sites.crawl_mock_site(mock_sites.SCRAMBLED_SITE),
            config_name="greenleaf",
            expected_links=frozenset(
                (mock_sites.absolute(s), mock_sites.absolute(t)) for s, t in mock_sites.SCRAMBLED_EXPECTED_PROPOSALS
            ),
            expectation_source="mock site ground truth: the good site's links missing here (src/benchmarks/mock_sites.py)",
            exhaustive=True,
            expected_issues=frozenset(
                (code, mock_sites.absolute(path)) for code, path in mock_sites.EXPECTED_ISSUES[mock_sites.SCRAMBLED_SITE]
            ),
        ),
        BenchmarkSite(
            key="mailchimp",
            name="Mailchimp",
            build_pages=get_mailchimp_pages,
            expected_links=_links(
                "https://mailchimp.com",
                ("/resources/welcome-email-sequence-guide/", "/features/audience-segmentation/"),
            ),
            expectation_source=_README,
        ),
        BenchmarkSite(
            key="stripe",
            name="Stripe",
            build_pages=get_stripe_pages,
            expected_links=_links(
                "https://stripe.com",
                ("/resources/more/how-to-prevent-credit-card-fraud", "/checkout"),
            ),
            expectation_source=_README,
            # Correct refusal: no paragraph of the fraud article mentions Checkout, so the
            # link would have no contextual reason. The fixture text does not support
            # the README claim (the opposite direction, checkout -> fraud, is produced).
            known_gaps={
                ("https://stripe.com/resources/more/how-to-prevent-credit-card-fraud",
                 "https://stripe.com/checkout"): REASON_CLASSIFIER_GATE,
            },
        ),
        BenchmarkSite(
            key="shopify",
            name="Shopify",
            build_pages=get_shopify_pages,
            expected_links=_links(
                "https://www.shopify.com",
                ("/blog/what-is-dropshipping", "/pos"),
            ),
            expectation_source=_README,
            # Correct refusal: the dropshipping article never mentions POS or retail,
            # so there is no sentence a contextual link could live in.
            known_gaps={
                ("https://www.shopify.com/blog/what-is-dropshipping", "https://www.shopify.com/pos"): REASON_CLASSIFIER_GATE,
            },
        ),
        BenchmarkSite(
            key="github",
            name="GitHub",
            build_pages=get_github_pages,
            expected_links=_links(
                "https://github.com",
                ("/resources/articles/devops/what-is-ci-cd", "/resources/articles/devops/github-actions-tutorial"),
                ("/resources/articles/devops/what-is-ci-cd", "/enterprise"),
            ),
            expectation_source=_README,
        ),
        BenchmarkSite(
            key="canivete",
            name="Canivete.cc",
            build_pages=build_canivete_pages,
            # Report links 1-4 and 6; links 5 and 7 target pages outside the fixture.
            expected_links=_links(
                "https://canivete.cc",
                ("/guias/guia-rescisao-trabalhista-clt-2026/", "/financas/calculadora-seguro-desemprego/"),
                ("/guias/guia-rescisao-trabalhista-clt-2026/", "/negocios/gerador-carta-demissao/"),
                ("/financas/calculadora-rescisao-clt/", "/financas/calculadora-seguro-desemprego/"),
                ("/guias/clt-vs-pj-equivalencia-salarial/", "/negocios/gerador-contrato-prestacao-servicos/"),
                ("/financas/calculadora-aposentadoria-inss/", "/financas/simulador-emprestimo-consignado-inss/"),
            ),
            expectation_source="reports/canivete_cc_audit_report.md, section 3 (links 1-4, 6)",
        ),
        BenchmarkSite(
            key="zazazine",
            name="ZAZAZINE",
            build_pages=build_zazazine_pages,
            # Report links 1, 2, 4, 5; links 3 and 6 involve pages outside the fixture.
            expected_links=_links(
                "https://zazazine.verdindex.com/artigo/",
                ("cure-act-projeto-protege-usuarios-de-maconha-em-empregos-federais",
                 "dea-deixa-estados-no-escuro-sobre-reclassificacao-da-cannabis"),
                ("dea-deixa-estados-no-escuro-sobre-reclassificacao-da-cannabis",
                 "dc-circuit-rejeita-bloquear-reclassificacao-maconha"),
                ("custo-de-ia-cai-47-por-trimestre", "google-lanca-gemini-3-8"),
                ("custo-de-ia-cai-47-por-trimestre", "majors-stability-ai-universal-elevenlabs"),
            ),
            expectation_source="reports/zazazine_audit_report.md, section 3 (links 1, 2, 4, 5)",
        ),
    ]
}


def get_benchmark(key: str) -> BenchmarkSite:
    try:
        return BENCHMARKS[key]
    except KeyError:
        raise KeyError(f"Unknown benchmark '{key}'; available: {sorted(BENCHMARKS)}") from None
