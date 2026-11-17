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
from src.workflows.linking_optimizer import (
    REASON_APPROVED, REASON_ROLE_RULE, REASON_SELF_LINK, REASON_UNKNOWN_PAGE, LinkingOptimizer,
)

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

    def test_explain_link_for_pairs_outside_the_run(self):
        a = _page("/a", "Alpha Guide", ["Read the beta widgets manual."])
        b = _page("/b", "Beta Widgets Manual", ["Nothing here."])
        optimizer, _ = self.run_pages([a, b])
        approved = optimizer.explain_link(a.url, b.url)
        self.assertTrue(approved.approved)
        unknown = optimizer.explain_link(a.url, f"{BASE}/never-crawled")
        self.assertEqual((unknown.reason, unknown.approved), (REASON_UNKNOWN_PAGE, False))
        self.assertIn("/never-crawled was not in the crawled pages", unknown.detail)
        self.assertEqual(optimizer.explain_link(f"{BASE}/ghost", b.url).detail, f"{BASE}/ghost was not in the crawled pages")
        self.assertEqual(optimizer.explain_link(a.url, a.url).reason, REASON_SELF_LINK)

    def test_legacy_jev_field_names_still_work(self):
        _, report = self.run_pages([_page("/a", "Alpha Guide", ["Read the beta widgets manual."]),
                                    _page("/b", "Beta Widgets Manual", ["Nothing here."])])
        result = report.results[0]
        self.assertEqual((result.jev_relevance_score, result.jev_confidence), (result.relevance_score, result.confidence))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Pruning: skipping pairs that cannot carry an anchor must not change any result
# ---------------------------------------------------------------------------

import random
from collections import Counter

from src.connectors.sitemap_crawler import LOCATION_CONTENT, PageLink
from src.engines.classifiers import HeuristicClassifier, LinkJudgement
from src.workflows.linking_optimizer import REASON_CLASSIFIER_GATE, REASON_NO_ANCHOR, REASON_NO_TOPIC_MENTION

VOCABULARY = ("compost soil garden tomato seed water bin worm mulch pepper bed raised pest organic harvest "
              "pruning season frost greenhouse irrigation").split()
FILLER = "the a of in for with and to".split()
_OPTIMIZER_LOGGER = "seo_magus.workflows.linking_optimizer"


def random_site(seed: int, size: int = 14):
    """A random site exercising every gate: clusters + affinities, roles, noindex, existing links, page 2 queries."""
    rng = random.Random(seed)
    folders = ("a", "b", "c")
    titles = [" ".join(rng.sample(VOCABULARY, rng.choice((2, 2, 3)))).title() for _ in range(size)]
    urls = [f"{BASE}/{rng.choice(folders)}/p{i}" for i in range(size)]
    pages = []
    for i, (url, title) in enumerate(zip(urls, titles)):
        paragraphs = []
        for _ in range(rng.randint(1, 4)):
            words = [rng.choice(VOCABULARY + FILLER) for _ in range(rng.randint(6, 14))]
            if rng.random() < 0.6:                     # name another page's topic, sometimes partially
                other = titles[rng.randrange(size)].lower().split()
                words[rng.randrange(len(words)):0] = other if rng.random() < 0.7 else other[:1]
            paragraphs.append(" ".join(words).capitalize() + ".")
        existing = rng.sample([u for u in urls if u != url], rng.randint(0, 2))
        links = [PageLink(target, titles[urls.index(target)].lower(), LOCATION_CONTENT, True) for target in existing]
        robots = "noindex" if rng.random() < 0.1 else ""
        pages.append(ParsedPage(url, title, title if rng.random() < 0.8 else "", paragraphs, existing,
                                links=links, meta_robots=robots))
    taxonomy = SiteTaxonomy(
        pillars=[urls[0][len(BASE):]], money_pages=[urls[1][len(BASE):], urls[2][len(BASE):]],
        clusters={"a": ["/a/"], "b": ["/b/"]} if seed % 3 else {},
        cluster_affinities={"a": ["b"]} if seed % 3 == 1 else {},
    )
    gsc = [GSCQueryRow(" ".join(rng.sample(VOCABULARY, 2)), rng.choice(urls), 1, 500, 0.01, 14.0)
           for _ in range(3)]
    rules = LinkRules(("forbid", "same_cluster", "allow")[seed % 3])
    return pages, taxonomy, gsc, rules


