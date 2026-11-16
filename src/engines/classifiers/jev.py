"""TypeSafe Jev System One as a LinkClassifier (the default provider when a key is set)."""

from typing import Optional

from src.engines.classifiers.base import ClassifierError, LinkCandidate, LinkClassifier, LinkJudgement
from src.engines.jev_client import JevClient

JEV_COST_PER_CALL_USD = 0.000025


class JevClassifier(LinkClassifier):
    name = "jev"

    def __init__(self, client: Optional[JevClient] = None, api_key: Optional[str] = None,
                 base_url: Optional[str] = None, timeout: float = 10.0,
                 cost_per_call_usd: float = JEV_COST_PER_CALL_USD):
        kwargs = {"timeout": timeout}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = client or JevClient(api_key=api_key, **kwargs)
        self.cost_per_call_usd = cost_per_call_usd

    def describe(self) -> str:
        return f"jev ({'offline simulation' if self.client.mock_mode else self.client.base_url})"

    def evaluate(self, candidate: LinkCandidate) -> LinkJudgement:
        response = self.client.evaluate_link_candidate(
            source_url=candidate.source_url,
            source_paragraph=candidate.source_paragraph,
            target_url=candidate.target_url,
            target_title=candidate.target_title,
            target_topic=candidate.target_topic,
            target_queries=list(candidate.target_queries),
            raise_on_error=True,
        )
        try:
            results = response["results"]
            legit = results["has_legitimate_contextual_reason"]
            return LinkJudgement(
                relevant=bool(legit["value"]),
                confidence=float(legit.get("confidence", 0.0)),
                score=float(results["relevance_score"]["score"]),
                provider="jev-simulation" if response.get("simulated") else "jev",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ClassifierError(f"unexpected Jev response: {exc!r}") from exc
