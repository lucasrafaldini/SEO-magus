"""
Reference (ground-truth) benchmark: the sanity check of the evaluation flow.

Real sites cannot tell us the *correct* output of the pipeline: nobody knows
their "true" link plan, and their rankings change daily. This module therefore
provides two references whose answers are known exactly:

1. WIKIPEDIA_PAGERANK_EXAMPLE - the graph from Wikipedia's "PageRank" article
   illustration (nodes A-K), with its published scores in percent. It pins the
   ranking math to an external, widely reproduced result.

2. A fictional site (Ledgerly, an invoicing & payroll SaaS on the reserved
   .example domain) designed so the correct outcome of every pipeline stage is
   known by construction:

   * GSC page 2 filter: rows sit exactly on the window and impression
     boundaries, so the expected opportunity list is unambiguous.
   * Link approval: each EXPECTED_LINKS entry has a source paragraph that
     explicitly names the target page's topic (clear contextual reason).
   * Link refusal: each FORBIDDEN_LINKS entry is topically tempting (the source
     paragraph names the target's topic) but must be blocked by exactly one
     rule of the flow, recorded as its reason.
   * Graph: the only page nothing links to is the off-topic company news post,
     and pillar click depths follow from the expected links.
   * Anchors: each expected link uses the phrase that names the target's topic,
     placed in the paragraph that names it best.
   * Search Console steering: links into page 2 pages are flagged with the
     query they boost.

If the pipeline output differs from this ground truth, the flow (not the
fixture) has changed behaviour and must be investigated.
"""

from typing import Dict, FrozenSet, List, Tuple

from src.connectors.gsc_connector import GSCQueryRow
from src.connectors.sitemap_crawler import ParsedPage

# --------------------------------------------------------------------------
# 1. Published known answer for the ranking engine
# --------------------------------------------------------------------------

# source -> targets. A has no outbound links (dangling).
WIKIPEDIA_PAGERANK_EXAMPLE: Dict[str, str] = {
    "A": "", "B": "C", "C": "B", "D": "AB", "E": "BDF", "F": "BE",
    "G": "BE", "H": "BE", "I": "BE", "J": "E", "K": "E",
}
# Published PageRank (damping 0.85) in percent, rounded to one decimal.
WIKIPEDIA_PAGERANK_PERCENT: Dict[str, float] = {
    "A": 3.3, "B": 38.4, "C": 34.3, "D": 3.9, "E": 8.1, "F": 3.9,
    "G": 1.6, "H": 1.6, "I": 1.6, "J": 1.6, "K": 1.6,
}

# --------------------------------------------------------------------------
# 2. Ground-truth reference site
# --------------------------------------------------------------------------

BASE = "https://ledgerly.example"
INVOICING_GUIDE = f"{BASE}/guides/invoicing"                       # pillar, invoicing
INVOICE_TEMPLATE = f"{BASE}/invoicing/invoice-template"            # support, invoicing
LATE_REMINDERS = f"{BASE}/invoicing/late-payment-reminders"        # support, invoicing
RECURRING_BILLING = f"{BASE}/features/recurring-billing"           # money, invoicing
PAYROLL_GUIDE = f"{BASE}/guides/payroll"                           # pillar, payroll
PAYROLL_TAX = f"{BASE}/payroll/payroll-tax-deadlines"              # support, payroll
PRICING = f"{BASE}/pricing"                                        # money, sales
COMPANY_NEWS = f"{BASE}/news/company-retreat"                      # support, general (off-topic)

Link = Tuple[str, str]

