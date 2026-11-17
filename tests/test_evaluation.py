"""
The evaluation harness itself (src/evaluation/): an evaluator that is wrong makes
every benchmark wrong, so metrics are checked against hand-computed and published
values, and every building block against its documented contract.

Sources are tested in test_evaluation_sources.py; the crawl-fidelity run over
HTTP is in the integration tier at the end of this file.
"""

import gzip
import itertools
import json
import math
import random
import tempfile
import unittest
import warnings
from pathlib import Path

import pytest

from src.engines.clustering import label_propagation, spherical_kmeans, suggested_k, tfidf_vectors
from src.engines.taxonomy import SiteTaxonomy
from src.evaluation import metrics, sampling, systems, tasks
from src.evaluation.corpus import Corpus, Document, GoldLink, Provenance
from src.evaluation.protocol import PROTOCOL, holm, protocol_hash
from src.evaluation.sources.synthetic import LINK_STYLES, SyntheticSpec, generate


def tiny_corpus() -> Corpus:
    """Four documents, hand-made: every number derived from it below can be checked by hand."""
    base = "https://t.example/wiki/"
    docs = [
        Document(base + "Compost_Bin", "Compost Bin", ["A compost bin holds kitchen scraps.",
                                                      "Read about worm farming basics and the garden soil guide."],
                 [GoldLink(base + "Worm_Farming", "worm farming", 1), GoldLink(base + "Garden_Soil", "garden soil guide", 1)],
                 [base + "Garden_Soil"], ["composting"], 100.0),
        Document(base + "Worm_Farming", "Worm Farming", ["Worm farming turns scraps into castings for a compost bin."],
                 [GoldLink(base + "Compost_Bin", "compost bin", 0)], [], ["composting"], 50.0),
        Document(base + "Garden_Soil", "Garden Soil", ["Garden soil needs compost."],
                 [GoldLink(base + "Missing_Page", "missing", 0), GoldLink(base + "Garden_Soil", "self", 0)],
                 [], ["soil"], 10.0),
        Document(base + "Clay", "Clay", ["Clay is heavy."], [], [], ["soil"], None),
    ]
    return Corpus("tiny", docs, Provenance("test", "hand-made")).closed()


class TestLinkMetrics(unittest.TestCase):
    def test_precision_recall_f1_by_hand(self):
        counts = metrics.link_counts({"a", "b", "c"}, {"b", "c", "d", "e"})
        self.assertEqual(counts, metrics.LinkCounts(tp=2, predicted=3, gold=4))
        p, r, f = metrics.prf(counts)
        self.assertEqual((p, r), (2 / 3, 0.5))
        self.assertAlmostEqual(f, 2 * (2 / 3) * 0.5 / (2 / 3 + 0.5))
        self.assertEqual(metrics.prf(metrics.LinkCounts(0, 0, 3)), (0.0, 0.0, 0.0))   # no prediction: P = 0

    def test_micro_pools_pairs_macro_averages_documents(self):
        units = [metrics.LinkCounts(1, 1, 1), metrics.LinkCounts(0, 3, 1), metrics.LinkCounts(0, 0, 2)]
        self.assertEqual(metrics.micro_prf(units)[:2], (1 / 4, 1 / 4))
        p, r, _ = metrics.macro_prf(units)
        self.assertEqual(p, (1 + 0) / 2)          # documents without predictions do not count for precision
        self.assertEqual(r, (1 + 0 + 0) / 3)


class TestClassificationMetrics(unittest.TestCase):
    def test_published_values(self):
        # scikit-learn documentation examples (adjusted_rand_score, normalized_mutual_info_score).
        self.assertAlmostEqual(metrics.adjusted_rand_index([0, 0, 1, 1], [0, 0, 1, 2]), 0.5714285714285715)
        self.assertAlmostEqual(metrics.nmi([0, 0, 1, 1], [0, 0, 1, 2]), 0.8)
        self.assertEqual(metrics.adjusted_rand_index([0, 0, 1, 1], [1, 1, 0, 0]), 1.0)   # label names do not matter
        self.assertAlmostEqual(metrics.adjusted_rand_index([0, 0, 0, 0], [0, 1, 2, 3]), 0.0)

    def test_purity_and_inverse_purity_catch_opposite_failures(self):
        truth = ["a", "a", "b", "b"]
        singletons, one = [1, 2, 3, 4], [0, 0, 0, 0]
        self.assertEqual((metrics.purity(truth, singletons), metrics.inverse_purity(truth, singletons)), (1.0, 0.5))
        self.assertEqual((metrics.purity(truth, one), metrics.inverse_purity(truth, one)), (0.5, 1.0))

    def test_nmi_is_not_chance_corrected_but_ari_is(self):
        # Why the protocol uses ARI as primary metric: random many-cluster labellings get a clearly positive NMI.
        rng = random.Random(0)
        truth = [rng.randrange(5) for _ in range(200)]
        noise = [rng.randrange(40) for _ in range(200)]
        self.assertGreater(metrics.nmi(truth, noise), 0.15)
        self.assertLess(abs(metrics.adjusted_rand_index(truth, noise)), 0.05)
        self.assertEqual(PROTOCOL["primary_metric"]["classification"], "ari")


