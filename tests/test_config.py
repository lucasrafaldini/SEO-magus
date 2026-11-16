"""
Tests for configuration loading and its wiring into the optimizer, GSC connector and CLI.
Precedence everywhere: explicit argument / CLI flag > config file > built-in default.
"""

import io
import tempfile
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from src import cli
from src.config import (
    DEFAULT_THRESHOLDS,
    SiteConfig,
    Thresholds,
    load_config,
    load_site_config,
    load_taxonomy,
)
from src.connectors.gsc_connector import GSCConnector, GSCQueryRow
from src.connectors.sitemap_crawler import ParsedPage, SitemapCrawler
from src.engines.link_graph import TaxonomyWarning
from src.engines.taxonomy import DEFAULT_CLUSTER, ROLE_MONEY, ROLE_PILLAR, ROLE_SUPPORT, SiteTaxonomy
from src.workflows.linking_optimizer import LinkingOptimizer

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG = REPO_ROOT / "config" / "config.example.yaml"

DEMO_PILLAR = "https://example.com/guides/email-marketing-mastery"
DEMO_MONEY = "https://example.com/pricing"


def _write(test: unittest.TestCase, text: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    test.addCleanup(Path(handle.name).unlink)
    return Path(handle.name)


class TestConfigLoading(unittest.TestCase):
    def test_example_config_loads(self):
        config = load_site_config(EXAMPLE_CONFIG)
        self.assertEqual(config.taxonomy.pillars, ("/guides/email-marketing-mastery", "/guides/domain-authentication"))
        self.assertEqual(config.taxonomy.money_pages, ("/pricing", "/features/automation", "/features/segmentation"))
        self.assertEqual(config.thresholds, Thresholds(
            min_confidence=0.85, min_score=7.0,
            page2_min_position=11.0, page2_max_position=20.0, min_impressions=100,
        ))
        self.assertEqual(load_taxonomy(EXAMPLE_CONFIG), config.taxonomy)

    def test_missing_file(self):
        with self.assertRaisesRegex(FileNotFoundError, "config.example.yaml"):
            load_config(REPO_ROOT / "config" / "does-not-exist.yaml")

    def test_empty_file_is_all_defaults(self):
        self.assertEqual(load_config(_write(self, "")), {})
        self.assertEqual(load_site_config(_write(self, "")), SiteConfig())

    def test_top_level_must_be_mapping(self):
        with self.assertRaisesRegex(ValueError, "mapping"):
            load_config(_write(self, "- just\n- a list\n"))


class TestThresholds(unittest.TestCase):
    def test_defaults_are_the_single_source_of_truth(self):
        self.assertEqual(DEFAULT_THRESHOLDS, Thresholds())
        optimizer = LinkingOptimizer()
        self.assertEqual((optimizer.min_score, optimizer.min_confidence), (7.0, 0.80))
        rows = [
            GSCQueryRow("in window", "p", 1, 50, 0.1, 11.0),
            GSCQueryRow("too few impressions", "p", 1, 49, 0.1, 15.0),
            GSCQueryRow("page 3", "p", 1, 500, 0.1, 20.5),
        ]
        self.assertEqual([r.query for r in GSCConnector().get_page2_opportunities(rows)], ["in window"])

    def test_partial_section_keeps_defaults(self):
        thresholds = Thresholds.from_config({"thresholds": {"min_impressions": 10}})
        self.assertEqual(thresholds, Thresholds(min_impressions=10))

    def test_unknown_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "min_score_minimum"):
            Thresholds.from_config({"thresholds": {"min_score_minimum": 8}})

    def test_invalid_values_are_rejected(self):
        for bad in (
            {"min_confidence": 1.5},
            {"min_score": 0},
            {"page2_min_position": 21.0},
            {"min_impressions": -1},
            {"min_impressions": 2.5},
            {"min_score": "7"},
            {"min_score": True},
            {"max_click_depth": 0},
        ):
            with self.subTest(**bad), self.assertRaises(ValueError):
                Thresholds(**bad)

    def test_legacy_vendor_names_still_work_with_a_warning(self):
        with self.assertLogs("seo_magus.config", "WARNING") as logs:
            thresholds = Thresholds.from_config({"thresholds": {"jev_noul_min_confidence": 0.9, "jev_score_min": 8}})
        self.assertEqual((thresholds.min_confidence, thresholds.min_score), (0.9, 8))
        self.assertTrue(all("deprecated" in line for line in logs.output))
        with self.assertRaisesRegex(ValueError, "legacy"):
            Thresholds.from_config({"thresholds": {"jev_score_min": 8, "min_score": 8}})

    def test_unknown_and_legacy_sections_are_reported(self):
        with self.assertLogs("seo_magus.config", "WARNING") as logs:
            SiteConfig.from_config({"api_keys": {"openai_api_key": "x"}, "thresholdz": {}})
        text = "\n".join(logs.output)
        self.assertIn("'api_keys' is no longer used", text)
        self.assertIn("Unknown config section 'thresholdz'", text)

    def test_overrides_ignore_none(self):
        base = Thresholds(min_score=8.0)
        self.assertEqual(base.with_overrides(min_score=None, min_impressions=5), Thresholds(min_score=8.0, min_impressions=5))


