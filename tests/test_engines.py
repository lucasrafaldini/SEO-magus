"""
Unit Tests for SEO-Magus Core Engines.
"""

import inspect
import random
import unittest
import warnings
from unittest import mock

from src.engines import link_graph as link_graph_module
from src.engines.link_graph import (
    HAS_NETWORKX,
    ConvergenceWarning,
    LinkGraph,
    NoPillarsWarning,
    TaxonomyWarning,
)
from src.engines.taxonomy import DEFAULT_CLUSTER, ROLE_MONEY, ROLE_PILLAR, ROLE_SUPPORT, SiteTaxonomy
from src.engines.jev_client import JevClient, JevQuestion, JevEvaluationRequest
from src.engines.auxiliary_ai import MAX_ANCHOR_WORDS, AuxiliaryAIEngine
from src.engines.text import STOPWORDS, content_tokens, matched_topic_tokens, tokenize, tokens_match
from src.config import LinkRules
from src.connectors.gsc_connector import GSCConnector, GSCQueryRow

# Tight tolerance for tests that compare against closed-form solutions.
EXACT = {"tol": 1e-12, "max_iter": 1000}


def _random_graph(seed: int, n_pages: int = 30, n_links: int = 90, n_pillars: int = 0) -> LinkGraph:
    """Deterministic pseudo-random site graph (includes orphans and dangling pages)."""
    rng = random.Random(seed)
    graph = LinkGraph()
    for i in range(n_pages):
        graph.add_page(f"https://example.com/p{i}", role=ROLE_PILLAR if i < n_pillars else ROLE_SUPPORT)
    for _ in range(n_links):
        graph.add_link(f"https://example.com/p{rng.randrange(n_pages)}", f"https://example.com/p{rng.randrange(n_pages)}")
    return graph


def _run_both_backends(compute):
    """[(label, result)] for the networkx path (if installed) and the pure-Python fallback."""
    results = []
    if HAS_NETWORKX:
        results.append(("networkx", compute()))
    with mock.patch.object(link_graph_module, "HAS_NETWORKX", False):
        results.append(("pure-python", compute()))
    return results


class TestLinkGraph(unittest.TestCase):
    def setUp(self):
        self.graph = LinkGraph()

    def test_add_pages_and_links(self):
        self.graph.add_page("https://example.com/pillar", role="pillar")
        self.graph.add_page("https://example.com/support", role="support")
        self.graph.add_link("https://example.com/support", "https://example.com/pillar")

        self.assertTrue(self.graph.has_link("https://example.com/support", "https://example.com/pillar"))
        self.assertFalse(self.graph.has_link("https://example.com/pillar", "https://example.com/support"))

    def test_orphan_page_detection(self):
        self.graph.add_page("https://example.com/a")
        self.graph.add_page("https://example.com/orphan")
        self.graph.add_link("https://example.com/b", "https://example.com/a")

        orphans = self.graph.find_orphan_pages()
        self.assertIn("https://example.com/orphan", orphans)

    def test_pagerank_computation(self):
        self.graph.add_page("https://example.com/a")
        self.graph.add_page("https://example.com/b")
        self.graph.add_page("https://example.com/c")
        self.graph.add_link("https://example.com/a", "https://example.com/b")
        self.graph.add_link("https://example.com/c", "https://example.com/b")

        pr = self.graph.compute_pagerank()
        self.assertGreater(pr["https://example.com/b"], pr["https://example.com/a"])

    def test_add_link_preserves_existing_page_metadata(self):
        # Regression: add_link() used to re-run add_page() with defaults,
        # silently demoting pillars/money pages to "support".
        self.graph.add_page("https://example.com/pillar", role="pillar", topic_cluster="email")
        self.graph.add_page("https://example.com/money", role="money", topic_cluster="email")
        self.graph.add_link("https://example.com/pillar", "https://example.com/money")

        self.assertEqual(self.graph.page_metadata["https://example.com/pillar"], {"role": "pillar", "cluster": "email"})
        self.assertEqual(self.graph.page_metadata["https://example.com/money"], {"role": "money", "cluster": "email"})
        if HAS_NETWORKX:
            self.assertEqual(self.graph.graph.nodes["https://example.com/pillar"]["role"], "pillar")

    def test_pagerank_fallback_matches_networkx(self):
        if not HAS_NETWORKX:
            self.skipTest("networkx not installed")
        graph = _random_graph(seed=7)
        results = dict(_run_both_backends(lambda: graph.compute_pagerank(**EXACT)))
        for url in graph.nodes:
            self.assertAlmostEqual(results["networkx"][url], results["pure-python"][url], places=9)

    def test_networkx_backend_is_really_used(self):
        # networkx.pagerank needs scipy; if it is missing, ranking silently falls
        # back to pure Python. Fail loudly instead of hiding a broken install.
        if not HAS_NETWORKX:
            self.skipTest("networkx not installed")
        graph = _random_graph(seed=8)
        with mock.patch.object(LinkGraph, "_power_iteration", side_effect=AssertionError("fell back to pure Python")):
            self.assertEqual(set(graph.compute_pagerank()), graph.nodes)
            self.assertEqual(set(graph.compute_cheirank()), graph.nodes)

    def test_taxonomy_validation(self):
        self.graph.add_page("https://example.com/support", role="support")
        self.graph.add_page("https://example.com/money", role="money")

        valid, _ = self.graph.validate_link_rules("https://example.com/support", "https://example.com/money")
        self.assertTrue(valid)

        invalid, reason = self.graph.validate_link_rules("https://example.com/money", "https://example.com/support")
        self.assertFalse(invalid)
        self.assertIn("Commercial money pages", reason)


