"""
Synthetic corpora with ground truth known by construction.

What it is for: measuring properties real data cannot reveal (which "false
positives" are valid mentions the editors did not link; recall per link style),
validating the evaluation code itself (every metric has a known answer here),
and scale tests of any size offline. What it is NOT for: claims about
real-world quality - the generator was written by the same project as the
system under test, so its results are always reported separately and broken
down by link style, never merged with real sources.

Realism controls (to avoid measuring generator artefacts):
  * pseudo-words from syllables, Zipf-distributed word frequencies;
  * vocabulary grows with corpus size (Heaps' law), so a page names a bounded
    number of other pages as the site grows, like real text;
  * topics overlap: every page mixes its topic with a secondary one (mostly a
    neighbouring topic on a ring), with a random weight up to 45%;
  * link targets are chosen by topic (mostly) and importance (preferential
    attachment).

Neutralized biases (each was found by running the harness on an earlier version):
  * disjoint topic vocabularies made content clustering perfect (NMI 1.0): topics
    now overlap as described above;
  * popularity was computed from the inbound link count, so in-degree won the
    ranking task by construction: popularity, links and page length are now
    independent noisy functions of a hidden importance, so no scorer is favoured
    by the formula (they can only win by tracking the hidden importance better).

Planted link styles (proportions per preset, recorded in every document):
  full       the target's title, verbatim                       anchor-based linking can find it
  inflected  the title words with plural endings                the light stemmer should find it
  partial    one word of the title                              below the 2-word anchor minimum
  alias      a synonym phrase the target page introduces         needs semantics, not mentions
  generic    "this approach", "see here"                          unrecoverable from the text
plus unlinked valid mentions (gold incompleteness) recorded in meta["unlinked_mentions"].
"""

import random
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from src.engines.text import STOPWORDS, is_content_token
from src.evaluation.corpus import Corpus, Document, GoldLink, Provenance

LINK_STYLES = ("full", "inflected", "partial", "alias", "generic")
GENERIC_ANCHORS = ("this approach", "see here", "the method described there", "related work", "more details")
FILLERS = {
    "en": ("the", "a", "of", "in", "for", "with", "and", "to", "is", "on", "by", "as"),
    "pt": ("o", "a", "de", "da", "do", "em", "para", "com", "e", "que", "por", "como"),
}
ALSO_KNOWN = {"en": "also known as", "pt": "também conhecido como"}
_ONSETS = "b c d f g k l m n p r s t v z br cr dr gr pl pr st tr".split()
_VOWELS = "a e i o u ai ea io ou".split()
_CODAS = ["", "", "", "n", "r", "s", "l", "m", "x", "nd", "st"]


@dataclass(frozen=True)
class SyntheticSpec:
    pages: int = 1000
    topics: int = 12
    seed: int = 0
    preset: str = "encyclopedia"          # encyclopedia | catalog | forum
    language: str = "en"                   # en | pt (filler words)
    styles: Tuple[Tuple[str, float], ...] = ()   # overrides the preset's link style mix
    unlinked_rate: float = -1.0            # overrides the preset's unlinked valid mention rate

    def style_mix(self) -> Dict[str, float]:
        mix = dict(self.styles) if self.styles else dict(PRESETS[self.preset]["styles"])
        total = sum(mix.values())
        return {s: mix.get(s, 0.0) / total for s in LINK_STYLES}


PRESETS = {
    "encyclopedia": {"styles": {"full": .40, "inflected": .10, "partial": .25, "alias": .15, "generic": .10},
                     "paragraphs": (3, 12), "links": 8, "unlinked": .20, "host": "synthetic-wiki.example"},
    "catalog": {"styles": {"full": .60, "inflected": .15, "partial": .10, "alias": .05, "generic": .10},
                "paragraphs": (2, 5), "links": 5, "unlinked": .30, "host": "synthetic-shop.example"},
    "forum": {"styles": {"full": .25, "inflected": .0, "partial": .15, "alias": .10, "generic": .50},
              "paragraphs": (2, 8), "links": 3, "unlinked": .10, "host": "synthetic-forum.example"},
}


class _Words:
    """Unique pronounceable pseudo-words (never stopwords, never numbers)."""

    def __init__(self, rng: random.Random):
        self.rng, self.used = rng, set()

    def make(self) -> str:
        while True:
            word = "".join(self.rng.choice(_ONSETS) + self.rng.choice(_VOWELS) for _ in range(self.rng.choice((2, 2, 3))))
            word += self.rng.choice(_CODAS)
            if word not in self.used and word not in STOPWORDS and is_content_token(word) and len(word) >= 4:
                self.used.add(word)
                return word


