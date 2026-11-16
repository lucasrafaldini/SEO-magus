"""
Google Search Console (GSC) Connector.

Pulls page-level and query-level performance metrics:
- Clicks, Impressions, CTR, Average Position
- Isolates Page 2 SERP opportunities (Positions 11.0 to 20.0)
- Currently works on GSCQueryRow lists (a built-in sample dataset is provided);
  importing Search Console exports / the live API is not implemented yet.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from src.config import DEFAULT_THRESHOLDS
from src.log import get_logger

logger = get_logger(__name__)


@dataclass
class GSCQueryRow:
    query: str
    page: str
    clicks: int
    impressions: int
    ctr: float
    position: float


class GSCConnector:
    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path

    def get_page2_opportunities(
        self,
        rows: List[GSCQueryRow],
        min_position: float = DEFAULT_THRESHOLDS.page2_min_position,
        max_position: float = DEFAULT_THRESHOLDS.page2_max_position,
        min_impressions: int = DEFAULT_THRESHOLDS.min_impressions,
    ) -> List[GSCQueryRow]:
        """
        Filters queries averaging positions 11 to 20 (inclusive) with substantial
        impressions, sorted by impressions. These are prime targets to boost
        with internal links. Defaults come from config.Thresholds.
        """
        candidates = [
            r
            for r in rows
            if min_position <= r.position <= max_position and r.impressions >= min_impressions
        ]
        logger.debug(
            "Page 2 filter (positions %s-%s, >= %s impressions): %d of %d rows kept",
            min_position, max_position, min_impressions, len(candidates), len(rows),
        )
        return sorted(candidates, key=lambda x: x.impressions, reverse=True)

    @classmethod
    def get_sample_dataset(cls) -> List[GSCQueryRow]:
        """Provides realistic sample data based on Borja's email software example."""
        return [
            GSCQueryRow(
                query="welcome email sequence",
                page="https://example.com/blog/welcome-sequence-guide",
                clicks=14,
                impressions=1820,
                ctr=0.007,
                position=14.2,
            ),
            GSCQueryRow(
                query="backlink exchange strategies",
                page="https://example.com/blog/backlink-guide",
                clicks=8,
                impressions=950,
                ctr=0.008,
                position=17.0,
            ),
            GSCQueryRow(
                query="email automation workflow",
                page="https://example.com/blog/automation-workflows",
                clicks=22,
                impressions=2400,
                ctr=0.009,
                position=12.5,
            ),
            GSCQueryRow(
                query="best email marketing tool",
                page="https://example.com/pricing",
                clicks=120,
                impressions=8900,
                ctr=0.013,
                position=4.1,
            ),
        ]
