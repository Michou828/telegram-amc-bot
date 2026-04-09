# AMC Scraping & Bot Detection Bypass Guide

This document details the technical strategy for scraping showtimes from the AMC Theatres website while bypassing aggressive bot protections.

## 1. Bot Detection Landscape

AMC employs two primary layers of protection:

- **Cloudflare**: Validates TLS fingerprints and browser integrity. Sets the `cf_clearance` cookie.
- **Queue-it**: A waiting-room system that uses a JavaScript-based cookie test (`cookietest=1`) to verify the client is a real browser. Sets the `QueueITAccepted` cookie.

**Critical**: The `QueueITAccepted` cookie is only issued when visiting a **showtime page** (e.g., `/movie-theatres/<market>/<theater>/showtimes?date=<date>`). Harvesting from the `/movies` page will get Cloudflare cookies but NOT Queue-it cookies — the bot will still be blocked.

## 2. Bypass Strategy: The Hybrid Approach

To balance reliability with resource efficiency, we use a two-layer hybrid strategy:

### Layer A: Cookie Harvesting (Heavyweight)

- **Tool**: Real headless Chrome via Selenium.
- **Purpose**: Executes the JavaScript required by Cloudflare and Queue-it challenges. Harvests both `cf_clearance` and `QueueITAccepted` cookies.
- **Harvest URL**: Must be a showtime page — `https://www.amctheatres.com/movie-theatres/new-york-city/amc-lincoln-square-13/showtimes?date=<today>`
- **Frequency**: Triggered on startup if no cached cookies, or when Layer B gets blocked (403 / `cookietest=1` response).
- **Sleep**: 45 seconds after page load to allow JS challenges to complete.

### Layer B: High-Frequency Polling (Lightweight)

- **Tool**: `curl_cffi` with `chrome124` impersonation.
- **Purpose**: Fast, low-memory requests that impersonate browser TLS fingerprints. Injects harvested cookies from Layer A.
- **Benefit**: Handles 5-minute polling intervals without the overhead of a full browser launch.

### Cooldown

After a failed harvest (Chrome not available, OOM, etc.), a 30-minute cooldown is set (`HARVEST_COOLDOWN = 1800`). Layer B continues to attempt requests during cooldown but skips harvest retries. This prevents CPU/RAM thrashing on constrained hardware.

## 3. Chrome Driver Strategy

The scraper tries two methods in order:

### UC Mode (seleniumbase — Mac/x86 preferred)

```python
with SB(uc=True, headless=True) as sb:
    sb.uc_open_with_reconnect(target_url, 4)
    time.sleep(15)
```

UC mode patches ChromeDriver for maximum stealth. Works on Mac and x86 Linux. The `seleniumbase` import is conditional — if the package isn't installed, this is skipped.

### System Chrome Fallback (ARM/Pi compatible)

Used when `seleniumbase` is unavailable or UC mode fails. Uses raw selenium with the **system-installed** chromedriver:

```python
system_chromedriver = next((p for p in ["/usr/bin/chromedriver", "/usr/local/bin/chromedriver"] if os.path.exists(p)), None)
```

Explicit path check comes first to avoid accidentally picking up `seleniumbase`'s bundled x86 chromedriver (which fails with `Exec format error` on ARM).

**Critical flags for constrained hardware (Pi Zero 2 W):**

```python
options.page_load_strategy = "none"          # return immediately, don't wait for full load
options.add_argument("--blink-settings=imagesEnabled=false")  # skip images
options.add_argument("--js-flags=--max-old-space-size=128")   # limit JS heap to 128MB
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
```

`page_load_strategy = "none"` is essential — without it, `driver.get()` blocks until the page fully loads, which can take 120+ seconds on a Pi and trigger ChromeDriver's read timeout. With `"none"`, the call returns immediately and we `sleep(45)` to let the JS challenges complete in the background.

### Mutex (OOM protection)

A `threading.Lock` prevents concurrent Chrome launches:

```python
self._harvest_lock = threading.Lock()
if not self._harvest_lock.acquire(blocking=True, timeout=300):
    print("Harvest lock timed out — skipping.")
    return False
```

On a Pi Zero 2 W with 512MB RAM (~400MB usable after OS), two simultaneous Chrome instances will be OOM-killed. The lock ensures only one harvest runs at a time; the second caller waits and reuses the freshly harvested cookies.

## 4. Data Extraction: RSC Hydration Parsing

AMC uses **Next.js React Server Components (RSC)**. Showtimes are streamed in encoded JavaScript chunks — standard HTML parsing won't find them.

### Mechanism

The scraper targets `<script>` tags containing `self.__next_f.push`:

1. **Extraction**: Regex isolates data payloads from hydration chunks.
2. **Reconstruction**: All chunks are concatenated and unescaped (`\"` → `"`, `\\` → `\`).
3. **URL Criticality**: URLs **must** include the market slug (e.g., `/new-york-city/`) and theatre slug. Without the market, AMC serves a hollow page with no hydration data.
4. **Targeting**:
   - **Movies**: `{"avatarImage":{...},"name":"<title>","slug":"<slug>"}`
   - **Formats**: `"h3",null,{"id":"...","children":...{"children":"<format name>"}}`
   - **Showtimes**: `{"showtimeId":<id>,...,"display":{"time":"<time>","amPm":"<am/pm>"}}`
5. **Association**: Position-based — each showtime is associated with the closest preceding format header and movie entry in the stream.

## 5. Matching Logic

### Movie Matching (Slug-First)

User input is token-matched against movie slugs. Once matched, all internal logic uses the slug as the stable identifier (e.g., `the-devil-wears-prada-2-80466`).

### Format Matching (Substring)

User-facing format buttons (`IMAX`, `DOLBY`, etc.) are matched via substring to AMC's verbose marketing names (e.g., `"IMAX with Laser at AMC"`). This bridges user selection to actual site format strings.

### Format Normalization

Scraped format names are normalized before storage:

| Normalized | Example raw names |
|---|---|
| `IMAX 70MM` | "IMAX 70mm Film" |
| `IMAX` | "IMAX with Laser at AMC" |
| `DOLBY` | "Dolby Cinema at AMC" |
| `70MM` | "70mm Film" |
| `3D` | "3D" |
| `PRIME` | "Prime at AMC" |
| `DBOX` | "D-BOX" |
| `4DX` | "4DX" |
| `SCREENX` | "ScreenX" |

Anything not matched is kept as-is, uppercased.

## 6. Cache & Persistence

- **`cache.json`**: Cookies + movie list cache (12h TTL). Persists across restarts. Copying this file from Mac to Pi bootstraps the Pi without needing an immediate Chrome harvest.
- **`amc_bot.db`**: SQLite database. Stores tracked movies and `seen_showtimes` for deduplication. Also records `first_seen_at` timestamps per format, used to generate the `🆕` badge for formats first seen within the last 24 hours.

## 7. Raspberry Pi Zero 2 W Deployment Notes

- Install system Chrome (not from `pip`): `sudo apt install chromium chromium-driver`
- Verify: `chromium --version` and `chromedriver --version`
- Do NOT install `seleniumbase` — its bundled x86 chromedriver causes `Exec format error` on ARM
- The system path `/usr/bin/chromedriver` is what the scraper will use
- First harvest takes ~2 minutes (45s sleep + overhead) — normal
- Subsequent polls are fast `curl_cffi` requests (~1–2 seconds each)
- Only one Chrome at a time — the mutex handles this automatically
