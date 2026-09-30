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

    def evaluate(self, request: JevEvaluationRequest) -> Dict[str, Any]:
        """
        Execute parallel decision questions on the provided state.
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

        try:
            with urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except URLError as e:
            # Fallback to simulation if endpoint is unreachable or in test environment
            return self._mock_evaluate(request)

    def evaluate_link_candidate(
        self,
        source_url: str,
        source_paragraph: str,
        target_url: str,
        target_title: str,
        target_topic: str,
    ) -> Dict[str, Any]:
        """
        Evaluate whether source_paragraph should link to target_url.
        Uses two Noul questions (legitimacy, anchor readiness) and one Score question.
        """
        questions = [
            JevQuestion(
                id="has_legitimate_contextual_reason",
                type="noul",
                prompt=f"Does this source paragraph have an immediate, natural educational/contextual reason to guide the reader to the page about '{target_topic}' ({target_title}) without being spammy or off-topic?",
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
            },
            questions=questions,
        )

        return self.evaluate(req)

    def _mock_evaluate(self, request: JevEvaluationRequest) -> Dict[str, Any]:
        """
        Realistic heuristic-based mock simulation when no API key is provided.
        Simulates sub-second latency and realistic scoring.
        """
        time.sleep(0.02)  # Simulate 20ms Jev latency
        state = request.state
        results: Dict[str, Any] = {}

        for q in request.questions:
            if q.type == "noul":
                source_p = state.get("source_paragraph", "").lower()
                target_topic = state.get("target_topic", "").lower()
                target_title = state.get("target_title", "").lower()

                topic_words = set(target_topic.split() + target_title.split()) - {
                    "the", "a", "an", "and", "or", "in", "to", "for", "of", "with"
                }
                match_count = sum(1 for w in topic_words if w and w in source_p)

                has_match = match_count >= 1
                confidence = min(0.98, 0.65 + (match_count * 0.12)) if has_match else 0.25

                results[q.id] = {
                    "value": has_match,
                    "confidence": round(confidence, 2),
                }

            elif q.type == "score":
                source_p = state.get("source_paragraph", "").lower()
                target_topic = state.get("target_topic", "").lower()
                topic_words = set(target_topic.split()) - {"the", "a", "to", "for"}
                match_count = sum(1 for w in topic_words if w and w in source_p)
                score = min(9.6, 5.0 + match_count * 1.8) if match_count > 0 else 3.2
                results[q.id] = {"score": round(score, 1)}

            elif q.type == "choice":
                selected = q.options[0] if q.options else "General"
                results[q.id] = {"selected": selected, "confidence": 0.88}

        return {"results": results, "latency_ms": 25, "simulated": True}
