"""
Machine-readable output: the JSON / CSV exporters (src/reporting/export.py) and
the CLI options that write them (`--json`, `--csv`) plus the `--fail-on`
exit-code check used by CI jobs.

Unit tests use the saved crawls in tests/fixtures/ (no HTTP); only
TestCliCrawlOverHttp serves a mock site (integration tier).
"""

import csv
import io
import json
import tempfile
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

from src import cli
from src.benchmarks import get_benchmark, mock_sites, run_benchmark
from src.benchmarks.mock_sites import MockSiteServer
from src.connectors.sitemap_crawler import CrawlResult
from src.reporting import analyze_benchmark
from src.reporting.export import (
    ISSUE_FIELDS, LINK_FIELDS, PAGE_FIELDS, SCHEMA, SCHEMA_VERSION, export_document, failing_issues, issue_rows,
    link_rows, page_rows, to_json, write_csv, write_json,
)
from src.workflows.site_audit import ERROR, NOTICE, WARNING
from tests.fixtures.crawls import crawl_path, offline_analysis

GREENLEAF_CONFIG = "config/sites/greenleaf.yaml"


def _mock_site_analysis(site: str = mock_sites.SCRAMBLED_SITE):
    """Full run (audit + link proposals + ranking) of a mock site, from its saved crawl."""
    return offline_analysis(site)


def _scrambled_analysis():
    return offline_analysis(mock_sites.SCRAMBLED_SITE)


