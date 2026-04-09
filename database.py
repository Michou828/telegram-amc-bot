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

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