class TestRankingMetrics(unittest.TestCase):
    def test_kendall_tau_b_equals_the_naive_definition(self):
        def naive(x, y):
            concordant = discordant = ties_x = ties_y = 0
            for i, j in itertools.combinations(range(len(x)), 2):
                a, b = (x[i] > x[j]) - (x[i] < x[j]), (y[i] > y[j]) - (y[i] < y[j])
                if a == 0 and b == 0:
                    continue
                if a == 0:
                    ties_x += 1
                elif b == 0:
                    ties_y += 1
                elif a == b:
                    concordant += 1
                else:
                    discordant += 1
            denominator = math.sqrt((concordant + discordant + ties_x) * (concordant + discordant + ties_y))
            return (concordant - discordant) / denominator if denominator else 0.0

        rng = random.Random(1)
        for _ in range(200):
            n = rng.randint(2, 30)
            x, y = [rng.randint(0, 5) for _ in range(n)], [rng.randint(0, 5) for _ in range(n)]
            self.assertAlmostEqual(metrics.kendall_tau_b(x, y), naive(x, y), places=12)

    def test_spearman_ties_and_extremes(self):
        self.assertEqual(metrics.average_ranks([10, 20, 20, 30]), [1.0, 2.5, 2.5, 4.0])
        self.assertAlmostEqual(metrics.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(metrics.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertEqual(metrics.spearman([1, 1, 1], [1, 2, 3]), 0.0)   # constant input: no correlation

    def test_ndcg_by_hand(self):
        ids, scores, relevance = ["a", "b", "c"], [3.0, 2.0, 1.0], [0.0, 1.0, 2.0]
        dcg = 0 / math.log2(2) + 1 / math.log2(3) + 2 / math.log2(4)
        idcg = 2 / math.log2(2) + 1 / math.log2(3) + 0
        self.assertAlmostEqual(metrics.ndcg_at_k(ids, scores, relevance, 3), dcg / idcg)
        self.assertEqual(metrics.ndcg_at_k(ids, [1, 1, 1], [1, 1, 1], 2), 1.0)
        self.assertEqual(metrics.ndcg_at_k(["b", "a"], [1, 1], [0, 1], 1), 1.0)   # ties broken by id, not input order


class TestUncertainty(unittest.TestCase):
    def test_bootstrap_is_seeded_and_brackets_the_estimate(self):
        values = [random.Random(2).gauss(0, 1) for _ in range(50)]
        mean = lambda xs: sum(xs) / len(xs)
        a, b = metrics.bootstrap(values, mean, 300, seed=4), metrics.bootstrap(values, mean, 300, seed=4)
        self.assertEqual(a, b)
        self.assertLessEqual(a.low, a.value)
        self.assertLessEqual(a.value, a.high)
        self.assertEqual(metrics.bootstrap([1.0], mean), metrics.Estimate(1.0, 1.0, 1.0))

    def test_paired_comparison_detects_a_consistent_difference(self):
        better = metrics.paired_bootstrap(list(range(40)), lambda u: 1.0 + len(u) * 0, lambda u: 0.0, 200, 1)
        self.assertEqual((better.verdict, better.p_not_better), ("better", 1 / 201))   # never exactly 0
        draws = metrics.resamples(30, 100, 3)
        self.assertEqual(draws, metrics.resamples(30, 100, 3))
        tie = metrics.compare_from(0.5, 0.5, [0.5] * 100, [0.5] * 100)
        self.assertEqual((tie.verdict, tie.p_not_better), ("not significant", 1.0))

    def test_holm_correction_textbook_example(self):
        # p = 0.01, 0.04, 0.03, 0.005 with alpha 0.05: thresholds 0.0125, 0.0167, 0.025, 0.05 in p order.
        rejected = holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.005}, alpha=0.05)
        self.assertEqual(rejected, {"d": True, "a": True, "c": False, "b": False})   # step-down stops at c


class TestProtocol(unittest.TestCase):
    def test_protocol_is_hashed_and_complete(self):
        self.assertEqual(len(protocol_hash()), 12)
        for key in ("version", "link_protocols", "samplers", "seeds", "primary_metric", "alpha", "min_units"):
            self.assertIn(key, PROTOCOL)
        self.assertEqual(set(PROTOCOL["samplers"]), set(sampling.SAMPLERS))


