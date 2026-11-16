"""
Configuration loading for SEO-Magus.

Reads the YAML file described by config/config.example.yaml. The sections
consumed by the pipeline are:

  thresholds  -> Thresholds       (classifier gate, anchor quality, SERP page 2 window, click depth)
  taxonomy    -> SiteTaxonomy     (page roles and topic clusters)
  link_rules  -> LinkRules        (site linking policy, e.g. may money pages link to support posts)
  classifier  -> ClassifierConfig (which model judges candidate links: Jev, any LLM, local, plugin)
  crawler     -> CrawlConfig      (how sites are crawled: limits, politeness, filters)

Both are strict: unknown keys raise ValueError so a typo cannot silently
fall back to a default. Precedence everywhere is:
explicit argument / CLI flag  >  config file  >  built-in default.
"""

from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from src.connectors.crawling.crawler import CrawlConfig
from src.engines.classifiers.factory import ClassifierConfig
from src.engines.taxonomy import SiteTaxonomy
from src.log import get_logger

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path("config/config.yaml")


# Vendor-specific names used before the classifier became pluggable.
LEGACY_THRESHOLD_KEYS = {"jev_noul_min_confidence": "min_confidence", "jev_score_min": "min_score"}


@dataclass(frozen=True)
class Thresholds:
    """Decision thresholds; the defaults are the built-in values used everywhere."""

    min_confidence: float = 0.80           # min classifier confidence that a link is legitimate
    min_score: float = 7.0                 # min classifier relevance score (1-10)
    page2_min_position: float = 11.0       # SERP page 2 window (inclusive)
    page2_max_position: float = 20.0
    min_impressions: int = 50              # min GSC impressions for a page 2 opportunity
    anchor_min_words: int = 2              # min distinct topic words in an anchor ("descriptive anchors")
    max_click_depth: int = 3               # site audit: deeper pages are flagged
    slow_page_ms: int = 2000               # site audit: slower responses are flagged

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"threshold '{f.name}' must be a number, got {value!r}")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(f"min_confidence must be in [0, 1], got {self.min_confidence}")
        if not 1.0 <= self.min_score <= 10.0:
            raise ValueError(f"min_score must be in [1, 10], got {self.min_score}")
        if not 0.0 < self.page2_min_position <= self.page2_max_position:
            raise ValueError(
                f"page 2 window must satisfy 0 < page2_min_position <= page2_max_position, "
                f"got {self.page2_min_position}..{self.page2_max_position}"
            )
        for name, minimum in (("min_impressions", 0), ("anchor_min_words", 1), ("max_click_depth", 1),
                              ("slow_page_ms", 1)):
            value = getattr(self, name)
            if value < minimum or int(value) != value:
                raise ValueError(f"{name} must be an integer >= {minimum}, got {value}")

    @classmethod
    def from_config(cls, config: Optional[Mapping[str, Any]]) -> "Thresholds":
        """Build from a parsed config dict; missing keys keep their defaults."""
        section = dict((config or {}).get("thresholds") or {})
        if not isinstance((config or {}).get("thresholds") or {}, Mapping):
            raise ValueError("config 'thresholds' must be a mapping")
        for legacy, current in LEGACY_THRESHOLD_KEYS.items():
            if legacy in section:
                if current in section:
                    raise ValueError(f"thresholds: use '{current}' only (remove the legacy '{legacy}')")
                logger.warning("thresholds.%s is deprecated; rename it to thresholds.%s", legacy, current)
                section[current] = section.pop(legacy)
        names = [f.name for f in fields(cls)]
        unknown = sorted(set(section) - set(names))
        if unknown:
            raise ValueError(f"Unknown thresholds {unknown}; expected some of {names}")
        return cls(**section)

    def with_overrides(self, **overrides: Optional[float]) -> "Thresholds":
        """Copy with the given values replaced; None means "not overridden"."""
        return replace(self, **{k: v for k, v in overrides.items() if v is not None})


DEFAULT_THRESHOLDS = Thresholds()

