"""
Any website (or a local mirror, e.g. a Kiwix-served Wikipedia) as an evaluation
corpus, through SEO-Magus's own crawler.

  links        the site's existing in-prose content links (anchor found in a
               paragraph); this is the link-recovery ground truth
  extra_links  its other content links (lists, tables, cards)
  labels       none: deriving labels from URL folders would make the URL-based
               classifier look right by construction; attach labels from an
               independent source if you have them
  popularity   none by default (attach analytics or Search Console data)

Also converts a saved crawl (--save-crawl / CrawlResult.save) without network.
"""

from typing import Optional

from src.connectors.sitemap_crawler import LOCATION_CONTENT, CrawlConfig, CrawlResult, SitemapCrawler
from src.evaluation.corpus import Corpus, Document, GoldLink, Provenance


def from_crawl(crawl: CrawlResult, name: str, method: str = "saved-crawl") -> Corpus:
    documents = []
    for page in crawl.pages:
        if not page.indexable:
            continue
        gold, other = [], []
        for link in page.links:
            if not link.internal or link.location != LOCATION_CONTENT or not link.anchor_text:
                continue
            paragraph = next((i for i, text in enumerate(page.paragraphs) if link.anchor_text in text), -1)
            if paragraph >= 0:
                gold.append(GoldLink(link.target, link.anchor_text, paragraph))
            else:
                other.append(link.target)
        documents.append(Document(page.url, page.title or page.h1 or page.url, list(page.paragraphs), gold,
                                  list(dict.fromkeys(other)), [], None, {"depth": page.depth}))
    provenance = Provenance("crawl", method, query=crawl.start_url, snapshot=f"{len(crawl.pages)} pages crawled",
                            notes="ground truth = the site's own in-prose links")
    return Corpus(name, documents, provenance).closed()


def crawl_site(url: str, name: str, max_pages: int = 500, config: Optional[CrawlConfig] = None) -> Corpus:
    config = (config or CrawlConfig()).with_overrides(max_pages=max_pages)
    return from_crawl(SitemapCrawler(url, config=config).crawl(), name, method="http-crawl")