EXPECTED_LINKS: FrozenSet[Link] = frozenset({
    (INVOICE_TEMPLATE, INVOICING_GUIDE),   # support -> pillar
    (LATE_REMINDERS, INVOICE_TEMPLATE),    # support -> support, same cluster
    (INVOICING_GUIDE, RECURRING_BILLING),  # pillar -> money
    (INVOICING_GUIDE, LATE_REMINDERS),     # pillar -> support (hub and spoke)
    (PAYROLL_TAX, PAYROLL_GUIDE),          # support -> pillar
    (PAYROLL_GUIDE, PAYROLL_TAX),          # pillar -> support
    (PAYROLL_GUIDE, PRICING),              # pillar -> money, across clusters via affinity
})

FORBIDDEN_LINKS: Dict[Link, str] = {
    (PAYROLL_TAX, INVOICE_TEMPLATE): "cluster boundary: payroll may not link to invoicing",
    (RECURRING_BILLING, LATE_REMINDERS): "role rule: money pages may not link to support posts",
    (LATE_REMINDERS, INVOICING_GUIDE): "existing link: already present in the crawl",
    (LATE_REMINDERS, RECURRING_BILLING): "Jev thresholds: a single shared word is not enough evidence",
    (PRICING, RECURRING_BILLING): "cluster affinity is one-way: sales may not link to invoicing",
}

# The anchor each expected link should use: the phrase in the source paragraph
# that names the target's topic (case-insensitive).
EXPECTED_ANCHORS: Dict[Link, str] = {
    (INVOICE_TEMPLATE, INVOICING_GUIDE): "complete invoicing guide",
    (LATE_REMINDERS, INVOICE_TEMPLATE): "free invoice template",
    (INVOICING_GUIDE, RECURRING_BILLING): "recurring billing automation",
    (INVOICING_GUIDE, LATE_REMINDERS): "late payment reminders",
    (PAYROLL_TAX, PAYROLL_GUIDE): "complete payroll guide",
    (PAYROLL_GUIDE, PAYROLL_TAX): "payroll tax deadlines",
    (PAYROLL_GUIDE, PRICING): "pricing plans",
}

# Known, documented differences between the current flow and the ground truth.
# Tests assert this set exactly: add an entry (with the reason) if the flow
# regresses knowingly, remove it when fixed. Empty: the flow matches exactly.
KNOWN_ANCHOR_DEVIATIONS: Dict[Link, str] = {}

# Links into pages with SERP page 2 queries must be flagged with the query
# they boost (the page's top query by impressions) and listed first.
EXPECTED_PAGE2_LINKS: Dict[Link, str] = {
    (INVOICING_GUIDE, RECURRING_BILLING): "recurring billing software",
    (INVOICING_GUIDE, LATE_REMINDERS): "late payment reminder email",
    (PAYROLL_GUIDE, PAYROLL_TAX): "payroll tax deadlines 2026",
}

EXPECTED_ORPHANS: FrozenSet[str] = frozenset({COMPANY_NEWS})

EXPECTED_PILLAR_DEPTHS: Dict[str, int] = {
    INVOICING_GUIDE: 0,
    PAYROLL_GUIDE: 0,
    RECURRING_BILLING: 1,
    LATE_REMINDERS: 1,
    PAYROLL_TAX: 1,
    PRICING: 1,
    INVOICE_TEMPLATE: 2,
}

# Ordered by impressions, as GSCConnector.get_page2_opportunities returns them,
# for the thresholds in config/sites/reference.yaml (positions 11-20, >= 100 impressions).
EXPECTED_PAGE2_QUERIES: Tuple[str, ...] = (
    "late payment reminder email",
    "recurring billing software",
    "payroll tax deadlines 2026",
)


