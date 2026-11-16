"""
LLM-backed link classifiers over plain HTTP (urllib, no vendor SDK).

* OpenAICompatibleClassifier - POST {base_url}/chat/completions. Works with OpenAI
  and every OpenAI-compatible server: Gemini's OpenAI endpoint, OpenRouter, Groq,
  and local servers such as Ollama, LM Studio, llama.cpp or vLLM.
* AnthropicClassifier - POST {base_url}/messages (Anthropic Messages API).

Both send the same prompt and expect a JSON object
{"relevant": true|false, "confidence": 0..1, "score": 1..10}.
"""

import json
import re
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.engines.classifiers.base import ClassifierError, LinkCandidate, LinkClassifier, LinkJudgement
from src.log import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "You are an SEO internal-linking judge. Decide whether a source paragraph gives its reader an "
    "immediate, natural, non-spammy reason to follow a link to a target page of the same website. "
    'Answer only with a JSON object: {"relevant": true or false, "confidence": number from 0 to 1, '
    '"score": integer from 1 to 10 for how valuable the link is to the reader}.'
)
_JSON_OBJECT_RE = re.compile(r"\{.*?\}", re.DOTALL)


def build_prompt(candidate: LinkCandidate) -> str:
    queries = "; ".join(candidate.target_queries) or "(none)"
    return (
        f"Source paragraph:\n{candidate.source_paragraph}\n\n"
        f"Target page title: {candidate.target_title}\n"
        f"Target page topic: {candidate.target_topic}\n"
        f"Search queries the target ranks for on page 2: {queries}\n\n"
        "Reply with the JSON object only."
    )


def parse_judgement(text: str, provider: str) -> LinkJudgement:
    """Extract and validate the JSON verdict from a model answer."""
    for match in _JSON_OBJECT_RE.finditer(text or ""):
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or not {"relevant", "confidence", "score"} <= set(data):
            continue
        relevant = data["relevant"]
        if isinstance(relevant, str):
            relevant = relevant.strip().lower() in ("true", "yes", "1")
        try:
            return LinkJudgement(bool(relevant), float(data["confidence"]), float(data["score"]), provider)
        except (TypeError, ValueError) as exc:
            raise ClassifierError(f"{provider}: invalid values in {data!r}") from exc
    raise ClassifierError(f"{provider}: no JSON verdict in answer {text[:200]!r}")


def post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method="POST",
                      headers={"Content-Type": "application/json", "User-Agent": "SEO-Magus/1.0", **headers})
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300] if exc.fp else ""
        raise ClassifierError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except (URLError, OSError, ValueError) as exc:
        raise ClassifierError(f"request to {url} failed: {getattr(exc, 'reason', exc)}") from exc
    logger.debug("POST %s answered in %.0f ms", url, 1000 * (time.perf_counter() - started))
    return data


class _HttpLLMClassifier(LinkClassifier):
    def __init__(self, name: str, base_url: str, model: str, api_key: Optional[str] = None,
                 timeout: float = 30.0, temperature: float = 0.0, max_tokens: int = 100,
                 cost_per_call_usd: float = 0.0):
        if not base_url:
            raise ValueError(f"classifier '{name}' needs a base_url")
        if not model:
            raise ValueError(f"classifier '{name}' needs a model name (classifier.model)")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.cost_per_call_usd = cost_per_call_usd

    def describe(self) -> str:
        return f"{self.name} ({self.model} @ {self.base_url})"


class OpenAICompatibleClassifier(_HttpLLMClassifier):
    def evaluate(self, candidate: LinkCandidate) -> LinkJudgement:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = post_json(f"{self.base_url}/chat/completions", {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(candidate)},
            ],
        }, headers, self.timeout)
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ClassifierError(f"{self.name}: unexpected response shape {str(data)[:200]}") from exc
        return parse_judgement(text, self.name)


class AnthropicClassifier(_HttpLLMClassifier):
    API_VERSION = "2023-06-01"

    def evaluate(self, candidate: LinkCandidate) -> LinkJudgement:
        headers = {"anthropic-version": self.API_VERSION}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        data = post_json(f"{self.base_url}/messages", {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": build_prompt(candidate)}],
        }, headers, self.timeout)
        try:
            text = "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
        except (KeyError, TypeError, AttributeError) as exc:
            raise ClassifierError(f"{self.name}: unexpected response shape {str(data)[:200]}") from exc
        return parse_judgement(text, self.name)
