"""
Offline heuristic classifier: no model, no network, deterministic.

Topic vocabulary = content tokens of the target title + topic (H1) + page 2
queries; m = number of those tokens the paragraph mentions (shared matching rule
in src/engines/text.py):
    relevant   = m >= 1
    confidence = min(0.98, 0.65 + 0.12 m)   (0.25 when m = 0)
    score      = min(9.6, 5.0 + 1.8 m)      (3.2 when m = 0)
"""

from typing import Iterable, Tuple

from src.engines.classifiers.base import LinkCandidate, LinkClassifier, LinkJudgement
from src.engines.text import content_tokens, matched_topic_tokens


def heuristic_scores(paragraph: str, title: str, topic: str, queries: Iterable[str] = ()) -> Tuple[bool, float, float, set]:
    vocabulary = content_tokens(title, topic, *queries)
    matched = matched_topic_tokens(vocabulary, paragraph)
    m = len(matched)
    confidence = min(0.98, 0.65 + 0.12 * m) if m else 0.25
    score = min(9.6, 5.0 + 1.8 * m) if m else 3.2
    return m >= 1, round(confidence, 2), round(score, 1), matched


class HeuristicClassifier(LinkClassifier):
    name = "heuristic"
    cost_per_call_usd = 0.0

    def evaluate(self, candidate: LinkCandidate) -> LinkJudgement:
        relevant, confidence, score, matched = heuristic_scores(
            candidate.source_paragraph, candidate.target_title, candidate.target_topic, candidate.target_queries
        )
        return LinkJudgement(relevant, confidence, score, self.name, f"matched topic words {sorted(matched)}")
