"""
Internal Link Graph Engine.

Maintains the site-wide directed link graph.
Calculates in-degree, out-degree, internal PageRank, CheiRank (hub centrality),
pillar-depth-weighted PageRank, identifies orphan pages, and validates
topological linking rules (Support -> Pillar, Pillar -> Money, etc.).
Has a pure-Python fallback if networkx is not installed.

All ranking methods share one contract:
  * parameters alpha (damping), max_iter and tol mean the same thing on the
    networkx and pure-Python backends: iterate at most max_iter times and stop
    once the L1 change between iterations is below N * tol (networkx's rule);
  * scores sum to 1 and pages with no outbound links spread their rank uniformly;
  * if the iteration does not converge, a ConvergenceWarning is emitted and the
    last iterate is returned.
"""

import warnings
from collections import deque
from typing import Dict, List, Set, Tuple

from src.engines.taxonomy import DEFAULT_CLUSTER, ROLE_MONEY, ROLE_PILLAR, ROLE_SUPPORT, SiteTaxonomy
from src.log import get_logger

logger = get_logger(__name__)
_warned_backend_fallback = False

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

DEFAULT_ALPHA = 0.85
DEFAULT_MAX_ITER = 100
DEFAULT_TOL = 1.0e-6
DEFAULT_DEPTH_DECAY = 0.85


class ConvergenceWarning(RuntimeWarning):
    """A ranking power iteration hit max_iter before reaching tol."""


class NoPillarsWarning(UserWarning):
    """Depth-weighted ranking was requested but no page has the pillar role."""


class TaxonomyWarning(UserWarning):
    """Configured taxonomy entries do not match any page in the graph."""


