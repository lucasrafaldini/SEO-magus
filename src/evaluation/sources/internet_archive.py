"""
Internet Archive items through the advancedsearch API (archive.org/advancedsearch.php).

Ground truth layers:
  labels       the collection an item was sampled from (primary), then its other
               collections and its subject keywords - assigned by archivists/uploaders
  popularity   downloads counter
  links        links inside descriptions to other items of the sample (sparse:
               archive items are catalogue records, not articles)

Sampling: equal shares per seed collection (label-stratified). Within a
collection, pages of results are drawn at random in identifier order, never
sorted by downloads: sampling only the most downloaded items would restrict
the range of the popularity variable and bias the ranking correlation.
"""

import random
import re
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlparse

from src.evaluation.corpus import Corpus, Document, GoldLink, Provenance
from src.evaluation.sources.http import HttpJsonClient
from src.evaluation.sources.prose import extract_prose
from src.log import get_logger

logger = get_logger(__name__)

SEARCH = "https://archive.org/advancedsearch.php"
FIELDS = ("identifier", "title", "description", "subject", "collection", "downloads", "mediatype")
ROWS = 100
_BREAKS_RE = re.compile(r"(?:\s*<br\s*/?>\s*){2,}|\n\s*\n", re.I)


def item_url(identifier: str) -> str:
    return f"https://archive.org/details/{identifier}"


def identifier_from_href(href: str) -> Optional[str]:
    parsed = urlparse(href)
    if parsed.netloc not in ("archive.org", "www.archive.org") or not parsed.path.startswith("/details/"):
        return None
    identifier = parsed.path[len("/details/"):].split("/", 1)[0]
    return identifier or None


def _as_list(value) -> List[str]:
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def description_html(value) -> str:
    """Descriptions are free HTML or plain text: make paragraphs explicit for the prose extractor."""
    text = "\n\n".join(_as_list(value))
    if "<p" in text.lower():
        return text
    return "".join(f"<p>{part}</p>" for part in _BREAKS_RE.split(text) if part.strip())


class InternetArchiveSource:
    def __init__(self, client: HttpJsonClient):
        self.client = client

    def _search(self, query: str, rows: int, page: int) -> dict:
        params = [("q", query), ("rows", rows), ("page", page), ("output", "json"), ("sort[]", "identifier asc")]
        params += [("fl[]", f) for f in FIELDS]
        return self.client.get_json(SEARCH, params)["response"]

    def sample_collection(self, collection: str, count: int, rng: random.Random,
                          mediatype: Optional[str] = None) -> List[dict]:
        query = f"collection:({collection})" + (f" AND mediatype:({mediatype})" if mediatype else "")
        total = self._search(query, 1, 1).get("numFound", 0)
        pages = list(range(1, max(1, -(-total // ROWS)) + 1))
        rng.shuffle(pages)
        items: List[dict] = []
        for page in pages:
            items += self._search(query, ROWS, page).get("docs", [])
            if len(items) >= count * 2:
                break
        rng.shuffle(items)
        return items[:count]

    def build(self, name: str, collections: Sequence[str], limit: int = 500, seed: int = 0,
              mediatype: Optional[str] = None) -> Corpus:
        rng = random.Random(seed)
        share = max(1, limit // len(collections))
        records: Dict[str, dict] = {}
        primary: Dict[str, str] = {}
        for collection in collections:
            for item in self.sample_collection(collection, share, rng, mediatype):
                identifier = item.get("identifier")
                if identifier and identifier not in records:
                    records[identifier] = item
                    primary[identifier] = collection
            logger.info("Internet Archive: %d items after collection %s", len(records), collection)
        documents = []
        for identifier, item in records.items():
            url = item_url(identifier)
            paragraphs, links = extract_prose(description_html(item.get("description")), url)
            gold = [GoldLink(item_url(target), link.anchor, link.paragraph)
                    for link in links for target in [identifier_from_href(link.href)] if target]
            others = [c for c in _as_list(item.get("collection")) if c != primary[identifier]]
            labels = [primary[identifier]] + others + [f"subject:{s.strip()}" for s in _as_list(item.get("subject"))]
            downloads = item.get("downloads")
            title = " ".join(_as_list(item.get("title"))) or identifier
            documents.append(Document(url, title, paragraphs or [title], gold, [], labels,
                                      float(downloads) if downloads is not None else None,
                                      {"identifier": identifier, "mediatype": item.get("mediatype")}))
        provenance = Provenance("internet_archive", "advancedsearch", query=", ".join(collections),
                                snapshot="archive.org live", license="per item (see each item's rights)",
                                notes=f"limit {limit}, seed {seed}, mediatype {mediatype or 'any'}")
        return Corpus(name, documents, provenance).closed()