class TestRankingContract(unittest.TestCase):
    """compute_pagerank, compute_cheirank and compute_weighted_pagerank share one parameter contract."""

    def setUp(self):
        self.graph = _random_graph(seed=11, n_pillars=2)
        self.methods = {
            "pagerank": self.graph.compute_pagerank,
            "cheirank": self.graph.compute_cheirank,
            "weighted_pagerank": self.graph.compute_weighted_pagerank,
        }

    def test_shared_parameter_defaults(self):
        expected = {"alpha": 0.85, "max_iter": 100, "tol": 1e-6}
        for name, method in self.methods.items():
            params = inspect.signature(method).parameters
            with self.subTest(method=name):
                self.assertEqual({k: params[k].default for k in expected}, expected)

    def test_invalid_parameters_rejected(self):
        bad_values = [
            {"alpha": -0.1}, {"alpha": 1.5},
            {"max_iter": 0}, {"max_iter": 2.5}, {"max_iter": True},
            {"tol": 0.0}, {"tol": -1e-6},
        ]
        for name, method in self.methods.items():
            for kwargs in bad_values:
                with self.subTest(method=name, **kwargs):
                    with self.assertRaises(ValueError):
                        method(**kwargs)

    def test_empty_graph_returns_empty_dict(self):
        empty = LinkGraph()
        for name in self.methods:
            with self.subTest(method=name):
                self.assertEqual(getattr(empty, f"compute_{name}")(), {})

    def test_max_iter_is_honoured_on_every_backend(self):
        # One power-iteration step from the uniform start, computed by hand.
        # The networkx backend used to ignore max_iter entirely.
        n, alpha = len(self.graph.nodes), 0.85
        dangling = sum(1.0 / n for u in self.graph.nodes if not self.graph.edges[u])
        expected = {
            v: (1 - alpha) / n + alpha * dangling / n
            + sum(alpha * (1.0 / n) / len(self.graph.edges[u]) for u in self.graph.in_edges[v])
            for v in self.graph.nodes
        }
        for label, (result, caught) in _run_both_backends(lambda: self._collect_warnings(
            lambda: self.graph.compute_pagerank(max_iter=1)
        )):
            with self.subTest(backend=label):
                self.assertTrue(any(issubclass(w.category, ConvergenceWarning) for w in caught))
                for v in self.graph.nodes:
                    self.assertAlmostEqual(result[v], expected[v], places=12)

    def test_non_convergence_warns_for_every_method(self):
        for name, method in self.methods.items():
            with self.subTest(method=name):
                with self.assertWarns(ConvergenceWarning):
                    result = method(max_iter=2)
                self.assertAlmostEqual(sum(result.values()), 1.0, places=9)

    def test_tol_controls_precision_on_every_backend(self):
        for label, (loose, strict, reference) in _run_both_backends(lambda: (
            self.graph.compute_pagerank(tol=1e-3),
            self.graph.compute_pagerank(tol=1e-9),
            self.graph.compute_pagerank(**EXACT),
        )):
            with self.subTest(backend=label):
                loose_err = max(abs(loose[u] - reference[u]) for u in reference)
                strict_err = max(abs(strict[u] - reference[u]) for u in reference)
                self.assertLess(strict_err, 1e-8)
                self.assertLess(strict_err, loose_err)

    def test_converged_runs_do_not_warn(self):
        for name, method in self.methods.items():
            with self.subTest(method=name):
                caught = self._collect_warnings(method)[1]
                self.assertEqual([w for w in caught if issubclass(w.category, ConvergenceWarning)], [])

    @staticmethod
    def _collect_warnings(compute):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = compute()
        return result, caught