class LinkGraph:
    def __init__(self):
        self.nodes: Set[str] = set()
        self.edges: Dict[str, Set[str]] = {}  # source -> set of targets
        self.in_edges: Dict[str, Set[str]] = {}  # target -> set of sources
        self.page_metadata: Dict[str, Dict] = {}
        if HAS_NETWORKX:
            self.graph = nx.DiGraph()

    def add_page(self, url: str, role: str = ROLE_SUPPORT, topic_cluster: str = DEFAULT_CLUSTER):
        """Add or update a page node with its role and cluster."""
        self.nodes.add(url)
        self.edges.setdefault(url, set())
        self.in_edges.setdefault(url, set())
        self.page_metadata[url] = {"role": role, "cluster": topic_cluster}
        if HAS_NETWORKX:
            self.graph.add_node(url, role=role, cluster=topic_cluster)

    def add_link(self, source: str, target: str, anchor: str = ""):
        """Add a directed internal link from source to target."""
        if source == target:
            return  # No self links
        # Only register unseen endpoints: re-calling add_page() would reset an
        # existing page's role/cluster metadata (e.g. demote a pillar to support).
        if source not in self.nodes:
            self.add_page(source)
        if target not in self.nodes:
            self.add_page(target)
        self.edges[source].add(target)
        self.in_edges[target].add(source)
        if HAS_NETWORKX:
            self.graph.add_edge(source, target, anchor=anchor)

    def copy(self) -> "LinkGraph":
        """Independent copy (pages, links, metadata)."""
        clone = LinkGraph()
        clone.nodes = set(self.nodes)
        clone.edges = {url: set(targets) for url, targets in self.edges.items()}
        clone.in_edges = {url: set(sources) for url, sources in self.in_edges.items()}
        clone.page_metadata = {url: dict(meta) for url, meta in self.page_metadata.items()}
        if HAS_NETWORKX:
            clone.graph = self.graph.copy()
        return clone

    def has_link(self, source: str, target: str) -> bool:
        """Check if link already exists."""
        return target in self.edges.get(source, set())

    def find_orphan_pages(self) -> List[str]:
        """Return pages with 0 inbound internal links."""
        return [node for node in self.nodes if len(self.in_edges.get(node, set())) == 0]

    def apply_taxonomy(self, taxonomy: SiteTaxonomy) -> List[str]:
        """
        Apply a site taxonomy to every page in the graph:
          * pages designated as pillar / money page get that role (config wins
            over whatever role the page was added with; other roles are kept);
          * if the taxonomy defines clusters, every page gets its configured
            cluster ("general" when no pattern matches).

        Returns the configured entries that match no page and emits a
        TaxonomyWarning for them, so typos or stale config don't silently
        leave a site without pillars or with empty clusters.
        """
        for url in self.nodes:
            updates = {}
            role = taxonomy.role_for(url)
            if role is not None:
                updates["role"] = role
            if taxonomy.has_clusters:
                updates["cluster"] = taxonomy.cluster_for(url)
            self.page_metadata[url].update(updates)
            if HAS_NETWORKX:
                self.graph.nodes[url].update(updates)

        unmatched = taxonomy.unmatched_entries(self.nodes)
        logger.info(
            "Taxonomy applied to %d pages: %d pillars, %d money pages, %d clusters configured, %d unmatched entries",
            len(self.nodes), sum(1 for m in self.page_metadata.values() if m["role"] == ROLE_PILLAR),
            sum(1 for m in self.page_metadata.values() if m["role"] == ROLE_MONEY), len(taxonomy.clusters), len(unmatched),
        )
        if unmatched:
            warnings.warn(
                f"Taxonomy entries match no page in the link graph: {unmatched}",
                TaxonomyWarning,
                stacklevel=2,
            )
        return unmatched

    # ------------------------------------------------------------------ ranking

    def compute_pagerank(
        self,
        alpha: float = DEFAULT_ALPHA,
        max_iter: int = DEFAULT_MAX_ITER,
        tol: float = DEFAULT_TOL,
    ) -> Dict[str, float]:
        """
        Compute internal PageRank equity distribution across all pages.

            PR(v) = (1 - alpha) / N
                    + alpha * sum_{u -> v} PR(u) / |out(u)|
                    + alpha * sum_{u : out(u) is empty} PR(u) / N
        """
        return self._rank(reverse=False, alpha=alpha, max_iter=max_iter, tol=tol)

    def compute_cheirank(
        self,
        alpha: float = DEFAULT_ALPHA,
        max_iter: int = DEFAULT_MAX_ITER,
        tol: float = DEFAULT_TOL,
    ) -> Dict[str, float]:
        """
        Compute CheiRank: PageRank on the reversed link graph.

        Where PageRank rewards pages that *receive* links from important pages,
        CheiRank rewards pages that *send* links to pages that are otherwise
        poorly linked, i.e. outgoing-link hubs. With N pages and damping alpha:

            CR(v) = (1 - alpha) / N
                    + alpha * sum_{w in out(v)} CR(w) / |in(w)|
                    + alpha * sum_{w : in(w) is empty} CR(w) / N

        Pages with no inbound links (orphans) are the dangling nodes of the
        reversed graph; their mass is redistributed uniformly, exactly as
        compute_pagerank() does for pages with no outbound links.
        Reference: Chepelianskii (2010), Zhirov, Zhirov & Shepelyansky (2010),
        "Two-dimensional ranking of Wikipedia articles".
        """
        return self._rank(reverse=True, alpha=alpha, max_iter=max_iter, tol=tol)

    def compute_pillar_depths(self) -> Dict[str, int]:
        """
        Click depth of every page from its nearest pillar page.

        Multi-source BFS along link direction starting from all pages whose
        role is "pillar": pillars have depth 0, pages they link to depth 1, etc.
        Pages not reachable from any pillar are omitted.
        """
        depths: Dict[str, int] = {
            url: 0 for url in self.nodes if self.page_metadata.get(url, {}).get("role") == ROLE_PILLAR
        }
        queue = deque(depths)
        while queue:
            current = queue.popleft()
            for target in self.edges.get(current, set()):
                if target not in depths:
                    depths[target] = depths[current] + 1
                    queue.append(target)
        return depths

    def compute_weighted_pagerank(
        self,
        depth_decay: float = DEFAULT_DEPTH_DECAY,
        alpha: float = DEFAULT_ALPHA,
        max_iter: int = DEFAULT_MAX_ITER,
        tol: float = DEFAULT_TOL,
    ) -> Dict[str, float]:
        """
        PageRank in which link equity is discounted by click depth from pillars.

        Let d(u) be the click depth of page u from the nearest pillar
        (see compute_pillar_depths()). Pages no pillar can reach get
        d(u) = D + 1, where D is the deepest reachable depth: they are treated
        as the least integrated pages, but their links (typically
        support -> pillar) still count. With delta = depth_decay, each page
        passes link equity with its own damping factor

            alpha_u = alpha * delta ** d(u)

        and the withheld share (alpha - alpha_u) is returned to the uniform
        teleport, so total equity is conserved:

            x(v) = sum_{u -> v} alpha_u * x(u) / |out(u)|
                   + (1 / N) * sum_u (1 - alpha_u * [out(u) non-empty]) * x(u)

        Properties:
          * Scores sum to 1 and the solution is unique (column-stochastic
            Google matrix with a strictly positive teleport term).
          * depth_decay = 1 reproduces standard PageRank exactly.
          * depth_decay = 0 means only pillar pages pass link equity.
          * The link equity a page receives (its score minus the teleport
            baseline) falls as depth_decay falls. Total scores need not:
            withheld equity is redistributed to every page via teleport.

        If no page has the pillar role, depth is undefined: a NoPillarsWarning
        is emitted and the result of compute_pagerank() is returned. Designate
        pillars with add_page(role="pillar") or apply_taxonomy().
        """
        _validate_unit_interval("depth_decay", depth_decay)
        _validate_ranking_params(alpha, max_iter, tol)
        if not self.nodes:
            return {}

        depths = self.compute_pillar_depths()
        if not depths:
            logger.info("Weighted PageRank requested without pillar pages: falling back to standard PageRank")
            warnings.warn(
                "No pillar pages designated; returning standard PageRank. "
                "Set role='pillar' on pages or configure taxonomy.pillars.",
                NoPillarsWarning,
                stacklevel=2,
            )
            return self.compute_pagerank(alpha=alpha, max_iter=max_iter, tol=tol)

        unreachable_depth = max(depths.values()) + 1
        damping = {
            node: alpha * depth_decay ** depths.get(node, unreachable_depth)
            for node in self.nodes
        }
        return self._power_iteration(self.edges, damping, max_iter, tol)

    def _rank(self, reverse: bool, alpha: float, max_iter: int, tol: float) -> Dict[str, float]:
        """Uniform-damping PageRank on the graph (or its reverse), networkx first."""
        _validate_ranking_params(alpha, max_iter, tol)
        if not self.nodes:
            return {}
        name = "CheiRank" if reverse else "PageRank"
        if HAS_NETWORKX:
            graph = self.graph.reverse(copy=False) if reverse else self.graph
            try:
                scores = nx.pagerank(graph, alpha=alpha, max_iter=max_iter, tol=tol)
                logger.debug("%s of %d pages computed with networkx", name, len(self.nodes))
                return scores
            except ImportError as exc:
                # networkx's pagerank needs scipy/numpy: warn once, then use the fallback.
                global _warned_backend_fallback
                if not _warned_backend_fallback:
                    logger.warning("networkx ranking backend unavailable (%s); using the pure-Python backend", exc)
                    _warned_backend_fallback = True
            except nx.PowerIterationFailedConvergence:
                # The fallback returns the last iterate with a ConvergenceWarning.
                logger.debug("networkx %s did not converge in %d iterations; retrying in pure Python", name, max_iter)

        adjacency = self.in_edges if reverse else self.edges
        return self._power_iteration(adjacency, {node: alpha for node in self.nodes}, max_iter, tol)

    def _power_iteration(
        self,
        adjacency: Dict[str, Set[str]],
        damping: Dict[str, float],
        max_iter: int,
        tol: float,
    ) -> Dict[str, float]:
        """
        Power iteration for PageRank with per-node damping factors.

        Page u forwards damping[u] of its rank evenly over adjacency[u]; the
        remainder (or all of it, for dangling pages) is spread uniformly over
        all pages. With a constant damping this is standard PageRank.
        Stops once the L1 change drops below N * tol; warns if max_iter is hit first.
        """
        node_list = list(self.nodes)
        n = len(node_list)
        rank = {node: 1.0 / n for node in node_list}

        for iteration in range(1, max_iter + 1):
            new_rank = {node: 0.0 for node in node_list}
            teleport = 0.0
            for src in node_list:
                out_links = adjacency.get(src, set())
                if out_links:
                    passed = damping[src] * rank[src]
                    share = passed / len(out_links)
                    for tgt in out_links:
                        new_rank[tgt] += share
                    teleport += rank[src] - passed
                else:
                    # Dangling node distributed equally
                    teleport += rank[src]
            teleport /= n
            for node in node_list:
                new_rank[node] += teleport

            change = sum(abs(new_rank[node] - rank[node]) for node in node_list)
            rank = new_rank
            if change < n * tol:
                logger.debug("Pure-Python power iteration over %d pages converged in %d iterations", n, iteration)
                return rank

        warnings.warn(
            f"Ranking did not converge within max_iter={max_iter} (tol={tol}); "
            "returning the last iterate. Increase max_iter or tol.",
            ConvergenceWarning,
            stacklevel=3,
        )
        return rank

    # ------------------------------------------------------------ link rules

    def validate_link_rules(self, source: str, target: str, money_to_support: str = "forbid") -> Tuple[bool, str]:
        """
        Validates connection against the 8-step playbook taxonomy:
        - support -> pillar (Allowed)
        - support -> money (Allowed)
        - support <-> support (Allowed if same/related cluster)
        - pillar -> money (Allowed)
        - pillar <-> pillar (Allowed)
        - money -> support (site policy, see config.LinkRules: "forbid" (default),
          "same_cluster" or "allow"; money pages should typically funnel toward conversion)
        """
        default_meta = {"role": ROLE_SUPPORT, "cluster": DEFAULT_CLUSTER}
        source_meta = self.page_metadata.get(source, default_meta)
        target_meta = self.page_metadata.get(target, default_meta)

        s_role, t_role = source_meta.get("role"), target_meta.get("role")

        if s_role == ROLE_MONEY and t_role == ROLE_SUPPORT:
            same_cluster = source_meta.get("cluster") == target_meta.get("cluster")
            if money_to_support == "allow" or (money_to_support == "same_cluster" and same_cluster):
                return True, f"Money -> support allowed by site policy '{money_to_support}'."
            return False, "Commercial money pages should not leak equity to generic support posts unless directly required."

        return True, "Valid linking topology."


def _validate_unit_interval(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value}")


def _validate_ranking_params(alpha: float, max_iter: int, tol: float) -> None:
    """Shared parameter contract of every ranking method."""
    _validate_unit_interval("alpha", alpha)
    if isinstance(max_iter, bool) or not isinstance(max_iter, int) or max_iter < 1:
        raise ValueError(f"max_iter must be a positive integer, got {max_iter!r}")
    if not tol > 0:
        raise ValueError(f"tol must be positive, got {tol}")
