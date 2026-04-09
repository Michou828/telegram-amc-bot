# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Running the Bot

```bash
# Preferred: auto-detects venv, loads .env implicitly (python-dotenv)
./start.sh

# Direct
python3 amc_showtime_bot.py
```

Credentials are stored in `.env`:
```
BOT_TOKEN=<telegram bot token>
CHAT_ID=<your telegram user id>
```

## Dependencies

Install from `requirements.txt`:

```bash
pip install -r requirements.txt
```

Key packages:
- `python-telegram-bot[job-queue]>=20.0` — async Telegram client with scheduler
- `curl_cffi>=0.5.9` — Cloudflare bypass (browser TLS impersonation)
- `seleniumbase` — UC mode Chrome (Mac/x86 only; optional, falls back gracefully)
- `python-dotenv` — loads `.env`

On Raspberry Pi: do NOT install `seleniumbase` — its bundled chromedriver is x86 and will `Exec format error` on ARM. Install system Chrome instead:
```bash
sudo apt install chromium chromium-driver
```

## Architecture

Three-file architecture:

| File | Responsibility |
|---|---|
| `amc_showtime_bot.py` | All bot logic: commands, conversation flow, polling |
| `scraper.py` | HTTP + cookie harvesting + showtime HTML parsing |
| `database.py` | SQLite: tracked movies, seen showtimes, format timestamps |

Supporting files:
- `theaters.json` — NYC metro AMC theater database (slug, name, market, neighborhood)
- `start.sh` — Auto-detects `.venv/` or `venv/`, runs `amc_showtime_bot.py`
- `requirements.txt` — Python dependencies

## `scraper.py`

`AMCScraper` — single instance, used globally in `amc_showtime_bot.py`.

### Scraping strategy

**Layer A — Cookie harvest (heavy, infrequent):** Headless Chrome (seleniumbase UC mode on Mac, system chromium on Pi). Must harvest from a **showtime URL** to trigger the `QueueITAccepted` cookie — harvesting from `/movies` won't work. Harvest takes ~45s (Pi) to ~15s (Mac).

**Layer B — Polling (light, frequent):** `curl_cffi` with `chrome124` impersonation. Injects Layer A cookies. Fast — 1–2 seconds per request.

### Key methods

- `harvest_cookies(target_url=None)` — acquires mutex, calls `_do_harvest()`
- `_do_harvest()` — tries UC mode first, falls back to `_harvest_with_system_chrome()`
- `get_page_data(url)` — Layer B fetch; triggers harvest on block; respects 30-min cooldown
- `parse_showtimes(html)` — parses `self.__next_f.push` RSC chunks; returns `{movie_slug: {format: [times]}}`
- `get_movies_list(list_type)` — fetches now-playing/coming-soon; 12h cache

### Mutex

`threading.Lock` on `_harvest_lock` prevents two Chrome instances running simultaneously (would OOM a Pi Zero 2 W). Second caller waits and reuses the freshly harvested cookies.

### Cache

`cache.json` — persists cookies + movie list. Copy from Mac to Pi to bootstrap without an immediate harvest.

## `database.py`

SQLite file: `amc_bot.db`

Tables:
- `tracked_movies` — `(user_id, movie_name, movie_slug, theater_name, theater_slug, date_range, formats)`
- `seen_showtimes` — `(movie_slug, theater_slug, date, format, time, first_seen_at)`

Key functions:
- `is_showtime_seen(...)` / `mark_showtime_seen(...)` — deduplication
- `is_format_new(movie_slug, theater_slug, date, format_name, hours=24)` — returns True if format's `first_seen_at` is within the last 24h; drives the `🆕` badge

## `amc_showtime_bot.py`

### Commands

| Command | Description |
|---|---|
| `/start` / `/help` | Show command list |
| `/check` | One-time showtime lookup (movie → theater → date) |
| `/track` | Start background monitoring (movie → theater → date → formats) |
| `/list` | Show all tracked movies |
| `/remove` | Stop tracking a movie |
| `/status` | Cookie age, tracked count, next poll time |
| `/refresh` | Force immediate cookie harvest |

All commands are owner-only (`OWNER_ID` from `CHAT_ID` env var).

### Conversation flow

Both `/check` and `/track` share the same 4-state `ConversationHandler`:

```
SELECT_MOVIE → SELECT_THEATER → SELECT_DATE → SELECT_FORMAT (track only)
```

Movie picker shows fuzzy-matched results from the user's text input, with inline keyboard buttons. Theater selection accepts typed input (fuzzy matched) or quick-select buttons from `theaters.json`.

Callback data prefixes:
- `movie:<slug>` — movie selected from picker
- `theater_<slug>` — theater quick-select button
- `format_<name>` — format toggle in `/track`
- `done_formats` — confirm format selection
- `remove_<id>` — remove tracked movie

### Polling

`polling_task` runs every 600 seconds via `job_queue.run_repeating`. For each tracked movie:

1. Builds showtime URL: `https://www.amctheatres.com/movie-theatres/<market>/<theater_slug>/showtimes?date=<date>`
2. Calls `scraper.get_page_data()` → `scraper.parse_showtimes()`
3. Filters by tracked formats (substring match)
4. For each unseen showtime: calls `mark_showtime_seen()`, appends to notification
5. Sends notification if any new showtimes found

`🆕` badge appears on formats where `is_format_new()` returns True (first seen within 24h).

Notification format:
```
🎉 NEW SHOWTIMES!

🎬 MOVIE TITLE
📅 April 4, 2026
🏛️ AMC Lincoln Square 13

🆕 DOLBY: 12:00pm, 3:30pm
IMAX: 11:00am, 2:30pm

🕐 Detected at 2:35 PM
```

### Date input format

- Single date: `MM/DD/YYYY`
- Date range: `MM/DD/YYYY>MM/DD/YYYY` (each date gets its own check and notification)

### Theater market map

`theaters.json` includes a `market` field per theater (e.g., `"new-york-city"`). A dict is built at runtime:
```python
market_map = {t['slug']: t.get('market', 'new-york-city') for t in THEATERS_DATA}
```

## Deployment (Raspberry Pi Zero 2 W)

See `doc/google-cloud-setup.md` for GCP. For Pi:

```bash
# 1. Install system Chrome (NOT pip)
sudo apt install chromium chromium-driver

# 2. Clone repo and set up venv
git clone <repo> telegram-amc-bot && cd telegram-amc-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Note: requirements.txt includes seleniumbase — that's fine, the binary just won't be used on ARM

# 3. Create .env
echo "BOT_TOKEN=..." > .env
echo "CHAT_ID=..." >> .env

# 4. Install and start service
sudo cp amc-showtime-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable amc-showtime-bot
sudo systemctl start amc-showtime-bot

# 5. Watch logs
sudo journalctl -u amc-showtime-bot -f
```

To bootstrap cookies from Mac (skips first Chrome harvest on Pi):
```bash
scp cache.json <user>@<pi-ip>:~/telegram-amc-bot/
```

To clear showtime cache (forces re-notification on next poll):
```bash
rm amc_bot.db
python3 -c "from database import init_db; init_db()"
```
