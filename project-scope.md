# Pulse — App Review Mining for Churn Root-Cause Analysis

## Purpose

A portfolio project for non-tech resume applications (Business Analyst, Product/Program Management, Consulting, non-trading Finance). The goal is a project that is buildable in a contained timeframe, fully defensible in an interview, and answers a real business question rather than reproducing a tutorial dataset.

## Business question

Which specific operational issues drive negative reviews of a quick-commerce app, and how much revenue is at risk from each issue if left unaddressed?

## Target app

Blinkit (Play Store). Swappable for Zomato or Swiggy Instamart if review volume or data quality is better for one of them; check volume before committing.

## Data source

Real, current Play Store reviews, pulled directly rather than sourced from a pre-cleaned public dataset.

- **Tool**: `google-play-scraper` (Python, no auth required, no cost)
- **Volume**: 3,000-5,000 reviews
- **Time window**: last 12-18 months, to support trend analysis over time
- **Fields captured**: review text, star rating, date, thumbs-up count

## Complaint taxonomy

Fixed categories, defined before classification begins:

1. Late/delayed delivery
2. Stockouts / item unavailability
3. Pricing / hidden charges
4. App bugs / payment failures
5. Rider / delivery-person behavior
6. Customer service / refunds
7. Product quality
8. Other / positive

## Classification pipeline

- **Model**: Groq API, `llama-3.3-70b-versatile` (fallback to `llama-3.1-8b-instant` if rate limits are hit)
- **Output per review**: category (from the fixed taxonomy above), severity score (1-5), one-sentence justification, returned as structured JSON
- **Processing**: batched, with results written to a local file or SQLite table after each batch, so a rate-limit error or crash does not require re-running completed work

## Business impact quantification

- Aggregate: complaint-theme volume over time, theme share of all 1-2 star reviews, severity-weighted score per theme
- Revenue-at-risk estimate: requires a stated assumption, since real GMV/order-volume data is not available. Example structure: "assuming X% of 1-star reviewers churn, and an average order value of ₹Y based on [cited public estimate], the [top theme] represents ₹Z at risk." The assumption must be stated explicitly in the final deliverable, not buried in a footnote.

## Deliverables

1. **Dashboard** (Power BI or Tableau): complaint-theme trend lines over time, severity breakdown, rating distribution by theme
2. **One-page recommendation memo**: ranks which operational issue to fix first, backed by the estimated revenue at risk

## Open decision

Whether to stop at "identified and quantified the biggest driver of dissatisfaction" (base scope) or extend to a before/after impact projection simulating the effect of fixing the top issue (extension scope, adds real build time). Recommendation: build the base scope first, add the projection only if time remains before the resume needs to be finalized.

## Resume skills this project is meant to demonstrate

SQL (aggregation and cohort-style queries over classified review data), Power BI/Tableau (dashboard build), applied NLP/classification (reused from prior ML project work, redirected at a business question), and structured business recommendation writing.
