# Pulse — Recommendation Memo
### Fix customer service before you fix anything else on the Swiggy roadmap
*Based on 5,000 Play Store reviews spanning 2026-06-14 to 2026-09-10 (87 days).*

## TL;DR

Customer service and refunds is the biggest driver of severe 1-star reviews on Swiggy's Play Store listing right now. Not late delivery. Not pricing. Not rider behaviour. On a stated churn-and-AOV model, it maps to roughly ₹23.2 lakh of forgone lifetime revenue in this sample alone, and the annualised, full-population number is meaningfully larger than that. It's the only theme in the taxonomy that leads on both review volume *and* severity, and it's the one I'd prioritise first.

## What the data says

I classified 5,000 reviews into eight themes (drawn uniformly at random from a wider 40,000-review pull). 1,502 of them landed in the seven "operational complaint" buckets. A few things fell out of that pretty quickly:

Customer service / refunds accounts for **28%** of the operational-complaint volume. That's the biggest single share by a comfortable margin. It also has the highest average severity score in the taxonomy — **4.37 out of 5**. The specific phrasing users reach for in this bucket is the vocabulary of churn: "no response for days", "refund never processed", "kept my money", "uninstalling".

The 1-star concentration tells the same story. 402 of the 1-star reviews fall in this theme. The next-worst is late delivery at 274. That's not a marginal gap — it's 96 more 1-star reviews than any other theme.

Applying the assumptions listed below, customer service / refunds maps to about **₹23.2 lakh** of projected lifetime revenue at risk over the sample window. That's a directional number, not an audited one, but the *ranking* it produces is what should drive the decision here.

## Why this jumps the queue

The obvious first fix for a delivery business is the delivery itself. Late orders are the visible failure, ops teams already measure them, and they show up in every NPS driver deck. So the natural instinct is to fix the SLA first.

The data pushes back on that instinct. Customers understand that occasional late orders happen and they rate accordingly — the severity of "delivery was late" reviews averages 4.07. What they *don't* forgive is the response when something goes wrong. A late order becomes a churn event only if the refund process compounds the frustration, and that's what the customer service theme's 4.37 severity is telling you.

Put differently: this is the theme with the highest "severity per review" leverage. Fixing it moves more churn per unit of engineering effort than fixing any of the ops-side issues that would normally get priority.

## Recommendation

Move the customer service and refunds overhaul ahead of the ops-side SLA work.

Three concrete first steps, ordered by how much of the observed complaint volume they'd blunt:

1. **Publish a refund SLA and expose the countdown in the app.** The recurring pattern in the severity-5 justifications isn't "refund refused" — it's "no one answered". A 48-hour resolution guarantee, with a visible in-app ticket status, would address the largest single sub-pattern in the 402 1-star reviews.
2. **Give people a way out of the chatbot after 24 hours.** A lot of the severity-5 language references chat-bot loops explicitly. A visible "talk to a human" escape hatch on any ticket over a day old would blunt the specific complaint that's driving the highest-severity reviews.
3. **Instrument the refund funnel.** Right now the only visibility on refund pain is what shows up in reviews, which is the trailing indicator. A dashboard of open-refund age plus refund-outcome tracking is the leading indicator equivalent. Cheap to build; would let the team see this coming next time.

Late delivery and pricing are the natural runners-up on the roadmap, in that order.

## The revenue-at-risk numbers

The revenue-at-risk figures are meant to rank themes, not to produce a rupee number anyone should quote back. Every input is a named constant at the top of [scripts/04_revenue_at_risk.py](../scripts/04_revenue_at_risk.py), so if you disagree with an assumption, change it there and re-run.

| Constant | Value | Source |
|---|---|---|
| `ASSUMED_CHURN_RATE` | 40% | Assumption. A 1-star review on a delivery app is a strong dissatisfaction signal. Industry rules of thumb range 25-60%; I picked the middle. |
| `ASSUMED_AVG_ORDER_VALUE_INR` | ₹600 | Rounded down from the Blinkit AOV of ~₹617 reported in Zomato's Q4 FY24 investor deck (quarter ending Mar-2024). Using it as a conservative proxy for Swiggy since I couldn't find a public Swiggy AOV number. |
| `ASSUMED_ORDER_FREQUENCY_MULTIPLIER` | 24 | Assumption. Assumes ~2 orders/month for an active user over a 12-month churn horizon → 24 forgone orders per churned user. |

Formula:

```
revenue_at_risk_inr =
    (1-star reviews for theme)
  * ASSUMED_CHURN_RATE
  * ASSUMED_AVG_ORDER_VALUE_INR
  * ASSUMED_ORDER_FREQUENCY_MULTIPLIER
```

## What this memo doesn't try to say

A few things I deliberately kept out, because the data doesn't support them:

- **Trend over time.** 87 days is enough to catch a spike, not enough to say anything about seasonality. The monthly-volume chart in the dashboard is a supporting view, not a headline.
- **Absolute revenue exposure.** The ₹23.2 lakh figure is derived from a 5,000-review sample, not from the full Swiggy user base. To turn it into a real annualised number I'd need the full-population review rate and the review-to-user ratio, and Play Store doesn't give me either. Rank on the theme, not the rupees.
- **Sub-segment cuts** by city, order type, or user tenure. Play Store review data doesn't carry those fields, so nothing I could say about them would be honest.
