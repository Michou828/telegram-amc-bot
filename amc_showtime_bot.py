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
    get_showtime_status, update_showtime_status,
    is_format_new, upsert_registry_movie, remove_registry_movie,
    upgrade_registry_to_advanced, get_registry_movies,
    add_recent_movie, get_recent_movies,
    add_slug_reconciliation, get_slug_reconciliation_pair, get_slug_reconciliation,
    set_slug_reconciliation_message_id, resolve_slug_reconciliation,
    apply_slug_reconciliation, get_pending_slug_reconciliations
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

HELP_TEXT = (
    "🎬 *Check & Track*\n"
    "/check — One-time showtime lookup\n"
    "/track — Monitor a movie for new showtimes\n\n"
    "📋 *Tracking List*\n"
    "/trackinglist — View all tracked movies\n"
    "/remove — Stop tracking a movie\n\n"
    "🎥 *Movie Browser*\n"
    "/movies — Browse Now Playing, Coming Soon & Events\n"
    "/refreshmovielist — Sync movie lists from AMC\n\n"
    "⚙️ *System*\n"
    "/botstatus — Bot health, cookie age, poll stats\n"
    "/refreshcookies — Force a fresh cookie harvest\n\n"
    "🔧 *Other*\n"
    "/cancel — Cancel the current action\n"
    "/help — Show this message"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    await update.message.reply_text(
        "Welcome to AMC Showtime Monitor Bot!\n\n" + HELP_TEXT,
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    await update.message.reply_text(
        "❓ Unknown command.\n\n" + HELP_TEXT,
        parse_mode="Markdown"
    )

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

    # Polling health — per tracked (movie, theater, date) item
    poll_failures = context.bot_data.get('poll_failures', {})
    if not poll_failures:
        poll_status = "OK"
    else:
        worst = max(poll_failures.values())
        poll_status = f"⚠️ {len(poll_failures)} item(s) failing (worst: {worst} consecutive)"

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
        f"Coming Soon: {len(scraper.movie_list_cache.get('coming-soon', []))}, "
        f"Events: {len(scraper.movie_list_cache.get('events', []))}\n\n"
        f"📡 *Polling*\n"
        f"  Last poll: {context.bot_data.get('last_check', 'Never')}\n"
        f"  Consecutive failures: {failures}\n"
        f"  Status: {poll_status}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

def _build_tracking_groups(tracked):
    """Group tracked rows by (movie_slug, theater_slug). Returns ordered list of group dicts."""
    groups = {}
    order = []
    for row in tracked:
        track_id, user_id, movie_name, movie_slug, theater_name, theater_slug, date_range, formats, _ = row
        key = (movie_slug, theater_slug)
        if key not in groups:
            groups[key] = {'name': movie_name, 'slug': movie_slug,
                           'theater': theater_name, 'formats': {}, 'entries': []}
            order.append(key)
        groups[key]['entries'].append((track_id, formats, date_range))
        for fmt in [f.strip() for f in formats.split(',')]:
            groups[key]['formats'].setdefault(fmt, []).append(date_range)
    return [groups[k] for k in order]

def _remove_keyboard(entries, selected):
    """Build the toggle keyboard for step-2 removal."""
    keyboard = []
    for track_id, formats, date_range in entries:
        check = "✅" if track_id in selected else "☐"
        keyboard.append([InlineKeyboardButton(
            f"{check} {formats} — {date_range}",
            callback_data=f"rmtoggle_{track_id}"
        )])
    n = len(selected)
    row = []
    if n:
        row.append(InlineKeyboardButton(f"🗑 Remove Selected ({n})", callback_data="rmconfirm"))
    row.append(InlineKeyboardButton("❌ Cancel", callback_data="rmcancel"))
    keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

async def list_tracked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    tracked = get_tracked_movies()
    if not tracked:
        await update.message.reply_text("You are not tracking any movies.\n\nUse /track to start.")
        return

    groups = _build_tracking_groups(tracked)
    lines = [f"*Tracking {len(groups)} movie(s):*\n"]
    for i, g in enumerate(groups, 1):
        mid = re.search(r'-(\d+)$', g['slug'])
        id_str = f" #{mid.group(1)}" if mid else ""
        lines.append(f"*#{i} {g['name']}{id_str}*")
        lines.append(f"📍 {g['theater']}")
        for fmt, dates in g['formats'].items():
            lines.append(f"  _{fmt}_: {', '.join(dates)}")
        lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def remove_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    tracked = get_tracked_movies()
    if not tracked:
        await update.message.reply_text("Nothing to remove.")
        return

    groups = _build_tracking_groups(tracked)
    context.bot_data['rm_groups'] = groups  # store for step-2

    keyboard = []
    for i, g in enumerate(groups):
        mid = re.search(r'-(\d+)$', g['slug'])
        id_str = f" #{mid.group(1)}" if mid else ""
        keyboard.append([InlineKeyboardButton(
            f"#{i+1} {g['name']}{id_str}", callback_data=f"rmpick_{i}"
        )])
    await update.message.reply_text("Select a movie:", reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(update): return
    await query.answer()

    idx = int(query.data.replace("rmpick_", ""))
    groups = context.bot_data.get('rm_groups', [])
    if idx >= len(groups):
        await query.edit_message_text("❌ Session expired. Run /remove again.")
        return

    g = groups[idx]
    mid = re.search(r'-(\d+)$', g['slug'])
    id_str = f" #{mid.group(1)}" if mid else ""
    context.bot_data['rm_entries'] = g['entries']
    context.bot_data['rm_selected'] = set()
    context.bot_data['rm_title'] = f"{g['name']}{id_str} @ {g['theater']}"

    await query.edit_message_text(
        f"Select entries to remove:\n*{context.bot_data['rm_title']}*",
        reply_markup=_remove_keyboard(g['entries'], set()),
        parse_mode="Markdown"
    )

async def remove_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(update): return
    await query.answer()

    track_id = int(query.data.replace("rmtoggle_", ""))
    selected = context.bot_data.get('rm_selected', set())
    if track_id in selected:
        selected.discard(track_id)
    else:
        selected.add(track_id)
    context.bot_data['rm_selected'] = selected

    entries = context.bot_data.get('rm_entries', [])
    title = context.bot_data.get('rm_title', '')
    await query.edit_message_text(
        f"Select entries to remove:\n*{title}*",
        reply_markup=_remove_keyboard(entries, selected),
        parse_mode="Markdown"
    )

async def remove_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(update): return
    await query.answer()

    selected = context.bot_data.get('rm_selected', set())
    if not selected:
        await query.answer("Nothing selected.", show_alert=True)
        return
    for track_id in selected:
        remove_tracked_movie(track_id)
    context.bot_data.pop('rm_groups', None)
    context.bot_data.pop('rm_entries', None)
    context.bot_data.pop('rm_selected', None)
    context.bot_data.pop('rm_title', None)
    await query.edit_message_text(f"✅ Removed {len(selected)} {'entry' if len(selected) == 1 else 'entries'}.")

async def remove_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(update): return
    await query.answer()
    context.bot_data.pop('rm_groups', None)
    context.bot_data.pop('rm_entries', None)
    context.bot_data.pop('rm_selected', None)
    context.bot_data.pop('rm_title', None)
    await query.edit_message_text("Cancelled.")

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
    """Update movie_registry from fresh list data. Called after refreshmovielist.

    Returns {"added": int, "candidates": list, "ambiguous": list} — the
    latter two come from comparing currently-tracked movies against this
    sync's coming-soon payload, to catch AMC slug/ID reissues.
    """
    coming_soon = lists.get("coming-soon", [])
    logger.info(f"[Registry] Syncing: {len(coming_soon)} coming-soon movies")
    added = 0
    for m in coming_soon:
        try:
            status = "advanced_tickets" if m.get("has_advanced_tickets") else "future_release"
            upsert_registry_movie(m['slug'], m['name'], status,
                                  release_date=m.get("release_date"),
                                  url=m.get("url"))
            added += 1
        except Exception as e:
            logger.error(f"[Registry] Failed to upsert {m['slug']}: {e}")
    logger.info(f"[Registry] Sync done: {added} added/updated")

    tracked_pairs = [(row[3], row[2]) for row in get_tracked_movies()]  # (movie_slug, movie_name)
    candidates, ambiguous = _find_slug_reconciliation_candidates(tracked_pairs, coming_soon)
    return {"added": added, "candidates": candidates, "ambiguous": ambiguous}

async def _handle_reconciliation_results(context, candidates, ambiguous):
    for old_slug, new_slug, movie_name in candidates:
        try:
            if get_slug_reconciliation_pair(old_slug, new_slug) is not None:
                continue  # already proposed or resolved for this exact pair — never re-ask
            rec_id = add_slug_reconciliation(old_slug, new_slug, movie_name)
            text = (
                f"🔄 *Possible AMC ID change detected*\n\n"
                f"*{movie_name}* seems to have a new ID:\n"
                f"`{old_slug}` → `{new_slug}`\n\n"
                f"Update tracking? Auto-applies in 1 hour if no response."
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Update", callback_data=f"reconcile_yes_{rec_id}"),
                InlineKeyboardButton("❌ Keep old ID", callback_data=f"reconcile_no_{rec_id}")
            ]])
            msg = await context.bot.send_message(
                chat_id=OWNER_ID, text=text, parse_mode="Markdown", reply_markup=keyboard
            )
            set_slug_reconciliation_message_id(rec_id, msg.message_id)
            context.job_queue.run_once(
                _auto_confirm_reconciliation_job,
                when=RECONCILIATION_AUTO_CONFIRM_SECONDS,
                data=rec_id,
                name=f"reconcile_auto_{rec_id}"
            )
        except Exception as e:
            # Isolated per-candidate: one failure (DB write or Telegram send)
            # doesn't stop the rest of this batch from being proposed, and
            # nothing is marked resolved, so it's naturally retried next sync.
            logger.error(f"[Reconciliation] Failed to propose {old_slug} -> {new_slug} for {movie_name}: {e}")

    for old_slug, movie_name, candidate_slugs in ambiguous:
        # Dedup sentinel: encode the sorted candidate set into new_slug so
        # repeat syncs with the same ambiguous combination don't re-nag.
        # status='ambiguous' keeps this row out of get_pending_slug_reconciliations()
        # entirely — no auto-confirm job, no buttons, nothing to ever apply.
        sentinel = "AMBIGUOUS:" + "|".join(sorted(candidate_slugs))
        if get_slug_reconciliation_pair(old_slug, sentinel) is not None:
            continue  # already reported this exact ambiguous combination
        text = (
            f"⚠️ *Ambiguous AMC ID match*\n\n"
            f"*{movie_name}* (tracked as `{old_slug}`) is missing from the latest "
            f"list, but multiple entries share its name:\n"
            + "\n".join(f"  • `{s}`" for s in candidate_slugs)
            + "\n\nResolve manually with /remove + /track if needed."
        )
        try:
            await context.bot.send_message(chat_id=OWNER_ID, text=text, parse_mode="Markdown")
            add_slug_reconciliation(old_slug, sentinel, movie_name, status="ambiguous")
        except Exception as e:
            # Insert only after a successful send: if the send fails, no dedup
            # row is written and this notice is naturally retried next sync
            # (same pattern as the candidate loop above).
            logger.error(f"[Reconciliation] Failed to send ambiguous notice for {movie_name}: {e}")

async def _resolve_reconciliation(context, rec_id, new_status):
    row = get_slug_reconciliation(rec_id)
    if row is None:
        return
    _, old_slug, new_slug, movie_name, status, proposed_at, resolved_at, message_id = row
    if status != "pending":
        return  # already resolved by the other path (button click vs. auto-confirm job)

    if not resolve_slug_reconciliation(rec_id, new_status):
        return  # lost the race between the read above and this write

    if new_status in ("confirmed", "auto_confirmed"):
        apply_slug_reconciliation(old_slug, new_slug)
        verb = "Auto-updated (no response within 1 hour)" if new_status == "auto_confirmed" else "Updated"
        result_text = f"✅ {verb} — *{movie_name}* now tracked as `{new_slug}`."
    else:
        result_text = f"❌ Left as-is — *{movie_name}* still tracked as `{old_slug}`."

    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=OWNER_ID, message_id=message_id, text=result_text, parse_mode="Markdown"
            )
            return
        except Exception as e:
            logger.error(f"[Reconciliation] Failed to edit message for reconciliation #{rec_id}: {e}")

    # No message_id (the original send_message failed before it could be
    # recorded, or this row otherwise never got one) — fall back to a fresh
    # send so a resolved reconciliation is never applied with zero owner
    # notification. Also covers edit_message_text failing above.
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=result_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[Reconciliation] Failed to send fallback message for reconciliation #{rec_id}: {e}")


