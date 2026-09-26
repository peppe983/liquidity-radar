# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Steps 1–3 of the 6-step roadmap are implemented and step 5 is in progress.

- **Step 0 (research)** — done: [doc/research.md](doc/research.md) (Korean).
- **Step 1 (data pipeline)** — done: `update.py` fetches FRED series,
  normalizes units, aligns to business days, writes `latest.json`.
- **Step 2 (judgment logic)** — done: `assess.py` computes the SOFR-IORB spread
  + Z-scores, pulls SRF usage from the NY Fed API, grades pressure on
  a four-level ladder, applies the pressure-first rule, and decomposes what
  drove the liquidity change. Thresholds are validated by `backtest.py`.
- **Step 3 (MCP server)** — done: `mcp_server.py` exposes seven tools over MCP
  (current state, series lookup, per-date assessment, decomposition, stress
  search, indicator glossary). It wraps `update.py`/`assess.py` rather than
  duplicating them, and caches the fetched DataFrame for an hour because a cold
  FRED pull takes ~10s. Registered locally with
  `claude mcp add liquidity -- <venv>/bin/python <repo>/mcp_server.py`.
- **Step 5 (dashboard)** — in progress, done ahead of step 4 so the news
  output has somewhere to live. Split into 5-0 repo on GitHub
  (`peppe983/liquidity-radar`, public) ✅, 5-1 `history.json` ✅, 5-2 GitHub
  Actions auto-update (`.github/workflows/update.yml`) ✅, 5-3 dashboard page
  (designed first in Claude Design from [doc/design-brief.md](doc/design-brief.md), then built),
  5-4 GitHub Pages deploy.
- **Steps 4 and 6 (news pipeline, testing/polish)** — not started.

There is no test framework yet; verification is done by running the script
and cross-checking values against the source websites (see Commands).

Treat `doc/research.md` as the source of truth for domain logic and design
decisions — check it before inventing a different approach, and update it if
a decision changes. [doc/data_dictionary.md](doc/data_dictionary.md) is the
per-indicator reference (what each series means, what each derived value is).

## Commands

```bash
source .venv/bin/activate     # deps: uv pip install -r requirements.txt
python update.py              # fetch + assess + rewrite latest.json
python backtest.py            # replay the pressure ladder over 2018-now
python mcp_server.py          # MCP server over stdio (Claude Code / Desktop)
python mcp_server.py --http   # same server over streamable-http (remote clients)
```

**Python 3.12** — the venv is built with `uv venv --python 3.12`. The MCP SDK
requires 3.10+ and macOS system Python is 3.9, so `uv` manages the interpreter.

Run `backtest.py` after changing any threshold in `assess.py`: it checks that
the ladder still reaches L3 during the 2019-09 repo blowup and 2020-03, and
that calm years stay quiet (2021-2023 currently produce zero L2+ days).

`update.py` is the only entrypoint; `assess.py` is a library module it calls
with the in-memory DataFrame (it does not re-read `latest.json`). Exit code 1
means a required series (`WALCL`/`WTREGEN`/`RRPONTSYD`) could not be fetched;
any other series failing is logged and skipped so an unattended cron run
still produces output.

## What this project is

A liquidity-analysis dashboard tracking US dollar liquidity (Fed balance
sheet, TGA, RRP, repo/funding-market stress) with an added news-analysis
layer that existing trackers lack. Planned architecture:

- **No backend server.** A single Python script run on a schedule (GitHub
  Actions cron), committing its output back to the repo.
- **GitHub Pages** serves a static dashboard reading the committed output.
- **`latest.json` snapshot pattern** (borrowed from `ruleaker/net-liquidity-dashboard`):
  the update script writes one JSON file with the latest computed values;
  every consumer (web page, future bots) reads only that file rather than
  recomputing from raw series.
- **`history.json` for charts.** `latest.json` holds a single snapshot, which
  cannot draw a line. `build_history()` also emits three years of
  **business-daily** values (~176KB). Daily, not weekly: weekly sampling drops
  the quarter-end repo spikes outright — the +32bp reading on 2025-10-31 would
  simply vanish, and the pressure chart would look calm through a real stress
  episode. It also carries per-day `srf_usd`, `sofr_minus_iorb_z6m` and
  `pressure_level`, recomputed with the same `classify_pressure_level` that
  grades today (via `assess.pressure_level_history`), so the dashboard's
  timeline can never disagree with the headline badge. SRF history and today's
  SRF value come from one NY Fed request; if it fails, `srf_usd` is **omitted**
  (with a `warnings` entry), never zero-filled.
