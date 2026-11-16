"""
Documentation must match the code: every audit check, CLI command and option,
config key, classifier provider, benchmark site and make target that the docs
mention exists, everything users can use is documented, and relative links resolve.
"""

import re
import unittest
from dataclasses import fields
from pathlib import Path

from src.benchmarks import BENCHMARKS, mock_sites
from src.cli import build_parser
from src.config import LinkRules, Thresholds
from src.connectors.sitemap_crawler import CrawlConfig
from src.engines.classifiers.factory import PROVIDERS, ClassifierConfig
from src.engines.taxonomy import TAXONOMY_KEYS
from src.workflows.site_audit import ISSUE_SEVERITY

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").glob("*.md"))]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def slug(heading: str) -> str:
    """GitHub heading anchor."""
    text = heading.strip().lower().replace("`", "")
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


class TestDocsMatchCode(unittest.TestCase):
    def test_every_audit_check_is_documented_with_its_severity(self):
        table = dict(re.findall(r"^\| `(\w+)` \| (error|warning|notice) \|", read("docs/CRAWLER.md"), re.M))
        self.assertEqual(table, ISSUE_SEVERITY)
        self.assertIn(f"{len(ISSUE_SEVERITY)} checks", read("README.md"))

    def test_every_cli_command_and_option_is_documented(self):
        guide = read("docs/USER_GUIDE.md")
        parser = build_parser()
        for action in parser._actions:
            for option in action.option_strings:
                if option.startswith("--") and option != "--help":
                    self.assertTrue(f"`{option}" in guide, f"{option} is not documented in docs/USER_GUIDE.md")
        subparsers = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
        for name, sub in subparsers.choices.items():
            with self.subTest(command=name):
                self.assertIn(f"### `{name}`", guide)
                for action in sub._actions:
                    for option in action.option_strings:
                        if option.startswith("--") and option not in ("--help", "--demo"):
                            self.assertTrue(f"`{option}" in guide, f"{name} {option} is not documented")

    def test_every_config_key_is_documented(self):
        doc = read("docs/CONFIGURATION.md")
        keys = {
            "crawler": [f.name for f in fields(CrawlConfig)],
            "thresholds": [f.name for f in fields(Thresholds)],
            "classifier": [f.name for f in fields(ClassifierConfig)],
            "link_rules": [f.name for f in fields(LinkRules)],
            "taxonomy": list(TAXONOMY_KEYS),
        }
        for section, names in keys.items():
            for name in names:
                with self.subTest(section=section, key=name):
                    needle = f"`{name}`" if section != "taxonomy" else f"{name}:"
                    self.assertTrue(needle in doc, f"{section}.{name} is not documented in docs/CONFIGURATION.md")

    def test_every_classifier_provider_is_documented(self):
        doc = read("docs/CLASSIFIERS.md")
        for provider in PROVIDERS:
            self.assertIn(f"| `{provider}`", doc)

    def test_every_benchmark_site_is_documented(self):
        doc = read("docs/BENCHMARKS.md")
        for key in BENCHMARKS:
            self.assertIn(f"`{key}`", doc)

    def test_mock_site_numbers(self):
        doc = read("docs/BENCHMARKS.md")
        issues = mock_sites.EXPECTED_ISSUES[mock_sites.SCRAMBLED_SITE]
        severities = [ISSUE_SEVERITY[code] for code, _ in issues]
        self.assertIn(f"exactly its {len(issues)} issues ({severities.count('error')} errors, "
                      f"{severities.count('warning')} warnings, {severities.count('notice')} notices)", doc)
        self.assertIn(f"exactly the {len(mock_sites.SCRAMBLED_EXPECTED_PROPOSALS)} contextual links", doc)

    def test_make_targets_mentioned_in_docs_exist(self):
        targets = set(re.findall(r"^([a-z][\w-]*):", read("Makefile"), re.M))
        for doc in DOCS:
            for target in re.findall(r"`make ([a-z][\w-]*)", doc.read_text(encoding="utf-8")):
                with self.subTest(doc=doc.name, target=target):
                    self.assertIn(target, targets)

    def test_relative_links_resolve(self):
        for doc in DOCS:
            text = doc.read_text(encoding="utf-8")
            for target in re.findall(r"\]\(([^)\s]+)\)", text):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path, _, anchor = target.partition("#")
                file = (doc.parent / path).resolve() if path else doc
                with self.subTest(doc=doc.name, link=target):
                    self.assertTrue(file.exists(), f"{target} does not exist")
                    if anchor and file.suffix == ".md":
                        headings = re.findall(r"^#+ (.+)$", file.read_text(encoding="utf-8"), re.M)
                        self.assertIn(anchor, {slug(h) for h in headings})


if __name__ == "__main__":
    unittest.main()
