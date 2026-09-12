# Pulse — Recommendation Memo
### Fix customer service before anything else on the Swiggy roadmap
*Based on 5,000 Play Store reviews spanning 2026-06-14 to 2026-09-10 (87 days).*

## TL;DR

**Fix customer service and refunds first.** It is the single largest driver of severe 1-star reviews on Swiggy's Play Store listing right now — bigger than late delivery, rider behavior, and pricing combined on a severity-weighted basis. On a stated set of churn/AOV assumptions, it maps to **≈ ₹23.2 lakh of forgone lifetime revenue** in the sample window alone; extrapolating the sample to full population volume, the annualized figure is materially larger. Nothing else in the eight-theme taxonomy comes close on both dimensions at the same time.

## What the data says

- **Theme volume:** Of 5,000 downsampled reviews (drawn uniformly at random from a wider 40,000-review pull), 1,502 landed in the seven "operational complaint" themes. Customer service / refunds accounts for **28 percent** of that operational-complaint volume — the largest single share.
- **Severity:** Customer service / refunds also has the **highest average severity score (4.37 / 5)**, meaning the specific complaints in this bucket are the ones users describe in terms most associated with churn: "no response for days", "refund never processed", "kept my money", "uninstalling".
- **1-star concentration:** 402 of the 1-star reviews in the sample fall into this theme. That is 96 more than the next-worst operational theme (late delivery, 274). The gap is not marginal.
- **Revenue at risk:** Under the assumptions stated below, that maps to **₹23.2 lakh** in projected lifetime revenue at risk over the sample. The exact rupee value is directional — the *ranking* is what should drive the roadmap decision, not the number itself.

## Why this theme should jump the queue

Late delivery and rider behavior are the operational themes most product teams naturally focus on first for a delivery business — they are the visible failures, they're operationally measurable, and they show up in NPS drivers. This dataset says something different: customers understand that occasional late deliveries happen and rate accordingly. What they **do not** forgive is the *response* when something goes wrong. A late order becomes a churn event only if the refund process compounds the frustration.

Concretely, the customer-service theme's severity 4.37 vs. late-delivery's 4.07 says two things:
1. Customers who complain about customer service are more likely to say they are leaving.
2. Fixing this theme has the highest "severity per volume" leverage in the whole taxonomy — bigger than the theme with more one-star reviews would have if severity were equal.

## Recommendation

Prioritize a **customer service and refunds overhaul** ahead of ops-side quick wins on the delivery SLA. Concrete first steps:

1. **Set and publish a refund SLA.** The recurring complaint pattern in the sample's justifications is not "refund refused" but "no one answered". A public 48-hour refund resolution guarantee, with visible in-app status, would address the largest fraction of the 402 one-star reviews.
2. **Route escalations to a human faster.** Many of the severity-5 justifications reference chat-bot loops. A visible "talk to a human" escape hatch on any ticket over 24 hours old would blunt the specific complaint driving churn.
3. **Instrument the refund funnel.** Right now Pulse only sees the aftermath in reviews. A dashboard of open-refund age plus refund-outcome tracking would let the team see the leading indicator instead of waiting for the trailing 1-star review.

Late delivery and pricing are the natural runners-up on the same list, in that order.

## Revenue-at-risk assumptions

The revenue-at-risk figures are directional, not audited. Each named constant lives at the top of [scripts/04_revenue_at_risk.py](../scripts/04_revenue_at_risk.py), so any of these can be changed and the analysis re-run in seconds.

| Constant | Value | Source |
|---|---|---|
| `ASSUMED_CHURN_RATE` | 40% | Assumption. A 1-star review on a delivery app is a strong dissatisfaction signal; industry rules-of-thumb range 25-60%. |
| `ASSUMED_AVG_ORDER_VALUE_INR` | ₹600 | Rounded down from the Blinkit AOV of ~₹617 reported in Zomato's Q4 FY24 investor deck (quarter ending Mar-2024). Used as a conservative proxy for Swiggy since a public number for Swiggy AOV was not sourced. |
| `ASSUMED_ORDER_FREQUENCY_MULTIPLIER` | 24 | Assumption. Assumes an active user places ~2 orders/month and the churn horizon is 12 months → 24 forgone orders per churned user. |

Formula:
```
revenue_at_risk_inr =
    (1-star review count for theme)
    * ASSUMED_CHURN_RATE
    * ASSUMED_AVG_ORDER_VALUE_INR
    * ASSUMED_ORDER_FREQUENCY_MULTIPLIER
```

## What's *not* in this memo (deliberate)

- **Trend over time**: the 87-day window is enough to check for a spike but not a seasonal trend. The monthly-volume chart in the dashboard is included as a supporting view, not a headline finding.
- **Absolute revenue at risk**: the ₹23.2 lakh figure is derived from a 5,000-review sample, not the full population of Swiggy reviews. Extrapolating requires knowing the full-population review rate and the review-to-user ratio, neither of which are in this dataset. Use the *ranking* to decide roadmap order, not the absolute rupees.
- **Sample-vs-population comparisons across sub-segments** (city, order type, user tenure): not available in Play Store review data.