class TestCheiRank(unittest.TestCase):
    HUB = "https://example.com/hub"
    LEAVES = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]

    def setUp(self):
        self.graph = LinkGraph()

    def _build_star(self):
        for leaf in self.LEAVES:
            self.graph.add_link(self.HUB, leaf)

    def test_star_closed_form(self):
        # Reversed star: every leaf links to the hub, hub is dangling.
        # Solving the CheiRank equations gives leaf = 1 / (4 + 3*alpha).
        self._build_star()
        for alpha in (0.5, 0.85):
            leaf = 1.0 / (4.0 + 3.0 * alpha)
            for label, cr in _run_both_backends(lambda: self.graph.compute_cheirank(alpha=alpha, **EXACT)):
                with self.subTest(backend=label, alpha=alpha):
                    for url in self.LEAVES:
                        self.assertAlmostEqual(cr[url], leaf, places=10)
                    self.assertAlmostEqual(cr[self.HUB], 1.0 - 3.0 * leaf, places=10)

    def test_hub_vs_authority(self):
        # The hub links out but receives nothing: lowest PageRank, highest CheiRank.
        self._build_star()
        pr = self.graph.compute_pagerank()
        cr = self.graph.compute_cheirank()
        for leaf in self.LEAVES:
            self.assertLess(pr[self.HUB], pr[leaf])
            self.assertGreater(cr[self.HUB], cr[leaf])

    def test_equals_pagerank_of_reversed_graph(self):
        graph = _random_graph(seed=1)
        reversed_graph = LinkGraph()
        for url in graph.nodes:
            reversed_graph.add_page(url)
        for src, targets in graph.edges.items():
            for tgt in targets:
                reversed_graph.add_link(tgt, src)

        for label, (cr, pr_rev) in _run_both_backends(
            lambda: (graph.compute_cheirank(), reversed_graph.compute_pagerank())
        ):
            with self.subTest(backend=label):
                self.assertEqual(set(cr), graph.nodes)
                for url in graph.nodes:
                    self.assertAlmostEqual(cr[url], pr_rev[url], places=9)

    def test_backends_agree_and_sum_to_one(self):
        graph = _random_graph(seed=2)
        results = dict(_run_both_backends(lambda: graph.compute_cheirank(**EXACT)))
        for label, cr in results.items():
            with self.subTest(backend=label):
                self.assertAlmostEqual(sum(cr.values()), 1.0, places=9)
                self.assertTrue(all(v > 0 for v in cr.values()))
        if "networkx" in results:
            for url in graph.nodes:
                self.assertAlmostEqual(results["networkx"][url], results["pure-python"][url], places=9)

    def test_does_not_mutate_graph(self):
        self._build_star()
        pr_before = self.graph.compute_pagerank()
        self.graph.compute_cheirank()
        self.assertTrue(self.graph.has_link(self.HUB, self.LEAVES[0]))
        self.assertFalse(self.graph.has_link(self.LEAVES[0], self.HUB))
        if HAS_NETWORKX:
            self.assertTrue(self.graph.graph.has_edge(self.HUB, self.LEAVES[0]))
            self.assertFalse(self.graph.graph.has_edge(self.LEAVES[0], self.HUB))
        self.assertEqual(self.graph.compute_pagerank(), pr_before)


