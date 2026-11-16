"""
Benchmark tests.

* TestRankingKnownAnswer    - ranking engine vs a published PageRank result.
* TestReferenceGroundTruth  - the whole evaluation flow vs a site whose correct
                              output is known by construction (sanity check).
* TestBenchmarkInvariants   - rules every approved link must satisfy, on every site.
* TestBenchmarkExpectations - documented expected links per site, with known gaps
                              asserted exactly (a fix or a regression both fail).
"""

import unittest
import warnings
from unittest import mock

from src.benchmarks import BENCHMARKS, BenchmarkRun, get_benchmark, run_benchmark
from src.benchmarks import reference as ref
from src.connectors.gsc_connector import GSCConnector
from src.engines import link_graph as link_graph_module
from src.engines.link_graph import HAS_NETWORKX, LinkGraph
from src.engines.auxiliary_ai import MAX_ANCHOR_WORDS
from src.engines.taxonomy import ROLE_MONEY, ROLE_SUPPORT, ROLES
from src.engines.text import is_content_token, tokenize
from src.benchmarks import mock_sites
from src.workflows.linking_optimizer import (
    REASON_NO_ANCHOR,
    REASON_CLUSTER_BOUNDARY,
    REASON_EXISTING_LINK,
    REASON_CLASSIFIER_GATE,
    REASON_ROLE_RULE,
    LinkingOptimizer,
)

_RUNS = {}
def _run(key: str) -> BenchmarkRun:
    """Each benchmark is run once per test session (fresh optimizer from its site config)."""
    if key not in _RUNS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _RUNS[key] = run_benchmark(get_benchmark(key))
    return _RUNS[key]


def _optimizer(key: str) -> LinkingOptimizer:
    return _run(key).optimizer


class TestRankingKnownAnswer(unittest.TestCase):
    """Wikipedia's PageRank illustration: published scores for an 11-node graph."""

    def _graph(self) -> LinkGraph:
        graph = LinkGraph()
        for node in ref.WIKIPEDIA_PAGERANK_EXAMPLE:
            graph.add_page(node)
        for source, targets in ref.WIKIPEDIA_PAGERANK_EXAMPLE.items():
            for target in targets:
                graph.add_link(source, target)
        return graph

    def test_published_pagerank_reproduced_on_every_backend(self):
        graph = self._graph()
        backends = [("pure-python", True)] + ([("networkx", False)] if HAS_NETWORKX else [])
        for label, force_fallback in backends:
            with self.subTest(backend=label), mock.patch.object(
                link_graph_module, "HAS_NETWORKX", HAS_NETWORKX and not force_fallback
            ):
                pagerank = graph.compute_pagerank(tol=1e-12, max_iter=1000)
                percent = {node: round(100 * score, 1) for node, score in pagerank.items()}
                self.assertEqual(percent, ref.WIKIPEDIA_PAGERANK_PERCENT)

    def test_published_ordering(self):
        # The illustration's point: C outranks E despite fewer inbound links,
        # because its one link comes from the most important page (B).
        pagerank = self._graph().compute_pagerank()
        self.assertGreater(pagerank["C"], pagerank["E"])
        self.assertGreater(len(self._graph().in_edges["E"]), len(self._graph().in_edges["C"]))


class TestReferenceGroundTruth(unittest.TestCase):
    """The full evaluation flow against a site whose correct output is known."""

    FORBIDDEN_REASON_CODES = {
        "cluster boundary": REASON_CLUSTER_BOUNDARY,
        "cluster affinity is one-way": REASON_CLUSTER_BOUNDARY,
        "role rule": REASON_ROLE_RULE,
        "existing link": REASON_EXISTING_LINK,
        "Jev thresholds": REASON_CLASSIFIER_GATE,
    }

    def setUp(self):
        self.run = _run("reference")

    def test_links_match_ground_truth_exactly(self):
        self.assertEqual(self.run.approved_links, ref.EXPECTED_LINKS)
        self.assertEqual((self.run.recall, self.run.precision), (1.0, 1.0))

    def test_each_trap_is_blocked_by_its_designated_rule(self):
        optimizer = _optimizer("reference")
        for (source, target), designed in ref.FORBIDDEN_LINKS.items():
            expected_reason = self.FORBIDDEN_REASON_CODES[designed.split(":")[0]]
            with self.subTest(link=f"{source} -> {target}"):
                self.assertNotIn((source, target), self.run.approved_links)
                self.assertEqual(optimizer.explain_link(source, target).reason, expected_reason)

    def test_search_console_steering(self):
        # Links into page 2 pages are flagged with the query they boost and come first.
        results = self.run.report.results
        flagged = {(r.source_url, r.target_url): r.page2_query for r in results if r.page2_query}
        self.assertEqual(flagged, ref.EXPECTED_PAGE2_LINKS)
        leading = results[: len(flagged)]
        self.assertTrue(all(r.page2_query for r in leading))
        self.assertEqual([r.page2_impressions for r in leading], sorted((r.page2_impressions for r in leading), reverse=True))
        self.assertEqual(self.run.report.page2_pages_boosted, {t for _, t in ref.EXPECTED_PAGE2_LINKS})

    def test_anchors_match_ground_truth_except_known_deviations(self):
        anchors = {(r.source_url, r.target_url): r.anchor_text.lower() for r in self.run.report.results}
        deviations = {link for link, expected in ref.EXPECTED_ANCHORS.items() if anchors.get(link) != expected}
        self.assertEqual(
            deviations, set(ref.KNOWN_ANCHOR_DEVIATIONS),
            "Anchor behaviour changed: update KNOWN_ANCHOR_DEVIATIONS in src/benchmarks/reference.py",
        )

    def test_graph_outcomes(self):
        self.assertEqual(set(self.run.report.orphan_pages), ref.EXPECTED_ORPHANS)
        self.assertEqual(self.run.link_graph.compute_pillar_depths(), ref.EXPECTED_PILLAR_DEPTHS)
        self.assertEqual(self.run.report.pages_refused, len(ref.EXPECTED_ORPHANS))

    def test_page2_opportunities_use_site_thresholds(self):
        thresholds = self.run.config.thresholds
        opportunities = GSCConnector().get_page2_opportunities(
            ref.build_reference_gsc_rows(),
            min_position=thresholds.page2_min_position,
            max_position=thresholds.page2_max_position,
            min_impressions=thresholds.min_impressions,
        )
        self.assertEqual(tuple(row.query for row in opportunities), ref.EXPECTED_PAGE2_QUERIES)


