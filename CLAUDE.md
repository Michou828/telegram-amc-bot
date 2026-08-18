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
python -m pytest test_amc_showtime_bot.py test_scraper.py test_database.py
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
- `parse_showtimes(html)` — parses RSC chunks; returns `(results, statuses, showtime_ids)` where `results = {movie_slug: {format: [times]}}`, `statuses = {movie_slug: {format: {time: status}}}`, and `showtime_ids = {movie_slug: {format: {time: showtimeId}}}`. `status` is AMC's own sellability field (confirmed values: `Sellable`, `AlmostFull`, `ComingSoon` — not yet on sale — and `Soldout`, confirmed live 2026-08-18 on Dune: Part Three's release day). `showtimeId` builds a direct booking deep link: `https://www.amctheatres.com/showtimes/{showtimeId}/seats`
- `get_movies_list(list_type)` — GraphQL fetch for `now-playing`/`coming-soon`/`events`; 12h cache. **Caution:** its staleness check reads a single shared `last_list_refresh` timestamp across all three list types — calling it back-to-back for multiple list types is unsafe (see bug below). Only call it for a single list type at a time, or go through `refresh_movie_list()`.
- `refresh_movie_list()` — clears per-list cache entries then re-fetches all three (important: must clear before fetching to avoid stale-cache skip bug — see below)

### Cache (`cache.json`)
Persists cookies + movie_list_cache + timestamps. Copy from Mac to Pi to bootstrap.

## `database.py`

SQLite: `amc_bot.db` — never auto-cleared.