class TestWeightedPageRank(unittest.TestCase):
    PILLAR = "https://example.com/guides/pillar"

    def setUp(self):
        self.graph = LinkGraph()
        self.graph.add_page(self.PILLAR, role=ROLE_PILLAR)

    def test_weighted_pagerank_rejects_invalid_depth_decay(self):
        for bad in (-0.1, 1.5):
            with self.assertRaises(ValueError):
                self.graph.compute_weighted_pagerank(depth_decay=bad)

    def test_weighted_pagerank_no_pillars_warns_and_returns_standard_pagerank(self):
        graph = _random_graph(seed=6)
        with self.assertWarnsRegex(NoPillarsWarning, "taxonomy.pillars"):
            wpr = graph.compute_weighted_pagerank(depth_decay=0.3, alpha=0.7)
        self.assertEqual(wpr, graph.compute_pagerank(alpha=0.7))

    def test_weighted_pagerank_pillar_click_depths(self):
        second_pillar = "https://example.com/guides/other"
        self.graph.add_page(second_pillar, role=ROLE_PILLAR)
        self.graph.add_link(self.PILLAR, "https://example.com/a")
        self.graph.add_link("https://example.com/a", "https://example.com/b")
        self.graph.add_link("https://example.com/b", "https://example.com/c")
        self.graph.add_link(second_pillar, "https://example.com/c")  # shortcut: nearest pillar wins
        self.graph.add_link("https://example.com/unreached", self.PILLAR)  # links in, never reached

        depths = self.graph.compute_pillar_depths()
        self.assertEqual(depths, {
            self.PILLAR: 0,
            second_pillar: 0,
            "https://example.com/a": 1,
            "https://example.com/b": 2,
            "https://example.com/c": 1,
        })

    def test_weighted_pagerank_two_page_cycle_closed_form(self):
        # P <-> S with d(S) = 1. Solving the defining equations gives
        # x_S = (1 + alpha) / (2 + alpha + alpha * delta).
        support = "https://example.com/support"
        self.graph.add_link(self.PILLAR, support)
        self.graph.add_link(support, self.PILLAR)
        alpha = 0.85
        for delta in (0.0, 0.5, 0.85, 1.0):
            with self.subTest(depth_decay=delta):
                wpr = self.graph.compute_weighted_pagerank(depth_decay=delta, alpha=alpha, **EXACT)
                expected_support = (1 + alpha) / (2 + alpha + alpha * delta)
                self.assertAlmostEqual(wpr[support], expected_support, places=10)
                self.assertAlmostEqual(wpr[self.PILLAR], 1 - expected_support, places=10)

    def test_weighted_pagerank_unreachable_support_closed_form(self):
        # Playbook topology: support S -> pillar P, pillar never links back.
        # S is unreachable, so d(S) = D + 1 = 1 (D = 0, only the pillar is reached).
        # P is dangling. Solving: x_P = (1 + alpha*delta) / (2 + alpha*delta).
        support = "https://example.com/support"
        self.graph.add_link(support, self.PILLAR)
        alpha = 0.85
        for delta in (0.0, 0.5, 0.85, 1.0):
            with self.subTest(depth_decay=delta):
                wpr = self.graph.compute_weighted_pagerank(depth_decay=delta, alpha=alpha, **EXACT)
                ad = alpha * delta
                self.assertAlmostEqual(wpr[self.PILLAR], (1 + ad) / (2 + ad), places=10)
                self.assertAlmostEqual(wpr[support], 1 / (2 + ad), places=10)

    def test_weighted_pagerank_no_decay_equals_standard_pagerank(self):
        graph = _random_graph(seed=3, n_pillars=2)
        wpr = graph.compute_weighted_pagerank(depth_decay=1.0, **EXACT)
        pr = graph.compute_pagerank(**EXACT)
        for url in graph.nodes:
            self.assertAlmostEqual(wpr[url], pr[url], places=9)

    def test_weighted_pagerank_satisfies_defining_equation(self):
        # Independent check: plug the result back into the definition,
        # including the D + 1 depth for pages no pillar reaches.
        graph = _random_graph(seed=4, n_pages=40, n_links=100, n_pillars=3)
        alpha, delta = 0.85, 0.6
        x = graph.compute_weighted_pagerank(depth_decay=delta, alpha=alpha, **EXACT)
        depths = graph.compute_pillar_depths()
        n = len(graph.nodes)
        self.assertTrue(len(depths) < n, "fixture should contain pages unreachable from pillars")
        unreachable_depth = max(depths.values()) + 1

        alpha_u = {u: alpha * delta ** depths.get(u, unreachable_depth) for u in graph.nodes}
        teleport = sum(
            (1 - alpha_u[u] * (1 if graph.edges[u] else 0)) * x[u] for u in graph.nodes
        ) / n
        for v in graph.nodes:
            inflow = sum(alpha_u[u] * x[u] / len(graph.edges[u]) for u in graph.in_edges[v])
            self.assertAlmostEqual(x[v], inflow + teleport, places=10)
        self.assertAlmostEqual(sum(x.values()), 1.0, places=10)

    def test_weighted_pagerank_pillar_equity_beats_equivalent_unreachable_source(self):
        # P (pillar) -> A and Q (support, unreachable) -> B are structurally
        # identical, so standard PageRank ties A and B. Depth weighting favours
        # the pillar's link, yet Q's link still passes some equity.
        self.graph.add_link(self.PILLAR, "https://example.com/a")
        self.graph.add_link("https://example.com/q", "https://example.com/b")

        pr = self.graph.compute_pagerank(**EXACT)
        self.assertAlmostEqual(pr["https://example.com/a"], pr["https://example.com/b"], places=9)

        wpr = self.graph.compute_weighted_pagerank()
        self.assertGreater(wpr["https://example.com/a"], wpr["https://example.com/b"])
        self.assertGreater(wpr["https://example.com/b"], wpr["https://example.com/q"])

    def test_weighted_pagerank_unreachable_pages_are_discounted_as_deepest(self):
        # Pillar -> d1 -> d2, plus unreachable U -> pillar. D = 2, so d(U) = 3:
        # U's link passes alpha * delta**3, less than any reachable page passes.
        self.graph.add_link(self.PILLAR, "https://example.com/d1")
        self.graph.add_link("https://example.com/d1", "https://example.com/d2")
        self.graph.add_link("https://example.com/u", self.PILLAR)
        self.graph.add_page("https://example.com/orphan")

        delta = 0.5
        wpr = self.graph.compute_weighted_pagerank(depth_decay=delta, **EXACT)
        baseline = wpr["https://example.com/orphan"]  # teleport-only share
        # U has no inbound links and sits at the baseline; the pillar receives
        # exactly alpha * delta**3 * x(U) through U's single link.
        self.assertAlmostEqual(wpr["https://example.com/u"], baseline, places=12)
        self.assertAlmostEqual(wpr[self.PILLAR] - baseline, 0.85 * delta ** 3 * wpr["https://example.com/u"], places=12)

    def test_weighted_pagerank_deeper_sources_pass_less_equity(self):
        # Pillar -> d1 -> d2 -> d3 -> tail. The tail is fed only through the deep
        # chain, so the link equity it receives must shrink as depth_decay drops.
        # Link equity = score minus the teleport-only baseline (an orphan page).
        # Total scores are not monotone: withheld equity goes back to everyone
        # via teleport, which matters a lot in tiny graphs.
        chain = [self.PILLAR] + [f"https://example.com/d{i}" for i in range(1, 4)] + ["https://example.com/tail"]
        for src, tgt in zip(chain, chain[1:]):
            self.graph.add_link(src, tgt)
        self.graph.add_page("https://example.com/orphan")

        received = []
        for decay in (1.0, 0.85, 0.5, 0.2, 0.0):
            wpr = self.graph.compute_weighted_pagerank(depth_decay=decay, **EXACT)
            received.append(wpr["https://example.com/tail"] - wpr["https://example.com/orphan"])

        for higher_decay, lower_decay in zip(received, received[1:]):
            self.assertGreater(higher_decay, lower_decay)
        self.assertAlmostEqual(received[-1], 0.0, places=12)  # delta=0: only pillars pass equity

    def test_weighted_pagerank_pillar_role_survives_linking(self):
        # Pillar detection depends on add_link() not overwriting roles.
        self.graph.add_link(self.PILLAR, "https://example.com/a")
        self.graph.add_link("https://example.com/a", self.PILLAR)
        self.assertEqual(self.graph.compute_pillar_depths()[self.PILLAR], 0)

    def test_weighted_pagerank_independent_of_networkx(self):
        graph = _random_graph(seed=5, n_pillars=2)
        results = [result for _, result in _run_both_backends(graph.compute_weighted_pagerank)]
        self.assertTrue(all(result == results[0] for result in results))


