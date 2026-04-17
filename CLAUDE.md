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
- `parse_showtimes(html)` — parses RSC chunks; returns `{movie_slug: {format: [times]}}`
- `get_movies_list(list_type)` — GraphQL fetch for `now-playing`/`coming-soon`/`events`; 12h cache
- `refresh_movie_list()` — clears per-list cache entries then re-fetches all three (important: must clear before fetching to avoid stale-cache skip bug)

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
1. Expands stored date string to individual dates
2. Fetches `https://www.amctheatres.com/movie-theatres/<market>/<theater>/showtimes?date=<date>`
3. Parses showtimes, filters by tracked formats
4. Notifies on new showtimes; `🆕` badge if format first seen within 24h
5. Alerts owner after 3 consecutive fetch failures

**Slug matching:** GraphQL sometimes returns shortened slugs (e.g. `the-mandalorian-grogu-60322`) that differ from theater-page slugs (`star-wars-the-mandalorian-and-grogu-60322`). Polling matches exact slug first, then falls back to matching by numeric movie ID suffix.

### Callback data prefixes
- `mv_<idx>` / `mv_recent_<slug>` — movie selection
- `theater_<slug>` — theater quick-select
- `fmt_<name>` — format toggle in `/track`
- `rmpick_<i>` / `rmtoggle_<id>` / `rmconfirm` / `rmcancel` — remove flow

## Deployment (Raspberry Pi Zero 2 W)

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

Bot is in good shape. Known issues / potential improvements:

- [ ] Atomicity bug: `mark_showtime_seen()` is called before `send_message()` — if the Telegram send fails, the showtime is permanently lost (never re-notified)
- [ ] Direct booking links in showtime notifications (deep link to AMC ticket page)
- [ ] `/movies` paging or filter — 300+ coming-soon is a lot even with caps
- [ ] Prune `seen_showtimes` for past dates automatically (table grows unbounded)
- [ ] Multi-theater tracking for same movie (currently one theater per tracked entry)
