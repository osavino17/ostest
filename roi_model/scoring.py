"""Scoring engine.

This is a *scoring* model, not an attribution model: nothing here claims
that a touchpoint caused a specific dollar of revenue. Every score is a
relative index (roughly 0-1, or 0-100 once percentile-ranked) meant to
support two questions coverage teams and event sponsors actually have:

  1. "Did this engagement land with the right, senior people?"          -> AQS / TEV
  2. "Are we spending our engagement budget on the clients/deals that
      matter most right now, given how we make money from them?"       -> BWS / TCS / ERI

The four "core data points" the model asked for (attendance, budget,
invitations, status) map to:
  - attendance -> `attended` / `accepted` (fill/no-show behaviour)
  - budget     -> `allocated_budget`, used only in the cost-efficiency step
  - invitations-> `invited` / `accepted` (funnel signal)
  - status     -> `event_tier` (prestige/format of the touchpoint) and
                  `attendee_seniority` (seniority of who actually showed up)

The "business information" data points (deal/mandate, pipeline, client
priority, intensity) map directly onto `ClientContext` fields and combine
into the Business Weight Score (BWS), which is blended by the client's
flow/cyclical revenue mix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from roi_model.models import ClientContext, Touchpoint


# ---------------------------------------------------------------------------
# Reference maps -- business/quant owners tune these, not the formulas below.
# ---------------------------------------------------------------------------

SENIORITY_WEIGHT: Dict[str, float] = {
    "c_suite": 1.00,
    "md": 0.80,
    "director": 0.55,
    "vp": 0.35,
    "associate": 0.15,
    "none": 0.00,
}

EVENT_TIER_WEIGHT: Dict[str, float] = {
    "flagship": 1.00,               # marquee, high-visibility conference
    "signature": 0.80,              # well-branded, recurring franchise event
    "roundtable": 0.70,             # small group, high touch
    "sponsorship_hospitality": 0.60,  # client-facing hospitality (e.g. suite, box)
    "regional": 0.55,               # local/regional market event
    "sponsorship_branding": 0.30,   # brand-visibility sponsorship, limited direct contact
}

# Typical/benchmark cost per attendee for each tier, used only to normalise
# cost-efficiency comparisons across very differently priced formats.
EVENT_TIER_BENCHMARK_COST: Dict[str, float] = {
    "flagship": 8000.0,
    "signature": 4000.0,
    "roundtable": 2500.0,
    "sponsorship_hospitality": 3000.0,
    "regional": 1500.0,
    "sponsorship_branding": 1000.0,
}

PRIORITY_TIER_SCORE: Dict[str, float] = {
    "strategic": 1.00,
    "core": 0.65,
    "developing": 0.40,
    "monitor": 0.15,
}

PIPELINE_STAGE_PROBABILITY: Dict[str, float] = {
    "none": 0.00,
    "prospect": 0.10,
    "qualified": 0.30,
    "committed": 0.60,
    "closing": 0.85,
}


@dataclass
class ScoringConfig:
    """All tunable weights and caps live here, kept separate from formulas."""

    # attendance-quality blend: base engagement level vs seniority multiplier
    attended_base: float = 1.00
    accepted_no_show_base: float = 0.20
    not_accepted_base: float = 0.00
    seniority_multiplier_floor: float = 0.60   # min multiplier even for a junior attendee
    seniority_multiplier_span: float = 0.40    # additional multiplier earned up to c-suite

    # touchpoint engagement value blend: AQS vs event tier/status
    tev_aqs_weight: float = 0.60
    tev_tier_weight: float = 0.40

    # business weight sub-score blends
    relationship_priority_weight: float = 0.55
    relationship_intensity_weight: float = 0.45
    deal_mandate_weight: float = 0.45
    deal_pipeline_weight: float = 0.55

    # normalisation caps
    intensity_cap: int = 8          # touchpoints/contacts per year treated as "max" intensity
    pipeline_value_cap: float = 25_000_000.0  # pipeline $ treated as "max" for normalisation
    mandate_saturation: int = 2     # active mandates at which mandate_component saturates at 1.0

    def seniority_multiplier(self, seniority: str) -> float:
        w = SENIORITY_WEIGHT.get(seniority, 0.0)
        return self.seniority_multiplier_floor + self.seniority_multiplier_span * w


DEFAULT_CONFIG = ScoringConfig()


# ---------------------------------------------------------------------------
# Touchpoint-side scoring (event quality, independent of any one client's
# commercial importance -- this half answers "did the event itself work?")
# ---------------------------------------------------------------------------

def attendance_quality_score(tp: Touchpoint, cfg: ScoringConfig = DEFAULT_CONFIG) -> float:
    """AQS in [0, 1]: did the invite convert into a senior, present attendee?"""
    if tp.attended:
        base = cfg.attended_base
    elif tp.accepted:
        base = cfg.accepted_no_show_base  # accepted but no-showed: weak negative signal
    else:
        base = cfg.not_accepted_base      # declined or never responded

    if base == 0.0:
        return 0.0

    return base * cfg.seniority_multiplier(tp.attendee_seniority)


def touchpoint_engagement_value(tp: Touchpoint, cfg: ScoringConfig = DEFAULT_CONFIG) -> float:
    """TEV in [0, 1]: blends attendance quality with the format's status/prestige."""
    aqs = attendance_quality_score(tp, cfg)
    tier_weight = EVENT_TIER_WEIGHT.get(tp.event_tier, 0.5)
    return cfg.tev_aqs_weight * aqs + cfg.tev_tier_weight * tier_weight * (1.0 if tp.attended or tp.accepted else 0.4)


