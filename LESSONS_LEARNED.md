# Pulse — Lessons Learned

An honest log of what went sideways while I was building this. I'm keeping it because a project without a postmortem is just a demo. I'd rather be able to talk about the mistakes in an interview than pretend the build was smooth.

---

## 1. The brief asked for a time window the target app couldn't fit

I set up the scrape thinking 5,000 reviews would give me the last year and a half. First run finished in six minutes and gave me exactly three days. Blinkit gets somewhere near 900 Play Store reviews a day, and `google-play-scraper` returns them newest-first with no date filter. So the 5k budget was gone before the scraper got anywhere close to the 18-month cutoff.

To actually cover 12 months I would have needed ~328,000 reviews, which is beyond what Play Store's continuation token will paginate through in practice.

I probed Zomato and Swiggy the same way to see if either behaved better:

| App | Rate (reviews/day) | 5k reviews spans |
|---|---|---|
| Blinkit | ~900 | 5.6 days |
| Zomato | ~585 | 8.5 days |
| Swiggy | ~335 | 14.9 days |

Even Swiggy couldn't do 12 months at 5k. The fix I landed on was "scrape wide, downsample narrow": pull 40,000 Swiggy reviews (which covered 87 days) and uniform-random downsample to 5,000 for classification. Uniform-random matters because it preserves per-day density, so the trend charts reflect the real review volume instead of a flat sampling artefact.

What I'd do next time:

- Actually check the daily review rate for the app before I write the scraper. A 30-second `count=500` call would have told me this immediately.
- Treat "5,000 reviews" and "12-18 months" as two constraints that can conflict, not one goal. State the tradeoff up front in scope.
- Build the "downsample after wide scrape" step as a first-class part of Phase 1, not something I bolted on when the first constraint failed.

---

## 2. The models named in the brief had been deprecated by launch time

The brief specified `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`. Every call returned HTTP 404 before I figured out that Groq had deprecated the whole Llama 3.x family before this project ran. I burned about 40 real calls and a lot of time watching an unhelpful error log before I noticed the pattern.

Fix was straightforward: `client.models.list()` to see what was actually available, then swap in the OpenAI open-weight family (`gpt-oss-120b` and `gpt-oss-20b`), which supports the same JSON response format.

Takeaways:

- Model IDs in a brief are just suggestions. Probe them live before writing code that depends on them. My scaffolding step now includes a "does the primary model actually respond?" ping.
- Store model IDs in one config file. I got this right by accident, and it saved me a lot of pain later when I ended up cycling through six different models.
- Record the model that produced each row. The `model_used` column in the SQLite table was originally just diagnostic, but it turned into the single most important design decision in this project. See lesson 4.

---

## 3. I put the API key in the wrong file, and the wrong file wasn't gitignored

I pasted the Groq key into `.env.example` instead of `.env`. Two things compounded:

1. My `.gitignore` was excluding `.env` but not `.env.example`. If this project had already been initialised as a git repo with a remote, one push would have leaked the key to a public URL.
2. The project sits inside OneDrive. During the ~5 minutes the misplaced key sat on disk, OneDrive was almost certainly syncing that version to Microsoft's cloud. OneDrive keeps file-version history for around 30 days on personal accounts, so even after I renamed the file, the earlier version isn't easy to wipe.

Recovery was fine: rename the file, admit the exposure honestly, rotate the key. Nothing bad actually happened.

What I'd change:

- Don't ship a `.env.example` at all if the "example" is a placeholder. The naming is dangerous — one character difference from `.env`, and people (me) will edit the wrong one. Either put the placeholder in the README and delete the file, or add `.env.example` to `.gitignore` too.
- Keep dev projects with secrets outside cloud sync roots. OneDrive silently caching a copy of a leaked key is the worst kind of exposure because you can't see it.
- `git init` on day one, even for a solo project. Not because I'll push it, but because I want an answer to "is this key in my history?" that isn't "let me look through my OneDrive backups."

---

## 4. I under-estimated Groq's free-tier rate limits by a factor of about twenty

I quoted the user an ETA of ~60 minutes for the full classification. The actual run took most of a day, spanned six models, and required four full rotations across model families. Every early estimate I gave was wrong by an order of magnitude, and each one was based on a 20-review smoke test where the RPM cap never kicked in.

Here's what the sustained rates actually looked like on the free tier:

| Model | Sustained (req/min) |
|---|---|
| gpt-oss-120b | 8-17 |
| gpt-oss-20b | 15-28 |
| qwen 3.8-27b | ~25 |
| everything else | somewhere in that band |

The nasty part isn't RPM. It's TPD — the daily token cap per model. RPM you notice immediately; TPD only shows up after hours of throughput, and when it hits, the primary and fallback models start 429-ing at the same time. That's the tell that a bucket is truly exhausted and not just throttled per-minute.