class TestCorpus(unittest.TestCase):
    def test_closed_world_and_layers(self):
        corpus = tiny_corpus()
        garden = corpus.get("https://t.example/wiki/Garden_Soil")
        self.assertEqual(garden.links, [])                        # dangling and self links dropped
        self.assertEqual(corpus.layers, {"links", "extra_links", "labels", "popularity"})
        self.assertEqual(len(corpus.gold_pairs()), 3)

    def test_save_load_round_trip_and_fingerprint(self):
        corpus = tiny_corpus()
        corpus.clickstream = {(corpus.ids[0], corpus.ids[1]): {"link": 12}}
        corpus._fingerprint = None
        with tempfile.TemporaryDirectory() as tmp:
            loaded = Corpus.load(corpus.save(Path(tmp, "c.jsonl.gz")))
            with gzip.open(Path(tmp, "c.jsonl.gz"), "rt", encoding="utf-8") as handle:
                header = json.loads(handle.readline())
        self.assertEqual(loaded.documents, corpus.documents)
        self.assertEqual(loaded.clickstream, corpus.clickstream)
        self.assertEqual(loaded.fingerprint(), corpus.fingerprint())
        self.assertEqual((header["format"], header["documents"]), ("seo-magus/corpus", 4))

    def test_invalid_files_and_duplicates_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp, "bad.jsonl.gz")
            with gzip.open(bad, "wt") as handle:
                handle.write('{"format": "something-else"}\n')
            with self.assertRaisesRegex(ValueError, "not a seo-magus/corpus file"):
                Corpus.load(bad)
        doc = Document("https://x/a", "A", ["a"])
        with self.assertRaisesRegex(ValueError, "duplicate document ids"):
            Corpus("dup", [doc, doc], Provenance("test", "x"))

    def test_to_pages_removes_links_but_keeps_their_words(self):
        corpus = tiny_corpus()
        bin_page = corpus.ids[0]
        removed = {(bin_page, "https://t.example/wiki/Worm_Farming")}
        page = next(p for p in corpus.to_pages(removed) if p.url == bin_page)
        self.assertEqual(page.existing_internal_links, ["https://t.example/wiki/Garden_Soil"])
        self.assertIn("worm farming", page.paragraphs[1])
        self.assertEqual([l.anchor_text for l in page.links], ["garden soil guide"])

    def test_subset_is_closed_over_the_chosen_documents(self):
        part = tiny_corpus().subset(["https://t.example/wiki/Worm_Farming", "https://t.example/wiki/Clay"])
        self.assertEqual(part.ids, ["https://t.example/wiki/Worm_Farming", "https://t.example/wiki/Clay"])
        self.assertEqual(part.gold_pairs(), set())


class TestSynthetic(unittest.TestCase):
    def test_deterministic_and_anchors_are_where_they_claim(self):
        spec = SyntheticSpec(pages=150, topics=5, seed=9)
        corpus = generate(spec)
        self.assertEqual(corpus.fingerprint(), generate(spec).fingerprint())
        for doc in corpus.documents:
            for link in doc.links:
                self.assertIn(link.anchor, doc.paragraphs[link.paragraph])
            self.assertFalse(set(doc.meta["alias"].split()) & set(doc.title.lower().split()))
        self.assertEqual(corpus.layers, {"links", "labels", "popularity", "clickstream"})
        self.assertNotEqual(corpus.fingerprint(), generate(SyntheticSpec(pages=150, topics=5, seed=10)).fingerprint())

    def test_style_mix_follows_the_spec(self):
        corpus = generate(SyntheticSpec(pages=400, topics=6, seed=1, styles=(("full", 1.0),)))
        styles = {s for d in corpus.documents for s in d.meta["styles"]}
        self.assertEqual(styles, {"full"})
        default = generate(SyntheticSpec(pages=400, topics=6, seed=1))
        counts = {s: sum(d.meta["styles"].count(s) for d in default.documents) for s in LINK_STYLES}
        self.assertTrue(all(counts[s] > 0 for s in LINK_STYLES))

    def test_presets_languages_and_validation(self):
        catalog = generate(SyntheticSpec(pages=60, topics=3, preset="catalog"))
        self.assertEqual(len({systems._url_folder(i) for i in catalog.ids}), 3)   # URL folders = topics
        portuguese = generate(SyntheticSpec(pages=40, topics=2, language="pt"))
        self.assertIn("também conhecido como", portuguese.documents[0].paragraphs[0])
        self.assertEqual(portuguese.provenance.language, "pt")
        with self.assertRaises(ValueError):
            generate(SyntheticSpec(preset="blog"))
        with self.assertRaises(ValueError):
            generate(SyntheticSpec(language="fr"))


