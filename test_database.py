import os
import sqlite3
import pytest
import database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_amc_bot.db")
    monkeypatch.setattr(database, "DB_NAME", db_path)
    database.init_db()
    return db_path


class TestSeenShowtimeStatus:
    def test_mark_and_get_status(self, temp_db):
        database.mark_showtime_seen("dune-part-three", "amc-lincoln-square-13", "2027-01-09", "IMAX", "9:00am", "ComingSoon")

        assert database.is_showtime_seen("dune-part-three", "amc-lincoln-square-13", "2027-01-09", "IMAX", "9:00am") is True
        assert database.get_showtime_status("dune-part-three", "amc-lincoln-square-13", "2027-01-09", "IMAX", "9:00am") == "ComingSoon"

    def test_unseen_showtime_has_no_status(self, temp_db):
        assert database.is_showtime_seen("nope", "nope", "2027-01-09", "IMAX", "9:00am") is False
        assert database.get_showtime_status("nope", "nope", "2027-01-09", "IMAX", "9:00am") is None

    def test_update_showtime_status(self, temp_db):
        database.mark_showtime_seen("dune-part-three", "amc-lincoln-square-13", "2027-01-09", "IMAX", "9:00am", "ComingSoon")

        database.update_showtime_status("dune-part-three", "amc-lincoln-square-13", "2027-01-09", "IMAX", "9:00am", "Sellable")

        assert database.get_showtime_status("dune-part-three", "amc-lincoln-square-13", "2027-01-09", "IMAX", "9:00am") == "Sellable"

    def test_pre_migration_row_has_null_status(self, temp_db):
        # Simulate a row written by the old schema/code, before the status column existed in practice
        conn = sqlite3.connect(temp_db)
        conn.execute(
            "INSERT INTO seen_showtimes (movie_slug, theater_slug, date, format, time) VALUES (?, ?, ?, ?, ?)",
            ("dune-part-three", "amc-lincoln-square-13", "2027-01-09", "IMAX", "9:00am"),
        )
        conn.commit()
        conn.close()

        assert database.is_showtime_seen("dune-part-three", "amc-lincoln-square-13", "2027-01-09", "IMAX", "9:00am") is True
        assert database.get_showtime_status("dune-part-three", "amc-lincoln-square-13", "2027-01-09", "IMAX", "9:00am") is None

    def test_migration_adds_column_without_defaulting_existing_rows(self, tmp_path, monkeypatch):
        # Build a DB using the pre-status-column schema, then run init_db() again
        # (as happens on every bot startup) and confirm existing rows land on NULL, not 'Sellable'.
        db_path = str(tmp_path / "legacy.db")
        monkeypatch.setattr(database, "DB_NAME", db_path)

        conn = sqlite3.connect(db_path)
        conn.execute('''
            CREATE TABLE seen_showtimes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_slug TEXT,
                theater_slug TEXT,
                date TEXT,
                format TEXT,
                time TEXT,
                first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute(
            "INSERT INTO seen_showtimes (movie_slug, theater_slug, date, format, time) VALUES (?, ?, ?, ?, ?)",
            ("dune-part-three", "amc-lincoln-square-13", "2027-01-09", "IMAX", "9:00am"),
        )
        conn.commit()
        conn.close()

        database.init_db()

        assert database.get_showtime_status("dune-part-three", "amc-lincoln-square-13", "2027-01-09", "IMAX", "9:00am") is None


class TestActiveTracking:
    def test_new_tracked_movie_defaults_active_tracking_off(self, temp_db):
        database.add_tracked_movie(1, "Dune: Part Three", "dune-part-three-77032",
                                    "AMC Lincoln Square 13", "amc-lincoln-square-13",
                                    "1/9-1/12", "IMAX")
        movies = database.get_movies_for_active_tracking(1)
        assert movies == [("dune-part-three-77032", "Dune: Part Three", 0)]

    def test_set_active_tracking_enables_for_all_rows_of_movie(self, temp_db):
        database.add_tracked_movie(1, "Dune: Part Three", "dune-part-three-77032",
                                    "AMC Lincoln Square 13", "amc-lincoln-square-13",
                                    "1/9-1/12", "IMAX")
        database.add_tracked_movie(1, "Dune: Part Three", "dune-part-three-77032",
                                    "AMC Empire 25", "amc-empire-25",
                                    "1/9-1/12", "Standard")

        database.set_active_tracking(1, "dune-part-three-77032", True)

        rows = database.get_tracked_movies()
        assert all(row[9] == 1 for row in rows)

    def test_set_active_tracking_only_affects_matching_user(self, temp_db):
        database.add_tracked_movie(1, "Dune: Part Three", "dune-part-three-77032",
                                    "AMC Lincoln Square 13", "amc-lincoln-square-13",
                                    "1/9-1/12", "IMAX")
        database.add_tracked_movie(2, "Dune: Part Three", "dune-part-three-77032",
                                    "AMC Empire 25", "amc-empire-25",
                                    "1/9-1/12", "Standard")

        database.set_active_tracking(1, "dune-part-three-77032", True)

        rows = {row[1]: row[9] for row in database.get_tracked_movies()}  # user_id -> active_tracking
        assert rows[1] == 1
        assert rows[2] == 0

    def test_set_active_tracking_can_disable(self, temp_db):
        database.add_tracked_movie(1, "Dune: Part Three", "dune-part-three-77032",
                                    "AMC Lincoln Square 13", "amc-lincoln-square-13",
                                    "1/9-1/12", "IMAX")
        database.set_active_tracking(1, "dune-part-three-77032", True)
        database.set_active_tracking(1, "dune-part-three-77032", False)

        movies = database.get_movies_for_active_tracking(1)
        assert movies == [("dune-part-three-77032", "Dune: Part Three", 0)]

    def test_get_movies_for_active_tracking_returns_distinct_movies(self, temp_db):
        database.add_tracked_movie(1, "Dune: Part Three", "dune-part-three-77032",
                                    "AMC Lincoln Square 13", "amc-lincoln-square-13",
                                    "1/9-1/12", "IMAX")
        database.add_tracked_movie(1, "Dune: Part Three", "dune-part-three-77032",
                                    "AMC Empire 25", "amc-empire-25",
                                    "1/9-1/12", "Standard")
        database.add_tracked_movie(1, "The Odyssey", "the-odyssey-12345",
                                    "AMC Lincoln Square 13", "amc-lincoln-square-13",
                                    "7/17", "IMAX")

        movies = database.get_movies_for_active_tracking(1)

        assert sorted(movies) == sorted([
            ("dune-part-three-77032", "Dune: Part Three", 0),
            ("the-odyssey-12345", "The Odyssey", 0),
        ])

    def test_migration_adds_active_tracking_column_to_legacy_db(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy.db")
        monkeypatch.setattr(database, "DB_NAME", db_path)

        conn = sqlite3.connect(db_path)
        conn.execute('''
            CREATE TABLE tracked_movies (
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
        conn.execute('''
            INSERT INTO tracked_movies (user_id, movie_name, movie_slug, theater_name, theater_slug, date_range, formats)
            VALUES (1, 'Dune: Part Three', 'dune-part-three-77032', 'AMC Lincoln Square 13', 'amc-lincoln-square-13', '1/9-1/12', 'IMAX')
        ''')
        conn.commit()
        conn.close()

        database.init_db()  # same call the bot makes on every startup

        movies = database.get_movies_for_active_tracking(1)
        assert movies == [("dune-part-three-77032", "Dune: Part Three", 0)]