The way I actually finished the run was by rotating across models. Groq caps rate limits per-model, not per-account, so switching from `gpt-oss-120b` to `qwen 3.8-27b` gives a fresh bucket for the day. The rotation ended up being:

`gpt-oss-120b → gpt-oss-20b → qwen 3.8-27b + 3.6-27b → gpt-oss-safeguard-20b → back to gpt-oss-120b (partially recovered) → gpt-oss-20b + qwen 3.8-27b (mop-up)`

Because the classifier is idempotent (skips reviews already in the SQLite table), each rotation was just: kill the process, edit `config.py`, restart, resume from wherever it stopped. No lost work per rotation, just a lot of wall clock.

Things I'd do differently on a rebuild:

- Quote sustained rate, not smoke-test rate. RPM caps don't engage in the first 20 requests. Estimate ETA from `RPM_ceiling × 60 × hours_of_daily_budget`, not from `smoke_seconds / smoke_count`.
- Design for model rotation from day one. Instead of `PRIMARY_MODEL` and `FALLBACK_MODEL` as scalar constants, use a chain — `MODEL_CHAIN = [(primary, fallback), (primary2, fallback2), ...]` — and have the classifier advance the pointer itself when both models in the current pair start 429-ing over a rolling window. Would have removed the manual kill/edit/restart loop entirely.
- Batch multiple reviews per prompt. One call that classifies 5-10 reviews cuts RPM usage by the same factor. Costs you a stricter JSON contract and a more brittle parser, but on a free tier it's worth it.
- Use async concurrency to sit at the RPM ceiling instead of under it. My sequential loop with `time.sleep(0.5)` was pacing itself well below the 30 RPM cap by construction. An asyncio semaphore of 20-30 workers would push right up against the ceiling and pull the wall-clock down 3-4x.
- If a real deadline mattered, pay Groq $5 for dev tier. RPM goes to 1000+ and the whole pipeline finishes in minutes. I could not talk myself into this because "free tier" was part of the brief, but for real work the tradeoff is trivial.

---

## 5. The classifier was silently falling back and I didn't notice for hours

The classifier catches `RateLimitError` on the primary model and quietly retries on the fallback. That's intentional. The problem was that the `log.warning` line that would have told me it happened kept getting eaten by the `| grep -v "HTTP Request"` filter I was using to keep the terminal readable, and buried underneath everything else in the log file.

So during the "120b run," a chunk of the rows were actually being classified by 20b as silent fallbacks. I only caught it when I ran a `SELECT model_used, COUNT(*) GROUP BY model_used` and saw a suspicious ratio.

I ended up adding a per-check breakdown of which models were used in the last window, so any drift is visible at a glance. That should have been in the check script from the start.

Rule of thumb I'll take forward: if the code does something you'd want to know about, don't only log it as a warning. Surface it in the summary too. Warnings get filtered.

---

## 6. My progress check was measuring the wrong thing

The check script was reporting "rate: 1500 reviews/min, ETA 2 minutes" while the classifier was actually stuck at 2 reviews/min. This went on for hours before I noticed. It's the bug I'm most embarrassed about, because the fix is one line.

The buggy calc looked like this:

```python
last = datetime.fromisoformat(rows[-1][0])
cutoff = last - timedelta(minutes=10)
recent = [r for r in rows if datetime.fromisoformat(r[0]) >= cutoff]
rate = len(recent) / (last - first_in_recent).seconds
```

The classifier writes 25 rows per SQLite commit (BATCH_SIZE=25), and those 25 rows all get roughly the same timestamp. So "the last 10 minutes" was catching 25 rows all landing within one second, dividing by that one second, and reporting 1500/min. Meanwhile the real cadence was one batch every hour.

The fix is to anchor the window on wall-clock now, and always divide by the fixed window length:

```python
cutoff = datetime.utcnow() - timedelta(minutes=10)
count = rows_with_classified_at_after(cutoff)
rate_per_min = count / 10   # always divide by 10 minutes, not by burst duration
```

That's it. Once I made that change, the check started reporting the real rate, the alerts started firing correctly, and I could actually see the stalls that had been quietly happening.

Two takeaways:

- Rate windows should always anchor on wall-clock time, not on data timestamps. "Reviews per minute over the last 10 minutes" means `count_in_window / 10`, full stop.
- Test the monitoring code with the same care as the pipeline code. A five-review dry run with a mock DB would have shown the burst-rate artefact instantly.

---

## 7. I over-promised what the "auto-check every 10 minutes" could do

I told the user I'd set up an automated check that would fire every 10 minutes and alert if the classifier stalled. What I actually set up was a session-scoped scheduled task, which only fires while the driving process is idle and alive. Between messages, if the session was suspended, nothing ran.