Tables:
- `tracked_movies` — active tracking tasks; `active_tracking` opt-in flag (off by default, toggled via `/activetracking`) enables silent delist detection and a distinct reappearance notification for that movie
- `seen_showtimes` — dedup log (grows forever; delete db to reset notifications); also tracks per-showtime status to detect ComingSoon-to-on-sale and Soldout-to-available transitions (the latter for every tracked movie, since AMC reports `Soldout` directly), plus a bot-internal `Delisted` status sentinel (distinct from AMC's own `Sellable`/`AlmostFull`/`ComingSoon`/`Soldout` values) used only for active-tracked movies
- `movie_registry` — coming-soon movies; status: `future_release` / `advanced_tickets`
- `recent_movies` — 7-day rolling window of searched/selected movies
- `slug_reconciliations` — proposed movie slug/ID rewrites for `tracked_movies`; status: `pending` / `confirmed` / `declined` / `auto_confirmed` / `ambiguous` (the last is a dedup-only marker, never surfaced to the sweep/auto-confirm path)

## `amc_showtime_bot.py`

### Commands

| Command | Description |
|---|---|
| `/check` | One-time showtime lookup (movie → theater → date) |
| `/track` | Background monitoring (movie → theater → date → formats) |
| `/trackinglist` | Show tracked movies grouped by movie → format → dates |
| `/activetracking` | Toggle disappear/reappear alerts for a tracked movie |
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

`_sweep_pending_reconciliations` also runs 5s after launch (separate `run_once`, alongside `_startup_sequence`): re-arms or immediately resolves any `pending` slug reconciliation whose 1h auto-confirm window was lost to the restart (no `telegram.ext` persistence is configured).

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
3. Parses showtimes, filters by tracked formats; `AlmostFull` showtimes get a ⚠️ badge, `ComingSoon` a 🕒 badge, and `Soldout` a 🚫 badge (`_format_times_with_badges`) so near-capacity, not-yet-on-sale, and sold-out times are distinguishable from wide-open ones. Each time is rendered as a direct link to that showtime's seats page (`https://www.amctheatres.com/showtimes/{showtimeId}/seats`) when a `showtimeId` was captured, rather than a generic link to the movie's page.
4. Notifies on new showtimes; `🆕` badge if format first seen within 24h; a showtime transitioning from `ComingSoon` to `Sellable`/`AlmostFull` triggers a separate "TICKETS NOW AVAILABLE" notification. A showtime transitioning to `Soldout` is persisted silently (no notification) for every tracked movie; if it later becomes `Sellable`/`AlmostFull` again, a `🔁 AVAILABLE AGAIN` notification fires — this Soldout→available path applies regardless of `/activetracking`, since `Soldout` is a status AMC reports directly rather than something the bot infers. For movies with active tracking enabled (`/activetracking`), a showtime that drops off the listing entirely (commonly AMC's release-day queue-it system pulling it mid-queue) is silently marked internally too (`Delisted`, a bot-only sentinel — this path is opt-in because a queue-it holding page can look identical to every showtime vanishing at once); reappearing from either `Soldout` or `Delisted` fires the same `🔁 AVAILABLE AGAIN` notification. Disappearance/sellout itself is never notified.
5. Alerts owner after 3 consecutive fetch failures **for that specific (movie, theater, date) item** — failures are tracked per item (`_register_poll_failure`/`_poll_failure_count`, keyed in `bot_data['poll_failures']`), not a single global counter, so one item's issue doesn't push unrelated items toward the alert threshold. A harvest that just ran and reports `_is_transient_harvest_retry` doesn't count as a failure at all — it's an expected single miss by design (the code deliberately defers the retry to the next call rather than re-fetching immediately)

**Slug matching:** GraphQL sometimes returns shortened slugs (e.g. `the-mandalorian-grogu-60322`) that differ from theater-page slugs (`star-wars-the-mandalorian-and-grogu-60322`). Polling matches exact slug first, then falls back to matching by numeric movie ID suffix.

### Movie ID reconciliation

AMC occasionally reissues a movie's slug/ID (e.g. graduating from an `events` placeholder to a real `coming-soon` entry). `_sync_movie_registry` runs `_find_slug_reconciliation_candidates(tracked_pairs, coming_soon)` on every real registry sync (12h cache-expiry refresh or `/refreshmovielist`) to detect a tracked slug that's vanished from the fresh list while exactly one same-named, differently-slugged entry has appeared.

- Exactly 1 match → `_handle_reconciliation_results` inserts a `pending` row in `slug_reconciliations`, dedup'd on `(old_slug, new_slug)`, and sends an owner prompt with `reconcile_yes_<id>` / `reconcile_no_<id>` buttons. Auto-applies (`_auto_confirm_reconciliation_job`) after 1h with no response.
- 2+ matches → ambiguous; a plain heads-up is sent (no buttons, no auto-action), dedup'd via a sentinel row (`status='ambiguous'`, `new_slug` encodes the sorted candidate slugs) so the same ambiguous combination doesn't re-nag every sync.
- `_resolve_reconciliation` edits the original prompt in place; if `message_id` is missing or the edit fails, it falls back to sending a fresh message — a reconciliation is never applied silently with zero owner notification.

### Callback data prefixes
- `mv_<idx>` / `mv_recent_<slug>` — movie selection
- `theater_<slug>` — theater quick-select
- `fmt_<name>` — format toggle in `/track`
- `rmpick_<i>` / `rmtoggle_<id>` / `rmconfirm` / `rmcancel` — remove flow
- `reconcile_yes_<id>` / `reconcile_no_<id>` — slug reconciliation confirm/decline
- `acttrack_<i>` / `acttrack_done` — active tracking toggle (index into `context.bot_data['acttrack_movies']`, not the raw slug — AMC event slugs can exceed Telegram's 64-byte callback_data limit)

## Deployment (Raspberry Pi Zero 2 W)

SSH: `ssh amc-bot-pi` (passwordless key auth, configured in `~/.ssh/config` on Mac — do NOT use the raw `user@hostname` form, which falls back to password auth and will hang non-interactively).

Pi quirks:
- `sqlite3` CLI not installed — use `sudo python3 -c "import sqlite3; ..."`
- `amc_bot.db` is owned by root (service runs as root) — must stop service before editing DB
- Pi DB path: `~/telegram-amc-bot/amc_bot.db`
- Use `pi_data/` (gitignored) for local DB copies pulled from Pi

```bash
# Pull and restart
ssh amc-bot-pi "cd ~/telegram-amc-bot && git pull && sudo systemctl restart amc-showtime-bot"

# Watch logs
ssh amc-bot-pi "sudo journalctl -u amc-showtime-bot -f"

# Bootstrap cookies from Mac (avoids first harvest on Pi)
scp cache.json amc-bot-pi:~/telegram-amc-bot/

# Reset seen showtimes (re-notifies on next poll)
ssh amc-bot-pi "cd ~/telegram-amc-bot && rm amc_bot.db && python3 -c 'from database import init_db; init_db()'"

# Query DB directly (root-owned — needs sudo)
ssh amc-bot-pi "sudo python3 -c \"import sqlite3; conn = sqlite3.connect('/home/michou/telegram-amc-bot/amc_bot.db'); ...\""
```

## Next Session: Pick Up Here

Bot is in good shape. Fixed 2026-07-21/22: spurious "Polling Warning" alerts (per-item failure tracking, harvest retries no longer miscounted), polling of expired tracked dates, movie-list cache going stale for days with no auto-refresh, and AlmostFull showtimes now badged. Details in git log (`e76f400`, `c4c506e`) and `test_amc_showtime_bot.py`/`test_scraper.py`.

Added 2026-07-24: movie ID reconciliation — detects a tracked movie's AMC slug/ID being reissued (e.g. Dune: Part Three's `dune-part-three-83391` → `dune-part-three-77032`) and prompts the owner to update `tracked_movies` rather than silently dead-polling forever. See "Movie ID reconciliation" above, `docs/superpowers/specs/2026-07-24-movie-id-reconciliation-design.md`, and `TestSlugReconciliationDetection`/`TestReconciliationAutoConfirmTiming` in `test_amc_showtime_bot.py`.

Added 2026-08-17: Available Soon tracking — AMC now lists future showtimes with `status: "ComingSoon"` before they go on sale. Previously these got folded into a normal "new showtime" notification and then never re-checked, so the bot never noticed when they actually became purchasable. `seen_showtimes` now has a `status` column (NULL-defaulted for pre-existing rows, so already-tracked movies backfill correctly without a spurious notification); `ComingSoon` times get a 🕒 badge; and a distinct `🎟️ TICKETS NOW AVAILABLE!` notification fires when a tracked showtime transitions from `ComingSoon` to `Sellable`/`AlmostFull`. See `docs/superpowers/specs/2026-08-17-available-soon-tracking-design.md`, `docs/superpowers/plans/2026-08-17-available-soon-tracking.md`, `_classify_showtime`/`TestClassifyShowtime` in `amc_showtime_bot.py`/`test_amc_showtime_bot.py`, and `test_database.py`. Deployed to the Pi 2026-08-17 and confirmed live: Dune: Part Three's pre-existing `ComingSoon` rows backfilled correctly with no spurious notification.

Added 2026-08-18: Active tracking — `tracked_movies` adds an `active_tracking` column (boolean, only read by polling if a tracked movie has opt-in enabled). When `/activetracking` toggles active tracking ON for a movie, polling now tracks showtime delistings (transition from `Sellable`/`AlmostFull` to absent from the page) internally via `status = 'Delisted'`, and fires a `🔁 AVAILABLE AGAIN` notification if a delisted showtime reappears as `Sellable`/`AlmostFull`. Delistings can be transient (AMC's queue-it system pulling showtimes mid-purchase window) or final, but the bot can't distinguish between them, so this feature is opt-in to avoid over-notifying on queue events. See `/activetracking` command and Callback data prefixes / Polling sections above, `docs/superpowers/specs/2026-08-18-active-tracking-design.md`, `docs/superpowers/plans/2026-08-18-active-tracking.md`, and unit tests in `test_amc_showtime_bot.py`.

Added 2026-08-18 (same day): confirmed AMC's `"Soldout"` status live for the first time — Dune: Part Three's IMAX 70MM showtimes at AMC Lincoln Square 13 on its release day, resolving the previous "no confirmed sold out signal" known issue. `_classify_showtime` gained a `went_soldout` transition (any status → `Soldout`, persisted silently — no notification, applies to every tracked movie, not gated behind `/activetracking`) and extended `available_again` to also cover `Soldout` → `Sellable`/`AlmostFull` (reusing the same 🔁 notification active tracking's `Delisted` case already used). `_format_time_label` gained a 🚫 badge for `Soldout`. Also resolved the "direct booking links" known issue: `parse_showtimes()` now returns a third `showtime_ids` dict (`{movie_slug: {format: {time: showtimeId}}}`), and every notification (`/check`, new-showtime, now-available, available-again) links each individual time directly to `https://www.amctheatres.com/showtimes/{showtimeId}/seats` instead of a single generic movie-page link at the bottom of the message. Verified against live data on the Pi (showtime 146171978 = Dune: Part Three, IMAX 70MM, 1/10/2027 4:00pm, confirmed sold out via the showtime's own seats page). See `_classify_showtime`/`_format_time_label`/`_format_times_with_badges`/`TestClassifyShowtime`/`TestFormatTimesWithBadges` in `amc_showtime_bot.py`/`test_amc_showtime_bot.py`, and `TestParseShowtimeId` in `test_scraper.py`.

Known issues / potential improvements:

- [ ] `/movies` paging or filter — 300+ coming-soon is a lot even with caps
- [ ] Prune `seen_showtimes` for past dates automatically (table grows unbounded) — also covers orphaned rows left behind when AMC retimes a showtime (e.g. 7:00pm → 7:30pm creates a new dedup row and abandons the old one, which then sits at `status = NULL` forever since polling only touches currently-listed times); confirmed live on Dune: Part Three 2026-08-17, harmless but worth folding into the same cleanup pass
- [ ] Multi-theater tracking for same movie (currently one theater per tracked entry)
- [ ] `/trackinglist` still displays tracked dates that have already passed (polling now skips them, but the DB/display side was left untouched — `/remove` still works to clean them up manually)
- [ ] Movie ID reconciliation doesn't clean up the orphaned old-slug row left behind in `movie_registry` after a confirmed rewrite — harmless duplicate, out of scope per the design doc
- [ ] The `seen_showtimes.status` column doesn't persist every status change — only the specific gate transitions the bot cares about (`ComingSoon`/`Soldout`/`Delisted` → available, and → `Soldout`) trigger a write. Plain `Sellable ↔ AlmostFull` churn is never persisted (to avoid re-nagging), so the stored value can lag behind AMC's live status for that specific pair. Not observed as a problem live; noted as a design tradeoff, not a bug
- [ ] Toggling active tracking off after `seen_showtimes` rows for that movie have accumulated a `Delisted` status leaves those rows stale — a subsequent poll (even with tracking off) could still classify a reappearing showtime as `available_again` and send one more 🔁 notification before that row's status gets overwritten with the live value. Bounded and self-draining (one extra notification per stale row, max); judged acceptable rather than worth a code fix
- [ ] Active tracking's delisting detection (the bot-inferred `Delisted` sentinel, distinct from AMC's own `Soldout` status) still can't distinguish "genuinely sold out" from "AMC's queue-it system transiently pulled this showtime" — by design, since a showtime disappearing from the page doesn't carry AMC's reasoning with it. A showtime that comes back after either cause triggers the same 🔁 AVAILABLE AGAIN.