class TestSiteTaxonomy(unittest.TestCase):
    def setUp(self):
        self.taxonomy = SiteTaxonomy(
            pillars=("/guides/email-marketing-mastery", "https://example.com/guides/deliverability/"),
            money_pages=("/pricing",),
        )

    def test_role_for_path_entries(self):
        role_for = self.taxonomy.role_for
        self.assertEqual(role_for("https://example.com/guides/email-marketing-mastery"), ROLE_PILLAR)
        self.assertEqual(role_for("https://example.com/guides/email-marketing-mastery/"), ROLE_PILLAR)
        self.assertEqual(role_for("https://other.com/guides/email-marketing-mastery"), ROLE_PILLAR)
        self.assertEqual(role_for("https://example.com/pricing?plan=pro"), ROLE_MONEY)
        self.assertIsNone(role_for("https://example.com/pricing-faq"))  # exact, not prefix
        self.assertIsNone(role_for("https://example.com/blog/post"))

    def test_role_for_absolute_url_entries_checks_host(self):
        self.assertEqual(self.taxonomy.role_for("https://EXAMPLE.com/guides/deliverability"), ROLE_PILLAR)
        self.assertIsNone(self.taxonomy.role_for("https://other.com/guides/deliverability"))

    def test_page_cannot_be_pillar_and_money(self):
        with self.assertRaisesRegex(ValueError, "both pillar and money"):
            SiteTaxonomy(pillars=["/pricing/"], money_pages=["/pricing"])

    def test_from_config(self):
        taxonomy = SiteTaxonomy.from_config({"taxonomy": {"pillars": ["/a"], "money_pages": ["/b"]}})
        self.assertEqual(taxonomy, SiteTaxonomy(pillars=("/a",), money_pages=("/b",)))
        self.assertEqual(SiteTaxonomy.from_config({}), SiteTaxonomy())
        self.assertEqual(SiteTaxonomy.from_config({"taxonomy": {"pillars": None}}), SiteTaxonomy())
        for bad in (
            {"taxonomy": ["/a"]},
            {"taxonomy": {"pillars": "/a"}},
            {"taxonomy": {"money_pages": [1]}},
            {"taxonomy": {"pilars": ["/a"]}},                      # typo: unknown key
            {"taxonomy": {"clusters": ["/a"]}},                    # must be a mapping
            {"taxonomy": {"clusters": {"x": "/a"}}},               # patterns must be a list
            {"taxonomy": {"cluster_affinities": {"x": ["y"]}}},    # undefined clusters
        ):
            with self.subTest(config=bad), self.assertRaises(ValueError):
                SiteTaxonomy.from_config(bad)

    def test_clusters_first_match_wins_and_default(self):
        taxonomy = SiteTaxonomy.from_config({"taxonomy": {
            "clusters": {"email": ["/blog/email", "/guides/"], "billing": ["/guides/billing", "/pricing"]},
            "cluster_affinities": {"email": ["billing"]},
        }})
        self.assertEqual(taxonomy.cluster_for("https://example.com/BLOG/Email-tips"), "email")
        self.assertEqual(taxonomy.cluster_for("https://example.com/guides/billing"), "email")  # config order
        self.assertEqual(taxonomy.cluster_for("https://example.com/pricing"), "billing")
        self.assertEqual(taxonomy.cluster_for("https://example.com/about"), DEFAULT_CLUSTER)
        self.assertEqual(taxonomy.allowed_target_clusters("email"), ("email", "billing"))
        self.assertEqual(taxonomy.allowed_target_clusters("billing"), ("billing",))  # affinity is one-way
        self.assertEqual(SiteTaxonomy().cluster_for("https://example.com/x"), DEFAULT_CLUSTER)

    def test_apply_taxonomy_assigns_clusters_and_reports_unused_patterns(self):
        graph = LinkGraph()
        graph.add_page("https://example.com/blog/email-tips", topic_cluster="manual")
        graph.add_page("https://example.com/about", topic_cluster="manual")
        taxonomy = SiteTaxonomy(clusters={"email": ["/blog/email"], "billing": ["/pricing"]})
        with self.assertWarnsRegex(TaxonomyWarning, "billing: /pricing"):
            unmatched = graph.apply_taxonomy(taxonomy)
        self.assertEqual(unmatched, ["billing: /pricing"])
        self.assertEqual(graph.page_metadata["https://example.com/blog/email-tips"]["cluster"], "email")
        self.assertEqual(graph.page_metadata["https://example.com/about"]["cluster"], DEFAULT_CLUSTER)

    def test_unmatched_entries(self):
        urls = ["https://example.com/pricing", "https://example.com/guides/email-marketing-mastery"]
        self.assertEqual(self.taxonomy.unmatched_entries(urls), ["https://example.com/guides/deliverability/"])

    def test_apply_taxonomy_sets_roles_and_keeps_clusters(self):
        graph = LinkGraph()
        graph.add_page("https://example.com/guides/email-marketing-mastery", topic_cluster="email")
        graph.add_page("https://example.com/pricing", role=ROLE_SUPPORT, topic_cluster="sales")
        graph.add_page("https://example.com/guides/deliverability", topic_cluster="email")
        graph.add_link("https://example.com/blog/post", "https://example.com/pricing")

        with warnings.catch_warnings():
            warnings.simplefilter("error")  # every entry matches: no warning expected
            self.assertEqual(graph.apply_taxonomy(self.taxonomy), [])

        meta = graph.page_metadata
        self.assertEqual(meta["https://example.com/guides/email-marketing-mastery"], {"role": ROLE_PILLAR, "cluster": "email"})
        self.assertEqual(meta["https://example.com/pricing"], {"role": ROLE_MONEY, "cluster": "sales"})
        self.assertEqual(meta["https://example.com/blog/post"]["role"], ROLE_SUPPORT)
        if HAS_NETWORKX:
            self.assertEqual(graph.graph.nodes["https://example.com/pricing"]["role"], ROLE_MONEY)

    def test_apply_taxonomy_warns_about_unmatched_entries(self):
        graph = LinkGraph()
        graph.add_page("https://example.com/pricing")
        with self.assertWarnsRegex(TaxonomyWarning, "email-marketing-mastery"):
            unmatched = graph.apply_taxonomy(self.taxonomy)
        self.assertEqual(len(unmatched), 2)

    def test_configured_pillars_drive_weighted_pagerank(self):
        graph = LinkGraph()
        graph.add_link("https://example.com/guides/email-marketing-mastery", "https://example.com/blog/a")
        graph.add_link("https://example.com/blog/a", "https://example.com/blog/b")
        with self.assertWarns(NoPillarsWarning):
            graph.compute_weighted_pagerank()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TaxonomyWarning)
            graph.apply_taxonomy(self.taxonomy)
        with warnings.catch_warnings():
            warnings.simplefilter("error", NoPillarsWarning)
            graph.compute_weighted_pagerank()
        self.assertEqual(graph.compute_pillar_depths()["https://example.com/blog/b"], 2)


