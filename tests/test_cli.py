"""
Command line paths not covered elsewhere: the default command, HTML output of
`audit` and `benchmark`, console encoding, `serve-mock`, `audit --url` with
`--save-crawl`, and `crawl --check-external`.

(Config wiring is in test_config.py, machine-readable output in test_export.py.)
"""

import io
import tempfile
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from src import cli
from src.benchmarks import mock_sites
from src.benchmarks.mock_sites import MockSiteServer
from tests import test_crawler as crawler_tests   # module alias: pytest must not collect its classes twice
from tests.fixtures.crawls import crawl_path

GREENLEAF_CONFIG = "config/sites/greenleaf.yaml"


def run_cli(*argv):
    out = io.StringIO()
    with redirect_stdout(out), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cli.main([str(arg) for arg in argv])
    return out.getvalue()


class TestCommands(unittest.TestCase):
    def test_no_command_runs_the_demo_audit(self):
        output = run_cli()
        self.assertIn("SITE AUDIT AND INTERNAL LINKING", output)
        self.assertIn("Demo dataset:", output)
        self.assertIn("Ranking: Demo audit", output)

    def test_audit_writes_the_html_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = run_cli("audit", "--from-crawl", crawl_path(mock_sites.SCRAMBLED_SITE),
                             "--config", GREENLEAF_CONFIG, "--html", tmp, "--top", "3")
            report = Path(tmp, "audit.html")
            self.assertTrue(report.is_file())
            self.assertIn("<h2>Site health</h2>", report.read_text(encoding="utf-8"))
        self.assertIn(f"[+] HTML report: {report.resolve()}", output)
        self.assertIn("top 3 of", output)

    def test_benchmark_of_one_site_writes_its_report_without_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = run_cli("benchmark", "--site", "reference", "--html", tmp, "--top", "2")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["reference.html"])
        self.assertIn("[OK] Expected links found: 7/7", output)
        self.assertIn("HTML report:", output)
        self.assertNotIn("site pages)", output)   # "(+N site pages)" only with an index

    def test_console_that_cannot_encode_page_text_does_not_crash(self):
        console = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
        with mock.patch("sys.stdout", console):
            cli.main(["boost-page2"])
            print("page text: caf\u00e9 \u2192 ok")
        self.assertEqual(console.errors, "replace")
        console.flush()
        self.assertIn(b"caf? ? ok", console.buffer.getvalue())


@pytest.mark.integration
class TestCommandsOverHttp(unittest.TestCase):
    def test_serve_mock_serves_until_interrupted(self):
        served = {}
        real_server = MockSiteServer

        def recording_server(site, port):
            served["server"] = real_server(site, port)
            return served["server"]

        class InterruptedEvent:
            """Stands in for the CLI's threading.Event: fetch a page while serving, then press Ctrl+C."""

            def wait(self):
                url = served["server"].base_url + "/"
                served["page"] = crawler_tests.HttpFetcher(timeout=5, retries=0).fetch(url)
                raise KeyboardInterrupt

        # Only the CLI's reference is replaced: Thread.start() itself relies on threading.Event.
        with mock.patch.object(cli, "threading", SimpleNamespace(Event=InterruptedEvent)), \
                mock.patch("src.cli.MockSiteServer", side_effect=recording_server):
            output = run_cli("serve-mock", mock_sites.GOOD_SITE, "--port", "0")
        self.assertEqual(served["page"].status, 200)
        self.assertIn(f"Serving mock site '{mock_sites.GOOD_SITE}' at {served['server'].base_url}/", output)
        self.assertIn("Stopped.", output)

    def test_audit_url_saves_the_crawl_for_later_runs(self):
        with MockSiteServer(mock_sites.SCRAMBLED_SITE) as server, tempfile.TemporaryDirectory() as tmp:
            saved = Path(tmp, "nested", "crawl.json")
            output = run_cli("audit", "--url", server.base_url + "/", "--config", GREENLEAF_CONFIG,
                             "--save-crawl", saved, "--max-pages", "50")
            self.assertTrue(saved.is_file())
            again = run_cli("audit", "--from-crawl", saved, "--config", GREENLEAF_CONFIG)
        self.assertIn(f"[+] Crawl saved to {saved}", output)
        self.assertIn("max 50 pages", output)
        proposed = [line for line in output.splitlines() if line.startswith("[*] Links proposed")]
        self.assertEqual(proposed, [line for line in again.splitlines() if line.startswith("[*] Links proposed")])

    def test_crawl_reports_checked_external_links(self):
        external = crawler_tests.RouteServer({"/ok/": (200, {}, crawler_tests.page("OK"))})
        self.addCleanup(external.close)
        site = crawler_tests.RouteServer({"/": (200, {}, crawler_tests.page(
            "Home", (external.url + "/ok/", "a working link"), (external.url + "/gone/", "a broken link")))})
        self.addCleanup(site.close)
        output = run_cli("crawl", "--url", site.url + "/", "--check-external")
        self.assertIn("External links checked: 2 (1 broken)", output)
        self.assertIn("broken_external_link", output)


if __name__ == "__main__":
    unittest.main()
