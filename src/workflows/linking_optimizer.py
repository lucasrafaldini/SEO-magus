"""
Linking Optimizer Workflow.

Orchestrates the end-to-end Cascade:
1. GSC Ingestion & Page 2 opportunity filtering (site thresholds)
2. Cluster-aware Candidate link generation (site taxonomy)
3. System 1 link classifier (TypeSafe Jev by default; any provider, see classifier config)
4. Auxiliary AI anchor insertion and sentence rewriting
5. Link Graph validation and audit generation

Search Console data steers the flow: a page with page 2 queries gets those
queries added to its topic (readers literally search for it that way), and
links that boost page 2 pages are flagged and listed first in the report.
"""

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from src.config import DEFAULT_THRESHOLDS, LinkRules, SiteConfig, Thresholds
from src.connectors.gsc_connector import GSCConnector, GSCQueryRow
from src.connectors.sitemap_crawler import ParsedPage
from src.engines.auxiliary_ai import AuxiliaryAIEngine
from src.engines.classifiers import LinkCandidate, LinkClassifier, build_classifier
from src.engines.classifiers.jev import JevClassifier
from src.engines.jev_client import JevClient
from src.engines.link_graph import LinkGraph
from src.engines.taxonomy import SiteTaxonomy, url_key
from src.log import get_logger

logger = get_logger(__name__)

@dataclass
class LinkOptimizationResult:
    source_url: str
    target_url: str
    relevance_score: float                   # classifier score, 1-10
    confidence: float                        # classifier confidence, 0-1
    original_sentence: str
    updated_sentence: str
    anchor_text: str
    rationale: str
    cluster: str
    page2_query: Optional[str] = None        # top page 2 query of the target this link boosts
    page2_impressions: int = 0
    classifier: str = ""                     # which classifier judged the link

    # Names from when the classifier was always Jev.
    @property
    def jev_relevance_score(self) -> float:
        return self.relevance_score

    @property
    def jev_confidence(self) -> float:
        return self.confidence


REASON_APPROVED = "approved"
REASON_CLUSTER_BOUNDARY = "cluster boundary"
REASON_EXISTING_LINK = "existing link"
REASON_ROLE_RULE = "role rule"
REASON_CLASSIFIER_GATE = "classifier gate"
REASON_JEV_GATE = REASON_CLASSIFIER_GATE  # backwards-compatible name
REASON_NO_ANCHOR = "no natural anchor"
REASON_UNKNOWN_PAGE = "unknown page"
REASON_SELF_LINK = "self link"
REASON_NOT_INDEXABLE = "not indexable"


@dataclass
class LinkDecision:
    """Outcome of the flow for one source -> target pair, with the deciding gate."""

    source_url: str
    target_url: str
    reason: str                                      # one of the REASON_* constants
    detail: str = ""
    result: Optional["LinkOptimizationResult"] = None  # set when approved
    paragraphs_evaluated: int = 0                    # classifier calls spent on this pair

    @property
    def approved(self) -> bool:
        return self.result is not None


@dataclass
class AuditReport:
    total_pages_evaluated: int
    candidate_pairs_checked: int                     # classifier calls made
    links_approved: int
    pages_refused: int
    duration_seconds: float
    estimated_cost_usd: float
    results: List[LinkOptimizationResult]            # page 2 boosting links first
    orphan_pages: List[str]
    page2_opportunities: List[GSCQueryRow] = field(default_factory=list)
    decisions_by_reason: Dict[str, int] = field(default_factory=dict)
    classifier: str = ""                             # description of the configured classifier
    classifier_fallbacks: int = 0                    # calls answered by the fallback classifier

    @property
    def page2_pages_boosted(self) -> Set[str]:
        return {r.target_url for r in self.results if r.page2_query}


