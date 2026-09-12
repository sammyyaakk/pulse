# Pulse — Lessons Learned

A running log of everything that went wrong while building this project, how we recovered, and — the point of the document — what a rebuild should do differently on day one.

Structured for interview defense: every entry is something the author can talk about honestly ("we hit X, this is what X actually is, this is what I'd do next time"). Nothing is hidden or spun as intentional.

---

## 1. The brief's target app couldn't support the brief's time window

**What went wrong.** The brief specified Blinkit, 3,000-5,000 reviews, spanning the last 12-18 months. The first scrape completed in ~6 minutes and returned 5,000 reviews spanning **three days**. Blinkit generates roughly 900 Play Store reviews per day; newest-first pagination hit the 5k budget long before it reached the 18-month cutoff. Twelve months of coverage at 900/day would need ≈328,000 reviews — infeasible on the free tier and beyond Play Store's paginated review depth in most cases.

**How we recovered.** Probed Zomato and Swiggy at 500 reviews each to measure their review firehose:
- Blinkit: ~900/day → 5k covers ~5.6 days
- Zomato: ~585/day → ~8.5 days
- Swiggy: ~335/day → ~14.9 days

Even Swiggy couldn't span 12 months at 5k reviews. Solution: **scrape wide, downsample narrow.** Pulled 40,000 Swiggy reviews (covered 87 days), then uniform-random downsampled to 5,000 for classification. Uniform-random preserves per-day density, so the resulting trend charts reflect real review volume rather than a flat sampling artefact.

**What we should have done from the start.**
- **Probe daily review rate for the target app before committing to a time window.** A 30-second `count=500` call would have shown the mismatch immediately, before writing any pipeline code.
- **Treat "3,000-5,000 reviews + 12-18 months" as two constraints that can conflict, not one goal.** State the tradeoff explicitly in the scope doc — either can be tightened, but not both without an app that has low daily review volume.
- **Design for downsampling as a first-class step, not a workaround.** The pipeline benefits from separating "the raw pull" (immutable checkpoint) from "the classification sample" — Phase 1's split into `raw_reviews_full.csv` and `raw_reviews.csv` reflects this.

---

## 2. The brief's model IDs had been deprecated by launch time

**What went wrong.** The brief specified `llama-3.3-70b-versatile` primary and `llama-3.1-8b-instant` fallback. Every classification call returned HTTP 404 — Groq had deprecated the entire Llama 3.x family well before we ran the pipeline. First 40+ calls burned before we noticed the pattern in the log.

**How we recovered.** Called Groq's `client.models.list()` to see what was currently available and swapped in the OpenAI open-weight models (`gpt-oss-120b` and `gpt-oss-20b`) that supported the same `response_format={"type":"json_object"}` behavior.

**What we should have done from the start.**
- **Never trust model IDs from a brief without a live probe.** The scaffolding step should include a one-line "does the primary model actually respond?" check that runs before the first real batch.
- **Store model IDs as config, not as literals scattered through code.** We got this right in `scripts/config.py` — it made every subsequent model rotation a one-line edit.
- **Log the actual model used per row.** The `model_used` column in the SQLite table saved us later when we needed to audit exactly which model classified what. Design for provenance from the start.

---

## 3. API key placed in the wrong file — and the wrong file wasn't gitignored

**What went wrong.** The user pasted the Groq API key into `.env.example` instead of `.env`. Two failures compounded:

1. `.env.example` isn't gitignored — only `.env` is. Had this project been under `git init` with a remote, one push would have leaked the key.
2. Since the project lives under OneDrive, the file with the key was syncing to Microsoft's cloud during the ~5-minute window it existed on disk. OneDrive's file-version history retains that snapshot for ~30 days on personal accounts.

**How we recovered.** Renamed `.env.example` → `.env`, discussed the exposure honestly (no git history had the key, but OneDrive version history likely did), rotated the key at `console.groq.com/keys` as insurance.

