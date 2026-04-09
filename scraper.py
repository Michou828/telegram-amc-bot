try:
    from seleniumbase import SB
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("Warning: seleniumbase not installed. Will use system Chrome fallback.")

from curl_cffi import requests
import datetime
import threading
import time
import re
import json
import os
import shutil

CACHE_FILE = "cache.json"
HARVEST_COOLDOWN = 1800  # 30 min cooldown after a failed harvest

class AMCScraper:
    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self.cookies = {}
        self.movie_list_cache = {"now-playing": [], "coming-soon": []}
        self.last_list_refresh = 0
        self.last_cookie_harvest = 0
        self._harvest_cooldown_until = 0  # runtime only, not persisted
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
        for name, value in self.cookies.items():
            self.session.cookies.set(name, value, domain=".amctheatres.com")
        self.last_cookie_harvest = time.time()
        self.save_cache()
        print(f"Stored {len(self.cookies)} cookies.")

    def harvest_cookies(self, target_url=None):
        if target_url is None:
            target_url = self._default_harvest_url()

        # Only one Chrome instance at a time — second caller waits, then reuses fresh cookies
        if not self._harvest_lock.acquire(blocking=True, timeout=300):
            print("Harvest lock timed out — skipping.")
            return False
        try:
            return self._do_harvest(target_url)
        finally:
            self._harvest_lock.release()

    def _do_harvest(self, target_url):
        # Try UC mode first — best stealth, works on Mac/x86
        if SELENIUM_AVAILABLE:
            print("Trying UC mode cookie harvest...")
            try:
                with SB(uc=True, headless=True) as sb:
                    sb.uc_open_with_reconnect(target_url, 4)
                    time.sleep(15)
                    sb_cookies = sb.get_cookies()
                    self._store_cookies(sb_cookies)
                    return True
            except Exception as e:
                print(f"UC mode failed: {e} — trying system Chrome fallback...")

        # Fallback: raw selenium with system chromedriver (ARM-compatible, Pi)
        return self._harvest_with_system_chrome(target_url)

    def _harvest_with_system_chrome(self, target_url):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service as ChromeService
            from selenium.webdriver.chrome.options import Options

            # Check system paths first — avoids picking up seleniumbase's bundled x86 drivers
            system_chromium = next((p for p in ["/usr/bin/chromium", "/usr/bin/chromium-browser"] if os.path.exists(p)), None)
            chromium_bin = system_chromium or shutil.which("chromium") or shutil.which("chromium-browser")

            system_chromedriver = next((p for p in ["/usr/bin/chromedriver", "/usr/local/bin/chromedriver"] if os.path.exists(p)), None)
            chromedriver_bin = system_chromedriver or shutil.which("chromedriver")

            print(f"Starting headless Chrome ({chromium_bin}) with driver ({chromedriver_bin})...")
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-extensions")
            options.add_argument("--blink-settings=imagesEnabled=false")  # skip images
            options.add_argument("--js-flags=--max-old-space-size=128")   # limit JS heap
            options.page_load_strategy = "none"  # don't wait for full page load
            options.binary_location = chromium_bin

            driver = webdriver.Chrome(service=ChromeService(chromedriver_bin), options=options)
            driver.get(target_url)
            time.sleep(45)  # wait for Cloudflare + queue-it JS to complete
            selenium_cookies = driver.get_cookies()
            driver.quit()

            if not selenium_cookies:
                raise Exception("Browser returned no cookies")

            self._store_cookies(selenium_cookies)
            return True

        except Exception as e:
            print(f"System Chrome harvest failed: {e}")
            self._harvest_cooldown_until = time.time() + HARVEST_COOLDOWN
            print(f"Harvest cooldown set for {HARVEST_COOLDOWN // 60} minutes.")
            return False

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
                return response.text

            # Blocked — check cooldown before attempting harvest
            if time.time() < self._harvest_cooldown_until:
                remaining = int((self._harvest_cooldown_until - time.time()) / 60)
                print(f"Blocked but harvest cooldown active ({remaining}m remaining). Skipping.")
                return None

            print(f"Blocked (status={response.status_code}), attempting cookie harvest...")
            if self.harvest_cookies():
                response = self.session.get(url, headers=headers, timeout=30)
                return response.text if response.status_code == 200 else None

        except Exception as e:
            print(f"Request error: {e}")
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
        if not html: return self.movie_list_cache.get(list_type, [])

        movies = []
        matches = re.findall(r'/movies/([a-z0-9-]+-(\d+))', html)
        for slug, movie_id in matches:
            name_parts = slug.split('-')[:-1]
            name = " ".join(name_parts).title().replace("A M C", "AMC").replace("Imax", "IMAX").replace("Q A", "Q&A")
            movie_obj = {"name": name, "slug": slug}
            if movie_obj not in movies:
                movies.append(movie_obj)

        self.movie_list_cache[list_type] = movies
        self.last_list_refresh = time.time()
        self.save_cache()
        return movies

if __name__ == "__main__":
    scraper = AMCScraper()
    movies = scraper.get_movies_list()
    print(f"Found {len(movies)} movies.")
