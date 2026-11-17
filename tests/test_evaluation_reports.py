"""
Evaluation reports: statistics (against reference values), tidy results, the
analysis layer, cross-report comparison, and every export (simple and full).
"""

import csv
import io
import json
import math
import random
import re
import tempfile
import unittest
import warnings
import xml.dom.minidom
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

from src.evaluation import stats
from src.evaluation.analysis import analyze, headline
from src.evaluation.compare import compare_reports, write_comparison
from src.evaluation.corpus import Provenance
from src.evaluation.metrics import spearman
from src.evaluation.report import FULL_FILES, SIMPLE_FILES, SUMMARY_COLUMNS, render_markdown, write_report
from src.evaluation.results import FIELDS, PRIMARY, group, load_rows, read_rows, rows_from_report, select, write_csv, write_jsonl
from src.evaluation.runner import evaluate
from src.evaluation.sources.synthetic import SyntheticSpec, generate
from src.evaluation.systems import LINK_SYSTEMS

_REPORT = None


def small_report() -> dict:
    """A real runner output: two corpora (one playing a real source), two samplers, two seeds, 3 link systems."""
    global _REPORT
    if _REPORT is None:
        real = generate(SyntheticSpec(pages=70, topics=3, seed=21))
        real.name = "pseudo-real"
        real.provenance = Provenance("wikipedia", "action-api/test", language="en")   # counts as evidence
        synthetic = generate(SyntheticSpec(pages=70, topics=3, seed=22, preset="catalog"))
        systems = [s for s in LINK_SYSTEMS if s.name in ("seo-magus", "exact-title", "random")]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _REPORT = evaluate([real, synthetic], samplers=["random", "label"], seeds=[1, 2], sample_size=35,
                               link_protocols=["cold"], link_systems=systems)
    return json.loads(json.dumps(_REPORT, default=str))        # a fresh copy, as loaded from report.json