class TestTextMatching(unittest.TestCase):
    def test_tokenize_is_unicode_and_lowercase(self):
        self.assertEqual(tokenize("Rescisão CLT: seguro-desemprego 2026!"), ["rescisão", "clt", "seguro", "desemprego", "2026"])

    def test_content_tokens_drop_stopwords_and_numbers(self):
        self.assertEqual(content_tokens("The Complete Guide to Payroll 2026"), {"complete", "guide", "payroll"})
        self.assertNotIn("guide", STOPWORDS)  # "guide" names topics ("complete invoicing guide")

    def test_prefix_matching_handles_inflections_only_for_long_tokens(self):
        self.assertTrue(tokens_match("segmentation", "segment"))
        self.assertTrue(tokens_match("salário", "salários"))
        self.assertTrue(tokens_match("pix", "pix"))
        self.assertFalse(tokens_match("pix", "pixel"))      # short tokens must match exactly
        self.assertFalse(tokens_match("on", "online"))
        self.assertEqual(matched_topic_tokens({"reminders", "late", "pay"}, "Late payments hurt."), {"late"})


class TestJevSimulation(unittest.TestCase):
    """Offline Jev: confidence and score must use one and the same topic vocabulary."""

    def setUp(self):
        self.client = JevClient(mock_mode=True)

    def _evaluate(self, paragraph, title="Audience Segmentation Software", h1="Deliver Smart Campaigns", queries=None):
        res = self.client.evaluate_link_candidate("s", paragraph, "t", title, h1, target_queries=queries)["results"]
        return res["relevance_score"]["score"], res["has_legitimate_contextual_reason"]["confidence"]

    def test_title_mentions_count_for_score_and_confidence(self):
        # Regression: the score used to ignore the title (6.8 vs 0.89 for this paragraph).
        score, confidence = self._evaluate("Use our audience segmentation features.")
        self.assertEqual((score, confidence), (8.6, 0.89))

    def test_h1_mentions_count_the_same_way(self):
        self.assertEqual(self._evaluate("Deliver smart emails."), self._evaluate("Audience segmentation emails."))

    def test_page2_queries_extend_the_topic(self):
        self.assertEqual(self._evaluate("Send a late payment reminder email.")[0], 3.2)
        score, _ = self._evaluate("Send a late payment reminder email.", queries=["late payment reminder email"])
        self.assertEqual(score, 9.6)

    def test_no_mention_scores_low(self):
        self.assertEqual(self._evaluate("Completely unrelated sentence."), (3.2, 0.25))