async def reconcile_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(update): return
    await query.answer()
    rec_id = int(query.data.split("_")[-1])
    await _resolve_reconciliation(context, rec_id, "confirmed")


async def reconcile_decline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(update): return
    await query.answer()
    rec_id = int(query.data.split("_")[-1])
    await _resolve_reconciliation(context, rec_id, "declined")


async def _auto_confirm_reconciliation_job(context: ContextTypes.DEFAULT_TYPE):
    rec_id = context.job.data
    await _resolve_reconciliation(context, rec_id, "auto_confirmed")

async def _sweep_pending_reconciliations(context: ContextTypes.DEFAULT_TYPE):
    """Runs once at startup. job_queue/bot_data don't persist across
    restarts (no telegram.ext persistence is configured), so a pending
    reconciliation's 1-hour timer is otherwise lost on every deploy. This
    re-arms it for the remaining time, or resolves it immediately if the
    window already passed while the bot was down.
    """
    for row in get_pending_slug_reconciliations():
        rec_id = row[0]
        proposed_at = row[5]
        remaining = _seconds_until_auto_confirm(proposed_at)
        if remaining <= 0:
            await _resolve_reconciliation(context, rec_id, "auto_confirmed")
        else:
            context.job_queue.run_once(
                _auto_confirm_reconciliation_job, when=remaining, data=rec_id, name=f"reconcile_auto_{rec_id}"
            )