- **Charts are JSON → web chart, not static PNG** — data is shipped as JSON
  and rendered client-side so it stays interactive.
- **News layer** (the actual differentiator vs. existing trackers): classify
  Fed/Treasury/QT/debt-ceiling news by direction/strength/rationale and tie
  it to observed liquidity moves; longer-term goal includes MCP-server-based
  natural-language queries over the data.

## Domain logic Claude must get right

This is the part existing trackers get wrong or oversimplify, and it's the
reason this project exists — don't "simplify" it away when implementing.

**Net Liquidity formula:** `Net Liquidity = WALCL − TGA − RRP` (Fed assets
minus the two balance-sheet buckets that sit outside the banking system).

**Unit normalization is mandatory:** `WALCL`/`WTREGEN`/`WRESBAL`/`TREAST`/
`WSHOMCB`/`WSHOSHO` are in millions of USD; `RRPONTSYD` and
`TLAACBW027SBOG` are in billions of USD. Normalize to trillions before
combining. **Never take a unit from the docs — read it off the FRED series
page and sanity-check the magnitude of the latest CSV row.** Precedents:
`DXY` was documented as a FRED series and doesn't exist (404); `WTREGEN`
was documented as daily and is weekly; `TLAACBW027SBOG` was declared
`millions` in `SERIES` and is actually *Billions of U.S. Dollars*, which
recorded it 1000x too small (0.0258T instead of 25.8T) and made the
reserves/bank-assets ratio read 11679% instead of 11.7%. A full audit of
every series' unit against its FRED page was done when fixing that one;
`TLAACBW027SBOG` was the only wrong entry.

FRED CSV missing values were historically encoded as `.`, but the live
endpoint has been observed returning an empty field instead — pass
`na_values=[".", ""]` when parsing to cover both.

**TGA/RRP are not interchangeable subtractions**, despite the formula
above treating them the same. Which one absorbs Treasury issuance changes
the market impact entirely:
- Path A (issuance funded from RRP, e.g. MMFs buying T-bills): RRP↓ → TGA↑,
  reserves unaffected — the buffer absorbs it.
- Path B (issuance funded from bank deposits/reserves): reserves↓ → TGA↑ —
  direct hit to liquidity.

The RRP buffer that absorbed this from ~2022–2026 is largely depleted, so
new code should treat Path B as the current regime, not an edge case. When
building the "cause decomposition" feature (see design requirement 5 below),
distinguish Fed-driven changes (`TREAST`↓ = QT) from Treasury-driven changes
(`WTREGEN`↑ = TGA refill) — the existing formula can't tell these apart on
its own.

**Pressure indicators override quantity indicators.** Judgment logic must
follow this precedence, not a weighted blend:
- quantity↑, no pressure signal → healthy
- quantity↓, no pressure signal → neutral
- **any pressure signal (SOFR−IORB spread widening, or meaningful SRF
  usage) → warning, regardless of quantity direction.**
- SRF usage of exactly 0 does *not* mean no stress (stigma effect) — always
  show it alongside the spreads, never alone.

**Known blind spots to disclose, not hide** (dashboard must surface these,
per design requirement 7): eurodollar/offshore dollar credit is invisible to
every indicator here; currency-in-circulation inflates WALCL-based reads
(prefer `WRESBAL` for a cleaner reserves read); credit creation via bank
lending doesn't move reserves at all; the liquidity→risk-asset lead/lag
relationship is regime-dependent and breaks down in crises.

## Data conventions

- **Source:** FRED public CSV endpoint, no API key needed:
  `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>`
- **Series used:** `WALCL` (Fed total assets, weekly/Thu), `WTREGEN` (TGA,
  **weekly**, ~7-day cadence — verified against live data during Step 1;
  research.md originally assumed daily), `RRPONTSYD` (ON RRP, daily),
  `WRESBAL` (reserves), `TREAST` (Fed UST holdings), `WSHOMCB` (Fed MBS
  holdings), `WSHOSHO` (**all** securities held outright, i.e. UST + MBS +
  agency — the docs originally called it "short-term UST"; verified as
  TREAST + WSHOMCB = WSHOSHO), `TLAACBW027SBOG` (bank total assets, for
  reserves/assets ratio), `WCURCIR` (currency in circulation — the fifth
  bucket in the liabilities breakdown and the most stable of them: a 0.16T
  range over three years), `DTWEXBGS` (Nominal Broad USD Index — **not**
  `DXY`; `DXY` is not a valid FRED series ID, confirmed 404), `DFII10`,
  `SP500` (S&P 500 index, daily, for overlaying against liquidity on the
  dashboard — FRED only licenses the **last 10 years**, verified: starts
  2016-09-26, 2608 rows; not in `REQUIRED_SERIES` so a fetch failure can't
  kill an unattended cron run).