def _zipf_sampler(rng: random.Random, words: Sequence[str], exponent: float = 1.07):
    weights = [1 / (rank + 1) ** exponent for rank in range(len(words))]
    cumulative, total = [], 0.0
    for w in weights:
        total += w
        cumulative.append(total)

    def draw() -> str:
        x = rng.random() * total
        lo, hi = 0, len(cumulative) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cumulative[mid] < x:
                lo = mid + 1
            else:
                hi = mid
        return words[lo]
    return draw


@dataclass
class _Article:
    index: int
    topic: int
    title: str
    alias: str
    importance: float
    secondary: int = 0          # second topic mixed into the text
    mix: float = 0.0            # share of topic words drawn from the secondary topic
    paragraphs: List[List[List[str]]] = field(default_factory=list)   # paragraph -> sentence -> tokens
    links: List[GoldLink] = field(default_factory=list)
    styles: List[str] = field(default_factory=list)
    unlinked: List[int] = field(default_factory=list)


def generate(spec: SyntheticSpec = SyntheticSpec()) -> Corpus:
    if spec.preset not in PRESETS:
        raise ValueError(f"unknown preset {spec.preset!r}; choose one of {sorted(PRESETS)}")
    if spec.language not in FILLERS:
        raise ValueError(f"unknown language {spec.language!r}; choose one of {sorted(FILLERS)}")
    preset = PRESETS[spec.preset]
    rng = random.Random(spec.seed)
    words = _Words(rng)
    n, k = spec.pages, max(1, min(spec.topics, spec.pages))
    # Heaps' law: vocabulary ~ K * n^0.6, split into topic vocabularies and a shared one.
    per_topic = max(60, int(12 * (n / k) ** 0.6) + 40)
    general = [words.make() for _ in range(max(150, int(20 * n ** 0.5)))]
    topic_words = [[words.make() for _ in range(per_topic)] for _ in range(k)]
    topic_names = [f"{topic_words[t][0]} studies" for t in range(k)]
    draw_general = _zipf_sampler(rng, general)
    draw_topic = [_zipf_sampler(rng, vocab) for vocab in topic_words]
    fillers = FILLERS[spec.language]

    # Articles: titles from the rarer half of their topic vocabulary (specific names), unique.
    articles: List[_Article] = []
    taken: Set[str] = set()
    for i in range(n):
        topic = i % k if i < k else rng.randrange(k)
        while True:
            size = rng.choices((1, 2, 3, 4), weights=(15, 45, 30, 10))[0]
            pool = topic_words[topic][per_topic // 4:]
            title = " ".join(rng.sample(pool, size)).title()
            if title.lower() not in taken:
                taken.add(title.lower())
                break
        title_words = set(title.lower().split())   # an alias never shares a word with the title
        alias = " ".join(rng.sample([w for w in topic_words[topic][per_topic // 4:] if w not in title_words], 2))
        articles.append(_Article(i, topic, title, alias, rng.lognormvariate(0, 1)))
        neighbour = (topic + rng.choice((-1, 1))) % k if rng.random() < 0.8 else rng.randrange(k)
        articles[-1].secondary, articles[-1].mix = neighbour, rng.uniform(0.0, 0.45)

    def sentence(article: "_Article") -> List[str]:
        out = []
        for _ in range(rng.randint(8, 18)):
            roll = rng.random()
            if roll < 0.28:
                out.append(rng.choice(fillers))
            elif roll < 0.78:
                topic = article.secondary if rng.random() < article.mix else article.topic
                out.append(draw_topic[topic]())
            elif roll < 0.95:
                out.append(draw_general())
            else:
                out.append(draw_topic[rng.randrange(k)]())
        return out

    low, high = preset["paragraphs"]
    for a in articles:
        # Length: mostly independent of importance (30% importance, 70% noise).
        drive = 0.3 * min(1.0, a.importance / 3) + 0.7 * rng.random()
        count = min(high, max(low, int(round(low + (high - low) * drive))))
        a.paragraphs = [[sentence(a) for _ in range(rng.randint(2, 5))] for _ in range(count)]
        a.paragraphs[0][0].insert(0, f"{a.title} ({ALSO_KNOWN[spec.language]} {a.alias})")

    # Gold links: mostly same topic, preferential to important articles.
    by_topic: Dict[int, List[_Article]] = {}
    for a in articles:
        by_topic.setdefault(a.topic, []).append(a)
    mix = spec.style_mix()
    styles, weights = list(mix), list(mix.values())
    unlinked_rate = preset["unlinked"] if spec.unlinked_rate < 0 else spec.unlinked_rate

    def pick_target(source: _Article, exclude: Set[int]) -> Optional[_Article]:
        """A target by topic and importance; None when every other article is already used."""
        pool = by_topic[source.topic] if rng.random() < 0.75 or k == 1 else articles
        for _ in range(20):
            candidate = rng.choices(pool, weights=[c.importance for c in pool])[0]
            if candidate.index != source.index and candidate.index not in exclude:
                return candidate
        rest = [c for c in articles if c.index != source.index and c.index not in exclude]
        return rng.choice(rest) if rest else None

    for a in articles:
        if n < 2:
            break
        wanted = min(n - 1, max(1, int(rng.expovariate(1 / preset["links"])) + 1))
        chosen: Set[int] = set()
        for _ in range(wanted):
            target = pick_target(a, chosen)
            if target is None:
                break
            chosen.add(target.index)
            style = rng.choices(styles, weights=weights)[0]
            anchor = _anchor(style, target, rng)
            paragraph = rng.randrange(len(a.paragraphs))
            _insert(a.paragraphs[paragraph], anchor, rng)
            a.links.append(GoldLink(target.index, anchor, paragraph))   # target index, mapped to ids below
            a.styles.append(style)
        for _ in range(sum(rng.random() < unlinked_rate for _ in range(wanted))):   # valid, unlinked mentions
            target = pick_target(a, chosen)
            if target is None:
                break
            chosen.add(target.index)
            _insert(a.paragraphs[rng.randrange(len(a.paragraphs))], target.title.lower(), rng)
            a.unlinked.append(target.index)

    host = preset["host"]
    ids = [_url(host, spec.preset, a, topic_names) for a in articles]
    # Popularity depends on the hidden importance only (not on links or length).
    views = [a.importance * rng.lognormvariate(0, 0.7) * 100 for a in articles]
    documents = []
    for a in articles:
        documents.append(Document(
            id=ids[a.index], title=a.title,
            paragraphs=[". ".join(_sentence_text(s) for s in p) + "." for p in a.paragraphs],
            links=[GoldLink(ids[l.target], l.anchor, l.paragraph) for l in a.links],
            labels=[topic_names[a.topic]],
            popularity=round(views[a.index], 2),
            meta={"styles": a.styles, "unlinked_mentions": [ids[t] for t in a.unlinked],
                  "importance": round(a.importance, 4), "alias": a.alias},
        ))
    clicks: Dict[Tuple[str, str], Dict[str, int]] = {}
    mean_importance = sum(a.importance for a in articles) / n
    for a in articles:
        for link in a.links:
            rate = views[a.index] * 0.02 * articles[link.target].importance / mean_importance
            clicks[(ids[a.index], ids[link.target])] = {"link": int(rate * rng.lognormvariate(0, 0.5))}
        for t in a.unlinked:   # readers search for what is mentioned but not linked
            clicks[(ids[a.index], ids[t])] = {"other": int(views[a.index] * 0.005 * rng.lognormvariate(0, 0.5)) + 1}
    provenance = Provenance("synthetic", f"generator/{spec.preset}", query=str(asdict(spec)),
                            snapshot=f"seed {spec.seed}", license="generated",
                            notes="ground truth by construction; see src/evaluation/sources/synthetic.py",
                            language=spec.language)
    return Corpus(f"synthetic-{spec.preset}-{spec.language}-{n}", documents, provenance, clicks).closed()


def _anchor(style: str, target: _Article, rng: random.Random) -> str:
    words = target.title.lower().split()
    if style == "full":
        return target.title if rng.random() < 0.3 else target.title.lower()
    if style == "inflected":
        return " ".join(w + ("es" if w.endswith(("s", "x")) else "s") for w in words)
    if style == "partial":
        return max(words, key=len)
    if style == "alias":
        return target.alias
    return rng.choice(GENERIC_ANCHORS)


def _insert(sentences: List[List[str]], phrase: str, rng: random.Random) -> None:
    """Put a phrase between two tokens of a random sentence; it stays one token, so later
    insertions never split it."""
    tokens = sentences[rng.randrange(len(sentences))]
    tokens.insert(rng.randint(1, max(1, len(tokens) - 1)), phrase)


def _sentence_text(tokens: List[str]) -> str:
    text = " ".join(tokens)
    return text[0].upper() + text[1:]


def _url(host: str, preset: str, article: _Article, topic_names: List[str]) -> str:
    slug = article.title.lower().replace(" ", "-")
    if preset == "catalog":
        return f"https://{host}/{topic_names[article.topic].split()[0]}/{slug}"
    if preset == "forum":
        return f"https://{host}/questions/{article.index}/{slug}"
    return f"https://{host}/wiki/{article.title.replace(' ', '_')}"


def style_of(corpus: Corpus) -> Dict[Tuple[str, str], str]:
    """(source, target) -> planted link style (first link of the pair)."""
    styles: Dict[Tuple[str, str], str] = {}
    for doc in corpus.documents:
        for link, style in zip(doc.links, doc.meta.get("styles", [])):
            styles.setdefault((doc.id, link.target), style)
    return styles