def cost_efficiency_ratio(tp: Touchpoint, cfg: ScoringConfig = DEFAULT_CONFIG) -> float:
    """Allocated budget relative to the tier's benchmark cost (1.0 = on-benchmark)."""
    benchmark = EVENT_TIER_BENCHMARK_COST.get(tp.event_tier, 3000.0)
    if benchmark <= 0:
        return 1.0
    return tp.allocated_budget / benchmark


# ---------------------------------------------------------------------------
# Client-side scoring (commercial importance -- this half answers "does this
# relationship deserve the engagement spend, and for what kind of revenue?")
# ---------------------------------------------------------------------------

def _priority_component(ctx: ClientContext) -> float:
    return PRIORITY_TIER_SCORE.get(ctx.priority_tier, 0.4)


def _intensity_component(ctx: ClientContext, cfg: ScoringConfig = DEFAULT_CONFIG) -> float:
    if cfg.intensity_cap <= 0:
        return 0.0
    return min(1.0, ctx.relationship_intensity_12m / cfg.intensity_cap)


def _mandate_component(ctx: ClientContext, cfg: ScoringConfig = DEFAULT_CONFIG) -> float:
    if cfg.mandate_saturation <= 0:
        return 0.0
    return min(1.0, ctx.active_mandates / cfg.mandate_saturation)


def _pipeline_component(ctx: ClientContext, cfg: ScoringConfig = DEFAULT_CONFIG) -> float:
    probability = PIPELINE_STAGE_PROBABILITY.get(ctx.pipeline_stage, 0.0)
    normalised_value = min(1.0, ctx.pipeline_value / cfg.pipeline_value_cap) if cfg.pipeline_value_cap > 0 else 0.0
    return probability * normalised_value


def relationship_health_score(ctx: ClientContext, cfg: ScoringConfig = DEFAULT_CONFIG) -> float:
    """RHS in [0, 1]: flow-revenue lens -- priority tier + how "warm" the relationship is."""
    return (
        cfg.relationship_priority_weight * _priority_component(ctx)
        + cfg.relationship_intensity_weight * _intensity_component(ctx, cfg)
    )


def deal_readiness_score(ctx: ClientContext, cfg: ScoringConfig = DEFAULT_CONFIG) -> float:
    """DRS in [0, 1]: cyclical-revenue lens -- live mandates + probability-weighted pipeline."""
    return (
        cfg.deal_mandate_weight * _mandate_component(ctx, cfg)
        + cfg.deal_pipeline_weight * _pipeline_component(ctx, cfg)
    )


def score_client_business_weight(ctx: ClientContext, cfg: ScoringConfig = DEFAULT_CONFIG) -> float:
    """BWS in [0, 1]: blends RHS and DRS by the client's actual flow/cyclical revenue mix.

    A client earning 90% of revenue from flow business gets a BWS dominated
    by relationship health (priority + intensity); a client earning mostly
    cyclical/deal revenue gets a BWS dominated by mandate/pipeline signal.
    """
    rhs = relationship_health_score(ctx, cfg)
    drs = deal_readiness_score(ctx, cfg)
    return ctx.flow_share * rhs + ctx.cyclical_share * drs


# ---------------------------------------------------------------------------
# Combined touchpoint contribution + ROI efficiency
# ---------------------------------------------------------------------------

@dataclass
class TouchpointScore:
    touchpoint_id: str
    client_id: str
    event_name: str
    aqs: float                    # attendance quality score
    tev: float                    # touchpoint engagement value (event-side only)
    bws: float                    # client business weight (client-side only)
    tcs: float                    # touchpoint contribution score = tev * bws
    cost_ratio: float             # allocated_budget / tier benchmark cost
    eri_raw: float                # tcs / cost_ratio (engagement ROI index, unranked)


def score_touchpoint(
    tp: Touchpoint,
    ctx: ClientContext,
    cfg: ScoringConfig = DEFAULT_CONFIG,
) -> TouchpointScore:
    aqs = attendance_quality_score(tp, cfg)
    tev = touchpoint_engagement_value(tp, cfg)
    bws = score_client_business_weight(ctx, cfg)
    tcs = tev * bws
    cost_ratio = cost_efficiency_ratio(tp, cfg)
    # guard against div-by-zero for zero-budget touchpoints (e.g. comped seat)
    eri_raw = tcs / cost_ratio if cost_ratio > 0 else tcs / 0.01

    return TouchpointScore(
        touchpoint_id=tp.touchpoint_id,
        client_id=tp.client_id,
        event_name=tp.event_name,
        aqs=round(aqs, 4),
        tev=round(tev, 4),
        bws=round(bws, 4),
        tcs=round(tcs, 4),
        cost_ratio=round(cost_ratio, 4),
        eri_raw=round(eri_raw, 4),
    )