class TestAnchorQuality(unittest.TestCase):
    def setUp(self):
        self.aux = AuxiliaryAIEngine()

    def _anchor(self, paragraph, title, topic=None, queries=None):
        proposal = self.aux.craft_link_insertion(paragraph, "https://x.example/t", title, topic or title, queries)
        return proposal.anchor_text if proposal else None

    def test_keeps_inner_stopwords_but_never_edge_ones(self):
        self.assertEqual(
            self._anchor("Emita o contrato de prestação de serviços com cuidado.", "Contrato de Prestação de Serviços"),
            "contrato de prestação de serviços",
        )
        self.assertEqual(self._anchor("Read the complete invoicing guide today.", "Complete Invoicing Guide"),
                         "complete invoicing guide")

    def test_refuses_single_word_number_and_stopword_anchors(self):
        self.assertIsNone(self._anchor("Compare all plans in 2026, your choice.", "Pricing Plans 2026"))
        self.assertIsNone(self._anchor("Our salary data is public.", "Salary Calculator"))

    def test_one_inner_modifier_is_allowed(self):
        self.assertEqual(
            self._anchor("A reclassificação federal da cannabis avança.", "Reclassificação da cannabis"),
            "reclassificação federal da cannabis",
        )

    def test_prefers_tight_anchors_that_name_the_target(self):
        # Same number of topic words: the phrase naming the page ("Stripe Checkout") wins.
        self.assertEqual(
            self._anchor("Embed a pre-built form using Stripe Checkout.", "Stripe Checkout | Pre-built, Hosted Payment Page"),
            "Stripe Checkout",
        )
        # Modifiers cost: "audience segmentation" beats "behavior using audience segmentation".
        self.assertEqual(
            self._anchor("Group contacts by behavior using audience segmentation tools.",
                         "Audience Segmentation Software & Behavioral Targeting"),
            "audience segmentation",
        )

    def test_anchor_length_is_capped(self):
        anchor = self._anchor(
            "Review payment processing in our complete guide to online payments now.",
            "The Complete Guide to Online Payments", "How Online Card Payments and Processing Work",
        )
        self.assertEqual(anchor, "complete guide to online payments")
        self.assertLessEqual(len(tokenize(anchor)), MAX_ANCHOR_WORDS)

    def test_wraps_the_chosen_occurrence_in_place(self):
        proposal = self.aux.craft_link_insertion(
            "Payroll matters. Keep payroll tax deadlines on a calendar.", "https://x.example/t",
            "Payroll Tax Deadlines", "Payroll Tax Deadlines",
        )
        self.assertEqual(proposal.original_sentence, "Keep payroll tax deadlines on a calendar.")
        self.assertEqual(proposal.updated_sentence, "Keep [payroll tax deadlines](https://x.example/t) on a calendar.")

    def test_queries_can_supply_the_anchor(self):
        self.assertEqual(
            self._anchor("Write a late payment reminder email.", "Dunning Basics", queries=["late payment reminder email"]),
            "late payment reminder email",
        )

    def test_anchors_never_overlap_existing_links(self):
        paragraph = "Tomatoes grow best in rich raised bed soil. A cedar raised bed lasts for years."
        free = self.aux.craft_link_insertion(paragraph, "https://x.example/kit", "Cedar Raised Bed Kit",
                                             "Cedar Raised Bed Kit", blocked_phrases=["raised bed soil"])
        self.assertEqual(free.anchor_text, "cedar raised bed")  # the second sentence is free
        blocked = self.aux.craft_link_insertion("Tomatoes grow best in rich raised bed soil.", "https://x.example/kit",
                                                "Cedar Raised Bed Kit", "Cedar Raised Bed Kit",
                                                blocked_phrases=["Raised Bed Soil"])
        self.assertIsNone(blocked)

    def test_min_anchor_words_is_configurable(self):
        aux = AuxiliaryAIEngine(min_anchor_words=1)
        proposal = aux.craft_link_insertion("Read about payroll.", "https://x.example/t", "Payroll", "Payroll")
        self.assertEqual(proposal.anchor_text, "payroll")