def _fixture_analysis():
    """A run on fixture pages (no crawl): ranking and proposals, but no site audit."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return analyze_benchmark(run_benchmark(get_benchmark("reference")))


def _read_csv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class TestJsonExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = _scrambled_analysis()
        cls.audit = cls.analysis.site_audit
        cls.document = export_document(cls.analysis)

    def test_document_describes_its_schema_and_the_site(self):
        self.assertEqual(self.document["schema"], SCHEMA)
        self.assertEqual(self.document["schema_version"], SCHEMA_VERSION)
        self.assertRegex(self.document["generated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(self.document["site"]["key"], mock_sites.SCRAMBLED_SITE)
        self.assertEqual(self.document["site"]["url"], self.audit.start_url)

    def test_site_audit_section_matches_the_audit_report(self):
        section = self.document["site_audit"]
        self.assertEqual(section["counts_by_severity"], self.audit.by_severity)
        self.assertEqual(section["counts_by_severity"], {ERROR: 4, WARNING: 16, NOTICE: 6})
        self.assertEqual(section["issues"], len(self.audit.issues))
        self.assertEqual((section["pages"], section["healthy_pages"]), (len(self.audit.pages), 0))
        self.assertEqual(section["health"], round(self.audit.health, 6))
        self.assertEqual(sum(section["counts_by_code"].values()), len(self.audit.issues))

    def test_issues_keep_the_report_order_and_fields(self):
        issues = self.document["issues"]
        self.assertEqual(len(issues), len(self.audit.issues))
        self.assertEqual(tuple(issues[0]), ISSUE_FIELDS)
        self.assertEqual([i["severity"] for i in issues[:4]], [ERROR] * 4)
        self.assertEqual([(i["code"], i["url"]) for i in issues],
                         [(i.code, i.url) for i in self.audit.issues])
        broken = next(i for i in issues if i["code"] == "broken_internal_link")
        self.assertEqual(broken["affected_pages"], sorted(
            next(i for i in self.audit.issues if i.code == "broken_internal_link").affected_pages))

    def test_pages_are_exported_best_first_with_their_derived_flags(self):
        pages = self.document["pages"]
        self.assertEqual(len(pages), len(self.analysis.pages))
        self.assertEqual(tuple(pages[0]), PAGE_FIELDS)
        self.assertEqual([p["rank_after"] for p in pages], list(range(1, len(pages) + 1)))
        best = self.analysis.pages[0]
        self.assertEqual(pages[0]["url"], best.url)
        self.assertEqual(pages[0]["rank_change"], best.rank_change)
        self.assertEqual(pages[0]["orphan_before"], best.orphan_before)
        self.assertEqual(pages[0]["orphan_after"], best.orphan_after)
        self.assertEqual(sum(p["new_inbound"] for p in pages), self.analysis.report.links_approved)

    def test_links_match_the_proposed_links(self):
        links = self.document["links"]
        self.assertEqual(len(links), self.analysis.report.links_approved)
        self.assertEqual(tuple(links[0]), LINK_FIELDS)
        self.assertEqual([(l["source_url"], l["target_url"]) for l in links],
                         [(r.source_url, r.target_url) for r in self.analysis.report.results])
        first = self.analysis.report.results[0]
        self.assertEqual(links[0]["anchor_text"], first.anchor_text)
        self.assertIn(first.anchor_text, links[0]["updated_sentence"])

    def test_optimization_summary_counts_the_run(self):
        summary = self.document["optimization"]
        report = self.analysis.report
        self.assertEqual(summary["links_proposed"], report.links_approved)
        self.assertEqual(summary["classifier_calls"], report.candidate_pairs_checked)
        self.assertEqual(summary["decisions_by_reason"], dict(sorted(report.decisions_by_reason.items())))
        self.assertGreaterEqual(summary["orphan_pages_before"], summary["orphan_pages_after"])

    def test_audit_only_source_exports_issues_without_ranking(self):
        document = export_document(self.audit)
        self.assertEqual(document["issues"], self.document["issues"])
        self.assertEqual((document["pages"], document["links"], document["optimization"]), ([], [], None))
        self.assertEqual(document["site"], {"key": "crawl", "name": self.audit.start_url, "url": self.audit.start_url})
        self.assertEqual(issue_rows(self.audit), self.document["issues"])
        self.assertEqual((page_rows(self.audit), link_rows(self.audit)), ([], []))

    def test_run_without_a_crawl_exports_the_ranking_without_issues(self):
        document = export_document(_fixture_analysis())
        self.assertIsNone(document["site_audit"])
        self.assertEqual(document["issues"], [])
        self.assertEqual(document["site"]["url"], "")
        self.assertTrue(document["pages"] and document["links"])

    def test_json_is_valid_utf8_and_reproducible(self):
        text = to_json(self.analysis)
        reloaded = json.loads(text)
        self.assertEqual(reloaded["issues"], self.document["issues"])
        without_time = lambda doc: {k: v for k, v in doc.items() if k != "generated_at"}
        self.assertEqual(without_time(reloaded), without_time(json.loads(to_json(self.analysis))))

    def test_write_json_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(self.analysis, Path(tmp, "out", "audit.json"), name="My site")
            self.assertTrue(path.is_file())
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            document = json.loads(text)
        self.assertEqual(document["site"]["name"], "My site")
        self.assertEqual(len(document["pages"]), len(self.analysis.pages))


class TestCsvExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = _scrambled_analysis()

    def test_three_tables_are_written_with_their_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_csv(self.analysis, tmp)
            self.assertEqual([p.name for p in paths], ["issues.csv", "pages.csv", "links.csv"])
            issues, pages, links = (_read_csv(p) for p in paths)
            self.assertEqual(tuple(issues[0]), ISSUE_FIELDS)
            self.assertEqual(tuple(pages[0]), PAGE_FIELDS)
            self.assertEqual(tuple(links[0]), LINK_FIELDS)
        self.assertEqual(len(issues), len(self.analysis.site_audit.issues))
        self.assertEqual(len(pages), len(self.analysis.pages))
        self.assertEqual(len(links), self.analysis.report.links_approved)
        self.assertEqual(pages[0]["url"], self.analysis.pages[0].url)

    def test_values_are_flattened_for_spreadsheets(self):
        with tempfile.TemporaryDirectory() as tmp:
            issues, pages, _ = (_read_csv(p) for p in write_csv(self.analysis, tmp))
        broken = next(row for row in issues if row["code"] == "broken_internal_link")
        affected = next(i for i in self.analysis.site_audit.issues if i.code == "broken_internal_link").affected_pages
        self.assertEqual(broken["affected_pages"].split(), sorted(affected))
        self.assertIn(pages[0]["crawled"], ("true", "false"))
        self.assertEqual({row["gsc_query"] for row in pages}, {""})  # None becomes an empty cell

    def test_run_without_a_crawl_writes_no_issue_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_csv(_fixture_analysis(), tmp)
            self.assertEqual([p.name for p in paths], ["pages.csv", "links.csv"])
            self.assertFalse(Path(tmp, "issues.csv").exists())

    def test_audit_only_source_writes_the_issue_table_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_csv(self.analysis.site_audit, tmp)
            self.assertEqual([p.name for p in paths], ["issues.csv"])
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["issues.csv"])


class TestFailingIssues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = _scrambled_analysis()
        cls.audit = cls.analysis.site_audit

    def test_fail_on_error_matches_errors_only(self):
        issues = failing_issues(self.audit, ERROR)
        self.assertEqual({i.severity for i in issues}, {ERROR})
        self.assertEqual(len(issues), self.audit.by_severity[ERROR])

    def test_fail_on_warning_also_matches_errors(self):
        issues = failing_issues(self.analysis, WARNING)
        self.assertEqual({i.severity for i in issues}, {ERROR, WARNING})
        self.assertEqual(len(issues), self.audit.by_severity[ERROR] + self.audit.by_severity[WARNING])

    def test_no_severity_no_audit_and_unknown_severity_never_fail(self):
        self.assertEqual(failing_issues(self.audit, None), [])
        self.assertEqual(failing_issues(self.audit, ""), [])
        self.assertEqual(len(failing_issues(self.audit, NOTICE)), len(self.audit.issues))  # "or above"
        self.assertEqual(failing_issues(self.audit, "fatal"), [])
        self.analysis.site_audit = None
        try:
            self.assertEqual(failing_issues(self.analysis, ERROR), [])
        finally:
            self.analysis.site_audit = self.audit

    def test_healthy_site_has_nothing_to_fail_on(self):
        self.assertEqual(failing_issues(_mock_site_analysis(mock_sites.GOOD_SITE), WARNING), [])


def run_cli(*argv):
    """Run the CLI in-process: (exit status, 0 when it does not exit; stdout)."""
    out = io.StringIO()
    status = 0
    try:
        with redirect_stdout(out), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cli.main([str(arg) for arg in argv])
    except SystemExit as exit_:
        status = exit_.code
    return status, out.getvalue()


class TestCliFromSavedCrawl(unittest.TestCase):
    """`audit --from-crawl` with the machine-readable options (no network)."""

    def test_audit_exports_the_full_run_and_fails_on_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp, "audit.json")
            status, output = run_cli("audit", "--from-crawl", crawl_path(mock_sites.SCRAMBLED_SITE),
                                     "--config", GREENLEAF_CONFIG, "--json", json_path, "--csv", tmp,
                                     "--fail-on", "warning")
            document = json.loads(json_path.read_text(encoding="utf-8"))
            tables = {name: _read_csv(Path(tmp, f"{name}.csv")) for name in ("issues", "pages", "links")}
        self.assertEqual(status, 1)
        self.assertIn("Quality gate failed (--fail-on warning): 4 error(s), 16 warning(s).", output)
        self.assertIn("... and 15 more", output)
        self.assertEqual(document["site"]["url"], mock_sites.PRODUCTION_BASE + "/")
        self.assertEqual(document["optimization"]["links_proposed"], len(mock_sites.SCRAMBLED_EXPECTED_PROPOSALS))
        for name, rows in tables.items():
            self.assertEqual(len(rows), len(document[name]), name)

    def test_healthy_site_passes_the_strictest_gate(self):
        status, output = run_cli("audit", "--from-crawl", crawl_path(mock_sites.GOOD_SITE),
                                 "--config", GREENLEAF_CONFIG, "--fail-on", "warning")
        self.assertEqual(status, 0)
        self.assertIn("Quality gate passed: no issue of severity 'warning' or above", output)

    def test_without_fail_on_the_command_never_exits(self):
        status, output = run_cli("audit", "--from-crawl", crawl_path(mock_sites.SCRAMBLED_SITE),
                                 "--config", GREENLEAF_CONFIG)
        self.assertEqual(status, 0)
        self.assertNotIn("Quality gate", output)

    def test_empty_crawl_still_exports_its_audit(self):
        empty = CrawlResult("https://empty.example/", [], [], False, {"https://empty.example/": 0}, {}, [])
        with tempfile.TemporaryDirectory() as tmp:
            saved, json_path = empty.save(Path(tmp, "empty.json")), Path(tmp, "out.json")
            status, output = run_cli("audit", "--from-crawl", saved, "--json", json_path, "--fail-on", "error")
            document = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(status, 0)
        self.assertIn("No HTML page could be crawled", output)
        self.assertIn("Quality gate passed", output)
        self.assertEqual((document["issues"], document["pages"], document["optimization"]), ([], [], None))

    def test_demo_audit_exports_issues_rankings_and_proposals(self):
        # Definition of done: `audit --json` on the demo dataset holds the audit issues, the page
        # ranking and the link proposals in one valid JSON document.
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp, "link_audit.json")
            status, output = run_cli("audit", "--json", json_path)
            document = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(status, 0)
        self.assertIn("site audit included", output)
        self.assertEqual(document["site"]["name"], "Demo audit")
        self.assertEqual(document["site_audit"]["counts_by_severity"], {ERROR: 1, WARNING: 2, NOTICE: 4})
        self.assertEqual([i["code"] for i in document["issues"] if i["severity"] == ERROR], ["orphan_page"])
        self.assertEqual(len(document["pages"]), 4)
        self.assertEqual([p["rank_after"] for p in document["pages"]], [1, 2, 3, 4])
        self.assertEqual(len(document["links"]), document["optimization"]["links_proposed"])
        self.assertGreater(len(document["links"]), 0)
        status, output = run_cli("audit", "--fail-on", "error")
        self.assertEqual(status, 1)                                     # the orphan page is an error
        self.assertIn("orphan_page", output)

    def test_runs_without_a_site_audit_have_nothing_to_gate_on(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli._fail_on_status(None, "error"), 0)
        self.assertIn("no site audit", out.getvalue())

    def test_unknown_severity_is_rejected_by_the_parser(self):
        with self.assertRaises(SystemExit) as exit_info, redirect_stdout(io.StringIO()), \
                mock.patch("sys.stderr", io.StringIO()) as stderr:
            cli.main(["crawl", "--url", "https://x.example/", "--fail-on", "notice"])
        self.assertEqual(exit_info.exception.code, 2)
        self.assertIn("invalid choice: 'notice'", stderr.getvalue())


@pytest.mark.integration
class TestCliCrawlOverHttp(unittest.TestCase):
    """`crawl` against a served mock site with the machine-readable options."""

    def test_crawl_writes_json_and_csv_and_fails_on_errors(self):
        with MockSiteServer(mock_sites.SCRAMBLED_SITE) as server, tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp, "crawl.json")
            status, output = run_cli("crawl", "--url", server.base_url + "/", "--issues", "3",
                                     "--json", json_path, "--csv", tmp, "--fail-on", "error")
            document = json.loads(json_path.read_text(encoding="utf-8"))
            issues = _read_csv(Path(tmp, "issues.csv"))
            self.assertFalse(Path(tmp, "pages.csv").exists())  # crawl has no ranking
        self.assertEqual(status, 1)
        self.assertIn("Quality gate failed (--fail-on error)", output)
        self.assertIn("4 error(s)", output)
        self.assertIn(str(json_path.resolve()), output)
        self.assertEqual(document["site_audit"]["counts_by_severity"], {ERROR: 4, WARNING: 16, NOTICE: 6})
        self.assertEqual(len(document["issues"]), len(issues))
        self.assertEqual(document["pages"], [])

    def test_crawl_of_a_healthy_site_passes_the_quality_gate(self):
        with MockSiteServer(mock_sites.GOOD_SITE) as server:
            status, output = run_cli("crawl", "--url", server.base_url + "/", "--fail-on", "warning")
        self.assertEqual(status, 0)
        self.assertIn("Quality gate passed", output)

    def test_crawl_without_fail_on_never_exits(self):
        with MockSiteServer(mock_sites.SCRAMBLED_SITE) as server:
            status, output = run_cli("crawl", "--url", server.base_url + "/", "--issues", "1")
        self.assertEqual(status, 0)
        self.assertNotIn("Quality gate", output)


if __name__ == "__main__":
    unittest.main()