class TestStatistics(unittest.TestCase):
    def test_chi_square_and_normal_reference_values(self):
        for x, df, expected in ((3.841459, 1, 0.05), (5.991465, 2, 0.05), (18.307038, 10, 0.05), (0.5, 3, 0.918891),
                                (0.0, 4, 1.0), (30.0, 2, 3.059e-7)):
            self.assertAlmostEqual(stats.chi2_sf(x, df), expected, places=5 if expected > 1e-6 else 9)
        self.assertAlmostEqual(stats.normal_cdf(1.959964), 0.975, places=6)

    def test_friedman_matches_the_classic_formula_without_ties(self):
        rng = random.Random(3)
        table = [[rng.random() for _ in range(5)] for _ in range(15)]
        result = stats.friedman(table)
        n, k = 15, 5
        totals = [sum(row[j] for row in stats.rank_matrix(table)) for j in range(k)]
        classic = 12 / (n * k * (k + 1)) * sum(t * t for t in totals) - 3 * n * (k + 1)
        self.assertAlmostEqual(result["chi2"], classic)
        self.assertAlmostEqual(sum(result["average_ranks"]), k * (k + 1) / 2)
        dominant = [[3.0, 2.0, 1.0]] * 10                        # system 0 always best
        result = stats.friedman(dominant)
        self.assertEqual(result["average_ranks"], [1.0, 2.0, 3.0])
        self.assertLess(result["p_value"], 0.001)
        self.assertEqual(stats.friedman([[1.0, 2.0]])["p_value"], 1.0)                  # one cell: no test

    def test_nemenyi_and_kendall_w(self):
        self.assertAlmostEqual(stats.nemenyi_cd(4, 10), 2.569 * math.sqrt(4 * 5 / 60))
        self.assertIsNone(stats.nemenyi_cd(11, 10))
        rng = random.Random(5)
        a, b = [rng.random() for _ in range(8)], [rng.random() for _ in range(8)]
        self.assertAlmostEqual(stats.kendall_w([a, b]), (spearman(a, b) + 1) / 2)     # identity for two raters
        self.assertEqual(stats.kendall_w([a, a, a]), 1.0)
        self.assertEqual(stats.kendall_w([[1, 2, 3], [3, 2, 1]]), 0.0)
        self.assertEqual(stats.kendall_w([a]), 1.0)

    def test_wilcoxon_exact_and_approximate(self):
        self.assertAlmostEqual(stats.wilcoxon_signed_rank([1, 2, 3, 4, 5])["p_value"], 0.0625)   # 2 / 2^5
        self.assertEqual(stats.wilcoxon_signed_rank([1, -1, 2, -2])["p_value"], 1.0)             # symmetric
        self.assertEqual(stats.wilcoxon_signed_rank([0, 0])["n"], 0)
        many = stats.wilcoxon_signed_rank([0.02] * 40)                                           # normal approximation
        self.assertLess(many["p_value"], 1e-6)
        tied = stats.wilcoxon_signed_rank([0.05] * 8)                                            # exact, with ties
        self.assertAlmostEqual(tied["p_value"], 2 / 2 ** 8)
        mixed = stats.wilcoxon_signed_rank([1, 1, 2, -3, 4, 4, 5, -6])
        self.assertAlmostEqual(mixed["p_value"], self._brute_force_p([1, 1, 2, -3, 4, 4, 5, -6]))

    @staticmethod
    def _brute_force_p(differences):
        """Enumerate every sign assignment: the definition of the exact test."""
        from itertools import product
        from src.evaluation.metrics import average_ranks
        ranks = average_ranks([abs(d) for d in differences])
        observed = sum(r for r, d in zip(ranks, differences) if d > 0)
        total = sum(ranks)
        extreme = min(observed, total - observed)
        hits = sum(1 for signs in product((0, 1), repeat=len(ranks))
                   if min(s := sum(r for r, b in zip(ranks, signs) if b), total - s) <= extreme + 1e-9)
        return min(1.0, hits / 2 ** len(ranks))

    def test_eta_squared_and_random_effects(self):
        values = [1.0, 1.0, 2.0, 2.0]
        shares = stats.eta_squared(values, {"decides": ["a", "a", "b", "b"], "unrelated": ["x", "y", "x", "y"]})
        self.assertEqual((shares["decides"], shares["unrelated"]), (1.0, 0.0))
        # Hand-computed: fixed mean 0.3, Q = 8, C = 200, tau² = 0.03, I² = 0.75, pooled 0.3, SE = sqrt(1/75).
        pooled = stats.random_effects([0.1, 0.3, 0.5], [0.01, 0.01, 0.01])
        self.assertAlmostEqual(pooled["pooled"], 0.3)
        self.assertAlmostEqual(pooled["tau2"], 0.03)
        self.assertAlmostEqual(pooled["i2"], 0.75)
        self.assertAlmostEqual(pooled["ci_high"] - pooled["pooled"], 1.959964 * math.sqrt(1 / 75))
        self.assertEqual(stats.random_effects([0.2, 0.2], [0.01, 0.02])["i2"], 0.0)
        self.assertEqual(stats.random_effects([], [])["sources"], 0)
        self.assertAlmostEqual(stats.se_from_ci(-1.959964, 1.959964), 1.0)


class TestTidyResults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = small_report()
        cls.rows = rows_from_report(cls.report, "small")

    def test_every_run_becomes_rows_with_its_methodology(self):
        primary = [r for r in self.rows if r.metric == PRIMARY[r.task]]
        runs = [run for run in self.report["runs"] if "systems" in run["result"]]
        self.assertEqual(len(primary), sum(len(run["result"]["systems"]) for run in runs))
        self.assertEqual({r.sampler for r in self.rows}, {"random", "label"})
        self.assertEqual({r.evidence for r in self.rows if r.corpus == "pseudo-real"}, {"evidence"})
        self.assertTrue(all(r.ci_low is not None for r in primary))
        links = select(self.rows, task="links", metric="difference[exact-title]")
        self.assertTrue(links and all(r.system == "seo-magus" and r.ci_low <= r.value <= r.ci_high for r in links))

    def test_skill_is_chance_normalized(self):
        for (cell,), members in group([r for r in self.rows if r.metric in ("skill", PRIMARY[r.task])], "cell").items():
            by = {(r.system, r.metric): r.value for r in members}
            task = members[0].task
            chance = by[("random", PRIMARY[task])]
            for (system, metric), value in by.items():
                if metric == "skill":
                    self.assertAlmostEqual(value, (by[(system, PRIMARY[task])] - chance) / (1 - chance))
            self.assertAlmostEqual(by[("random", "skill")], 0.0)

    def test_csv_and_jsonl_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_rows = read_rows(write_csv(self.rows, Path(tmp, "runs.csv")))
            jsonl_rows = read_rows(write_jsonl(self.rows, Path(tmp, "results.jsonl")))
            with Path(tmp, "runs.csv").open(encoding="utf-8") as handle:
                header = next(csv.reader(handle))
            relabelled = load_rows(Path(tmp, "results.jsonl"), "other")
        self.assertEqual(header, FIELDS)
        self.assertEqual(jsonl_rows, self.rows)
        self.assertEqual(len(csv_rows), len(self.rows))
        self.assertTrue(all(abs(a.value - b.value) < 1e-6 for a, b in zip(csv_rows, self.rows)))
        self.assertEqual({r.report for r in relabelled}, {"other"})


class TestAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = rows_from_report(small_report(), "small")
        cls.analysis = analyze(cls.rows)

    def test_describe_and_wins_are_consistent_with_the_rows(self):
        entry = next(e for e in self.analysis["describe"]
                     if e["task"] == "links" and e["corpus"] == "pseudo-real" and e["system"] == "seo-magus")
        values = [r.value for r in select(self.rows, task="links", corpus="pseudo-real", system="seo-magus", metric="f1")]
        self.assertAlmostEqual(entry["mean"], sum(values) / len(values))
        self.assertEqual(entry["n"], 4)                                    # 2 samplers x 2 seeds
        for w in self.analysis["wins"]:
            self.assertEqual(w["won"] + w["tied"] + w["lost"], w["cells"])
            self.assertTrue(0 <= w["win_rate"] <= 1)

    def test_ranks_agreement_sensitivity_and_meta(self):
        top = headline(self.analysis, "links")
        self.assertEqual(top["cells"], 8)                                  # 2 corpora x 2 samplers x 2 seeds
        self.assertEqual(sorted(top["average_rank"]), ["exact-title", "random", "seo-magus"])
        self.assertEqual(list(top["average_rank"])[-1], "random")
        factors = {(a["task"], a["factor"]) for a in self.analysis["agreement"]}
        self.assertIn(("links", "corpus"), factors)
        for a in self.analysis["agreement"]:
            self.assertTrue(0 <= a["kendall_w"] <= 1)
        for s in self.analysis["sensitivity"]:
            self.assertTrue(all(0 <= s[f"eta2_{f}"] <= 1 + 1e-9 for f in ("corpus", "protocol", "sampler", "seed")))
        meta = next(m for m in self.analysis["meta"] if m["task"] == "links" and m["baseline"] == "random")
        self.assertEqual(meta["all"]["sources"], 2)
        self.assertEqual(meta["real"]["sources"], 1)                       # only the pseudo-real corpus is evidence
        self.assertGreater(meta["all"]["pooled"], 0)