class TestBenchmarkInvariants(unittest.TestCase):
    """Rules of the flow that must hold for every approved link on every benchmark site."""

    def _each_site(self):
        return [(key, _run(key)) for key in BENCHMARKS]

    def test_site_configs_match_their_pages(self):
        for key, run in self._each_site():
            with self.subTest(site=key):
                self.assertEqual(run.taxonomy_warnings, [], f"config/sites/{key}.yaml has stale entries")
                self.assertTrue({m["role"] for m in run.link_graph.page_metadata.values()} <= set(ROLES))

    def test_links_are_new_unique_and_between_crawled_pages(self):
        for key, run in self._each_site():
            with self.subTest(site=key):
                urls = {page.url for page in run.pages}
                existing = {(page.url, target) for page in run.pages for target in page.existing_internal_links}
                pairs = [(r.source_url, r.target_url) for r in run.report.results]
                self.assertEqual(len(pairs), len(set(pairs)), "duplicate approvals")
                for source, target in pairs:
                    self.assertIn(source, urls)
                    self.assertIn(target, urls)
                    self.assertNotEqual(source, target)
                    self.assertNotIn((source, target), existing)

    def test_links_respect_taxonomy_and_link_rules(self):
        for key, run in self._each_site():
            with self.subTest(site=key):
                meta, taxonomy = run.link_graph.page_metadata, run.config.taxonomy
                policy = run.config.link_rules.money_to_support
                for r in run.report.results:
                    source_meta, target_meta = meta[r.source_url], meta[r.target_url]
                    self.assertIn(target_meta["cluster"], taxonomy.allowed_target_clusters(source_meta["cluster"]))
                    self.assertEqual(r.cluster, source_meta["cluster"])
                    if source_meta["role"] == ROLE_MONEY and target_meta["role"] == ROLE_SUPPORT:
                        self.assertNotEqual(policy, "forbid")
                        if policy == "same_cluster":
                            self.assertEqual(source_meta["cluster"], target_meta["cluster"])

    def test_links_pass_the_site_thresholds(self):
        for key, run in self._each_site():
            with self.subTest(site=key):
                thresholds = run.config.thresholds
                for r in run.report.results:
                    self.assertGreaterEqual(r.relevance_score, thresholds.min_score)
                    self.assertGreaterEqual(r.confidence, thresholds.min_confidence)

    def test_anchors_are_descriptive(self):
        for key, run in self._each_site():
            with self.subTest(site=key):
                for r in run.report.results:
                    words = tokenize(r.anchor_text)
                    self.assertTrue(is_content_token(words[0]) and is_content_token(words[-1]), r.anchor_text)
                    self.assertLessEqual(len(words), MAX_ANCHOR_WORDS, r.anchor_text)
                    self.assertGreaterEqual(
                        sum(1 for w in set(words) if is_content_token(w)),
                        run.config.thresholds.anchor_min_words, r.anchor_text,
                    )

    def test_rewrites_only_wrap_the_anchor(self):
        for key, run in self._each_site():
            with self.subTest(site=key):
                paragraphs = {page.url: page.paragraphs for page in run.pages}
                for r in run.report.results:
                    self.assertTrue(any(r.original_sentence in p for p in paragraphs[r.source_url]))
                    wrapped = f"[{r.anchor_text}]({r.target_url})"
                    self.assertEqual(r.updated_sentence.count(wrapped), 1)
                    self.assertEqual(r.updated_sentence.replace(wrapped, r.anchor_text), r.original_sentence)

    def test_graph_reflects_the_run(self):
        for key, run in self._each_site():
            with self.subTest(site=key):
                graph = run.link_graph
                for source, target in run.approved_links:
                    self.assertTrue(graph.has_link(source, target))
                    self.assertFalse(run.baseline_graph.has_link(source, target))
                self.assertEqual(set(run.report.orphan_pages), {n for n in graph.nodes if not graph.in_edges[n]})
                self.assertAlmostEqual(sum(graph.compute_pagerank().values()), 1.0, places=6)
                self.assertAlmostEqual(sum(graph.compute_cheirank().values()), 1.0, places=6)

    def test_runs_are_deterministic(self):
        for key in ("reference", "canivete"):
            with self.subTest(site=key), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                again = run_benchmark(get_benchmark(key))
                first = [(r.source_url, r.target_url, r.updated_sentence) for r in _run(key).report.results]
                self.assertEqual([(r.source_url, r.target_url, r.updated_sentence) for r in again.report.results], first)


