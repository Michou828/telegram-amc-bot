from scraper import AMCScraper


def _next_f_html(payload):
    """Wrap a raw JSON-ish payload the way AMC's Next.js RSC stream encodes it:
    self.__next_f.push([N,"<payload with every double-quote escaped>"])
    parse_showtimes() unescapes \\" -> " and \\\\ -> \\ to recover this text.
    """
    escaped = payload.replace('"', '\\"')
    return f'<script>self.__next_f.push([1,"{escaped}"])</script>'


def _showtime_json(showtime_id, status, time, am_pm):
    return (
        '{"showtimeId":' + str(showtime_id) + ',"policyCodes":[],'
        '"hasTrailers":true,"status":"' + status + '",'
        '"showDateTimeUtc":"2026-07-24T14:30:00.000Z",'
        '"display":{"time":"' + time + '","amPm":"' + am_pm + '"},'
        '"discountMatineeMessage":null,"maximumIntendedAttendance":null}'
    )


def _sample_page(showtimes):
    """Build a minimal synthetic RSC payload: one movie, one format header,
    followed by the given showtime JSON blobs (in stream order)."""
    movie = '{"avatarImage":{"url":"x"},"name":"Moana","slug":"moana-72474"}'
    format_header = '["$","h3",null,{"id":"fmt-1","children":["$","span",null,{"children":"IMAX with Laser at AMC"}]}]'
    body = movie + format_header + "".join(showtimes)
    return _next_f_html(body)


class TestParseShowtimeStatus:
    """Bug: sold-out/near-capacity showtimes were notified identically to wide-open
    ones because parse_showtimes() only extracted showtimeId/time/amPm and threw
    away AMC's own "status" field (confirmed live values: "Sellable", "AlmostFull").
    """

    def test_captures_sellable_status(self):
        s = AMCScraper()
        html = _sample_page([_showtime_json(1, "Sellable", "10:30", "am")])

        results, statuses = s.parse_showtimes(html)

        assert results["moana-72474"]["IMAX with Laser at AMC"] == ["10:30am"]
        assert statuses["moana-72474"]["IMAX with Laser at AMC"]["10:30am"] == "Sellable"

    def test_captures_almost_full_status(self):
        s = AMCScraper()
        html = _sample_page([_showtime_json(2, "AlmostFull", "1:15", "pm")])

        results, statuses = s.parse_showtimes(html)

        assert results["moana-72474"]["IMAX with Laser at AMC"] == ["1:15pm"]
        assert statuses["moana-72474"]["IMAX with Laser at AMC"]["1:15pm"] == "AlmostFull"

    def test_multiple_showtimes_tracked_independently(self):
        s = AMCScraper()
        html = _sample_page([
            _showtime_json(1, "Sellable", "10:30", "am"),
            _showtime_json(2, "AlmostFull", "1:15", "pm"),
        ])

        results, statuses = s.parse_showtimes(html)

        fmt_statuses = statuses["moana-72474"]["IMAX with Laser at AMC"]
        assert fmt_statuses["10:30am"] == "Sellable"
        assert fmt_statuses["1:15pm"] == "AlmostFull"

    def test_empty_html_returns_empty_statuses(self):
        s = AMCScraper()
        results, statuses = s.parse_showtimes("")
        assert results == {}
        assert statuses == {}
