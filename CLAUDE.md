# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Bot

```bash
# Preferred: uses .env for credentials
./start.sh

# Direct invocation
python3 bot.py "<BOT_TOKEN>" "<CHAT_ID>"
```

Credentials are stored in `.env` as `BOT_TOKEN` and `CHAT_ID`.

## Dependencies

No `requirements.txt` exists. Install manually:

```bash
pip install requests beautifulsoup4 cloudscraper
```

`cloudscraper` is required — AMC's website and GraphQL API are behind Cloudflare and return 403 to plain `requests`.

## Architecture

This is a **Telegram bot** that monitors AMC movie showtimes and sends notifications when new showtimes appear.

### Key Files

- **`bot.py`** — Main application. All production logic lives here.
- **`theater_matcher.py`** — Fuzzy theater name search against `theaters.json`.
- **`theaters.json`** — NYC metro area AMC theater database (Manhattan, Bronx, NJ).
- **`amc_bot_mac.py`** — Legacy prototype; not actively used.
- **`start.sh`** — Loads `.env` and runs `bot.py`.
- **`amc-movie-urls-guide.md`** — Reference doc for AMC URL patterns and GraphQL API.

### Core Classes in `bot.py`

| Class | Responsibility |
|---|---|
| `NowPlayingFetcher` | Scrapes `amctheatres.com/movies` for Now Playing titles; 5-min in-memory cache |
| `RecentMovies` | Persists last 5 tracked movies to `~/.amc_monitors/recent_movies.json` |
| `TelegramBot` | Telegram API wrapper (long-polling, send messages, inline keyboards) |
| `AMCHelper` | URL parsing, slug/title conversion, date parsing, theater validation |
| `ShowtimeFetcher` | Scrapes AMC showtime HTML; parses formats and showtimes |
| `MovieTracker` | Tracks one movie at one theater; caches results per date to detect changes |
| `MonitorManager` | Background thread; checks all trackers every N seconds (default 300s) |
| `BotCommandHandler` | Routes commands and manages per-user conversation state machine |

### Cloudflare / HTTP

All AMC requests use a **shared module-level `_amc_scraper`** (`cloudscraper.create_scraper()`) defined at the top of `bot.py`. Used by `ShowtimeFetcher`, `NowPlayingFetcher`, and `AMCHelper.validate_theater`. Never use plain `requests` for AMC URLs.

### Conversation State Machine

Two multi-step flows, both start by presenting movie picker buttons:

- **`/track`**: movie → theater → date(s) → formats → start background monitoring
- **`/check`**: movie → theater → date(s) → fetch & display once

Movie picker shows two button sections: **Recent** (last 5 tracked) and **Now Playing** (top 10 from AMC). Inline keyboard header buttons (`── Recent ──`, `── Now Playing ──`) use `callback_data: "noop"` and are silently ignored. Theater selection supports fuzzy matching with suggestions; quick-select button for AMC Lincoln Square 13.

Callback data prefixes:
- `movie:<slug>` — recent movie selected
- `nowplaying:<slug>` — now playing movie selected
- `theater:<slug>` — theater selected
- `noop` — section header button, ignored

### Tracking & Notification Logic

`MonitorManager` runs a background thread checking all trackers every `check_interval` seconds. For each tracker, `MovieTracker.check_showtimes()` fetches every tracked date. A notification is sent per-date when showtimes are available AND the formats dict differs from the cached version.

**Multiple dates = multiple messages.** Each date with new/changed showtimes gets its own Telegram message.

**Notification format:**
```
🎉 NEW SHOWTIMES!

🎬 MOVIE TITLE
📅 April 4, 2026
🏛️ AMC Lincoln Square 13

🆕 DOLBY: 12:00, 15:30, 19:00
IMAX: 11:00, 14:30

🕐 Detected at 2:35 PM
```

`🆕` appears on formats first seen within the last 24 hours — persists across both notifications and manual `/check` calls so missed notifications are still informative.

### Caching & State Persistence

Cache directory: `~/.amc_monitors/`

Per-tracker cache file: MD5 of `{movie_slug}-{theater_slug}-{dates[0]}`. Stores per-date:
- `formats` — current showtime dict (used to detect changes)
- `format_first_seen` — timestamp per format name (drives the 24h `🆕` badge)
- `last_update` — last check timestamp

To clear showtime cache while keeping recent movies history:
```bash
find ~/.amc_monitors/ -name "*.json" ! -name "recent_movies.json" -delete
```

### Theater Matcher

`TheaterMatcher` loads `theaters.json` via `Path(__file__).parent / "theaters.json"`. Add new theaters by appending to the `theaters` array with `slug`, `name`, `city`, `state`, `address`, `zip`, `neighborhood`, and `search_terms` fields.

### Date Input Format

- Single date: `MM/DD/YYYY`
- Date range: `MM/DD/YYYY>MM/DD/YYYY`

### Format Names

Showtime formats are standardized to: `IMAX 70MM`, `IMAX`, `DOLBY`, `70MM`, `3D`, `PRIME`, `DBOX`, `4DX`, `SCREENX`. Anything else kept as-is uppercased. User format preferences use partial string matching.