class TestBenchmarkExpectations(unittest.TestCase):
    """Documented expected links per site; known gaps must match exactly."""

    def test_registry_is_well_formed(self):
        for key, site in BENCHMARKS.items():
            with self.subTest(site=key):
                self.assertTrue(site.config_path.is_file())
                urls = {page.url for page in site.pages()}
                for source, target in site.expected_links:
                    self.assertIn(source, urls)
                    self.assertIn(target, urls)
                self.assertTrue(set(site.known_gaps) <= site.expected_links)
                self.assertTrue(site.expectation_source)
        self.assertEqual([k for k, s in BENCHMARKS.items() if s.exhaustive],
                         ["reference", "greenleaf-good", "greenleaf-scrambled"])

    def test_missing_links_are_exactly_the_known_gaps(self):
        for key, site in BENCHMARKS.items():
            with self.subTest(site=key):
                run, optimizer = _run(key), _optimizer(key)
                actual = {link: optimizer.explain_link(*link).reason for link in run.missing_links}
                self.assertEqual(
                    actual, site.known_gaps,
                    f"{key}: expected-link results changed; update known_gaps in src/benchmarks/__init__.py",
                )

    def test_exhaustive_benchmarks_have_no_unexpected_links(self):
        for key, site in BENCHMARKS.items():
            if site.exhaustive:
                with self.subTest(site=key):
                    run = _run(key)
                    self.assertEqual(run.approved_links, site.expected_links - set(site.known_gaps))
                    self.assertEqual(run.precision, 1.0)

    def test_crawled_sites_audit_matches_expected_issues(self):
        for key, site in BENCHMARKS.items():
            if site.build_crawl:
                with self.subTest(site=key):
                    run = _run(key)
                    self.assertIsNotNone(run.site_audit)
                    self.assertEqual(run.site_audit.issue_keys(), set(site.expected_issues))

    def test_scrambled_site_proposals_fix_its_structure(self):
        # Applying the proposals gives the orphan page inbound links and makes
        # the buried vegetable pillar reachable in one click from the home page.
        run = _run(mock_sites.SCRAMBLED_SITE)
        hot, vegetables = mock_sites.absolute(mock_sites.HOT), mock_sites.absolute(mock_sites.VEGETABLES)
        self.assertFalse(run.baseline_graph.in_edges[hot])
        self.assertGreaterEqual(len(run.link_graph.in_edges[hot]), 3)
        self.assertIn(mock_sites.absolute(mock_sites.HOME), run.link_graph.in_edges[vegetables])

    def test_good_site_gets_no_link_nested_in_an_existing_one(self):
        # "raised bed" (-> raised-bed-kit) sits inside the existing "raised bed soil"
        # anchor on two pages: placing it would nest a link inside a link.
        run = _run(mock_sites.GOOD_SITE)
        kit = mock_sites.absolute(mock_sites.KIT)
        for source in (mock_sites.COMPOSTING, mock_sites.TOMATO):
            with self.subTest(source=source):
                decision = run.optimizer.explain_link(mock_sites.absolute(source), kit)
                self.assertEqual(decision.reason, REASON_NO_ANCHOR)

    def test_canivete_is_an_ordinary_benchmark_site(self):
        # Canivete's clusters come from its own config; another site gets none of them.
        canivete_clusters = {name for name, _ in _run("canivete").config.taxonomy.clusters}
        self.assertEqual(canivete_clusters, {"trabalhista", "juridico_rh", "credito_previdencia", "dev_tech"})
        for key in BENCHMARKS:
            if key != "canivete":
                with self.subTest(site=key):
                    clusters = {m["cluster"] for m in _run(key).link_graph.page_metadata.values()}
                    self.assertFalse(clusters & canivete_clusters)

    def test_zazazine_clusters_block_cross_topic_links(self):
        run = _run("zazazine")
        meta = run.link_graph.page_metadata
        self.assertTrue(run.report.results)
        for r in run.report.results:
            self.assertEqual(meta[r.source_url]["cluster"], meta[r.target_url]["cluster"])


if __name__ == "__main__":
    unittest.main()
