"""
Stack Exchange sites from their public data dumps (Posts.xml, PostLinks.xml).

The dumps are published by Stack Exchange (CC BY-SA) and mirrored on the
Internet Archive (archive.org/details/stackexchange); extract a site's archive
and point `import_dump` at the directory. Small sites (gardening, cooking,
writers...) are a few MB; Stack Overflow itself is too large for this importer.

One document per question page (question + its answers, best score first):
  links        links inside question and answer bodies to other questions of
               the sample (answers /a/N are resolved to their question)
  extra_links  PostLinks rows between sample questions: "linked" (1) and
               "duplicate" (3) relations recorded by the site - independent of the text
  labels       tags (sampling tag first with tag sampling)
  popularity   view count
"""

import random
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union
from urllib.parse import urlparse

from src.evaluation.corpus import Corpus, Document, GoldLink, Provenance
from src.evaluation.sources.prose import extract_prose
from src.log import get_logger

logger = get_logger(__name__)

_QUESTION_PATH = re.compile(r"^/(?:questions|q)/(\d+)")
_ANSWER_PATH = re.compile(r"^/a/(\d+)")
_TAG_RE = re.compile(r"<([^>]+)>")


def parse_tags(value: str) -> List[str]:
    """Both dump formats: "<python><pandas>" (until 2023) and "|python|pandas|"."""
    if not value:
        return []
    if value.startswith("<"):
        return _TAG_RE.findall(value)
    return [t for t in value.split("|") if t]


def _rows(path: Path) -> Iterator[Dict[str, str]]:
    for _, element in ET.iterparse(str(path), events=("end",)):
        if element.tag == "row":
            yield dict(element.attrib)
        element.clear()


class StackExchangeDump:
    def __init__(self, directory: Union[str, Path], site: str):
        self.directory = Path(directory)
        self.site = site.rstrip("/")
        if not self.site.startswith("http"):
            self.site = f"https://{self.site}"
        self.host = urlparse(self.site).netloc
        if not (self.directory / "Posts.xml").is_file():
            raise FileNotFoundError(f"{self.directory / 'Posts.xml'} not found (extract the site's dump first)")

    def question_url(self, question_id: str) -> str:
        return f"{self.site}/questions/{question_id}"

    def _question_of(self, href: str, answers: Dict[str, str]) -> Optional[str]:
        parsed = urlparse(href)
        if parsed.netloc and parsed.netloc != self.host:
            return None
        match = _QUESTION_PATH.match(parsed.path)
        if match:
            return match.group(1)
        match = _ANSWER_PATH.match(parsed.path)
        return answers.get(match.group(1)) if match else None

    def import_dump(self, name: str, limit: int = 1000, seed: int = 0, tags: Sequence[str] = ()) -> Corpus:
        rng = random.Random(seed)
        questions: Dict[str, Tuple[str, List[str], Optional[float]]] = {}   # id -> title, tags, views
        answers: Dict[str, str] = {}                                         # answer id -> question id
        for row in _rows(self.directory / "Posts.xml"):
            if row.get("PostTypeId") == "1":
                views = row.get("ViewCount")
                questions[row["Id"]] = (row.get("Title", ""), parse_tags(row.get("Tags", "")),
                                        float(views) if views else None)
            elif row.get("PostTypeId") == "2" and row.get("ParentId"):
                answers[row["Id"]] = row["ParentId"]
        primary: Dict[str, str] = {}
        if tags:
            share = max(1, limit // len(tags))
            chosen: List[str] = []
            for tag in tags:
                members = sorted(q for q, (_, t, _) in questions.items() if tag in t and q not in primary)
                rng.shuffle(members)
                for q in members[:share]:
                    primary[q] = tag
                    chosen.append(q)
            method = "tags"
        else:
            chosen = sorted(questions)
            rng.shuffle(chosen)
            chosen = chosen[:limit]
            method = "random"
        sample: Set[str] = set(chosen)

        bodies: Dict[str, List[Tuple[int, str]]] = {q: [] for q in sample}   # question -> (order, html)
        for row in _rows(self.directory / "Posts.xml"):
            if row.get("PostTypeId") == "1" and row["Id"] in sample:
                bodies[row["Id"]].append((-10**9, row.get("Body", "")))      # the question comes first
            elif row.get("PostTypeId") == "2" and row.get("ParentId") in sample:
                bodies[row["ParentId"]].append((-int(row.get("Score", "0") or 0), row.get("Body", "")))

        related: Dict[str, List[str]] = {q: [] for q in sample}
        links_file = self.directory / "PostLinks.xml"
        if links_file.is_file():
            for row in _rows(links_file):
                a, b = row.get("PostId"), row.get("RelatedPostId")
                if a in sample and b in sample and row.get("LinkTypeId") in ("1", "3"):
                    related[a].append(self.question_url(b))

        documents = []
        for q in chosen:
            title, question_tags, views = questions[q]
            paragraphs: List[str] = []
            gold: List[GoldLink] = []
            for _, html in sorted(bodies[q], key=lambda item: item[0]):
                texts, links = extract_prose(html, self.question_url(q), list_items=True)
                offset = len(paragraphs)
                paragraphs += texts
                for link in links:
                    target = self._question_of(link.href, answers)
                    if target and target in sample:
                        gold.append(GoldLink(self.question_url(target), link.anchor, offset + link.paragraph))
            labels = ([primary[q]] if q in primary else []) + [t for t in question_tags if t != primary.get(q)]
            documents.append(Document(self.question_url(q), title, paragraphs or [title], gold,
                                      list(dict.fromkeys(related[q])), labels, views, {"question_id": q}))
        logger.info("Stack Exchange %s: %d questions sampled (%s)", self.host, len(documents), method)
        provenance = Provenance("stackexchange", f"dump/{method}", query=", ".join(tags) or "random",
                                snapshot=str(self.directory), license="CC BY-SA (Stack Exchange data dump)",
                                notes=f"limit {limit}, seed {seed}")
        return Corpus(name, documents, provenance).closed()
