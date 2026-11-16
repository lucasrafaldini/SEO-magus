"""
Build the configured link classifier.

Config (section `classifier:` of a site config; every key optional):

    classifier:
      provider: auto         # auto | jev | heuristic | openai | anthropic | gemini | openrouter |
                             # groq | ollama | lmstudio | openai_compatible | python:module:Class
      model: ""              # model name (required by LLM providers without a default)
      base_url: ""           # endpoint override (proxies, self-hosted / local servers)
      api_key_env: ""        # environment variable holding the API key (default per provider)
      timeout: 30            # seconds per request
      fallback: heuristic    # heuristic | none - what to do when the provider is unusable
      cost_per_call_usd: 0   # for cost estimates (default per provider)
      temperature: 0

"auto" (the default) uses TypeSafe Jev when TYPESAFE_API_KEY is set and the
offline heuristic otherwise. API keys are only ever read from environment
variables, never from config files.
"""

import importlib
import inspect
import os
from dataclasses import dataclass, fields
from typing import Any, Mapping, Optional

from src.engines.classifiers.base import ClassifierError, LinkCandidate, LinkClassifier, LinkJudgement
from src.engines.classifiers.heuristic import HeuristicClassifier
from src.log import get_logger

logger = get_logger(__name__)

FALLBACK_POLICIES = ("heuristic", "none")
PLUGIN_PREFIX = "python:"


@dataclass(frozen=True)
class ProviderPreset:
    kind: str                    # jev | openai_compatible | anthropic
    base_url: str = ""
    api_key_env: str = ""
    key_required: bool = True
    model: str = ""              # default model; empty = the user must choose one
    cost_per_call_usd: float = 0.0