**What we should have done from the start.**
- **Don't ship a `.env.example` at all if the "example" is just `KEY=your_key_here`.** The naming is confusingly close to `.env`; users edit the wrong one. Either put the placeholder in the README and delete the example file, or add `.env.example` to `.gitignore` too.
- **Never build dev projects with real secrets inside OneDrive / Dropbox / iCloud sync roots.** Move the project out of the sync root (e.g. `C:\dev\`) or exclude it from sync via the client's per-folder exclude list.
- **`git init` on day one, even for a solo portfolio project.** History is useful and it also gives you a concrete answer to "is this key in a commit?"
- **Consider a `.env.local` naming convention** (many stacks use this) — clearer distinction from `.env.example` and less accident-prone.

---

## 4. Free-tier rate limits were massively under-estimated

**What went wrong.** The initial ETA I quoted was ~60 minutes for the full 5,000-review classification. Reality: the run took a full day plus, spanned six models, and required four full rotation cycles. Every early estimate was wrong by an order of magnitude, and each was based on the smoke-test rate (0.75s/request) rather than the sustained rate that free-tier RPM+TPM limits actually permit.

Sustained observed rates by model on Groq's free tier:
- `gpt-oss-120b`: 8-17 requests/min
- `gpt-oss-20b`: 15-28 requests/min
- Qwen and safeguard variants: similar bands

Beyond RPM, there is also a daily TPD (tokens per day) ceiling per model that only manifests after hours of throughput. When it hits, both the primary and fallback models start returning 429s in tandem — that's the signal that the bucket is truly exhausted, not just throttled per-minute.

**How we recovered.** Rotated across independent per-model rate-limit buckets. Groq caps rate limits *per model*, not per account, so switching between model families gives a fresh bucket. We cycled: gpt-oss-120b → gpt-oss-20b → Qwen 3.8 → Qwen 3.6 → gpt-oss-safeguard-20b → back to gpt-oss-120b as the earlier buckets partially reset. The classifier is idempotent (skips reviews already in the SQLite table on restart), so each rotation was: kill classifier → edit `config.py` → relaunch → resume from where it stopped.

**What we should have done from the start.**
- **Quote sustained rate, not smoke-test rate.** A 20-review smoke test finishes before RPM caps engage. Estimate ETA from `RPM_ceiling * 60 * hours_of_daily_budget`, not from `smoke_seconds / smoke_reviews`.
- **Design for model rotation from day one.** Instead of hardcoding `PRIMARY_MODEL` and `FALLBACK_MODEL` as two constants, use a *chain* — `MODEL_CHAIN = [(primary, fallback), (primary2, fallback2), …]` — and let the classifier itself advance the pointer when it sees repeated "rate-limited on both" failures over a rolling window. Would have removed the need for manual kill/edit/relaunch cycles.
- **Batch multiple reviews per prompt.** One API call that classifies 5-10 reviews at once cuts RPM usage 5-10x, at the cost of a stricter JSON output contract and a slightly more brittle parser. Would have finished the whole 5k in a single quota window.
- **Use async concurrency to sit at the RPM ceiling instead of below it.** A sequential for-loop with `time.sleep(0.5)` between calls stayed below the 30 RPM cap by design. An asyncio semaphore of 20-30 workers would push right up to the ceiling.
- **Reserve a small budget of paid tier if this had a real deadline.** Groq's dev tier ($5 loads a lot of quota) lifts RPM to 1000+; the whole pipeline would have completed in minutes instead of a day.

---

## 5. Silent fallback masked a real problem

**What went wrong.** The classifier catches `RateLimitError` on the primary model and silently retries on the fallback. That behavior is intended, but the `log.warning` line calling out the fallback got filtered out by the `| grep -v "HTTP Request"` pipe I was using in the terminal, and buried in the sheer volume of the run's log output otherwise. Result: during the "120b run", many rows were actually classified by 20b as silent fallbacks, and I only noticed when the `model_used` column showed a suspicious ratio.

**How we recovered.** Added the model breakdown to the progress-check script (`by_model` in the last 10-minute window). Made the fallback ratio visible on every check.

**What we should have done from the start.**
- **Report fallback usage in the summary, not just as a debug warning.** A one-line "primary hit rate-limit N times, fallback used M times" per batch write would have surfaced the pattern immediately.
- **Provenance columns are cheap.** The `model_used` column let us audit the mix retroactively. Also add `attempt_count` and `latency_ms` — those help debug throttling patterns without needing raw log parsing.

---

## 6. Progress-check query had a rate-calculation bug

**What went wrong.** The check anchored its 10-minute window on `MAX(classified_at)`:
```python
last = datetime.fromisoformat(rows[-1][0])
cutoff = last - timedelta(minutes=10)
recent = [r for r in rows if datetime.fromisoformat(r[0]) >= cutoff]
rate = len(recent) / (last - first_in_recent).seconds
```
Because the classifier writes 25 rows in one SQLite commit (BATCH_SIZE=25), those 25 rows share timestamps within ~1 second. The "10-minute window" caught 25 rows all landing in 1 second, computed `25 / 1s * 60s = 1500 reviews/min`, and reported "ETA: 2 minutes." Meanwhile the classifier was actually stuck at ~2 reviews/min real throughput. **Every check for hours reported healthy numbers while the run was stalled.**

**How we recovered.** Rewrote the check (`scripts/check_progress.py`) to anchor the window on wall-clock now, and always divide by the fixed 10-minute window length rather than by the span between the first and last row inside it. Corrected the failure-delta calculation to use a persistent state file so we could measure "new failures since last check" across cron fires. Also lowered the alert thresholds to trigger on ≥1 failure/minute average and any sustained rate below 8/min.

**What we should have done from the start.**
- **Anchor rate windows on wall-clock, always.** "Reviews per minute over the last 10 minutes" means `count_in_last_10_minutes / 10`, not `count_in_burst / burst_duration`. This mistake is one that shows up in dashboards and cron logs everywhere; the fix is trivial and matters a lot.
- **Test the monitoring code as carefully as the pipeline code.** A five-review dry-run of the check script with a fake DB would have shown the burst-rate artefact immediately.
- **Log deltas, not just totals.** For anything counted (failures, retries, tokens spent), record a checkpoint each time so "how much changed since the last check" is a single subtraction.

---

## 7. Over-promised on "automatic" progress checks

**What went wrong.** Set up a session-only cron job to fire the progress check every 10 minutes and treated it as "auto-checking every 10 minutes." What was missed: session-scoped scheduled tasks only fire when the driving process is actively idle. If the session is suspended or the terminal is closed between check windows, nothing fires. Combined with the bugged check query above, several stalls slipped past without a real check happening.

**How we recovered.** Killed the session-only cron and switched to running `check_progress.py` explicitly on demand. Set expectations for the automation to match what it can actually guarantee.

**What we should have done from the start.**
- **Understand the failure modes of the automation before promising it.** In-process schedulers in interactive tools are best-effort, not guaranteed. State that up front.
- **For anything that must fire on a real schedule, use an OS-level scheduler** (Windows Task Scheduler, or a plain `while true; do python check_progress.py; sleep 600; done` in a second terminal). Both are more reliable than an in-process scheduled task tied to an interactive REPL.

---

## 8. Silent HTTP 429 retries wasted TPD budget

**What went wrong.** Every rate-limit hit triggered up to 4 tenacity retries with exponential backoff. Those retry calls each consumed a small amount of quota even when they failed. On a stalled bucket, we were re-hitting the same failing endpoint and burning a fraction of the daily budget on requests that would never succeed.

**How we recovered.** Kept the retry policy (it does help on true transient failures) but rotated to a different model chain as soon as failures started to compound, which stopped the retry-storm on an exhausted bucket.

**What we should have done from the start.**
- **Distinguish transient errors from steady-state errors in the retry policy.** A 429 with `Retry-After: <big>` is not a "wait 2 seconds and try again" case — it's an "abandon this model" case. `tenacity` supports conditional retry predicates; a check on the retry-after header would have short-circuited retries against a truly exhausted bucket.
- **Cap the daily 429 budget per model.** If a model returns >N 429s in a rolling window, mark it dead for the day and skip it entirely.

---

## 9. No git repo, and the project lived in OneDrive

**What went wrong.** The project was created inside `C:\Users\<user>\OneDrive\Desktop\projects\pulse` and never `git init`'d during the build. Two consequences:
- No local version history for code — every `config.py` edit during model rotations was ephemeral, and I couldn't roll back to a prior state cleanly.
- OneDrive was continuously syncing every intermediate file, including the SQLite database, the raw reviews CSV, and (briefly) the misplaced API key file.

**How we recovered.** Nothing broke because of either issue, but both added risk that was avoidable.

**What we should have done from the start.**
- **`git init` and an initial `git add .` commit on day one.** Every rotation of `PRIMARY_MODEL` would then be a real commit — useful for the interview-story timeline and for rolling back a misconfiguration.
- **Keep dev projects out of cloud-sync roots.** `C:\dev\pulse\` avoids OneDrive syncing every intermediate file. If the project must live in the sync root, exclude the folder from OneDrive via the client's "Choose folders" or "Exclude" settings — the sync client re-scans on save otherwise.

---

## 10. Windows console encoding tripped over emoji in reviews

**What went wrong.** Play Store reviews are full of emoji, Devanagari, Kannada, Arabic, and other non-Latin scripts. Windows' default console codec is `cp1252`, which cannot encode most of those characters. Every attempt to print a sample review to the terminal raised `UnicodeEncodeError`, even though the CSV file itself was written in UTF-8 correctly.

**How we recovered.** Ran Python with `-X utf8` on every invocation, which forces the interpreter into UTF-8 mode for stdin/stdout regardless of the console codec.

**What we should have done from the start.**
- **Set `PYTHONUTF8=1` in the environment (or in a `.env` file the pipeline reads).** Same effect as `-X utf8` without needing to remember the flag each time.
- **Never assume the terminal codec matches the file codec on Windows.** Files can be UTF-8 while the terminal is cp1252; that's the default state on Windows 10/11.

---

## 11. Failure log had no timestamps

**What went wrong.** The classifier wrote failures as `{"review_id":..., "text":..., "reason":...}` — no `logged_at` field. When 200+ failures appeared in a check window, we couldn't tell whether they happened over the last 5 minutes (fast collapse — rotate immediately) or over the last 5 hours (slow bleed — hold and see). The `check_progress.py` state file worked around this by tracking the failure-count delta between checks, but that only tells us "how many since last check", not "when they happened".

**How we recovered.** Persisted the failure count in `logs/check_state.json` between check runs so we could report a delta.

**What we should have done from the start.**
- **Every log line gets a timestamp.** Same for every DB row. Non-negotiable.
- **JSONL log entries are ~free to enrich.** `{"logged_at": <iso8601>, "review_id": ..., "reason": ...}` gives us everything we need to compute failure velocity without a sidecar state file.

---

## Meta-lessons

Three that come up across most of the individual incidents:

1. **Probe before committing.** The Blinkit review-rate mismatch, the deprecated Llama models, the free-tier RPM assumption — every one of these would have been caught by a 30-second probe before the pipeline was built to depend on it. "Cheap probes upfront" beats "expensive rewrites later" almost every time.
2. **Measure the thing you're claiming.** Every ETA I quoted was wrong until the progress check was rewritten to measure what it actually claimed to measure. Same principle applies to review counts, model choice, revenue-at-risk numbers — always sanity-check that the reported figure is the figure you meant to compute.
3. **Design for provenance from day one.** The `model_used` column, the `raw_reviews_full.csv` checkpoint, and the SQLite idempotency were all things we happened to build in for other reasons — but they saved the run when we had to rotate models mid-flight. If a downstream consumer might ever ask "which model / which pull / which run produced this row", the answer should be embedded in the data, not reconstructed from git history.
