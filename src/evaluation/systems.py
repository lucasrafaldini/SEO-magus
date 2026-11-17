"""
Systems evaluated side by side: SEO-Magus variants and the baselines they must beat.

Every system sees exactly the same input (the corpus with the evaluated links
removed) through the same interface, and is scored by the same code. Baselines
are chosen to expose specific weaknesses, not to be easy to beat:

Link prediction (source -> targets)
  seo-magus            the product as a user runs it on an unknown site: heuristic
                       classifier, no taxonomy (no topic boundaries)
  seo-magus+content    topic boundaries from content clustering (no configuration)
  seo-magus+structure  topic boundaries from link-graph communities (no configuration)
  seo-magus+labels     topic boundaries from the human labels: an ORACLE upper bound of
                       what a perfect taxonomy would add (never compared as a product)
  exact-title          link wherever a page's full title is written (classic "wikifier"
                       baseline): tests whether the classifier and anchor rules add anything
  title-overlap        link when >= 2 title words occur anywhere in the page: the raw
                       lexical signal without anchors, gates or classifier
  similar-content      the 5 most similar pages by TF-IDF cosine: a recommender that
                       ignores mentions entirely (different failure modes)
  random               5 random pages: the chance level

Classification (page -> cluster)
  seo-magus            what the product does without configuration: one cluster
  url-folders          URL folder as topic (what a hand-written URL taxonomy encodes)
  content-k / content-sqrt   TF-IDF k-means with k = number of true labels (oracle k)
                       or k = sqrt(n/2) (no oracle)
  structure            link-graph label propagation (no text)
  random               uniform over as many clusters as true labels

Ranking (page -> importance score)
  pagerank / cheirank  SEO-Magus internal PageRank and CheiRank on the site's link graph
  in-degree            number of inbound links (the obvious cheap alternative)
  length               text length (do long pages just look important?)
  random               chance level
"""

import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from src.engines.classifiers import HeuristicClassifier, LinkClassifier
from src.engines.clustering import content_clusters, label_propagation, suggested_k, tfidf_vectors
from src.engines.link_graph import LinkGraph
from src.engines.taxonomy import SiteTaxonomy
from src.engines.text import is_content_token, tokenize
from src.evaluation.corpus import Corpus, Pair
from src.workflows.linking_optimizer import LinkingOptimizer

Predictions = Dict[str, List[str]]          # source id -> ranked targets
RANDOM_K = SIMILAR_K = 5
# Text-only computations do not depend on which links were removed: computed once per corpus (and seed).
_CACHE: Dict[tuple, object] = {}


def _cached(key: tuple, compute: Callable[[], object]):
    if key not in _CACHE:
        if len(_CACHE) > 64:
            _CACHE.clear()
        _CACHE[key] = compute()
    return _CACHE[key]


@dataclass(frozen=True)
class LinkSystem:
    name: str
    kind: str                                # "product" | "oracle" | "baseline"
    predict: Callable[[Corpus, Set[Pair], Sequence[str], int], Predictions]


# ------------------------------------------------------------ SEO-Magus


def _seo_magus(clusters: Optional[Callable[[Corpus, Set[Pair], int], Dict[str, str]]] = None,
               classifier: Optional[Callable[[], LinkClassifier]] = None):
    def predict(corpus: Corpus, removed: Set[Pair], sources: Sequence[str], seed: int) -> Predictions:
        taxonomy = SiteTaxonomy(assignments=clusters(corpus, removed, seed)) if clusters else SiteTaxonomy()
        optimizer = LinkingOptimizer(classifier=(classifier or HeuristicClassifier)(), taxonomy=taxonomy)
        report = optimizer.run_optimization(corpus.to_pages(removed), sources=sources)
        ranked: Predictions = defaultdict(list)
        for result in sorted(report.results, key=lambda r: (-r.relevance_score, -r.confidence)):
            ranked[result.source_url].append(result.target_url)
        return dict(ranked)
    return predict


def _label_clusters(corpus: Corpus, removed: Set[Pair], seed: int) -> Dict[str, str]:
    return {doc.id: doc.labels[0] for doc in corpus.documents if doc.labels}