class TestOptimizerConfiguration(unittest.TestCase):
    def _run(self, optimizer, pages=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TaxonomyWarning)
            return optimizer.run_optimization(pages or SitemapCrawler.get_sample_site_pages())

    def test_site_agnostic_without_config(self):
        # No site is built in: without a taxonomy every page is a support page
        # in the default cluster, whatever its URL looks like.
        optimizer = LinkingOptimizer()
        pages = [
            ParsedPage("https://canivete.cc/guias/guia-rescisao/", "Guia", "Guia", ["Texto."]),
            ParsedPage("https://canivete.cc/financas/calculadora-rescisao-clt/", "Calc", "Calc", ["Texto."]),
            ParsedPage("https://example.com/pricing", "Pricing", "Pricing", ["Text."]),
        ]
        self._run(optimizer, pages)
        for url, meta in optimizer.link_graph.page_metadata.items():
            with self.subTest(url=url):
                self.assertEqual(meta, {"role": ROLE_SUPPORT, "cluster": DEFAULT_CLUSTER})

    def test_config_thresholds_and_taxonomy_are_applied(self):
        config = load_site_config(EXAMPLE_CONFIG)
        optimizer = LinkingOptimizer.from_config(config)
        self.assertEqual((optimizer.min_score, optimizer.min_confidence), (7.0, 0.85))
        self._run(optimizer)
        meta = optimizer.link_graph.page_metadata
        self.assertEqual(meta[DEMO_PILLAR]["role"], ROLE_PILLAR)
        self.assertEqual(meta[DEMO_MONEY]["role"], ROLE_MONEY)

    def test_explicit_arguments_override_config(self):
        config = SiteConfig(thresholds=Thresholds(min_score=8.0, min_confidence=0.9))
        optimizer = LinkingOptimizer.from_config(config, min_score=9.5)
        self.assertEqual((optimizer.min_score, optimizer.min_confidence), (9.5, 0.9))

    def test_stricter_thresholds_approve_fewer_links(self):
        lenient = self._run(LinkingOptimizer(thresholds=Thresholds(min_confidence=0.5, min_score=5.0)))
        strict = self._run(LinkingOptimizer(thresholds=Thresholds(min_confidence=0.95, min_score=9.5)))
        self.assertGreater(lenient.links_approved, strict.links_approved)
        for r in strict.results:
            self.assertGreaterEqual(r.relevance_score, 9.5)

    def test_each_run_starts_from_a_fresh_graph(self):
        optimizer = LinkingOptimizer()
        first_pages = SitemapCrawler.get_sample_site_pages()
        second_pages = [
            ParsedPage("https://other.example/a", "Alpha", "Alpha", ["Read about beta widgets here."]),
            ParsedPage("https://other.example/b", "Beta Widgets", "Beta Widgets", ["Widgets explained."]),
        ]
        first = self._run(optimizer, first_pages)
        second = self._run(optimizer, second_pages)
        self.assertEqual(optimizer.link_graph.nodes, {p.url for p in second_pages})
        self.assertTrue(set(second.orphan_pages) <= {p.url for p in second_pages})
        # Running the first site again reproduces its original result exactly.
        again = self._run(optimizer, first_pages)
        self.assertEqual([r.updated_sentence for r in again.results], [r.updated_sentence for r in first.results])
        self.assertEqual(sorted(again.orphan_pages), sorted(first.orphan_pages))

    def test_taxonomy_clusters_set_the_topic_boundary(self):
        pages = [
            ParsedPage("https://site.example/email/a", "A", "A", ["Our welcome sequence guide explains onboarding."]),
            ParsedPage("https://site.example/email/welcome", "Welcome Sequence Guide", "Welcome Sequence Guide", ["x"]),
            ParsedPage("https://site.example/billing/b", "B", "B", ["Our welcome sequence guide explains onboarding."]),
        ]
        taxonomy = SiteTaxonomy(clusters={"email": ["/email/"], "billing": ["/billing/"]})
        result = self._run(LinkingOptimizer(taxonomy=taxonomy), pages)
        links = {(r.source_url, r.target_url) for r in result.results}
        self.assertIn(("https://site.example/email/a", "https://site.example/email/welcome"), links)
        self.assertNotIn(("https://site.example/billing/b", "https://site.example/email/welcome"), links)

        with_affinity = SiteTaxonomy(
            clusters={"email": ["/email/"], "billing": ["/billing/"]}, cluster_affinities={"billing": ["email"]}
        )
        result = self._run(LinkingOptimizer(taxonomy=with_affinity), pages)
        self.assertIn(
            ("https://site.example/billing/b", "https://site.example/email/welcome"),
            {(r.source_url, r.target_url) for r in result.results},
        )


