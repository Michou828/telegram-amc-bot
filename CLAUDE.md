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
# Mac / residential (curl_cffi preferred, cloudscraper as fallback)
pip install requests beautifulsoup4 curl_cffi

# Pi / Linux / cloud (curl_cffi required — cloudscraper doesn't pass Cloudflare there)
pip install requests beautifulsoup4 curl_cffi
```

`curl_cffi` is the primary Cloudflare bypass (browser TLS impersonation). If not installed, falls back to `cloudscraper`, then plain `requests`. `beautifulsoup4` is kept for any remaining HTML parsing.

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
| `ShowtimeFetcher` | Fetches showtimes via AMC GraphQL API; parses formats and times |
| `MovieTracker` | Tracks one movie at one theater; caches results per date to detect changes |
| `MonitorManager` | Background thread; checks all trackers every N seconds (default 300s) |
| `BotCommandHandler` | Routes commands and manages per-user conversation state machine |

### Cloudflare / HTTP

All AMC data now comes from the **GraphQL API at `https://graph.amctheatres.com`**, not HTML scraping. AMC's website pages are protected by queue-it (a JS challenge that can't be solved without real browser execution).

Two module-level sessions in `bot.py`:
- `_amc_scraper` — for any remaining HTML requests (curl_cffi chrome110 → cloudscraper → requests)
- `_gql_session` — dedicated GraphQL session (always curl_cffi chrome110 if available)

`_graphql(query)` is the helper used by `NowPlayingFetcher` and `ShowtimeFetcher`. GraphQL headers include `Origin` and `Referer` pointing to `amctheatres.com` — required for the API to accept requests.

`theaters.json` now includes a `theatre_id` numeric field for each theater (the AMC internal ID required for GraphQL showtime queries). The `_THEATRE_ID_CACHE` dict maps slug→id and is populated at startup from `theaters.json`.

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
