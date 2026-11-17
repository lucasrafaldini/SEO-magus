# Evaluation methodology

How good is SEO-Magus on large, real sites - not on fixtures written for it? This document is the method; the
code is `src/evaluation/`, the commands are the `eval-*` make targets (see [Running it](#running-it)), and every run writes
`build/eval/report.md`.

- [Why another kind of benchmark](#why-another-kind-of-benchmark)
- [Questions](#questions)
- [Principle: triangulation](#principle-triangulation)
- [Sources and ground truth](#sources-and-ground-truth)
- [Bias catalogue](#bias-catalogue)
- [Tasks](#tasks)
- [Systems and baselines](#systems-and-baselines)
- [Statistics and claims](#statistics-and-claims)
- [Reports and exports](#reports-and-exports)
- [Comparing methodologies and reports](#comparing-methodologies-and-reports)
- [Crawl fidelity](#crawl-fidelity)
- [Scale](#scale)
- [Running it](#running-it)
- [Results so far](#results-so-far)
- [Limitations and next steps](#limitations-and-next-steps)
- [Protocol changes](#protocol-changes)

---

## Why another kind of benchmark

The [benchmarks](BENCHMARKS.md) are small sites whose every expected link is written down: they catch any change of
behaviour exactly, but a handful of hand-written pages cannot say how good the tool is on a 10,000-page site, on real
writing, or in another language. This evaluation measures quality at scale against ground truth that other people
produced for their own reasons (encyclopedia editors, archivists, forum users, readers) and that SEO-Magus never saw.

## Questions

| Question | Task | Ground truth |
| :--- | :--- | :--- |
| Does it propose the links a careful human would write? | **links** (link recovery) | human in-prose links, removed before the run |
| Does it understand what a page is about? | **classification** | human categories, collections, tags |
| Does its internal ranking reflect real importance? | **ranking** | pageviews, downloads, views |
| Can it crawl a big site and see it correctly? | **crawl fidelity** | the rendered site itself |
| Does cost stay reasonable as sites grow? | **scale** | the exhaustive flow (must give identical links) |

## Principle: triangulation

Any single benchmark has a bias: one source has one style of writing, one ground truth is incomplete in one way, one
sample over-represents one kind of page, one metric rewards one kind of error. The answer is not to pick the least
biased benchmark but to use all of them, with biases that differ, and to accept a claim only when it survives every
one. Concretely, a claim such as "SEO-Magus proposes links better than the exact-title baseline" is **supported**
only if it is significant:

* on **every real source** that can test it (encyclopedia, archive, Q&A forum, crawled site...),
* under **every sampler** (random, snowball, label-stratified, popularity-stratified) and **every seed**,
* for each **removal protocol** separately (cold page, page with missing links),
* after **correcting for the number of comparisons** (Holm-Bonferroni within each run, then replication),
* with the **protocol fixed before looking at results** (its hash is printed in every report).

Wherever a ground truth is known to be incomplete or circular, a **second, independent layer** measures how much that
matters (below). Synthetic data is used where only construction can tell the truth, and never as evidence about
real-world quality.

## Sources and ground truth

Each source is converted to one corpus format (`src/evaluation/corpus.py`) carrying up to five ground-truth layers;
a task runs on a corpus only if the corpus has the layer the task needs, so a missing layer is reported as "skipped",
never as a zero.

| Source | Access path(s) | links | extra_links | labels | popularity | clickstream |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Wikipedia** (any language) | MediaWiki Action API: `action=parse` HTML, `prop=links`, `prop=categories`, `prop=pageviews`; clickstream dump | editors' in-prose links | every wikilink (navboxes, templates) | visible categories (seed category first) | 60-day pageviews | reader navigation, with and without a link |
| **Internet Archive** | `advancedsearch.php` | links inside descriptions (sparse) | - | collection (seed first), other collections, subjects | downloads | - |
| **Stack Exchange** (data dump) | `Posts.xml`, `PostLinks.xml` (CC BY-SA, mirrored on the Internet Archive) | links in questions and answers | "linked" and "duplicate" relations | tags | views | - |
| **Any website** (or a local mirror, e.g. Kiwix) | SEO-Magus's crawler, or a saved crawl | the site's in-prose links | its other content links | - (never from URLs) | - (attach analytics) | - |
| **Synthetic** | generator (`sources/synthetic.py`) | planted, with their style | - | planted topic | hidden importance + noise | planted reader demand |

The same prose extractor (`sources/prose.py`) decides for every HTML source what an in-prose link is: text inside
`<p>`, without infoboxes, navigation boxes, reference markers, edit links or figures, with the anchor text and its
paragraph. Links through redirects are resolved to the article they land on.

**Two independent link layers** answer "is the human link set complete?": precision is reported against the in-prose
links (strict) and against every human link of the page (`lenient P`). On Wikipedia, the **clickstream** adds a third,
reader-side view: pairs readers navigate between without a link are evidence of a missing link (`reader P`). On
synthetic corpora, valid mentions that were deliberately left unlinked measure the same thing exactly (`FP valid`).

## Bias catalogue

| # | Bias | How it enters | Control | Where |
| ---: | :--- | :--- | :--- | :--- |
| 1 | Domain | one kind of site (encyclopedia) has one writing style | encyclopedia, archive catalogue, Q&A forum, arbitrary sites, three synthetic site styles | `sources/` |
| 2 | Access path | HTML, API and dumps expose different links | several paths per source, one prose extractor for all | `sources/prose.py` |
| 3 | Incomplete gold | editors link a term once, not every useful link | lenient precision, reader-validated precision, planted valid mentions | `tasks.link_task` |
| 4 | Circularity | editor anchors often contain the target title, which favours mention-based linking | difficulty strata (`names-2+`, `names-1`, `names-0`), the anchor ceiling, an exact-title baseline and a mention-free similarity baseline | `tasks.mention_stratum` |
| 5 | Label granularity | Wikipedia categories are fine-grained and arbitrary | category-stratified sampling (seed categories are the labels); corpora with too many labels are skipped | `protocol.max_label_ratio` |
| 6 | Chance-inflated metrics | NMI rewards many clusters even at random | ARI (chance-corrected) is primary; random baseline in every task | `protocol.primary_metric` |
| 7 | Sampling | a random sample is dominated by the most common page type | four samplers; a claim must hold under all | `sampling.py` |
| 8 | Range restriction | sampling only popular items shrinks correlations | archive items drawn in identifier order, never by downloads; popularity-stratified sampler | `sources/internet_archive.py` |
| 9 | Luck | one seed, one sample | three seeds; every value shown with its min-max range | `protocol.seeds` |
| 10 | Multiple comparisons | many benchmarks produce false wins by chance | Holm-Bonferroni within each run; a claim must replicate in every run and on every real source | `protocol.holm`, `runner.summarize` |
| 11 | Researcher degrees of freedom | choosing metrics or samples after seeing results | pre-registered protocol, hashed in every report; changes logged below | `protocol.py` |
| 12 | Generator bias | the synthetic generator is written by the same project | synthetic results never count as evidence for classification and ranking; links reported per planted style; biases found in the generator listed in its docstring | `runner.evidence_role` |
| 13 | Language | English-only tokenization quirks | Portuguese synthetic corpus; any Wikipedia language edition | `--lang`, `--language` |
| 14 | Scale | small sites hide cost and noise | corpora of thousands of pages; scale task up to 10,000+ | `scale.py` |
| 15 | Confounded importance | long or heavily linked pages look important for any scorer | length and in-degree baselines next to PageRank | `systems.SCORERS` |
| 16 | Leakage | the removed link stays visible | removed links leave the graph and the page's anchors; only their words remain, as on a real page missing the link; kept links are excluded from scoring | `Corpus.to_pages` |
| 17 | Drift | live sources change every day | provenance, content fingerprint, record/replay cache of every API response | `sources/http.py` |
| 18 | Measurement artefacts | the test server, not the crawler, limits throughput | listen backlog fixed; throughput reported as a lower bound | `crawl_eval.py` |

## Tasks

### Link recovery (`links`)

For each sampled page, its human in-prose links are removed - all of them (**cold**: a page written without links)
or a random half (**holdout**: a page with missing links; the other half stays as existing links) - and every system
proposes links for those pages, with the whole corpus as possible targets. A proposal is correct when it points to a
removed target (one link per source-target pair, as SEO-Magus proposes at most one).

* **primary**: micro F1 over pairs; also micro/macro precision and recall, with bootstrap CIs;
* **recall by stratum**: `names-2+` (the anchor names at least two words of the target title - the only ones an
  anchor-based linker can reach), `names-1`, `names-0`; the share of `names-2+` links is the **anchor ceiling**;
* **lenient P**, **reader P**, **FP valid**: how much of the "error" is incomplete ground truth (see above);
* **recall by planted style** (synthetic): full title, inflected, partial, alias, generic;
* **PR rebuilt**: Spearman between the PageRank of the intact site and the PageRank after adding the proposals to the
  stripped site, next to the stripped site's own value - do the proposals rebuild the editors' equity distribution?

### Classification (`classification`)

Every page is clustered; the sampled pages' clusters are compared with their primary human label. **Primary: ARI**
(chance-corrected); also NMI, purity (penalizes merging topics) and inverse purity (penalizes splitting them).

### Ranking (`ranking`)

Every page gets an importance score from the site's own link graph; on the sampled pages it is correlated with
external popularity. **Primary: Spearman**; also Kendall tau-b and NDCG@10/@100 (gain = log(1 + popularity)).

## Systems and baselines

Every system gets the same input through the same interface (`src/evaluation/systems.py`) and is scored by the same
code. Baselines are chosen to expose specific weaknesses, not to be easy to beat.

| Task | System | Kind | What it tests |
| :--- | :--- | :--- | :--- |
| links | `seo-magus` | product | the tool as a user runs it on an unknown site (no taxonomy) |
| links | `seo-magus+content`, `seo-magus+structure` | product | topic boundaries from content clustering / link communities, no configuration |
| links | `seo-magus+labels` | oracle | topic boundaries from the human labels: the upper bound of a perfect taxonomy |
| links | `exact-title` | baseline | link wherever a full title is written (classic wikifier): do the classifier and anchor rules add anything? |
| links | `title-overlap` | baseline | >= 2 title words anywhere on the page: the raw lexical signal |
| links | `similar-content` | baseline | the 5 most similar pages (TF-IDF): a recommender with different failure modes |
| links | `random` | baseline | chance level |
| classification | `seo-magus` | product | what the tool does without configuration: one cluster |
| classification | `content-sqrt`, `structure` | product | TF-IDF k-means (k = sqrt(n/2)), link-graph label propagation |
| classification | `content-k` | oracle | k-means told the true number of labels |
| classification | `url-folders`, `random` | baseline | what a URL-pattern taxonomy encodes; chance |
| ranking | `pagerank`, `cheirank` | product | internal PageRank / CheiRank of the site's link graph |
| ranking | `in-degree`, `length`, `random` | baseline | cheap alternatives and confounders; chance |

Oracles are reported but never compared as products: they show what a perfect input would change.

## Statistics and claims

* Uncertainty: percentile bootstrap over sampled documents (1,000 resamples, 95%). All systems of a run are scored on
  the **same** resamples, so paired differences cancel document difficulty.
* Comparison: every product/oracle system against every baseline on the primary metric; one-sided
  p = (resamples where the system does not beat the baseline + 1) / (resamples + 1), never 0.
* Correction: Holm-Bonferroni over the comparisons of each run (alpha 0.05). Chance wins across the many runs are
  controlled by **replication**: a claim must be significant in every run of every real source. (A single
  report-wide family of ~2,000 comparisons would need p < 2.5×10⁻⁵, finer than 1,000 bootstrap resamples can
  resolve - "significant" would silently mean "p = 0", an artefact of the estimator.)
* Per corpus: `robust` = significant after correction in every sampler x seed run; `mixed` = in some; `no` = none;
  `worse` = the baseline significantly better somewhere; `insufficient data` = fewer than 30 documents.
* Across sources: **supported on every real source** only if `robust` on each real corpus that has the layer;
  `untested on real data` when only synthetic or tiny corpora could test it.

The whole protocol is `src/evaluation/protocol.py`; the report prints its version and hash.

## Reports and exports

Every run writes its results at two levels (`run --export simple|full`, default full; `export` re-writes them from a
`report.json`, e.g. after updating the report code):

| Level | File | Contents | Use it for |
| :--- | :--- | :--- | :--- |
| simple | `report.md` | at a glance, claims matrix, scores, ranks, methodologies, meta-analysis, diagnostics, crawl, scale | reading |
| simple | `summary.csv` | one row per task x protocol x corpus x system: runs, mean, median, sd, min, max, skill, rank in the corpus, win rate and mean difference against the strongest baseline | spreadsheets |
| simple | `claims.csv` | one row per claim: status and the verdict on every corpus | tracking claims |
| simple | `report.json` | the raw report, source of every other file | re-exporting |
| full | `runs.csv`, `results.jsonl` | **tidy rows**: every metric of every system in every methodology cell (schema below) | pivot tables, notebooks, dashboards |
| full | `analysis.json` | every calculation below | automation |
| full | `report.html` | self-contained visual report: claims matrix, score heatmaps, rank diagrams, methodology agreement, variance bars, forest plots, scale chart | sharing |

**Tidy schema** (`src/evaluation/results.py`), one row per number:
`report, protocol_version, protocol_hash, corpus, source, language, fingerprint, evidence, task, protocol, sampler,
seed, system, kind, metric, value, ci_low, ci_high, units`. Metrics: the primary one (`f1`, `ari`, `spearman`, with its
bootstrap CI), `skill`, the secondary ones (`precision`, `recall`, `nmi`, `ndcg@10`...), `recall[names-2+]` and
`recall[style:full]`, and the paired comparisons `difference[<baseline>]` (with the CI of the paired difference) and
`significant[<baseline>]`. Any view is a filter and a group-by away, e.g. `metric == "f1"` grouped by `sampler` to see
whether the sampler matters.

### Calculations

Simple, to read at a glance:

* **describe** - runs, mean, median, sd, min, max per task x protocol x corpus x system.
* **skill** - `(value - random) / (1 - random)`, with `random` the random baseline of the same cell: 0 = chance,
  1 = perfect, negative = worse than chance. It puts F1, ARI and Spearman on one scale, so results of different
  tasks and sources can sit side by side (the HTML colours every score by it).
* **wins** - for each system against each baseline: cells won, tied and lost, win rate, mean difference, and the
  share of runs significant after correction.

Complex, to compare without over-reading:

* **ranks** - every methodology cell (corpus x protocol x sampler x seed) ranks the systems; the Friedman test says
  whether they differ at all, the Nemenyi critical difference which ones differ from the best (Demsar 2006, the
  standard way to compare several systems over several datasets).
* **agreement** - for each factor (corpus, protocol, sampler, seed), the systems are ranked under each of its levels;
  Kendall's W measures how much those rankings agree, with the winner per level. A low W, or a winner that changes,
  means the conclusion depends on that methodological choice.
* **sensitivity** - eta²: the share of each system's score variance explained by each factor alone. It says which
  choice moves the numbers most (today: the corpus explains 86% of SEO-Magus's link F1 variance, the sampler 0%).
* **meta-analysis** - each system-vs-baseline difference pooled across corpora with random effects
  (DerSimonian-Laird), with I² heterogeneity; once over every corpus and once over the real sources only. Per corpus
  the variance is the mean squared standard error of its runs: runs of one corpus overlap, so they are not counted as
  independent evidence.

Every statistic is checked against published reference values in `tests/test_evaluation_reports.py` (chi-square
critical values, Friedman against the classic formula, Kendall's W against its identity with Spearman, the exact
Wilcoxon test against brute-force enumeration, the random-effects model against a hand-computed example).

## Comparing methodologies and reports

**Inside one report**, the "Methodologies compared" section answers "would another methodology tell another story?"
(agreement and sensitivity above), and the rank and meta-analysis sections pool across methodologies only with
tests made for it.

**Across reports** (another code version, protocol, sample size, set of sources), `compare` takes the first report as
the reference:

| Mode | When | What is compared |
| :--- | :--- | :--- |
| direct | same protocol hash and, for every shared corpus, the same data fingerprint | cells are paired (same corpus, task, protocol, sampler, seed); each system's change is tested with the Wilcoxon signed-rank test over paired cells (exact up to 25 cells, ties included), Holm-corrected over the systems that changed |
| indirect | the protocol or the data differ | only scale-free quantities - mean skill and average rank of each system - with the reasons listed and no significance claimed |

In both modes Kendall's tau between the two rankings of the systems says whether the two evaluations agree on what is
better. Settings that keep cells pairable but change the methodology (documents per run, cells present in one report
only) are listed as notes: the paired changes then measure the effect of that choice.

```bash
make eval-compare REPORTS="build/eval-old/report.json build/eval/report.json"
python -m src.evaluation compare A/report.json B/results.jsonl C/runs.csv --labels before after other --out build/cmp
```

Outputs: `compare.md` (read), `compare.csv` (one row per report pair x task x protocol x system), `compare.json`.

## Crawl fidelity

A corpus is rendered as a static website - one page per document, its human links as real `<a>` elements in the
paragraphs, a navigation bar and footer around them, robots.txt and an XML sitemap - served on localhost and crawled
by the real crawler over HTTP. Reported: coverage, exact titles, exact paragraph text, content-link recall and
precision against the rendered links, navigation links misread as content, and throughput. Throughput is a lower
bound: the test server runs in the same Python process as the crawler.

## Scale

Synthetic sites of growing size (topics grow with the site) run through the link flow; the exhaustive flow
(`LinkingOptimizer(prune=False)`, every pair and every paragraph) runs too on the smaller sizes and must give
**identical** links. Reported: seconds, classifier calls (the paid part with an API classifier), links, memory, and
the fitted exponents of time ~ n^b and calls ~ n^b (1 = linear, 2 = quadratic).

## Running it

```bash
make eval-smoke                     # a few minutes: the whole pipeline on a small synthetic corpus
make eval                           # offline: synthetic corpora, full protocol, crawl fidelity, scale (~30 min)
```

Real sources (network access required; every response is cached under `build/eval/cache/` for offline replay):

```bash
make eval-wikipedia CONTACT=you@example.com                     # English, six seed categories, 1,200 articles
make eval-wikipedia CONTACT=you@example.com WIKI_LANG=pt WIKI_CATEGORIES="Compostagem Xadrez"
make eval-archive CONTACT=you@example.com                       # prelinger, gutenberg, librivoxaudio
make eval-stackexchange SE_DUMP=~/dumps/gardening SE_SITE=gardening.stackexchange.com
make eval-run                                                    # every corpus in build/eval/corpora
```

* **CONTACT** is mandatory for live sources: it goes into the User-Agent, as
  [Wikimedia's User-Agent policy](https://meta.wikimedia.org/wiki/User-Agent_policy) requires. Requests are serial,
  rate-limited (`--interval`) and retried politely.
* **Replay**: `python -m src.evaluation wikipedia ... --offline` (or `make eval-wikipedia OFFLINE=1`, same for
  `eval-archive`) rebuilds a corpus from the cache only. Without network access a live fetch stops with a clear error
  (exit 2) instead of a traceback.
* **Logs**: make runs the evaluation at `EVAL_LOG_LEVEL=WARNING` (its own progress lines say what runs); set
  `EVAL_LOG_LEVEL=INFO` for the milestones of every component, and see `make logs` for what each step did.
* **Clickstream**: download a monthly file from dumps.wikimedia.org (`other/clickstream/`), then
  `python -m src.evaluation clickstream --corpus build/eval/corpora/wikipedia-en.jsonl.gz --tsv clickstream-enwiki-<month>.tsv.gz`.
* **Stack Exchange**: download a site's archive from archive.org/details/stackexchange, extract `Posts.xml` and
  `PostLinks.xml` into a directory. Small sites (gardening, cooking, writers) are a few MB.
* **Your own site**: `python -m src.evaluation crawl --url https://your-site.example/ --out build/eval/corpora/mine.jsonl.gz`.
* **Inspect** any corpus: `python -m src.evaluation info FILE` (documents, links, labels, layers, provenance).
* Narrow a run with `ARGS`, e.g. `make eval-run ARGS="--tasks links --samplers random --seeds 1"`.

### Command reference (`python -m src.evaluation <command>`)

| Command | Options | Does |
| :--- | :--- | :--- |
| `synthetic` | `--pages`, `--topics`, `--preset` (encyclopedia, catalog, forum), `--language` (en, pt), `--seed`, `--out` | generate a corpus with ground truth by construction |
| `wikipedia` | `--lang`, one of `--seeds` / `--categories` / `--random`, `--limit`, `--seed`, `--name`, `--out`, `--contact`, `--cache`, `--offline`, `--interval` | sample a Wikipedia edition |
| `archive` | `--collections`, `--mediatype`, `--limit`, `--seed`, `--name`, `--out`, `--contact`, `--cache`, `--offline`, `--interval` | sample Internet Archive collections |
| `stackexchange` | `--dump`, `--site`, `--tags`, `--limit`, `--seed`, `--name`, `--out` | import a Stack Exchange data dump |
| `crawl` | `--url` or `--from-crawl`, `--max-pages`, `--limit`, `--seed`, `--name`, `--out` | a website (or a saved crawl) as a corpus |
| `clickstream` | `--corpus`, `--tsv`, `--lang`, `--out` | attach a Wikipedia clickstream dump |
| `run` | corpora, `--out`, `--tasks`, `--samplers`, `--seeds`, `--sample-size`, `--protocols`, `--systems`, `--config`, `--export` (simple, full) | run the protocol and write the [reports and exports](#reports-and-exports) |
| `export` | report.json, `--out`, `--level` (simple, full), `--label` | re-write the exports of a report |
| `compare` | reports (report.json, results.jsonl or runs.csv), `--labels`, `--out` | [compare reports](#comparing-methodologies-and-reports) |
| `crawl-fidelity` | corpora, `--out`, `--concurrency` | render, serve, crawl and compare |
| `scale` | `--sizes`, `--preset`, `--seed`, `--exhaustive-max`, `--out` | time and classifier calls against size |
| `info` | corpora | documents, links, labels, layers, provenance |

`-v`, `--log-level LEVEL` and `--log-file FILE` (before the command) control the logs, as for the main CLI. `run --config config/sites/<site>.yaml` makes the SEO-Magus systems use that
config's classifier (e.g. an LLM) instead of the offline heuristic; the classifier-call counts of the scale task give
the budget.

## Results so far

Measured with `make eval` in this repository's development environment, which has **no access to Wikipedia, the
Internet Archive or Stack Exchange**: only four synthetic corpora (2,000-3,000 pages; encyclopedia, catalog and
forum styles; English and Portuguese) and one real-HTML crawl of 10 pages were available. **No real-world quality
claim is established yet**: every claim in the report reads "untested on real data", and the bias checklist flags the
missing independent real sources. What the offline runs do show:

* **Scale**: 10,000 pages in 46 s with 35,022 classifier calls (heuristic classifier); time ~ n^1.16, classifier
  calls ~ n^1.06. At 300 pages the exhaustive flow needed 622,420 classifier calls and 59 s for **identical** links
  (872 calls, 0.8 s with pruning). Before pruning, 10,000 pages meant ~8×10⁸ classifier calls.
* **Crawl fidelity**: four rendered sites, 9,000 pages in total (including Portuguese text): coverage, titles,
  paragraphs, content-link recall and precision all 1.000, no navigation link misread as content; 69-107 pages/s as
  a lower bound.
* **Link recovery, by construction** (synthetic; F1 mean over 12 runs per cell): SEO-Magus 0.30-0.66 against
  0.20-0.51 for the exact-title baseline, significant in every run of every synthetic corpus under both protocols.
  It recovers 96-100% of the links whose anchor names two or more title words and almost none of the others, so its
  recall is bounded by the share of such links (the anchor ceiling: 0.21 forum, 0.42 encyclopedia, 0.64 catalog).
  77-92% of its "false positives" are mentions the planted editors left unlinked: strict precision (0.49-0.74
  across runs) understates it. Its proposals bring the PageRank distribution slightly closer to the editors' (0.976 vs 0.973 for
  the stripped site on the encyclopedia), while every baseline's proposals move it further away (0.93-0.95).
* **Topic boundaries cost recall**: every variant that restricts links to a topic cluster (content clusters, link
  communities, even the true labels) scores a lower F1 than no boundary at all, on every synthetic corpus; boundaries
  from link communities collapse when the links are what is missing (F1 0.00 on the 10-page crawl, 0.10 on the forum).
* **Warning signs to check on real data**: on the only real-HTML corpus (10 pages, too small for evidence) the simple
  baselines beat SEO-Magus (exact-title 0.78, title-overlap 0.82, SEO-Magus 0.68 in the cold protocol).
* **Classification and ranking** (code validation only): without configuration SEO-Magus puts every page in one
  cluster (ARI 0); the new content clustering reaches ARI 0.72-0.80 and link communities 0.75-0.98 on synthetic
  topics. In-degree tracks synthetic popularity better than PageRank (0.65-0.73 vs 0.54-0.64) - to be re-checked
  on real pageviews, downloads and views before drawing any conclusion.
* **Methodologies compared**: the systems' link ranking is the same under every sampler (Kendall's W 1.00), seed
  (0.99) and removal protocol (0.96), but not under every corpus (W 0.77: exact-title wins on the 10-page real crawl).
  The corpus explains 86% of the variance of SEO-Magus's link F1, the protocol 7%, the sampler and the seed 0%: the
  conclusions hinge on the data sources, not on sampling choices - which is why real sources are the priority.
  Over all 120 link cells SEO-Magus has the best average rank (1.62), statistically tied only with its oracle variant
  (Nemenyi CD 0.96); pooled across the five corpora its F1 advantage over exact-title is +0.11 [0.08, 0.15] (cold)
  with I² 87% - it depends on the source.
* **Sample size** (a second run with 100 instead of 200 documents per run, compared with `compare`): no score changes
  significantly over the 72 paired cells (largest mean change of a non-random system +0.011, +0.008 for link F1; the
  random baseline moves most, +0.044 Spearman, as chance fluctuates more in smaller samples), and every task keeps the
  same best system
  (Kendall's tau between the two rankings 0.86-1.00) - cheaper runs are good enough to iterate, the full size is for
  the record.
* The full report is `build/eval/report.md` and `report.html`, with every number in `runs.csv` / `analysis.json`.

Findings about the evaluation itself, fixed before any real data (each would have biased results):

* the exhaustive link flow was quadratic (pairs x paragraphs classifier calls); pruning made it near-linear with
  identical results (`docs/ALGORITHMS.md`);
* the first synthetic generator made content clustering perfect (disjoint topic vocabularies) and made in-degree win
  ranking by construction (popularity was computed from inbound links); both fixed;
* NMI gave a random 22-cluster labelling 0.35: the primary classification metric is ARI;
* the mock server's listen backlog of 5 made concurrent crawls slower than serial ones; fixed;
* a report-wide Holm family (~2,000 comparisons) with 1,000-resample bootstrap p-values made "significant" mean
  "p = 0 exactly" (an estimator artefact): p-values now use (count + 1) / (B + 1) and the family is the run, with
  replication across runs and sources as the guard against chance wins;
* the first "PageRank without the removed links" removed edges from the graph's dictionaries but not from its
  networkx copy, so PageRank never changed (a tell-tale Spearman of exactly 1.000): graphs are now rebuilt from
  scratch, and a test checks two invariants - removing links lowers the agreement, and proposing exactly the removed
  links restores it to 1.

## Limitations and next steps

* **No real data yet**: run `make eval-wikipedia eval-archive eval-stackexchange eval-run` where the network is
  available; adapters are tested against the documented response formats, the first live run should be checked with
  `python -m src.evaluation info` (and its cache can become a test fixture).
* **Classifier**: the runs above use the offline heuristic classifier, which (as the pruning analysis showed) adds
  no judgement beyond word overlap on the benchmark sites. Measuring an LLM classifier is one option away
  (`run --config`); its cost scales with the classifier calls reported by the scale task.
* **Human adjudication**: a random sample of "false positives" judged by people would calibrate the incompleteness
  estimates on real sources (protocol to be added; the report already lists the pairs in `report.json`).
* **More sources**: Wikidata (instance-of classes as labels), Common Crawl (arbitrary sites at scale), Project
  Gutenberg's catalogue (Library of Congress classes), Curlie/DMOZ (a human web directory).
* Content clustering is evaluated but not yet wired into the product's configuration (it can be: `SiteTaxonomy`
  accepts explicit `assignments`).

## Protocol changes

| Version | Change | Why |
| :--- | :--- | :--- |
| 1.0 | initial protocol | - |