class TestSamplers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = generate(SyntheticSpec(pages=300, topics=6, seed=2))

    def test_every_sampler_is_deterministic_and_sized(self):
        for name, sampler in sampling.SAMPLERS.items():
            with self.subTest(sampler=name):
                first = sampler(self.corpus, 60, 5)
                self.assertEqual(first, sampler(self.corpus, 60, 5))
                self.assertEqual(len(first), len(set(first)))
                self.assertEqual(len(first), 60)
                self.assertNotEqual(first, sampler(self.corpus, 60, 6))

    def test_stratified_samplers_balance_their_strata(self):
        by_label = sampling.sample_by_label(self.corpus, 60, 1)
        labels = [self.corpus.get(i).labels[0] for i in by_label]
        self.assertEqual(set(labels.count(l) for l in set(labels)), {10})
        by_popularity = sampling.sample_by_popularity(self.corpus, 40, 1)
        ordered = sorted(d.popularity for d in self.corpus.documents)
        quartile = lambda p: min(3, ordered.index(p) * 4 // len(ordered))
        counts = [sum(1 for i in by_popularity if quartile(self.corpus.get(i).popularity) == q) for q in range(4)]
        self.assertEqual(counts, [10, 10, 10, 10])

    def test_snowball_follows_links_and_fallbacks_without_layers(self):
        chain = sampling.sample_snowball(self.corpus, 30, 3)
        linked = {t for i in chain for t in self.corpus.get(i).link_targets}
        self.assertGreater(len(set(chain[1:]) & linked), 20)
        bare = Corpus("bare", [Document(f"https://b/{i}", str(i), ["x"]) for i in range(10)], Provenance("t", "t"))
        self.assertEqual(sampling.sample_by_label(bare, 5, 1), sampling.sample_random(bare, 5, 1))
        self.assertEqual(sampling.sample_by_popularity(bare, 5, 1), sampling.sample_random(bare, 5, 1))


class TestClustering(unittest.TestCase):
    def test_tfidf_vectors_are_normalized(self):
        vectors = tfidf_vectors(["compost worms compost", "compost soil clay", "galaxy star orbit", "star planet orbit"])
        for vector in vectors:
            self.assertAlmostEqual(sum(w * w for w in vector.values()), 1.0)

    def test_kmeans_and_label_propagation_separate_obvious_groups(self):
        garden = [f"compost worms soil mulch garden bed {i}" for i in range(6)]
        space = [f"galaxy star orbit planet comet telescope {i}" for i in range(6)]
        labels = spherical_kmeans(tfidf_vectors(garden + space, min_df=1), 2, seed=1)
        self.assertEqual(len(set(labels[:6])), 1)
        self.assertEqual(len(set(labels[6:])), 1)
        self.assertNotEqual(labels[0], labels[6])
        self.assertEqual(labels, spherical_kmeans(tfidf_vectors(garden + space, min_df=1), 2, seed=1))
        nodes = [f"a{i}" for i in range(5)] + [f"b{i}" for i in range(5)]
        edges = [(x, y) for g in ("a", "b") for x in nodes if x[0] == g for y in nodes if y[0] == g and x < y]
        communities = label_propagation(nodes + ["alone"], edges + [("a0", "b0")], seed=2)
        self.assertEqual(len({communities[n] for n in nodes[:5]}), 1)
        self.assertEqual(len({communities[n] for n in nodes[5:]}), 1)
        self.assertNotEqual(communities["alone"], communities["a0"])
        self.assertEqual((suggested_k(2), suggested_k(200), suggested_k(10 ** 6)), (2, 10, 50))

    def test_taxonomy_assignments_take_precedence_over_patterns(self):
        taxonomy = SiteTaxonomy(clusters={"blog": ["/blog/"]}, assignments={"https://s.example/blog/x": "special"},
                                cluster_affinities={"special": ["blog"]})
        self.assertEqual(taxonomy.cluster_for("https://s.example/blog/x/"), "special")
        self.assertEqual(taxonomy.cluster_for("https://s.example/blog/y"), "blog")
        self.assertTrue(SiteTaxonomy(assignments={"https://s.example/a": "x"}).has_clusters)
        self.assertFalse(SiteTaxonomy().has_clusters)


class TestSystems(unittest.TestCase):
    def test_baselines_on_the_hand_made_corpus(self):
        corpus = tiny_corpus()
        sources = corpus.ids
        exact = systems._exact_title(corpus, set(), sources, 0)
        self.assertEqual(exact[corpus.ids[0]], ["https://t.example/wiki/Worm_Farming", "https://t.example/wiki/Garden_Soil"])
        self.assertEqual(exact[corpus.ids[1]], ["https://t.example/wiki/Compost_Bin"])
        overlap = systems._title_overlap(corpus, set(), sources, 0)
        self.assertIn("https://t.example/wiki/Compost_Bin", overlap[corpus.ids[1]])
        random_links = systems._random_links(corpus, set(), sources, 3)
        self.assertEqual(random_links, systems._random_links(corpus, set(), sources, 3))
        self.assertTrue(all(s not in targets for s, targets in random_links.items()))

    def test_every_link_system_only_answers_for_the_requested_sources(self):
        corpus = generate(SyntheticSpec(pages=80, topics=3, seed=4))
        sources = corpus.ids[:10]
        removed = tasks.remove_links(corpus, sources, 1.0, 1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for system in systems.LINK_SYSTEMS:
                with self.subTest(system=system.name):
                    predictions = system.predict(corpus, removed, sources, 1)
                    self.assertTrue(set(predictions) <= set(sources))

    def test_url_folders(self):
        self.assertEqual(systems._url_folder("https://x.example/wiki/Paris"), "/wiki")
        self.assertEqual(systems._url_folder("https://x.example/shop/garden/spade/"), "/shop/garden")
        self.assertEqual(systems._url_folder("https://x.example/"), "/")


class TestTasks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = generate(SyntheticSpec(pages=200, topics=4, seed=6))
        cls.sample = sampling.sample_random(cls.corpus, 60, 1)

    def test_mention_strata(self):
        self.assertEqual(tasks.mention_stratum("worm farming basics", "Worm Farming"), "names-2+")
        self.assertEqual(tasks.mention_stratum("Paris", "Paris, France"), "names-1")
        self.assertEqual(tasks.mention_stratum("the city of light", "Paris"), "names-0")
        self.assertEqual(tasks.mention_stratum("worm composters", "Worm Composter"), "names-2+")   # light stemming
        self.assertEqual(tasks.mention_stratum("compost bins", "Compost Bin"), "names-1")   # "bin" < 4 letters: no stemming

    def test_removal_protocols(self):
        cold = tasks.remove_links(self.corpus, self.sample, 1.0, 1)
        holdout = tasks.remove_links(self.corpus, self.sample, 0.5, 1)
        self.assertEqual(cold, self.corpus.gold_pairs(self.sample))
        self.assertTrue(holdout < cold)
        for source in self.sample:
            n = len(self.corpus.get(source).link_targets)
            self.assertEqual(sum(1 for s, _ in holdout if s == source), math.ceil(n / 2))

    def test_link_task_reports_every_layer_and_comparison(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = tasks.link_task(self.corpus, self.sample, "holdout", 1)
        self.assertEqual(result["units"], 60)
        self.assertEqual(sum(result["gold_by_stratum"].values()), result["gold_links"])
        self.assertTrue(0 <= result["anchor_ceiling"] <= 1)
        magus = result["systems"]["seo-magus"]
        for key in ("precision", "recall", "f1", "f1_ci", "recall_by_stratum", "reader_validated_precision",
                    "recall_by_planted_style", "false_positives_planted_valid", "pagerank_rebuilt_rho"):
            self.assertIn(key, magus)
        self.assertLessEqual(magus["f1_ci"]["ci_low"], magus["f1"])
        products = [s.name for s in systems.LINK_SYSTEMS if s.kind != "baseline"]
        baselines = [s.name for s in systems.LINK_SYSTEMS if s.kind == "baseline"]
        self.assertEqual(len(result["comparisons"]), len(products) * len(baselines))
        self.assertEqual(result["systems"]["random"]["kind"], "baseline")

    def test_pagerank_reconstruction_invariants(self):
        # Regression: the stripped graph once kept its networkx edges, so PageRank never changed (rho exactly 1).
        removed = tasks.remove_links(self.corpus, self.sample, 1.0, 1)
        perfect = systems.LinkSystem("perfect", "product", lambda corpus, removed_, sources, seed: {
            s: [t for (src, t) in removed_ if src == s] for s in sources})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = tasks.link_task(self.corpus, self.sample, "cold", 1,
                                     [perfect, next(s for s in systems.LINK_SYSTEMS if s.name == "random")])
        oracle = result["systems"]["perfect"]
        self.assertEqual((oracle["precision"], oracle["recall"]), (1.0, 1.0))
        self.assertLess(oracle["pagerank_stripped_rho"], 0.999)            # removing links changes PageRank
        self.assertAlmostEqual(oracle["pagerank_rebuilt_rho"], 1.0)        # exact links rebuild it exactly
        self.assertLess(result["systems"]["random"]["pagerank_rebuilt_rho"], oracle["pagerank_rebuilt_rho"])
        stripped = systems.site_graph(self.corpus, exclude=removed)
        self.assertEqual(stripped.graph.number_of_edges() if hasattr(stripped, "graph") else None,
                         sum(len(t) for t in stripped.edges.values()) if hasattr(stripped, "graph") else None)

    def test_classification_and_ranking_tasks(self):
        result = tasks.classification_task(self.corpus, self.sample, 1)
        self.assertEqual(result["true_labels"], 4)
        self.assertEqual(result["systems"]["seo-magus"]["ari"], 0.0)          # one cluster: no information
        self.assertGreater(result["systems"]["content-k"]["ari"], result["systems"]["random"]["ari"])
        ranking = tasks.ranking_task(self.corpus, self.sample, 1)
        self.assertIn("ndcg@10", ranking["systems"]["pagerank"])
        self.assertIn("pagerank vs in-degree", ranking["comparisons"])

    def test_tasks_skip_corpora_that_cannot_answer(self):
        fine = Corpus("fine", [Document(f"https://f/{i}", str(i), ["x"], labels=[f"l{i}"]) for i in range(9)],
                      Provenance("t", "t"))
        self.assertIn("too fine-grained", tasks.classification_task(fine, fine.ids, 1)["skipped"])
        self.assertIn("no popularity", tasks.ranking_task(fine, fine.ids, 1)["skipped"])


class TestRunnerAndReport(unittest.TestCase):
    def test_small_end_to_end_run(self):
        from src.evaluation.report import render_markdown, write_report
        from src.evaluation.runner import evaluate
        corpus = generate(SyntheticSpec(pages=70, topics=3, seed=8))
        messages = []
        link_systems = [s for s in systems.LINK_SYSTEMS if s.name in ("seo-magus", "exact-title", "random")]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            report = evaluate([corpus], samplers=["random", "label"], seeds=[1, 2], sample_size=24,
                              link_protocols=["cold"], link_systems=link_systems, progress=messages.append)
        self.assertEqual(len(report["runs"]), 3 * 2 * 2)                       # tasks x samplers x seeds
        self.assertEqual(report["protocol_hash"], protocol_hash())
        groups = {(g["task"], g["protocol"]) for g in report["summary"]["groups"]}
        self.assertEqual(groups, {("links", "cold"), ("classification", None), ("ranking", None)})
        claim = next(c for c in report["summary"]["claims"] if c["claim"] == "seo-magus vs random")
        self.assertEqual(claim["status"], "untested on real data")                # synthetic is never evidence
        comparisons = [c for r in report["runs"] for c in r["result"].get("comparisons", {}).values()]
        self.assertTrue(all("significant_after_correction" in c for c in comparisons))
        markdown = render_markdown(report)
        for heading in ("## Claims", "## Bias checklist", "## Scores", "## Link diagnostics",
                        "No real corpus in this report"):
            self.assertIn(heading, markdown)
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_report(report, tmp)
            from src.evaluation.report import FULL_FILES
            self.assertEqual([p.name for p in paths], list(FULL_FILES))
            self.assertEqual(json.loads(paths[0].read_text())["protocol_hash"], protocol_hash())

    def test_scale_task_checks_equivalence_with_the_exhaustive_flow(self):
        from src.evaluation.scale import loglog_slope, scale_task
        result = scale_task([20, 40], brute_max=40)
        self.assertTrue(all(row["identical_links"] for row in result["rows"]))
        self.assertTrue(all(row["classifier_calls"] <= row["exhaustive_calls"] for row in result["rows"]))
        self.assertAlmostEqual(loglog_slope([10, 100, 1000], [1, 100, 10000]), 2.0)


class TestEvaluationCli(unittest.TestCase):
    def test_generate_describe_and_run(self):
        from contextlib import redirect_stdout
        import io
        from src.evaluation.__main__ import main
        with tempfile.TemporaryDirectory() as tmp:
            corpus_path = Path(tmp, "synthetic.jsonl.gz")
            out = io.StringIO()
            with redirect_stdout(out), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                main(["synthetic", "--pages", "50", "--topics", "3", "--out", str(corpus_path)])
                main(["info", str(corpus_path)])
                main(["run", str(corpus_path), "--out", tmp, "--samplers", "random", "--seeds", "1",
                      "--sample-size", "20", "--protocols", "cold", "--systems", "seo-magus", "random"])
                main(["scale", "--sizes", "15", "30", "--exhaustive-max", "30", "--out", tmp])
            report = Path(tmp, "report.md").read_text(encoding="utf-8")
        self.assertIn("50 documents", out.getvalue())
        self.assertIn("## Claims", report)
        self.assertIn("## Scale", report)                     # merged into the same report

    def test_run_with_a_site_config_classifier(self):
        from contextlib import redirect_stdout
        import io
        from src.evaluation.__main__ import main
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()) as out, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            corpus = generate(SyntheticSpec(pages=40, topics=2, seed=3)).save(Path(tmp, "c.jsonl.gz"))
            main(["run", str(corpus), "--out", tmp, "--tasks", "links", "--samplers", "random", "--seeds", "1",
                  "--sample-size", "15", "--protocols", "cold", "--systems", "seo-magus", "random",
                  "--config", "config/sites/greenleaf.yaml"])
            report = json.loads(Path(tmp, "report.json").read_text(encoding="utf-8"))
        self.assertIn("SEO-Magus systems use the classifier of config/sites/greenleaf.yaml: heuristic", out.getvalue())
        self.assertEqual(set(report["runs"][0]["result"]["systems"]), {"seo-magus", "random"})


class TestDegenerateInputs(unittest.TestCase):
    """Metrics and helpers must give defined answers (never crash or divide by zero) on degenerate inputs."""

    def test_metrics(self):
        self.assertEqual((metrics.purity([], []), metrics.nmi([], []), metrics.adjusted_rand_index(["a"], ["x"])),
                         (0.0, 0.0, 1.0))
        self.assertEqual(metrics.nmi(["a", "a"], ["x", "x"]), 1.0)                 # both constant: identical
        self.assertEqual(metrics.adjusted_rand_index(["a", "a"], ["x", "x"]), 1.0)
        with self.assertRaisesRegex(ValueError, "same length"):
            metrics.purity(["a"], ["x", "y"])
        self.assertEqual((metrics.pearson([1], [2]), metrics.kendall_tau_b([1], [2])), (0.0, 0.0))
        self.assertEqual(metrics.kendall_tau_b([1, 1, 1], [1, 2, 3]), 0.0)         # all tied in x
        self.assertEqual((metrics.ndcg_at_k([], [], [], 5), metrics.ndcg_at_k(["a"], [1], [0], 5)), (0.0, 0.0))
        self.assertEqual(metrics.macro_prf([]), (0.0, 0.0, 0.0))
        self.assertEqual(metrics.paired_bootstrap([1], lambda u: 1.0, lambda u: 0.0).verdict, "better")
        self.assertEqual(metrics.estimate_from(0.5, []), metrics.Estimate(0.5, 0.5, 0.5))
        self.assertEqual(metrics.compare_from(0.0, 1.0, [], []).p_not_better, 1.0)
        self.assertEqual(metrics.resamples(1, 10, 0), [])
        self.assertEqual(metrics._percentile([], 0.5), 0.0)
        self.assertEqual((metrics.label_of(["a", "b"]), metrics.label_of([])), ("a", None))
        self.assertEqual(str(metrics.Estimate(0.5, 0.25, 0.75)), "0.500 [0.250, 0.750]")

    def test_clustering_edges(self):
        self.assertEqual(spherical_kmeans([], 3), [])
        self.assertEqual(spherical_kmeans([{"a": 1.0}] * 3, 5), [0, 0, 0])        # identical points: one center
        self.assertEqual(tfidf_vectors(["x", "y"]), [{}, {}])                       # nothing passes min_df
        from src.engines.clustering import assignments_for
        self.assertEqual(assignments_for({"u": "1"}, prefix="topic-"), (("u", "topic-1"),))
        from src.evaluation.scale import loglog_slope
        self.assertTrue(math.isnan(loglog_slope([10], [1])))

    def test_small_helpers(self):
        systems._CACHE.clear()
        for i in range(70):                                                          # bounded cache
            systems._cached(("k", i), lambda: i)
        self.assertLessEqual(len(systems._CACHE), 65)
        from src.evaluation.crawl_eval import _base
        two_hosts = Corpus("h", [Document("https://a.example/x", "X", ["x"]), Document("https://b.example/y", "Y", ["y"])],
                           Provenance("t", "t"))
        with self.assertRaisesRegex(ValueError, "single-host"):
            _base(two_hosts)
        self.assertIn(tiny_corpus().ids[0], tiny_corpus())
        with tempfile.TemporaryDirectory() as tmp:
            newer = Path(tmp, "newer.jsonl.gz")
            with gzip.open(newer, "wt") as handle:
                handle.write(json.dumps({"format": "seo-magus/corpus", "version": 99}) + "\n")
            with self.assertRaisesRegex(ValueError, "corpus format v99"):
                Corpus.load(newer)

    def test_lenient_precision_uses_the_other_human_links(self):
        corpus = tiny_corpus()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = tasks.link_task(corpus, corpus.ids, "cold", 1,
                                     [s for s in systems.LINK_SYSTEMS if s.name in ("exact-title", "random")])
        self.assertEqual(result["systems"]["exact-title"]["lenient_precision"], 1.0)   # Garden Soil is in extra_links
        self.assertEqual(result["anchor_ceiling"], 1.0)          # worm farming, garden soil guide, compost bin: 2+ words


class TestClaimRules(unittest.TestCase):
    def test_cross_source_status(self):
        from src.evaluation.runner import _claims, evidence_role
        group = lambda corpus, verdict, evidence: {"task": "links", "protocol": "cold", "corpus": corpus,
                                                   "evidence": evidence, "verdicts": {"A vs B": verdict}}
        status = lambda *groups: _claims(list(groups))[0]["status"]
        self.assertEqual(status(group("w", "robust", "evidence"), group("s", "robust", "evidence")),
                         "supported on every real source")
        self.assertEqual(status(group("w", "robust", "evidence"), group("s", "mixed", "evidence")), "not established")
        self.assertEqual(status(group("w", "robust", "evidence"), group("s", "worse", "evidence")),
                         "contradicted on some real source")
        self.assertEqual(status(group("syn", "robust", "by construction, per link style")), "untested on real data")
        tiny = Corpus("t", [Document("https://t/a", "A", ["a"])], Provenance("crawl", "x"))
        self.assertEqual(evidence_role(tiny, "links"), "too small for evidence")

    def test_runner_skips_tasks_without_their_layer(self):
        from src.evaluation.runner import evaluate
        bare = Corpus("bare", [Document(f"https://b/{i}", f"Page {i}", ["text"]) for i in range(5)], Provenance("t", "t"))
        messages = []
        report = evaluate([bare], samplers=["random"], seeds=[1], progress=messages.append)
        self.assertEqual(report["runs"], [])
        self.assertEqual(len([m for m in messages if "skipped" in m]), 3)

    def test_report_renders_partial_reports(self):
        from src.evaluation.report import render_markdown
        scale = {"preset": "encyclopedia", "seed": 0, "time_exponent": 1.1, "calls_exponent": 1.0,
                 "rows": [{"pages": 10, "seconds": 0.1, "classifier_calls": 5, "links": 2},
                          {"pages": 20, "seconds": 0.2, "classifier_calls": 9, "links": 4, "exhaustive_seconds": 1,
                           "exhaustive_calls": 50, "identical_links": False}]}
        crawl = [{"corpus": "c", "documents": 3, "coverage": 1.0, "title_exact": 1.0, "paragraphs_exact": 1.0,
                  "link_recall": 1.0, "link_precision": 1.0, "navigation_leaks": 0, "pages_per_second": 9.0}]
        runs = [{"corpus": "c", "task": "ranking", "result": {"task": "ranking", "skipped": "no popularity layer"}}]
        markdown = render_markdown({"scale": scale, "crawl": crawl, "runs": runs})
        self.assertIn("| 20 | 0.2 | 9 | 4 | 1 | 50 | **NO** |", markdown)
        self.assertIn("| 10 | 0.1 | 5 | 2 | - | - | - |", markdown)
        self.assertIn("* c: ranking skipped - no popularity layer", markdown)
        self.assertIn("## Crawl fidelity", markdown)


class TestEvaluationCliSources(unittest.TestCase):
    """The fetch commands wire their options to the sources (sources themselves: test_evaluation_sources.py)."""

    def _main(self, *argv):
        from contextlib import redirect_stdout
        import io
        from unittest import mock
        from src.evaluation.__main__ import main
        built = {}

        def fake_build(kind):
            def build(self_, name, *args, **kwargs):
                built[kind] = (name, args, kwargs)
                return tiny_corpus()
            return build

        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()) as out, \
                mock.patch("src.evaluation.sources.wikipedia.WikipediaSource.build", fake_build("wikipedia")), \
                mock.patch("src.evaluation.sources.internet_archive.InternetArchiveSource.build", fake_build("archive")), \
                mock.patch("src.evaluation.sources.stackexchange.StackExchangeDump.import_dump", fake_build("se")), \
                mock.patch("src.evaluation.sources.stackexchange.StackExchangeDump.__init__", lambda s, d, site: setattr(s, "host", site)):
            target = str(Path(tmp, "c.jsonl.gz"))
            main([*argv, "--out", target] if argv[0] != "info" else list(argv))
            saved = Corpus.load(target) if Path(target).exists() else None
        return built, out.getvalue(), saved

    def test_fetch_commands(self):
        built, output, saved = self._main("wikipedia", "--contact", "me@example.com", "--lang", "pt",
                                          "--categories", "Compostagem", "Xadrez", "--limit", "50", "--offline")
        name, _, kwargs = built["wikipedia"]
        self.assertEqual((name, kwargs["categories"], kwargs["limit"]), ("wikipedia-pt", ["Compostagem", "Xadrez"], 50))
        self.assertEqual(saved.fingerprint(), tiny_corpus().fingerprint())
        self.assertIn("4 documents", output)
        built, _, _ = self._main("archive", "--contact", "me@example.com", "--collections", "prelinger", "--mediatype", "movies")
        self.assertEqual(built["archive"][0], "internet-archive")
        self.assertEqual(built["archive"][2]["mediatype"], "movies")
        built, _, _ = self._main("stackexchange", "--dump", "/d", "--site", "gardening.stackexchange.com", "--tags", "worms")
        self.assertEqual(built["se"][2]["tags"], ["worms"])

    def test_crawl_and_clickstream_commands_offline(self):
        from contextlib import redirect_stdout
        import io
        from src.evaluation.__main__ import main
        from src.evaluation.sources.wikipedia import article_url
        from tests.fixtures.crawls import crawl_path
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            corpus_file = str(Path(tmp, "crawl.jsonl.gz"))
            main(["crawl", "--from-crawl", str(crawl_path("greenleaf-good")), "--out", corpus_file])
            self.assertEqual(len(Corpus.load(corpus_file)), 10)
            url = lambda title: article_url("en", title)
            wiki = Corpus("wiki", [Document(url("Compost"), "Compost", ["x"]), Document(url("Worm"), "Worm", ["y"])],
                          Provenance("wikipedia", "action-api/test"))
            wiki_file = wiki.save(Path(tmp, "wiki.jsonl.gz"))
            tsv = Path(tmp, "clicks.tsv.gz")
            with gzip.open(tsv, "wt", encoding="utf-8") as handle:
                handle.write("Compost\tWorm\tlink\t25\nWorm\tCompost\tother\t3\n")
            main(["clickstream", "--corpus", str(wiki_file), "--tsv", str(tsv)])
            enriched = Corpus.load(wiki_file)
        self.assertEqual(enriched.clickstream, {(url("Compost"), url("Worm")): {"link": 25},
                                                (url("Worm"), url("Compost")): {"other": 3}})
        self.assertNotEqual(enriched.fingerprint(), wiki.fingerprint())     # the layer is part of the content


@pytest.mark.integration
class TestCrawlFidelity(unittest.TestCase):
    def test_rendered_site_is_crawled_exactly(self):
        from src.evaluation.crawl_eval import crawl_fidelity
        result = crawl_fidelity(generate(SyntheticSpec(pages=60, topics=3, seed=5)), concurrency=4)
        self.assertEqual((result["coverage"], result["title_exact"], result["paragraphs_exact"]), (1.0, 1.0, 1.0))
        self.assertEqual((result["link_recall"], result["link_precision"], result["navigation_leaks"]), (1.0, 1.0, 0))
        self.assertGreater(result["rendered_links"], 100)

    def test_crawl_site_and_cli_commands_over_http(self):
        from contextlib import redirect_stdout
        import io
        from src.benchmarks import mock_sites
        from src.benchmarks.mock_sites import MockSiteServer
        from src.evaluation.__main__ import main
        from src.evaluation.sources.site_crawl import crawl_site
        with MockSiteServer(mock_sites.SCRAMBLED_SITE) as server:
            corpus = crawl_site(server.base_url + "/", "scrambled", max_pages=50)
            with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()) as out:
                main(["crawl", "--url", server.base_url + "/", "--max-pages", "50", "--out", str(Path(tmp, "c.jsonl.gz"))])
                synthetic = generate(SyntheticSpec(pages=20, topics=2, seed=1)).save(Path(tmp, "s.jsonl.gz"))
                main(["crawl-fidelity", str(synthetic), "--out", tmp, "--concurrency", "2"])
                report = Path(tmp, "report.md").read_text(encoding="utf-8")
        self.assertIn("links", corpus.layers)
        self.assertEqual(len(corpus), 10)                                  # indexable pages only
        self.assertIn('"coverage": 1.0', out.getvalue())
        self.assertIn("## Crawl fidelity", report)


if __name__ == "__main__":
    unittest.main()
