import os
import time
import json
import logging
import asyncio
import datetime
import difflib
import re
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters
)

from database import (
    init_db, add_tracked_movie, get_tracked_movies,
    remove_tracked_movie, is_showtime_seen, mark_showtime_seen,
    is_format_new, upsert_registry_movie, remove_registry_movie,
    upgrade_registry_to_advanced, get_registry_movies,
    add_recent_movie, get_recent_movies
)
from scraper import AMCScraper

# Load environment variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("CHAT_ID", "0"))

if not TOKEN:
    print("Error: BOT_TOKEN not found in .env file.")
    exit(1)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for ConversationHandler
SELECT_MOVIE, SELECT_THEATER, SELECT_DATE, SELECT_FORMAT = range(4)

# Global scraper instance
scraper = AMCScraper()

# Load theaters
with open('theaters.json', 'r') as f:
    THEATERS_DATA = json.load(f)['theaters']

def is_authorized(update: Update):
    return update.effective_user.id == OWNER_ID

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    await update.message.reply_text(
        "Welcome to AMC Showtime Monitor Bot!\n\n"
        "Commands:\n"
        "/checkshowtime - Quick check for showtimes\n"
        "/trackmovie - Start tracking a movie\n"
        "/trackinglist - Show tracked movies\n"
        "/remove - Stop tracking a movie\n"
        "/botstatus - Bot status\n"
        "/refreshcookies - Force cookie refresh\n"
        "/refreshmovielist - Refresh movie lists (Now Playing, Events, Coming Soon)\n"
        "/movies - Show upcoming movie registry\n"
        "/cancel - Cancel current action\n"
        "/help - Show this message"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

def _age_str(ts):
    """Convert a unix timestamp to a human-readable age string."""
    if not ts:
        return "Never"
    mins = int((time.time() - ts) / 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    return f"{mins // 60}h {mins % 60}m ago"

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    tracked = get_tracked_movies()

    # Harvest cooldown
    cooldown_str = "None"
    if time.time() < scraper._harvest_cooldown_until:
        remaining = int((scraper._harvest_cooldown_until - time.time()) / 60)
        cooldown_str = f"Active — {remaining}m remaining"

    # Movie list cache validity
    list_age = _age_str(scraper.last_list_refresh)
    list_valid_for = max(0, int((43200 - (time.time() - scraper.last_list_refresh)) / 60)) if scraper.last_list_refresh else 0

    # Polling health
    failures = context.bot_data.get('consecutive_poll_failures', 0)
    poll_status = "OK" if failures == 0 else f"⚠️ {failures} consecutive failure(s)"

    # Last fail reason (truncate if long)
    fail_reason = scraper.last_fail_reason or "None"
    if len(fail_reason) > 80:
        fail_reason = fail_reason[:77] + "..."

    msg = (
        f"*Bot Status: RUNNING*\n"
        f"Tracking: {len(tracked)} task(s)\n\n"
        f"🍪 *Cookies*\n"
        f"  Harvested: {_age_str(scraper.last_cookie_harvest)}\n"
        f"  Stored: {len(scraper.cookies)} cookies\n"
        f"  Last successful fetch: {_age_str(scraper.last_successful_fetch)}\n"
        f"  Last failed fetch: {_age_str(scraper.last_failed_fetch)}\n"
        f"  Last fail reason: {fail_reason}\n"
        f"  Harvest cooldown: {cooldown_str}\n\n"
        f"🎬 *Movie list*\n"
        f"  Last updated: {list_age}"
        + (f" (valid {list_valid_for}m more)" if scraper.last_list_refresh else "") + "\n"
        f"  Now Playing: {len(scraper.movie_list_cache.get('now-playing', []))}, "
        f"Events: {len(scraper.movie_list_cache.get('events', []))}, "
        f"Coming Soon: {len(scraper.movie_list_cache.get('coming-soon', []))}\n\n"
        f"📡 *Polling*\n"
        f"  Last poll: {context.bot_data.get('last_check', 'Never')}\n"
        f"  Consecutive failures: {failures}\n"
        f"  Status: {poll_status}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def list_tracked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    tracked = get_tracked_movies()
    if not tracked:
        await update.message.reply_text("You are not tracking any movies.")
        return

    msg = "Current tracking tasks:\n"
    for row in tracked:
        track_id, user_id, movie_name, movie_slug, theater_name, theater_slug, date_range, formats, created_at = row
        msg += f"\n*#{track_id}* {movie_name}\n📍 {theater_name}\n📅 {date_range}  🎬 {formats}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def remove_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    tracked = get_tracked_movies()
    if not tracked:
        await update.message.reply_text("Nothing to remove.")
        return

    keyboard = []
    for row in tracked:
        track_id, user_id, movie_name, movie_slug, theater_name, theater_slug, date_range, formats, created_at = row
        btn_text = f"{movie_name} @ {theater_name} ({date_range})"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"remove_{track_id}")])

    await update.message.reply_text("Select a task to remove:", reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(update): return
    await query.answer()

    track_id = int(query.data.replace("remove_", ""))
    remove_tracked_movie(track_id)
    await query.edit_message_text(f"Task #{track_id} removed.")

async def refresh_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return

    COOKIE_HEALTHY_WINDOW = 1800  # 30 minutes
    harvest_age = time.time() - scraper.last_cookie_harvest if scraper.last_cookie_harvest else None
    fetch_age = time.time() - scraper.last_successful_fetch if scraper.last_successful_fetch else None

    cookies_healthy = (
        harvest_age is not None and harvest_age < COOKIE_HEALTHY_WINDOW and
        fetch_age is not None and fetch_age < COOKIE_HEALTHY_WINDOW
    )

    if cookies_healthy:
        harvest_str = _age_str(scraper.last_cookie_harvest)
        fetch_str = _age_str(scraper.last_successful_fetch)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, force refresh", callback_data="confirm_refresh"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_refresh")
        ]])
        await update.message.reply_text(
            f"⚠️ *Cookies look healthy*\n"
            f"  Harvested: {harvest_str}\n"
            f"  Last successful fetch: {fetch_str}\n\n"
            f"Harvest a new cookie anyway?",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await _do_refresh(update.message)

async def _do_refresh(msg_or_query):
    """Run the actual harvest and edit the status message with the result."""
    is_query = hasattr(msg_or_query, 'edit_message_text')
    if is_query:
        await msg_or_query.edit_message_text(
            "🔄 Refreshing cookies with stealth browser...\n"
            "Attempt 1/2 — this may take up to 60s per attempt."
        )
        send = msg_or_query.edit_message_text
    else:
        status_msg = await msg_or_query.reply_text(
            "🔄 Refreshing cookies with stealth browser...\n"
            "Attempt 1/2 — this may take up to 60s per attempt."
        )
        send = status_msg.edit_text

    success = await asyncio.to_thread(scraper.harvest_cookies, force=True)
    if success:
        await send("✅ Cookies refreshed successfully!")
    else:
        reason = scraper.last_fail_reason or "Unknown error"
        await send(f"❌ Cookie refresh failed after 2 attempts.\n\n{reason}")

async def confirm_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(update): return
    await query.answer()
    await _do_refresh(query)

async def cancel_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(update): return
    await query.answer()
    await query.edit_message_text("Cancelled.")

async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

def _sync_movie_registry(lists):
    """Update movie_registry from fresh list data. Called after refreshmovielist."""
    coming_soon = lists.get("coming-soon", [])

    logger.info(f"[Registry] Syncing: {len(coming_soon)} coming-soon movies")

    added = 0
    for m in coming_soon:
        try:
            upsert_registry_movie(m['slug'], m['name'], "future_release",
                                  release_date=m.get("release_date"),
                                  url=m.get("url"))
            added += 1
        except Exception as e:
            logger.error(f"[Registry] Failed to upsert {m['slug']}: {e}")

    logger.info(f"[Registry] Sync done: {added} added/updated")
    return added

async def refresh_movie_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    status_msg = await update.message.reply_text(
        "🔄 Refreshing movie lists (Now Playing, Events, Coming Soon)..."
    )
    counts = await asyncio.to_thread(scraper.refresh_movie_list)
    if any(v > 0 for v in counts.values()):
        # Sync registry with fresh data
        registry_count = _sync_movie_registry(scraper.movie_list_cache)
        lines = "\n".join(
            f"  {'Now Playing' if k == 'now-playing' else k.replace('-', ' ').title()}: {v}"
            for k, v in counts.items()
        )
        reg_movies = get_registry_movies()
        await status_msg.edit_text(
            f"✅ Movie lists refreshed!\n\n{lines}\n\n"
            f"Registry: {len(reg_movies)} upcoming movies tracked"
        )
    else:
        await status_msg.edit_text("❌ Failed to fetch movie lists. Cookies may need refreshing — try /refresh first.")

async def show_movie_registry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    movies = get_registry_movies()
    if not movies:
        await update.message.reply_text(
            "Registry is empty.\n\nRun /refreshmovielist to populate it from AMC's coming-soon list."
        )
        return

    advanced = [(slug, name, release_date, url) for slug, name, status, first, last, release_date, url in movies if status == "advanced_tickets"]
    future = [(slug, name, release_date, url) for slug, name, status, first, last, release_date, url in movies if status == "future_release"]

    # Build lines, then send in chunks to stay under Telegram's 4096 char limit
    lines = [f"*Upcoming Movie Registry* ({len(movies)} total)\n"]
    if advanced:
        lines.append(f"\n🎟 *Advanced Tickets Available* ({len(advanced)})")
        for slug, name, release_date, url in advanced:
            date_str = f" — opens {release_date}" if release_date else ""
            lines.append(f"  • [{name}]({url}){date_str}")
    if future:
        lines.append(f"\n🔮 *Future Releases* ({len(future)})")
        for slug, name, release_date, url in future:
            date_str = f" — {release_date}" if release_date else " — TBD"
            lines.append(f"  • [{name}]({url}){date_str}")
    lines.append(f"\n_Use /refreshmovielist to sync._")

    chunk = ""
    for line in lines:
        candidate = chunk + line + "\n"
        if len(candidate) > 3800:
            await update.message.reply_text(chunk, parse_mode="Markdown")
            chunk = line + "\n"
        else:
            chunk = candidate
    if chunk:
        await update.message.reply_text(chunk, parse_mode="Markdown")

# --- TRACK / CHECK FLOW ---

async def initiate_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return ConversationHandler.END

    cmd = update.message.text.split()[0][1:]  # e.g. 'trackmovie' or 'checkshowtime'
    context.user_data['action'] = 'track' if cmd == 'trackmovie' else 'check'

    status_msg = await update.message.reply_text(
        "🤖 Fetching movie lists from AMC...\n"
        "Please wait — up to 90s if cookies need refreshing (Chrome harvest on Pi)."
    )

    try:
        full_now_playing = await asyncio.to_thread(scraper.get_movies_list, "now-playing")
        full_events = await asyncio.to_thread(scraper.get_movies_list, "events")
        full_coming_soon = await asyncio.to_thread(scraper.get_movies_list, "coming-soon")

        seen_slugs = set()
        all_movies = []
        for m in (full_now_playing + full_events + full_coming_soon):
            if m['slug'] not in seen_slugs:
                all_movies.append(m)
                seen_slugs.add(m['slug'])

        context.user_data['movie_list'] = all_movies

        seen_btn_slugs = set()
        button_movies = []
        for m in (full_now_playing[:8] + full_events[:4] + full_coming_soon[:4]):
            if m['slug'] not in seen_btn_slugs:
                button_movies.append(m)
                seen_btn_slugs.add(m['slug'])

        keyboard = []

        # Recent movies section
        recents = get_recent_movies(limit=4)
        if recents:
            keyboard.append([InlineKeyboardButton("🕐 Recently Used:", callback_data="noop")])
            for i in range(0, len(recents), 2):
                row = [InlineKeyboardButton(recents[j][1], callback_data=f"mv_recent_{recents[j][0]}")
                       for j in range(i, min(i + 2, len(recents)))]
                keyboard.append(row)

        for i in range(0, len(button_movies), 2):
            row = []
            for m in button_movies[i:i+2]:
                idx = all_movies.index(m)
                row.append(InlineKeyboardButton(m['name'], callback_data=f"mv_{idx}"))
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_flow")])

        await status_msg.delete()
        await update.message.reply_text(
            "🎬 Select a movie, type a name, or paste an AMC URL:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECT_MOVIE
    except Exception as e:
        logger.error(f"Error in initiate_flow: {e}")
        await status_msg.edit_text("❌ An error occurred while fetching movies.")
        return ConversationHandler.END

async def movie_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    movie_slug = None
    movie_name = None
    all_movies = context.user_data.get('movie_list', [])

    if query:
        await query.answer()
        if query.data.startswith("mv_recent_"):
            slug = query.data.replace("mv_recent_", "")
            # Look up in current list first; fall back to recent_movies DB (movie may be off AMC)
            match = next((m for m in all_movies if m['slug'] == slug), None)
            if match:
                movie_name, movie_slug = match['name'], match['slug']
            else:
                recents = get_recent_movies(limit=8)
                rec = next((r for r in recents if r[0] == slug), None)
                if rec:
                    movie_name, movie_slug = rec[1], rec[0]
                else:
                    await query.edit_message_text("❌ Could not find that movie. Please search by name.")
                    return SELECT_MOVIE
        else:
            try:
                idx = int(query.data.replace("mv_", ""))
                movie_name, movie_slug = all_movies[idx]['name'], all_movies[idx]['slug']
            except:
                await query.edit_message_text("❌ Selection expired. Please start over.")
                return ConversationHandler.END
    else:
        text = update.message.text.strip()

        # URL or bare slug input — bypass search entirely
        url_match = re.search(r'amctheatres\.com/movies/([a-z0-9-]+-\d+)', text)
        slug_match = re.match(r'^([a-z0-9-]+-\d+)$', text.lower())
        if url_match or slug_match:
            movie_slug = (url_match or slug_match).group(1)
            match = next((m for m in all_movies if m['slug'] == movie_slug), None)
            if match:
                movie_name = match['name']
            else:
                movie_name = " ".join(movie_slug.split('-')[:-1]).title()
            await update.message.reply_text(f"🎯 Using: *{movie_name}*", parse_mode="Markdown")
        else:
            clean_input = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', text).lower()
            clean_input = re.sub(r'[^a-z0-9 ]', '', clean_input).strip()
            input_tokens = set(clean_input.split())

            matches = []
            for m in all_movies:
                name_norm = re.sub(r'[^a-z0-9 ]', '', m['name'].lower())
                slug_norm = m['slug'].replace('-', ' ')
                if clean_input in name_norm or all(t in name_norm or t in slug_norm for t in input_tokens):
                    if m not in matches: matches.append(m)

            if not matches:
                names = [m['name'] for m in all_movies]
                fuzzy = difflib.get_close_matches(clean_input, names, n=5, cutoff=0.4)
                for fn in fuzzy:
                    for m in all_movies:
                        if m['name'] == fn and m not in matches: matches.append(m)

            if not matches:
                await update.message.reply_text(
                    f"❌ Could not find \"{text}\".\n\nTry a name, paste an AMC URL, or pick from the list."
                )
                return SELECT_MOVIE
            elif len(matches) == 1:
                movie_name, movie_slug = matches[0]['name'], matches[0]['slug']
                await update.message.reply_text(f"🎯 Matched to: *{movie_name}*", parse_mode="Markdown")
            else:
                keyboard = []
                for m in matches[:10]:
                    idx = all_movies.index(m)
                    keyboard.append([InlineKeyboardButton(m['name'], callback_data=f"mv_{idx}")])
                await update.message.reply_text(
                    f"🔍 Multiple matches for \"{text}\":",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return SELECT_MOVIE

    context.user_data['movie_name'] = movie_name
    context.user_data['movie_slug'] = movie_slug
    add_recent_movie(movie_slug, movie_name, f"https://www.amctheatres.com/movies/{movie_slug}")
    keyboard = [
        [InlineKeyboardButton("AMC Lincoln Square 13", callback_data="theater_amc-lincoln-square-13")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_flow")]
    ]
    msg = f"🎬 *{movie_name}*\n\n📍 Select a theater or enter a neighborhood manually:"
    if query:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return SELECT_THEATER

async def theater_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    theater_slug = None
    theater_name = None
    theater_market = None

    if query:
        await query.answer()
        theater_slug = query.data.replace("theater_", "")
        for t in THEATERS_DATA:
            if t['slug'] == theater_slug:
                theater_name = t['name']
                theater_market = t.get('market', 'new-york-city')
                break
    else:
        text = update.message.text.lower()
        best_match = None
        highest_score = 0
        for t in THEATERS_DATA:
            score = difflib.SequenceMatcher(None, text, t['name'].lower()).ratio()
            for term in t['search_terms']:
                term_score = difflib.SequenceMatcher(None, text, term.lower()).ratio()
                score = max(score, term_score)
            if score > highest_score:
                highest_score = score
                best_match = t
        if highest_score > 0.5:
            theater_name = best_match['name']
            theater_slug = best_match['slug']
            theater_market = best_match.get('market', 'new-york-city')
        else:
            await update.message.reply_text(
                "❌ Could not find that theater. Please try again or enter a neighborhood."
            )
            return SELECT_THEATER

    context.user_data['theater_name'] = theater_name
    context.user_data['theater_slug'] = theater_slug
    context.user_data['theater_market'] = theater_market
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_flow")]])
    msg = (f"🎬 *{context.user_data['movie_name']}*\n📍 {theater_name}\n\n"
           f"📅 Enter date (e.g. 4/11) or range (e.g. 4/11-4/15):")
    if query:
        await query.edit_message_text(msg, reply_markup=cancel_kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=cancel_kb, parse_mode="Markdown")
    return SELECT_DATE

async def date_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    action = context.user_data['action']
    dates = get_dates_from_range(text)
    if not dates:
        await update.message.reply_text(
            "❌ Invalid date format. Use M/D (e.g., 4/11) or M/D-M/D (e.g., 4/11-4/13)."
        )
        return SELECT_DATE
    now = datetime.date.today()
    first_date = datetime.datetime.strptime(dates[0], "%Y-%m-%d").date()
    if first_date < now:
        await update.message.reply_text(
            f"❌ The date *{dates[0]}* is in the past. Please enter a future date.",
            parse_mode="Markdown"
        )
        return SELECT_DATE

    context.user_data['date_range'] = text

    if action == 'check':
        status_msg = await update.message.reply_text(
            f"🔍 Checking showtimes for *{context.user_data['movie_name']}*...\nPlease wait.",
            parse_mode="Markdown"
        )
        try:
            found_any = False
            for date in dates:
                user_data_copy = dict(context.user_data)
                user_data_copy['date_range'] = date
                results = await asyncio.to_thread(run_single_check_sync, user_data_copy)
                if results:
                    found_any = True
                    movie_slug = context.user_data['movie_slug']
                    theater_slug = context.user_data['theater_slug']
                    msg = (f"🎬 *{context.user_data['movie_name']}*\n"
                           f"📍 {context.user_data['theater_name']}\n📅 {date}\n")
                    for fmt, times in results.items():
                        badge = "🆕 " if is_format_new(movie_slug, theater_slug, date, fmt) else ""
                        msg += f"\n{badge}*{fmt}*\n{', '.join(times)}\n"
                        # Mark as seen so future checks and polls track newness correctly
                        for t in times:
                            if not is_showtime_seen(movie_slug, theater_slug, date, fmt, t):
                                mark_showtime_seen(movie_slug, theater_slug, date, fmt, t)
                    await update.message.reply_text(msg, parse_mode="Markdown")
                await asyncio.sleep(1)
            if not found_any:
                await status_msg.edit_text("❌ No showtimes found for the selected dates.")
            else:
                await status_msg.delete()
        except Exception as e:
            logger.error(f"Error in check: {e}")
            await status_msg.edit_text("❌ An error occurred during scraping.")
        return ConversationHandler.END
    else:
        context.user_data['selected_formats'] = []
        return await show_format_selection(update, context)

async def show_format_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected = context.user_data.get('selected_formats', [])
    keyboard = []
    for f_list in [["IMAX", "Dolby"], ["70mm", "Laser"]]:
        row = [
            InlineKeyboardButton(f"✅ {f}" if f in selected else f, callback_data=f"fmt_{f}")
            for f in f_list
        ]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("✅ ALL" if "ALL" in selected else "ALL", callback_data="fmt_ALL")])
    keyboard.append([InlineKeyboardButton("✨ DONE", callback_data="fmt_DONE")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_flow")])
    msg = "🎬 Select formats to track (click multiple):"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_FORMAT

async def format_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    fmt = query.data.replace("fmt_", "")
    selected = context.user_data.get('selected_formats', [])

    if fmt == "DONE":
        fmts_str = ",".join(selected) or "ALL"
        add_tracked_movie(
            OWNER_ID,
            context.user_data['movie_name'], context.user_data['movie_slug'],
            context.user_data['theater_name'], context.user_data['theater_slug'],
            context.user_data['date_range'], fmts_str
        )
        msg = (f"✅ *TRACKING STARTED*\n\n🎬 *{context.user_data['movie_name']}*\n"
               f"📍 {context.user_data['theater_name']}\n📅 {context.user_data['date_range']}\n\n"
               f"*Formats:* {fmts_str}\n\nI will notify you as soon as new showtimes appear!")
        await query.edit_message_text(msg, parse_mode="Markdown")
        asyncio.create_task(polling_task(context))
        return ConversationHandler.END
    elif fmt == "ALL":
        selected = ["ALL"] if "ALL" not in selected else []
    else:
        if "ALL" in selected: selected.remove("ALL")
        if fmt in selected: selected.remove(fmt)
        else: selected.append(fmt)

    context.user_data['selected_formats'] = selected
    return await show_format_selection(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Action cancelled.")
    return ConversationHandler.END

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Action cancelled.")
    return ConversationHandler.END

# --- POLLING LOGIC ---

def run_single_check_sync(user_data):
    date_str = user_data['date_range']
    parsed_date = parse_date_input(date_str)
    movie_slug = user_data['movie_slug']
    theater_slug = user_data['theater_slug']
    theater_market = user_data.get('theater_market', 'new-york-city')
    url = f"https://www.amctheatres.com/movie-theatres/{theater_market}/{theater_slug}/showtimes?date={parsed_date}"
    logger.info(f"Checking URL: {url}")
    html = scraper.get_page_data(url)
    if not html: return None
    all_data = scraper.parse_showtimes(html)
    return all_data.get(movie_slug)

def parse_date_input(text):
    try:
        now = datetime.datetime.now()
        if "/" in text:
            parts = text.split("/")
            month, day = int(parts[0]), int(parts[1])
            year = now.year if month >= now.month else now.year + 1
            return datetime.date(year, month, day).strftime("%Y-%m-%d")
    except:
        pass
    return text

def get_dates_from_range(text):
    dates = []
    try:
        if "-" in text:
            start_str, end_str = text.split("-", 1)
            start_parsed = parse_date_input(start_str.strip())
            end_parsed = parse_date_input(end_str.strip())
            start_dt = datetime.datetime.strptime(start_parsed, "%Y-%m-%d").date()
            end_dt = datetime.datetime.strptime(end_parsed, "%Y-%m-%d").date()
            curr = start_dt
            while curr <= end_dt:
                dates.append(curr.strftime("%Y-%m-%d"))
                curr += datetime.timedelta(days=1)
        else:
            dates.append(parse_date_input(text.strip()))
    except Exception as e:
        logger.error(f"Error parsing date range '{text}': {e}")
    return dates

POLL_FAILURE_ALERT_THRESHOLD = 3    # alert after this many consecutive failures
POLL_FAILURE_ALERT_COOLDOWN = 1800  # seconds between repeated alerts

async def polling_task(context: ContextTypes.DEFAULT_TYPE):
    cookie_age = _age_str(scraper.last_cookie_harvest)
    logger.info(f"Starting background polling cycle... Cookies: {cookie_age}")
    tracked = get_tracked_movies()
    market_map = {t['slug']: t.get('market', 'new-york-city') for t in THEATERS_DATA}

    for row in tracked:
        track_id, user_id, movie_name, movie_slug, theater_name, theater_slug, date_range, target_formats, _ = row
        market = market_map.get(theater_slug, 'new-york-city')
        dates = get_dates_from_range(date_range)

        for date in dates:
            url = f"https://www.amctheatres.com/movie-theatres/{market}/{theater_slug}/showtimes?date={date}"
            html = await asyncio.to_thread(scraper.get_page_data, url)
            if not html:
                failures = context.bot_data.get('consecutive_poll_failures', 0) + 1
                context.bot_data['consecutive_poll_failures'] = failures
                logger.warning(f"Fetch failed for {movie_name} @ {theater_slug} ({date}). Consecutive failures: {failures}")
                # Alert owner if failures hit threshold and cooldown has passed
                last_alert = context.bot_data.get('last_poll_alert', 0)
                if failures >= POLL_FAILURE_ALERT_THRESHOLD and (time.time() - last_alert) > POLL_FAILURE_ALERT_COOLDOWN:
                    reason = scraper.last_fail_reason or "Unknown error"
                    alert_msg = (
                        f"⚠️ *Polling Warning*\n"
                        f"{failures} consecutive fetch failure(s).\n\n"
                        f"Last error: {reason}\n\n"
                        f"Check /status for details."
                    )
                    try:
                        await context.bot.send_message(chat_id=OWNER_ID, text=alert_msg, parse_mode="Markdown")
                        context.bot_data['last_poll_alert'] = time.time()
                    except Exception as e:
                        logger.error(f"Failed to send poll alert: {e}")
                continue
            context.bot_data['consecutive_poll_failures'] = 0  # reset on success

            all_data = scraper.parse_showtimes(html)
            new_showtimes_found = {}

            if movie_slug in all_data:
                # Showtimes detected — upgrade registry status if applicable
                if upgrade_registry_to_advanced(movie_slug):
                    logger.info(f"[Registry] {movie_name} upgraded to advanced_tickets")
                for fmt_name, times in all_data[movie_slug].items():
                    if target_formats != "ALL":
                        target_fmts_list = [f.strip().lower() for f in target_formats.split(",")]
                        if not any(tf in fmt_name.lower() for tf in target_fmts_list):
                            continue
                    for time_val in times:
                        if not is_showtime_seen(movie_slug, theater_slug, date, fmt_name, time_val):
                            new_showtimes_found.setdefault(fmt_name, []).append(time_val)
                            mark_showtime_seen(movie_slug, theater_slug, date, fmt_name, time_val)

            if new_showtimes_found:
                msg = f"🔔 *NEW SHOWTIMES FOUND!*\n\n🎬 *{movie_name}*\n📍 {theater_name}\n📅 {date}\n"
                for fmt, times in new_showtimes_found.items():
                    badge = "🆕 " if is_format_new(movie_slug, theater_slug, date, fmt) else ""
                    msg += f"\n{badge}*{fmt}*\n{', '.join(times)}\n"
                msg += f"\n[Book Tickets](https://www.amctheatres.com/movies/{movie_slug})"
                try:
                    await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Failed to send notification to {user_id}: {e}")

            await asyncio.sleep(2)

    context.bot_data['last_check'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors but suppress noisy transient network errors."""
    err = context.error
    if isinstance(err, Exception) and "NetworkError" in type(err).__name__:
        logger.warning(f"Transient network error (auto-retry): {err}")
    else:
        logger.error(f"Unhandled error: {err}", exc_info=err)

async def post_init(application):
    if OWNER_ID:
        try:
            await application.bot.send_message(chat_id=OWNER_ID, text="🤖 Bot Started!\n\nSend /start")
        except Exception as e:
            logger.error(f"Failed to send startup message: {e}")

if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("trackmovie", initiate_flow),
            CommandHandler("checkshowtime", initiate_flow)
        ],
        states={
            SELECT_MOVIE: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_flow$"),
                CallbackQueryHandler(movie_selected, pattern="^mv_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, movie_selected)
            ],
            SELECT_THEATER: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_flow$"),
                CallbackQueryHandler(theater_selected, pattern="^theater_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, theater_selected)
            ],
            SELECT_DATE: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_flow$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, date_entered)
            ],
            SELECT_FORMAT: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_flow$"),
                CallbackQueryHandler(format_callback, pattern="^fmt_")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("botstatus", status))
    app.add_handler(CommandHandler("trackinglist", list_tracked))
    app.add_handler(CommandHandler("remove", remove_movie))
    app.add_handler(CommandHandler("refreshcookies", refresh_cookies))
    app.add_handler(CommandHandler("refreshmovielist", refresh_movie_list_cmd))
    app.add_handler(CommandHandler("movies", show_movie_registry))
    app.add_handler(CallbackQueryHandler(confirm_refresh_callback, pattern="^confirm_refresh$"))
    app.add_handler(CallbackQueryHandler(cancel_refresh_callback, pattern="^cancel_refresh$"))
    app.add_handler(CallbackQueryHandler(remove_callback, pattern="^remove_"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern="^noop$"))
    app.add_handler(conv_handler)
    app.add_error_handler(error_handler)
    app.job_queue.run_repeating(polling_task, interval=600, first=10)

    print("\n" + "="*30 + "\n🤖 AMC Showtime Monitor running!\n💬 Message your bot in Telegram\n🛑 Ctrl+C to stop\n" + "="*30 + "\n")
    app.run_polling()