class TestCliWiring(unittest.TestCase):
    def _main(self, *argv):
        out = io.StringIO()
        with mock.patch("src.cli.LinkingOptimizer", wraps=LinkingOptimizer) as optimizer_cls, \
                mock.patch("sys.argv", ["seo-magus", *argv]), \
                warnings.catch_warnings(), redirect_stdout(out):
            warnings.simplefilter("ignore", TaxonomyWarning)
            optimizer_cls.from_config = mock.Mock(wraps=LinkingOptimizer.from_config)
            cli.main()
        return optimizer_cls.from_config.call_args_list, out.getvalue()

    def test_audit_uses_config_thresholds(self):
        calls, output = self._main("audit", "--config", str(EXAMPLE_CONFIG))
        config, kwargs = calls[0].args[0], calls[0].kwargs
        self.assertEqual(config, load_site_config(EXAMPLE_CONFIG))
        self.assertEqual((kwargs["min_score"], kwargs["min_confidence"]), (None, None))
        self.assertIn("Gate: score >= 7.0, confidence >= 0.85", output)

    def test_audit_flags_override_config(self):
        _, output = self._main("audit", "--config", str(EXAMPLE_CONFIG), "--min-score", "9.5", "--min-conf", "0.9")
        self.assertIn("Gate: score >= 9.5, confidence >= 0.9", output)

    def test_audit_without_config_uses_defaults(self):
        calls, output = self._main("audit")
        self.assertEqual(calls[0].args[0], SiteConfig())
        self.assertIn("Gate: score >= 7.0, confidence >= 0.8", output)

    def test_boost_page2_uses_config_then_flags(self):
        # Sample data has a page 2 query with 950 impressions; the example config needs >= 100.
        _, output = self._main("boost-page2", "--config", str(EXAMPLE_CONFIG))
        self.assertIn("Positions 11.0 to 20.0, >= 100 impressions", output)
        self.assertIn("backlink exchange strategies", output)
        _, output = self._main("boost-page2", "--config", str(EXAMPLE_CONFIG), "--min-impressions", "1000")
        self.assertIn(">= 1000 impressions", output)
        self.assertNotIn("backlink exchange strategies", output)
        _, output = self._main("boost-page2")
        self.assertIn(">= 50 impressions", output)

    def test_benchmark_uses_each_sites_own_config(self):
        from src.benchmarks import BENCHMARKS, run_benchmark
        runs = []

        def recording_run(site, *args, **kwargs):
            runs.append(run_benchmark(site, *args, **kwargs))
            return runs[-1]

        with mock.patch("src.cli.run_benchmark", side_effect=recording_run):
            _, output = self._main("benchmark", "--site", "all")
        self.assertEqual([run.config for run in runs], [site.load_config() for site in BENCHMARKS.values()])
        self.assertEqual(len({id(run.optimizer) for run in runs}), len(BENCHMARKS))  # fresh optimizer per site
        self.assertIn("[OK] Expected links found: 7/7 (recall 100% | precision 100%)", output)
        self.assertIn("Ranking: Ledgerly", output)


if __name__ == "__main__":
    unittest.main()