Combined with the buggy check from lesson 6, several hours-long stalls slipped past without a single real check firing. From my side it looked like the automation was working; from reality's side the automation had barely run.

I killed the session-scoped scheduler and just started running the check explicitly when I wanted a number. Boring but honest.

If I had needed a truly automated monitor, the right tool would have been an OS-level scheduler (Windows Task Scheduler) or the world's simplest polling loop in a second terminal:

```bash
while true; do python check_progress.py; sleep 600; done
```

Both would have kept running whether the assistant session was awake or not. The lesson: know what "automatic" means for the specific tool you're using before you promise it to anyone.

---

## 8. Retrying against an exhausted bucket wasted quota

Every rate-limit response triggered up to 4 tenacity retries with exponential backoff. That's fine for a transient blip, but a rate-limited *bucket* is not transient — it's a steady state that lasts until the daily quota window rolls over. Retrying against it just burns fractional quota on requests that will never succeed, and each retry counts toward TPM even when it returns nothing useful.

I kept the retry policy (it does help on true transients) but leaned on rotation to escape a truly stuck bucket rather than sitting on it.

For a rebuild I'd tighten the retry logic:

- Distinguish "429 with a small `Retry-After`" (worth waiting on) from "429 with a large `Retry-After`" (bucket is dead, abandon it).
- Cap the daily 429 budget per model — if a model returns more than N 429s in a rolling window, mark it dead-for-the-day and skip it. `tenacity` supports conditional retry predicates, so this is a small change.

---

## 9. No git repo, and the project lived under OneDrive

Two things I should have set up on day one but didn't:

- **`git init`**. During the model rotations I was editing `config.py` a lot, and every edit was ephemeral — no history, no easy rollback. It also meant I had no clean way to answer "is this leaked key in a commit?" (see lesson 3). Fifteen seconds of work up front.
- **A project location outside OneDrive**. Sync is aggressive and constant. Every intermediate CSV, every SQLite write, every `.env` change was going to Microsoft's cloud. Nothing bad came of it, but it's the kind of thing that's zero cost to prevent and non-trivial to unwind after the fact.

Neither of these broke anything, but both added risk that was avoidable.

---

## 10. Windows terminal codec choked on emoji

Play Store reviews are full of emoji, Devanagari, Kannada, Arabic, and a lot of other non-ASCII. Windows' default console codec is `cp1252`, which can't encode any of that. So every time I tried to print a review to the terminal, I got a `UnicodeEncodeError`, even though the CSV file itself was written in UTF-8 correctly.

The workaround is `python -X utf8 my_script.py`, which forces UTF-8 mode for stdin/stdout regardless of what the console thinks. I typed that a lot.

The permanent fix is `PYTHONUTF8=1` as an environment variable (or in the `.env` file that everything else already reads). Same effect, without having to remember the flag each time.

Reminder to myself: on Windows, file codec and terminal codec are two separate settings. Files being UTF-8 tells you nothing about whether the terminal can display them.

---

## 11. My failure log had no timestamps

The classifier logged failures as `{"review_id": ..., "text": ..., "reason": ...}` — no `logged_at` field. When 200+ failures showed up in a check window, I couldn't tell whether they'd happened in the last five minutes (a fast collapse — rotate immediately) or over the last five hours (a slow bleed — hold and see). That's exactly the information the log is supposed to give me.

I worked around it by persisting the failure count between check runs in a state file, so at least I could report a delta. But that only tells me "how many since the last check," not "when specifically they happened."

Not-negotiable rule for next time: every log line gets a timestamp. Same for every DB row. JSONL entries are effectively free to enrich — one extra key, no performance cost, and it prevents this exact class of confusion.

---

## Three patterns that showed up more than once

Skimming back through this list, the same handful of mistakes keep showing up:

**I trusted the brief without probing.** The Blinkit review rate, the deprecated Llama models, the free-tier RPM number — every one of them would have been caught by a 30-second live check before I committed to the plan. Cheap probes upfront beat expensive rewrites later.

**I claimed things I wasn't measuring.** The 60-minute ETA, the 1500/min rate, the "auto-checks every 10 minutes" — none of those were true, and I couldn't have known they were false without stopping to ask "am I actually measuring what I think I'm measuring?" I want that question to be reflexive next time.

**Provenance columns saved the run.** The `model_used` column, the split between `raw_reviews_full.csv` and `raw_reviews.csv`, the SQLite idempotency — I built all of them for their obvious first-order reasons, but they turned out to matter because they let me rotate models mid-run without losing my place or fudging the audit trail. If a downstream reader might ever ask "which pull / which model / which run produced this row," bake the answer into the data. Cheap now, invaluable later.