def _refresh_movie_lists(scraper_obj):
    """Periodic safety net so newly-added AMC listings don't sit invisible for days.

    get_movies_list() only ever runs when a user happens to invoke /movies,
    /check, /track, or /refreshmovielist — a bot that's been up for weeks can
    carry a stale cache indefinitely if nobody browses movies.

    Deliberately does NOT call get_movies_list() three times in a row: that
    function's 12h staleness check reads a single last_list_refresh timestamp
    shared by all three list types, so the first call's refetch updates that
    timestamp and makes the next call look artificially fresh, silently
    skipping its own refetch even though its cached data is still stale.
    refresh_movie_list() sidesteps this by clearing all three caches to empty
    before fetching, forcing every list type to actually refetch once triggered.

    Returns True if a refresh was triggered (i.e. the registry should be
    re-synced), False if the cache was still fresh and nothing happened.
    """
    if time.time() - scraper_obj.last_list_refresh < 43200:
        return False
    scraper_obj.refresh_movie_list()
    return True

async def refresh_movie_lists_task(context: ContextTypes.DEFAULT_TYPE):
    changed = await asyncio.to_thread(_refresh_movie_lists, scraper)
    if changed:
        logger.info("[MovieList] Periodic refresh picked up new data — syncing registry.")
        result = _sync_movie_registry(scraper.movie_list_cache)
        await _handle_reconciliation_results(context, result["candidates"], result["ambiguous"])

