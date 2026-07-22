# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Running the Bot

```bash
# Preferred: auto-detects venv, loads .env implicitly (python-dotenv)
./start.sh

# Direct
python3 amc_showtime_bot.py
```

Credentials in `.env`:
```
BOT_TOKEN=<telegram bot token>
CHAT_ID=<your telegram user id>
```

## Dependencies

```bash
pip install -r requirements.txt
```

Key packages:
- `python-telegram-bot[job-queue]>=20.0` — async Telegram client with scheduler
- `curl_cffi>=0.5.9` — Cloudflare bypass (browser TLS impersonation)
- `seleniumbase` — UC mode Chrome (Mac/x86 only; falls back gracefully on ARM)
- `python-dotenv` — loads `.env`

On Raspberry Pi — do NOT use seleniumbase's bundled chromedriver (x86, will `Exec format error` on ARM):
```bash
sudo apt install chromium chromium-driver
```

## Testing

```bash
pip install pytest
python -m pytest test_amc_showtime_bot.py test_scraper.py
```

Unit tests for the pure/testable logic (date filtering, per-item poll failure tracking, movie-list refresh staleness handling, showtime status badging). `test_scraper.py` builds synthetic AMC RSC payloads to exercise `parse_showtimes()` without hitting the network. No tests cover the Telegram handlers themselves (conversation flow, callbacks) — those still need manual verification.

## Architecture

| File | Responsibility |
|---|---|
| `amc_showtime_bot.py` | All bot logic: commands, conversation flow, polling |
| `scraper.py` | Cookie harvesting + showtime HTML parsing + GraphQL movie lists |
| `database.py` | SQLite: tracked_movies, seen_showtimes, movie_registry, recent_movies |

Supporting files:
- `theaters.json` — NYC metro AMC theater database
- `start.sh` — auto-detects venv, runs bot
- `requirements.txt` — Python dependencies

## `scraper.py`

### Two scraping layers

**Layer A — Movie lists (light):** AMC GraphQL API at `graph.amctheatres.com`. No Cloudflare bypass needed — uses existing session cookies. Queries: `NOW_PLAYING`, `COMING_SOON` (first:500), `ADVANCE_TICKETS`, `EVENTS`. 12h cache in `cache.json`.

**Layer B — Showtimes (heavy):** HTML scraping of AMC showtime pages via `curl_cffi` (`chrome124` impersonation). Requires Cloudflare cookies from Layer A harvest.

**Cookie harvest:** Headless Chrome (seleniumbase UC mode on Mac, system chromium on Pi). Must harvest from a **showtime URL** to get `QueueITAccepted` cookie — `/movies` URL won't work. Takes ~45s (Pi) / ~15s (Mac).

### Key methods

- `harvest_cookies(target_url=None, force=False)` — acquires mutex, calls `_do_harvest()`
- `get_page_data(url)` — Layer B fetch; triggers harvest on block; 30-min cooldown after failure
- `parse_showtimes(html)` — parses RSC chunks; returns `(results, statuses)` where `results = {movie_slug: {format: [times]}}` and `statuses = {movie_slug: {format: {time: status}}}`. `status` is AMC's own sellability field (confirmed values: `Sellable`, `AlmostFull` — no confirmed "sold out" value has ever been observed in the data, live sampling and payload text search both came up empty)
- `get_movies_list(list_type)` — GraphQL fetch for `now-playing`/`coming-soon`/`events`; 12h cache. **Caution:** its staleness check reads a single shared `last_list_refresh` timestamp across all three list types — calling it back-to-back for multiple list types is unsafe (see bug below). Only call it for a single list type at a time, or go through `refresh_movie_list()`.
- `refresh_movie_list()` — clears per-list cache entries then re-fetches all three (important: must clear before fetching to avoid stale-cache skip bug — see below)

### Cache (`cache.json`)
Persists cookies + movie_list_cache + timestamps. Copy from Mac to Pi to bootstrap.

## `database.py`

SQLite: `amc_bot.db` — never auto-cleared.

Tables:
- `tracked_movies` — active tracking tasks
- `seen_showtimes` — dedup log (grows forever; delete db to reset notifications)
- `movie_registry` — coming-soon movies; status: `future_release` / `advanced_tickets`
- `recent_movies` — 7-day rolling window of searched/selected movies

## `amc_showtime_bot.py`

### Commands

| Command | Description |
|---|---|
| `/check` | One-time showtime lookup (movie → theater → date) |
| `/track` | Background monitoring (movie → theater → date → formats) |
| `/trackinglist` | Show tracked movies grouped by movie → format → dates |
| `/remove` | Two-step multi-select removal by date entry |
| `/movies` | Browse Now Playing / Advance Tickets / Coming Soon / Events |
| `/refreshmovielist` | Force GraphQL refresh of all three movie lists |
| `/refreshcookies` | Force cookie harvest (double-confirm if cookies healthy) |
| `/botstatus` | Cookie age, movie list counts, polling health |
| `/cancel` | Cancel current conversation |
| `/help` | Show sectioned command list |

Unknown commands show the help text automatically.

### Startup sequence

On every start, `_startup_sequence` runs 5s after launch:
1. Sends progress message to owner
2. Harvests cookies (skipped if <1h old)
3. Refreshes all three movie lists via GraphQL
4. Edits message to "Bot Ready!" + full help text

### Movie list auto-refresh

