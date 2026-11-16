# Link Classifiers ("System 1")

For every candidate pair (source paragraph → target page) a classifier answers one question: *does this paragraph
give the reader a natural reason to follow a link to the target, how confident are you (0–1) and how valuable is the
link (1–10)?* Pairs that pass the gate (`thresholds.min_confidence`, `thresholds.min_score`) go on to anchor
selection. The optimizer only depends on this interface, so any model can be used.

## Choosing a provider

```yaml
classifier:
  provider: ollama          # see the table
  model: "llama3.2:3b"
```

| `provider` | What it is | API key (environment variable) | Default endpoint |
| :--- | :--- | :--- | :--- |
| `auto` *(default)* | `jev` when `TYPESAFE_API_KEY` is set, else `heuristic` | – | – |
| `heuristic` | offline, deterministic, free: counts the target's topic words in the paragraph | – | – |
| `jev` | TypeSafe Jev System One ([details](JEV_INTEGRATION.md)) | `TYPESAFE_API_KEY` | `https://api.typesafe.ai/v1/systemone` |
| `openai` | OpenAI Chat Completions | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| `anthropic` | Anthropic Messages API | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` |
| `gemini` | Google Gemini (OpenAI-compatible endpoint) | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `openrouter` | OpenRouter | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` |
| `groq` | Groq | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` |
| `ollama` | local Ollama (default model `llama3.2:3b`) | – | `http://localhost:11434/v1` |
| `lmstudio` | local LM Studio | – | `http://localhost:1234/v1` |
| `openai_compatible` | any OpenAI-compatible server (vLLM, llama.cpp, LiteLLM, proxies); set `base_url` | optional (`api_key_env`) | – |
| `python:package.module:Class` | your own classifier class | – | – |

Cloud LLM providers need `model` (there is no default: model names change too often). Override the endpoint with
`base_url` and the key variable with `api_key_env`. Keys are only read from the environment:

```bash
export OPENAI_API_KEY=sk-...
python -m src.cli audit --url https://example.com/ --config config/config.yaml
```

All providers use HTTP through the standard library; no vendor SDK is installed. LLM providers receive the same
prompt and must answer with a JSON object `{"relevant": true, "confidence": 0.9, "score": 8}` (extra text around it
is tolerated).

## Fallback and costs

* `fallback: heuristic` *(default)* – if the provider is unusable (missing key) or a call fails (network, HTTP
  error, unparseable answer), the heuristic answers instead. Every fallback is logged and counted in the report;
  results show which classifier judged each link.
* `fallback: none` – a missing key stops the run; failed calls raise an error.
* Each candidate **paragraph** is one call (a 10-page site is ~200 calls). Reports show the number of calls and an
  estimated cost: `cost_per_call_usd` (Jev default 0.000025; set it for paid LLMs). Run `crawl` first (no calls)
  and limit the scope with `include`/`exclude` on large sites.

## Writing your own classifier

Any class with an `evaluate(candidate)` method works – for example a local transformers model:

```python
# my_project/judge.py
class MyClassifier:
    cost_per_call_usd = 0.0

    def __init__(self, config):                  # optional: receives the ClassifierConfig
        self.model = load_my_model(config.model)

    def evaluate(self, candidate):
        # candidate fields: source_url, source_paragraph, target_url, target_title,
        #                   target_topic (the target's H1), target_queries (SERP page 2 queries)
        p = self.model.probability(candidate.source_paragraph, candidate.target_title)
        return {"relevant": p > 0.5, "confidence": p, "score": 1 + 9 * p}
```

```yaml
classifier:
  provider: python:my_project.judge:MyClassifier
```

Return a `LinkJudgement` (`src/engines/classifiers/base.py`) or a dict with `relevant`, `confidence` and `score`.
Exceptions are turned into fallbacks (or errors with `fallback: none`).

## Adding a built-in provider

* **OpenAI-compatible service:** add a `ProviderPreset` (endpoint, key variable) in
  `src/engines/classifiers/factory.py` – no other code needed.
* **Other API:** add a `LinkClassifier` subclass in `src/engines/classifiers/` (see `llm.py`); raise `ClassifierError`
  on any failure so the fallback policy applies; test it against a fake local server like
  `tests/test_classifiers.py` does (no network needed).
