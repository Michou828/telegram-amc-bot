# AMC Showtime Bot - Project TODO List

## Phase 1: Research & Scraper Validation [COMPLETED]
- [x] Environment Setup (Python venv, libraries)
- [x] Connectivity Test (curl_cffi initial testing)
- [x] Stealth Bypass Testing (SeleniumBase UC mode)
- [x] Hybrid Strategy Implementation (Cookie harvesting + curl_cffi polling)
- [x] RSC Hydration Data Extraction (accurate parsing of streamed Next.js data)
- [x] Format & Theater Data Isolation (Verified correctly grouping IMAX, Dolby, Open Caption, etc.)
- [x] Cross-Check Verification (Verified Mario @ Lincoln Square on 4/11)

## Phase 2: Bot Foundation [COMPLETED]
- [x] Initialize Telegram Bot (`python-telegram-bot`)
- [x] Implement Security: Owner-only access check (User ID validation)
- [x] Implement Basic Commands: `/start`, `/help`, `/check`, `/track`, `/list`, `/remove`, `/status`
- [x] Robust Movie Matching: Token-based logic ("Prada2" -> "The Devil Wears Prada 2")
- [x] Multi-Match Handling: Menus for ambiguous movie names
- [x] Format Checklist UI: Persistent checklist with ✅ checkmarks
- [x] Responsive UI: Non-blocking background threads for scraping
- [x] Advance Ticket Support: Handling "Coming Soon" movies

## Phase 3: Monitoring & Persistence [COMPLETED]
- [x] Database Setup: SQLite schema for user preferences and "seen" showtimes
- [x] Polling Engine: Background loop with grouped notifications
- [x] Persistent Session: Disk-based `cache.json` for cookies and movie lists
- [x] Immediate Feedback: Trigger poll instantly after tracking setup
- [x] Date Validation: Past date rejection and range support (`M/D-M/D`)

## Phase 4: Raspberry Pi Deployment [COMPLETED]
- [x] ARM Compatibility: `curl_cffi` wheel verified on Pi Zero 2 W (aarch64)
- [x] ARM Chrome: System `chromium` + `chromedriver` via `apt` — seleniumbase x86 driver bypassed
- [x] OOM Protection: `threading.Lock` mutex prevents concurrent Chrome launches (512MB RAM)
- [x] ChromeDriver Timeout Fix: `page_load_strategy="none"` prevents 120s read timeout on slow Pi
- [x] Harvest URL Fix: Harvest from showtime page (not `/movies`) to get `QueueITAccepted` cookie
- [x] Systemd Service: `amc-showtime-bot.service` with venv Python, auto-restart
- [x] Error Recovery: 30-min cooldown after failed harvest; `/refresh` command for manual re-harvest

## Phase 5: Polish & Feature Expansion [IN PROGRESS]
- [x] Maintenance Mode: `/refresh` command to force cookie harvest manually
- [x] `🆕` Badge: Formats first seen within 24h marked in both `/check` and poll notifications
- [ ] Direct Booking Links: Refining the Next.js deep link format for ticket purchase URLs
- [ ] `harvest.py`: Standalone Mac script for manual cookie refresh and transfer to Pi
