# AMC Telegram Bot - Complete Setup Guide

## 🚀 Quick Start (5 Minutes)

### Step 1: Create Your Telegram Bot

1. **Open Telegram** and search for `@BotFather`
2. **Start a chat** and send: `/newbot`
3. **Choose a name** (e.g., "AMC Showtime Notifier")
4. **Choose a username** (must end in 'bot', e.g., "amc_showtime_bot")
5. **Save your token** - BotFather will give you something like:
   ```
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
   ⚠️ **Keep this secret!** This is your bot's password.

### Step 2: Install Python Dependencies

```bash
pip install requests beautifulsoup4
```

### Step 3: Run the Bot (First Time)

```bash
python amc_telegram_bot.py YOUR_BOT_TOKEN
```

The script will ask you to send a message to your bot. Do this:
1. Find your bot in Telegram (search for the username you created)
2. Click "Start" or send any message
3. The script will automatically find your chat ID

### Step 4: Add the Movie URL

When prompted, paste the AMC movie page URL:
```
https://www.amctheatres.com/movies/wicked-70896
```

### Step 5: Done! 🎉

The bot is now running and will send you Telegram notifications when showtimes change!

---

## 📱 Full Usage Examples

### Basic Usage (Interactive)
```bash
python amc_telegram_bot.py 123456:ABC-DEF
# Script will help you find your chat ID and ask for URL
```

### Advanced Usage (Non-Interactive)
```bash
python amc_telegram_bot.py \
  123456:ABC-DEF \
  987654321 \
  "https://www.amctheatres.com/movies/wicked-70896" \
  300
```

Arguments:
1. `BOT_TOKEN` - From BotFather
2. `CHAT_ID` - Your Telegram chat ID (found on first run)
3. `AMC_URL` - Movie page URL
4. `INTERVAL` - Check interval in seconds (default: 300 = 5 minutes)

---

## 🔧 Advanced Setup

### Running as a Background Service (Linux/Mac)

**Using screen:**
```bash
screen -S amc-monitor
python amc_telegram_bot.py YOUR_TOKEN YOUR_CHAT_ID "YOUR_URL"
# Press Ctrl+A, then D to detach
# Reattach with: screen -r amc-monitor
```

**Using nohup:**
```bash
nohup python amc_telegram_bot.py YOUR_TOKEN YOUR_CHAT_ID "YOUR_URL" &
# Check logs: tail -f nohup.out
# Stop: ps aux | grep amc_telegram_bot
#       kill <PID>
```

**Using tmux:**
```bash
tmux new -s amc-monitor
python amc_telegram_bot.py YOUR_TOKEN YOUR_CHAT_ID "YOUR_URL"
# Press Ctrl+B, then D to detach
# Reattach with: tmux attach -t amc-monitor
```

### Running as a System Service (Linux systemd)

Create `/etc/systemd/system/amc-monitor.service`:

```ini
[Unit]
Description=AMC Showtime Monitor
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME
Environment="PATH=/usr/bin:/usr/local/bin"
ExecStart=/usr/bin/python3 /home/YOUR_USERNAME/amc_telegram_bot.py \
  YOUR_BOT_TOKEN \
  YOUR_CHAT_ID \
  "YOUR_AMC_URL" \
  300
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable amc-monitor
sudo systemctl start amc-monitor

# Check status
sudo systemctl status amc-monitor

