"""
LinkingOptimizer flow behaviour: best paragraph selection, Search Console
steering, site link rules and the run's bookkeeping.
"""

import unittest
import warnings

from src.config import LinkRules, SiteConfig, Thresholds
from src.connectors.gsc_connector import GSCQueryRow
from src.connectors.sitemap_crawler import ParsedPage
from src.engines.taxonomy import SiteTaxonomy
from src.workflows.linking_optimizer import REASON_APPROVED, REASON_ROLE_RULE, LinkingOptimizer

BASE = "https://site.example"


def _page(path, title, paragraphs, links=()):
    return ParsedPage(f"{BASE}{path}", title, title, list(paragraphs), list(links))


class OptimizerTestCase(unittest.TestCase):
    def run_pages(self, pages, optimizer=None, gsc=None):
        optimizer = optimizer or LinkingOptimizer()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            report = optimizer.run_optimization(pages, gsc)
        return optimizer, report


class TestBestParagraph(OptimizerTestCase):
    def test_best_paragraph_wins_over_first_qualifying(self):
        # Paragraph 1 passes the gate with a valid anchor ("payroll deadline"),
        # but paragraph 2 names the target better.
        source = _page("/guides/payroll", "Payroll Guide", [
            "Never miss a payroll deadline again.",
            "Keep a calendar of payroll tax deadlines for every state.",
        ])
        target = _page("/payroll/deadlines", "Payroll Tax Deadlines", ["Quarterly filings are due in April."])
        optimizer, report = self.run_pages([source, target])
        result = next(r for r in report.results if r.target_url == target.url)
        self.assertEqual(result.anchor_text, "payroll tax deadlines")
        self.assertEqual(result.original_sentence, "Keep a calendar of payroll tax deadlines for every state.")
        decision = optimizer.explain_link(source.url, target.url)
        self.assertEqual((decision.reason, decision.paragraphs_evaluated), (REASON_APPROVED, 2))
        # Paragraph 1 alone would have been approved with the weaker anchor.
        _, alone = self.run_pages([_page("/guides/payroll", "Payroll Guide", source.paragraphs[:1]), target])
        self.assertEqual(alone.results[0].anchor_text, "payroll deadline")

    def test_ties_keep_the_earliest_paragraph(self):
        source = _page("/a", "A", ["See the pricing plans page.", "Compare pricing plans again."])
        target = _page("/pricing", "Pricing Plans", ["Plans."])
        _, report = self.run_pages([source, target])
        self.assertEqual(report.results[0].original_sentence, "See the pricing plans page.")


class TestSearchConsoleSteering(OptimizerTestCase):
    def setUp(self):
        super().setUp()
        self.source = _page("/blog/dunning", "Dunning Basics", ["Every overdue account needs a late payment reminder email."])
        self.target = _page("/reminders/", "Overdue Notices", ["Templates for overdue notices."])
        self.gsc = [GSCQueryRow("late payment reminder email", f"{BASE}/reminders", 10, 900, 0.01, 14.0)]

    def test_without_search_console_the_link_is_not_found(self):
        # "overdue" alone is one topic word: not enough evidence.
        _, report = self.run_pages([self.source, self.target])
        self.assertEqual(report.results, [])
        self.assertEqual(report.page2_opportunities, [])

    def test_page2_query_makes_the_link_and_flags_it(self):
        # Trailing slash differences between GSC and the crawl are normalized.
        _, report = self.run_pages([self.source, self.target], gsc=self.gsc)
        (result,) = report.results
        self.assertEqual((result.target_url, result.anchor_text), (self.target.url, "late payment reminder email"))
        self.assertEqual((result.page2_query, result.page2_impressions), ("late payment reminder email", 900))
        self.assertEqual(report.page2_pages_boosted, {self.target.url})

    def test_queries_outside_the_site_thresholds_are_ignored(self):
        optimizer = LinkingOptimizer(thresholds=Thresholds(min_impressions=1000))
        _, report = self.run_pages([self.source, self.target], optimizer=optimizer, gsc=self.gsc)
        self.assertEqual(report.results, [])

    def test_page2_links_are_listed_first(self):
        other = _page("/guides/overdue", "Overdue Accounts Guide", ["x"])
        source = _page("/blog/a", "A", [
            "Read the overdue accounts guide first.",
            "Then send a late payment reminder email.",
        ])
        _, report = self.run_pages([source, other, self.target], gsc=self.gsc)
        self.assertEqual([r.target_url for r in report.results], [self.target.url, other.url])


class TestRunBookkeeping(OptimizerTestCase):
    def test_link_rules_come_from_site_config(self):
        money = _page("/pricing", "Pricing", ["Start with our payroll tax deadlines checklist."])
        support = _page("/blog/deadlines", "Payroll Tax Deadlines", ["x"])
        taxonomy = SiteTaxonomy(money_pages=["/pricing"])
        forbid, _ = self.run_pages([money, support], LinkingOptimizer.from_config(SiteConfig(taxonomy=taxonomy)))
        self.assertEqual(forbid.explain_link(money.url, support.url).reason, REASON_ROLE_RULE)
        allow, report = self.run_pages(
            [money, support],
            LinkingOptimizer.from_config(SiteConfig(taxonomy=taxonomy, link_rules=LinkRules("allow"))),
        )
        self.assertEqual([r.target_url for r in report.results], [support.url])

    def test_decisions_are_counted_and_baseline_is_kept(self):
        a = _page("/a", "Alpha Guide", ["Read the beta widgets manual."], links=[f"{BASE}/c"])
        b = _page("/b", "Beta Widgets Manual", ["Nothing here."])
        c = _page("/c", "Gamma", ["Nothing."])
        optimizer, report = self.run_pages([a, b, c])
        self.assertEqual(sum(report.decisions_by_reason.values()), 6)  # 3 pages -> 6 ordered pairs
        self.assertEqual(report.decisions_by_reason[REASON_APPROVED], report.links_approved)
        self.assertTrue(optimizer.link_graph.has_link(a.url, b.url))
        self.assertFalse(optimizer.baseline_graph.has_link(a.url, b.url))
        self.assertTrue(optimizer.baseline_graph.has_link(a.url, c.url))


if __name__ == "__main__":
    unittest.main()
