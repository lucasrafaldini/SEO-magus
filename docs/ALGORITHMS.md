# Algorithms

## Internal link graph ranking (`src/engines/link_graph.py`)

The link graph has one node per page and one edge per contextual internal link (navigation links are not part of
it). N is the number of pages, α the damping factor, `out(u)` / `in(u)` the pages u links to / is linked from.

### PageRank – `compute_pagerank()`

    PR(v) = (1 − α)/N + α · Σ_{u→v} PR(u)/|out(u)| + α · Σ_{u: out(u)=∅} PR(u)/N

Pages with no outbound link spread their rank uniformly. PageRank measures the link equity a page **receives**.

### CheiRank – `compute_cheirank()`

PageRank of the reversed graph (Chepelianskii 2010; Zhirov, Zhirov & Shepelyansky 2010):

    CR(v) = (1 − α)/N + α · Σ_{w ∈ out(v)} CR(w)/|in(w)| + α · Σ_{w: in(w)=∅} CR(w)/N

A page scores high when it links to many pages that few others link to: it measures **hub** pages, the ones that
distribute equity. Orphan pages are the dangling nodes of the reversed graph.

### Pillar click-depth weighted PageRank – `compute_weighted_pagerank(depth_decay=0.85)`

Let d(u) be the click depth of u from the nearest pillar page (multi-source BFS, `compute_pillar_depths()`); pages no
pillar can reach get d(u) = D + 1 where D is the deepest reachable depth. With δ = `depth_decay`, page u passes on
only part of its equity:

    α_u = α · δ^{d(u)}
    x(v) = Σ_{u→v} α_u · x(u)/|out(u)| + (1/N) · Σ_u (1 − α_u · [out(u) ≠ ∅]) · x(u)

The withheld share returns to the uniform teleport, so scores still sum to 1 and the solution is unique. δ = 1 gives
exactly PageRank; δ = 0 means only pillars pass link equity. (Weighting edges by the source depth would have no
effect: PageRank normalizes each page's outgoing weights.) Without pillar pages the method warns
(`NoPillarsWarning`) and returns standard PageRank.

### Shared contract

All three methods take `alpha=0.85, max_iter=100, tol=1e-6`, with the same meaning on the networkx and the
pure-Python backend: at most `max_iter` power iterations, stop when the L1 change is below N·tol, emit a
`ConvergenceWarning` and return the last iterate otherwise.

## Link decision flow (`src/workflows/linking_optimizer.py`)

Every ordered pair of crawled pages (source → target) goes through these gates in order; the first that refuses
gives the reason shown in reports and logs (`-vv`) and in `explain_link()`:

| # | Gate | Refusal reason |
| :--- | :--- | :--- |
| 1 | both pages indexable (no noindex, canonical to themselves) | `not indexable` |
| 2 | target cluster allowed for the source cluster (`taxonomy.clusters`, `cluster_affinities`) | `cluster boundary` |
| 3 | the link does not already exist | `existing link` |
| 4 | role rules (`link_rules.money_to_support`) | `role rule` |
| 5 | the classifier judges every source paragraph; at least one must pass `min_confidence` and `min_score` | `classifier gate` |
| 6 | a passing paragraph contains a descriptive anchor | `no natural anchor` |

Among the paragraphs that pass, the best one gets the link: highest score, then confidence, then most descriptive
anchor, then earliest.

## Anchors (`src/engines/auxiliary_ai.py`)

An anchor is a phrase of the source sentence that names the target, built from the target's title, H1 and SERP page 2
queries (shared tokenizer and matching rules in `src/engines/text.py`):

* at least `anchor_min_words` distinct topic words, at most 6 words;
* starts and ends with a topic word (never a stopword or a bare number); up to 2 stopwords and 1 non-topic word inside;
* never overlaps the anchor of a link already on the page or already proposed for it (no nested links);
* ranking: topic words net of non-topic words, then words of the target's name (first title segment, e.g.
  "Stripe Checkout" in "Stripe Checkout | Pre-built..."), then fewer words, then earlier.

The link is written in place: `[anchor](target URL)` in the original sentence.

## Search Console steering

Rows on SERP page 2 (`page2_min_position`–`page2_max_position`, at least `min_impressions`) mark their pages as
opportunities: their queries are added to the page's topic (readers literally search for it that way, and the query
can become the anchor), links into them are flagged with the query they boost and listed first.

## Offline heuristic classifier

With m = number of the target's topic words (title + H1 + page 2 queries) mentioned in the paragraph:
relevant = m ≥ 1, confidence = min(0.98, 0.65 + 0.12·m), score = min(9.6, 5 + 1.8·m). Other providers are
described in [CLASSIFIERS.md](CLASSIFIERS.md).
