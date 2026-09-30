"""
Internal Link Graph Engine.

Maintains the site-wide directed link graph.
Calculates in-degree, out-degree, internal PageRank, identifies orphan pages,
and validates topological linking rules (Support -> Pillar, Pillar -> Money, etc.).
Has a pure-Python fallback if networkx is not installed.
"""

from typing import Dict, List, Set, Tuple

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


class LinkGraph:
    def __init__(self):
        self.nodes: Set[str] = set()
        self.edges: Dict[str, Set[str]] = {}  # source -> set of targets
        self.in_edges: Dict[str, Set[str]] = {}  # target -> set of sources
        self.page_metadata: Dict[str, Dict] = {}
        if HAS_NETWORKX:
            self.graph = nx.DiGraph()

    def add_page(self, url: str, role: str = "support", topic_cluster: str = "general"):
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
        self.add_page(source)
        self.add_page(target)
        self.edges[source].add(target)
        self.in_edges[target].add(source)
        if HAS_NETWORKX:
            self.graph.add_edge(source, target, anchor=anchor)

    def has_link(self, source: str, target: str) -> bool:
        """Check if link already exists."""
        return target in self.edges.get(source, set())

    def find_orphan_pages(self) -> List[str]:
        """Return pages with 0 inbound internal links."""
        return [node for node in self.nodes if len(self.in_edges.get(node, set())) == 0]

    def compute_pagerank(self, alpha: float = 0.85, max_iter: int = 50) -> Dict[str, float]:
        """Compute internal PageRank equity distribution across all pages."""
        if not self.nodes:
            return {}
        if HAS_NETWORKX:
            try:
                return nx.pagerank(self.graph, alpha=alpha)
            except Exception:
                pass

        # Pure Python standard PageRank implementation
        n = len(self.nodes)
        node_list = list(self.nodes)
        rank = {node: 1.0 / n for node in node_list}

        for _ in range(max_iter):
            new_rank = {node: (1.0 - alpha) / n for node in node_list}
            for src in node_list:
                out_links = self.edges.get(src, set())
                if out_links:
                    share = (alpha * rank[src]) / len(out_links)
                    for tgt in out_links:
                        new_rank[tgt] += share
                else:
                    # Dangling node distributed equally
                    share = (alpha * rank[src]) / n
                    for tgt in node_list:
                        new_rank[tgt] += share
            rank = new_rank

        return rank

    def validate_link_rules(self, source: str, target: str) -> Tuple[bool, str]:
        """
        Validates connection against the 8-step playbook taxonomy:
        - support -> pillar (Allowed)
        - support -> money (Allowed)
        - support <-> support (Allowed if same/related cluster)
        - pillar -> money (Allowed)
        - pillar <-> pillar (Allowed)
        - money -> support (Caution: should typically funnel toward conversion)
        """
        source_meta = self.page_metadata.get(source, {"role": "support", "cluster": "general"})
        target_meta = self.page_metadata.get(target, {"role": "support", "cluster": "general"})

        s_role, t_role = source_meta.get("role"), target_meta.get("role")

        if s_role == "money" and t_role == "support":
            return False, "Commercial money pages should not leak equity to generic support posts unless directly required."

        return True, "Valid linking topology."
