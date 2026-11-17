"""
Logging: configuration (levels, env var, file, warnings) and the workflow events
the project must log so a run can be followed while it happens.
"""

import io
import logging
import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock
from urllib.error import URLError

import pytest

from src import cli
from src.connectors.sitemap_crawler import SitemapCrawler
from src.engines import link_graph as link_graph_module
from src.engines.jev_client import JevClient
from src.engines.link_graph import LinkGraph, TaxonomyWarning
from src.engines.taxonomy import SiteTaxonomy
from src.log import ROOT_LOGGER_NAME, configure_logging, get_logger, resolve_level
from src.workflows.linking_optimizer import LinkingOptimizer

ROOT = ROOT_LOGGER_NAME


class LoggingTestCase(unittest.TestCase):
    def setUp(self):
        root = logging.getLogger(ROOT)
        saved = (root.level, list(root.handlers))
        warnings_logger = logging.getLogger("py.warnings")
        saved_warnings = (list(warnings_logger.handlers), warnings_logger.propagate)

        def restore():
            root.setLevel(saved[0])
            root.handlers[:] = saved[1]
            warnings_logger.handlers[:] = saved_warnings[0]
            warnings_logger.propagate = saved_warnings[1]
            logging.captureWarnings(False)

        self.addCleanup(restore)


class TestConfiguration(LoggingTestCase):
    def test_module_loggers_live_under_one_root(self):
        self.assertEqual(get_logger("src.engines.link_graph").name, f"{ROOT}.engines.link_graph")
        self.assertEqual(get_logger("__main__").name, f"{ROOT}.cli")

    def test_level_precedence_flag_env_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_level(None), logging.WARNING)
        with mock.patch.dict(os.environ, {"SEO_MAGUS_LOG_LEVEL": "debug"}):
            self.assertEqual(resolve_level(None), logging.DEBUG)
            self.assertEqual(resolve_level("error"), logging.ERROR)
        self.assertEqual(resolve_level(logging.INFO), logging.INFO)  # numeric levels pass through
        with self.assertRaises(ValueError):
            resolve_level("LOUD")

    def test_stream_file_and_warnings(self):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp, "logs", "run.log")
            configure_logging("INFO", log_file, stream=stream)
            configure_logging("INFO", log_file, stream=stream)  # idempotent: no duplicate handlers
            get_logger("src.test").info("hello %s", "world")
            get_logger("src.test").debug("hidden")
            warnings.warn("taxonomy problem", TaxonomyWarning)
            for handler in logging.getLogger(ROOT).handlers:
                handler.flush()
            text = log_file.read_text(encoding="utf-8")
            for handler in list(logging.getLogger(ROOT).handlers):
                handler.close()
        self.assertEqual(stream.getvalue().count("hello world"), 1)
        self.assertIn("INFO    seo_magus.test: hello world", text)
        self.assertNotIn("hidden", text)
        self.assertIn("TaxonomyWarning: taxonomy problem", stream.getvalue())


class TestWorkflowEvents(LoggingTestCase):
    def test_optimizer_logs_milestones_and_decisions(self):
        optimizer = LinkingOptimizer()
        with self.assertLogs(f"{ROOT}.workflows.linking_optimizer", "DEBUG") as logs:
            optimizer.run_optimization(SitemapCrawler.get_sample_site_pages())
        text = "\n".join(logs.output)
        self.assertIn("Optimization started: 4 pages", text)
        self.assertIn("Link graph built", text)
        self.assertIn("No Search Console data", text)
        self.assertIn("Source 4/4 done", text)
        self.assertIn("Optimization finished", text)
        self.assertEqual(text.count("DEBUG:seo_magus.workflows.linking_optimizer:Decision "), 12)  # 4 x 3 pairs

    def test_jev_api_failure_is_a_warning(self):
        client = JevClient(api_key="placeholder")
        with mock.patch("src.engines.jev_client.urlopen", side_effect=URLError("offline")), \
                self.assertLogs(f"{ROOT}.engines.jev_client", "WARNING") as logs:
            result = client.evaluate_link_candidate("s", "text", "t", "Title", "Topic")
        self.assertTrue(result["simulated"])
        self.assertIn("falling back to offline simulation", logs.output[0])

    def test_networkx_backend_fallback_is_logged_once(self):
        if not link_graph_module.HAS_NETWORKX:
            self.skipTest("networkx not installed")
        graph = LinkGraph()
        graph.add_link("a", "b")
        with mock.patch.object(link_graph_module, "_warned_backend_fallback", False), \
                mock.patch.object(link_graph_module.nx, "pagerank", side_effect=ImportError("No module named 'scipy'")), \
                self.assertLogs(f"{ROOT}.engines.link_graph", "WARNING") as logs:
            graph.compute_pagerank()
            graph.compute_cheirank()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("pure-Python backend", logs.output[0])

    @pytest.mark.integration  # crawls the mock site over HTTP
    def test_crawl_and_site_audit_are_logged(self):
        from src.benchmarks.mock_sites import SCRAMBLED_SITE, crawl_mock_site
        from src.workflows.site_audit import audit_site
        with self.assertLogs(ROOT, "DEBUG") as logs:
            audit_site(crawl_mock_site(SCRAMBLED_SITE).result)
        text = "\n".join(logs.output)
        self.assertIn("Crawl finished", text)
        self.assertIn("2 broken, 2 redirects, 1 blocked by robots.txt", text)
        self.assertIn("Blocked by robots.txt", text)
        self.assertIn("Site audit of", text)
        self.assertIn("Issue [error] orphan_page", text)

    def test_taxonomy_application_is_logged(self):
        graph = LinkGraph()
        graph.add_page("https://x.example/pricing")
        with self.assertLogs(f"{ROOT}.engines.link_graph", "INFO") as logs:
            graph.apply_taxonomy(SiteTaxonomy(money_pages=["/pricing"]))
        self.assertIn("1 money pages", logs.output[0])


