import datetime
import time
import amc_showtime_bot as bot
from scraper import AMCScraper


class TestPollFailureTracking:
    """Bug: Polling Warning fires from transient, self-resolving harvest retries.

    get_page_data() returns None in two very different situations:
      1. A harvest just ran and succeeded — by design the *next* call is expected
         to succeed, so this single miss isn't a real failure.
      2. Everything else (harvest failed, cooldown active, network exception) —
         a genuine failure that should count toward the alert.

    The old code counted both identically in a single counter shared across
    ALL tracked movie/theater/date combos, so unrelated items' failures piled
    up together and crossed the alert threshold even when nothing was wrong.
    """

    def test_transient_harvest_retry_is_not_a_real_failure(self):
        assert bot._is_transient_harvest_retry(
            "Harvest succeeded — next request should work."
        ) is True

    def test_other_fail_reasons_are_real_failures(self):
        assert bot._is_transient_harvest_retry("Blocked (status=403), harvest cooldown active (12m remaining)") is False
        assert bot._is_transient_harvest_retry("Harvest failed after 2 attempts. Last error: boom") is False
        assert bot._is_transient_harvest_retry("Request exception: timeout") is False

    def test_failures_are_tracked_per_item_not_globally(self):
        bot_data = {}
        key_a = ("movie-a", "theater-1", "2026-08-01")
        key_b = ("movie-b", "theater-2", "2026-08-02")

        bot._register_poll_failure(bot_data, key_a, transient=False)
        bot._register_poll_failure(bot_data, key_a, transient=False)
        bot._register_poll_failure(bot_data, key_b, transient=False)

        assert bot._poll_failure_count(bot_data, key_a) == 2
        assert bot._poll_failure_count(bot_data, key_b) == 1

    def test_transient_failure_does_not_increment_count(self):
        bot_data = {}
        key = ("movie-a", "theater-1", "2026-08-01")

        bot._register_poll_failure(bot_data, key, transient=True)
        bot._register_poll_failure(bot_data, key, transient=True)

        assert bot._poll_failure_count(bot_data, key) == 0

    def test_success_clears_failure_count_for_that_item_only(self):
        bot_data = {}
        key_a = ("movie-a", "theater-1", "2026-08-01")
        key_b = ("movie-b", "theater-2", "2026-08-02")

        bot._register_poll_failure(bot_data, key_a, transient=False)
        bot._register_poll_failure(bot_data, key_b, transient=False)
        bot._register_poll_success(bot_data, key_a)

        assert bot._poll_failure_count(bot_data, key_a) == 0
        assert bot._poll_failure_count(bot_data, key_b) == 1


class TestFilterFutureDates:
    """Bug: polling_task fetched showtimes for tracked dates that already passed,
    forever, on every 10-min cycle, since get_dates_from_range() has no concept
    of "today" — it just expands whatever range the user originally entered.
    """

    def test_drops_dates_before_today(self):
        today = datetime.date(2026, 7, 21)
        dates = ["2026-07-19", "2026-07-20", "2026-07-21", "2026-07-22"]

        result = bot._filter_future_dates(dates, today=today)

        assert result == ["2026-07-21", "2026-07-22"]

    def test_keeps_today(self):
        today = datetime.date(2026, 7, 21)
        assert bot._filter_future_dates(["2026-07-21"], today=today) == ["2026-07-21"]

    def test_all_past_returns_empty(self):
        today = datetime.date(2026, 7, 21)
        assert bot._filter_future_dates(["2026-07-01", "2026-07-19"], today=today) == []

    def test_empty_input_returns_empty(self):
        today = datetime.date(2026, 7, 21)
        assert bot._filter_future_dates([], today=today) == []

    def test_preserves_order(self):
        today = datetime.date(2026, 7, 21)
        dates = ["2026-07-25", "2026-07-22", "2026-07-30"]
        assert bot._filter_future_dates(dates, today=today) == ["2026-07-25", "2026-07-22", "2026-07-30"]


def _fake_movies_edge(name, slug):
    return {"node": {"name": name, "slug": slug, "absoluteWebsiteUrl": None, "releaseDateUtc": "2026-12-17"}}


