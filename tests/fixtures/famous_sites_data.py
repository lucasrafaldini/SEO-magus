"""
Compatibility path for the original famous-sites benchmark tests
(tests/test_famous_sites.py). The fixtures live in src/benchmarks/famous_sites.py.
"""

from src.benchmarks.famous_sites import get_github_pages, get_mailchimp_pages, get_shopify_pages, get_stripe_pages

__all__ = ["get_github_pages", "get_mailchimp_pages", "get_shopify_pages", "get_stripe_pages"]
