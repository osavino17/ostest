import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from roi_model.models import ClientContext, Touchpoint
from roi_model.scoring import (
    ScoringConfig,
    attendance_quality_score,
    deal_readiness_score,
    relationship_health_score,
    score_client_business_weight,
    score_touchpoint,
    touchpoint_engagement_value,
)
from roi_model.pipeline import _percentile_rank, load_clients, load_touchpoints, rank_engagement_roi, score_all

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_data")


def make_touchpoint(**overrides) -> Touchpoint:
    base = dict(
        touchpoint_id="T-test",
        client_id="C-test",
        event_name="Test Event",
        event_type="event",
        event_tier="flagship",
        date="2026-01-01",
        allocated_budget=5000.0,
        invited=True,
        accepted=True,
        attended=True,
        attendee_seniority="md",
    )
    base.update(overrides)
    return Touchpoint(**base)


def make_client(**overrides) -> ClientContext:
    base = dict(
        client_id="C-test",
        client_name="Test Client",
        priority_tier="core",
        active_mandates=0,
        pipeline_value=0.0,
        pipeline_stage="none",
        relationship_intensity_12m=2,
        flow_revenue_ltm=1_000_000.0,
        cyclical_revenue_ltm=0.0,
    )
    base.update(overrides)
    return ClientContext(**base)


class AttendanceQualityScoreTests(unittest.TestCase):
    def test_declined_scores_zero(self):
        tp = make_touchpoint(accepted=False, attended=False, attendee_seniority="none")
        self.assertEqual(attendance_quality_score(tp), 0.0)

    def test_attended_c_suite_beats_attended_associate(self):
        senior = make_touchpoint(attendee_seniority="c_suite")
        junior = make_touchpoint(attendee_seniority="associate")
        self.assertGreater(attendance_quality_score(senior), attendance_quality_score(junior))

    def test_no_show_scores_less_than_attended(self):
        attended = make_touchpoint(attended=True, attendee_seniority="md")
        no_show = make_touchpoint(attended=False, accepted=True, attendee_seniority="none")
        self.assertGreater(attendance_quality_score(attended), attendance_quality_score(no_show))
        self.assertGreater(attendance_quality_score(no_show), 0.0)

    def test_score_bounded_zero_to_one(self):
        for seniority in ("c_suite", "md", "director", "vp", "associate", "none"):
            tp = make_touchpoint(attendee_seniority=seniority)
            score = attendance_quality_score(tp)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


class TouchpointEngagementValueTests(unittest.TestCase):
    def test_flagship_beats_branding_sponsorship_for_same_attendance(self):
        flagship = make_touchpoint(event_tier="flagship")
        branding = make_touchpoint(event_tier="sponsorship_branding")
        self.assertGreater(touchpoint_engagement_value(flagship), touchpoint_engagement_value(branding))

    def test_unattended_touchpoint_still_bounded(self):
        tp = make_touchpoint(invited=True, accepted=False, attended=False, attendee_seniority="none")
        value = touchpoint_engagement_value(tp)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)


class BusinessWeightScoreTests(unittest.TestCase):
    def test_flow_heavy_client_weighted_by_relationship_health(self):
        cfg = ScoringConfig()
        flow_client = make_client(
            flow_revenue_ltm=5_000_000, cyclical_revenue_ltm=0,
            priority_tier="strategic", relationship_intensity_12m=8,
            active_mandates=0, pipeline_value=0, pipeline_stage="none",
        )
        bws = score_client_business_weight(flow_client, cfg)
        rhs = relationship_health_score(flow_client, cfg)
        # flow-only client: BWS should equal RHS exactly (cyclical_share == 0)
        self.assertAlmostEqual(bws, rhs, places=6)

    def test_cyclical_heavy_client_weighted_by_deal_readiness(self):
        cfg = ScoringConfig()
        deal_client = make_client(
            flow_revenue_ltm=0, cyclical_revenue_ltm=5_000_000,
            priority_tier="monitor", relationship_intensity_12m=0,
            active_mandates=2, pipeline_value=20_000_000, pipeline_stage="closing",
        )
        bws = score_client_business_weight(deal_client, cfg)
        drs = deal_readiness_score(deal_client, cfg)
        self.assertAlmostEqual(bws, drs, places=6)

    def test_strategic_active_mandate_client_scores_higher_than_monitor_prospect(self):
        cfg = ScoringConfig()
        strong = make_client(
            priority_tier="strategic", active_mandates=2, pipeline_value=20_000_000,
            pipeline_stage="closing", relationship_intensity_12m=8,
            flow_revenue_ltm=2_000_000, cyclical_revenue_ltm=8_000_000,
        )
        weak = make_client(
            priority_tier="monitor", active_mandates=0, pipeline_value=0,
            pipeline_stage="none", relationship_intensity_12m=0,
            flow_revenue_ltm=100_000, cyclical_revenue_ltm=0,
        )
        self.assertGreater(score_client_business_weight(strong, cfg), score_client_business_weight(weak, cfg))

    def test_bws_bounded_zero_to_one(self):
        cfg = ScoringConfig()
        extreme = make_client(
            priority_tier="strategic", active_mandates=10, pipeline_value=999_000_000,
            pipeline_stage="closing", relationship_intensity_12m=100,
            flow_revenue_ltm=1, cyclical_revenue_ltm=1,
        )
        bws = score_client_business_weight(extreme, cfg)
        self.assertGreaterEqual(bws, 0.0)
        self.assertLessEqual(bws, 1.0)