class TestPeriodicMovieListRefresh:
    """Bug: a newly-added AMC "Coming Soon" listing (e.g. Dune: Part Three) could
    sit invisible to the user for arbitrarily long periods. get_movies_list()
    already has a 12h cache TTL, but nothing ever calls it unless a user runs
    /movies, /check, /track, or /refreshmovielist — so on a bot that's been up
    for weeks, a stale cache just sits there until someone happens to browse.

    _refresh_movie_lists() is a periodic safety net: if the cache is older than
    12h, force a full refresh (via refresh_movie_list()) of all three list
    types; otherwise it's a no-op. It deliberately does NOT call
    get_movies_list() repeatedly in a loop — that function's staleness check
    reads one last_list_refresh timestamp shared by all three list types, so
    the first call's refetch would update that timestamp and make the next
    call look artificially fresh, silently skipping its own refetch even
    though its specific cached list was still stale.
    """

    def _make_scraper(self):
        s = AMCScraper()
        s.save_cache = lambda: None  # don't touch the real cache.json during tests
        return s

    def test_fresh_cache_does_not_hit_network(self):
        s = self._make_scraper()
        s.last_list_refresh = time.time()  # just refreshed
        s.movie_list_cache = {"now-playing": [{"name": "x", "slug": "x-1"}], "coming-soon": [{"name": "y", "slug": "y-1"}], "events": [{"name": "z", "slug": "z-1"}]}

        def _boom(*a, **kw):
            raise AssertionError("should not hit the network when cache is fresh")
        s._graphql_movies = _boom

        changed = bot._refresh_movie_lists(s)

        assert changed is False

    def test_stale_cache_refetches_and_picks_up_new_movies(self):
        s = self._make_scraper()
        s.last_list_refresh = time.time() - 50000  # > 12h old
        s.movie_list_cache = {"now-playing": [], "coming-soon": [], "events": []}
        s._graphql_movies = lambda availability, first=500: (
            [_fake_movies_edge("Dune: Part Three", "dune-part-three-77032")]
            if availability == "COMING_SOON" else []
        )

        changed = bot._refresh_movie_lists(s)

        assert changed is True
        slugs = {m['slug'] for m in s.movie_list_cache['coming-soon']}
        assert "dune-part-three-77032" in slugs

    def test_all_three_list_types_actually_refetch_not_just_the_first(self):
        """Regression test: reproduces the exact bug caught live in production —
        now-playing successfully refetched *first* (real data, not empty), which
        updated the shared last_list_refresh timestamp. That made coming-soon's
        still-stale cache look artificially fresh on the very next call, so it
        silently kept serving the old list and Dune stayed permanently missing.
        (An earlier version of this test had now-playing return empty data,
        which accidentally sidestepped the bug instead of catching it.)"""
        s = self._make_scraper()
        s.last_list_refresh = time.time() - 50000  # > 12h old
        s.movie_list_cache = {
            "now-playing": [{"name": "Old Now Playing", "slug": "old-np-1"}],
            "coming-soon": [{"name": "Old Coming Soon", "slug": "old-cs-1"}],
            "events": [{"name": "Old Event", "slug": "old-ev-1"}],
        }
        s._graphql_movies = lambda availability, first=500: {
            "NOW_PLAYING": [_fake_movies_edge("Some Movie", "some-movie-1")],
            "COMING_SOON": [_fake_movies_edge("Dune: Part Three", "dune-part-three-77032")],
            "ADVANCE_TICKETS": [],
            "EVENTS": [],
        }.get(availability, [])

        changed = bot._refresh_movie_lists(s)

        assert changed is True
        slugs = {m['slug'] for m in s.movie_list_cache['coming-soon']}
        assert "dune-part-three-77032" in slugs
        assert "old-cs-1" not in slugs


