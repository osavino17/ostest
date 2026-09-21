# Client Engagement ROI Scoring Model

A scoring model for the ROI of client-facing events and sponsorships at an
investment / corporate banking business whose revenue is a **blend of flow
(recurring, transactional) and cyclical (deal-driven) revenue**.

## Why not attribution?

Last-touch or multi-touch attribution (crediting a touchpoint with a dollar
amount of resulting revenue) doesn't hold up in this business:

- Deal cycles run months to years, with dozens of touchpoints (banker calls,
  pitches, events, personal relationships) contributing to a single mandate
  — there's no clean causal link from "attended the Q1 forum" to "won the
  Q4 DCM mandate."
- Flow revenue (trading, treasury, transaction banking) isn't won in
  discrete deals at all; it's a function of ongoing relationship health.
- Compliance and information-barrier constraints make it inappropriate to
  tie individual events to specific deal outcomes in a system of record.

Instead, this model produces a **relative score**: given who actually
engaged with a touchpoint and how commercially important that client
relationship is right now, how much did this touchpoint likely contribute
to the relationship — compared to every other touchpoint in the portfolio?
That's enough to answer the questions coverage teams and event sponsors
actually have: *which events are working, which clients are we over- or
under-investing in, and where should next year's budget go* — without
claiming a causal, dollar-for-dollar return.

## Model structure

Every touchpoint (one event or sponsorship, for one client) is scored in
two independent halves, then combined:

```
Attendance Quality Score (AQS)  --\
                                    >--> Touchpoint Engagement Value (TEV)
Event Tier / Status            --/            (did the event work?)

Priority Tier + Intensity      --> Relationship Health Score (RHS)  --\
Mandates + Pipeline            --> Deal Readiness Score (DRS)        >--> Business Weight Score (BWS)
                     blended by client's flow/cyclical revenue mix --/    (does this client matter right now?)

Touchpoint Contribution Score (TCS) = TEV x BWS
Engagement ROI Index (ERI)          = percentile_rank(TCS / cost-normalized budget)
```

### 1. Touchpoint Engagement Value (TEV) — "did the event work?"

Built only from the touchpoint's own data, independent of any client's
commercial importance:

| Input (the "core data points") | Used in |
|---|---|
| `invited` / `accepted` / `attended` | Attendance Quality Score — full credit for attending, partial credit for accepting-then-no-showing (still a relationship signal, but weaker), zero for declining/no response |
| `attendee_seniority` | multiplies the attendance score — a C-suite attendee counts for more than an associate |
| `event_tier` ("status") | Event Tier weight — a flagship conference counts for more than a branding-only sponsorship |
| `allocated_budget` | **not** part of TEV — cost only enters later, in the ROI efficiency step, so we don't penalize a touchpoint for being expensive when judging whether it worked |

### 2. Business Weight Score (BWS) — "does this client matter right now?"

Built only from client business context, independent of any specific event:

| Input (the "business information") | Used in |
|---|---|
| `priority_tier` (strategic/core/developing/monitor) | Relationship Health Score |
| `relationship_intensity_12m` | Relationship Health Score |
| `active_mandates` | Deal Readiness Score |
| `pipeline_value` x `pipeline_stage` probability | Deal Readiness Score |

**The flow/cyclical blend**: each client's `flow_revenue_ltm` and
`cyclical_revenue_ltm` determine `flow_share` / `cyclical_share`. BWS is a
weighted blend of Relationship Health (flow lens) and Deal Readiness
(cyclical lens) using those shares — so a client who makes money mostly
from steady flow business is scored mostly on relationship warmth, while a
client who makes money mostly from episodic deals is scored mostly on live
mandates and pipeline, and mixed clients land in between automatically.

### 3. Combining them

`TCS = TEV x BWS` — a touchpoint only scores well if the event itself
landed well *and* the client is commercially important right now. A
flagship event attended by a low-priority client, or a strategic client's
no-show, both correctly score low.

`ERI` divides TCS by the touchpoint's cost relative to a benchmark cost for
its tier (so a $2,500 roundtable and a $9,000 flagship dinner are compared
on efficiency, not absolute spend), then percentile-ranks the result across
the whole portfolio into a 0–100 index.

## Reports

Running the model produces three CSVs:

- **`touchpoint_scores.csv`** — every touchpoint, ranked by Engagement ROI
  Index. Use to identify which specific engagements delivered the most
  value per dollar.
- **`client_alignment.csv`** — per client, total contribution score vs.
  business-weight percentile, with an `alignment_flag` calling out clients
  who are **over-invested** (getting more engagement spend than their
  current commercial importance justifies) or **under-invested**
  (important clients/deals not getting enough engagement attention).
- **`event_effectiveness.csv`** — per event/sponsorship, averaged across
  all attending clients. Use to inform next year's event and sponsorship
  budget allocation.

## Usage

```bash
python3 run_model.py \
    --touchpoints sample_data/touchpoints.csv \
    --clients sample_data/clients.csv \
    --out-dir out/
```

No external dependencies — stdlib only.

### Bring your own data

Replace `sample_data/touchpoints.csv` and `sample_data/clients.csv` with
real data in the same schema (see `roi_model/models.py` for field
definitions). One row per (touchpoint, client) pair in the touchpoints
file; one row per client in the clients file, refreshed on whatever cadence
your CRM/pipeline data allows (e.g. monthly).

### Tuning the model

All weights, seniority/tier maps, and normalization caps live in
`roi_model/scoring.py` (`ScoringConfig` and the module-level maps at the
top of the file) — deliberately kept separate from the scoring formulas so
business/quant stakeholders can retune the model (e.g. how much weight
pipeline value gets vs. active mandates, what counts as "high intensity")
without touching logic.

## Project layout

```
roi_model/
  models.py     Touchpoint / ClientContext data classes
  scoring.py     scoring formulas + ScoringConfig (the tunable weights)
  pipeline.py     CSV I/O, aggregation, report writers
sample_data/      example touchpoints.csv / clients.csv
tests/            unit tests for every scoring function
run_model.py       CLI entry point
```

## Testing

```bash
python3 -m unittest discover -s tests -v
```