class TestPruningIsLossless(OptimizerTestCase):
    SEEDS = range(40)

    def _run(self, pages, taxonomy, gsc, rules, prune, debug=False):
        optimizer = LinkingOptimizer(classifier=HeuristicClassifier(), taxonomy=taxonomy, link_rules=rules, prune=prune)
        if debug:   # -vv: every pair is evaluated (and logged) one by one
            with self.assertLogs(_OPTIMIZER_LOGGER, "DEBUG"):
                return self.run_pages(pages, optimizer, gsc)
        return self.run_pages(pages, optimizer, gsc)

    @staticmethod
    def _links(report):
        return [(r.source_url, r.target_url, r.anchor_text, r.updated_sentence, r.relevance_score, r.confidence,
                 r.page2_query) for r in report.results]

    def test_same_links_fewer_classifier_calls_on_random_sites(self):
        pruned_calls = brute_calls = 0
        for seed in self.SEEDS:
            site = random_site(seed)
            with self.subTest(seed=seed):
                _, brute = self._run(*site, prune=False)
                _, pruned = self._run(*site, prune=True)
                self.assertEqual(self._links(pruned), self._links(brute))
                self.assertLessEqual(pruned.candidate_pairs_checked, brute.candidate_pairs_checked)
                # Pairs refused for lack of a topic mention were classifier-gate or no-anchor refusals before.
                moved = {REASON_NO_TOPIC_MENTION, REASON_CLASSIFIER_GATE, REASON_NO_ANCHOR}
                before, after = Counter(brute.decisions_by_reason), Counter(pruned.decisions_by_reason)
                self.assertEqual({k: v for k, v in after.items() if k not in moved},
                                 {k: v for k, v in before.items() if k not in moved})
                self.assertEqual(sum(after[k] for k in moved), sum(before[k] for k in moved))
                self.assertEqual(sum(after.values()), len(site[0]) * (len(site[0]) - 1))
                pruned_calls += pruned.candidate_pairs_checked
                brute_calls += brute.candidate_pairs_checked
        self.assertLess(pruned_calls, brute_calls / 2)   # the point of pruning

    def test_grouped_counting_equals_pair_by_pair_evaluation(self):
        for seed in self.SEEDS:
            site = random_site(seed)
            with self.subTest(seed=seed):
                _, grouped = self._run(*site, prune=True)
                optimizer, one_by_one = self._run(*site, prune=True, debug=True)
                self.assertEqual(grouped.decisions_by_reason, one_by_one.decisions_by_reason)
                self.assertEqual(self._links(grouped), self._links(one_by_one))
                self.assertEqual(grouped.candidate_pairs_checked, one_by_one.candidate_pairs_checked)

    def test_explanations_agree_with_the_run(self):
        pages, taxonomy, gsc, rules = random_site(7)
        optimizer, report = self._run(pages, taxonomy, gsc, rules, prune=True)
        explained = Counter(optimizer.explain_link(s.url, t.url).reason for s in pages for t in pages if s is not t)
        self.assertEqual(explained, Counter(report.decisions_by_reason))

    def test_the_classifier_still_decides_pairs_that_can_carry_an_anchor(self):
        class Refusing(HeuristicClassifier):
            def evaluate(self, candidate):
                return LinkJudgement(False, 0.99, 1.0, "refusing")

        source = _page("/a", "Alpha Guide", ["Read the beta widgets manual today."])
        target = _page("/b", "Beta Widgets Manual", ["Nothing here."])
        optimizer = LinkingOptimizer(classifier=Refusing())
        optimizer, report = self.run_pages([source, target], optimizer)
        decision = optimizer.explain_link(source.url, target.url)
        self.assertEqual((decision.reason, decision.paragraphs_evaluated), (REASON_CLASSIFIER_GATE, 1))
        pre_checked = optimizer.explain_link(target.url, source.url)
        self.assertEqual((pre_checked.reason, pre_checked.paragraphs_evaluated), (REASON_NO_TOPIC_MENTION, 0))
        self.assertEqual(REASON_NO_TOPIC_MENTION, REASON_CLASSIFIER_GATE)      # one vocabulary for users
        self.assertIn("classifier not called", pre_checked.detail)
        self.assertEqual(report.candidate_pairs_checked, 1)

    def test_custom_anchor_engines_are_never_pruned(self):
        class OpaqueEngine:   # no may_anchor(): its anchor rule is unknown, so every pair is evaluated
            min_anchor_words = 2

            def craft_link_insertion(self, **kwargs):
                return None

        self.assertFalse(LinkingOptimizer(auxiliary_ai=OpaqueEngine()).prune)
        self.assertTrue(LinkingOptimizer().prune)
        self.assertFalse(LinkingOptimizer(prune=False).prune)


