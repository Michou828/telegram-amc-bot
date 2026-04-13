import sqlite3
import datetime

DB_NAME = "amc_bot.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracked_movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            movie_name TEXT,
            movie_slug TEXT,
            theater_name TEXT,
            theater_slug TEXT,
            date_range TEXT,
            formats TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS seen_showtimes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            movie_slug TEXT,
            theater_slug TEXT,
            date TEXT,
            format TEXT,
            time TEXT,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS movie_registry (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            release_date TEXT,
            url TEXT
        )
    ''')
    # Migrate existing installs that don't have the new columns yet
    for col, typedef in [("release_date", "TEXT"), ("url", "TEXT")]:
        try:
            cursor.execute(f"ALTER TABLE movie_registry ADD COLUMN {col} {typedef}")
        except Exception:
            pass  # column already exists

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recent_movies (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            last_used_at TEXT NOT NULL,
            use_count INTEGER DEFAULT 1
        )
    ''')

    conn.commit()
    conn.close()

def add_tracked_movie(user_id, movie_name, movie_slug, theater_name, theater_slug, date_range, formats):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tracked_movies (user_id, movie_name, movie_slug, theater_name, theater_slug, date_range, formats)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, movie_name, movie_slug, theater_name, theater_slug, date_range, formats))
    conn.commit()
    conn.close()

def get_tracked_movies():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tracked_movies')
    rows = cursor.fetchall()
    conn.close()
    return rows

def remove_tracked_movie(track_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM tracked_movies WHERE id = ?', (track_id,))
    conn.commit()
    conn.close()

def is_showtime_seen(movie_slug, theater_slug, date, format_name, time_val):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id FROM seen_showtimes
        WHERE movie_slug = ? AND theater_slug = ? AND date = ? AND format = ? AND time = ?
    ''', (movie_slug, theater_slug, date, format_name, time_val))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def mark_showtime_seen(movie_slug, theater_slug, date, format_name, time_val):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO seen_showtimes (movie_slug, theater_slug, date, format, time)
        VALUES (?, ?, ?, ?, ?)
    ''', (movie_slug, theater_slug, date, format_name, time_val))
    conn.commit()
    conn.close()

def is_format_new(movie_slug, theater_slug, date, format_name, hours=24):
    """Returns True if this format was first seen within the last `hours` hours."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT MIN(first_seen_at) FROM seen_showtimes
        WHERE movie_slug = ? AND theater_slug = ? AND date = ? AND format = ?
    ''', (movie_slug, theater_slug, date, format_name))
    row = cursor.fetchone()
    conn.close()
    if not row or not row[0]:
        return False
    first_seen = datetime.datetime.fromisoformat(row[0])
    return (datetime.datetime.now() - first_seen).total_seconds() < hours * 3600

def upsert_registry_movie(slug, name, status="future_release", release_date=None, url=None):
    """Insert or update a movie in the registry. Won't downgrade advanced_tickets → future_release."""
    now = datetime.datetime.now().isoformat()
    if url is None:
        url = f"https://www.amctheatres.com/movies/{slug}"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM movie_registry WHERE slug = ?', (slug,))
    row = cursor.fetchone()
    if row:
        new_status = row[0] if row[0] == "advanced_tickets" and status == "future_release" else status
        cursor.execute(
            'UPDATE movie_registry SET name = ?, status = ?, last_seen_at = ?, release_date = COALESCE(?, release_date), url = ? WHERE slug = ?',
            (name, new_status, now, release_date, url, slug)
        )
    else:
        cursor.execute(
            'INSERT INTO movie_registry (slug, name, status, first_seen_at, last_seen_at, release_date, url) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (slug, name, status, now, now, release_date, url)
        )
    conn.commit()
    conn.close()

def remove_registry_movie(slug):
    conn = sqlite3.connect(DB_NAME)
    conn.execute('DELETE FROM movie_registry WHERE slug = ?', (slug,))
    conn.commit()
    conn.close()

def upgrade_registry_to_advanced(slug):
    """Mark a registry movie as having advanced tickets. No-op if not in registry."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.datetime.now().isoformat()
    cursor.execute(
        'UPDATE movie_registry SET status = ?, last_seen_at = ? WHERE slug = ? AND status = ?',
        ("advanced_tickets", now, slug, "future_release")
    )
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    return updated > 0

def get_registry_movies():
    """Returns all registry movies ordered by status (advanced_tickets first) then release_date, then name."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT slug, name, status, first_seen_at, last_seen_at, release_date, url
        FROM movie_registry
        ORDER BY CASE status WHEN 'advanced_tickets' THEN 0 ELSE 1 END,
                 CASE WHEN release_date IS NULL THEN 1 ELSE 0 END,
                 release_date,
                 name
    ''')
    rows = cursor.fetchall()
    conn.close()
    return rows

def add_recent_movie(slug, name, url):
    """Upsert a recently searched/tracked movie."""
    now = datetime.datetime.now().isoformat()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT use_count FROM recent_movies WHERE slug = ?', (slug,))
    row = cursor.fetchone()
    if row:
        cursor.execute(
            'UPDATE recent_movies SET name = ?, url = ?, last_used_at = ?, use_count = ? WHERE slug = ?',
            (name, url, now, row[0] + 1, slug)
        )
    else:
        cursor.execute(
            'INSERT INTO recent_movies (slug, name, url, last_used_at, use_count) VALUES (?, ?, ?, ?, 1)',
            (slug, name, url, now)
        )
    conn.commit()
    conn.close()

def get_recent_movies(limit=8):
    """Return recently used movies, most recent first."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT slug, name, url, last_used_at, use_count FROM recent_movies ORDER BY last_used_at DESC LIMIT ?',
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
