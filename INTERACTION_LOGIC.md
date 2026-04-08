# AMC Bot Interaction & UI Guide

This document documents the conversation flow and formatting rules for the Telegram bot.

## 1. Global Commands
- `/start` & `/help`: Basic onboarding.
- `/status`: Returns bot health and tracking statistics.
- `/list`: Lists all current tracking tasks in a single message with horizontal dividers.
- `/remove`: Opens an inline menu to delete specific tracking tasks.

## 2. Conversation States (The Flow)
Both `/check` and `/track` share a common initialization flow:

### Step 1: Movie Selection
- **Buttons**: Shows Top 10 Now Playing and Top 5 Coming Soon.
- **Manual Input**: Supports natural language. Uses token-based matching (e.g., "Prada2" -> "The Devil Wears Prada 2").
- **Resolution**: If multiple movies match, the bot presents a sub-menu of up to 10 candidates.

### Step 2: Theater Selection
- **Default**: A quick-action button for "AMC Lincoln Square 13".
- **Manual**: Matches input against `theaters.json`. Supports neighborhood names (e.g., "Upper West Side").

### Step 3: Date/Range Entry
- **Format**: Supports `M/D` (e.g., `4/11`) or `M/D-M/D` (e.g., `4/11-4/15`).
- **Validation**: Automatically rejects dates in the past.
- **Rollover**: Handles year-end rollover (e.g., entering "1/1" while in December).

### Step 4: Format Checklist (Track Only)
- **UI**: A persistent inline grid with toggleable formats (IMAX, Dolby, etc.).
- **Feedback**: Displays a ✅ checkmark next to selected items.
- **Completion**: Task is saved only when the user clicks **✨ DONE**.

## 3. Message Formatting Rules
To maintain a high-signal, minimal aesthetic:

### Result Headers
- **Movie**: 🎬 **[Movie Name]** (Bold + Emoji)
- **Theater**: 📍 [Theater Name]
- **Date**: 📅 [YYYY-MM-DD]

### Showtime Body
- **Grouped**: Times are grouped by format.
- **Format Label**: *[Format Name]* (Bold Italics, No Emoji)
- **Time Slots**: [Time], [Time] (Comma separated, No Emoji)

### Notification Logic
- **Check**: One consolidated message per date requested.
- **Track**: One grouped message per date found. Triggered immediately upon setup completion and thereafter every 10 minutes.
