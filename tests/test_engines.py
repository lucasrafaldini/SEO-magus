"""
Unit Tests for SEO-Magus Core Engines.
"""

import unittest
from src.engines.link_graph import LinkGraph
from src.engines.jev_client import JevClient, JevQuestion, JevEvaluationRequest
from src.engines.auxiliary_ai import AuxiliaryAIEngine
from src.connectors.gsc_connector import GSCConnector, GSCQueryRow


class TestLinkGraph(unittest.TestCase):
    def setUp(self):
        self.graph = LinkGraph()

    def test_add_pages_and_links(self):
        self.graph.add_page("https://example.com/pillar", role="pillar")
        self.graph.add_page("https://example.com/support", role="support")
        self.graph.add_link("https://example.com/support", "https://example.com/pillar")

        self.assertTrue(self.graph.has_link("https://example.com/support", "https://example.com/pillar"))
        self.assertFalse(self.graph.has_link("https://example.com/pillar", "https://example.com/support"))

    def test_orphan_page_detection(self):
        self.graph.add_page("https://example.com/a")
        self.graph.add_page("https://example.com/orphan")
        self.graph.add_link("https://example.com/b", "https://example.com/a")

        orphans = self.graph.find_orphan_pages()
        self.assertIn("https://example.com/orphan", orphans)

    def test_pagerank_computation(self):
        self.graph.add_page("https://example.com/a")
        self.graph.add_page("https://example.com/b")
        self.graph.add_page("https://example.com/c")
        self.graph.add_link("https://example.com/a", "https://example.com/b")
        self.graph.add_link("https://example.com/c", "https://example.com/b")

        pr = self.graph.compute_pagerank()
        self.assertGreater(pr["https://example.com/b"], pr["https://example.com/a"])

    def test_taxonomy_validation(self):
        self.graph.add_page("https://example.com/support", role="support")
        self.graph.add_page("https://example.com/money", role="money")

        valid, _ = self.graph.validate_link_rules("https://example.com/support", "https://example.com/money")
        self.assertTrue(valid)

        invalid, reason = self.graph.validate_link_rules("https://example.com/money", "https://example.com/support")
        self.assertFalse(invalid)
        self.assertIn("Commercial money pages", reason)


class TestJevClient(unittest.TestCase):
    def setUp(self):
        self.client = JevClient(mock_mode=True)

    def test_link_candidate_evaluation(self):
        res = self.client.evaluate_link_candidate(
            source_url="https://example.com/blog/tips",
            source_paragraph="You need to set up a sequence of welcome emails for new subscribers.",
            target_url="https://example.com/blog/welcome-sequence",
            target_title="Welcome Sequence Guide",
            target_topic="welcome sequence",
        )
        self.assertIn("results", res)
        results = res["results"]
        self.assertTrue(results["has_legitimate_contextual_reason"]["value"])
        self.assertGreaterEqual(results["relevance_score"]["score"], 7.0)


class TestAuxiliaryAI(unittest.TestCase):
    def setUp(self):
        self.aux = AuxiliaryAIEngine()

    def test_craft_link_insertion(self):
        paragraph = "You need to set up an automated welcome sequence for all new signups."
        proposal = self.aux.craft_link_insertion(
            source_paragraph=paragraph,
            target_url="https://example.com/welcome-guide",
            target_title="Welcome Sequence Guide",
            target_topic="welcome sequence",
        )
        self.assertIsNotNone(proposal)
        self.assertIn("welcome", proposal.anchor_text.lower())
        self.assertIn("[", proposal.updated_sentence)
        self.assertIn("https://example.com/welcome-guide", proposal.updated_sentence)


class TestGSCConnector(unittest.TestCase):
    def test_page2_filtering(self):
        connector = GSCConnector()
        rows = [
            GSCQueryRow(query="page 1 term", page="p1", clicks=100, impressions=5000, ctr=0.02, position=3.4),
            GSCQueryRow(query="page 2 term high imp", page="p2", clicks=10, impressions=2500, ctr=0.004, position=13.5),
            GSCQueryRow(query="page 2 term low imp", page="p3", clicks=2, impressions=20, ctr=0.1, position=15.0),
            GSCQueryRow(query="page 3 term", page="p4", clicks=0, impressions=300, ctr=0.0, position=25.0),
        ]
        opps = connector.get_page2_opportunities(rows, min_impressions=50)
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].query, "page 2 term high imp")


if __name__ == "__main__":
    unittest.main()
