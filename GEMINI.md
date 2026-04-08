# AMC Showtime Monitor Bot - Gemini Guidelines

- **Hardware Constraint (CRITICAL)**: The bot is designed for a **Raspberry Pi Zero 2 W (512MB RAM)**. 
    - Every tool, library, and logic block MUST prioritize low memory usage.
    - Full browsers (SeleniumBase/Chrome) are restricted to **on-demand cookie harvesting ONLY**. They must never be the primary scraping engine.
    - Normal polling and bot operations must stay within a ~50MB RAM footprint using lightweight tools like `curl_cffi` and `sqlite3`.
- **Python Environment**: Always use the virtual environment located at `./venv` or `./.venv`.
- **Security & Credentials**: 
    - Load all sensitive data via `python-dotenv` from a local `.env` file.
    - NEVER print credentials in logs or tool outputs.
- **Scraping Architecture**:
    - **Hybrid Engine**: Use `seleniumbase` (UC Mode) sparingly for cookie harvesting and `curl_cffi` for primary lightweight polling.
    - **Persistence**: Save harvested cookies and movie metadata to a `cache.json` file to survive restarts and minimize browser launches.
    - **Market-Aware URLs**: Always include the regional market slug (e.g., `/new-york-city/`) in theatre URLs. AMC's server hides showtime data in the lightweight stream if the market is missing.
    - **Detection Bypass**: Solve JS challenges in a stealth browser to obtain `cf_clearance` and `QueueITAccepted` cookies.
    - **Data Extraction**: Target the Next.js React Server Component (RSC) hydration stream (`self.__next_f.push`) for 100% data accuracy.
- **Bot Integrity & Logic**:
    - **Owner ID**: Restrict all bot interactions to the verified `CHAT_ID` from `.env`.
    - **Deduplication**: All movie lists (Now Playing + Coming Soon) MUST be deduplicated by their unique slug before matching or display.
    - **Immediate Feedback**: Every tracking task setup should trigger an immediate background poll to provide instant confirmation of current showtimes.
    - **Non-Blocking**: Use `asyncio.to_thread` for all scraper calls to ensure the Telegram bot remains responsive during RAM-intensive operations.

