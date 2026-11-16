"""Example user classifier plugin used by the tests (provider: python:tests.classifier_plugin:KeywordClassifier)."""


class KeywordClassifier:
    """Relevant when the paragraph contains the target title verbatim. Returns a plain dict."""

    cost_per_call_usd = 0.0

    def __init__(self, config):
        self.config = config

    def evaluate(self, candidate):
        hit = candidate.target_title.lower() in candidate.source_paragraph.lower()
        return {"relevant": hit, "confidence": 0.95 if hit else 0.1, "score": 9 if hit else 2}


class NoEvaluate:
    pass


class Exploding:
    def evaluate(self, candidate):
        raise RuntimeError("model crashed")
