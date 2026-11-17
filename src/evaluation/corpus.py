"""
Evaluation corpus: documents plus independent ground-truth layers.

Every source (Wikipedia, Internet Archive, Stack Exchange, a crawled site, a
synthetic generator) is converted into this one format, so every task and
metric runs identically on every source. A corpus carries up to four layers of
human (or planted) ground truth; tasks declare which layers they need and skip
corpora that lack them instead of scoring them as zero:

  links        in-prose links written by people (editor links, answer links),
               with their anchor text and paragraph          -> link recovery
  extra_links  other human links between documents (all wikilinks, "related"
               questions): a looser, independent link layer  -> lenient precision
  labels       human classification (categories, collections, tags),
               primary label first                           -> classification
  popularity   external demand (pageviews, downloads, views) -> ranking relevance
  clickstream  reader navigation between documents (link and non-link
               traffic), independent of the editors          -> reader-validated links

Stored as gzip-compressed JSON lines: a header line (name, provenance,
clickstream) then one document per line. `fingerprint` hashes the content so a
report names exactly the data it was computed on.
"""

import gzip
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

from src.connectors.sitemap_crawler import LOCATION_CONTENT, PageLink, ParsedPage

FORMAT = "seo-magus/corpus"
FORMAT_VERSION = 1
LAYERS = ("links", "extra_links", "labels", "popularity", "clickstream")
Pair = Tuple[str, str]


@dataclass(frozen=True)
class GoldLink:
    target: str          # id of the target document
    anchor: str          # anchor text written by the human
    paragraph: int       # index of the paragraph holding the link (-1: unknown)


@dataclass
class Document:
    id: str                                   # canonical URL
    title: str
    paragraphs: List[str]
    links: List[GoldLink] = field(default_factory=list)
    extra_links: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    popularity: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def link_targets(self) -> List[str]:
        """Distinct gold targets, in order of first appearance."""
        return list(dict.fromkeys(link.target for link in self.links))


@dataclass
class Provenance:
    source: str                    # wikipedia, internet_archive, stackexchange, crawl, synthetic, ...
    method: str                    # access path: "action-api", "dump", "advancedsearch", "http-crawl", ...
    query: str = ""                # what was asked for (seeds, categories, collections, generator spec)
    snapshot: str = ""             # data date / dump name, when the source has one
    license: str = ""
    notes: str = ""
    language: str = ""             # ISO code of the text, "" when unknown / mixed
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