def build_reference_pages() -> List[ParsedPage]:
    return [
        ParsedPage(
            url=INVOICING_GUIDE,
            title="Complete Invoicing Guide",
            h1="Complete Invoicing Guide",
            paragraphs=[
                "Invoicing is how a business turns finished work into cash. Every invoice needs a number, a due date and clear payment terms.",
                "Once clients pay every month, switch to recurring billing automation so invoices go out without manual work.",
                "When an invoice is overdue, polite late payment reminders recover most of the money within a week.",
            ],
        ),
        ParsedPage(
            url=INVOICE_TEMPLATE,
            title="Free Invoice Template",
            h1="Free Invoice Template",
            paragraphs=[
                "Download a free invoice template in Word or PDF format, fill in your client details and send it the same day.",
                "For the full process from quote to payment, read our complete invoicing guide.",
            ],
        ),
        ParsedPage(
            url=LATE_REMINDERS,
            title="Late Payment Reminders",
            h1="Late Payment Reminders",
            paragraphs=[
                "Send the first reminder three days after the due date and keep the tone friendly.",
                "Attach a copy of the original invoice, ideally built from a clean free invoice template, so the client can pay immediately.",
                "Our complete invoicing guide explains how to set payment terms that prevent late payments.",
                "Some teams add a billing portal so clients can settle balances themselves.",
            ],
            existing_internal_links=[INVOICING_GUIDE],
        ),
        ParsedPage(
            url=RECURRING_BILLING,
            title="Recurring Billing Automation",
            h1="Recurring Billing Automation",
            paragraphs=[
                "Charge subscriptions automatically on a fixed schedule and let customers update their card details.",
                "Failed charges trigger late payment reminders automatically, with no extra setup.",
            ],
        ),
        ParsedPage(
            url=PAYROLL_GUIDE,
            title="Complete Payroll Guide",
            h1="Complete Payroll Guide",
            paragraphs=[
                # Qualifies for payroll-tax-deadlines too ("payroll deadline"), but the
                # next paragraph names the target best: the link must go there.
                "Running payroll means meeting every payroll deadline and paying employees on schedule.",
                "Missing a filing date is expensive, so keep a calendar of payroll tax deadlines for every state.",
                "Compare our pricing plans to see which tier includes automated payroll runs.",
            ],
        ),
        ParsedPage(
            url=PAYROLL_TAX,
            title="Payroll Tax Deadlines",
            h1="Payroll Tax Deadlines",
            paragraphs=[
                "Quarterly filings are due one month after each quarter ends, and annual forms are due in January.",
                "Before you file, make sure every contractor has received a free invoice template from your accounts team.",
                "New to running payroll? Start with the complete payroll guide.",
            ],
        ),
        ParsedPage(
            url=PRICING,
            title="Pricing Plans",
            h1="Pricing Plans",
            paragraphs=[
                "Every plan includes unlimited invoices, recurring billing automation and payroll for up to five employees.",
            ],
        ),
        ParsedPage(
            url=COMPANY_NEWS,
            title="Company Retreat Recap",
            h1="Company Retreat Recap",
            paragraphs=[
                "Our whole team spent three days hiking, cooking and planning the roadmap for next year.",
            ],
        ),
    ]


def build_reference_gsc_rows() -> List[GSCQueryRow]:
    return [
        GSCQueryRow("invoice template", INVOICE_TEMPLATE, clicks=410, impressions=5400, ctr=0.076, position=3.2),        # page 1
        GSCQueryRow("recurring billing software", RECURRING_BILLING, clicks=9, impressions=900, ctr=0.01, position=11.0),  # lower bound
        GSCQueryRow("late payment reminder email", LATE_REMINDERS, clicks=21, impressions=2600, ctr=0.008, position=14.5),
        GSCQueryRow("payroll tax deadlines 2026", PAYROLL_TAX, clicks=4, impressions=450, ctr=0.009, position=20.0),       # upper bound
        GSCQueryRow("payroll guide for startups", PAYROLL_GUIDE, clicks=1, impressions=60, ctr=0.017, position=16.0),     # too few impressions
        GSCQueryRow("invoicing guide", INVOICING_GUIDE, clicks=12, impressions=3000, ctr=0.004, position=20.1),           # just past page 2
        GSCQueryRow("company retreat ideas", COMPANY_NEWS, clicks=0, impressions=80, ctr=0.0, position=35.0),
    ]
