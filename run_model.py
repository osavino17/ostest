#!/usr/bin/env python3
"""Run the client engagement ROI scoring model over CSV inputs.

Usage:
    python run_model.py \
        --touchpoints sample_data/touchpoints.csv \
        --clients sample_data/clients.csv \
        --out-dir out/

Produces three reports in --out-dir:
    touchpoint_scores.csv      per-touchpoint scores, ranked by Engagement ROI Index
    client_alignment.csv       per-client spend/contribution vs. business importance
    event_effectiveness.csv    per-event average scores, for future budget allocation
"""

from __future__ import annotations

import argparse
import os

from roi_model.pipeline import (
    load_clients,
    load_touchpoints,
    rank_engagement_roi,
    score_all,
    write_client_alignment_report,
    write_event_effectiveness_report,
    write_touchpoint_report,
)
from roi_model.scoring import ScoringConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--touchpoints", default="sample_data/touchpoints.csv")
    parser.add_argument("--clients", default="sample_data/clients.csv")
    parser.add_argument("--out-dir", default="out")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    touchpoints = load_touchpoints(args.touchpoints)
    clients = load_clients(args.clients)
    cfg = ScoringConfig()

    scores = score_all(touchpoints, clients, cfg)
    eri_index = rank_engagement_roi(scores)

    write_touchpoint_report(scores, eri_index, os.path.join(args.out_dir, "touchpoint_scores.csv"))
    write_client_alignment_report(scores, clients, os.path.join(args.out_dir, "client_alignment.csv"))
    write_event_effectiveness_report(scores, eri_index, os.path.join(args.out_dir, "event_effectiveness.csv"))

    print(f"Scored {len(scores)} touchpoints across {len(clients)} clients.")
    print(f"Reports written to {args.out_dir}/")


if __name__ == "__main__":
    main()