async def refresh_movie_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    status_msg = await update.message.reply_text(
        "🔄 Refreshing movie lists (Now Playing, Coming Soon, Events)..."
    )
    counts = await asyncio.to_thread(scraper.refresh_movie_list)
    if any(v > 0 for v in counts.values()):
        result = _sync_movie_registry(scraper.movie_list_cache)
        await _handle_reconciliation_results(context, result["candidates"], result["ambiguous"])
        label = {"now-playing": "Now Playing", "coming-soon": "Coming Soon", "events": "Events"}
        lines = "\n".join(f"  {label.get(k, k)}: {v}" for k, v in counts.items())
        reg_movies = get_registry_movies()
        await status_msg.edit_text(
            f"✅ Movie lists refreshed!\n\n{lines}\n\n"
            f"Registry: {len(reg_movies)} upcoming movies tracked"
        )
    else:
        await status_msg.edit_text("❌ Failed to fetch movie lists. Cookies may need refreshing — try /refreshcookies first.")

async def show_movie_registry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    now_playing = scraper.movie_list_cache.get("now-playing", [])
    coming_soon = scraper.movie_list_cache.get("coming-soon", [])
    events = scraper.movie_list_cache.get("events", [])

    if not any([now_playing, coming_soon, events]):
        await update.message.reply_text(
            "Movie list is empty.\n\nRun /refreshmovielist to fetch from AMC."
        )
        return

    def _sorted(lst):
        return sorted(lst, key=lambda m: m.get("release_date") or "9999")

    def _section(lst, header, cap, date_fmt):
        lst = _sorted(lst)
        lines = [header]
        for m in lst[:cap]:
            date_str = (f" — {date_fmt}{m['release_date']}" if m.get("release_date") else "")
            url = m.get("url") or f"https://www.amctheatres.com/movies/{m['slug']}"
            lines.append(f"  • [{m['name']}]({url}){date_str}")
        if len(lst) > cap:
            lines.append(f"  _...+{len(lst) - cap} more — search by name in /checkshowtime_")
        return lines

    lines = [f"*AMC Movies*\n"]

    if now_playing:
        lines += _section(now_playing, f"🎬 *Now Playing* ({len(now_playing)})", 20, "")

    if coming_soon:
        adv = [m for m in coming_soon if m.get("has_advanced_tickets")]
        future = [m for m in coming_soon if not m.get("has_advanced_tickets")]
        if adv:
            lines += _section(adv, f"\n🎟 *Advance Tickets On Sale* ({len(adv)})", 30, "opens ")
        if future:
            lines += _section(future, f"\n🔮 *Coming Soon* ({len(future)})", 20, "")

    if events:
        lines += _section(events, f"\n🎭 *Events* ({len(events)})", 20, "")

    age = _age_str(scraper.last_list_refresh) if scraper.last_list_refresh else "never"
    lines.append(f"\n_Last updated: {age} — /refreshmovielist to sync_")

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

    cmd = update.message.text.split()[0][1:]  # 'track' or 'check'
    context.user_data['action'] = 'track' if cmd == 'track' else 'check'

    status_msg = await update.message.reply_text("🤖 Loading movie list...")

    try:
        full_now_playing = await asyncio.to_thread(scraper.get_movies_list, "now-playing")
        full_coming_soon = await asyncio.to_thread(scraper.get_movies_list, "coming-soon")
        full_events = await asyncio.to_thread(scraper.get_movies_list, "events")

        seen_slugs = set()
        all_movies = []
        for m in (full_now_playing + full_coming_soon + full_events):
            if m['slug'] not in seen_slugs:
                all_movies.append(m)
                seen_slugs.add(m['slug'])

        context.user_data['movie_list'] = all_movies

        keyboard = []

        # Show up to 4 recently used movies (only those still on AMC)
        current_slugs = {m['slug'] for m in all_movies}
        recents = [r for r in get_recent_movies(limit=8) if r[0] in current_slugs][:4]
        if recents:
            keyboard.append([InlineKeyboardButton("🕐 Recently Used:", callback_data="noop")])
            for r in recents:
                slug, name = r[0], r[1]
                mid = re.search(r'-(\d+)$', slug)
                label = f"{name} #{mid.group(1)}" if mid else name
                keyboard.append([InlineKeyboardButton(label, callback_data=f"mv_recent_{slug}")])

        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_flow")])

        await status_msg.delete()
        await update.message.reply_text(
            "🎬 Type a movie name or paste an AMC URL:" + ("\n\nOr pick a recent:" if recents else ""),
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
                mid = re.search(r'-(\d+)$', movie_slug)
                id_str = f" \\#{mid.group(1)}" if mid else ""
                await update.message.reply_text(f"🎯 Matched to: *{movie_name}*{id_str}", parse_mode="Markdown")
            else:
                keyboard = []
                for m in matches[:10]:
                    idx = all_movies.index(m)
                    mid = re.search(r'-(\d+)$', m['slug'])
                    label = f"{m['name']} #{mid.group(1)}" if mid else m['name']
                    keyboard.append([InlineKeyboardButton(label, callback_data=f"mv_{idx}")])
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
           f"📅 Enter date(s):\n"
           f"  Single: `7/17`\n"
           f"  Range: `7/17-7/20`\n"
           f"  Mixed: `7/17, 7/20-7/22, 7/25`")
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
            "❌ Invalid date format.\n\n"
            "Examples:\n"
            "  7/17\n"
            "  7/17-7/20\n"
            "  7/17, 7/20-7/22, 7/25"
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
                check_result = await asyncio.to_thread(run_single_check_sync, user_data_copy)
                if check_result:
                    results, statuses = check_result
                    found_any = True
                    movie_slug = context.user_data['movie_slug']
                    theater_slug = context.user_data['theater_slug']
                    msg = (f"🎬 *{context.user_data['movie_name']}*\n"
                           f"📍 {context.user_data['theater_name']}\n📅 {date}\n")
                    for fmt, times in results.items():
                        badge = "🆕 " if is_format_new(movie_slug, theater_slug, date, fmt) else ""
                        msg += f"\n{badge}*{fmt}*\n{_format_times_with_badges(times, statuses.get(fmt, {}))}\n"
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