# View logs
sudo journalctl -u amc-monitor -f
```

### Running on Windows

**Using Task Scheduler:**

1. Open Task Scheduler
2. Create Basic Task
3. Trigger: At system startup
4. Action: Start a program
   - Program: `python`
   - Arguments: `C:\path\to\amc_telegram_bot.py YOUR_TOKEN YOUR_CHAT_ID "URL"`
5. Save and run

**Or use a batch file:**
```batch
@echo off
cd C:\path\to\script
python amc_telegram_bot.py YOUR_TOKEN YOUR_CHAT_ID "YOUR_URL"
pause
```

---

## 🌐 Running on a Free Cloud Server

### Option 1: PythonAnywhere (Free Tier)

1. **Sign up** at https://www.pythonanywhere.com (free account)

2. **Upload your script** via Files tab

3. **Install dependencies** in Bash console:
   ```bash
   pip3 install --user requests beautifulsoup4
   ```

4. **Create scheduled task** in Tasks tab:
   ```bash
   python3 /home/YOUR_USERNAME/amc_telegram_bot.py YOUR_TOKEN YOUR_CHAT_ID "URL"
   ```

5. **Or use "Always-on task"** (paid feature) for continuous monitoring

### Option 2: Replit (Free)

1. **Sign up** at https://replit.com

2. **Create new Repl** (Python)

3. **Paste your script** and install dependencies:
   ```bash
   poetry add requests beautifulsoup4
   ```

4. **Set secrets** (Environment variables):
   - `BOT_TOKEN`
   - `CHAT_ID`
   - `AMC_URL`

5. **Modify script** to read from environment:
   ```python
   import os
   bot_token = os.getenv('BOT_TOKEN')
   chat_id = os.getenv('CHAT_ID')
   movie_url = os.getenv('AMC_URL')
   ```

6. **Keep alive** with UptimeRobot pinging your Repl URL

### Option 3: Oracle Cloud (Free Tier - Best Option)

Free VPS with generous limits:

1. **Sign up** at https://www.oracle.com/cloud/free/

2. **Create VM instance** (Always Free tier)
   - Ubuntu 22.04
   - 1 GB RAM (sufficient)

3. **SSH into server** and install dependencies:
   ```bash
   sudo apt update
   sudo apt install python3-pip
   pip3 install requests beautifulsoup4
   ```

4. **Upload script** via SCP:
   ```bash
   scp amc_telegram_bot.py ubuntu@YOUR_SERVER_IP:/home/ubuntu/
   ```

5. **Set up systemd service** (see above)

6. **Runs 24/7 completely free!**

### Option 4: Heroku (Was Free, Now Paid)

Now requires paid plan, but if you have credits:

1. Create `requirements.txt`:
   ```
   requests
   beautifulsoup4
   ```

2. Create `Procfile`:
   ```
   worker: python amc_telegram_bot.py $BOT_TOKEN $CHAT_ID $AMC_URL
   ```

3. Deploy:
   ```bash
   git init
   heroku create
   heroku config:set BOT_TOKEN=your_token
   heroku config:set CHAT_ID=your_chat_id
   heroku config:set AMC_URL=your_url
   git add .
   git commit -m "Deploy bot"
   git push heroku main
   heroku ps:scale worker=1
   ```

---

## 🔍 Finding Your Chat ID (Manual Method)

If the automatic detection doesn't work:

1. **Send a message** to your bot
2. **Visit this URL** in your browser:
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
3. **Look for "chat":{"id":123456789**
4. That number is your chat ID!

Example:
```json
{
  "ok": true,
  "result": [
    {
      "update_id": 123,
      "message": {
        "message_id": 1,
        "from": {...},
        "chat": {
          "id": 987654321,  // <-- This is your chat ID!
          "first_name": "Your Name",
          "type": "private"
        },
        "text": "Hello"
      }
    }
  ]
}
```

---

## 🎨 Customization Tips

### Change Notification Format

Edit the `format_notification` method:

```python
def format_notification(self, data):
    # Custom format
    message = "🍿 SHOWTIMES ALERT! 🍿\n\n"
    message += f"Movie page updated at {datetime.now().strftime('%I:%M %p')}\n"
    message += f"Check it out: {self.movie_url}"
    return message
```

### Monitor Multiple Movies

Create a wrapper script:

```python
import subprocess
import sys

movies = [
    ("https://www.amctheatres.com/movies/wicked-70896", "Wicked"),
    ("https://www.amctheatres.com/movies/dune-part-two-12345", "Dune"),
]

bot_token = sys.argv[1]
chat_id = sys.argv[2]

for url, name in movies:
    print(f"Starting monitor for {name}...")
    subprocess.Popen([
        "python3", "amc_telegram_bot.py",
        bot_token, chat_id, url, "300"
    ])
