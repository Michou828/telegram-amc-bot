# AMC Theatres — Find Now Playing Movie URLs

## Goal
Find all **Now Playing** movies on AMC Theatres and retrieve their individual movie page URLs.

---

## What We Know

### Site Tech Stack
- **URL**: https://www.amctheatres.com/movies
- **Framework**: Next.js 15 App Router with React Server Components (RSC)
- Movie data is rendered **server-side** — no client-side API call appears in the browser Network tab during a normal page load.
- The underlying data API is a **GraphQL endpoint**.

---

## Method 1: Scrape URLs Directly from the Web Page (No API Needed)

Navigate to https://www.amctheatres.com/movies and extract all anchor tags whose `href` matches the pattern `/movies/<slug>`.

### URL Pattern
Every AMC movie page follows this structure:
```
https://www.amctheatres.com/movies/<title-slug>-<movieId>
```

**Examples from live site (as of March 2026):**
| Movie Title | URL |
|---|---|
| Project Hail Mary | https://www.amctheatres.com/movies/project-hail-mary-76779 |
| Ready or Not 2: Here I Come | https://www.amctheatres.com/movies/ready-or-not-2-here-i-come-80592 |
| Reminders of Him | https://www.amctheatres.com/movies/reminders-of-him-71462 |
| Dhurandhar The Revenge | https://www.amctheatres.com/movies/dhurandhar-the-revenge-83060 |
| Hoppers | https://www.amctheatres.com/movies/hoppers-72462 |

### Extraction Steps
1. Navigate to `https://www.amctheatres.com/movies`
2. Wait for the page to fully load (it's server-rendered, so content is in the initial HTML)
3. Use JavaScript to extract all movie links:
```javascript
const links = Array.from(document.querySelectorAll('a[href^="/movies/"]'));
const movieUrls = [...new Set(
  links
    .map(l => l.getAttribute('href'))
    .filter(href => /^\/movies\/[a-z0-9-]+-\d+$/.test(href)) // slug + numeric ID only
)].map(href => 'https://www.amctheatres.com' + href);

console.log(movieUrls);
```

4. This returns a deduplicated array of all Now Playing movie page URLs.

### Why This Works
The AMC movies page is server-rendered — all movie cards (with their `<a>` tags) are present in the initial HTML. No JavaScript execution or API call is needed to get the links. Each movie card has **two** `<a>` tags pointing to the same URL (one wraps the poster image, one wraps the title), so deduplication is important.

---

## Method 2: GraphQL API (If Direct DOM Access Fails)

AMC has a public-facing GraphQL API that the website uses server-side.

### Endpoint
```
POST https://graph.amctheatres.com
```

### Request Headers
```
Content-Type: application/json
Accept: application/json
```

### Query to Get Now Playing Movies
```graphql
{
  viewer {
    movies(availability: NOW_PLAYING, first: 100) {
      edges {
        node {
          movieId
          name
          slug
          status
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
```

### How to Run It (JavaScript in browser console)
```javascript
const response = await fetch('https://graph.amctheatres.com', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  },
  body: JSON.stringify({
    query: `{
      viewer {
        movies(availability: NOW_PLAYING, first: 100) {
          edges {
            node {
              movieId
              name
              slug
              status
            }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    }`
  })
});
const data = await response.json();
const movies = data.data.viewer.movies.edges.map(e => e.node);
const urls = movies.map(m => ({
  name: m.name,
  url: `https://www.amctheatres.com/movies/${m.slug}`
}));
console.table(urls);
```

### Constructing the URL from API Data
The `slug` field directly maps to the URL path:
```
https://www.amctheatres.com/movies/{slug}
```
Example: slug = `project-hail-mary-76779` → URL = `https://www.amctheatres.com/movies/project-hail-mary-76779`

### Available `availability` Filter Values
- `NOW_PLAYING`
- `COMING_SOON`
- `ADVANCE_TICKETS`
- `EVENTS`
- `ON_DEMAND`
- `NOT_IN_THEATRES`
- `ALL`

---

## Movie Object Fields Available (from GraphQL Schema)

| Field | Type | Notes |
|---|---|---|
| `movieId` | `Int` | Numeric ID (e.g. `76779`) |
| `name` | `String` | Movie title |
| `slug` | `String` | URL path segment (e.g. `project-hail-mary-76779`) |
| `mpaaRating` | `String` | `PG`, `PG13`, `R`, `NR`, etc. |
| `runTime` | `Int` | Duration in minutes |
| `genre` | `String` | Primary genre |
| `secondaryGenre` | `String` | Secondary genre (may be null) |
| `synopsis` | `String` | Full plot description |
| `status` | `MovieStatus` | e.g. `NOW_PLAYING` |
| `releaseDateDisplay` | `DateDisplay` | Sub-fields: `monthDayYear`, `prefix`, `date`, `year`, etc. |
| `starringActors` | `String` | Cast |
| `directors` | `String` | Director(s) |
| `preferredPoster` | `Media` | Poster image — query `.url` sub-field |
| `preferredTrailer` | `Media` | Trailer video — query `.url` sub-field |

---

## Recommended Approach

**Start with Method 1** (DOM scraping). It's simpler, requires no API knowledge, and works because:
- The page is server-rendered (movies are in the HTML on first load)
- The URL pattern is consistent and easy to filter with a regex
- No authentication or special headers required

**Fall back to Method 2** (GraphQL) if:
- The page structure has changed
- You need additional metadata (rating, runtime, cast, etc.) alongside the URL
- You want to filter by availability type programmatically

---

## Notes
- The GraphQL API does **not** require authentication for public movie data queries (as of March 2026).
- Pagination: use `pageInfo.hasNextPage` and pass `after: endCursor` to page through results if there are more than your `first` limit.
- The `first: 100` argument should be more than enough to capture all Now Playing titles at any given time.