- **Publication frequency mismatch:** WALCL and WTREGEN are weekly
  (WALCL: Thursday H.4.1 release, ~21:30 UTC); RRPONTSYD is daily. Reindex
  to business days and forward-fill (`ffill`) the weekly series rather than
  downsampling the daily one. The update cron
  (`.github/workflows/update.yml`) runs at 22:00 UTC **every weekday**, not
  just Thursdays: Thursday's run catches the H.4.1 release, and the other days
  keep the daily pressure series (SOFR/RRP/SRF) fresh — a Thursday-only run
  would surface a quarter-end repo spike up to a week late.
- **FRED can publish future-dated rows.** `IORB` (an administered rate) is
  posted for the next business day in advance. `align_daily` caps its end at
  today (UTC); without that, a Saturday run set `as_of` to the following
  Monday and ffilled every other series onto a date that hadn't happened.
- **Regime sensitivity:** don't hardcode absolute thresholds for
  warning/healthy classification — use Z-scores with a selectable lookback
  window (2M/6M/1Y/2Y), since the same raw values mean different things in
  different regimes.

## Pressure layer (as implemented in `assess.py`)

- **Series:** `SOFR` and `IORB` (both daily, both on FRED). The spread
  `SOFR−IORB` is expressed in bp.
- **SRF usage** is *not* on FRED. It comes from the NY Fed Markets API:
  `https://markets.newyorkfed.org/api/rp/results/search.json?startDate=…&endDate=…&operationTypes=Repo`,
  filtering client-side for `operationType=="Repo" AND operationMethod=="Full
  Allotment"` and summing `totalAmtAccepted` per date (the API's
  `securityType=srf` parameter returns an empty array — don't use it).
- **Four-level ladder (L0-L3), not a binary flag.** Each level's conditions
  are OR'd; see `classify_pressure_level` in `assess.py`. Every threshold
  comes from the measured distribution, not intuition:
  - **L1** — SOFR-IORB 6M Z-score >= 2.0 **or** spread >= +5bp (95th pct).
  - **L2** — that breach persists 2 of 3 business days, **or** spread >=
    +15bp (99th pct), **or** SRF >= $1B.
  - **L3** — SOFR-IORB >= +30bp, **or** SRF >= $10B.
- **Z-score is one-sided.** Only an *upward* deviation is stress; a spread far
  *below* its norm means liquidity is abundant. Using `abs(z)` flags calm
  periods as pressure — a real bug the backtest caught.
- **`SRF > 0` is unusable as a trigger.** 119 of 798 business days are nonzero
  and most are single-digit millions, so it would light up permanently. Only
  10 days exceeded $1B and 7 exceeded $10B — hence those cuts.
- All four Z-score windows are still computed and stored so the dashboard can
  offer the period selector; only the 6M window drives the ladder.
- **`None` is not `False`.** A signal that could not be evaluated (SRF fetch
  failed, series missing, window unfilled) is stored as `null`, never as
  "no pressure", and flips `pressure_data_complete` to false. `IORB` only
  starts 2021-07-29, so 2Y Z-scores are legitimately unavailable for older
  as-of dates.
- **EFFR is deliberately not used.** The bank-side spread (EFFR-IORB) was
  dropped at the user's request — it is not collected and not judged on. To
  restore it, see the comment above `SPREAD_DEFINITIONS` in `assess.py`.
- **IOER vs IORB is a regime break.** The benchmark before 2021-07 was IOER,
  and spreads behaved differently against it. Backtest output from that era
  is not directly comparable to today's.
- **Zero variance ≠ missing data.** A spread that is perfectly flat across
  the window yields `0/0 = NaN`; that is recorded as `zero_variance` and
  treated as "not triggered", with the caveat (surfaced in `warnings`) that a
  spread stuck at a *wide* level also scores near zero.