class TestCliLogging(LoggingTestCase):
    def _main(self, *argv):
        stream = io.StringIO()
        real_configure = configure_logging
        with mock.patch("src.cli.configure_logging", side_effect=lambda level, log_file: real_configure(level, log_file, stream)), \
                mock.patch("sys.stdout", io.StringIO()):
            cli.main(list(argv))
        return stream.getvalue()

    def test_verbosity_flags(self):
        self.assertNotIn("INFO", self._main("boost-page2"))
        self.assertIn("INFO    seo_magus.cli: Command: boost-page2", self._main("-v", "boost-page2"))
        self.assertIn("DEBUG   seo_magus.connectors.gsc_connector", self._main("-vv", "boost-page2"))
        self.assertIn("DEBUG", self._main("--log-level", "debug", "boost-page2"))

    def test_bad_config_is_logged_and_exits_with_code_2(self):
        with self.assertLogs(f"{ROOT}.cli", "ERROR") as logs, self.assertRaises(SystemExit) as exit_info:
            self._main("boost-page2", "--config", "/does/not/exist.yaml")
        self.assertEqual(exit_info.exception.code, 2)
        self.assertIn("Config file not found: /does/not/exist.yaml", logs.output[0])


if __name__ == "__main__":
    unittest.main()


class TestRunContextAndProgress(LoggingTestCase):
    def test_make_run_id_is_named_once_and_the_line_format_never_changes(self):
        with mock.patch.dict(os.environ, {"SEO_MAGUS_RUN_ID": "20260101T000000Z-abcd"}):
            stream = io.StringIO()
            configure_logging("INFO", stream=stream)
            get_logger("src.test").info("inside a make step")
            command = self._cli_log("-v", "boost-page2")
        self.assertIn("INFO    seo_magus.test: inside a make step", stream.getvalue())     # same format as ever
        self.assertIn("seo_magus.cli: Command: boost-page2 (make run 20260101T000000Z-abcd)", command)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIn("Command: boost-page2\n", self._cli_log("-v", "boost-page2"))

    def _cli_log(self, *argv):
        stream = io.StringIO()
        real_configure = configure_logging
        with mock.patch("src.cli.configure_logging", side_effect=lambda level, log_file: real_configure(level, log_file, stream)), \
                mock.patch("sys.stdout", io.StringIO()):
            cli.main(list(argv))
        return stream.getvalue()

    def test_large_runs_log_progress_not_every_page(self):
        from src.connectors.sitemap_crawler import ParsedPage
        pages = [ParsedPage(f"https://x.example/p{i}", f"Page {i} Topic", f"Page {i} Topic", [f"Read about page {i + 1} topic."])
                 for i in range(40)]
        with self.assertLogs(f"{ROOT}.workflows.linking_optimizer", "INFO") as logs:
            LinkingOptimizer().run_optimization(pages)
        info = [line for line in logs.output if line.startswith("INFO")]
        progress = [line for line in info if "Link search" in line]
        self.assertEqual(len(progress), 9)                                # 10%, 20%, ... 90% (100% = "finished")
        self.assertIn("Link search 10% (4/40 source pages)", progress[0])
        self.assertFalse([line for line in info if "Source " in line or "Link approved" in line])