@dataclass
class Corpus:
    name: str
    documents: List[Document]
    provenance: Provenance
    clickstream: Dict[Pair, Dict[str, int]] = field(default_factory=dict)   # (from, to) -> {"link": n, "other": n}

    # ------------------------------------------------------------- access

    def __post_init__(self):
        self._by_id: Dict[str, Document] = {}
        self._reindex()

    def _reindex(self):
        self._by_id = {doc.id: doc for doc in self.documents}
        if len(self._by_id) != len(self.documents):
            raise ValueError(f"corpus {self.name!r} has duplicate document ids")

    def __len__(self) -> int:
        return len(self.documents)

    def __contains__(self, doc_id: str) -> bool:
        return doc_id in self._by_id

    def get(self, doc_id: str) -> Document:
        return self._by_id[doc_id]

    @property
    def ids(self) -> List[str]:
        return [doc.id for doc in self.documents]

    @property
    def layers(self) -> Set[str]:
        """Ground-truth layers present in this corpus."""
        present = set()
        if any(doc.links for doc in self.documents):
            present.add("links")
        if any(doc.extra_links for doc in self.documents):
            present.add("extra_links")
        if any(doc.labels for doc in self.documents):
            present.add("labels")
        if sum(doc.popularity is not None for doc in self.documents) >= 2:
            present.add("popularity")
        if self.clickstream:
            present.add("clickstream")
        return present

    def gold_pairs(self, ids: Optional[Iterable[str]] = None) -> Set[Pair]:
        docs = self.documents if ids is None else [self.get(i) for i in ids]
        return {(doc.id, target) for doc in docs for target in doc.link_targets}

    def closed(self) -> "Corpus":
        """
        Closed world: links and extra links only to documents of this corpus,
        no self-links, clickstream only between corpus documents.
        """
        ids = set(self.ids)
        documents = []
        for doc in self.documents:
            links = [l for l in doc.links if l.target in ids and l.target != doc.id]
            extra = list(dict.fromkeys(t for t in doc.extra_links if t in ids and t != doc.id))
            documents.append(Document(doc.id, doc.title, list(doc.paragraphs), links, extra, list(doc.labels),
                                      doc.popularity, dict(doc.meta)))
        clicks = {pair: dict(n) for pair, n in self.clickstream.items() if pair[0] in ids and pair[1] in ids}
        return Corpus(self.name, documents, self.provenance, clicks)

    def subset(self, ids: Iterable[str], name: Optional[str] = None) -> "Corpus":
        """The documents with these ids (in this order), closed over them."""
        keep = list(dict.fromkeys(ids))
        part = Corpus(name or self.name, [self.get(i) for i in keep], self.provenance, self.clickstream)
        return part.closed()

    # ------------------------------------------------------- to SEO-Magus

    def to_pages(self, remove: Set[Pair] = frozenset()) -> List[ParsedPage]:
        """
        The corpus as the crawled pages SEO-Magus sees. Gold links in `remove` are
        taken out (their anchor words stay in the text, only the link goes), every
        other gold link stays an existing content link with its anchor.
        """
        pages = []
        for doc in self.documents:
            kept = [l for l in doc.links if (doc.id, l.target) not in remove]
            targets = list(dict.fromkeys(l.target for l in kept))
            links = [PageLink(l.target, l.anchor, LOCATION_CONTENT, True) for l in kept]
            pages.append(ParsedPage(doc.id, doc.title, doc.title, list(doc.paragraphs), targets, links=links))
        return pages

    # ------------------------------------------------------------ storage

    def fingerprint(self) -> str:
        """Content hash (cached: corpora are not modified after loading, except by load_clickstream)."""
        cached = getattr(self, "_fingerprint", None)
        if cached is not None:
            return cached
        digest = hashlib.sha256()
        for doc in self.documents:
            digest.update(json.dumps(_doc_dict(doc), sort_keys=True, ensure_ascii=False).encode())
        for pair in sorted(self.clickstream):
            digest.update(json.dumps([pair, self.clickstream[pair]], sort_keys=True).encode())
        self._fingerprint = digest.hexdigest()[:16]
        return self._fingerprint

    def save(self, path: Union[str, Path]) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "format": FORMAT, "version": FORMAT_VERSION, "name": self.name,
            "provenance": asdict(self.provenance), "documents": len(self.documents),
            "clickstream": [[a, b, counts] for (a, b), counts in sorted(self.clickstream.items())],
        }
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(json.dumps(header, ensure_ascii=False) + "\n")
            for doc in self.documents:
                handle.write(json.dumps(_doc_dict(doc), ensure_ascii=False) + "\n")
        return path

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Corpus":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            header = json.loads(handle.readline())
            if header.get("format") != FORMAT:
                raise ValueError(f"{path} is not a {FORMAT} file")
            if header.get("version", 0) > FORMAT_VERSION:
                raise ValueError(f"{path} uses corpus format v{header['version']}; this code reads v{FORMAT_VERSION}")
            documents = [_doc_from_dict(json.loads(line)) for line in handle if line.strip()]
        clicks = {(a, b): dict(counts) for a, b, counts in header.get("clickstream", [])}
        return cls(header["name"], documents, Provenance(**header["provenance"]), clicks)


def _doc_dict(doc: Document) -> Dict[str, Any]:
    data = asdict(doc)
    data["links"] = [[l.target, l.anchor, l.paragraph] for l in doc.links]
    return data


def _doc_from_dict(data: Dict[str, Any]) -> Document:
    links = [GoldLink(t, a, p) for t, a, p in data.pop("links", [])]
    return Document(links=links, **data)
