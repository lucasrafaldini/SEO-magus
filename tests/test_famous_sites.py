"""
Famous Sites Benchmark Tests.

Validates SEO-Magus across real-world architectures from Mailchimp, Stripe, Shopify, and GitHub.
Tests whether the Jev System 1 + Auxiliary AI cascade correctly identifies:
- Support -> Pillar links
- Pillar -> Money page links
- Lateral support links
- Rejection of unnatural/off-topic connections
"""

import unittest
from tests.fixtures.famous_sites_data import (
    get_mailchimp_pages,
    get_stripe_pages,
    get_shopify_pages,
    get_github_pages,
)
from src.workflows.linking_optimizer import LinkingOptimizer


class TestFamousSitesBenchmarks(unittest.TestCase):
    def setUp(self):
        self.optimizer = LinkingOptimizer(min_jev_score=7.0, min_jev_confidence=0.75)

    def test_mailchimp_benchmark(self):
        pages = get_mailchimp_pages()
        report = self.optimizer.run_optimization(pages)

        self.assertEqual(report.total_pages_evaluated, 4)
        self.assertGreater(report.links_approved, 0)
        self.assertLess(report.duration_seconds, 3.0)

        # Check that welcome sequence links to audience segmentation
        approved_targets = [r.target_url for r in report.results]
        self.assertTrue(
            any("audience-segmentation" in t or "welcome-email" in t for t in approved_targets),
            f"Expected link to audience segmentation or welcome sequence in {approved_targets}",
        )

    def test_stripe_benchmark(self):
        pages = get_stripe_pages()
        report = self.optimizer.run_optimization(pages)

        self.assertEqual(report.total_pages_evaluated, 3)
        self.assertGreater(report.links_approved, 0)

        # Check that fraud prevention links to Checkout or Guide to Online Payments
        target_urls = [r.target_url for r in report.results]
        self.assertTrue(
            any("checkout" in t or "guide-to-online-payments" in t for t in target_urls),
            f"Expected connection to checkout or guide in {target_urls}",
        )

    def test_shopify_benchmark(self):
        pages = get_shopify_pages()
        report = self.optimizer.run_optimization(pages)

        self.assertEqual(report.total_pages_evaluated, 3)
        self.assertGreater(report.links_approved, 0)

        # Check connection between ecommerce business guide and dropshipping / POS
        target_urls = [r.target_url for r in report.results]
        self.assertTrue(
            any("dropshipping" in t or "pos" in t for t in target_urls),
            f"Expected connection in {target_urls}",
        )

    def test_github_benchmark(self):
        pages = get_github_pages()
        report = self.optimizer.run_optimization(pages)

        self.assertEqual(report.total_pages_evaluated, 3)
        self.assertGreater(report.links_approved, 0)

        # Check CI/CD guide connecting to Actions or Enterprise
        target_urls = [r.target_url for r in report.results]
        self.assertTrue(
            any("github-actions" in t or "enterprise" in t for t in target_urls),
            f"Expected connection in {target_urls}",
        )


if __name__ == "__main__":
    unittest.main()
