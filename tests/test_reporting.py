"""
Visual reporting: per-page analysis, HTML report (semantic map, leaderboard,
authority/hub plane) and terminal leaderboard.
"""

import io
import re
import tempfile
import unittest
import warnings
import xml.dom.minidom
from pathlib import Path
from unittest import mock

from src.benchmarks import get_benchmark, run_benchmark
from src.benchmarks import reference as ref
from src.config import SiteConfig
from src.connectors.sitemap_crawler import ParsedPage
from src.reporting import analyze_benchmark, analyze_site, render_index, render_site_report, write_reports
from src.reporting import terminal
from src.workflows.linking_optimizer import LinkingOptimizer


def _reference_analysis():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return analyze_benchmark(run_benchmark(get_benchmark("reference")))


class TestAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = _reference_analysis()

    def test_pages_are_ranked_best_first(self):
        pages = self.analysis.pages
        self.assertEqual([p.rank_after for p in pages], list(range(1, len(pages) + 1)))
        self.assertEqual(pages, sorted(pages, key=lambda p: -p.pagerank_after))
        self.assertEqual(pages[0].url, ref.INVOICING_GUIDE)
        self.assertAlmostEqual(sum(p.pagerank_after for p in pages), 1.0, places=6)
        self.assertAlmostEqual(sum(p.pagerank_before for p in pages), 1.0, places=6)

    def test_before_after_and_link_counts(self):
        news = self.analysis.page(ref.COMPANY_NEWS)
        self.assertTrue(news.orphan_before and news.orphan_after)
        template = self.analysis.page(ref.INVOICE_TEMPLATE)
        self.assertEqual((template.inbound_before, template.inbound_after, template.new_inbound), (0, 1, 1))
        self.assertEqual(sum(p.new_inbound for p in self.analysis.pages), len(ref.EXPECTED_LINKS))
        self.assertEqual(sum(p.new_outbound for p in self.analysis.pages), len(ref.EXPECTED_LINKS))

    def test_depths_weighted_rank_and_search_console(self):
        for url, depth in ref.EXPECTED_PILLAR_DEPTHS.items():
            self.assertEqual(self.analysis.page(url).click_depth, depth)
        self.assertIsNone(self.analysis.page(ref.COMPANY_NEWS).click_depth)
        self.assertTrue(all(p.weighted_pagerank is not None for p in self.analysis.pages))
        page2 = {p.url for p in self.analysis.pages if p.page2}
        self.assertEqual(page2, {t for _, t in ref.EXPECTED_PAGE2_LINKS})
        self.assertEqual(self.analysis.page(ref.INVOICE_TEMPLATE).gsc_position, 3.2)

    def test_clusters_ordered_by_equity_and_verdict(self):
        self.assertEqual(self.analysis.clusters[0], "invoicing")
        verdict = self.analysis.benchmark
        self.assertEqual((verdict.recall, verdict.precision, verdict.missing), (1.0, 1.0, []))

    def test_sites_without_pillars_skip_weighted_rank(self):
        pages = [ParsedPage("https://x.example/a", "A", "A", ["x"], ["https://x.example/b"]),
                 ParsedPage("https://x.example/b", "B", "B", ["y"])]
        optimizer = LinkingOptimizer()
        report = optimizer.run_optimization(pages)
        analysis = analyze_site("x", "X", pages, optimizer.baseline_graph, optimizer.link_graph, report, SiteConfig())
        self.assertTrue(all(p.weighted_pagerank is None for p in analysis.pages))
        self.assertIn("No pillar pages", analysis.notes[0])


class TestHtmlReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = _reference_analysis()
        cls.html = render_site_report(cls.analysis)

    def test_sections_are_present(self):
        for heading in ("Benchmark verdict", "Semantic map", "Ranking leaderboard", "Authorities and hubs",
                        "Approved links", "Decision funnel"):
            self.assertIn(f"<h2>{heading}</h2>", self.html)

    def test_svgs_are_well_formed_and_show_every_page_and_link(self):
        svgs = re.findall(r"<svg.*?</svg>", self.html, re.S)
        self.assertEqual(len(svgs), 2)
        for svg in svgs:
            xml.dom.minidom.parseString(svg)
        semantic_map = svgs[0]
        for page in self.analysis.pages:
            self.assertIn(f"#{page.rank_after} {page.label}", semantic_map)
        self.assertEqual(semantic_map.count("<title>new link:"), len(ref.EXPECTED_LINKS))
        self.assertEqual(semantic_map.count("<title>existing link:"), 1)

    def test_anchor_highlight_and_page2_badges(self):
        self.assertIn("<mark>payroll tax deadlines</mark>", self.html)
        self.assertEqual(self.html.count("boosts page 2:"), len(ref.EXPECTED_PAGE2_LINKS))

    def test_content_is_escaped(self):
        pages = [ParsedPage("https://x.example/<a>", "<script>alert(1)</script>", "h", ["Text."])]
        optimizer = LinkingOptimizer()
        report = optimizer.run_optimization(pages)
        analysis = analyze_site("x", "<b>X</b>", pages, optimizer.baseline_graph, optimizer.link_graph, report, SiteConfig())
        html = render_site_report(analysis)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>X</b>", html)
        for svg in re.findall(r"<svg.*?</svg>", html, re.S):
            xml.dom.minidom.parseString(svg)

    def test_write_reports_creates_index_and_site_pages(self):
        second = _reference_analysis()
        second.key, second.name = "copy", "Copy"
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_reports([self.analysis, second], tmp)
            self.assertEqual([p.name for p in paths], ["index.html", "reference.html", "copy.html"])
            index = Path(tmp, "index.html").read_text(encoding="utf-8")
            self.assertIn('href="reference.html"', index)
            self.assertIn('href="index.html"', Path(tmp, "reference.html").read_text(encoding="utf-8"))
        self.assertIn('<td class="good">7/7</td>', render_index([self.analysis]))

    def test_known_gaps_are_amber_not_green(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stripe = analyze_benchmark(run_benchmark(get_benchmark("stripe")))
        self.assertIn('<td class="warn">0/1</td>', render_index([stripe]))


class TestTerminal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = _reference_analysis()

    def _leaderboard(self, **style):
        out = io.StringIO()
        terminal.print_leaderboard(self.analysis, limit=3, file=out, style=terminal.TerminalStyle(**style))
        return out.getvalue()

    def test_leaderboard_lists_pages_best_first(self):
        text = self._leaderboard()
        labels = [p.label for p in self.analysis.pages]
        positions = [text.index(label) for label in labels[:3]]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn(labels[-1], text)
        self.assertIn("#", text)

    def test_default_output_is_plain_ascii_without_colour(self):
        text = self._leaderboard()
        self.assertTrue(text.isascii(), [c for c in text if not c.isascii()])
        self.assertNotIn("\x1b[", text)
        self.assertIn("+----", text)

    def test_tables_fit_the_terminal_width(self):
        for width in (50, 60, 80, 100, 140):
            with self.subTest(width=width):
                lines = self._leaderboard(width=width).splitlines()
                self.assertLessEqual(max(len(line) for line in lines), width)

    def test_unicode_and_colour_are_opt_in(self):
        fancy = self._leaderboard(unicode=True, color=True)
        self.assertIn("│", fancy)
        self.assertIn("\x1b[", fancy)

    def test_detect_respects_environment(self):
        tty = mock.Mock(isatty=lambda: True)
        with mock.patch.dict("os.environ", {"NO_COLOR": "1", "SEO_MAGUS_UNICODE": "1"}):
            style = terminal.TerminalStyle.detect(stream=tty, width=90)
        self.assertEqual((style.unicode, style.color, style.width), (True, False, 90))
        with mock.patch.dict("os.environ", {}, clear=True):
            piped = terminal.TerminalStyle.detect(stream=io.StringIO())
        self.assertEqual((piped.unicode, piped.color, piped.width), (False, False, terminal.DEFAULT_WIDTH))

    def test_verdict_explains_missing_links(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            analysis = analyze_benchmark(run_benchmark(get_benchmark("stripe")))
        out = io.StringIO()
        terminal.print_verdict(analysis, file=out, style=terminal.TerminalStyle())
        self.assertIn("missing [known gap] how-to-prevent-credit-card-fraud -> checkout: classifier gate", out.getvalue())
        self.assertTrue(out.getvalue().isascii())


if __name__ == "__main__":
    unittest.main()
