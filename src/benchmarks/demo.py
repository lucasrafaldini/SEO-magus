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