class TestSourcesSubset(OptimizerTestCase):
    def test_only_selected_sources_get_proposals_and_decisions(self):
        for seed in range(10):
            pages, taxonomy, gsc, rules = random_site(seed)
            chosen = {pages[3].url, pages[5].url}
            with self.subTest(seed=seed):
                full = LinkingOptimizer(classifier=HeuristicClassifier(), taxonomy=taxonomy, link_rules=rules)
                _, everything = self.run_pages(pages, full, gsc)
                part = LinkingOptimizer(classifier=HeuristicClassifier(), taxonomy=taxonomy, link_rules=rules)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    subset = part.run_optimization(pages, gsc, sources=chosen)
                expected = [r for r in everything.results if r.source_url in chosen]
                self.assertEqual([(r.source_url, r.target_url, r.anchor_text) for r in subset.results],
                                 [(r.source_url, r.target_url, r.anchor_text) for r in expected])
                self.assertEqual(sum(subset.decisions_by_reason.values()), len(chosen) * (len(pages) - 1))


class TestWordLookups(unittest.TestCase):
    """Words.names() and TopicIndex must agree exactly with tokens_match() (they replace pairwise loops)."""

    def test_agree_with_tokens_match_on_random_words(self):
        from src.engines.text import tokens_match
        from src.workflows.linking_optimizer import TopicIndex, Words
        rng = random.Random(3)
        alphabet = "abcde"      # tiny alphabet: many prefix relations, the hard case
        for _ in range(300):
            words = {"".join(rng.choice(alphabet) for _ in range(rng.randint(1, 7))) for _ in range(rng.randint(1, 12))}
            terms = {"".join(rng.choice(alphabet) for _ in range(rng.randint(1, 7))) for _ in range(rng.randint(1, 6))}
            prepared = Words(words)
            for term in terms:
                self.assertEqual(prepared.names(term), any(tokens_match(w, term) for w in words), (term, words))
            index = TopicIndex()
            index.add(0, terms)
            expected = {t for t in terms if any(tokens_match(w, t) for w in words)}
            self.assertEqual(index.freeze().terms_named_by(words), expected, (terms, words))


class TestPruningContract(OptimizerTestCase):
    def test_engines_can_opt_out_of_pruning(self):
        from src.engines.auxiliary_ai import AuxiliaryAIEngine

        class SynonymEngine(AuxiliaryAIEngine):
            may_anchor = None                     # anchors may not name the topic: never prune

        self.assertFalse(LinkingOptimizer(auxiliary_ai=SynonymEngine()).prune)
        self.assertTrue(LinkingOptimizer(auxiliary_ai=AuxiliaryAIEngine()).prune)