PRESETS = {
    "jev": ProviderPreset("jev", "https://api.typesafe.ai/v1/systemone", "TYPESAFE_API_KEY", cost_per_call_usd=0.000025),
    "openai": ProviderPreset("openai_compatible", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    "anthropic": ProviderPreset("anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY"),
    "gemini": ProviderPreset("openai_compatible", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "openrouter": ProviderPreset("openai_compatible", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "groq": ProviderPreset("openai_compatible", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "ollama": ProviderPreset("openai_compatible", "http://localhost:11434/v1", key_required=False, model="llama3.2:3b"),
    "lmstudio": ProviderPreset("openai_compatible", "http://localhost:1234/v1", key_required=False),
    "openai_compatible": ProviderPreset("openai_compatible", key_required=False),
}
PROVIDERS = ("auto", "heuristic", *PRESETS)


@dataclass(frozen=True)
class ClassifierConfig:
    provider: str = "auto"
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    timeout: float = 30.0
    fallback: str = "heuristic"
    cost_per_call_usd: Optional[float] = None
    temperature: float = 0.0

    def __post_init__(self):
        provider = str(self.provider).strip()
        object.__setattr__(self, "provider", provider if provider.startswith(PLUGIN_PREFIX) else provider.lower())
        if not (self.provider in PROVIDERS or self.provider.startswith(PLUGIN_PREFIX)):
            raise ValueError(
                f"classifier.provider {self.provider!r} is unknown; use one of {list(PROVIDERS)} "
                f"or '{PLUGIN_PREFIX}package.module:ClassName'"
            )
        if self.fallback not in FALLBACK_POLICIES:
            raise ValueError(f"classifier.fallback must be one of {list(FALLBACK_POLICIES)}, got {self.fallback!r}")
        if not self.timeout > 0:
            raise ValueError(f"classifier.timeout must be positive, got {self.timeout}")

    @classmethod
    def from_config(cls, config: Optional[Mapping[str, Any]]) -> "ClassifierConfig":
        section = (config or {}).get("classifier") or {}
        if not isinstance(section, Mapping):
            raise ValueError("config 'classifier' must be a mapping")
        names = [f.name for f in fields(cls)]
        unknown = sorted(set(section) - set(names))
        if unknown:
            raise ValueError(f"Unknown classifier settings {unknown}; expected some of {names}")
        if "api_key" in section:  # defensive: never accept secrets in config files
            raise ValueError("Do not put API keys in config files; set classifier.api_key_env instead")
        return cls(**section)


class FallbackClassifier(LinkClassifier):
    """Use `primary`; when it raises ClassifierError, answer with `backup` and count it."""

    WARN_FIRST = 3

    def __init__(self, primary: LinkClassifier, backup: LinkClassifier):
        self.primary, self.backup = primary, backup
        self.name = primary.name
        self.cost_per_call_usd = primary.cost_per_call_usd
        self.fallbacks = 0

    def describe(self) -> str:
        return f"{self.primary.describe()}, falling back to {self.backup.name} on errors"

    def evaluate(self, candidate: LinkCandidate) -> LinkJudgement:
        try:
            return self.primary.evaluate(candidate)
        except ClassifierError as exc:
            self.fallbacks += 1
            log = logger.warning if self.fallbacks <= self.WARN_FIRST else logger.debug
            log("Classifier %s failed (%s); using %s for this candidate%s", self.primary.name, exc, self.backup.name,
                " (further failures logged at DEBUG)" if self.fallbacks == self.WARN_FIRST else "")
            judgement = self.backup.evaluate(candidate)
            return LinkJudgement(judgement.relevant, judgement.confidence, judgement.score,
                                 f"{self.backup.name} (fallback)", judgement.detail)


class _PluginAdapter(LinkClassifier):
    """Wraps a user classifier; accepts LinkJudgement or a dict result."""

    def __init__(self, plugin, name: str):
        self.plugin, self.name = plugin, name
        self.cost_per_call_usd = float(getattr(plugin, "cost_per_call_usd", 0.0))

    def describe(self) -> str:
        return f"plugin {self.name}"

    def evaluate(self, candidate: LinkCandidate) -> LinkJudgement:
        try:
            result = self.plugin.evaluate(candidate)
        except ClassifierError:
            raise
        except Exception as exc:  # plugin bugs must not crash the run silently
            raise ClassifierError(f"plugin {self.name} raised {exc!r}") from exc
        if isinstance(result, LinkJudgement):
            return result if result.provider else LinkJudgement(result.relevant, result.confidence, result.score, self.name)
        if isinstance(result, Mapping):
            try:
                return LinkJudgement(bool(result["relevant"]), float(result["confidence"]), float(result["score"]), self.name)
            except (KeyError, TypeError, ValueError) as exc:
                raise ClassifierError(f"plugin {self.name} returned {result!r}") from exc
        raise ClassifierError(f"plugin {self.name} returned {type(result).__name__}, expected LinkJudgement or dict")


def _load_plugin(spec: str, config: ClassifierConfig) -> LinkClassifier:
    target = spec[len(PLUGIN_PREFIX):]
    module_name, _, class_name = target.partition(":")
    if not module_name or not class_name:
        raise ValueError(f"classifier.provider {spec!r} must look like '{PLUGIN_PREFIX}package.module:ClassName'")
    try:
        cls = getattr(importlib.import_module(module_name), class_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(f"Cannot load classifier plugin {target!r}: {exc}") from exc
    accepts_config = len(inspect.signature(cls).parameters) > 0
    plugin = cls(config) if accepts_config else cls()
    if not callable(getattr(plugin, "evaluate", None)):
        raise ValueError(f"Classifier plugin {target!r} has no evaluate(candidate) method")
    return _PluginAdapter(plugin, class_name)


def _unusable(config: ClassifierConfig, reason: str) -> LinkClassifier:
    if config.fallback == "none":
        raise ValueError(f"classifier '{config.provider}' is unusable: {reason} (fallback: none)")
    logger.warning("Classifier '%s' is unusable (%s): using the offline heuristic classifier", config.provider, reason)
    return HeuristicClassifier()


def build_classifier(config: Optional[ClassifierConfig] = None, environ: Optional[Mapping[str, str]] = None) -> LinkClassifier:
    """Instantiate the configured classifier (wrapped with the fallback policy)."""
    config = config or ClassifierConfig()
    environ = os.environ if environ is None else environ
    provider = config.provider

    if provider == "auto":
        if environ.get(config.api_key_env or PRESETS["jev"].api_key_env):
            provider = "jev"
        else:
            logger.info("Classifier: offline heuristic (provider 'auto' and TYPESAFE_API_KEY is not set)")
            return HeuristicClassifier()
    if provider == "heuristic":
        logger.info("Classifier: offline heuristic")
        return HeuristicClassifier()

    if provider.startswith(PLUGIN_PREFIX):
        primary = _load_plugin(provider, config)
    else:
        preset = PRESETS[provider]
        key_env = config.api_key_env or preset.api_key_env
        api_key = environ.get(key_env) if key_env else None
        if preset.key_required and not api_key:
            return _unusable(config, f"environment variable {key_env} is not set")
        cost = preset.cost_per_call_usd if config.cost_per_call_usd is None else config.cost_per_call_usd
        base_url = config.base_url or preset.base_url
        if preset.kind == "jev":
            from src.engines.classifiers.jev import JevClassifier
            primary = JevClassifier(api_key=api_key, base_url=base_url, timeout=config.timeout, cost_per_call_usd=cost)
        else:
            from src.engines.classifiers.llm import AnthropicClassifier, OpenAICompatibleClassifier
            cls = AnthropicClassifier if preset.kind == "anthropic" else OpenAICompatibleClassifier
            primary = cls(provider, base_url, config.model or preset.model, api_key,
                          timeout=config.timeout, temperature=config.temperature, cost_per_call_usd=cost)

    classifier = primary if config.fallback == "none" else FallbackClassifier(primary, HeuristicClassifier())
    logger.info("Classifier: %s", classifier.describe())
    return classifier