def _format_time_label(time_str, status):
    """Badge a showtime with AMC's own sellability signal: AlmostFull means it
    may sell out imminently, ComingSoon means it isn't purchasable yet. Any
    other status is treated as available rather than guessed at — we've only
    ever confirmed "Sellable"/"AlmostFull"/"ComingSoon" live."""
    if status == "AlmostFull":
        return f"{time_str} ⚠️"
    if status == "ComingSoon":
        return f"{time_str} 🕒"
    return time_str

def _format_times_with_badges(times, status_by_time):
    return ", ".join(_format_time_label(t, status_by_time.get(t, "Sellable")) for t in times)

def _classify_showtime(seen, stored_status, current_status):
    """What a polled (format, time) entry means for notification purposes.

    seen: whether this exact (movie, theater, date, format, time) tuple has
      ever been recorded in seen_showtimes before.
    stored_status: the status recorded when it was last seen, or None if
      seen but predates the status column (no baseline to compare against).
    current_status: AMC's status for this showtime on this poll.
    """
    if not seen:
        return "new"
    if stored_status is None:
        return "backfill"
    if stored_status == "ComingSoon" and current_status != "ComingSoon":
        return "now_available"
    return "unchanged"

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
    all_data, all_statuses = scraper.parse_showtimes(html)
    times_by_format = all_data.get(movie_slug)
    if not times_by_format:
        return None
    return times_by_format, all_statuses.get(movie_slug, {})

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
    """Parse a date string into a list of YYYY-MM-DD dates.
    Supports: single date, range (M/D-M/D), or comma-separated mix (M/D, M/D-M/D, ...)
    """
    dates = []
    seen = set()
    for segment in [s.strip() for s in text.split(',')]:
        if not segment:
            continue
        try:
            if '-' in segment:
                start_str, end_str = segment.split('-', 1)
                start_dt = datetime.datetime.strptime(
                    parse_date_input(start_str.strip()), "%Y-%m-%d").date()
                end_dt = datetime.datetime.strptime(
                    parse_date_input(end_str.strip()), "%Y-%m-%d").date()
                curr = start_dt
                while curr <= end_dt:
                    d = curr.strftime("%Y-%m-%d")
                    if d not in seen:
                        dates.append(d)
                        seen.add(d)
                    curr += datetime.timedelta(days=1)
            else:
                d = parse_date_input(segment)
                if d not in seen:
                    dates.append(d)
                    seen.add(d)
        except Exception as e:
            logger.error(f"Error parsing date segment '{segment}': {e}")
    return dates

def _filter_future_dates(dates, today=None):
    """Drop dates before today — no point polling showtimes for a date that already passed."""
    if today is None:
        today = datetime.date.today()
    return [d for d in dates if datetime.datetime.strptime(d, "%Y-%m-%d").date() >= today]