class ScoreTouchpointIntegrationTests(unittest.TestCase):
    def test_important_client_at_flagship_event_outscores_low_priority_client_same_event(self):
        cfg = ScoringConfig()
        strategic_client = make_client(priority_tier="strategic", active_mandates=1, pipeline_value=10_000_000,
                                        pipeline_stage="committed", relationship_intensity_12m=6,
                                        flow_revenue_ltm=1_000_000, cyclical_revenue_ltm=3_000_000)
        monitor_client = make_client(priority_tier="monitor", active_mandates=0, pipeline_value=0,
                                      pipeline_stage="none", relationship_intensity_12m=1,
                                      flow_revenue_ltm=50_000, cyclical_revenue_ltm=0)
        tp = make_touchpoint()
        strategic_score = score_touchpoint(tp, strategic_client, cfg)
        monitor_score = score_touchpoint(tp, monitor_client, cfg)
        self.assertGreater(strategic_score.tcs, monitor_score.tcs)
        # AQS/TEV are event-side only and must be identical for the identical touchpoint
        self.assertEqual(strategic_score.tev, monitor_score.tev)

    def test_zero_budget_touchpoint_does_not_raise(self):
        cfg = ScoringConfig()
        tp = make_touchpoint(allocated_budget=0.0)
        client = make_client()
        score = score_touchpoint(tp, client, cfg)
        self.assertGreaterEqual(score.eri_raw, 0.0)


class PercentileRankTests(unittest.TestCase):
    def test_min_value_near_zero_percentile(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertLess(_percentile_rank(values, 1.0), 20.0)

    def test_max_value_near_hundred_percentile(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertGreater(_percentile_rank(values, 5.0), 80.0)

    def test_empty_list_returns_zero(self):
        self.assertEqual(_percentile_rank([], 1.0), 0.0)


class SampleDataPipelineTests(unittest.TestCase):
    def test_full_pipeline_runs_on_sample_data(self):
        touchpoints = load_touchpoints(os.path.join(SAMPLE_DIR, "touchpoints.csv"))
        clients = load_clients(os.path.join(SAMPLE_DIR, "clients.csv"))
        self.assertGreater(len(touchpoints), 0)
        self.assertGreater(len(clients), 0)

        scores = score_all(touchpoints, clients)
        self.assertEqual(len(scores), len(touchpoints))

        eri_index = rank_engagement_roi(scores)
        for s in scores:
            self.assertIn(s.touchpoint_id, eri_index)
            self.assertGreaterEqual(eri_index[s.touchpoint_id], 0.0)
            self.assertLessEqual(eri_index[s.touchpoint_id], 100.0)

    def test_every_touchpoint_resolves_to_a_known_client(self):
        touchpoints = load_touchpoints(os.path.join(SAMPLE_DIR, "touchpoints.csv"))
        clients = load_clients(os.path.join(SAMPLE_DIR, "clients.csv"))
        for tp in touchpoints:
            self.assertIn(tp.client_id, clients)


if __name__ == "__main__":
    unittest.main()
