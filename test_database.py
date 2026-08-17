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