class TestFormatTimesWithBadges:
    """AMC's own "status" field distinguishes near-capacity ("AlmostFull") from
    wide-open ("Sellable") showtimes. Previously this was discarded entirely, so
    a showtime already down to its last couple of seats looked identical to one
    with plenty of availability. Badge AlmostFull times so the user has signal
    that it may sell out imminently, instead of finding out only after clicking
    through to a sold-out page.
    """

    def test_sellable_time_has_no_badge(self):
        assert bot._format_time_label("10:30am", "Sellable") == "10:30am"

    def test_almost_full_time_gets_badge(self):
        assert bot._format_time_label("1:15pm", "AlmostFull") == "1:15pm ⚠️"

    def test_unknown_status_defaults_to_no_badge(self):
        assert bot._format_time_label("1:15pm", "SomeFutureStatusWeHaventSeen") == "1:15pm"

    def test_formats_mixed_list_of_times(self):
        times = ["10:30am", "1:15pm", "4:00pm"]
        status_by_time = {"10:30am": "Sellable", "1:15pm": "AlmostFull", "4:00pm": "Sellable"}

        result = bot._format_times_with_badges(times, status_by_time)

        assert result == "10:30am, 1:15pm ⚠️, 4:00pm"

    def test_missing_status_entries_default_to_no_badge(self):
        result = bot._format_times_with_badges(["10:30am"], {})
        assert result == "10:30am"

    def test_coming_soon_time_gets_clock_badge(self):
        assert bot._format_time_label("9:00am", "ComingSoon") == "9:00am 🕒"

    def test_formats_mixed_list_with_coming_soon(self):
        times = ["9:00am", "1:15pm", "4:00pm"]
        status_by_time = {"9:00am": "ComingSoon", "1:15pm": "AlmostFull", "4:00pm": "Sellable"}

        result = bot._format_times_with_badges(times, status_by_time)

        assert result == "9:00am 🕒, 1:15pm ⚠️, 4:00pm"


class TestClassifyShowtime:
    """Decides what a polled (format, time) entry means for notification
    purposes, given whether it's been seen before and what status was
    recorded then vs. now. Kept pure/DB-free so the branching logic that
    drives the polling loop's two notification paths is unit-testable.
    """

    def test_unseen_is_new(self):
        assert bot._classify_showtime(seen=False, stored_status=None, current_status="ComingSoon") == "new"

    def test_unseen_is_new_regardless_of_current_status(self):
        assert bot._classify_showtime(seen=False, stored_status=None, current_status="Sellable") == "new"

    def test_seen_with_no_stored_status_is_backfill(self):
        assert bot._classify_showtime(seen=True, stored_status=None, current_status="ComingSoon") == "backfill"

    def test_seen_with_no_stored_status_is_backfill_even_if_currently_sellable(self):
        assert bot._classify_showtime(seen=True, stored_status=None, current_status="Sellable") == "backfill"

    def test_coming_soon_to_sellable_is_now_available(self):
        assert bot._classify_showtime(seen=True, stored_status="ComingSoon", current_status="Sellable") == "now_available"

    def test_coming_soon_to_almost_full_is_now_available(self):
        assert bot._classify_showtime(seen=True, stored_status="ComingSoon", current_status="AlmostFull") == "now_available"

    def test_coming_soon_to_coming_soon_is_unchanged(self):
        assert bot._classify_showtime(seen=True, stored_status="ComingSoon", current_status="ComingSoon") == "unchanged"

    def test_sellable_to_almost_full_is_unchanged(self):
        assert bot._classify_showtime(seen=True, stored_status="Sellable", current_status="AlmostFull") == "unchanged"

    def test_sellable_to_sellable_is_unchanged(self):
        assert bot._classify_showtime(seen=True, stored_status="Sellable", current_status="Sellable") == "unchanged"