def _find_slug_reconciliation_candidates(tracked_pairs, coming_soon_list):
    """Compare currently-tracked (movie_slug, movie_name) pairs against a
    fresh coming-soon payload to find AMC ID reissues.

    Returns (candidates, ambiguous):
      candidates: list of (old_slug, new_slug, movie_name) — exactly one
        same-named, differently-slugged entry exists in the fresh list for
        a tracked slug that's missing from it.
      ambiguous: list of (old_slug, movie_name, [candidate_slugs]) — 2+
        same-named matches found; too risky to auto-resolve.

    A tracked slug simply missing from the fresh list with nothing else
    sharing its name (0 matches) is the normal case — e.g. it graduated to
    now-playing — and isn't reported at all.
    """
    fresh_slugs = {m['slug'] for m in coming_soon_list}
    candidates = []
    ambiguous = []
    seen_old_slugs = set()
    for old_slug, movie_name in tracked_pairs:
        if old_slug in seen_old_slugs:
            continue
        seen_old_slugs.add(old_slug)
        if old_slug in fresh_slugs:
            continue
        matches = [
            m['slug'] for m in coming_soon_list
            if m['name'].strip().lower() == movie_name.strip().lower() and m['slug'] != old_slug
        ]
        if len(matches) == 1:
            candidates.append((old_slug, matches[0], movie_name))
        elif len(matches) > 1:
            ambiguous.append((old_slug, movie_name, matches))
    return candidates, ambiguous


RECONCILIATION_AUTO_CONFIRM_SECONDS = 3600  # auto-apply a proposed slug update after this long with no owner response

def _seconds_until_auto_confirm(proposed_at_iso, now=None):
    """Returns remaining seconds until a reconciliation's auto-confirm
    window closes. <= 0 means the window already passed (overdue)."""
    if now is None:
        now = datetime.datetime.now()
    proposed_at = datetime.datetime.fromisoformat(proposed_at_iso)
    elapsed = (now - proposed_at).total_seconds()
    return RECONCILIATION_AUTO_CONFIRM_SECONDS - elapsed


POLL_FAILURE_ALERT_THRESHOLD = 3    # alert after this many consecutive failures
POLL_FAILURE_ALERT_COOLDOWN = 1800  # seconds between repeated alerts
POLL_REQUEST_DELAY = 1.5            # seconds between sequential showtime fetches — a tracked movie can span dozens of dates at the same theater; firing them back-to-back with no spacing was tripping Cloudflare's soft rate limiting on a random few requests each cycle

# get_page_data() sets this exact reason when a harvest just completed and it
# deliberately deferred the retry to the next call — that's an expected single
# miss by design, not evidence of a real, ongoing problem.
_TRANSIENT_HARVEST_RETRY_REASON = "Harvest succeeded — next request should work."


def _is_transient_harvest_retry(fail_reason):
    return fail_reason == _TRANSIENT_HARVEST_RETRY_REASON


def _register_poll_failure(bot_data, item_key, transient):
    """Track consecutive failures per tracked (movie, theater, date) item.

    Scoped per item so one item's failures don't compound with unrelated
    items' failures into a shared global count. Transient harvest-retry
    misses don't increment — they're expected to resolve on the next call.
    """
    failures = bot_data.setdefault('poll_failures', {})
    if transient:
        return failures.get(item_key, 0)
    failures[item_key] = failures.get(item_key, 0) + 1
    return failures[item_key]


def _register_poll_success(bot_data, item_key):
    bot_data.setdefault('poll_failures', {}).pop(item_key, None)


def _poll_failure_count(bot_data, item_key):
    return bot_data.setdefault('poll_failures', {}).get(item_key, 0)


