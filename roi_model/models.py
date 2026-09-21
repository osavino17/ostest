"""Data model for touchpoints and client business context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Touchpoint:
    """A single event or sponsorship interaction with one client.

    One row per (touchpoint, client) pair -- a flagship conference with
    12 invited clients produces 12 Touchpoint records, one per client,
    since attendance/seniority/status are all client-specific.
    """

    touchpoint_id: str
    client_id: str
    event_name: str
    event_type: str          # "event" | "sponsorship"
    event_tier: str          # "flagship" | "signature" | "regional" | "roundtable" |
                              # "sponsorship_branding" | "sponsorship_hospitality"
    date: str                # ISO date
    allocated_budget: float  # cost attributed to this client's seat/slot, in local currency
    invited: bool
    accepted: bool
    attended: bool
    attendee_seniority: str = "none"  # "c_suite" | "md" | "director" | "vp" | "associate" | "none"
    coverage_banker: str = ""
    notes: str = ""


@dataclass
class ClientContext:
    """Business context for a client, refreshed periodically (e.g. monthly)."""

    client_id: str
    client_name: str
    priority_tier: str            # "strategic" | "core" | "developing" | "monitor"
    active_mandates: int          # count of live mandates (M&A, DCM, ECM, lending, etc.)
    pipeline_value: float         # expected value ($) of deals in pipeline, not yet mandated
    pipeline_stage: str           # "none" | "prospect" | "qualified" | "committed" | "closing"
    relationship_intensity_12m: int  # count of substantive touchpoints/contacts in trailing 12mo
    flow_revenue_ltm: float       # recurring/transactional revenue, last twelve months
    cyclical_revenue_ltm: float   # deal-driven revenue, last twelve months
    coverage_banker: str = ""

    @property
    def flow_share(self) -> float:
        total = self.flow_revenue_ltm + self.cyclical_revenue_ltm
        if total <= 0:
            return 0.5  # no revenue history yet (e.g. prospect) -> assume balanced mix
        return self.flow_revenue_ltm / total

    @property
    def cyclical_share(self) -> float:
        return 1.0 - self.flow_share