class TestCompare(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = rows_from_report(small_report(), "before")

    def _shifted(self, label, delta, **changes):
        return [replace(r, report=label, value=r.value + (delta if r.system == "seo-magus" and r.metric == "f1" else 0),
                        **changes) for r in self.rows]

    def test_direct_comparison_detects_a_consistent_change(self):
        result = compare_reports({"before": self.rows, "after": self._shifted("after", 0.05)})
        c = result["comparisons"][0]
        self.assertEqual((c["mode"], c["reasons"], c["notes"]), ("direct", [], []))
        change = next(x for x in c["changes"] if x["system"] == "seo-magus" and x["task"] == "links")
        self.assertEqual((change["cells"], change["improved"], change["worsened"]), (8, 8, 0))
        self.assertAlmostEqual(change["mean_change"], 0.05)
        self.assertEqual(change["verdict"], "better")
        unchanged = next(x for x in c["changes"] if x["system"] == "random" and x["task"] == "links")
        self.assertEqual(unchanged["verdict"], "unchanged")
        self.assertEqual({a["kendall_tau"] for a in c["ranking_agreement"]}, {1.0})

    def test_different_methodologies_are_compared_without_significance(self):
        other = self._shifted("v2", 0.0, protocol_hash="another", fingerprint="changed")
        c = compare_reports({"before": self.rows, "v2": other})["comparisons"][0]
        self.assertEqual(c["mode"], "indirect")
        self.assertIn("protocol differs", c["reasons"][0])
        self.assertTrue(any("data of" in r for r in c["reasons"]))
        self.assertNotIn("changes", c)
        self.assertTrue(c["skill"])
        smaller = [replace(r, report="n100", units=r.units // 2) for r in self.rows if r.sampler == "random"]
        c = compare_reports({"before": self.rows, "n100": smaller})["comparisons"][0]
        self.assertEqual(c["mode"], "direct")
        self.assertTrue(any("documents per run differ" in n for n in c["notes"]))
        self.assertTrue(any("cells in common" in n for n in c["notes"]))
        with self.assertRaises(ValueError):
            compare_reports({"only": self.rows})

    def test_comparison_exports(self):
        result = compare_reports({"before": self.rows, "after": self._shifted("after", 0.05)})
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_comparison(result, tmp)
            markdown = paths[0].read_text(encoding="utf-8")
            with paths[1].open(encoding="utf-8") as handle:
                records = list(csv.DictReader(handle))
            self.assertEqual(json.loads(paths[2].read_text(encoding="utf-8"))["reference"], "before")
        self.assertIn("## before -> after (direct)", markdown)
        self.assertIn("**better**", markdown)
        better = [r for r in records if r["system"] == "seo-magus" and r["task"] == "links"]
        self.assertEqual(better[0]["verdict"], "better")


class TestExports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = small_report()
        cls.report["scale"] = {"preset": "encyclopedia", "seed": 0, "time_exponent": 1.1, "calls_exponent": 1.0,
                               "rows": [{"pages": 100, "seconds": 0.3, "classifier_calls": 270, "links": 160,
                                         "exhaustive_calls": 60000, "identical_links": True},
                                        {"pages": 1000, "seconds": 3.0, "classifier_calls": 3000, "links": 1400}]}

    def test_levels_write_their_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            simple = write_report(self.report, Path(tmp, "s"), level="simple")
            full = write_report(self.report, Path(tmp, "f"), level="full")
        self.assertEqual([p.name for p in simple], list(SIMPLE_FILES))
        self.assertEqual([p.name for p in full], list(FULL_FILES))
        with self.assertRaises(ValueError):
            write_report(self.report, "/tmp/never", level="everything")

    def test_simple_csv_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_report(self.report, tmp, level="simple")
            with Path(tmp, "summary.csv").open(encoding="utf-8") as handle:
                summary = list(csv.DictReader(handle))
            with Path(tmp, "claims.csv").open(encoding="utf-8") as handle:
                claims = list(csv.reader(handle))
        self.assertEqual(tuple(summary[0]), SUMMARY_COLUMNS)
        magus = next(r for r in summary if r["system"] == "seo-magus" and r["corpus"] == "pseudo-real"
                     and r["task"] == "links")
        self.assertEqual((magus["runs"], magus["best_baseline"]), ("4", "exact-title"))
        self.assertTrue(0 <= float(magus["win_rate_vs_best_baseline"]) <= 1)
        self.assertEqual(claims[0][:4], ["task", "protocol", "claim", "status"])
        self.assertEqual(claims[0][4:], ["pseudo-real", "synthetic-catalog-en-70"])
        self.assertEqual(len(claims) - 1, len(self.report["summary"]["claims"]))

    def test_markdown_sections_and_line_length(self):
        markdown = render_markdown(self.report)
        for heading in ("## At a glance", "## Claims", "## Scores", "## Ranks across methodologies",
                        "## Methodologies compared", "## Meta-analysis across sources", "## Link diagnostics",
                        "## Scale", "## Files"):
            self.assertIn(heading, markdown)
        self.assertIn("Corpus key: C1 = pseudo-real", markdown)
        self.assertLessEqual(max(len(line) for line in markdown.splitlines()), 400)

    def test_html_is_self_contained_and_well_formed(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_report(self.report, tmp, level="full")
            html = Path(tmp, "report.html").read_text(encoding="utf-8")
        svgs = re.findall(r"<svg.*?</svg>", html, re.S)
        self.assertGreaterEqual(len(svgs), 4)               # rank diagrams, sensitivity, forest plots, scale
        for svg in svgs:
            xml.dom.minidom.parseString(svg)
        for section in ("summary", "claims", "scores", "ranks", "methodologies", "meta", "diagnostics", "scale"):
            self.assertIn(f'<section id="{section}">', html)
        self.assertNotRegex(re.sub(r"<[^>]+>", " ", html), r"\b(nan|None)\b")
        self.assertNotIn("<script", html)
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))      # no external assets
        self.assertIn("exhaustive flow: 60,000 calls", html)

    def test_export_and_compare_commands(self):
        from src.evaluation.__main__ import main
        with tempfile.TemporaryDirectory() as tmp:
            source = write_report(self.report, Path(tmp, "a"), level="simple")[0]
            out = io.StringIO()
            with redirect_stdout(out):
                main(["export", str(source), "--level", "full", "--label", "first"])
                main(["compare", str(source), str(Path(tmp, "a", "results.jsonl")), "--labels", "json", "jsonl",
                      "--out", str(Path(tmp, "cmp"))])
            self.assertTrue(Path(tmp, "a", "report.html").is_file())
            comparison = Path(tmp, "cmp", "compare.md").read_text(encoding="utf-8")
        self.assertIn("json -> jsonl: direct", out.getvalue())
        self.assertIn("| links | cold | seo-magus | f1 |", comparison)
        self.assertIn("0 / 0 / 8 |", comparison)                     # same results: every cell unchanged


if __name__ == "__main__":
    unittest.main()


class TestIncompleteData(unittest.TestCase):
    """Reports from different methodologies rarely line up: every layer must cope with missing pieces."""

    @classmethod
    def setUpClass(cls):
        cls.report = small_report()
        cls.rows = rows_from_report(cls.report, "partial")

    def test_systems_missing_from_some_cells(self):
        # exact-title only ran with the random sampler; one corpus has a single run of everything.
        partial = [r for r in self.rows if not (r.system == "exact-title" and r.sampler == "label")
                   and not (r.corpus == "pseudo-real" and (r.sampler, r.seed) != ("random", 1))]
        analysis = analyze(partial)
        head_to_head = [w for w in analysis["wins"] if w["baseline"] == "exact-title" and w["task"] == "links"]
        self.assertEqual({w["corpus"]: w["cells"] for w in head_to_head},      # only cells where both ran
                         {"pseudo-real": 1, "synthetic-catalog-en-70": 2})
        top = headline(analysis, "links")
        self.assertEqual(top["cells"], 3)                                          # cells with every system present
        self.assertTrue(all(s["runs"] >= 3 for s in analysis["sensitivity"]))     # too few runs: skipped
        markdown = render_markdown(self.report, partial, analysis)
        self.assertIn("## Ranks across methodologies", markdown)
        from src.evaluation.html_report import render_html
        html = render_html(self.report, partial, analysis)
        for svg in re.findall(r"<svg.*?</svg>", html, re.S):
            xml.dom.minidom.parseString(svg)

    def test_claims_and_scores_with_missing_corpora(self):
        from src.evaluation.html_report import render_html
        report = json.loads(json.dumps(self.report))
        claim = report["summary"]["claims"][0]
        claim["by_corpus"].pop(next(iter(claim["by_corpus"])))
        rows = [r for r in self.rows if not (r.system == "random" and r.corpus == "pseudo-real")]
        html = render_html(report, rows, analyze(rows))
        self.assertIn('<td class="v-na">·</td>', html)
        self.assertIn("<td></td>", html)                                          # no score for that corpus

    def test_reports_without_a_shared_corpus_and_empty_inputs(self):
        other = [replace(r, report="elsewhere", corpus=r.corpus + "-other") for r in self.rows]
        c = compare_reports({"here": self.rows, "elsewhere": other})["comparisons"][0]
        self.assertEqual(c["mode"], "indirect")
        self.assertIn("no corpus in common", c["reasons"])
        self.assertEqual(len(c["corpora_in_one_report_only"]), 4)
        with tempfile.TemporaryDirectory() as tmp:
            markdown = write_comparison(compare_reports({"here": self.rows, "elsewhere": other}), tmp)[0].read_text()
        self.assertIn("Corpora in one report only", markdown)
        self.assertIn("Not directly comparable: no corpus in common", markdown)
        empty = analyze([])
        self.assertEqual({k: v for k, v in empty.items() if k != "notes"},
                         {"describe": [], "wins": [], "ranks": [], "agreement": [], "sensitivity": [], "meta": []})
        from src.evaluation.html_report import _scale_svg, _sensitivity_svg, _skill_color
        self.assertEqual((_scale_svg({"rows": []}), _sensitivity_svg([]), _skill_color(None)), ("", "", "#ffffff"))
