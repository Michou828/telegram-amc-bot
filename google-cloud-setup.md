# Google Cloud Deployment Guide

Deploy the AMC showtime bot to a Google Cloud free-tier VM so it runs persistently without your Mac.

---

## Free Tier Summary

Google Cloud's **Always Free** e2-micro includes:
- 1 e2-micro VM (1 shared vCPU, 1 GB RAM) — forever, no expiry
- 30 GB standard persistent disk
- 1 GB outbound network per month (to US/Canada destinations)
- Only free in these 3 regions: `us-central1`, `us-west1`, `us-east1`

No charges as long as you stay within those limits. This bot uses well under all of them.

---

## 1. Create a Google Cloud Account

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Sign in with your Google account
3. Click **Try for free** — you get a $300 free credit for 90 days on top of the always-free tier
4. Enter billing info (credit card required for identity verification — the e2-micro itself won't be charged after the trial)
5. Complete account setup

---

## 2. Create a Project

1. In the top bar, click the project dropdown (says "My First Project" or similar)
2. Click **New Project**
3. Name it `amc-bot` (or anything)
4. Click **Create**
5. Make sure the new project is selected in the dropdown

---

## 3. Create the VM

1. In the left sidebar → **Compute Engine** → **VM instances**
2. If prompted, click **Enable** to enable the Compute Engine API (takes ~1 min)
3. Click **Create Instance**

### Configure the instance

**Name**: `amc-bot`

**Region**: Must be one of these for free tier:
- `us-central1` (Iowa) — recommended
- `us-west1` (Oregon)
- `us-east1` (South Carolina)

**Zone**: Any zone within that region (e.g. `us-central1-a`)

**Machine configuration**:
- Series: **E2**
- Machine type: **e2-micro** (2 vCPU, 1 GB memory)
- You'll see a note confirming it's free-tier eligible

**Boot disk**: Click **Change**
- Operating system: **Ubuntu**
- Version: **Ubuntu 22.04 LTS**
- Boot disk type: **Standard persistent disk**
- Size: **30 GB**
- Click **Select**

**Firewall**: Check both boxes:
- ✅ Allow HTTP traffic
- ✅ Allow HTTPS traffic

(Not strictly needed for the bot, but useful to have open.)

4. Click **Create** at the bottom. Instance will be ready in ~30 seconds.

---

## 4. Add Your SSH Key

1. On the VM instances page, click your instance name (`amc-bot`)
2. Click **Edit** (pencil icon at the top)
3. Scroll down to **SSH Keys** → click **Add item**
4. On your Mac, run:
   ```bash
   cat ~/.ssh/oracle_cloud_key.pub
   ```
5. Paste the full output into the SSH key field
6. Click **Save** at the bottom

---

## 5. Connect via SSH

On the VM instances page, find the **External IP** of your instance (e.g. `34.123.45.67`).

From your Mac:
```bash
ssh -i ~/.ssh/oracle_cloud_key <your-google-username>@<external-ip>
```

Your Google username is the part of your Google email before the `@`. For example, if your email is `john.smith@gmail.com`, it's `john.smith`.

If you're unsure of your username, use the **SSH** button in the Google Cloud console to open a browser-based terminal — it will show your username in the prompt.

You're on the server when you see a prompt like: `john.smith@amc-bot:~$`

---

## 6. Server Setup

Run these commands on the server:

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install Python and pip
sudo apt install python3 python3-pip -y

# Install bot dependencies
pip3 install requests beautifulsoup4 cloudscraper

# Create bot directory
mkdir ~/amc-bot
```

Verify Python works:
```bash
python3 --version   # should print Python 3.10+
```

---

## 7. Upload Bot Files

From your **Mac** (new terminal tab):

```bash
# Replace <IP> with your instance's External IP
# Replace <username> with your Google username
scp -i ~/.ssh/oracle_cloud_key \
  /Users/michaelzhou/Documents/Playgrounds/telegram-bot/AMC_new_tickets/bot.py \
  /Users/michaelzhou/Documents/Playgrounds/telegram-bot/AMC_new_tickets/theater_matcher.py \
  /Users/michaelzhou/Documents/Playgrounds/telegram-bot/AMC_new_tickets/theaters.json \
  /Users/michaelzhou/Documents/Playgrounds/telegram-bot/AMC_new_tickets/.env \
  <username>@<IP>:~/amc-bot/
```

Back on the **server**, verify and do a quick test:
```bash
ls ~/amc-bot/
# Should show: bot.py  theater_matcher.py  theaters.json  .env

cd ~/amc-bot
source .env
python3 bot.py "$BOT_TOKEN" "$CHAT_ID"
# Ctrl+C to stop after a few seconds
```

If no errors, proceed to the next step.

---

## 8. Run Persistently with systemd

```bash
sudo nano /etc/systemd/system/amc-bot.service
```

Paste this — replace `<username>` with your actual Google username (e.g. `john.smith`):

```ini
[Unit]
Description=AMC Showtime Telegram Bot
After=network.target

[Service]
Type=simple
User=<username>
WorkingDirectory=/home/<username>/amc-bot
ExecStart=/bin/bash -c 'source /home/<username>/amc-bot/.env && /usr/bin/python3 /home/<username>/amc-bot/bot.py "$BOT_TOKEN" "$CHAT_ID"'
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Save and exit: `Ctrl+O`, `Enter`, `Ctrl+X`

```bash
sudo systemctl daemon-reload
sudo systemctl enable amc-bot    # auto-start on reboot
sudo systemctl start amc-bot     # start now

# Verify it's running
sudo systemctl status amc-bot

# Watch live logs
sudo journalctl -u amc-bot -f
```

---

## 9. Managing the Bot

| Task | Command |
|------|---------|
| Check status | `sudo systemctl status amc-bot` |
| Live logs | `sudo journalctl -u amc-bot -f` |
| Restart | `sudo systemctl restart amc-bot` |
| Stop | `sudo systemctl stop amc-bot` |

**Deploying a code update from your Mac:**

```bash
# Upload new file
scp -i ~/.ssh/oracle_cloud_key bot.py <username>@<IP>:~/amc-bot/

# SSH in and restart
ssh -i ~/.ssh/oracle_cloud_key <username>@<IP>
sudo systemctl restart amc-bot
```

---

## 10. Free Tier Limitations

### What this bot actually uses

| Resource | Free allowance | Bot's actual usage | Risk |
|----------|---------------|-------------------|------|
| CPU | 1 shared vCPU | ~0.1% (sleeps between checks) | None |
| RAM | 1 GB | ~50–80 MB | None |
| Disk | 30 GB | ~10 MB | None |
| Network egress | 1 GB/month | ~5–20 MB/month | None |

The bot checks showtimes every 5 minutes. Each check is a small HTML page fetch. You will not come close to any free tier limit with normal usage.

### When the free tier won't be enough

| Scenario | Why it's a problem |
|----------|--------------------|
| Tracking 50+ movies simultaneously | Python becomes CPU-bound; shared vCPU may throttle |
| Check interval under 1 minute | Much more CPU and network usage |
| Adding other services to the same VM (web server, database, other bots) | 1 GB RAM fills up fast |
| Log accumulation over months | Disk fills up; fix with `sudo journalctl --vacuum-size=100M` |

For normal use — a handful of movies, 5-minute check interval — the free tier is indefinitely sufficient.

### Other notes

- **Active trackers reset on restart** — re-run `/track` in Telegram after any restart; tracker state is in-memory only
- **Cache persists across restarts** — `~/.amc_monitors/` (recent movies, `🆕` timestamps) is on disk and survives restarts
- **`.env` contains your bot token** — don't commit it to git
- **Region lock** — VM must stay in `us-central1`, `us-west1`, or `us-east1` to remain free; moving to another region will incur charges
