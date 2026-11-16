"""
TypeSafe Jev System One Client.

Interacts with the TypeSafe Jev API (POST https://api.typesafe.ai/v1/systemone)
for ultra-fast, structured decisions using Choice, Score, and Noul primitives.
Includes an intelligent local simulation mode for offline testing and staging.
Zero-external-dependency capable (uses urllib and dataclasses with pydantic/httpx fallback).
"""

import os
import time
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from src.engines.classifiers.heuristic import heuristic_scores
from src.log import get_logger

logger = get_logger(__name__)


@dataclass
class JevQuestion:
    id: str
    type: str  # 'choice', 'score', or 'noul'
    prompt: str
    options: Optional[List[str]] = None
    scale: Optional[List[int]] = None


@dataclass
class JevEvaluationRequest:
    state: Dict[str, Any]
    questions: List[JevQuestion]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "questions": [asdict(q) for q in self.questions],
        }


class JevClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.typesafe.ai/v1/systemone",
        timeout: float = 10.0,
        mock_mode: bool = False,
    ):
        self.api_key = api_key or os.getenv("TYPESAFE_API_KEY", "")
        self.base_url = base_url
        self.timeout = timeout
        self.mock_mode = mock_mode or not bool(self.api_key)
        logger.info(
            "Jev client ready: %s",
            "offline simulation (no TYPESAFE_API_KEY)" if self.mock_mode else f"API {self.base_url}",
        )

    def evaluate(self, request: JevEvaluationRequest, raise_on_error: bool = False) -> Dict[str, Any]:
        """
        Execute parallel decision questions on the provided state.
        Network failures fall back to the offline simulation unless raise_on_error.
        """
        if self.mock_mode:
            return self._mock_evaluate(request)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "SEO-Magus-JevClient/1.0",
        }

        payload = json.dumps(request.to_dict()).encode("utf-8")
        req = Request(self.base_url, data=payload, headers=headers, method="POST")

        started = time.perf_counter()
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, ValueError) as e:
            if raise_on_error:
                from src.engines.classifiers.base import ClassifierError
                raise ClassifierError(f"Jev API request failed: {e}") from e
            # Fallback to simulation if endpoint is unreachable or in test environment
            logger.warning("Jev API unreachable (%s); falling back to offline simulation for this request", e)
            return self._mock_evaluate(request)
        logger.debug("Jev API answered in %.0f ms", 1000 * (time.perf_counter() - started))
        return data

    def evaluate_link_candidate(
        self,
        source_url: str,
        source_paragraph: str,
        target_url: str,
        target_title: str,
        target_topic: str,
        target_queries: Optional[List[str]] = None,
        raise_on_error: bool = False,
    ) -> Dict[str, Any]:
        """
        Evaluate whether source_paragraph should link to target_url.
        Uses two Noul questions (legitimacy, anchor readiness) and one Score question.
        target_queries are search queries the target ranks for on SERP page 2
        (from Search Console): they describe how readers look for the target.
        """
        queries = list(target_queries or [])
        searched_as = f" Readers search for it as: {'; '.join(queries)}." if queries else ""
        questions = [
            JevQuestion(
                id="has_legitimate_contextual_reason",
                type="noul",
                prompt=f"Does this source paragraph have an immediate, natural educational/contextual reason to guide the reader to the page about '{target_topic}' ({target_title}) without being spammy or off-topic?{searched_as}",
            ),
            JevQuestion(
                id="candidate_anchor_present",
                type="noul",
                prompt="Does this source paragraph contain existing words or a natural phrase that clearly introduces the concept of the target destination?",
            ),
            JevQuestion(
                id="relevance_score",
                type="score",
                scale=[1, 10],
                prompt=f"Score from 1 to 10 how valuable this link transition is for someone reading about '{target_topic}'.",
            ),
        ]

        req = JevEvaluationRequest(
            state={
                "source_url": source_url,
                "source_paragraph": source_paragraph,
                "target_url": target_url,
                "target_title": target_title,
                "target_topic": target_topic,
                "target_queries": queries,
            },
            questions=questions,
        )

        return self.evaluate(req, raise_on_error=raise_on_error)

    def _mock_evaluate(self, request: JevEvaluationRequest) -> Dict[str, Any]:
        """
        Offline simulation used when no API key is provided: answers Jev's
        questions with the shared heuristic (src/engines/classifiers/heuristic.py).
        """
        state = request.state
        relevant, confidence, score, matched = heuristic_scores(
            state.get("source_paragraph", ""), state.get("target_title", ""),
            state.get("target_topic", ""), state.get("target_queries", []),
        )
        results: Dict[str, Any] = {}
        for q in request.questions:
            if q.type == "noul":
                results[q.id] = {"value": relevant, "confidence": confidence}
            elif q.type == "score":
                results[q.id] = {"score": score}
            elif q.type == "choice":
                selected = q.options[0] if q.options else "General"
                results[q.id] = {"selected": selected, "confidence": 0.88}

        logger.debug(
            "Jev simulation: %s -> %s matched %d topic tokens %s",
            state.get("source_url"), state.get("target_url"), len(matched), sorted(matched),
        )
        return {"results": results, "latency_ms": 0, "simulated": True}
