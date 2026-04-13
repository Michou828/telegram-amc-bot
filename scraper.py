try:
    from seleniumbase import SB
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("Warning: seleniumbase not installed. Will use system Chrome fallback.")

from curl_cffi import requests
import datetime
import subprocess
import threading
import time
import re
import json
import os
import platform
import shutil

# UC mode requires x86 — skip entirely on ARM to avoid seleniumbase downloading an x86 driver then failing
_IS_ARM = platform.machine().startswith(("aarch", "arm"))

CACHE_FILE = "cache.json"
HARVEST_COOLDOWN = 1800  # 30 min cooldown after a failed harvest

# cf_clearance is bound to the User-Agent used during harvest.
# curl_cffi impersonates chrome124 on Mac — Chrome must use the same UA so the cookie validates.
HARVEST_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

class AMCScraper:
    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self.cookies = {}
        self.movie_list_cache = {"now-playing": [], "coming-soon": []}
        self.last_list_refresh = 0
        self.last_cookie_harvest = 0
        self.last_successful_fetch = 0   # last time get_page_data returned HTML
        self.last_failed_fetch = 0       # last time get_page_data returned None
        self.last_fail_reason = ""       # human-readable reason for last failure
        self._harvest_cooldown_until = 0  # runtime only, not persisted
        self._session_harvest_at = 0     # runtime only — set only when Chrome actually ran this session
        self._harvest_lock = threading.Lock()  # prevents concurrent Chrome launches
        self.load_cache()

    def load_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    data = json.load(f)
                    self.cookies = data.get("cookies", {})
                    self.movie_list_cache = data.get("movie_list", {"now-playing": [], "coming-soon": []})
                    self.last_list_refresh = data.get("last_list_refresh", 0)
                    self.last_cookie_harvest = data.get("last_cookie_harvest", 0)
                    self.last_successful_fetch = data.get("last_successful_fetch", 0)
                    self.last_failed_fetch = data.get("last_failed_fetch", 0)
                    self.last_fail_reason = data.get("last_fail_reason", "")
                    for name, value in self.cookies.items():
                        self.session.cookies.set(name, value, domain=".amctheatres.com")
            except Exception as e:
                print(f"Failed to load cache: {e}")

    def save_cache(self):
        try:
            data = {
                "cookies": self.cookies,
                "movie_list": self.movie_list_cache,
                "last_list_refresh": self.last_list_refresh,
                "last_cookie_harvest": self.last_cookie_harvest,
                "last_successful_fetch": self.last_successful_fetch,
                "last_failed_fetch": self.last_failed_fetch,
                "last_fail_reason": self.last_fail_reason,
            }
            with open(CACHE_FILE, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Failed to save cache: {e}")

    def _default_harvest_url(self):
        """Use a showtime page — required to trigger QueueITAccepted cookie."""
        today = datetime.date.today().strftime("%Y-%m-%d")
        return f"https://www.amctheatres.com/movie-theatres/new-york-city/amc-lincoln-square-13/showtimes?date={today}"

    def _store_cookies(self, cookie_list):
        self.cookies = {c['name']: c['value'] for c in cookie_list}
        self.session.cookies.clear()  # remove stale cookies before loading fresh ones
        for name, value in self.cookies.items():
            self.session.cookies.set(name, value, domain=".amctheatres.com")
        self.last_cookie_harvest = time.time()
        self._session_harvest_at = time.time()  # marks that Chrome actually ran this session
        self.save_cache()
        cookie_names = ", ".join(sorted(self.cookies.keys()))
        print(f"Stored {len(self.cookies)} cookies: {cookie_names}")

    def harvest_cookies(self, target_url=None, force=False):
        if target_url is None:
            target_url = self._default_harvest_url()

        # Only one Chrome instance at a time — second caller waits, then reuses fresh cookies
        if not self._harvest_lock.acquire(blocking=True, timeout=300):
            print("Harvest lock timed out — skipping.")
            return False
        try:
            # If another caller ran Chrome within the last 2 min, reuse those cookies.
            # force=True bypasses this — used by /refresh so it always runs Chrome.
            if not force and self._session_harvest_at and time.time() - self._session_harvest_at < 120:
                print("[Harvest] Cookies recently harvested — reusing.")
                return True
            return self._do_harvest(target_url)
        finally:
            self._harvest_lock.release()

    def _do_harvest(self, target_url):
        last_err = "Unknown error"
        for attempt in range(1, 3):
            print(f"[Harvest] Attempt {attempt}/2...")

            # UC mode only on attempt 1, and only on x86 — ARM can't run seleniumbase's bundled driver
            if SELENIUM_AVAILABLE and attempt == 1 and not _IS_ARM:
                print("[Harvest] Trying UC mode...")
                try:
                    with SB(uc=True, headless=True) as sb:
                        sb.uc_open_with_reconnect(target_url, 4)
                        time.sleep(15)
                        sb_cookies = sb.get_cookies()
                        self._store_cookies(sb_cookies)
                        print("[Harvest] UC mode succeeded.")
                        return True
                except Exception as e:
                    last_err = f"UC mode: {e}"
                    print(f"[Harvest] UC mode failed: {e} — trying system Chrome...")

            # System Chrome fallback — longer wait on attempt 2
            wait_secs = 45 if attempt == 1 else 60
            ok, err = self._harvest_with_system_chrome(target_url, wait_secs=wait_secs)
            if ok:
                return True
            last_err = err
            print(f"[Harvest] Attempt {attempt}/2 failed: {err}")
            if attempt == 1:
                print("[Harvest] Waiting 10s before retry...")
                time.sleep(10)

        reason = f"Harvest failed after 2 attempts. Last error: {last_err}"
        self.last_fail_reason = reason
        self.last_failed_fetch = time.time()
        self._harvest_cooldown_until = time.time() + HARVEST_COOLDOWN
        print(f"[Harvest] Cooldown set for {HARVEST_COOLDOWN // 60} minutes.")
        self.save_cache()
        return False

    def _harvest_with_system_chrome(self, target_url, wait_secs=45):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service as ChromeService
            from selenium.webdriver.chrome.options import Options

            # Check system paths first — avoids picking up seleniumbase's bundled x86 drivers
            system_chromium = next((p for p in ["/usr/bin/chromium", "/usr/bin/chromium-browser"] if os.path.exists(p)), None)
            chromium_bin = system_chromium or shutil.which("chromium") or shutil.which("chromium-browser")

            system_chromedriver = next((p for p in ["/usr/bin/chromedriver", "/usr/local/bin/chromedriver"] if os.path.exists(p)), None)
            chromedriver_bin = system_chromedriver or shutil.which("chromedriver")

            print(f"[Harvest] Starting headless Chrome ({chromium_bin}), driver ({chromedriver_bin}), wait={wait_secs}s...")
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-setuid-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-zygote")           # saves ~30MB on ARM
            options.add_argument("--single-process")      # fits in 512MB Pi RAM
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-background-networking")
            options.add_argument("--disable-default-apps")
            options.add_argument("--disable-sync")
            options.add_argument("--no-first-run")
            options.add_argument(f"--user-agent={HARVEST_USER_AGENT}")  # must match curl_cffi UA — cf_clearance is UA-bound
            options.add_argument("--disable-blink-features=AutomationControlled")  # hide navigator.webdriver from Cloudflare
            options.add_argument("--blink-settings=imagesEnabled=false")  # skip images
            options.add_argument("--js-flags=--max-old-space-size=128")   # limit JS heap
            options.page_load_strategy = "none"  # don't wait for full page load
            options.binary_location = chromium_bin

            driver = None
            try:
                driver = webdriver.Chrome(service=ChromeService(chromedriver_bin), options=options)
                driver.get(target_url)
                time.sleep(wait_secs)  # wait for Cloudflare + queue-it JS to complete
                selenium_cookies = driver.get_cookies()
            finally:
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                # Hard kill any surviving chromium/chromedriver processes — driver.quit()
                # can silently fail if Chrome crashed (OOM etc.), leaving RAM-hungry zombies
                for proc in ("chromedriver", "chromium", "chromium-browser"):
                    subprocess.run(["pkill", "-f", proc], capture_output=True)
                print("[Harvest] Chrome processes cleaned up.")

            if not selenium_cookies:
                raise Exception("Browser returned no cookies")

            self._store_cookies(selenium_cookies)
            return True, ""

        except Exception as e:
            return False, f"System Chrome: {e}"

    def get_page_data(self, url):
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.amctheatres.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            if response.status_code == 200 and "cookietest=1" not in response.text:
                self.last_successful_fetch = time.time()
                return response.text

            # Blocked — check cooldown before attempting harvest
            if time.time() < self._harvest_cooldown_until:
                remaining = int((self._harvest_cooldown_until - time.time()) / 60)
                reason = f"Blocked (status={response.status_code}), harvest cooldown active ({remaining}m remaining)"
                print(reason)
                self.last_failed_fetch = time.time()
                self.last_fail_reason = reason
                self.save_cache()
                return None

            print(f"Blocked (status={response.status_code}), harvesting cookies from showtime URL...")
            if self.harvest_cookies():  # always harvest from showtime URL — required for QueueITAccepted cookie
                # Don't re-fetch immediately — cookies need a moment to be recognized.
                # The next call to get_page_data will succeed with the fresh cookies.
                print("Harvest succeeded — fresh cookies ready for next request.")
                self.last_fail_reason = "Harvest succeeded — next request should work."
                self.save_cache()
                return None
            # harvest_cookies already set last_fail_reason on failure

        except Exception as e:
            reason = f"Request exception: {e}"
            print(reason)
            self.last_failed_fetch = time.time()
            self.last_fail_reason = reason
            self.save_cache()
        return None

    def parse_showtimes(self, html):
        """Returns showtimes keyed by movie SLUG for 100% matching accuracy."""
        if not html: return {}

        results = {}  # { movie_slug: { format_name: [times] } }

        chunks = re.findall(r'self\.__next_f\.push\(\[\d+,(?:"(.*?)"|null)\]\)', html, re.DOTALL)
        full_data = "".join([c for c in chunks if c]).replace('\\"', '"').replace('\\\\', '\\')

        if not full_data: return {}

        movie_matches = list(re.finditer(r'{"avatarImage":{.*?},"name":"([^"]+)","slug":"([^"]+)"', full_data))
        format_matches = list(re.finditer(r'"h3",null,{"id":"[^"]+","children":.*?{"children":"([^"]+)"}', full_data))
        showtime_matches = list(re.finditer(r'{"showtimeId":(\d+),"policyCodes".*?"display":{"time":"([^"]+)","amPm":"([^"]+)"}', full_data))

        if not showtime_matches:
            showtime_matches = list(re.finditer(r'{"showtimeId":(\d+),.*?"display":{"time":"([^"]+)","amPm":"([^"]+)"}', full_data))

        for s in showtime_matches:
            time_val = f"{s.group(2)}{s.group(3)}"
            pos = s.start()

            current_slug = "unknown"
            movie_pos = -1
            for m in reversed(movie_matches):
                if m.start() < pos:
                    current_slug = m.group(2)
                    movie_pos = m.start()
                    break

            current_format = "Standard"
            for f in reversed(format_matches):
                if f.start() < pos and f.start() > movie_pos:
                    current_format = f.group(1).replace('\\u0026', '&')
                    break

            if current_slug not in results:
                results[current_slug] = {}
            if current_format not in results[current_slug]:
                results[current_slug][current_format] = []
            if time_val not in results[current_slug][current_format]:
                results[current_slug][current_format].append(time_val)

        return results

    def get_movies_list(self, list_type="now-playing"):
        if time.time() - self.last_list_refresh < 43200 and self.movie_list_cache.get(list_type):
            return self.movie_list_cache[list_type]

        url = f"https://www.amctheatres.com/movies?movie-list={list_type}"
        html = self.get_page_data(url)
        if not html:
            # Movies URL sometimes needs an extra moment after harvest — retry once
            print(f"[MovieList] {list_type}: first fetch blocked, retrying in 5s...")
            time.sleep(5)
            html = self.get_page_data(url)
        if not html:
            print(f"[MovieList] {list_type}: both fetches blocked, using cache ({len(self.movie_list_cache.get(list_type, []))} entries)")
            return self.movie_list_cache.get(list_type, [])

        # Extract release dates from RSC chunks (coming-soon pages only)
        release_dates = {}
        if list_type == "coming-soon":
            chunks = re.findall(r'self\.__next_f\.push\(\[\d+,(?:"(.*?)"|null)\]\)', html, re.DOTALL)
            full_data = "".join([c for c in chunks if c]).replace('\\"', '"').replace('\\\\', '\\')
            # Try multiple date patterns AMC uses in their JSON data
            for pattern in [
                r'"slug":"([a-z0-9-]+-\d+)"[^}]*"releaseDate":"(\d{4}-\d{2}-\d{2})"',
                r'"slug":"([a-z0-9-]+-\d+)"[^}]*"openDate":"(\d{4}-\d{2}-\d{2})"',
                r'"releaseDate":"(\d{4}-\d{2}-\d{2})"[^}]*"slug":"([a-z0-9-]+-\d+)"',
            ]:
                for m in re.finditer(pattern, full_data):
                    slug_g, date_g = (m.group(1), m.group(2)) if 'slug' in pattern.split('"releaseDate"')[0] else (m.group(2), m.group(1))
                    release_dates[slug_g] = date_g

        movies = []
        seen_slugs = set()
        matches = re.findall(r'/movies/([a-z0-9-]+-(\d+))', html)
        for slug, movie_id in matches:
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            name_parts = slug.split('-')[:-1]
            name = " ".join(name_parts).title().replace("A M C", "AMC").replace("Imax", "IMAX").replace("Q A", "Q&A")
            movie_obj = {
                "name": name,
                "slug": slug,
                "url": f"https://www.amctheatres.com/movies/{slug}",
                "release_date": release_dates.get(slug),
            }
            movies.append(movie_obj)

        self.movie_list_cache[list_type] = movies
        self.last_list_refresh = time.time()
        self.save_cache()
        return movies

    def refresh_movie_list(self):
        """Force-fetch now-playing and coming-soon lists, bypassing the 12h cache. Returns counts dict."""
        counts = {}
        for list_type in ("now-playing", "coming-soon"):
            saved = self.last_list_refresh
            self.last_list_refresh = 0
            movies = self.get_movies_list(list_type)
            if not movies:
                self.last_list_refresh = saved
            counts[list_type] = len(movies)
            print(f"[MovieList] {list_type}: {len(movies)} movies")
        return counts

if __name__ == "__main__":
    scraper = AMCScraper()
    movies = scraper.get_movies_list()
    print(f"Found {len(movies)} movies.")
