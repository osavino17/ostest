"""CSV in, scored CSVs out. No external dependencies (stdlib only)."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import asdict
from statistics import mean
from typing import Dict, List

from roi_model.models import ClientContext, Touchpoint
from roi_model.scoring import ScoringConfig, TouchpointScore, score_touchpoint


def _to_bool(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def load_touchpoints(path: str) -> List[Touchpoint]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [
        Touchpoint(
            touchpoint_id=r["touchpoint_id"],
            client_id=r["client_id"],
            event_name=r["event_name"],
            event_type=r["event_type"],
            event_tier=r["event_tier"],
            date=r["date"],
            allocated_budget=float(r["allocated_budget"]),
            invited=_to_bool(r["invited"]),
            accepted=_to_bool(r["accepted"]),
            attended=_to_bool(r["attended"]),
            attendee_seniority=r.get("attendee_seniority", "none") or "none",
            coverage_banker=r.get("coverage_banker", ""),
            notes=r.get("notes", ""),
        )
        for r in rows
    ]


def load_clients(path: str) -> Dict[str, ClientContext]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    clients = {}
    for r in rows:
        ctx = ClientContext(
            client_id=r["client_id"],
            client_name=r["client_name"],
            priority_tier=r["priority_tier"],
            active_mandates=int(r["active_mandates"]),
            pipeline_value=float(r["pipeline_value"]),
            pipeline_stage=r["pipeline_stage"],
            relationship_intensity_12m=int(r["relationship_intensity_12m"]),
            flow_revenue_ltm=float(r["flow_revenue_ltm"]),
            cyclical_revenue_ltm=float(r["cyclical_revenue_ltm"]),
            coverage_banker=r.get("coverage_banker", ""),
        )
        clients[ctx.client_id] = ctx
    return clients


def _percentile_rank(values: List[float], v: float) -> float:
    """Simple 0-100 percentile rank of v within values (ties get mean rank)."""
    if not values:
        return 0.0
    n = len(values)
    below = sum(1 for x in values if x < v)
    equal = sum(1 for x in values if x == v)
    return 100.0 * (below + 0.5 * equal) / n


def score_all(
    touchpoints: List[Touchpoint],
    clients: Dict[str, ClientContext],
    cfg: ScoringConfig = ScoringConfig(),
) -> List[TouchpointScore]:
    scores = []
    for tp in touchpoints:
        ctx = clients.get(tp.client_id)
        if ctx is None:
            raise KeyError(f"No ClientContext found for client_id={tp.client_id!r} (touchpoint {tp.touchpoint_id})")
        scores.append(score_touchpoint(tp, ctx, cfg))
    return scores


def rank_engagement_roi(scores: List[TouchpointScore]) -> Dict[str, float]:
    """Percentile-rank raw ERI across the whole portfolio -> Engagement ROI Index (0-100)."""
    raw_values = [s.eri_raw for s in scores]
    return {s.touchpoint_id: round(_percentile_rank(raw_values, s.eri_raw), 1) for s in scores}


def write_touchpoint_report(scores: List[TouchpointScore], eri_index: Dict[str, float], out_path: str) -> None:
    fieldnames = [
        "touchpoint_id", "client_id", "event_name",
        "aqs", "tev", "bws", "tcs", "cost_ratio", "eri_raw", "engagement_roi_index",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for s in sorted(scores, key=lambda s: eri_index[s.touchpoint_id], reverse=True):
            row = asdict(s)
            row["engagement_roi_index"] = eri_index[s.touchpoint_id]
            writer.writerow(row)


def write_client_alignment_report(
    scores: List[TouchpointScore],
    clients: Dict[str, ClientContext],
    out_path: str,
) -> None:
    """Per client: total engagement spend/contribution vs. business importance.

    Flags clients where investment (spend, contribution score) is out of
    step with commercial importance (BWS) -- both over- and under-invested.
    """
    by_client: Dict[str, List[TouchpointScore]] = defaultdict(list)
    for s in scores:
        by_client[s.client_id].append(s)

    contribution_sum: Dict[str, float] = defaultdict(float)
    touchpoint_count: Dict[str, int] = defaultdict(int)
    for s in scores:
        contribution_sum[s.client_id] += s.tcs
        touchpoint_count[s.client_id] += 1

    bws_by_client = {}
    for cid in contribution_sum:
        ctx = clients[cid]
        # BWS already implicit in each score's .bws (constant per client); reuse it.
        bws_by_client[cid] = next(s.bws for s in by_client[cid])

    contribution_values = list(contribution_sum.values())
    bws_values = list(bws_by_client.values())

    fieldnames = [
        "client_id", "client_name", "priority_tier",
        "touchpoint_count", "total_contribution_score", "contribution_percentile",
        "business_weight_score", "business_weight_percentile",
        "alignment_gap", "alignment_flag",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for cid, contribution in sorted(contribution_sum.items(), key=lambda kv: kv[1], reverse=True):
            ctx = clients[cid]
            contribution_pct = _percentile_rank(contribution_values, contribution)
            bws_pct = _percentile_rank(bws_values, bws_by_client[cid])
            gap = contribution_pct - bws_pct

            if gap > 20:
                flag = "over-invested (spend/engagement exceeds commercial importance)"
            elif gap < -20:
                flag = "under-invested (commercial importance exceeds engagement received)"
            else:
                flag = "aligned"

            writer.writerow({
                "client_id": cid,
                "client_name": ctx.client_name,
                "priority_tier": ctx.priority_tier,
                "touchpoint_count": touchpoint_count[cid],
                "total_contribution_score": round(contribution, 4),
                "contribution_percentile": round(contribution_pct, 1),
                "business_weight_score": round(bws_by_client[cid], 4),
                "business_weight_percentile": round(bws_pct, 1),
                "alignment_gap": round(gap, 1),
                "alignment_flag": flag,
            })


def write_event_effectiveness_report(scores: List[TouchpointScore], eri_index: Dict[str, float], out_path: str) -> None:
    """Per event: average engagement ROI index across all attending clients."""
    by_event: Dict[str, List[TouchpointScore]] = defaultdict(list)
    for s in scores:
        by_event[s.event_name].append(s)

    fieldnames = ["event_name", "client_count", "avg_tev", "avg_bws", "avg_engagement_roi_index"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        rows = []
        for event_name, event_scores in by_event.items():
            rows.append({
                "event_name": event_name,
                "client_count": len(event_scores),
                "avg_tev": round(mean(s.tev for s in event_scores), 4),
                "avg_bws": round(mean(s.bws for s in event_scores), 4),
                "avg_engagement_roi_index": round(mean(eri_index[s.touchpoint_id] for s in event_scores), 1),
            })
        for row in sorted(rows, key=lambda r: r["avg_engagement_roi_index"], reverse=True):
            writer.writerow(row)
