"""Demo pages of an email marketing software site (used by `audit` without --url)."""

from typing import List

from src.connectors.crawling.html_extract import ParsedPage


def sample_site_pages() -> List[ParsedPage]:
    """Sample pages demonstrating the email marketing software site scenario."""
    return [
        ParsedPage(
            url="https://example.com/blog/welcome-email-template",
            title="Welcome Email Template & 5 Examples",
            h1="How to Write Your First Welcome Email",
            paragraphs=[
                "When a new subscriber signs up for your list, the welcome email sets expectations. Use this simple template to introduce your brand.",
                "Once you have nailed your subject line, you need to set up a sequence of 3 to 5 emails to nurture leads over their first two weeks.",
                "You can send this sequence automatically with our email automation software whenever someone fills out a form.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://example.com/blog/welcome-sequence-guide",
            title="The Complete Guide to Automated Welcome Sequences",
            h1="Building Multi-Step Welcome Sequences That Convert",
            paragraphs=[
                "A welcome sequence goes beyond the initial greeting. It is an automated journey designed to onboard new users step by step.",
                "If you haven't written the first email yet, check out our welcome email template before setting up your timing rules.",
                "Combine this with domain authentication so that your automated emails never land in the spam folder.",
            ],
            existing_internal_links=["https://example.com/blog/welcome-email-template"],
        ),
        ParsedPage(
            url="https://example.com/guides/email-marketing-mastery",
            title="Email Marketing Mastery: The Definitive Pillar Guide",
            h1="The Ultimate Email Marketing Guide",
            paragraphs=[
                "Email marketing remains the highest ROI channel for digital businesses. This comprehensive guide covers list building, sequencing, and segmentation.",
                "To start engaging new signups, create a dedicated welcome sequence that introduces your core product benefits.",
                "Make sure your sending reputation is protected with proper DKIM and SPF domain authentication records.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://example.com/pricing",
            title="Email Automation Software Pricing & Plans",
            h1="Choose the Right Plan for Your Business",
            paragraphs=[
                "All plans include unlimited automated welcome sequences, subscriber tagging, and high deliverability servers.",
            ],
            existing_internal_links=[],
        ),
    ]


DEMO_START = "https://example.com/guides/email-marketing-mastery"
_NAVIGATION = (("https://example.com/guides/email-marketing-mastery", "Guide"), ("https://example.com/pricing", "Pricing"))


def sample_crawl():
    """
    The demo pages as a crawler would record them, so the demo runs the site audit too:
    one content link (the sequence guide cites the welcome email template), a header
    navigation to the guide and pricing on every page, one <h1> each, no meta
    descriptions, every page in the sitemap. The guide is the start page.
    """
    from dataclasses import replace

    from src.connectors.crawling.crawler import CrawlResult
    from src.connectors.crawling.html_extract import LOCATION_CONTENT, LOCATION_NAVIGATION, PageLink

    pages = []
    for page in sample_site_pages():
        links = [PageLink(url, anchor, LOCATION_NAVIGATION, True) for url, anchor in _NAVIGATION if url != page.url]
        for target in page.existing_internal_links:
            anchor = "welcome email template" if target.endswith("welcome-email-template") else target.rsplit("/", 1)[-1]
            links.append(PageLink(target, anchor, LOCATION_CONTENT, True))
        pages.append(replace(page, links=links, h1_count=1, depth=0 if page.url == DEMO_START else None))
    urls = [page.url for page in pages]
    return CrawlResult(start_url=DEMO_START, pages=pages, sitemap_urls=urls, sitemap_found=True,
                       statuses={url: 200 for url in urls}, redirects={}, robots_blocked=[])
