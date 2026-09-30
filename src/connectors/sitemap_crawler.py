"""
Sitemap and Content Crawler.

Extracts pages, titles, headers, body paragraphs, and outgoing internal links.
Can crawl live XML sitemaps or work from a local cache/mock site.
Zero-external-dependency capable (falls back to html.parser if bs4 is missing).
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, List, Set
from urllib.parse import urljoin, urlparse

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


@dataclass
class ParsedPage:
    url: str
    title: str
    h1: str
    paragraphs: List[str]
    existing_internal_links: List[str] = field(default_factory=list)
    meta_description: str = ""


class SimpleHTMLBodyExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.title = ""
        self.h1 = ""
        self.paragraphs: List[str] = []
        self.internal_links: Set[str] = set()

        self._in_title = False
        self._in_h1 = False
        self._in_p = False
        self._skip_tag = False
        self._current_text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in ["script", "style", "nav", "header", "footer"]:
            self._skip_tag = True
            return

        if self._skip_tag:
            return

        if tag == "title":
            self._in_title = True
        elif tag == "h1" and not self.h1:
            self._in_h1 = True
        elif tag == "p":
            self._in_p = True
            self._current_text = []
        elif tag == "a" and "href" in attrs_dict:
            href = attrs_dict["href"]
            full_url = urljoin(self.base_url, href)
            if urlparse(full_url).netloc == self.domain and full_url != self.base_url:
                self.internal_links.add(full_url)

    def handle_endtag(self, tag):
        if tag in ["script", "style", "nav", "header", "footer"]:
            self._skip_tag = False
            return

        if self._skip_tag:
            return

        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "p":
            self._in_p = False
            text = "".join(self._current_text).strip()
            if len(text) > 25:
                self.paragraphs.append(text)
            self._current_text = []

    def handle_data(self, data):
        if self._skip_tag:
            return
        if self._in_title:
            self.title += data.strip()
        elif self._in_h1:
            self.h1 += data.strip()
        elif self._in_p:
            self._current_text.append(data)


class SitemapCrawler:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc

    def parse_html(self, url: str, html_content: str) -> ParsedPage:
        """Parses raw HTML into a structured ParsedPage object."""
        if HAS_BS4:
            soup = BeautifulSoup(html_content, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            h1_tag = soup.find("h1")
            h1 = h1_tag.get_text(strip=True) if h1_tag else ""

            for ignored in soup(["nav", "header", "footer", "script", "style"]):
                ignored.decompose()

            paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 25]

            internal_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                full_url = urljoin(url, href)
                if urlparse(full_url).netloc == self.domain and full_url != url:
                    internal_links.append(full_url)

            return ParsedPage(
                url=url,
                title=title,
                h1=h1,
                paragraphs=paragraphs,
                existing_internal_links=list(set(internal_links)),
            )
        else:
            parser = SimpleHTMLBodyExtractor(url)
            parser.feed(html_content)
            return ParsedPage(
                url=url,
                title=parser.title,
                h1=parser.h1,
                paragraphs=parser.paragraphs,
                existing_internal_links=list(parser.internal_links),
            )

    @classmethod
    def get_sample_site_pages(cls) -> List[ParsedPage]:
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