def _content_clusters(corpus: Corpus, removed: Set[Pair], seed: int) -> Dict[str, str]:
    return _content_k(corpus, suggested_k(len(corpus)), seed)


def _structure_clusters(corpus: Corpus, removed: Set[Pair], seed: int) -> Dict[str, str]:
    edges = [(doc.id, t) for doc in corpus.documents for t in doc.link_targets if (doc.id, t) not in removed]
    return label_propagation(corpus.ids, edges, seed)


# ------------------------------------------------------------ baselines


def _words(text: str) -> List[str]:
    return tokenize(text)


def _exact_title(corpus: Corpus, removed: Set[Pair], sources: Sequence[str], seed: int) -> Predictions:
    by_first: Dict[str, List[Tuple[Tuple[str, ...], str]]] = defaultdict(list)
    for doc in corpus.documents:
        words = tuple(_words(doc.title))
        if words:
            by_first[words[0]].append((words, doc.id))
    predictions: Predictions = {}
    for source in sources:
        doc = corpus.get(source)
        found: List[str] = []
        for paragraph in doc.paragraphs:
            words = _words(paragraph)
            for i, word in enumerate(words):
                for title, target in by_first.get(word, ()):
                    if target != source and target not in found and tuple(words[i:i + len(title)]) == title:
                        found.append(target)
        predictions[source] = found
    return predictions


def _title_overlap(corpus: Corpus, removed: Set[Pair], sources: Sequence[str], seed: int) -> Predictions:
    postings: Dict[str, List[str]] = defaultdict(list)
    for doc in corpus.documents:
        for word in {w for w in _words(doc.title) if is_content_token(w)}:
            postings[word].append(doc.id)
    predictions: Predictions = {}
    for source in sources:
        words = {w for p in corpus.get(source).paragraphs for w in _words(p) if is_content_token(w)}
        shared = Counter(t for w in words for t in postings.get(w, ()) if t != source)
        predictions[source] = [t for t, n in sorted(shared.items(), key=lambda kv: (-kv[1], kv[0])) if n >= 2]
    return predictions


def _similar_content(corpus: Corpus, removed: Set[Pair], sources: Sequence[str], seed: int) -> Predictions:
    ids = corpus.ids
    vectors, postings = _cached(("tfidf", corpus.fingerprint()), lambda: _tfidf_index(corpus))
    by_id = dict(zip(ids, vectors))
    predictions: Predictions = {}
    for source in sources:
        query = by_id[source]
        top_terms = sorted(query.items(), key=lambda kv: -kv[1])[:20]
        scores: Counter = Counter()
        for term, weight in top_terms:
            for i in postings[term]:
                scores[i] += weight * vectors[i][term]
        ranked = [ids[i] for i, _ in sorted(scores.items(), key=lambda kv: (-kv[1], ids[kv[0]])) if ids[i] != source]
        predictions[source] = ranked[:SIMILAR_K]
    return predictions


def _tfidf_index(corpus: Corpus):
    vectors = tfidf_vectors([" ".join([d.title] + d.paragraphs) for d in corpus.documents])
    postings: Dict[str, List[int]] = defaultdict(list)
    for i, vector in enumerate(vectors):
        for term in vector:
            postings[term].append(i)
    return vectors, postings


def _random_links(corpus: Corpus, removed: Set[Pair], sources: Sequence[str], seed: int) -> Predictions:
    rng = random.Random(seed)
    ids = corpus.ids
    return {s: [t for t in rng.sample(ids, min(len(ids), RANDOM_K + 1)) if t != s][:RANDOM_K] for s in sources}


