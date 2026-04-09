# AMC Showtime Monitor - Setup Guide

## Method 1: Python Script (Recommended)

### Prerequisites
```bash
pip install requests beautifulsoup4
```

### Usage
```bash
# Monitor a specific movie page
python amc_monitor.py "https://www.amctheatres.com/movies/..."

# Monitor by ZIP code
python amc_monitor.py 10001

# Custom check interval (in seconds)
python amc_monitor.py "https://www.amctheatres.com/movies/..." 180
```

### Features
- Runs in the background
- Desktop notifications when showtimes change
- Logs all checks with timestamps
- Saves state between runs

---

## Method 2: Browser Bookmarklet (No Installation)

### Setup
1. Open `amc_monitor_bookmarklet.js` in a text editor
2. Copy ALL the code
3. Create a new bookmark in your browser
4. Paste the code as the URL (prefix with `javascript:` if needed)
5. Name it "AMC Monitor"

### Usage
1. Navigate to an AMC movie page
2. Click the "AMC Monitor" bookmark
3. A panel appears showing monitoring status
4. Leave the tab open - it will check every minute
5. You'll get an alert when new showtimes appear

---

## Method 3: Browser Extension (Advanced)

Use a browser automation extension like:
- **Distill Web Monitor** (Chrome/Firefox)
- **Visualping** (Chrome)
- **Check Mark** (Chrome)

Steps:
1. Install extension
2. Navigate to AMC movie page
3. Select the showtime area to monitor
4. Set check interval (e.g., every 5 minutes)
5. Configure notifications

---

## Method 4: Cloud Automation (No Local Setup)

### Using IFTTT or Zapier
1. Use their "Website Change Detection" feature
2. Enter the AMC movie URL
3. Set check frequency
4. Configure notification (email, SMS, push)

### Using UptimeRobot (Free)
1. Create free account at uptimerobot.com
2. Add new "HTTP(s)" monitor
3. Enter AMC movie URL
4. Set interval to 5 minutes
5. Enable "Keyword Monitoring" for specific showtimes
6. Configure alerts

---

## Tips

### Finding the Right URL
- Go to amctheatres.com
- Search for your movie
- Click "Get Tickets"
- Copy the full URL from your browser

### Optimal Check Intervals
- During release week: Every 1-5 minutes
- Normal times: Every 15-30 minutes
- Off-peak: Every hour

### When Do AMC Release Times?
- Typically **Tuesdays around 9-11 AM ET**
- Sometimes Wednesdays for limited releases
- Special events: announced separately

### Notification Options
- **Desktop**: Built into Python script
- **Email**: Use cloud automation services
- **SMS**: IFTTT, Zapier, or Twilio integration
- **Push**: Browser notifications with bookmarklet

---

## Troubleshooting

### Python Script Issues
```bash
# Test if script can reach AMC
curl -I https://www.amctheatres.com

# Check Python version (needs 3.6+)
python3 --version

# Install dependencies in virtual environment
python3 -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install requests beautifulsoup4
```

### Bookmarklet Not Working
- Make sure you're on the actual movie page (not search results)
- Check browser console (F12) for errors
- Try refreshing the page first

### Too Many Checks
- AMC may rate-limit frequent requests
- Keep intervals above 60 seconds for Python script
- Use cloud services for very frequent checks