`refresh_movie_lists_task` runs hourly (`job_queue.run_repeating`, separate from the 10-min polling job). Calls `_refresh_movie_lists(scraper)`, which force-refreshes all three lists via `refresh_movie_list()` once the 12h cache goes stale, then re-syncs `movie_registry`. This is a safety net for bots that stay up for weeks without anyone running `/movies`, `/check`, `/track`, or `/refreshmovielist` — without it, a stale cache just sits there indefinitely since nothing else ever re-triggers it.

### Conversation flow

`/check` and `/track` share a 4-state `ConversationHandler`:
```
SELECT_MOVIE → SELECT_THEATER → SELECT_DATE → SELECT_FORMAT (track only)
```

Movie picker shows recently used movies only (7-day expiry, one per row, name + `#ID`).
Full search by typing name or pasting AMC URL.

### Date input

- Single: `7/17`
- Range: `7/17-7/20`
- Comma-mixed: `7/7, 7/10-7/14, 7/16-7/18`

`get_dates_from_range()` splits on commas, expands ranges, deduplicates.
Raw text stored in DB; expanded to individual dates on every poll.

### Tracking list / Remove

`/trackinglist` — grouped by movie, then format, then dates. Shows URL `#ID` in name.

`/remove` — two-step:
1. Pick a movie from grouped list
2. Toggle individual date entries (✅/☐), then "Remove Selected (N)"

### Polling

`polling_task` runs every 600s. For each tracked movie:
1. Expands stored date string to individual dates, then drops any date before today (`_filter_future_dates`) — a tracked range doesn't get cleaned out of the DB, so without this the bot would otherwise keep fetching expired dates forever
2. Fetches `https://www.amctheatres.com/movie-theatres/<market>/<theater>/showtimes?date=<date>`
3. Parses showtimes, filters by tracked formats; `AlmostFull` showtimes get a ⚠️ badge (`_format_times_with_badges`) so near-capacity times are distinguishable from wide-open ones
4. Notifies on new showtimes; `🆕` badge if format first seen within 24h
5. Alerts owner after 3 consecutive fetch failures **for that specific (movie, theater, date) item** — failures are tracked per item (`_register_poll_failure`/`_poll_failure_count`, keyed in `bot_data['poll_failures']`), not a single global counter, so one item's issue doesn't push unrelated items toward the alert threshold. A harvest that just ran and reports `_is_transient_harvest_retry` doesn't count as a failure at all — it's an expected single miss by design (the code deliberately defers the retry to the next call rather than re-fetching immediately)

**Slug matching:** GraphQL sometimes returns shortened slugs (e.g. `the-mandalorian-grogu-60322`) that differ from theater-page slugs (`star-wars-the-mandalorian-and-grogu-60322`). Polling matches exact slug first, then falls back to matching by numeric movie ID suffix.

### Callback data prefixes
- `mv_<idx>` / `mv_recent_<slug>` — movie selection
- `theater_<slug>` — theater quick-select
- `fmt_<name>` — format toggle in `/track`
- `rmpick_<i>` / `rmtoggle_<id>` / `rmconfirm` / `rmcancel` — remove flow

## Deployment (Raspberry Pi Zero 2 W)

Pi quirks:
- `sqlite3` CLI not installed — use `sudo python3 -c "import sqlite3; ..."`
- `amc_bot.db` is owned by root (service runs as root) — must stop service before editing DB
- Pi DB path: `~/telegram-amc-bot/amc_bot.db`
- Use `pi_data/` (gitignored) for local DB copies pulled from Pi

```bash
# Pull and restart
git pull && sudo systemctl restart amc-showtime-bot

# Watch logs
sudo journalctl -u amc-showtime-bot -f

# Bootstrap cookies from Mac (avoids first harvest on Pi)
scp cache.json <user>@<pi-ip>:~/telegram-amc-bot/

# Reset seen showtimes (re-notifies on next poll)
rm amc_bot.db && python3 -c "from database import init_db; init_db()"
```

## Next Session: Pick Up Here

Bot is in good shape. Fixed 2026-07-21/22: spurious "Polling Warning" alerts (per-item failure tracking, harvest retries no longer miscounted), polling of expired tracked dates, movie-list cache going stale for days with no auto-refresh, and AlmostFull showtimes now badged. Details in git log (`e76f400`, `c4c506e`) and `test_amc_showtime_bot.py`/`test_scraper.py`.

Known issues / potential improvements:

- [ ] Direct booking links in showtime notifications — currently links to the movie's general page, not a showtime-specific deep link (deferred: AMC's Next.js deep-link format for ticket purchase URLs still needs reverse-engineering)
- [ ] `/movies` paging or filter — 300+ coming-soon is a lot even with caps
- [ ] Prune `seen_showtimes` for past dates automatically (table grows unbounded)
- [ ] Multi-theater tracking for same movie (currently one theater per tracked entry)
- [ ] `/trackinglist` still displays tracked dates that have already passed (polling now skips them, but the DB/display side was left untouched — `/remove` still works to clean them up manually)
- [ ] AMC occasionally reissues a movie's slug/ID when it graduates from an early "event" placeholder listing to a real Coming Soon entry (e.g. Dune: Part Three went from `dune-part-three-83391` under `events` to `dune-part-three-77032` under `coming-soon`) — the bot has no logic to reconcile these as the same movie; the old slug just becomes an orphaned, harmless duplicate
- [ ] No confirmed "sold out" signal exists anywhere in AMC's showtime data (checked ~1,250 live showtimes + raw payload text, found only `Sellable`/`AlmostFull`) — if a sold-out showtime notification recurs, capture the specific movie/theater/date/time so the live payload can be inspected at that exact moment
