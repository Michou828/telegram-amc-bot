#!/usr/bin/env python3
"""
AMC Showtime Monitor - Final Working Version
Correctly parses AMC's actual HTML structure
With fuzzy theater search
"""

import requests
try:
    import cloudscraper
except ImportError:
    cloudscraper = None
from bs4 import BeautifulSoup
import hashlib
import time
import json
import sys
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

NY_TZ = ZoneInfo('America/New_York')
KNOWN_FORMATS = ['IMAX 70MM', 'IMAX', 'DOLBY', '70MM', '3D', 'PRIME', 'DBOX', '4DX', 'SCREENX']

from theater_matcher import TheaterMatcher

CACHE_DIR = Path.home() / ".amc_monitors"
CACHE_DIR.mkdir(exist_ok=True)

# Shared HTTP session for AMC HTML pages (bypasses Cloudflare where possible)
try:
    from curl_cffi import requests as cffi_requests
    _amc_scraper = cffi_requests.Session(impersonate="chrome110")
    print("Using curl_cffi (chrome110 impersonation)")
except ImportError:
    if cloudscraper:
        _amc_scraper = cloudscraper.create_scraper()
        print("Using cloudscraper")
    else:
        _amc_scraper = requests.Session()
        print("WARNING: Neither curl_cffi nor cloudscraper available — plain requests")

# GraphQL API session (separate — always uses curl_cffi for TLS fingerprinting)
try:
    from curl_cffi import requests as _cffi
    _gql_session = _cffi.Session(impersonate="chrome110")
except ImportError:
    _gql_session = requests.Session()

GRAPHQL_URL = "https://graph.amctheatres.com"
GRAPHQL_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.amctheatres.com",
    "Referer": "https://www.amctheatres.com/",
}

# slug → numeric theatre_id lookup (populated from theaters.json)
_THEATRE_ID_CACHE: dict = {}

def _load_theatre_ids():
    """Load theatre slug→id mapping from theaters.json."""
    try:
        with open(Path(__file__).parent / "theaters.json") as f:
            data = json.load(f)
        for t in data.get("theaters", []):
            if t.get("theatre_id"):
                _THEATRE_ID_CACHE[t["slug"]] = t["theatre_id"]
    except Exception as e:
        print(f"Warning: could not load theatre IDs: {e}")

def _graphql(query: str) -> dict:
    """Execute a GraphQL query against the AMC API."""
    r = _gql_session.post(GRAPHQL_URL, headers=GRAPHQL_HEADERS,
                          json={"query": query}, timeout=20)
    r.raise_for_status()
    return r.json()

# Format name mapping: AMC API → our standardized KNOWN_FORMATS names
_API_FORMAT_MAP = {
    "imax with laser at amc": "IMAX",
    "imax at amc": "IMAX",
    "imax 70mm": "IMAX 70MM",
    "dolby cinema at amc": "DOLBY",
    "laser at amc": "PRIME",
    "reald 3d": "3D",
    "3d at amc": "3D",
    "d-box at amc": "DBOX",
    "d-box": "DBOX",
    "dbox": "DBOX",
    "4dx at amc": "4DX",
    "4dx": "4DX",
    "screenx": "SCREENX",
    "70mm": "70MM",
}

def _normalize_api_format(name: str) -> str:
    """Map an AMC API format attribute name to our standardized format name."""
    key = name.strip().lower()
    if key in _API_FORMAT_MAP:
        return _API_FORMAT_MAP[key]
    # Fallback: uppercase as-is
    return name.strip().upper()

class RecentMovies:
    """Track recently checked/tracked movies for quick access"""
    
    def __init__(self, cache_file: Path = CACHE_DIR / "recent_movies.json"):
        self.cache_file = cache_file
        self.movies = self._load()
    
    def _load(self) -> List[Dict]:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    return data.get('movies', [])
            except:
                return []
        return []
    
    def _save(self):
        try:
            with open(self.cache_file, 'w') as f:
                json.dump({'movies': self.movies}, f, indent=2)
        except Exception as e:
            print(f"Error saving recent movies: {e}")
    
    def add(self, movie_url: str, movie_name: str, movie_slug: str):
        """Add a movie to recent list (max 5)"""
        # Remove if already exists
        self.movies = [m for m in self.movies if m['slug'] != movie_slug]
        
        # Add to front
        self.movies.insert(0, {
            'url': movie_url,
            'name': movie_name,
            'slug': movie_slug,
            'last_used': datetime.now().isoformat()
        })
        
        # Keep only last 5
        self.movies = self.movies[:5]
        
        self._save()
    
    def get_recent(self, max_count: int = 5) -> List[Dict]:
        """Get recent movies"""
        return self.movies[:max_count]
    
    def get_buttons(self) -> List[List[Dict]]:
        """Get Telegram inline keyboard buttons for recent movies"""
        if not self.movies:
            return []
        
        buttons = []
        for movie in self.movies:
            buttons.append([{
                "text": f"🎬 {movie['name']}",
                "callback_data": f"movie:{movie['slug']}"
            }])
        
        return buttons


class NowPlayingFetcher:
    """Scrapes Now Playing movies from AMC website with in-memory caching"""

    MOVIES_URL = "https://www.amctheatres.com/movies"
    CACHE_TTL = 86400  # 24 hours

    def __init__(self):
        self._cache = None
        self._cache_time = 0

    def fetch(self, limit: int = 10) -> List[Dict]:
        """Returns list of {name, slug, url} for Now Playing movies via GraphQL API."""
        now = time.time()
        if self._cache is not None and (now - self._cache_time) < self.CACHE_TTL:
            return self._cache[:limit]

        try:
            data = _graphql(
                "{ viewer { movies(availability: NOW_PLAYING, first: 100) "
                "{ edges { node { name slug } } } } }"
            )
            edges = data["data"]["viewer"]["movies"]["edges"]
            movies = [
                {
                    "name": e["node"]["name"],
                    "slug": e["node"]["slug"],
                    "url": f"https://www.amctheatres.com/movies/{e['node']['slug']}",
                }
                for e in edges
            ]
            self._cache = movies
            self._cache_time = now
            print(f"Fetched {len(movies)} now playing movies from AMC GraphQL")
            return movies[:limit]
        except Exception as e:
            print(f"Error fetching now playing movies: {e}")
            return []

    def get_buttons(self, limit: int = 10) -> List[List[Dict]]:
        """Returns inline keyboard buttons for now playing movies"""
        movies = self.fetch(limit)
        return [[{"text": f"🎥 {m['name']}", "callback_data": f"nowplaying:{m['slug']}"}]
                for m in movies]


