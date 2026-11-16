"""
HTML extraction: one pass over a page with the standard-library parser.

Captures title, meta description, meta robots, canonical, lang, every <h1>,
body paragraphs (outside nav/header/footer/aside, text joined with correct
spacing) and every link with its anchor text, location ("content" or
"navigation") and rel=nofollow.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from src.connectors.crawling.urls import normalize_url

MIN_PARAGRAPH_CHARS = 25
LOCATION_CONTENT = "content"
LOCATION_NAVIGATION = "navigation"

_BOILERPLATE_TAGS = {"nav", "header", "footer", "aside"}
_SKIPPED_TAGS = {"script", "style", "noscript", "template", "svg"}
# Block-level tags that implicitly close an open <p> (HTML parsing rules).
_CLOSES_P = {
    "p", "div", "ul", "ol", "dl", "table", "section", "article", "aside", "header", "footer", "nav",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "form", "hr", "figure", "main",
}
_WHITESPACE_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _unique(items) -> List[str]:
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


@dataclass
class PageLink:
    url: str                      # absolute, normalized, as written on the page
    anchor_text: str
    location: str                 # LOCATION_CONTENT or LOCATION_NAVIGATION
    internal: bool
    final_url: str = ""           # after redirects (set by the crawler)
    nofollow: bool = False        # rel="nofollow" (or ugc / sponsored)

    @property
    def target(self) -> str:
        return self.final_url or self.url


@dataclass
class ParsedPage:
    url: str
    title: str
    h1: str
    paragraphs: List[str]
    existing_internal_links: List[str] = field(default_factory=list)  # content links only
    meta_description: str = ""
    links: List[PageLink] = field(default_factory=list)                # every link, with anchors
    h1_count: Optional[int] = None                                     # None: not parsed from HTML
    canonical: str = ""
    status: int = 200
    meta_robots: str = ""          # meta robots + X-Robots-Tag, lower-case, e.g. "noindex, follow"
    lang: str = ""
    depth: Optional[int] = None    # clicks from the crawl start page (None: only found via the sitemap)
    response_ms: float = 0.0
    content_bytes: int = 0

    @property
    def navigation_links(self) -> List[str]:
        return _unique(
            l.target for l in self.links
            if l.internal and l.location == LOCATION_NAVIGATION and l.target != self.url
        )

    @property
    def content_anchor_texts(self) -> List[str]:
        return [l.anchor_text for l in self.links if l.location == LOCATION_CONTENT and l.anchor_text]

    @property
    def noindex(self) -> bool:
        return "noindex" in self.meta_robots or "none" in self.meta_robots.replace(" ", "").split(",")

    @property
    def nofollow(self) -> bool:
        return "nofollow" in self.meta_robots or "none" in self.meta_robots.replace(" ", "").split(",")

    @property
    def canonicalized(self) -> bool:
        """The page declares another URL as its canonical version (it is a duplicate)."""
        return bool(self.canonical) and self.canonical != self.url

    @property
    def indexable(self) -> bool:
        """Can this page rank? (HTTP 200, no noindex, canonical to itself or absent)."""
        return self.status == 200 and not self.noindex and not self.canonicalized


class HtmlPageExtractor(HTMLParser):
    """Single-pass extractor of the SEO-relevant parts of an HTML page."""

    def __init__(self, url: str, normalizer: Callable[[str], str] = normalize_url):
        super().__init__(convert_charrefs=True)
        self.normalize = normalizer
        self.url = normalizer(url)
        self.base = self.url
        self.host = urlparse(self.url).netloc
        self.title_parts: List[str] = []
        self.meta_description = ""
        self.meta_robots: List[str] = []
        self.canonical = ""
        self.lang = ""
        self.h1s: List[str] = []
        self.paragraphs: List[str] = []
        self.links: List[PageLink] = []
        self._open: List[str] = []          # boilerplate / skipped ancestors
        self._in_title = False
        self._h1: Optional[List[str]] = None
        self._p: Optional[List[str]] = None
        self._a: Optional[Tuple[dict, List[str]]] = None

    @property
    def _skipping(self) -> bool:
        return any(tag in _SKIPPED_TAGS for tag in self._open)

    @property
    def _in_boilerplate(self) -> bool:
        return any(tag in _BOILERPLATE_TAGS for tag in self._open)

    def _close_p(self):
        if self._p is not None:
            text = _clean("".join(self._p))
            if len(text) > MIN_PARAGRAPH_CHARS and not self._in_boilerplate:
                self.paragraphs.append(text)
            self._p = None

    def handle_starttag(self, tag, attrs):
        attrs = {k: (v or "") for k, v in attrs}
        if tag in _CLOSES_P:
            self._close_p()
        if tag in _SKIPPED_TAGS or tag in _BOILERPLATE_TAGS:
            self._open.append(tag)
            return
        if self._skipping:
            return
        if tag == "html" and attrs.get("lang"):
            self.lang = attrs["lang"].strip().lower()
        elif tag == "base" and attrs.get("href"):
            self.base = urljoin(self.url, attrs["href"])
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = attrs.get("name", "").lower()
            if name == "description":
                self.meta_description = _clean(attrs.get("content", ""))
            elif name in ("robots", "googlebot"):
                self.meta_robots.append(_clean(attrs.get("content", "")).lower())
        elif tag == "link" and "canonical" in attrs.get("rel", "").lower().split():
            self.canonical = self.normalize(urljoin(self.base, attrs.get("href", "")))
        elif tag == "h1":
            self._h1 = []
        elif tag == "p":
            self._p = []
        elif tag == "a" and attrs.get("href"):
            self._a = (attrs, [])
        elif tag == "img" and self._a is not None and attrs.get("alt"):
            self._a[1].append(" " + attrs["alt"] + " ")
        elif tag == "br":
            self.handle_data(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in _SKIPPED_TAGS or tag in _BOILERPLATE_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in _SKIPPED_TAGS or tag in _BOILERPLATE_TAGS:
            if tag in self._open:
                while self._open:
                    if self._open.pop() == tag:
                        break
            return
        if self._skipping:
            return
        if tag == "title":
            self._in_title = False
        elif tag == "h1" and self._h1 is not None:
            self.h1s.append(_clean("".join(self._h1)))
            self._h1 = None
        elif tag == "p":
            self._close_p()
        elif tag == "a" and self._a is not None:
            attrs, parts = self._a
            self._a = None
            self._add_link(attrs, _clean("".join(parts)))

    def handle_data(self, data):
        if self._skipping:
            return
        if self._in_title:
            self.title_parts.append(data)
        if self._h1 is not None:
            self._h1.append(data)
        if self._p is not None:
            self._p.append(data)
        if self._a is not None:
            self._a[1].append(data)

    def _add_link(self, attrs: dict, anchor_text: str):
        href = attrs["href"].strip()
        if href.lower().startswith(("mailto:", "tel:", "javascript:", "data:", "sms:", "ftp:")):
            return
        url = self.normalize(urljoin(self.base, href))
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or url == self.url:
            return  # non-web scheme or link to the page itself (e.g. "#top")
        rel = set(attrs.get("rel", "").lower().split())
        self.links.append(PageLink(
            url=url,
            anchor_text=anchor_text,
            location=LOCATION_NAVIGATION if self._in_boilerplate else LOCATION_CONTENT,
            internal=parsed.netloc == self.host,
            nofollow=bool(rel & {"nofollow", "ugc", "sponsored"}),
        ))

    def close(self):
        super().close()
        self._close_p()

    def page(self, status: int = 200, extra_robots: str = "") -> ParsedPage:
        self.close()
        robots = ", ".join(r for r in self.meta_robots + [extra_robots.lower().strip()] if r)
        return ParsedPage(
            url=self.url,
            title=_clean("".join(self.title_parts)),
            h1=self.h1s[0] if self.h1s else "",
            paragraphs=self.paragraphs,
            existing_internal_links=_unique(
                l.url for l in self.links if l.internal and l.location == LOCATION_CONTENT
            ),
            meta_description=self.meta_description,
            links=self.links,
            h1_count=len(self.h1s),
            canonical=self.canonical,
            status=status,
            meta_robots=robots,
            lang=self.lang,
        )


def parse_html_page(url: str, html_content: str, status: int = 200, x_robots_tag: str = "",
                    normalizer: Callable[[str], str] = normalize_url) -> ParsedPage:
    extractor = HtmlPageExtractor(url, normalizer)
    extractor.feed(html_content)
    return extractor.page(status, x_robots_tag)
