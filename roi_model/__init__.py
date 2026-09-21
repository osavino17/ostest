"""ROI scoring model for client engagement touchpoints (events & sponsorships).

Non-attribution scoring model: touchpoints are never credited with a dollar
amount of revenue. Instead each touchpoint gets a relative "contribution
score" built from (a) how well the engagement itself went (who showed up,
how prestigious the format) and (b) how commercially important the client
relationship is right now (open mandates, pipeline, priority tier,
relationship intensity), blended according to the client's mix of flow vs.
cyclical revenue.
"""

from roi_model.models import ClientContext, Touchpoint
from roi_model.scoring import ScoringConfig, score_touchpoint, score_client_business_weight

__all__ = [
    "ClientContext",
    "Touchpoint",
    "ScoringConfig",
    "score_touchpoint",
    "score_client_business_weight",
]