class TestLinkRulesPolicy(unittest.TestCase):
    def setUp(self):
        self.graph = LinkGraph()
        self.graph.add_page("https://x.example/money", role=ROLE_MONEY, topic_cluster="a")
        self.graph.add_page("https://x.example/same", role=ROLE_SUPPORT, topic_cluster="a")
        self.graph.add_page("https://x.example/other", role=ROLE_SUPPORT, topic_cluster="b")

    def _allowed(self, target, policy):
        return self.graph.validate_link_rules("https://x.example/money", target, money_to_support=policy)[0]

    def test_policies(self):
        same, other = "https://x.example/same", "https://x.example/other"
        self.assertEqual((self._allowed(same, "forbid"), self._allowed(other, "forbid")), (False, False))
        self.assertEqual((self._allowed(same, "same_cluster"), self._allowed(other, "same_cluster")), (True, False))
        self.assertEqual((self._allowed(same, "allow"), self._allowed(other, "allow")), (True, True))
        self.assertFalse(self.graph.validate_link_rules("https://x.example/money", same)[0])  # default: forbid

    def test_config_section_is_strict(self):
        self.assertEqual(LinkRules.from_config({"link_rules": {"money_to_support": "allow"}}), LinkRules("allow"))
        self.assertEqual(LinkRules.from_config({}), LinkRules("forbid"))
        for bad in ({"link_rules": {"money_to_suport": "allow"}}, {"link_rules": {"money_to_support": "sometimes"}}):
            with self.subTest(config=bad), self.assertRaises(ValueError):
                LinkRules.from_config(bad)


class TestJevClient(unittest.TestCase):
    def setUp(self):
        self.client = JevClient(mock_mode=True)

    def test_simulated_choice_questions_pick_the_first_option(self):
        request = JevEvaluationRequest(state={"source_paragraph": "text", "target_title": "Title"}, questions=[
            JevQuestion("cluster", "choice", "Which cluster?", options=["Billing", "Email"]),
            JevQuestion("free", "choice", "Any category?"),
        ])
        results = self.client.evaluate(request)["results"]
        self.assertEqual(results["cluster"], {"selected": "Billing", "confidence": 0.88})
        self.assertEqual(results["free"]["selected"], "General")

    def test_link_candidate_evaluation(self):
        res = self.client.evaluate_link_candidate(
            source_url="https://example.com/blog/tips",
            source_paragraph="You need to set up a sequence of welcome emails for new subscribers.",
            target_url="https://example.com/blog/welcome-sequence",
            target_title="Welcome Sequence Guide",
            target_topic="welcome sequence",
        )
        self.assertIn("results", res)
        results = res["results"]
        self.assertTrue(results["has_legitimate_contextual_reason"]["value"])
        self.assertGreaterEqual(results["relevance_score"]["score"], 7.0)


class TestAuxiliaryAI(unittest.TestCase):
    def setUp(self):
        self.aux = AuxiliaryAIEngine()

    def test_llm_key_is_reported_as_unused(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "placeholder"}), \
                self.assertLogs("seo_magus.engines.auxiliary_ai", "WARNING") as logs:
            engine = AuxiliaryAIEngine()
        self.assertEqual(engine.api_key, "placeholder")
        self.assertIn("only the offline anchor engine is implemented", logs.output[0])

    def test_craft_link_insertion(self):
        paragraph = "You need to set up an automated welcome sequence for all new signups."
        proposal = self.aux.craft_link_insertion(
            source_paragraph=paragraph,
            target_url="https://example.com/welcome-guide",
            target_title="Welcome Sequence Guide",
            target_topic="welcome sequence",
        )
        self.assertIsNotNone(proposal)
        self.assertIn("welcome", proposal.anchor_text.lower())
        self.assertIn("[", proposal.updated_sentence)
        self.assertIn("https://example.com/welcome-guide", proposal.updated_sentence)


class TestGSCConnector(unittest.TestCase):
    def test_page2_filtering(self):
        connector = GSCConnector()
        rows = [
            GSCQueryRow(query="page 1 term", page="p1", clicks=100, impressions=5000, ctr=0.02, position=3.4),
            GSCQueryRow(query="page 2 term high imp", page="p2", clicks=10, impressions=2500, ctr=0.004, position=13.5),
            GSCQueryRow(query="page 2 term low imp", page="p3", clicks=2, impressions=20, ctr=0.1, position=15.0),
            GSCQueryRow(query="page 3 term", page="p4", clicks=0, impressions=300, ctr=0.0, position=25.0),
        ]
        opps = connector.get_page2_opportunities(rows, min_impressions=50)
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].query, "page 2 term high imp")


if __name__ == "__main__":
    unittest.main()
