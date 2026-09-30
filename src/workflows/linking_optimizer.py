"""
Linking Optimizer Workflow.

Orchestrates the end-to-end Cascade:
1. GSC Ingestion & Page 2 opportunity filtering
2. Cluster-aware Candidate link generation
3. TypeSafe Jev System 1 high-speed qualification
4. Auxiliary AI anchor insertion and sentence rewriting
5. Link Graph validation and audit generation
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from src.engines.jev_client import JevClient
from src.engines.auxiliary_ai import AuxiliaryAIEngine, InsertionProposal
from src.engines.link_graph import LinkGraph
from src.connectors.sitemap_crawler import ParsedPage
from src.connectors.gsc_connector import GSCQueryRow


@dataclass
class LinkOptimizationResult:
    source_url: str
    target_url: str
    jev_relevance_score: float
    jev_confidence: float
    original_sentence: str
    updated_sentence: str
    anchor_text: str
    rationale: str
    cluster: str


@dataclass
class AuditReport:
    total_pages_evaluated: int
    candidate_pairs_checked: int
    links_approved: int
    pages_refused: int
    duration_seconds: float
    estimated_cost_usd: float
    results: List[LinkOptimizationResult]
    orphan_pages: List[str]


# Cluster compatibility matrix (defines which clusters may link to each other)
CLUSTER_AFFINITIES = {
    "trabalhista": {"trabalhista", "juridico_rh"},
    "juridico_rh": {"juridico_rh", "trabalhista"},
    "credito_previdencia": {"credito_previdencia", "financas_pessoais"},
    "financas_pessoais": {"financas_pessoais", "credito_previdencia", "trabalhista"},
    "dev_tech": {"dev_tech"},
    "arquivos": {"arquivos"},
}


class LinkingOptimizer:
    def __init__(
        self,
        jev_client: Optional[JevClient] = None,
        auxiliary_ai: Optional[AuxiliaryAIEngine] = None,
        min_jev_score: float = 7.0,
        min_jev_confidence: float = 0.80,
    ):
        self.jev = jev_client or JevClient()
        self.aux_ai = auxiliary_ai or AuxiliaryAIEngine()
        self.min_score = min_jev_score
        self.min_confidence = min_jev_confidence
        self.link_graph = LinkGraph()

    def detect_cluster(self, url: str) -> str:
        """Infer cluster from path."""
        u = url.lower()
        if any(k in u for k in ["rescisao", "salario", "clt", "ferias", "13-salario", "demissao", "seguro-desemprego", "horas-extras"]):
            return "trabalhista"
        if any(k in u for k in ["contrato", "termos", "recibo", "declaracao", "procuracao", "negocios"]):
            return "juridico_rh"
        if any(k in u for k in ["consignado", "aposentadoria", "inss"]):
            return "credito_previdencia"
        if any(k in u for k in ["pix", "json", "cpf", "cnpj", "uuid", "jwt", "base64", "desenvolvedores"]):
            return "dev_tech"
        if any(k in u for k in ["pdf", "epub", "mobi", "webp", "audio", "arquivos"]):
            return "arquivos"
        return "geral"

    def run_optimization(
        self,
        pages: List[ParsedPage],
        gsc_data: Optional[List[GSCQueryRow]] = None,
    ) -> AuditReport:
        start_time = time.time()

        # 1. Initialize link graph and cluster mappings
        page_clusters: Dict[str, str] = {}
        for page in pages:
            cluster = self.detect_cluster(page.url)
            page_clusters[page.url] = cluster

            role = "support"
            if "/pricing" in page.url or "/simulador" in page.url or "calculadora" in page.url or "gerador" in page.url:
                role = "tool_money"
            elif "/guias/" in page.url:
                role = "pillar"

            self.link_graph.add_page(page.url, role=role, topic_cluster=cluster)
            for target in page.existing_internal_links:
                self.link_graph.add_link(page.url, target)

        approved_links: List[LinkOptimizationResult] = []
        candidate_count = 0
        refused_pages_set: Set[str] = set(p.url for p in pages)

        # 2. Evaluate candidate pairs within cluster affinity
        for source in pages:
            source_cluster = page_clusters[source.url]
            allowed_targets = CLUSTER_AFFINITIES.get(source_cluster, {source_cluster})

            for target in pages:
                if source.url == target.url:
                    continue

                target_cluster = page_clusters[target.url]
                if target_cluster not in allowed_targets:
                    # Enforce topic boundary (Step 2 of playbook)
                    continue

                # Skip if link already exists
                if self.link_graph.has_link(source.url, target.url):
                    continue

                # Validate graph topology rules
                valid_topology, _ = self.link_graph.validate_link_rules(source.url, target.url)
                if not valid_topology:
                    continue

                # Evaluate paragraphs in source page
                for p_idx, paragraph in enumerate(source.paragraphs):
                    candidate_count += 1

                    # Fast Jev System 1 check
                    jev_res = self.jev.evaluate_link_candidate(
                        source_url=source.url,
                        source_paragraph=paragraph,
                        target_url=target.url,
                        target_title=target.title,
                        target_topic=target.h1 or target.title,
                    )

                    res_data = jev_res.get("results", {})
                    legit_check = res_data.get("has_legitimate_contextual_reason", {})
                    score_check = res_data.get("relevance_score", {})

                    is_legit = legit_check.get("value", False)
                    confidence = legit_check.get("confidence", 0.0)
                    score = score_check.get("score", 0.0)

                    # Decision Gate
                    if is_legit and confidence >= self.min_confidence and score >= self.min_score:
                        # Step 3: Auxiliary AI crafts the sentence rewriting & anchor
                        proposal = self.aux_ai.craft_link_insertion(
                            source_paragraph=paragraph,
                            target_url=target.url,
                            target_title=target.title,
                            target_topic=target.h1 or target.title,
                        )

                        if not proposal:
                            # Refuse link if no clean, non-stopword anchor is available
                            continue

                        approved_links.append(
                            LinkOptimizationResult(
                                source_url=source.url,
                                target_url=target.url,
                                jev_relevance_score=score,
                                jev_confidence=confidence,
                                original_sentence=proposal.original_sentence,
                                updated_sentence=proposal.updated_sentence,
                                anchor_text=proposal.anchor_text,
                                rationale=proposal.rationale,
                                cluster=source_cluster,
                            )
                        )

                        self.link_graph.add_link(source.url, target.url, proposal.anchor_text)
                        refused_pages_set.discard(target.url)
                        break  # Only one link per paragraph

        duration = time.time() - start_time
        estimated_cost = candidate_count * 0.000025

        return AuditReport(
            total_pages_evaluated=len(pages),
            candidate_pairs_checked=candidate_count,
            links_approved=len(approved_links),
            pages_refused=len(refused_pages_set),
            duration_seconds=round(duration, 2),
            estimated_cost_usd=round(estimated_cost, 4),
            results=approved_links,
            orphan_pages=self.link_graph.find_orphan_pages(),
        )