class TestSlugReconciliationDetection:
    """A tracked movie's slug can go stale when AMC reissues it (event
    placeholder -> real Coming Soon listing, e.g. Dune: Part Three going
    from dune-part-three-83391 to dune-part-three-77032 while keeping the
    exact same title). Detecting this means comparing tracked slugs against
    each fresh coming-soon payload.
    """

    def test_reissued_id_is_detected_as_candidate(self):
        tracked = [("dune-part-three-83391", "Dune: Part Three")]
        coming_soon = [
            {"slug": "dune-part-three-77032", "name": "Dune: Part Three"},
            {"slug": "the-odyssey-76238", "name": "The Odyssey"},
        ]
        candidates, ambiguous = bot._find_slug_reconciliation_candidates(tracked, coming_soon)
        assert candidates == [("dune-part-three-83391", "dune-part-three-77032", "Dune: Part Three")]
        assert ambiguous == []

    def test_normal_graduation_out_of_coming_soon_is_not_flagged(self):
        # The tracked movie left coming-soon (e.g. now playing) — nothing
        # else in the fresh list shares its name, so there's no candidate.
        tracked = [("the-odyssey-76238", "The Odyssey")]
        coming_soon = [{"slug": "dune-part-three-77032", "name": "Dune: Part Three"}]
        candidates, ambiguous = bot._find_slug_reconciliation_candidates(tracked, coming_soon)
        assert candidates == []
        assert ambiguous == []

    def test_still_present_slug_is_not_flagged(self):
        tracked = [("dune-part-three-77032", "Dune: Part Three")]
        coming_soon = [{"slug": "dune-part-three-77032", "name": "Dune: Part Three"}]
        candidates, ambiguous = bot._find_slug_reconciliation_candidates(tracked, coming_soon)
        assert candidates == []
        assert ambiguous == []

    def test_ambiguous_match_is_reported_separately_not_as_a_candidate(self):
        tracked = [("some-movie-111", "Some Movie")]
        coming_soon = [
            {"slug": "some-movie-222", "name": "Some Movie"},
            {"slug": "some-movie-333", "name": "Some Movie"},
        ]
        candidates, ambiguous = bot._find_slug_reconciliation_candidates(tracked, coming_soon)
        assert candidates == []
        assert ambiguous == [("some-movie-111", "Some Movie", ["some-movie-222", "some-movie-333"])]

    def test_name_match_is_case_insensitive(self):
        tracked = [("dune-part-three-83391", "dune: part three")]
        coming_soon = [{"slug": "dune-part-three-77032", "name": "Dune: Part Three"}]
        candidates, ambiguous = bot._find_slug_reconciliation_candidates(tracked, coming_soon)
        assert candidates == [("dune-part-three-83391", "dune-part-three-77032", "dune: part three")]

    def test_duplicate_tracked_pairs_only_produce_one_candidate(self):
        # The Odyssey is tracked at the same theater across 3 separate
        # date-range rows in tracked_movies — the same (slug, name) pair
        # repeats. Should still only produce one candidate, not three.
        tracked = [
            ("the-odyssey-76238", "The Odyssey"),
            ("the-odyssey-76238", "The Odyssey"),
            ("the-odyssey-76238", "The Odyssey"),
        ]
        coming_soon = [{"slug": "the-odyssey-99999", "name": "The Odyssey"}]
        candidates, ambiguous = bot._find_slug_reconciliation_candidates(tracked, coming_soon)
        assert candidates == [("the-odyssey-76238", "the-odyssey-99999", "The Odyssey")]


class TestReconciliationAutoConfirmTiming:
    """No telegram.ext persistence is configured, so a pending reconciliation's
    1-hour auto-confirm timer is lost on a restart (which happens after every
    deploy). Startup needs to recompute remaining time rather than trusting
    an in-memory job survived.
    """

    def test_recent_proposal_has_remaining_time(self):
        now = datetime.datetime(2026, 7, 24, 12, 0, 0)
        proposed_at = datetime.datetime(2026, 7, 24, 11, 30, 0).isoformat()  # 30 min ago
        remaining = bot._seconds_until_auto_confirm(proposed_at, now=now)
        assert remaining == 1800  # 30 min left of the 1-hour window

    def test_just_proposed_has_nearly_full_window(self):
        now = datetime.datetime(2026, 7, 24, 12, 0, 0)
        proposed_at = now.isoformat()
        remaining = bot._seconds_until_auto_confirm(proposed_at, now=now)
        assert remaining == 3600

    def test_overdue_proposal_is_zero_or_negative(self):
        now = datetime.datetime(2026, 7, 24, 14, 0, 0)
        proposed_at = datetime.datetime(2026, 7, 24, 11, 0, 0).isoformat()  # 3h ago
        remaining = bot._seconds_until_auto_confirm(proposed_at, now=now)
        assert remaining <= 0