```

### Add Sound to Notifications

Telegram supports notification sounds by default, but you can customize in Telegram settings:

1. Open Telegram
2. Settings → Notifications and Sounds
3. Find your bot's notifications
4. Set custom sound

### Check Specific Times Only

Modify the main loop to only check during AMC release windows:

```python
from datetime import datetime

def should_check_now():
    now = datetime.now()
    # Only check Tuesdays 8 AM - 2 PM ET
    if now.weekday() == 1:  # Tuesday
        if 8 <= now.hour < 14:
            return True
    return False

# In the main loop:
while True:
    if should_check_now():
        current_data = self.get_showtimes()
        # ... rest of logic
    else:
        print(f"Outside monitoring window, sleeping...")
    
    time.sleep(interval)
```

---

## 🐛 Troubleshooting

### "Invalid bot token"
- Double-check token from BotFather
- Make sure there are no extra spaces
- Token format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

### "Chat ID not found"
- Make sure you clicked "Start" on your bot
- Try the manual chat ID method above
- Send a message and wait 5 seconds before running script

### "Failed to fetch showtimes"
- Check your internet connection
- Verify the AMC URL is correct
- AMC might have changed their HTML structure
- Try adding `--debug` flag to see HTML

### Bot sends notifications but I don't receive them
- Check Telegram notification settings
- Make sure bot isn't muted
- Check if messages are going to "Archived Chats"

### "Connection timeout"
- Your network might block Telegram API
- Try using a VPN
- Check firewall settings

### Running on server but stops after logout
- Use `screen`, `tmux`, or `nohup` (see above)
- Or set up as systemd service

---

## 📊 Monitoring Status

### Check if bot is running:

```bash
ps aux | grep amc_telegram_bot
```

### View logs:

```bash
tail -f nohup.out  # if using nohup
journalctl -u amc-monitor -f  # if using systemd
```

### Test bot manually:

```python
python3
>>> from amc_telegram_bot import TelegramBot
>>> bot = TelegramBot("YOUR_TOKEN")
>>> bot.send_message("YOUR_CHAT_ID", "Test message")
```

---

## 🎯 Pro Tips

1. **Set interval based on urgency:**
   - Normal: 300s (5 min)
   - Release week: 60s (1 min)
   - Release day: 30s (30 sec)

2. **Run on release days only:**
   - Stop after showtimes release
   - Saves bandwidth and API calls

3. **Use multiple monitors:**
   - Different theaters
   - Different movies
   - Different formats (IMAX, Dolby, etc.)

4. **Combine with other alerts:**
   - Bot can also send to Slack, Discord, etc.
   - Modify `send_message` to call multiple APIs

5. **Add retry logic:**
   - If AMC site is down temporarily
   - Exponential backoff for rate limits

---

## 🔐 Security Best Practices

1. **Never share your bot token**
2. **Use environment variables** for sensitive data
3. **Don't commit tokens to Git** (use `.gitignore`)
4. **Restrict bot commands** (only respond to your chat ID)
5. **Use HTTPS** for webhook mode (advanced)

Example `.gitignore`:
```
.env
*.cache.json
nohup.out
__pycache__/
```

Example with environment variables:
```bash
export BOT_TOKEN="123456:ABC-DEF"
export CHAT_ID="987654321"
export AMC_URL="https://..."

python amc_telegram_bot.py $BOT_TOKEN $CHAT_ID $AMC_URL
```

---

## 📈 Next Steps

Once you have the basic bot running, you can:

1. **Add commands** (`/status`, `/stop`, `/change_movie`)
2. **Add inline buttons** for quick actions
3. **Support multiple users** (store chat IDs in database)
4. **Add webhook mode** (instead of polling)
5. **Create web dashboard** to manage monitoring
6. **Add analytics** (track response times, changes)

---

## 🆘 Need Help?

Common commands to get unstuck:

```bash
# Check Python version (need 3.6+)
python3 --version

# Install packages
pip3 install requests beautifulsoup4

# Run with full output
python3 amc_telegram_bot.py YOUR_TOKEN 2>&1 | tee output.log

# Find running processes
ps aux | grep python

# Kill stuck process
kill <PID>
```

---

**Ready to go? Start with Step 1 and message @BotFather!** 🚀