def link_systems(classifier: Optional[Callable[[], LinkClassifier]] = None) -> Tuple[LinkSystem, ...]:
    """All link systems; `classifier` builds the classifier of the SEO-Magus variants (default: heuristic)."""
    return (
        LinkSystem("seo-magus", "product", _seo_magus(classifier=classifier)),
        LinkSystem("seo-magus+content", "product", _seo_magus(_content_clusters, classifier)),
        LinkSystem("seo-magus+structure", "product", _seo_magus(_structure_clusters, classifier)),
        LinkSystem("seo-magus+labels", "oracle", _seo_magus(_label_clusters, classifier)),
        LinkSystem("exact-title", "baseline", _exact_title),
        LinkSystem("title-overlap", "baseline", _title_overlap),
        LinkSystem("similar-content", "baseline", _similar_content),
        LinkSystem("random", "baseline", _random_links),
    )


LINK_SYSTEMS: Tuple[LinkSystem, ...] = link_systems()


# ------------------------------------------------------ classification

Clusterer = Callable[[Corpus, int, int], Dict[str, str]]   # corpus, number of true labels, seed


def _url_folder(url: str) -> str:
    path = re.sub(r"^https?://[^/]+", "", url).rstrip("/")
    return path.rsplit("/", 1)[0] or "/"


def _content_k(corpus: Corpus, k: int, seed: int) -> Dict[str, str]:
    return _cached(("kmeans", corpus.fingerprint(), k, seed), lambda: content_clusters(
        {d.id: " ".join([d.title] + d.paragraphs) for d in corpus.documents}, k, seed))


def _content_sqrt(corpus: Corpus, k: int, seed: int) -> Dict[str, str]:
    return _content_k(corpus, suggested_k(len(corpus)), seed)


def _structure(corpus: Corpus, k: int, seed: int) -> Dict[str, str]:
    edges = [(d.id, t) for d in corpus.documents for t in list(d.link_targets) + d.extra_links]
    return label_propagation(corpus.ids, edges, seed)


def _random_clusters(corpus: Corpus, k: int, seed: int) -> Dict[str, str]:
    rng = random.Random(seed)
    return {d.id: f"c{rng.randrange(max(1, k))}" for d in corpus.documents}


CLUSTERERS: Dict[str, Tuple[str, Clusterer]] = {
    "seo-magus": ("product", lambda corpus, k, seed: {d.id: "general" for d in corpus.documents}),
    "url-folders": ("baseline", lambda corpus, k, seed: {d.id: _url_folder(d.id) for d in corpus.documents}),
    "content-k": ("oracle", _content_k),
    "content-sqrt": ("product", _content_sqrt),
    "structure": ("product", _structure),
    "random": ("baseline", _random_clusters),
}


# ------------------------------------------------------------- ranking

Scorer = Callable[[Corpus, int], Dict[str, float]]


def site_graph(corpus: Corpus, exclude: Set[Pair] = frozenset()) -> LinkGraph:
    """
    The site's own link graph: in-prose links plus the other human links, without
    the `exclude`d in-prose links (a pair also present as another human link stays).
    Built from scratch: LinkGraph keeps a networkx copy of its edges, so removing
    edges afterwards from its dictionaries would not affect PageRank.
    """
    graph = LinkGraph()
    for doc in corpus.documents:
        graph.add_page(doc.id)
    for doc in corpus.documents:
        extra = set(doc.extra_links)
        for target in doc.link_targets:
            if (doc.id, target) not in exclude or target in extra:
                graph.add_link(doc.id, target)
        for target in doc.extra_links:
            graph.add_link(doc.id, target)
    return graph


def _random_scores(corpus: Corpus, seed: int) -> Dict[str, float]:
    rng = random.Random(seed)
    return {d.id: rng.random() for d in corpus.documents}


SCORERS: Dict[str, Tuple[str, Scorer]] = {
    "pagerank": ("product", lambda corpus, seed: site_graph(corpus).compute_pagerank()),
    "cheirank": ("product", lambda corpus, seed: site_graph(corpus).compute_cheirank()),
    "in-degree": ("baseline", lambda corpus, seed: {n: float(len(s)) for n, s in site_graph(corpus).in_edges.items()}),
    "length": ("baseline", lambda corpus, seed: {d.id: float(sum(len(p) for p in d.paragraphs)) for d in corpus.documents}),
    "random": ("baseline", _random_scores),
}
