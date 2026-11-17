"""
Crawl fidelity: can SEO-Magus crawl a large site and see it correctly?

The corpus is rendered as a static website (one page per document, its human
links written as real <a> elements in the paragraphs, navigation and footer
around them, robots.txt and an XML sitemap), served on localhost, crawled by
the real crawler over HTTP, and what the crawler extracted is compared with
what was rendered:

  coverage            documents crawled / documents rendered
  title_exact         crawled <title> equals the document title
  paragraphs_exact    crawled paragraphs equal the document paragraphs (text extraction)
  link_recall         rendered in-prose links found as content links
  link_precision      crawled content links that were rendered in-prose links
  navigation_leaks    navigation links misclassified as content links
  pages_per_second    throughput at the configured concurrency - a lower bound: the
                      server runs in the same Python process and shares its CPU (GIL)
"""

import time
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Set, Tuple
from urllib.parse import unquote, urlparse

from src.benchmarks.mock_sites import MockSiteServer
from src.connectors.sitemap_crawler import LOCATION_CONTENT, CrawlConfig, SitemapCrawler
from src.evaluation.corpus import Corpus, Pair

NAV_LINKS = 5


def _key(url: str) -> str:
    return url.rstrip("/")


def _base(corpus: Corpus) -> str:
    hosts = {f"{urlparse(i).scheme}://{urlparse(i).netloc}" for i in corpus.ids}
    if len(hosts) != 1:
        raise ValueError(f"crawl fidelity needs a single-host corpus, got {sorted(hosts)[:3]}")
    return hosts.pop()


def _paragraph_html(text: str, links: List[Tuple[str, str]], rendered: Set[str]) -> str:
    """Wrap the first free occurrence of each anchor in a link; overlapping anchors are skipped."""
    spans: List[Tuple[int, int, str]] = []
    for target, anchor in links:
        start = text.find(anchor)
        while start != -1 and any(start < e and s < start + len(anchor) for s, e, _ in spans):
            start = text.find(anchor, start + 1)
        if start != -1:
            spans.append((start, start + len(anchor), target))
            rendered.add(target)
    out, position = [], 0
    for start, end, target in sorted(spans):
        out.append(escape(text[position:start]))
        out.append(f'<a href="{escape(target)}">{escape(text[start:end])}</a>')
        position = end
    out.append(escape(text[position:]))
    return "".join(out)


def render_site(corpus: Corpus, root: Path) -> Set[Pair]:
    """Write the corpus as a static site under root; returns the in-prose links actually rendered."""
    base = _base(corpus)
    navigation = corpus.ids[:NAV_LINKS]
    nav = "".join(f'<a href="{escape(u)}">{escape(corpus.get(u).title)}</a>' for u in navigation)
    rendered_pairs: Set[Pair] = set()
    for doc in corpus.documents:
        by_paragraph: Dict[int, List[Tuple[str, str]]] = {}
        for link in doc.links:
            by_paragraph.setdefault(link.paragraph, []).append((link.target, link.anchor))
        body = []
        for index, text in enumerate(doc.paragraphs):
            rendered: Set[str] = set()
            body.append(f"<p>{_paragraph_html(text, by_paragraph.get(index, []), rendered)}</p>")
            rendered_pairs |= {(doc.id, t) for t in rendered}
        html = (f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{escape(doc.title)}</title></head><body>"
                f"<header><nav>{nav}</nav></header><main><h1>{escape(doc.title)}</h1>{''.join(body)}</main>"
                f"<footer><a href='{escape(base)}/'>Home</a></footer></body></html>")
        path = root / unquote(urlparse(doc.id).path).strip("/") / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    home = "".join(f'<p><a href="{escape(u)}">{escape(corpus.get(u).title)}</a></p>' for u in navigation)
    (root / "index.html").write_text(f"<html><head><title>Home</title></head><body>{home}</body></html>",
                                     encoding="utf-8")
    (root / "robots.txt").write_text(f"User-agent: *\nDisallow:\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    urls = "".join(f"<url><loc>{escape(_key(i))}/</loc></url>" for i in corpus.ids)
    (root / "sitemap.xml").write_text(
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', encoding="utf-8")
    return rendered_pairs


def crawl_fidelity(corpus: Corpus, concurrency: int = 8) -> dict:
    base = _base(corpus)
    with TemporaryDirectory() as tmp:
        rendered = render_site(corpus, Path(tmp))
        with MockSiteServer("corpus", root=Path(tmp), production_base=base) as server:
            config = CrawlConfig(max_pages=len(corpus) + 10, concurrency=concurrency, timeout=10, retries=1)
            started = time.perf_counter()
            crawl = SitemapCrawler(server.base_url + "/", config=config).crawl()
            elapsed = time.perf_counter() - started
    crawl = crawl.rebase(server.base_url, base)
    pages = {_key(p.url): p for p in crawl.pages}
    ids = {_key(i): i for i in corpus.ids}
    found = [ids[k] for k in pages if k in ids]
    rendered_keys = {(_key(s), _key(t)) for s, t in rendered}
    navigation = {_key(u) for u in corpus.ids[:NAV_LINKS]} | {_key(base)}
    content_links: Set[Pair] = set()
    leaks = 0
    for key, page in pages.items():
        if key not in ids:
            continue
        for link in page.links:
            if link.internal and link.location == LOCATION_CONTENT:
                content_links.add((key, _key(link.target)))
        leaks += sum(1 for link in page.links if link.location == LOCATION_CONTENT and _key(link.target) in navigation
                     and (key, _key(link.target)) not in rendered_keys)
    hits = content_links & rendered_keys
    return {
        "task": "crawl", "documents": len(corpus), "crawled": len(found),
        "coverage": len(found) / len(corpus) if len(corpus) else 0.0,
        "title_exact": sum(pages[_key(i)].title == corpus.get(i).title for i in found) / max(1, len(found)),
        "paragraphs_exact": sum(pages[_key(i)].paragraphs == corpus.get(i).paragraphs for i in found) / max(1, len(found)),
        "link_recall": len(hits) / len(rendered_keys) if rendered_keys else 0.0,
        "link_precision": len(hits) / len(content_links) if content_links else 0.0,
        "navigation_leaks": leaks,
        "rendered_links": len(rendered_keys),
        "seconds": round(elapsed, 2), "pages_per_second": round(len(crawl.pages) / elapsed, 1) if elapsed else 0.0,
        "requests": crawl.requests_made, "concurrency": concurrency,
    }
