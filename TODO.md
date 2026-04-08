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

## Phase 4: Raspberry Pi Deployment [PENDING]
- [ ] Performance Tuning: Final RAM footprint check
- [ ] ARM Compatibility: Verify `curl_cffi` wheel on Pi architecture
- [ ] Systemd Service: Automated startup script
- [ ] Error Recovery: Automated Selenium refresh on long-term cookie expiry

## Phase 5: Polish & Feature Expansion [PENDING]
- [ ] Direct Booking Links: Refining the Next.js deep link format
- [ ] Maintenance Mode: Command to force cookie refresh manually
