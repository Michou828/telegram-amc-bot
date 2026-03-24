# Deployment & Update Guide

## Server Info
- **Cloud:** Google Cloud
- **User:** amc-bot
- **Bot directory:** `/home/amc-bot/telegram-amc-bot`
- **Service file:** `/etc/systemd/system/amc-bot.service`
- **Repo:** https://github.com/Michou828/telegram-amc-bot

---

## Updating the Bot (Every Time)

1. Make changes on your Mac and push to GitHub:
```bash
git add -A
git commit -m "describe your change"
git push
```

2. SSH into the server, then pull and restart:
```bash
sudo systemctl stop amc-bot
git pull
sudo systemctl start amc-bot
sudo systemctl status amc-bot
```

---

## Useful Server Commands

```bash
# Check if bot is running
sudo systemctl status amc-bot

# View live logs
sudo journalctl -u amc-bot -f

# Stop the bot
sudo systemctl stop amc-bot

# Start the bot
sudo systemctl start amc-bot

# Restart the bot
sudo systemctl restart amc-bot
```

---

## First-Time Server Setup (Already Done)

These steps are recorded for reference only — no need to repeat.

1. Clone the repo:
```bash
cd ~
git clone https://github.com/Michou828/telegram-amc-bot.git
```

2. Copy `.env` from old location:
```bash
sudo cp /home/womzhou/amc-bot/.env ~/telegram-amc-bot/.env
```

3. Update `/etc/systemd/system/amc-bot.service`:
```
[Unit]
Description=AMC Showtime Telegram Bot
After=network.target

[Service]
Type=simple
User=amc-bot
WorkingDirectory=/home/amc-bot/telegram-amc-bot
EnvironmentFile=/home/amc-bot/telegram-amc-bot/.env
ExecStart=/usr/bin/python3 -u /home/amc-bot/telegram-amc-bot/bot.py ${BOT_TOKEN} ${CHAT_ID}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

4. Reload and start:
```bash
sudo systemctl daemon-reload
sudo systemctl start amc-bot
sudo systemctl enable amc-bot
```
