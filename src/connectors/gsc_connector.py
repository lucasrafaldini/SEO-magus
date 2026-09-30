"""
Google Search Console (GSC) Connector.

Pulls page-level and query-level performance metrics:
- Clicks, Impressions, CTR, Average Position
- Isolates Page 2 SERP opportunities (Positions 11.0 to 20.0)
- Supports live Google API authentication or local CSV/JSON exports.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


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
        min_position: float = 11.0,
        max_position: float = 20.0,
        min_impressions: int = 50,
    ) -> List[GSCQueryRow]:
        """
        Filters queries averaging positions 11 to 20 with substantial impressions.
        These are prime targets to boost with internal links.
        """
        candidates = [
            r
            for r in rows
            if min_position <= r.position <= max_position and r.impressions >= min_impressions
        ]
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