MONEY_TO_SUPPORT_POLICIES = ("forbid", "same_cluster", "allow")


@dataclass(frozen=True)
class LinkRules:
    """
    Site linking policy.

    money_to_support: may money pages link to support posts?
      forbid        (default) never - money pages should funnel toward conversion
      same_cluster  only within the same topic cluster (e.g. tool sites whose
                    calculators naturally lead to related helper tools)
      allow         always
    """

    money_to_support: str = "forbid"

    def __post_init__(self):
        if self.money_to_support not in MONEY_TO_SUPPORT_POLICIES:
            raise ValueError(
                f"link_rules.money_to_support must be one of {list(MONEY_TO_SUPPORT_POLICIES)}, "
                f"got {self.money_to_support!r}"
            )

    @classmethod
    def from_config(cls, config: Optional[Mapping[str, Any]]) -> "LinkRules":
        section = (config or {}).get("link_rules") or {}
        if not isinstance(section, Mapping):
            raise ValueError("config 'link_rules' must be a mapping")
        names = [f.name for f in fields(cls)]
        unknown = sorted(set(section) - set(names))
        if unknown:
            raise ValueError(f"Unknown link_rules {unknown}; expected some of {names}")
        return cls(**section)


KNOWN_SECTIONS = ("site", "thresholds", "taxonomy", "link_rules", "classifier", "crawler")
LEGACY_SECTIONS = {
    "model_providers": "configure the link classifier in the 'classifier' section",
    "api_keys": "API keys are read from environment variables only (classifier.api_key_env)",
}


@dataclass(frozen=True)
class SiteConfig:
    """Everything the pipeline needs to know about one site."""

    thresholds: Thresholds = field(default_factory=Thresholds)
    taxonomy: SiteTaxonomy = field(default_factory=SiteTaxonomy)
    link_rules: LinkRules = field(default_factory=LinkRules)
    classifier: ClassifierConfig = field(default_factory=ClassifierConfig)
    crawler: CrawlConfig = field(default_factory=CrawlConfig)

    @classmethod
    def from_config(cls, config: Optional[Mapping[str, Any]]) -> "SiteConfig":
        for section in sorted(set(config or {}) - set(KNOWN_SECTIONS)):
            if section in LEGACY_SECTIONS:
                logger.warning("Config section '%s' is no longer used: %s", section, LEGACY_SECTIONS[section])
            else:
                logger.warning("Unknown config section '%s' is ignored (known: %s)", section, ", ".join(KNOWN_SECTIONS))
        return cls(
            thresholds=Thresholds.from_config(config),
            taxonomy=SiteTaxonomy.from_config(config),
            link_rules=LinkRules.from_config(config),
            classifier=ClassifierConfig.from_config(config),
            crawler=CrawlConfig.from_config(config),
        )


def load_config(path: Union[str, Path] = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """Parse a YAML config file into a dict. An empty file yields {}."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - pyyaml is a core requirement
        raise ImportError("Loading config files requires pyyaml: pip install -r requirements.txt") from exc

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config/config.example.yaml to {DEFAULT_CONFIG_PATH} and edit it."
        )
    logger.debug("Reading config file %s", path)
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping at the top level.")
    return data


def load_site_config(path: Union[str, Path] = DEFAULT_CONFIG_PATH) -> SiteConfig:
    """Load the thresholds and taxonomy sections of a config file."""
    site_config = SiteConfig.from_config(load_config(path))
    taxonomy = site_config.taxonomy
    logger.info(
        "Site config %s: %s | %d pillars, %d money pages, %d clusters | money->support: %s | classifier: %s",
        path, site_config.thresholds, len(taxonomy.pillars), len(taxonomy.money_pages),
        len(taxonomy.clusters), site_config.link_rules.money_to_support, site_config.classifier.provider,
    )
    return site_config


def load_taxonomy(path: Union[str, Path] = DEFAULT_CONFIG_PATH) -> SiteTaxonomy:
    """Load only the `taxonomy` section (page roles and clusters)."""
    return SiteTaxonomy.from_config(load_config(path))
