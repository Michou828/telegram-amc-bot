# AMC Showtime Monitor Bot

A Telegram bot that monitors AMC movie showtimes and sends notifications when new showtimes appear.

## Features

- Track any AMC movie at any theater
- Get notified the moment showtimes go on sale
- Support for specific formats: IMAX, DOLBY, 3D, PRIME, DBOX, 4DX, SCREENX
- Monitor multiple movies and date ranges simultaneously
- Manual showtime lookup with `/check`
- Remove individual tracked movies with `/remove`

## Commands

| Command | Description |
|---|---|
| `/track` | Start monitoring a movie |
| `/check` | Look up showtimes once without tracking |
| `/list` | Show all currently tracked movies |
| `/remove` | Stop tracking a specific movie |
| `/status` | Show bot status and number of tracked movies |
| `/interval <seconds>` | Change how often the bot checks (default 300s) |
| `/stop` | Stop all monitoring |
| `/help` | Show help |

## How to Use

1. Send `/track`
2. Pick a movie from the list or paste an AMC movie URL
3. Enter the theater name (supports fuzzy search)
4. Enter a date or date range — `04/10` or `04/10/2026` or `04/10>04/20`
5. Choose formats to track (e.g. `IMAX, DOLBY`) or `any`
6. The bot will notify you as soon as showtimes appear

## Setup

### Requirements

```bash
pip install requests beautifulsoup4 cloudscraper
```

### Environment Variables

Create a `.env` file:
```
BOT_TOKEN=your_telegram_bot_token
CHAT_ID=your_telegram_chat_id
```

### Run Locally

```bash
./start.sh
```

### Deploy to Server

See [deploy.md](deploy.md) for full Google Cloud deployment and update instructions.

## Project Structure

| File | Description |
|---|---|
| `bot.py` | Main application — all bot logic |
| `theater_matcher.py` | Fuzzy theater name search |
| `theaters.json` | NYC metro area AMC theater database |
| `start.sh` | Local startup script |
| `deploy.md` | Server deployment & update guide |
