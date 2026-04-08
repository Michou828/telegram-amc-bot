# AMC Scraping & Bot Detection Bypass Guide

This document details the technical strategy for scraping showtimes from the AMC Theatres website while bypassing aggressive bot protections.

## 1. Bot Detection Landscape
AMC employs two primary layers of protection:
- **Cloudflare**: Validates TLS fingerprints and browser integrity.
- **Queue-it**: A waiting-room system that uses a JavaScript-based cookie test (`cookietest=1`) to verify the client is a real browser.

## 2. Bypass Strategy: The Hybrid Approach
To balance reliability with resource efficiency (especially for Raspberry Pi deployment), we use a hybrid strategy:

### Layer A: Cookie Harvesting (Heavyweight)
- **Tool**: `seleniumbase` in **Undetected-Chromedriver (UC)** mode.
- **Purpose**: Mimics a real user, handles the JavaScript execution required by Queue-it, and solves Cloudflare challenges.
- **Output**: Harvests `cf_clearance` and `QueueITAccepted` cookies.
- **Frequency**: Triggered only on initial startup or when Layer B encounters a 403 Forbidden / Redirect.

### Layer B: High-Frequency Polling (Lightweight)
- **Tool**: `curl_cffi`.
- **Purpose**: Executes extremely fast, low-memory requests that impersonate modern browser TLS fingerprints (e.g., `chrome124`).
- **Implementation**: Injects the harvested cookies into the `curl_cffi` session headers.
- **Benefit**: Allows 5-10 minute polling intervals without the overhead of a full browser.

## 3. Data Extraction: RSC Hydration Parsing
AMC uses **Next.js React Server Components (RSC)**. Standard HTML parsing (BeautifulSoup) is insufficient because showtimes are "streamed" in encoded JavaScript chunks.

### The Mechanism
The scraper targets `<script>` tags containing `self.__next_f.push`.
1. **Extraction**: Regex isolates the data payload from the hydration stream.
2. **Reconstruction**: Chunks are concatenated and unescaped into a single data stream.
3. **URL Criticality**: URLs **MUST** include the market slug (e.g., `/new-york-city/`) and the theatre slug. Without the market, AMC serves a "hollow" page without hydration data for the lightweight fetcher.
4. **Targeting**:
   - **Movies**: Identified by the `name` and `slug` keys. 
   - **Formats**: Identified by `h3` tags containing format names (e.g., "IMAX with Laser").
   - **Showtimes**: Identified by `showtimeId` objects containing `display.time` and `display.amPm`.
5. **Association**: Showtimes are associated with the closest preceding Format Header, which is in turn associated with the closest preceding Movie entry in the stream. 

## 4. Matching Logic (Accuracy & Fuzzy)
To handle user input and site variations, the bot employs a multi-tiered matching system:

### Movie Matching (Slug-First)
- **Tokenization**: Input like "Prada2" is split into "Prada" and "2".
- **Validation**: All tokens must exist in either the movie title or the movie slug.
- **Slug Key**: Once matched, all internal logic uses the movie's unique **Slug** (e.g., `the-devil-wears-prada-2-80466`) to ensure the background poll perfectly identifies the correct title.

### Format Matching (Substring)
- Users select generic formats (IMAX, Dolby, Laser).
- The bot uses **Substring Matching** (e.g., `'imax' in 'IMAX with Laser at AMC'`) to bridge the gap between simple buttons and verbose marketing names.

## 5. Key Performance Indicators (KPIs)
- **Isolation**: Only showtimes for the specific theater in the URL are returned.
- **Granularity**: Full support for IMAX, Dolby, 3D, Open Caption, and 70mm.
- **Stealth**: Rotating User-Agents and random jitter (±30s) are used to prevent IP-based rate limiting.
- **RAM Efficiency**: Primary fetcher stays under 50MB; full browser is invoked only for 403 recovery.