async def polling_task(context: ContextTypes.DEFAULT_TYPE):
    cookie_age = _age_str(scraper.last_cookie_harvest)
    logger.info(f"Starting background polling cycle... Cookies: {cookie_age}")
    tracked = get_tracked_movies()
    market_map = {t['slug']: t.get('market', 'new-york-city') for t in THEATERS_DATA}

    for row in tracked:
        track_id, user_id, movie_name, movie_slug, theater_name, theater_slug, date_range, target_formats, _ = row
        market = market_map.get(theater_slug, 'new-york-city')
        all_dates = get_dates_from_range(date_range)
        dates = _filter_future_dates(all_dates)
        if len(dates) < len(all_dates):
            logger.info(f"Skipping {len(all_dates) - len(dates)} past date(s) for {movie_name} @ {theater_slug} (track #{track_id})")

        for date in dates:
            item_key = (movie_slug, theater_slug, date)
            url = f"https://www.amctheatres.com/movie-theatres/{market}/{theater_slug}/showtimes?date={date}"
            html = await asyncio.to_thread(scraper.get_page_data, url)
            await asyncio.sleep(POLL_REQUEST_DELAY)
            if not html:
                transient = _is_transient_harvest_retry(scraper.last_fail_reason)
                failures = _register_poll_failure(context.bot_data, item_key, transient)
                if transient:
                    logger.info(f"Deferred retry for {movie_name} @ {theater_slug} ({date}) after cookie harvest — not counted as a failure.")
                else:
                    logger.warning(f"Fetch failed for {movie_name} @ {theater_slug} ({date}). Consecutive failures: {failures}")
                # Alert owner if this specific item's failures hit threshold and cooldown has passed
                last_alert = context.bot_data.get('last_poll_alert', 0)
                if failures >= POLL_FAILURE_ALERT_THRESHOLD and (time.time() - last_alert) > POLL_FAILURE_ALERT_COOLDOWN:
                    reason = scraper.last_fail_reason or "Unknown error"
                    alert_msg = (
                        f"⚠️ *Polling Warning*\n"
                        f"{movie_name} @ {theater_name} ({date}): {failures} consecutive fetch failure(s).\n\n"
                        f"Last error: {reason}\n\n"
                        f"Check /status for details."
                    )
                    try:
                        await context.bot.send_message(chat_id=OWNER_ID, text=alert_msg, parse_mode="Markdown")
                        context.bot_data['last_poll_alert'] = time.time()
                    except Exception as e:
                        logger.error(f"Failed to send poll alert: {e}")
                continue
            _register_poll_success(context.bot_data, item_key)

            all_data, all_statuses = scraper.parse_showtimes(html)
            new_showtimes_found = {}
            now_available_found = {}

            # Match by exact slug first, then fall back to numeric movie ID suffix
            # (GraphQL slugs sometimes differ from theater-page slugs, e.g. the-mandalorian-grogu-60322
            # vs star-wars-the-mandalorian-and-grogu-60322)
            matched_slug = movie_slug
            if movie_slug not in all_data:
                id_suffix = movie_slug.split('-')[-1]
                if id_suffix.isdigit():
                    matched_slug = next((k for k in all_data if k.endswith(f'-{id_suffix}')), None)
                else:
                    matched_slug = None

            matched_statuses = all_statuses.get(matched_slug, {}) if matched_slug else {}

            if matched_slug:
                # Showtimes detected — upgrade registry status if applicable
                if upgrade_registry_to_advanced(movie_slug):
                    logger.info(f"[Registry] {movie_name} upgraded to advanced_tickets")
                for fmt_name, times in all_data[matched_slug].items():
                    if target_formats != "ALL":
                        target_fmts_list = [f.strip().lower() for f in target_formats.split(",")]
                        if not any(tf in fmt_name.lower() for tf in target_fmts_list):
                            continue
                    for time_val in times:
                        current_status = matched_statuses.get(fmt_name, {}).get(time_val, "Sellable")
                        seen = is_showtime_seen(movie_slug, theater_slug, date, fmt_name, time_val)
                        stored_status = get_showtime_status(movie_slug, theater_slug, date, fmt_name, time_val) if seen else None
                        classification = _classify_showtime(seen, stored_status, current_status)

                        if classification == "new":
                            new_showtimes_found.setdefault(fmt_name, []).append(time_val)
                        elif classification == "now_available":
                            now_available_found.setdefault(fmt_name, []).append(time_val)
                        elif classification == "backfill":
                            update_showtime_status(movie_slug, theater_slug, date, fmt_name, time_val, current_status)
                        # "unchanged" -> no-op

            if new_showtimes_found:
                msg = f"🔔 *NEW SHOWTIMES FOUND!*\n\n🎬 *{movie_name}*\n📍 {theater_name}\n📅 {date}\n"
                for fmt, times in new_showtimes_found.items():
                    badge = "🆕 " if is_format_new(movie_slug, theater_slug, date, fmt) else ""
                    msg += f"\n{badge}*{fmt}*\n{_format_times_with_badges(times, matched_statuses.get(fmt, {}))}\n"
                msg += f"\n[Book Tickets](https://www.amctheatres.com/movies/{movie_slug})"
                try:
                    await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
                    for fmt_name, times in new_showtimes_found.items():
                        for time_val in times:
                            status = matched_statuses.get(fmt_name, {}).get(time_val, "Sellable")
                            mark_showtime_seen(movie_slug, theater_slug, date, fmt_name, time_val, status)
                except Exception as e:
                    logger.error(f"Failed to send notification to {user_id}: {e}")

            if now_available_found:
                msg = f"🎟️ *TICKETS NOW AVAILABLE!*\n\n🎬 *{movie_name}*\n📍 {theater_name}\n📅 {date}\n"
                for fmt, times in now_available_found.items():
                    msg += f"\n*{fmt}*\n{_format_times_with_badges(times, matched_statuses.get(fmt, {}))}\n"
                msg += f"\n[Book Tickets](https://www.amctheatres.com/movies/{movie_slug})"
                try:
                    await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
                    for fmt_name, times in now_available_found.items():
                        for time_val in times:
                            status = matched_statuses.get(fmt_name, {}).get(time_val, "Sellable")
                            update_showtime_status(movie_slug, theater_slug, date, fmt_name, time_val, status)
                except Exception as e:
                    logger.error(f"Failed to send now-available notification to {user_id}: {e}")

            await asyncio.sleep(2)

    context.bot_data['last_check'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors but suppress noisy transient network errors."""
    err = context.error
    if isinstance(err, Exception) and "NetworkError" in type(err).__name__:
        logger.warning(f"Transient network error (auto-retry): {err}")
    else:
        logger.error(f"Unhandled error: {err}", exc_info=err)

async def _startup_sequence(context: ContextTypes.DEFAULT_TYPE):
    """Runs shortly after start — harvests cookies and refreshes movie lists, then shows welcome."""
    cookie_age_h = (time.time() - scraper.last_cookie_harvest) / 3600
    skip_harvest = cookie_age_h < 1  # cookies are fresh enough

    try:
        msg = await context.bot.send_message(
            chat_id=OWNER_ID,
            text=(
                "🤖 *Bot Starting Up*\n\n"
                + ("⏭ Stage 1/2: Cookies fresh — skipping harvest\n" if skip_harvest else
                   "⏳ *Stage 1/2: Refreshing cookies...*\n"
                   "   Launching headless Chrome (~45s on Pi)\n\n")
                + "⏸ Stage 2/2: Fetch movie lists (~5s)\n\n"
                "_Please wait before using commands._"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"[Startup] Failed to send status message: {e}")
        return

    # Stage 1: cookies
    if skip_harvest:
        cookie_ok = True
        cookie_line = "✅ Stage 1/2: Cookies are fresh — skipped"
    else:
        cookie_ok = await asyncio.to_thread(scraper.harvest_cookies, None, True)
        if cookie_ok:
            cookie_line = "✅ Stage 1/2: Cookies refreshed"
        else:
            reason = (scraper.last_fail_reason or "Unknown")[:80]
            cookie_line = f"⚠️ Stage 1/2: Cookie refresh failed\n   _{reason}_"

    try:
        await msg.edit_text(
            f"🤖 *Bot Starting Up*\n\n"
            f"{cookie_line}\n\n"
            f"⏳ *Stage 2/2: Fetching movie lists...*\n"
            f"   Now Playing + Coming Soon + Events (~5s)",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    # Stage 2: movie lists
    counts = await asyncio.to_thread(scraper.refresh_movie_list)
    result = _sync_movie_registry(scraper.movie_list_cache)
    await _handle_reconciliation_results(context, result["candidates"], result["ambiguous"])
    label = {"now-playing": "Now Playing", "coming-soon": "Coming Soon", "events": "Events"}
    list_lines = "\n".join(f"  • {label.get(k, k)}: {v}" for k, v in counts.items())
    list_ok = any(v > 0 for v in counts.values())
    list_line = f"✅ Stage 2/2: Movie lists loaded\n{list_lines}" if list_ok else "⚠️ Stage 2/2: Movie list fetch failed"

    try:
        await msg.edit_text(
            f"🤖 *Bot Ready!*\n\n"
            f"{cookie_line}\n"
            f"{list_line}\n\n"
            + HELP_TEXT,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"[Startup] Final message edit failed: {e}")
        try:
            await msg.edit_text("🤖 Bot Ready! Use /help to see commands.")
        except Exception:
            pass

async def post_init(application):
    if OWNER_ID:
        application.job_queue.run_once(_startup_sequence, when=5)
        application.job_queue.run_once(_sweep_pending_reconciliations, when=5)

if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("track", initiate_flow),
            CommandHandler("check", initiate_flow)
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
    app.add_handler(CallbackQueryHandler(reconcile_confirm_callback, pattern=r"^reconcile_yes_\d+$"))
    app.add_handler(CallbackQueryHandler(reconcile_decline_callback, pattern=r"^reconcile_no_\d+$"))
    app.add_handler(CallbackQueryHandler(remove_pick_callback, pattern="^rmpick_"))
    app.add_handler(CallbackQueryHandler(remove_toggle_callback, pattern="^rmtoggle_"))
    app.add_handler(CallbackQueryHandler(remove_confirm_callback, pattern="^rmconfirm$"))
    app.add_handler(CallbackQueryHandler(remove_cancel_callback, pattern="^rmcancel$"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern="^noop$"))
    app.add_handler(conv_handler)
    # Must be last — catches any /command not matched above
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_error_handler(error_handler)
    app.job_queue.run_repeating(polling_task, interval=600, first=10)
    # Safety net: keeps movie lists from silently going stale if nobody runs
    # /movies, /check, /track, or /refreshmovielist for a long stretch.
    app.job_queue.run_repeating(refresh_movie_lists_task, interval=3600, first=60)

    print("\n" + "="*30 + "\n🤖 AMC Showtime Monitor running!\n💬 Message your bot in Telegram\n🛑 Ctrl+C to stop\n" + "="*30 + "\n")
    app.run_polling()
