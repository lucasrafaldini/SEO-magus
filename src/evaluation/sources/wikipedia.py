"""
Wikipedia (any language edition) through the MediaWiki Action API.

Ground truth comes from independent access paths of the same source:

  links        in-prose editor links      action=parse (article HTML) -> prose.extract_prose
  extra_links  every article wikilink     prop=links (includes navboxes and templates: looser)
  labels       visible categories         action=parse prop=categories (hidden maintenance ones dropped);
                                          with category sampling the seed category comes first
  popularity   pageviews, last 60 days    prop=pageviews (PageViewInfo extension)
  clickstream  reader navigation          monthly clickstream dump (load_clickstream, separate file)

Links through redirects are resolved to the article they land on, so a link
to "USA" and one to "United States" are the same gold target.

Sampling (chosen at fetch time, recorded in the provenance):
  seeds       snowball: breadth-first over in-prose links from seed articles
  categories  members of seed categories, in equal shares (label-stratified)
  random      list=random (uniform over the main namespace)

Be polite: the client identifies itself, sends one request at a time and caches
every response (see http.py). Wikimedia also publishes dumps; for very large
samples prefer them.
"""

import gzip
import random
from collections import deque
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote, unquote, urlparse

from src.evaluation.corpus import Corpus, Document, GoldLink, Provenance
from src.evaluation.sources.http import HttpJsonClient
from src.evaluation.sources.prose import extract_prose
from src.log import get_logger

logger = get_logger(__name__)

BATCH = 50                 # titles per query (API limit for normal clients)
NON_ARTICLE_PREFIXES = {
    "file", "image", "category", "help", "wikipedia", "template", "portal", "special", "talk", "user", "module",
    "draft", "mediawiki", "book", "timedtext", "wp", "wikt", "commons", "media", "project",
}


def article_url(lang: str, title: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='()_,:!.-')}"


def title_from_href(href: str, lang: str) -> Optional[str]:
    """Main-namespace article title of a /wiki/ link on the same wiki, else None."""
    parsed = urlparse(href)
    if parsed.netloc and parsed.netloc != f"{lang}.wikipedia.org":
        return None
    if not parsed.path.startswith("/wiki/"):
        return None
    title = unquote(parsed.path[len("/wiki/"):]).replace("_", " ").strip()
    if not title:
        return None
    prefix = title.split(":", 1)[0].strip().lower() if ":" in title else ""
    if prefix.endswith(" talk") or prefix in NON_ARTICLE_PREFIXES:
        return None
    return title[0].upper() + title[1:]          # MediaWiki first-letter case folding