class LinkingOptimizer:
    """
    Site-agnostic linking pipeline. Everything site-specific (page roles, topic
    clusters, cluster affinities, decision thresholds, linking policy) comes from
    SiteConfig, normally loaded from the site's config.yaml (see from_config).
    """

    def __init__(
        self,
        classifier: Optional[LinkClassifier] = None,
        auxiliary_ai: Optional[AuxiliaryAIEngine] = None,
        min_score: Optional[float] = None,
        min_confidence: Optional[float] = None,
        taxonomy: Optional[SiteTaxonomy] = None,
        thresholds: Optional[Thresholds] = None,
        link_rules: Optional[LinkRules] = None,
        *,
        jev_client: Optional[JevClient] = None,       # deprecated: pass classifier=JevClassifier(client)
        min_jev_score: Optional[float] = None,        # deprecated alias of min_score
        min_jev_confidence: Optional[float] = None,   # deprecated alias of min_confidence
    ):
        # Explicit min_* arguments override the given (or default) thresholds.
        self.thresholds = (thresholds or DEFAULT_THRESHOLDS).with_overrides(
            min_score=min_score if min_score is not None else min_jev_score,
            min_confidence=min_confidence if min_confidence is not None else min_jev_confidence,
        )
        self.taxonomy = taxonomy or SiteTaxonomy()
        self.link_rules = link_rules or LinkRules()
        if classifier is None:
            classifier = JevClassifier(client=jev_client) if jev_client is not None else build_classifier()
        self.classifier = classifier
        self.aux_ai = auxiliary_ai or AuxiliaryAIEngine(min_anchor_words=self.thresholds.anchor_min_words)
        # State of the most recent run_optimization() call (rebuilt on every run).
        self.link_graph = LinkGraph()        # crawl links + approved links
        self.baseline_graph = LinkGraph()    # crawl links only (before optimization)
        self._last_pages: Dict[str, ParsedPage] = {}
        self._last_approved: Dict[Tuple[str, str], LinkDecision] = {}
        self._page2: Dict[Tuple[str, str], List[GSCQueryRow]] = {}
        self._used_anchors: Dict[str, List[str]] = {}

    @classmethod
    def from_config(cls, site_config: SiteConfig, **kwargs) -> "LinkingOptimizer":
        """Optimizer using a site's thresholds, taxonomy, link rules and classifier; kwargs override them."""
        kwargs.setdefault("taxonomy", site_config.taxonomy)
        kwargs.setdefault("thresholds", site_config.thresholds)
        kwargs.setdefault("link_rules", site_config.link_rules)
        if kwargs.get("classifier") is None and kwargs.get("jev_client") is None:
            kwargs["classifier"] = build_classifier(site_config.classifier)
        return cls(**kwargs)

    @property
    def min_score(self) -> float:
        return self.thresholds.min_score

    @property
    def min_confidence(self) -> float:
        return self.thresholds.min_confidence

    # ------------------------------------------------------------- decisions

    def explain_link(self, source_url: str, target_url: str) -> LinkDecision:
        """
        Why the last run_optimization() approved or refused source -> target.

        Re-applies the same decision function used by the run (so explanations
        cannot drift from real decisions). Note: this re-queries the classifier
        for pairs that reach the classifier gate.
        """
        if (source_url, target_url) in self._last_approved:
            return self._last_approved[(source_url, target_url)]
        source = self._last_pages.get(source_url)
        target = self._last_pages.get(target_url)
        if source is None or target is None:
            missing = source_url if source is None else target_url
            return LinkDecision(source_url, target_url, REASON_UNKNOWN_PAGE, f"{missing} was not in the crawled pages")
        if source_url == target_url:
            return LinkDecision(source_url, target_url, REASON_SELF_LINK, "a page cannot link to itself")
        return self._decide(source, target)

    def _decide(self, source: ParsedPage, target: ParsedPage) -> LinkDecision:
        """Apply the flow's gates, in order, to one candidate source -> target pair."""
        # noindex pages and canonicalized duplicates neither receive nor carry new links:
        # edits belong on the canonical, indexable version.
        for page in (source, target):
            if not page.indexable:
                why = "noindex" if page.noindex else f"canonical is {page.canonical}"
                return LinkDecision(source.url, target.url, REASON_NOT_INDEXABLE, f"{page.url} is not indexable ({why})")
        meta = self.link_graph.page_metadata
        source_cluster, target_cluster = meta[source.url]["cluster"], meta[target.url]["cluster"]

        # Topic boundary (Step 2 of playbook)
        if target_cluster not in self.taxonomy.allowed_target_clusters(source_cluster):
            return LinkDecision(
                source.url, target.url, REASON_CLUSTER_BOUNDARY,
                f"cluster '{source_cluster}' may not link to cluster '{target_cluster}'",
            )

        if self.link_graph.has_link(source.url, target.url):
            return LinkDecision(source.url, target.url, REASON_EXISTING_LINK, "the link is already on the page")

        valid_topology, rule_message = self.link_graph.validate_link_rules(
            source.url, target.url, money_to_support=self.link_rules.money_to_support
        )
        if not valid_topology:
            return LinkDecision(
                source.url, target.url, REASON_ROLE_RULE,
                f"{meta[source.url]['role']} -> {meta[target.url]['role']}: {rule_message}",
            )

        # Classifier gate on every paragraph; among paragraphs that pass the gate
        # and contain a descriptive anchor, the best one gets the link:
        # highest score, then confidence, then most descriptive anchor, then earliest.
        # Anchors may not overlap the anchor text of an existing link on the page
        # or of a link already proposed for it in this run.
        page2_rows = self._page2.get(url_key(target.url), [])
        queries = [row.query for row in page2_rows]
        target_topic = target.h1 or target.title
        blocked = self._used_anchors.get(source.url, [])
        best_score, best_confidence, passed_gate = 0.0, 0.0, False
        best: Optional[Tuple[Tuple[float, float, int], LinkOptimizationResult]] = None

        for paragraph in source.paragraphs:
            judgement = self.classifier.evaluate(LinkCandidate(
                source_url=source.url,
                source_paragraph=paragraph,
                target_url=target.url,
                target_title=target.title,
                target_topic=target_topic,
                target_queries=tuple(queries),
            ))
            score, confidence = judgement.score, judgement.confidence
            best_score, best_confidence = max(best_score, score), max(best_confidence, confidence)

            if not (judgement.relevant and confidence >= self.min_confidence and score >= self.min_score):
                continue
            passed_gate = True

            # Step 3: Auxiliary AI crafts the sentence rewriting & anchor
            proposal = self.aux_ai.craft_link_insertion(
                source_paragraph=paragraph,
                target_url=target.url,
                target_title=target.title,
                target_topic=target_topic,
                target_queries=queries,
                blocked_phrases=blocked,
            )
            if not proposal:
                continue  # no descriptive anchor in this paragraph

            key = (score, confidence, len(proposal.anchor_text))
            if best is None or key > best[0]:
                best = (key, LinkOptimizationResult(
                    source_url=source.url,
                    target_url=target.url,
                    relevance_score=score,
                    confidence=confidence,
                    original_sentence=proposal.original_sentence,
                    updated_sentence=proposal.updated_sentence,
                    anchor_text=proposal.anchor_text,
                    rationale=proposal.rationale,
                    cluster=source_cluster,
                    page2_query=page2_rows[0].query if page2_rows else None,
                    page2_impressions=page2_rows[0].impressions if page2_rows else 0,
                    classifier=judgement.provider,
                ))

        evaluated = len(source.paragraphs)
        if best is not None:
            result = best[1]
            return LinkDecision(source.url, target.url, REASON_APPROVED, result.rationale, result, evaluated)
        if passed_gate:
            return LinkDecision(
                source.url, target.url, REASON_NO_ANCHOR,
                f"paragraphs passed the classifier gate but none has a free anchor with >= "
                f"{self.thresholds.anchor_min_words} topic words",
                None, evaluated,
            )
        return LinkDecision(
            source.url, target.url, REASON_CLASSIFIER_GATE,
            f"best score {best_score} / confidence {best_confidence} vs required "
            f"{self.min_score} / {self.min_confidence}",
            None, evaluated,
        )

    # ------------------------------------------------------------------- run

    def _index_page2(self, gsc_data: Optional[List[GSCQueryRow]]) -> List[GSCQueryRow]:
        """Page 2 opportunities (site thresholds), indexed by normalized page URL."""
        self._page2 = {}
        if not gsc_data:
            logger.info("No Search Console data: links are not prioritised by SERP page 2 opportunities")
            return []
        t = self.thresholds
        opportunities = GSCConnector().get_page2_opportunities(
            gsc_data, t.page2_min_position, t.page2_max_position, t.min_impressions
        )
        for row in opportunities:  # already sorted by impressions
            self._page2.setdefault(url_key(row.page), []).append(row)
        logger.info(
            "Search Console: %d rows, %d page 2 opportunities on %d pages (positions %s-%s, >= %s impressions)",
            len(gsc_data), len(opportunities), len(self._page2),
            t.page2_min_position, t.page2_max_position, t.min_impressions,
        )
        return opportunities

    def run_optimization(
        self,
        pages: List[ParsedPage],
        gsc_data: Optional[List[GSCQueryRow]] = None,
    ) -> AuditReport:
        start_time = time.time()
        fallbacks_before = getattr(self.classifier, "fallbacks", 0)
        logger.info(
            "Optimization started: %d pages | classifier %s | gate score >= %s, confidence >= %s | "
            "anchors >= %d topic words",
            len(pages), self.classifier.describe(), self.min_score, self.min_confidence,
            self.thresholds.anchor_min_words,
        )

        # 1. Build this site's link graph from scratch; roles and clusters come
        #    from the site taxonomy (unmatched config entries raise a TaxonomyWarning).
        self.link_graph = LinkGraph()
        for page in pages:
            self.link_graph.add_page(page.url)
            for target in page.existing_internal_links:
                self.link_graph.add_link(page.url, target)
        self.link_graph.apply_taxonomy(self.taxonomy)
        self.baseline_graph = self.link_graph.copy()
        roles = Counter(m["role"] for m in self.link_graph.page_metadata.values())
        clusters = Counter(m["cluster"] for m in self.link_graph.page_metadata.values())
        logger.info(
            "Link graph built: %d pages, %d existing links | roles %s | clusters %s",
            len(self.link_graph.nodes), sum(len(t) for t in self.link_graph.edges.values()),
            dict(roles), dict(clusters),
        )

        page2_opportunities = self._index_page2(gsc_data)

        approved_links: List[LinkOptimizationResult] = []
        candidate_count = 0
        refused_pages_set: Set[str] = set(p.url for p in pages)
        reasons: Counter = Counter()

        # 2. Evaluate every ordered page pair; _decide applies the gates in order.
        self._last_pages = {page.url: page for page in pages}
        self._last_approved = {}
        self._used_anchors = {page.url: list(page.content_anchor_texts) for page in pages}
        for index, source in enumerate(pages, start=1):
            calls_before, approved_before = candidate_count, len(approved_links)
            for target in pages:
                if source.url == target.url:
                    continue
                decision = self._decide(source, target)
                reasons[decision.reason] += 1
                candidate_count += decision.paragraphs_evaluated
                logger.debug("Decision %s -> %s: %s (%s)", source.url, target.url, decision.reason, decision.detail)
                if decision.result is not None:
                    result = decision.result
                    approved_links.append(result)
                    self._last_approved[(source.url, target.url)] = decision
                    self.link_graph.add_link(source.url, target.url, result.anchor_text)
                    self._used_anchors[source.url].append(result.anchor_text)
                    refused_pages_set.discard(target.url)
                    logger.info(
                        "Link approved: %s -> %s [%s] score %s, confidence %s (%s)%s",
                        source.url, target.url, result.anchor_text, result.relevance_score,
                        result.confidence, result.classifier,
                        f" | boosts page 2 query '{result.page2_query}'" if result.page2_query else "",
                    )
            logger.info(
                "Source %d/%d done: %s | %d classifier calls, %d links approved",
                index, len(pages), source.url, candidate_count - calls_before, len(approved_links) - approved_before,
            )

        # Page 2 boosting links first (most impressions first), then in evaluation order.
        approved_links.sort(key=lambda r: -r.page2_impressions)

        duration = time.time() - start_time
        estimated_cost = candidate_count * self.classifier.cost_per_call_usd
        fallbacks = getattr(self.classifier, "fallbacks", 0) - fallbacks_before
        report = AuditReport(
            total_pages_evaluated=len(pages),
            candidate_pairs_checked=candidate_count,
            links_approved=len(approved_links),
            pages_refused=len(refused_pages_set),
            duration_seconds=round(duration, 2),
            estimated_cost_usd=round(estimated_cost, 4),
            results=approved_links,
            orphan_pages=self.link_graph.find_orphan_pages(),
            page2_opportunities=page2_opportunities,
            decisions_by_reason=dict(reasons),
            classifier=self.classifier.describe(),
            classifier_fallbacks=fallbacks,
        )
        if fallbacks:
            logger.warning("%d of %d classifier calls were answered by the fallback classifier", fallbacks, candidate_count)
        logger.info(
            "Optimization finished in %.2fs: %d links approved, %d classifier calls (~$%.4f), "
            "%d page 2 pages boosted, %d orphan pages | decisions %s",
            duration, report.links_approved, candidate_count, estimated_cost,
            len(report.page2_pages_boosted), len(report.orphan_pages), dict(reasons),
        )
        return report