class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, chat_id: int, text: str, parse_mode: str = "HTML", 
                     reply_markup: Optional[Dict] = None):
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error sending message: {e}")
            return None
    
    def send_message_with_buttons(self, chat_id: int, text: str, buttons: List[List[Dict]], 
                                   parse_mode: str = "HTML"):
        """Send message with inline keyboard buttons
        
        buttons format: [
            [{"text": "Button 1", "callback_data": "data1"}, {"text": "Button 2", "callback_data": "data2"}],
            [{"text": "Button 3", "callback_data": "data3"}]
        ]
        """
        reply_markup = {
            "inline_keyboard": buttons
        }
        return self.send_message(chat_id, text, parse_mode, reply_markup)
    
    def get_updates(self, offset: Optional[int] = None, timeout: int = 30):
        url = f"{self.base_url}/getUpdates"
        params = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset:
            params["offset"] = offset
        
        try:
            response = requests.get(url, params=params, timeout=timeout+5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error getting updates: {e}")
            return None
    
    def answer_callback_query(self, callback_query_id: str, text: str = ""):
        """Answer a callback query (acknowledge button press)"""
        url = f"{self.base_url}/answerCallbackQuery"
        payload = {
            "callback_query_id": callback_query_id,
            "text": text
        }
        try:
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error answering callback: {e}")
            return None

    def edit_message_reply_markup(self, chat_id: int, message_id: int, buttons: List[List[Dict]]):
        """Edit the inline keyboard of an existing message"""
        url = f"{self.base_url}/editMessageReplyMarkup"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": {"inline_keyboard": buttons}
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error editing reply markup: {e}")
            return None

class AMCHelper:
    """Helper functions for AMC website interaction"""
    
    @staticmethod
    def extract_movie_slug(url: str) -> Optional[str]:
        """Extract movie slug from URL"""
        match = re.search(r'/movies/([^/]+)', url)
        return match.group(1) if match else None
    
    @staticmethod
    def slug_to_title(slug: str) -> str:
        """Convert URL slug to title case"""
        name = re.sub(r'-\d+$', '', slug)
        return name.replace('-', ' ').title()
    
    @staticmethod
    def theater_name_to_slug(name: str) -> str:
        """Convert theater name to URL slug"""
        slug = name.lower()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        return slug
    
    @staticmethod
    def parse_date_input(date_str: str) -> Tuple[List[str], str]:
        """Parse date or date range input"""
        date_str = date_str.strip()
        
        if '>' in date_str:
            parts = date_str.split('>')
            start_str = parts[0].strip()
            end_str = parts[1].strip()
            
            start_date = AMCHelper.parse_single_date(start_str)
            end_date = AMCHelper.parse_single_date(end_str)
            
            if not start_date or not end_date:
                return None, None
            
            dates = []
            current = start_date
            while current <= end_date:
                dates.append(current.strftime('%Y-%m-%d'))
                current += timedelta(days=1)
            
            display = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"
            return dates, display
        else:
            single_date = AMCHelper.parse_single_date(date_str)
            if not single_date:
                return None, None
            
            return [single_date.strftime('%Y-%m-%d')], single_date.strftime('%B %d, %Y')
    
    @staticmethod
    def parse_single_date(date_str: str) -> Optional[datetime]:
        """Parse a single date string in MM/DD/YYYY or MM/DD format.
        Year defaults to current year when omitted."""
        try:
            return datetime.strptime(date_str, '%m/%d/%Y')
        except ValueError:
            pass
        try:
            month, day = date_str.split('/')
            return datetime(datetime.now().year, int(month), int(day))
        except ValueError:
            pass
        return None
    
    @staticmethod
    def validate_theater(theater_input: str, movie_slug: str = None) -> Optional[Dict]:
        """Validate theater name and return standardized info
        
        If movie_slug is provided, validates that the theater actually exists
        by checking if the showtimes page loads.
        """
        slug = AMCHelper.theater_name_to_slug(theater_input)
        name = theater_input.strip()
        if not name.upper().startswith('AMC'):
            name = 'AMC ' + name
        
        result = {
            'name': name,
            'slug': slug,
            'valid': None  # None = not checked, True = valid, False = invalid
        }
        
        # If movie_slug provided, validate by testing the URL
        if movie_slug:
            test_url = f"https://www.amctheatres.com/movies/{movie_slug}/showtimes?theatre={slug}"
            try:
                response = _amc_scraper.get(test_url, timeout=10)
                
                # Check if we got a valid response
                if response.status_code == 200:
                    # Check if page contains theater name or showtime sections
                    page_lower = response.text.lower()
                    
                    # If page has "no theatre found" or similar error
                    if 'theatre not found' in page_lower or 'theater not found' in page_lower:
                        result['valid'] = False
                    else:
                        result['valid'] = True
                else:
                    result['valid'] = False
                    
            except Exception as e:
                print(f"Theater validation error: {e}")
                # If validation fails, assume it might be valid (network issue)
                result['valid'] = None
        
        return result

class ShowtimeFetcher:
    """Fetches showtimes from AMC GraphQL API."""

    def __init__(self):
        pass

    def _get_theatre_id(self, theater_slug: str) -> Optional[int]:
        """Return numeric theatreId for a slug, fetching from API if not cached."""
        if theater_slug in _THEATRE_ID_CACHE:
            return _THEATRE_ID_CACHE[theater_slug]
        try:
            data = _graphql(
                f'{{ viewer {{ theatre(slug: "{theater_slug}") {{ theatreId }} }} }}'
            )
            tid = data["data"]["viewer"]["theatre"]["theatreId"]
            if tid:
                _THEATRE_ID_CACHE[theater_slug] = tid
            return tid
        except Exception as e:
            print(f"Could not fetch theatreId for {theater_slug}: {e}")
            return None

    def get_showtimes_for_date(self, movie_slug: str, theater_slug: str, date: str) -> Dict:
        """Get showtimes for a specific date and theater via GraphQL API.

        date: YYYY-MM-DD format
        Returns {'available': bool, 'formats': {format_name: [HH:MM, ...]}}
        """
        theatre_id = self._get_theatre_id(theater_slug)
        if not theatre_id:
            print(f"No theatreId for {theater_slug} — cannot fetch showtimes")
            return {'available': False, 'formats': {}}

        query = f"""{{
          viewer {{
            movie(slug: "{movie_slug}") {{
              formats(theatreId: {theatre_id}) {{
                items {{
                  groups {{
                    edges {{
                      node {{
                        showtimeGroupHeadingAttribute {{ name }}
                        showtimes(first: 100) {{
                          edges {{ node {{ when businessDate }} }}
                        }}
                      }}
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}"""

        try:
            data = _graphql(query)
            movie_data = data.get("data", {}).get("viewer", {}).get("movie")
            if not movie_data or not movie_data.get("formats"):
                print(f"No movie/formats data for {movie_slug}")
                return {'available': False, 'formats': {}}

            formats_dict: Dict[str, List[str]] = {}

            for item in (movie_data["formats"]["items"] or []):
                for edge in item["groups"]["edges"]:
                    node = edge["node"]
                    raw_name = node["showtimeGroupHeadingAttribute"]["name"]
                    format_name = _normalize_api_format(raw_name)

                    times = []
                    for st_edge in node["showtimes"]["edges"]:
                        st = st_edge["node"]
                        if st["businessDate"] != date:
                            continue
                        # Convert UTC ISO to Eastern time HH:MM
                        utc_dt = datetime.fromisoformat(
                            st["when"].replace("Z", "+00:00")
                        )
                        et_dt = utc_dt.astimezone(NY_TZ)
                        times.append(et_dt.strftime("%H:%M"))

                    if times:
                        if format_name in formats_dict:
                            formats_dict[format_name] = sorted(
                                set(formats_dict[format_name] + times)
                            )
                        else:
                            formats_dict[format_name] = sorted(times)

            print(f"Found {len(formats_dict)} formats for {movie_slug} on {date}")
            for fmt, times in formats_dict.items():
                print(f"  {fmt}: {times}")

            return {'available': len(formats_dict) > 0, 'formats': formats_dict}

        except Exception as e:
            print(f"Error fetching showtimes via GraphQL: {e}")
            return {'available': False, 'formats': {}}

class MovieTracker:
    """Tracks a movie at a specific theater for specific dates"""
    
    def __init__(self, movie_url: str, movie_slug: str, movie_name: str, 
                 theater_name: str, theater_slug: str, dates: List[str], 
                 date_display: str, formats_filter: List[str]):
        self.movie_url = movie_url
        self.movie_slug = movie_slug
        self.movie_name = movie_name
        self.theater_name = theater_name
        self.theater_slug = theater_slug
        self.dates = dates
        self.date_display = date_display
        self.formats_filter = [f.upper() for f in formats_filter] if formats_filter else []
        
        self.cache_file = CACHE_DIR / f"{hashlib.md5(f'{movie_slug}-{theater_slug}-{dates[0]}'.encode()).hexdigest()}.json"
        self.fetcher = ShowtimeFetcher()
    
    def check_showtimes(self) -> Dict[str, Dict]:
        """Check showtimes for all tracked dates"""
        results = {}
        cache = self.load_cache()
        
        for date in self.dates:
            showtimes = self.fetcher.get_showtimes_for_date(
                self.movie_slug, self.theater_slug, date
            )
            
            # Apply format filtering (partial match)
            if self.formats_filter:
                filtered_formats = self._filter_formats(showtimes['formats'])
            else:
                filtered_formats = showtimes['formats']
            
            # Check if this is new data
            filtered_showtimes = {
                'available': len(filtered_formats) > 0,
                'formats': filtered_formats
            }
            is_new = self._is_new_data(date, filtered_showtimes, cache)
            previous_formats = cache.get('dates', {}).get(date, {}).get('formats', {})
            new_within_24h = self._get_new_within_24h(date, filtered_formats, cache)

            results[date] = {
                'available': len(filtered_formats) > 0,
                'formats': filtered_formats,
                'previous_formats': previous_formats,
                'new_within_24h': new_within_24h,
                'is_new': is_new
            }
        
        return results
    
    def _filter_formats(self, all_formats: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """Filter formats based on user's format filter (partial match)
        
        Example:
        - User wants: ['IMAX', 'DOLBY']
        - All formats: {'IMAX 70MM': [...], 'IMAX': [...], 'DOLBY': [...], '70MM': [...]}
        - Returns: {'IMAX 70MM': [...], 'IMAX': [...], 'DOLBY': [...]}
        """
        if not self.formats_filter:
            return all_formats
        
        filtered = {}
        for format_name, times in all_formats.items():
            # Check if any of the user's filters matches this format (partial match)
            for user_format in self.formats_filter:
                if user_format.upper() in format_name.upper():
                    filtered[format_name] = times
                    break
        
        return filtered
    
    def _is_new_data(self, date: str, current_data: Dict, cache: Dict) -> bool:
        """Check if showtime data is new or has changed since last notification"""
        if not current_data['available']:
            return False

        cached_dates = cache.get('dates', {})
        if date not in cached_dates:
            return True  # First time seeing showtimes for this date

        # Compare against last NOTIFIED formats (not last seen).
        # This prevents re-notification when AMC's page returns slightly
        # different data between fetches (fluctuating times, nearby theaters).
        last_notified = cached_dates[date].get('last_notified_formats')
        if last_notified is None:
            # Never notified yet — fall back to comparing against last seen
            return cached_dates[date].get('formats') != current_data['formats']
        return last_notified != current_data['formats']
    
    def _get_new_within_24h(self, date: str, formats: Dict, cache: Dict) -> set:
        """Return set of format names first seen within the last 24 hours"""
        first_seen = cache.get('dates', {}).get(date, {}).get('format_first_seen', {})
        cutoff = time.time() - 86400
        # Formats not yet in first_seen are brand new (first seen right now)
        return {fmt for fmt in formats if first_seen.get(fmt, time.time()) > cutoff}

    def save_results(self, results: Dict[str, Dict], notified_dates: set = None):
        """Save results to cache. Pass notified_dates to record last_notified_formats."""
        existing_cache = self.load_cache()
        cache_data = {'dates': {}}
        now = time.time()

        for date, data in results.items():
            existing_date_cache = existing_cache.get('dates', {}).get(date, {})
            existing_first_seen = existing_date_cache.get('format_first_seen', {})
            # Record first-seen time for any new formats; preserve existing timestamps
            format_first_seen = {fmt: existing_first_seen.get(fmt, now) for fmt in data['formats']}
            entry = {
                'formats': data['formats'],
                'format_first_seen': format_first_seen,
                'last_update': now
            }
            # Only update last_notified_formats when a notification was actually sent
            if notified_dates and date in notified_dates:
                entry['last_notified_formats'] = data['formats']
            elif 'last_notified_formats' in existing_date_cache:
                entry['last_notified_formats'] = existing_date_cache['last_notified_formats']
            cache_data['dates'][date] = entry

        try:
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            print(f"Error saving cache: {e}")
    
    def load_cache(self) -> Dict:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

class MonitorManager:
    def __init__(self, bot: TelegramBot):
        self.bot = bot
        self.trackers: List[MovieTracker] = []
        self.monitoring = False
        self.check_interval = 300
        self.chat_id = None
        self.monitor_thread = None
    
    def add_tracker(self, movie_url: str, movie_slug: str, movie_name: str,
                   theater_name: str, theater_slug: str, dates: List[str],
                   date_display: str, formats_filter: List[str]):
        tracker = MovieTracker(
            movie_url, movie_slug, movie_name,
            theater_name, theater_slug, dates,
            date_display, formats_filter
        )
        self.trackers.append(tracker)
        return tracker
    
    def check_all_trackers(self):
        import random
        for tracker in self.trackers:
            results = tracker.check_showtimes()
            
            # Check for new showtimes
            new_dates = [date for date, data in results.items() if data['available'] and data['is_new']]
            
            if new_dates:
                for date in new_dates:
                    self._send_notification(tracker, date, results[date])
            
            # Save results (pass notified_dates so last_notified_formats is updated)
            tracker.save_results(results, notified_dates=set(new_dates))
            
            # Log
            timestamp = datetime.now().strftime('%H:%M:%S')
            available_count = sum(1 for d in results.values() if d['available'])
            print(f"[{timestamp}] [{tracker.movie_name}] {available_count}/{len(tracker.dates)} dates available")
            
            # Delay between trackers
            if len(self.trackers) > 1:
                time.sleep(random.uniform(3, 7))
    
    def _send_notification(self, tracker: MovieTracker, date: str, data: Dict):
        """Send notification for new showtimes"""
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        date_display = date_obj.strftime('%B %d, %Y')

        current_formats = data['formats']
        newly_added = data.get('new_within_24h', set())

        message = f"🎉 <b>NEW SHOWTIMES!</b>\n\n"
        message += f"🎬 <b>{tracker.movie_name.upper()}</b>\n"
        message += f"📅 {date_display}\n"
        message += f"🏛️ {tracker.theater_name}\n\n"

        for format_name in sorted(current_formats.keys()):
            times_str = ', '.join(current_formats[format_name])
            if format_name in newly_added:
                message += f"🆕 <b>{format_name}:</b> {times_str}\n"
            else:
                message += f"<b>{format_name}:</b> {times_str}\n"

        message += f"\n🕐 <i>Detected at {datetime.now(NY_TZ).strftime('%I:%M %p')} ET</i>"

        self.bot.send_message(self.chat_id, message)
    
    def monitoring_loop(self):
        print("🎬 Monitoring started")
        
        while self.monitoring:
            self.check_all_trackers()
            time.sleep(self.check_interval)
    
    def start_monitoring(self, chat_id: int):
        if not self.monitoring:
            self.monitoring = True
            self.chat_id = chat_id
            self.monitor_thread = threading.Thread(target=self.monitoring_loop, daemon=True)
            self.monitor_thread.start()
    
    def stop_monitoring(self):
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)

class BotCommandHandler:
    def __init__(self, bot: TelegramBot, manager: MonitorManager):
        self.bot = bot
        self.manager = manager
        self.fetcher = ShowtimeFetcher()
        self.now_playing = NowPlayingFetcher()
    
    def handle_start(self, chat_id: int):
        message = (
            "🎬 <b>AMC Showtime Monitor</b>\n\n"
            "Smart tracking for AMC movies!\n\n"
            "<b>Commands:</b>\n\n"
            "/track - Monitor a movie\n"
            "/check - Check showtimes now\n"
            "/list - Show tracked movies\n"
            "/remove - Remove a tracked movie\n"
            "/status - Bot status\n"
            "/interval &lt;seconds&gt; - Check frequency\n"
            "/stop - Stop monitoring\n"
            "/help - Detailed help"
        )
        self.bot.send_message(chat_id, message)
    
    def handle_help(self, chat_id: int):
        message = (
            "🎯 <b>How to Use</b>\n\n"
            "<b>Track a Movie:</b>\n"
            "1. /track\n"
            "2. Provide movie URL\n"
            "3. Enter theater name\n"
            "4. Enter date or range\n"
            "5. Tap formats to toggle (or add custom)\n\n"
            "<b>Date Examples:</b>\n"
            "Single: <code>03/09</code> or <code>03/09/2026</code>\n"
            "Range: <code>03/09&gt;03/15</code> or <code>03/09/2026&gt;03/15/2026</code>\n\n"
            "<b>Check Showtimes:</b>\n"
            "/check - Manual lookup\n\n"
            "<b>View Tracking:</b>\n"
            "/list - See all tracked movies"
        )
        self.bot.send_message(chat_id, message)
    
    def _build_movie_buttons(self, recent_buttons, now_playing_buttons):
        """Build button list with header labels separating sections"""
        buttons = []
        if recent_buttons:
            buttons.append([{"text": "── Recent ──", "callback_data": "noop"}])
            buttons += recent_buttons
        if now_playing_buttons:
            buttons.append([{"text": "── Now Playing ──", "callback_data": "noop"}])
            buttons += now_playing_buttons
        return buttons

    def _build_format_keyboard(self, selected: set, extra_custom: list = None) -> List[List[Dict]]:
        """Build a toggle-style inline keyboard for format selection.

        selected: set of format name strings currently toggled on
        extra_custom: list of custom format strings added by user (appended after KNOWN_FORMATS)
        Returns inline_keyboard rows.
        """
        all_formats = KNOWN_FORMATS + (extra_custom or [])
        buttons = []

        # Two formats per row
        row = []
        for fmt in all_formats:
            check = "✅" if fmt in selected else "⬜"
            row.append({"text": f"{check} {fmt}", "callback_data": f"fmt:{fmt}"})
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        # Custom input button
        buttons.append([{"text": "⌨️ Custom format...", "callback_data": "fmt_custom"}])

        # Done button — shows selection summary
        if selected:
            done_label = f"✅ Done — {', '.join(sorted(selected))}"
        else:
            done_label = "✅ Done — All formats"
        buttons.append([{"text": done_label, "callback_data": "fmt_done"}])

        return buttons

    def handle_track(self, chat_id: int, recent_movies: RecentMovies):
        recent_buttons = recent_movies.get_buttons()
        now_playing_buttons = self.now_playing.get_buttons()
        buttons = self._build_movie_buttons(recent_buttons, now_playing_buttons)

        message = "🎬 <b>Track a Movie</b>\n\nOr send an <b>AMC movie URL</b>\nOr /cancel"
        if buttons:
            self.bot.send_message_with_buttons(chat_id, message, buttons)
        else:
            self.bot.send_message(chat_id, message)

        return "awaiting_url"

    def handle_check(self, chat_id: int, recent_movies: RecentMovies):
        recent_buttons = recent_movies.get_buttons()
        now_playing_buttons = self.now_playing.get_buttons()
        buttons = self._build_movie_buttons(recent_buttons, now_playing_buttons)

        message = "🔍 <b>Check Showtimes</b>\n\nOr send an <b>AMC movie URL</b>\nOr /cancel"
        if buttons:
            self.bot.send_message_with_buttons(chat_id, message, buttons)
        else:
            self.bot.send_message(chat_id, message)

        return "check_awaiting_url"
    
    def handle_list(self, chat_id: int):
        if not self.manager.trackers:
            self.bot.send_message(chat_id, "📭 No tracked movies.\n\nUse /track!")
            return
        
        for i, tracker in enumerate(self.manager.trackers, 1):
            # Get current status
            results = tracker.check_showtimes()
            
            message = f"━━━━━━━━━━━━━━━━━\n"
            message += f"<b>{i}️⃣ {tracker.movie_name.upper()}</b>\n"
            message += f"🏛️ {tracker.theater_name}\n"
            message += f"📅 {tracker.date_display}\n"
            
            if tracker.formats_filter:
                message += f"🎯 Tracking: {', '.join(tracker.formats_filter)}\n"
            else:
                message += f"🎯 Tracking: All formats\n"
            
            message += "\n"
            
            # Show availability for each date
            available_dates = [d for d, data in results.items() if data['available']]
            
            if available_dates:
                message += "<b>STATUS: ✅ Showtimes Available</b>\n\n"
                
                for date in sorted(available_dates):
                    date_obj = datetime.strptime(date, '%Y-%m-%d')
                    date_str = date_obj.strftime('%b %d')
                    
                    data = results[date]
                    new_marker = "🆕 " if data['is_new'] else ""
                    
                    message += f"{new_marker}<b>{date_str}:</b>\n"
                    
                    for format_name in sorted(data['formats'].keys()):
                        times = data['formats'][format_name]
                        times_str = ', '.join(times[:5])
                        if len(times) > 5:
                            times_str += f" +{len(times)-5} more"
                        message += f"  {format_name}: {times_str}\n"
                    
                    message += "\n"
            else:
                message += "<b>STATUS: ⏳ Not available yet</b>\n"
            
            message += f"<i>Last check: {datetime.now(NY_TZ).strftime('%I:%M %p')} ET</i>\n"
            message += f"━━━━━━━━━━━━━━━━━"
            
            self.bot.send_message(chat_id, message)
            time.sleep(0.5)
    
    def handle_status(self, chat_id: int):
        status = "🟢 Active" if self.manager.monitoring else "🔴 Stopped"
        message = (
            f"<b>Status:</b> {status}\n"
            f"<b>Tracked:</b> {len(self.manager.trackers)} movies\n"
            f"<b>Interval:</b> {self.manager.check_interval}s "
            f"({self.manager.check_interval//60} min)\n"
        )
        self.bot.send_message(chat_id, message)
    
    def handle_interval(self, chat_id: int, args: List[str]):
        if not args:
            self.bot.send_message(chat_id, "❌ Usage: /interval <seconds>\n\nExample: /interval 600")
            return
        
        try:
            interval = int(args[0])
            if interval < 60:
                self.bot.send_message(chat_id, "⚠️ Minimum 60 seconds")
                return
            
            self.manager.check_interval = interval
            self.bot.send_message(chat_id, f"✅ Interval: {interval}s ({interval//60} min)")
        except ValueError:
            self.bot.send_message(chat_id, "❌ Invalid number")
    
    def handle_stop(self, chat_id: int):
        self.manager.stop_monitoring()
        self.bot.send_message(chat_id, "🛑 Stopped.\n\nUse /track to restart.")

    def handle_remove(self, chat_id: int):
        if not self.manager.trackers:
            self.bot.send_message(chat_id, "📭 No tracked movies to remove.")
            return
        buttons = []
        for i, tracker in enumerate(self.manager.trackers):
            buttons.append([{
                "text": f"❌ {tracker.movie_name} @ {tracker.theater_name} ({tracker.date_display})",
                "callback_data": f"remove_tracker:{i}"
            }])
        buttons.append([{"text": "Cancel", "callback_data": "noop"}])
        self.bot.send_message_with_buttons(chat_id, "🗑️ <b>Select a movie to stop tracking:</b>", buttons)

    def handle_refreshlist(self, chat_id: int):
        self.bot.send_message(chat_id, "🔄 Refreshing Now Playing list...")
        self.now_playing._cache = None
        self.now_playing._cache_time = 0
        movies = self.now_playing.fetch()
        if movies:
            self.bot.send_message(chat_id, f"✅ Refreshed — {len(movies)} movies loaded.")
        else:
            self.bot.send_message(chat_id, "❌ Refresh failed. AMC may be unreachable.")
    
    def perform_manual_check(self, movie_slug: str, movie_name: str, theater_slug: str,
                            theater_name: str, dates: List[str], chat_id: int):
        """Execute /check command"""
        # Load cache to know which formats are within their 24h 🆕 window
        cache_file = CACHE_DIR / f"{hashlib.md5(f'{movie_slug}-{theater_slug}-{dates[0]}'.encode()).hexdigest()}.json"
        cache = {}
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    cache = json.load(f)
            except:
                pass

        cutoff = time.time() - 86400

        for date in dates:
            showtimes = self.fetcher.get_showtimes_for_date(movie_slug, theater_slug, date)

            date_obj = datetime.strptime(date, '%Y-%m-%d')
            date_display = date_obj.strftime('%B %d, %Y')

            message = f"━━━━━━━━━━━━━━━━━\n"
            message += f"🎬 <b>{movie_name.upper()}</b>\n"
            message += f"📅 {date_display}\n"
            message += f"🏛️ {theater_name}\n\n"

            if showtimes['available']:
                first_seen = cache.get('dates', {}).get(date, {}).get('format_first_seen', {})
                for format_name in sorted(showtimes['formats'].keys()):
                    times_str = ', '.join(showtimes['formats'][format_name])
                    is_new = first_seen.get(format_name, time.time()) > cutoff
                    prefix = "🆕 " if is_new else ""
                    message += f"{prefix}<b>{format_name}:</b> {times_str}\n"
            else:
                message += "⏳ <b>Not available yet</b>\n"

            message += f"━━━━━━━━━━━━━━━━━"

            self.bot.send_message(chat_id, message)
            time.sleep(0.5)

# Load theatre IDs from theaters.json into the module-level cache
_load_theatre_ids()


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 bot.py <BOT_TOKEN> <CHAT_ID>")
        sys.exit(1)
    
    bot_token = sys.argv[1]
    chat_id = int(sys.argv[2])
    
    bot = TelegramBot(bot_token)
    manager = MonitorManager(bot)
    handler = BotCommandHandler(bot, manager)
    recent_movies = RecentMovies()
    
    bot.send_message(chat_id, "🤖 <b>Bot Started!</b>\n\nSend /start")
    
    print("🤖 AMC Monitor running!")
    print("💬 Message your bot in Telegram")
    print("🛑 Ctrl+C to stop\n")
    
    offset = None
    conversation_state = {}
    tracking_data = {}
    
    # Matcher for theaters
    matcher = TheaterMatcher(Path(__file__).parent / "theaters.json")
    
    try:
        while True:
            updates = bot.get_updates(offset)
            
            if updates and updates.get('ok'):
                for update in updates['result']:
                    offset = update['update_id'] + 1
                    
                    # Handle button callbacks
                    if 'callback_query' in update:
                        callback = update['callback_query']
                        user_chat_id = callback['message']['chat']['id']
                        callback_data = callback['data']
                        callback_id = callback['id']
                        
                        # Answer the callback
                        bot.answer_callback_query(callback_id)

                        # Ignore header/separator buttons
                        if callback_data == 'noop':
                            continue

                        # Handle movie button press
                        if callback_data.startswith('movie:'):
                            movie_slug = callback_data.split(':', 1)[1]
                            
                            # Find movie in recent list
                            for movie in recent_movies.get_recent():
                                if movie['slug'] == movie_slug:
                                    # Simulate user entering URL
                                    state = conversation_state.get(user_chat_id)
                                    
                                    if state == "awaiting_url":
                                        # Track flow
                                        movie_name = movie['name']
                                        tracking_data[user_chat_id] = {
                                            'url': movie['url'],
                                            'slug': movie['slug'],
                                            'name': movie_name
                                        }
                                        conversation_state[user_chat_id] = "awaiting_theater"
                                        
                                        # Add quick Lincoln Square button
                                        lincoln_button = [[{
                                            "text": "🎯 AMC Lincoln Square 13",
                                            "callback_data": "theater:amc-lincoln-square-13"
                                        }]]
                                        
                                        bot.send_message_with_buttons(
                                            user_chat_id,
                                            f"✅ Movie: <b>{movie_name}</b>\n\n"
                                            f"<b>Quick select:</b> (tap button)\n\n"
                                            f"Or send <b>theater name</b>\n\n"
                                            f"Example: AMC Empire 25",
                                            lincoln_button
                                        )
                                    
                                    elif state == "check_awaiting_url":
                                        # Check flow
                                        movie_name = movie['name']
                                        tracking_data[user_chat_id] = {
                                            'slug': movie['slug'],
                                            'name': movie_name
                                        }
                                        conversation_state[user_chat_id] = "check_awaiting_theater"
                                        
                                        # Add quick Lincoln Square button
                                        lincoln_button = [[{
                                            "text": "🎯 AMC Lincoln Square 13",
                                            "callback_data": "theater:amc-lincoln-square-13"
                                        }]]
                                        
                                        bot.send_message_with_buttons(
                                            user_chat_id,
                                            f"✅ Movie: <b>{movie_name}</b>\n\n"
                                            f"<b>Quick select:</b> (tap button)\n\n"
                                            f"Or send <b>theater name</b>\n\n"
                                            f"Example: AMC Empire 25",
                                            lincoln_button
                                        )
                                    break
                        
                        # Handle now playing movie button press
                        elif callback_data.startswith('nowplaying:'):
                            movie_slug = callback_data.split(':', 1)[1]
                            movie_url = f"https://www.amctheatres.com/movies/{movie_slug}"
                            movie_name = AMCHelper.slug_to_title(movie_slug)
                            state = conversation_state.get(user_chat_id)

                            recent_movies.add(movie_url, movie_name, movie_slug)

                            lincoln_button = [[{
                                "text": "🎯 AMC Lincoln Square 13",
                                "callback_data": "theater:amc-lincoln-square-13"
                            }]]

                            if state == "awaiting_url":
                                tracking_data[user_chat_id] = {
                                    'url': movie_url,
                                    'slug': movie_slug,
                                    'name': movie_name
                                }
                                conversation_state[user_chat_id] = "awaiting_theater"
                                bot.send_message_with_buttons(
                                    user_chat_id,
                                    f"✅ Movie: <b>{movie_name}</b>\n\n"
                                    f"<b>Quick select:</b> (tap button)\n\n"
                                    f"Or send <b>theater name</b>\n\n"
                                    f"Example: AMC Empire 25",
                                    lincoln_button
                                )

                            elif state == "check_awaiting_url":
                                tracking_data[user_chat_id] = {
                                    'slug': movie_slug,
                                    'name': movie_name
                                }
                                conversation_state[user_chat_id] = "check_awaiting_theater"
                                bot.send_message_with_buttons(
                                    user_chat_id,
                                    f"✅ Movie: <b>{movie_name}</b>\n\n"
                                    f"<b>Quick select:</b> (tap button)\n\n"
                                    f"Or send <b>theater name</b>\n\n"
                                    f"Example: AMC Empire 25",
                                    lincoln_button
                                )

                        # Handle theater button press
                        elif callback_data.startswith('theater:'):
                            theater_slug = callback_data.split(':', 1)[1]
                            
                            # Get theater details
                            theater = matcher.get_theater_by_slug(theater_slug)
                            if theater:
                                state = conversation_state.get(user_chat_id)
                                
                                if state == "awaiting_theater":
                                    # Track flow
                                    tracking_data[user_chat_id]['theater_name'] = theater['name']
                                    tracking_data[user_chat_id]['theater_slug'] = theater['slug']
                                    conversation_state[user_chat_id] = "awaiting_dates"
                                    
                                    bot.send_message(
                                        user_chat_id,
                                        f"✅ Theater: <b>{theater['name']}</b> ✓\n\n"
                                        f"Send <b>date or date range</b>\n\n"
                                        f"Single: <code>03/09</code> or <code>03/09/2026</code>\n"
                                        f"Range: <code>03/09&gt;03/15</code> or <code>03/09/2026&gt;03/15/2026</code>"
                                    )
                                
                                elif state == "check_awaiting_theater":
                                    # Check flow
                                    tracking_data[user_chat_id]['theater_name'] = theater['name']
                                    tracking_data[user_chat_id]['theater_slug'] = theater['slug']
                                    conversation_state[user_chat_id] = "check_awaiting_dates"
                                    
                                    bot.send_message(
                                        user_chat_id,
                                        f"✅ Theater: <b>{theater['name']}</b> ✓\n\n"
                                        f"Send <b>date or date range</b>\n\n"
                                        f"Single: <code>03/09/2026</code>\n"
                                        f"Range: <code>03/09/2026&gt;03/15/2026</code>"
                                    )
                        
                        # Handle remove tracker button press
                        elif callback_data.startswith('remove_tracker:'):
                            try:
                                idx = int(callback_data.split(':', 1)[1])
                                if 0 <= idx < len(manager.trackers):
                                    removed = manager.trackers.pop(idx)
                                    bot.send_message(user_chat_id, f"✅ Stopped tracking <b>{removed.movie_name}</b> @ {removed.theater_name}")
                                else:
                                    bot.send_message(user_chat_id, "❌ Tracker not found (list may have changed).")
                            except (ValueError, IndexError):
                                bot.send_message(user_chat_id, "❌ Invalid selection.")

                        elif callback_data.startswith('fmt:'):
                            fmt_name = callback_data.split(':', 1)[1]
                            state = conversation_state.get(user_chat_id)
                            if state == "awaiting_formats":
                                selected = tracking_data[user_chat_id].get('selected_formats', set())
                                if fmt_name in selected:
                                    selected.discard(fmt_name)
                                else:
                                    selected.add(fmt_name)
                                tracking_data[user_chat_id]['selected_formats'] = selected
                                custom = tracking_data[user_chat_id].get('custom_formats', [])
                                keyboard = handler._build_format_keyboard(selected, custom)
                                msg_id = tracking_data[user_chat_id].get('format_msg_id')
                                if msg_id:
                                    bot.edit_message_reply_markup(user_chat_id, msg_id, keyboard)

                        elif callback_data == 'fmt_done':
                            state = conversation_state.get(user_chat_id)
                            if state == "awaiting_formats":
                                selected = tracking_data[user_chat_id].get('selected_formats', set())
                                formats = sorted(selected)  # empty list = all formats

                                data = tracking_data[user_chat_id]
                                manager.add_tracker(
                                    data['url'], data['slug'], data['name'],
                                    data['theater_name'], data['theater_slug'],
                                    data['dates'], data['date_display'], formats
                                )

                                if not manager.monitoring:
                                    manager.start_monitoring(user_chat_id)

                                del conversation_state[user_chat_id]
                                del tracking_data[user_chat_id]

                                fmt_text = ', '.join(formats) if formats else 'Any'
                                bot.send_message(
                                    user_chat_id,
                                    f"🎉 <b>Tracking Started!</b>\n\n"
                                    f"🎬 {data['name']}\n"
                                    f"🏛️ {data['theater_name']}\n"
                                    f"📅 {data['date_display']}\n"
                                    f"🎯 Formats: {fmt_text}\n\n"
                                    f"I'll notify you when showtimes appear!"
                                )

                        elif callback_data == 'fmt_custom':
                            state = conversation_state.get(user_chat_id)
                            if state == "awaiting_formats":
                                conversation_state[user_chat_id] = "awaiting_custom_format"
                                bot.send_message(
                                    user_chat_id,
                                    "⌨️ Type a custom format name and send it.\n"
                                    "Example: <code>LASER</code> or <code>OPEN CAPTION</code>\n\n"
                                    "Or /cancel to go back."
                                )

                        continue

                    if 'message' not in update:
                        continue
                    
                    message = update['message']
                    user_chat_id = message['chat']['id']
                    text = message.get('text', '').strip()
                    
                    if not text:
                        continue
                    
                    # Handle conversation states
                    if user_chat_id in conversation_state:
                        state = conversation_state[user_chat_id]
                        
                        if text == '/cancel':
                            del conversation_state[user_chat_id]
                            if user_chat_id in tracking_data:
                                del tracking_data[user_chat_id]
                            bot.send_message(user_chat_id, "❌ Cancelled")
                            continue
                        
                        # TRACK flow
                        if state == "awaiting_url":
                            movie_slug = AMCHelper.extract_movie_slug(text)
                            if not movie_slug:
                                bot.send_message(user_chat_id, "❌ Invalid URL. Try again or /cancel")
                                continue
                            
                            movie_name = AMCHelper.slug_to_title(movie_slug)
                            
                            # Add to recent movies
                            recent_movies.add(text, movie_name, movie_slug)
                            
                            tracking_data[user_chat_id] = {
                                'url': text,
                                'slug': movie_slug,
                                'name': movie_name
                            }
                            conversation_state[user_chat_id] = "awaiting_theater"
                            
                            # Add quick Lincoln Square button
                            lincoln_button = [[{
                                "text": "🎯 AMC Lincoln Square 13",
                                "callback_data": "theater:amc-lincoln-square-13"
                            }]]
                            
                            bot.send_message_with_buttons(
                                user_chat_id,
                                f"✅ Movie: <b>{movie_name}</b>\n\n"
                                f"<b>Quick select:</b> (tap button)\n\n"
                                f"Or send <b>theater name</b>\n\n"
                                f"Example: AMC Empire 25",
                                lincoln_button
                            )
                        
                        elif state == "awaiting_theater":
                            # Use fuzzy matcher to find theater suggestions
                            matcher = TheaterMatcher(Path(__file__).parent / "theaters.json")
                            data = tracking_data[user_chat_id]
                            
                            matches = matcher.find_matches(text, max_results=5)
                            
                            if not matches:
                                bot.send_message(
                                    user_chat_id,
                                    f"❌ No theaters found matching '<b>{text}</b>'.\n\n"
                                    f"<b>Tips:</b>\n"
                                    f"• Try a different name\n"
                                    f"• Use neighborhood: 'Times Square', 'Upper West Side'\n"
                                    f"• Use street: '34th Street', 'Lincoln Square'\n\n"
                                    f"Or /cancel"
                                )
                                continue
                            
                            # If only one match and high confidence, use it directly
                            if len(matches) == 1 and matches[0]['score'] > 0.9:
                                selected_theater = matches[0]
                                
                                # Validate theater exists
                                theater_info = AMCHelper.validate_theater(selected_theater['name'], data['slug'])
                                
                                if theater_info['valid'] == False:
                                    bot.send_message(
                                        user_chat_id,
                                        f"❌ Theater '<b>{selected_theater['name']}</b>' not responding.\n\n"
                                        f"Try a different theater or /cancel"
                                    )
                                    continue
                                
                                tracking_data[user_chat_id]['theater_name'] = selected_theater['name']
                                tracking_data[user_chat_id]['theater_slug'] = selected_theater['slug']
                                conversation_state[user_chat_id] = "awaiting_dates"
                                
                                bot.send_message(
                                    user_chat_id,
                                    f"✅ Theater: <b>{selected_theater['name']}</b> ✓\n\n"
                                    f"Send <b>date or date range</b>\n\n"
                                    f"Single: <code>03/09</code> or <code>03/09/2026</code>\n"
                                    f"Range: <code>03/09&gt;03/15</code> or <code>03/09/2026&gt;03/15/2026</code>"
                                )
                            else:
                                # Multiple matches - show suggestions
                                tracking_data[user_chat_id]['theater_suggestions'] = matches
                                conversation_state[user_chat_id] = "awaiting_theater_selection"
                                
                                message = f"🔍 <b>Found {len(matches)} matches:</b>\n\n"
                                
                                for i, match in enumerate(matches, 1):
                                    score_indicator = "⭐" if match['score'] > 0.8 else ""
                                    message += f"{i}. <b>{match['name']}</b> {score_indicator}\n"
                                    message += f"   📍 {match.get('neighborhood', match['city'])}\n"
                                    if 'address' in match:
                                        message += f"   {match['address']}\n"
                                    message += "\n"
                                
                                message += f"<b>Reply with number</b> (1-{len(matches)}) or /cancel"
                                
                                bot.send_message(user_chat_id, message)
                        
                        elif state == "awaiting_theater_selection":
                            # User selected a theater from suggestions
                            try:
                                selection = int(text.strip())
                                suggestions = tracking_data[user_chat_id].get('theater_suggestions', [])
                                
                                if selection < 1 or selection > len(suggestions):
                                    bot.send_message(
                                        user_chat_id,
                                        f"❌ Invalid selection. Choose 1-{len(suggestions)} or /cancel"
                                    )
                                    continue
                                
                                selected_theater = suggestions[selection - 1]
                                data = tracking_data[user_chat_id]
                                
                                # Validate theater exists
                                theater_info = AMCHelper.validate_theater(selected_theater['name'], data['slug'])
                                
                                if theater_info['valid'] == False:
                                    bot.send_message(
                                        user_chat_id,
                                        f"❌ Theater '<b>{selected_theater['name']}</b>' not responding.\n\n"
                                        f"Try selecting a different theater."
                                    )
                                    # Stay in same state so they can pick another
                                    continue
                                
                                tracking_data[user_chat_id]['theater_name'] = selected_theater['name']
                                tracking_data[user_chat_id]['theater_slug'] = selected_theater['slug']
                                conversation_state[user_chat_id] = "awaiting_dates"
                                
                                # Clean up suggestions from tracking_data
                                del tracking_data[user_chat_id]['theater_suggestions']
                                
                                bot.send_message(
                                    user_chat_id,
                                    f"✅ Theater: <b>{selected_theater['name']}</b> ✓\n\n"
                                    f"Send <b>date or date range</b>\n\n"
                                    f"Single: <code>03/09</code> or <code>03/09/2026</code>\n"
                                    f"Range: <code>03/09&gt;03/15</code> or <code>03/09/2026&gt;03/15/2026</code>"
                                )
                                
                            except ValueError:
                                bot.send_message(
                                    user_chat_id,
                                    f"❌ Please send a number (1-{len(tracking_data[user_chat_id].get('theater_suggestions', []))}) or /cancel"
                                )
                        
                        elif state == "awaiting_dates":
                            dates, date_display = AMCHelper.parse_date_input(text)
                            if not dates:
                                bot.send_message(user_chat_id, "❌ Invalid date format. Try again or /cancel")
                                continue

                            tracking_data[user_chat_id]['dates'] = dates
                            tracking_data[user_chat_id]['date_display'] = date_display
                            conversation_state[user_chat_id] = "awaiting_formats"
                            tracking_data[user_chat_id]['selected_formats'] = set()
                            tracking_data[user_chat_id]['custom_formats'] = []
                            keyboard = handler._build_format_keyboard(set())
                            result = bot.send_message_with_buttons(
                                user_chat_id,
                                f"✅ Dates: <b>{date_display}</b>\n\n"
                                f"Which <b>formats</b> to track?\n"
                                f"Tap to toggle. Done with nothing selected = all formats.",
                                keyboard
                            )
                            if result and result.get('ok'):
                                tracking_data[user_chat_id]['format_msg_id'] = result['result']['message_id']
                        
                        elif state == "awaiting_custom_format":
                            custom_fmt = text.strip().upper()
                            if not custom_fmt:
                                bot.send_message(user_chat_id, "❌ Format name cannot be empty. Try again or /cancel.")
                            elif custom_fmt:
                                tracking_data[user_chat_id].setdefault('custom_formats', [])
                                if custom_fmt not in tracking_data[user_chat_id]['custom_formats']:
                                    tracking_data[user_chat_id]['custom_formats'].append(custom_fmt)
                                # Auto-select the custom format
                                tracking_data[user_chat_id].setdefault('selected_formats', set())
                                tracking_data[user_chat_id]['selected_formats'].add(custom_fmt)

                                conversation_state[user_chat_id] = "awaiting_formats"
                                selected = tracking_data[user_chat_id]['selected_formats']
                                custom = tracking_data[user_chat_id]['custom_formats']
                                keyboard = handler._build_format_keyboard(selected, custom)
                                result = bot.send_message_with_buttons(
                                    user_chat_id,
                                    f"✅ Added <b>{custom_fmt}</b>. Continue selecting or tap Done.",
                                    keyboard
                                )
                                if result and result.get('ok'):
                                    tracking_data[user_chat_id]['format_msg_id'] = result['result']['message_id']

                        # CHECK flow
                        elif state == "check_awaiting_url":
                            movie_slug = AMCHelper.extract_movie_slug(text)
                            if not movie_slug:
                                bot.send_message(user_chat_id, "❌ Invalid URL. Try again or /cancel")
                                continue
                            
                            movie_name = AMCHelper.slug_to_title(movie_slug)
                            
                            # Add to recent movies
                            recent_movies.add(text, movie_name, movie_slug)
                            
                            tracking_data[user_chat_id] = {
                                'slug': movie_slug,
                                'name': movie_name
                            }
                            conversation_state[user_chat_id] = "check_awaiting_theater"
                            
                            # Add quick Lincoln Square button
                            lincoln_button = [[{
                                "text": "🎯 AMC Lincoln Square 13",
                                "callback_data": "theater:amc-lincoln-square-13"
                            }]]
                            
                            bot.send_message_with_buttons(
                                user_chat_id,
                                f"✅ Movie: <b>{movie_name}</b>\n\n"
                                f"<b>Quick select:</b> (tap button)\n\n"
                                f"Or send <b>theater name</b>\n\n"
                                f"Example: AMC Empire 25",
                                lincoln_button
                            )
                        
                        elif state == "check_awaiting_theater":
                            # Use fuzzy matcher for check flow too
                            matcher = TheaterMatcher(Path(__file__).parent / "theaters.json")
                            data = tracking_data[user_chat_id]
                            
                            matches = matcher.find_matches(text, max_results=5)
                            
                            if not matches:
                                bot.send_message(
                                    user_chat_id,
                                    f"❌ No theaters found matching '<b>{text}</b>'.\n\n"
                                    f"Try a different name or /cancel"
                                )
                                continue
                            
                            # If only one match and high confidence, use it directly
                            if len(matches) == 1 and matches[0]['score'] > 0.9:
                                selected_theater = matches[0]
                                
                                tracking_data[user_chat_id]['theater_name'] = selected_theater['name']
                                tracking_data[user_chat_id]['theater_slug'] = selected_theater['slug']
                                conversation_state[user_chat_id] = "check_awaiting_dates"
                                
                                bot.send_message(
                                    user_chat_id,
                                    f"✅ Theater: <b>{selected_theater['name']}</b> ✓\n\n"
                                    f"Send <b>date or date range</b>\n\n"
                                    f"Single: <code>03/09</code> or <code>03/09/2026</code>\n"
                                    f"Range: <code>03/09&gt;03/15</code> or <code>03/09/2026&gt;03/15/2026</code>"
                                )
                            else:
                                # Multiple matches - show suggestions
                                tracking_data[user_chat_id]['theater_suggestions'] = matches
                                conversation_state[user_chat_id] = "check_awaiting_theater_selection"
                                
                                message = f"🔍 <b>Found {len(matches)} matches:</b>\n\n"
                                
                                for i, match in enumerate(matches, 1):
                                    score_indicator = "⭐" if match['score'] > 0.8 else ""
                                    message += f"{i}. <b>{match['name']}</b> {score_indicator}\n"
                                    message += f"   📍 {match.get('neighborhood', match['city'])}\n\n"
                                
                                message += f"<b>Reply with number</b> (1-{len(matches)}) or /cancel"
                                
                                bot.send_message(user_chat_id, message)
                        
                        elif state == "check_awaiting_theater_selection":
                            # User selected a theater from suggestions (check flow)
                            try:
                                selection = int(text.strip())
                                suggestions = tracking_data[user_chat_id].get('theater_suggestions', [])
                                
                                if selection < 1 or selection > len(suggestions):
                                    bot.send_message(
                                        user_chat_id,
                                        f"❌ Invalid selection. Choose 1-{len(suggestions)} or /cancel"
                                    )
                                    continue
                                
                                selected_theater = suggestions[selection - 1]
                                
                                tracking_data[user_chat_id]['theater_name'] = selected_theater['name']
                                tracking_data[user_chat_id]['theater_slug'] = selected_theater['slug']
                                conversation_state[user_chat_id] = "check_awaiting_dates"
                                
                                # Clean up suggestions
                                del tracking_data[user_chat_id]['theater_suggestions']
                                
                                bot.send_message(
                                    user_chat_id,
                                    f"✅ Theater: <b>{selected_theater['name']}</b> ✓\n\n"
                                    f"Send <b>date or date range</b>\n\n"
                                    f"Single: <code>03/09</code> or <code>03/09/2026</code>\n"
                                    f"Range: <code>03/09&gt;03/15</code> or <code>03/09/2026&gt;03/15/2026</code>"
                                )
                                
                            except ValueError:
                                bot.send_message(
                                    user_chat_id,
                                    f"❌ Please send a number (1-{len(tracking_data[user_chat_id].get('theater_suggestions', []))}) or /cancel"
                                )
                        
                        elif state == "check_awaiting_dates":
                            dates, date_display = AMCHelper.parse_date_input(text)
                            if not dates:
                                bot.send_message(user_chat_id, "❌ Invalid date format. Try again or /cancel")
                                continue
                            
                            # Perform the check
                            data = tracking_data[user_chat_id]
                            handler.perform_manual_check(
                                data['slug'], data['name'],
                                data['theater_slug'], data['theater_name'],
                                dates, user_chat_id
                            )
                            
                            del conversation_state[user_chat_id]
                            del tracking_data[user_chat_id]
                        
                        continue
                    
                    # Handle commands
                    if text.startswith('/'):
                        parts = text.split()
                        command = parts[0][1:].lower()
                        args = parts[1:]
                        
                        if command == 'start':
                            handler.handle_start(user_chat_id)
                        elif command == 'help':
                            handler.handle_help(user_chat_id)
                        elif command == 'track':
                            conversation_state[user_chat_id] = handler.handle_track(user_chat_id, recent_movies)
                        elif command == 'check':
                            conversation_state[user_chat_id] = handler.handle_check(user_chat_id, recent_movies)
                        elif command == 'list':
                            handler.handle_list(user_chat_id)
                        elif command == 'status':
                            handler.handle_status(user_chat_id)
                        elif command == 'interval':
                            handler.handle_interval(user_chat_id, args)
                        elif command == 'stop':
                            handler.handle_stop(user_chat_id)
                        elif command == 'remove':
                            handler.handle_remove(user_chat_id)
                        elif command == 'refreshlist':
                            handler.handle_refreshlist(user_chat_id)
                        else:
                            bot.send_message(user_chat_id, "❌ Unknown. Send /help")
    
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")
        manager.stop_monitoring()

if __name__ == "__main__":
    main()