class WikipediaSource:
    def __init__(self, client: HttpJsonClient, lang: str = "en"):
        self.client = client
        self.lang = lang
        self.api = f"https://{lang}.wikipedia.org/w/api.php"

    def _query(self, **params) -> dict:
        params = {"format": "json", "formatversion": 2, "maxlag": 5, **params}
        return self.client.get_json(self.api, params)

    def _query_all(self, **params) -> Iterator[dict]:
        """Follow API continuation until the result set is exhausted."""
        cont: Dict[str, str] = {}
        while True:
            data = self._query(**params, **cont)
            yield data
            if "continue" not in data:
                return
            cont = data["continue"]

    # ------------------------------------------------------------ samplers

    def random_titles(self, limit: int) -> List[str]:
        titles: List[str] = []
        for call in range(limit // 10 + 10):        # duplicates are rare; this bounds pathological cases
            # requestid (a standard, echoed parameter) makes each draw a distinct cached request.
            data = self._query(action="query", list="random", rnnamespace=0, rnlimit=min(500, limit - len(titles)),
                               requestid=f"draw{call}")
            for page in data["query"]["random"]:
                if page["title"] not in titles:         # duplicates within a draw and across draws
                    titles.append(page["title"])
            if len(titles) >= limit:
                break
        return titles[:limit]

    def category_members(self, category: str, limit: int) -> List[str]:
        title = category if category.lower().startswith("category:") else f"Category:{category}"
        members: List[str] = []
        for data in self._query_all(action="query", list="categorymembers", cmtitle=title, cmnamespace=0,
                                    cmlimit="max", cmtype="page"):
            members += [m["title"] for m in data["query"]["categorymembers"]]
            if len(members) >= limit:
                break
        return members[:limit]

    # -------------------------------------------------------------- pages

    def parse(self, title: str) -> Optional[dict]:
        data = self._query(action="parse", page=title, prop="text|categories", redirects=1,
                           disableeditsection=1, disablelimitreport=1)
        if "error" in data:
            logger.warning("Wikipedia parse failed for %r: %s", title, data["error"].get("info"))
            return None
        return data["parse"]

    def resolve(self, titles: Iterable[str]) -> Dict[str, str]:
        """title -> canonical article title (normalization and redirects followed)."""
        titles = sorted(set(titles))        # deterministic batches: replayable requests
        resolved: Dict[str, str] = {}
        for start in range(0, len(titles), BATCH):
            batch = titles[start:start + BATCH]
            data = self._query(action="query", titles="|".join(batch), redirects=1)
            query = data.get("query", {})
            step = {n["from"]: n["to"] for n in query.get("normalized", [])}
            redirect = {r["from"]: r["to"] for r in query.get("redirects", [])}
            missing = {p["title"] for p in query.get("pages", []) if p.get("missing") or p.get("invalid")}
            for title in batch:
                final = redirect.get(step.get(title, title), step.get(title, title))
                if final not in missing:
                    resolved[title] = final
        return resolved

    def pageviews(self, titles: Sequence[str], days: int = 60) -> Dict[str, float]:
        views: Dict[str, float] = {}
        for start in range(0, len(titles), BATCH):
            data = self._query(action="query", prop="pageviews", titles="|".join(titles[start:start + BATCH]),
                               pvipdays=days)
            for page in data.get("query", {}).get("pages", []):
                daily = page.get("pageviews") or {}
                if daily:
                    views[page["title"]] = float(sum(v or 0 for v in daily.values()))
        return views

    def all_links(self, titles: Sequence[str]) -> Dict[str, List[str]]:
        links: Dict[str, List[str]] = {}
        for start in range(0, len(titles), BATCH):
            for data in self._query_all(action="query", prop="links", titles="|".join(titles[start:start + BATCH]),
                                        plnamespace=0, pllimit="max"):
                for page in data.get("query", {}).get("pages", []):
                    links.setdefault(page["title"], []).extend(l["title"] for l in page.get("links", []))
        return links

    # -------------------------------------------------------------- corpus

    def build(self, name: str, seeds: Sequence[str] = (), categories: Sequence[str] = (), random_count: int = 0,
              limit: int = 500, seed: int = 0, pageviews: bool = True, wikilinks: bool = True) -> Corpus:
        """Fetch a sample and return it as a closed corpus (see the module docstring)."""
        if sum(bool(x) for x in (seeds, categories, random_count)) != 1:
            raise ValueError("choose exactly one sampler: seeds, categories or random_count")
        rng = random.Random(seed)
        primary: Dict[str, str] = {}
        if categories:
            share = max(1, limit // len(categories))
            queue: List[str] = []
            for category in categories:
                members = self.category_members(category, share * 3)
                rng.shuffle(members)
                for title in members[:share]:
                    primary.setdefault(title, category.split(":", 1)[-1])
                    queue.append(title)
            method, query = "categories", ", ".join(categories)
        elif random_count:
            queue, method, query = self.random_titles(min(random_count, limit)), "random", f"{random_count} random"
        else:
            queue, method, query = list(seeds), "snowball", ", ".join(seeds)

        parsed: Dict[str, dict] = {}
        pending = deque(queue)
        seen: Set[str] = set(queue)
        while pending and len(parsed) < limit:
            title = pending.popleft()
            page = self.parse(title)
            if page is None or page["title"] in parsed:
                continue
            parsed[page["title"]] = page
            if title in primary:
                primary.setdefault(page["title"], primary[title])
            if method == "snowball":
                _, links = extract_prose(page.get("text", ""), article_url(self.lang, page["title"]))
                for link in links:
                    target = title_from_href(link.href, self.lang)
                    if target and target not in seen:
                        seen.add(target)
                        pending.append(target)
            if len(parsed) % 100 == 0:
                logger.info("Wikipedia %s: %d/%d articles parsed", self.lang, len(parsed), limit)

        documents = self._documents(parsed, primary)
        titles = list(parsed)
        if pageviews:
            views = self.pageviews(titles)
            for doc in documents:
                doc.popularity = views.get(doc.meta["title"])
        if wikilinks:
            wiki = self.all_links(titles)
            resolved = self.resolve({t for targets in wiki.values() for t in targets})
            for doc in documents:
                doc.extra_links = list(dict.fromkeys(
                    article_url(self.lang, resolved[t]) for t in wiki.get(doc.meta["title"], []) if t in resolved))
        provenance = Provenance("wikipedia", f"action-api/{method}", query=query, snapshot=f"{self.lang}.wikipedia live",
                                license="CC BY-SA 4.0", notes=f"limit {limit}, seed {seed}", language=self.lang)
        return Corpus(name, documents, provenance).closed()

    def _documents(self, parsed: Dict[str, dict], primary: Dict[str, str]) -> List[Document]:
        raw_targets = {}
        for title, page in parsed.items():
            paragraphs, links = extract_prose(page.get("text", ""), article_url(self.lang, title))
            raw_targets[title] = (paragraphs, [(title_from_href(l.href, self.lang), l) for l in links])
        resolved = self.resolve({t for _, links in raw_targets.values() for t, _ in links if t})
        documents = []
        for title, page in parsed.items():
            paragraphs, links = raw_targets[title]
            gold = [GoldLink(article_url(self.lang, resolved[t]), l.anchor, l.paragraph)
                    for t, l in links if t and t in resolved]
            visible = [c["category"].replace("_", " ") for c in page.get("categories", []) if not c.get("hidden")]
            labels = ([primary[title]] if title in primary else []) + [c for c in visible if c != primary.get(title)]
            documents.append(Document(article_url(self.lang, title), title, paragraphs, gold, [], labels, None,
                                      {"title": title, "pageid": page.get("pageid")}))
        return documents


def load_clickstream(corpus: Corpus, lines: Iterable[str], lang: str = "en") -> Corpus:
    """
    Attach a Wikipedia clickstream dump (TSV: prev, curr, type, n) to a corpus,
    keeping navigation between its own articles. `type` is "link" (the reader
    followed a link) or "other" (internal navigation without a link, e.g. search).
    """
    ids = set(corpus.ids)
    clicks: Dict[Tuple[str, str], Dict[str, int]] = {}
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 4 or parts[2] not in ("link", "other"):
            continue
        source, target = article_url(lang, parts[0]), article_url(lang, parts[1])
        if source in ids and target in ids and source != target:
            counts = clicks.setdefault((source, target), {})
            counts[parts[2]] = counts.get(parts[2], 0) + int(parts[3])
    corpus.clickstream = clicks
    corpus._fingerprint = None       # content changed
    return corpus


def open_clickstream(path: str) -> Iterator[str]:
    """Lines of a clickstream dump file (.tsv or .tsv.gz), streamed (dumps are GBs)."""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        yield from handle
