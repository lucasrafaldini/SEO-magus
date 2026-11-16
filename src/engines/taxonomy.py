"""
Site Taxonomy.

Single source of truth for page roles (pillar / money / support) and topic
clusters. Everything site-specific lives in the `taxonomy:` section of a
site's config.yaml; the engines themselves make no assumptions about any site:

    taxonomy:
      pillars:                      # exact pages
        - "/guides/email-marketing-mastery"
      money_pages:                  # exact pages
        - "/pricing"
      clusters:                     # cluster -> URL substrings, first match wins
        email: ["/guides/email", "/blog/welcome"]
        sales: ["/pricing"]
      cluster_affinities:           # source cluster -> other clusters it may link to
        email: [sales]

Role entries are URL paths ("/pricing") or absolute URLs
("https://example.com/pricing"). A page matches a role entry when its path is
identical (ignoring a trailing slash) and, for absolute entries, its host is
identical too; matching is exact, so "/pricing" does not match "/pricing-faq".
Pages not listed are support pages.

Cluster patterns are case-insensitive substrings of the page URL, checked in
config order. Pages matching no pattern belong to the "general" cluster.
A page may always link within its own cluster, plus to the clusters listed in
cluster_affinities for it. Without any clusters configured every page is in
"general", i.e. there is no topic boundary.
"""

from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

ROLE_PILLAR = "pillar"
ROLE_MONEY = "money"
ROLE_SUPPORT = "support"
ROLES = (ROLE_PILLAR, ROLE_MONEY, ROLE_SUPPORT)

DEFAULT_CLUSTER = "general"

TAXONOMY_KEYS = ("pillars", "money_pages", "clusters", "cluster_affinities")

_Key = Tuple[Optional[str], str]  # (host or None for path-only entries, normalized path)


def _normalize_path(path: str) -> str:
    path = path if path.startswith("/") else "/" + path
    return path.rstrip("/") or "/"


def _entry_key(entry: str) -> _Key:
    parsed = urlparse(entry.strip())
    if parsed.netloc:
        return parsed.netloc.lower(), _normalize_path(parsed.path)
    return None, _normalize_path(parsed.path)


def _matches(key: _Key, url: str) -> bool:
    host, path = key
    parsed = urlparse(url)
    if _normalize_path(parsed.path) != path:
        return False
    return host is None or parsed.netloc.lower() == host


def url_key(url: str) -> Tuple[str, str]:
    """Comparable form of a page URL: (host, path without trailing slash)."""
    parsed = urlparse(url.strip())
    return parsed.netloc.lower(), _normalize_path(parsed.path)


@dataclass(frozen=True)
class SiteTaxonomy:
    """Page roles and topic clusters for one site."""

    pillars: Tuple[str, ...] = ()
    money_pages: Tuple[str, ...] = ()
    clusters: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    cluster_affinities: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "pillars", tuple(self.pillars))
        object.__setattr__(self, "money_pages", tuple(self.money_pages))
        object.__setattr__(self, "clusters", _pairs(self.clusters))
        object.__setattr__(self, "cluster_affinities", _pairs(self.cluster_affinities))

        overlap = {_entry_key(e) for e in self.pillars} & {_entry_key(e) for e in self.money_pages}
        if overlap:
            pages = sorted(path if host is None else host + path for host, path in overlap)
            raise ValueError(f"Pages cannot be both pillar and money page: {pages}")

        known = {name for name, _ in self.clusters} | {DEFAULT_CLUSTER}
        for source, targets in self.cluster_affinities:
            unknown = sorted({source, *targets} - known)
            if unknown:
                raise ValueError(f"cluster_affinities refers to undefined clusters: {unknown}")

    @classmethod
    def from_config(cls, config: Optional[Mapping[str, Any]]) -> "SiteTaxonomy":
        """Build from a parsed config dict (the `taxonomy` section may be absent)."""
        section = (config or {}).get("taxonomy") or {}
        if not isinstance(section, Mapping):
            raise ValueError("config 'taxonomy' must be a mapping")
        unknown = sorted(set(section) - set(TAXONOMY_KEYS))
        if unknown:
            raise ValueError(f"Unknown taxonomy keys {unknown}; expected some of {list(TAXONOMY_KEYS)}")
        return cls(
            pillars=_string_list(section.get("pillars"), "taxonomy.pillars"),
            money_pages=_string_list(section.get("money_pages"), "taxonomy.money_pages"),
            clusters=_string_list_mapping(section.get("clusters"), "taxonomy.clusters"),
            cluster_affinities=_string_list_mapping(section.get("cluster_affinities"), "taxonomy.cluster_affinities"),
        )

    def role_for(self, url: str) -> Optional[str]:
        """Configured role for url, or None if the taxonomy does not mention it."""
        if any(_matches(_entry_key(e), url) for e in self.pillars):
            return ROLE_PILLAR
        if any(_matches(_entry_key(e), url) for e in self.money_pages):
            return ROLE_MONEY
        return None

    def cluster_for(self, url: str) -> str:
        """First configured cluster whose pattern occurs in url, else "general"."""
        lowered = url.lower()
        for name, patterns in self.clusters:
            if any(pattern.lower() in lowered for pattern in patterns):
                return name
        return DEFAULT_CLUSTER

    def allowed_target_clusters(self, cluster: str) -> Tuple[str, ...]:
        """Clusters a page in `cluster` may link to: itself plus its affinities."""
        affinities = dict(self.cluster_affinities).get(cluster, ())
        return (cluster,) + tuple(c for c in affinities if c != cluster)

    def unmatched_entries(self, urls: Iterable[str]) -> List[str]:
        """Configured role entries and cluster patterns that match none of the given URLs."""
        urls = list(urls)
        lowered = [url.lower() for url in urls]
        unmatched = [
            entry for entry in self.pillars + self.money_pages
            if not any(_matches(_entry_key(entry), url) for url in urls)
        ]
        unmatched += [
            f"{name}: {pattern}"
            for name, patterns in self.clusters
            for pattern in patterns
            if not any(pattern.lower() in url for url in lowered)
        ]
        return unmatched


def _pairs(value) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    items = value.items() if isinstance(value, Mapping) else value
    return tuple((name, tuple(patterns)) for name, patterns in items)


def _string_list(values: Any, name: str) -> Tuple[str, ...]:
    values = values or []
    if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
        raise ValueError(f"config '{name}' must be a list of non-empty strings")
    return tuple(values)


def _string_list_mapping(values: Any, name: str) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    values = values or {}
    if not isinstance(values, Mapping):
        raise ValueError(f"config '{name}' must be a mapping of name -> list of strings")
    return tuple((str(key), _string_list(items, f"{name}.{key}")) for key, items in values.items())
