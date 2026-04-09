# Cloud-Based AMC Showtime Monitoring - Detailed Guide

## Option 1: Distill Web Monitor (Recommended - Easiest)

### What It Is
Browser extension that monitors web pages for changes. Works in Chrome, Firefox, Edge, Safari.

### Setup (5 minutes)
1. **Install Extension**
   - Chrome: https://chrome.google.com/webstore (search "Distill Web Monitor")
   - Firefox: https://addons.mozilla.org (search "Distill Web Monitor")

2. **Configure Monitor**
   - Navigate to your AMC movie page
   - Click the Distill icon in your browser toolbar
   - Click "Select parts of page to monitor"
   - Click on the showtime section (dates/times area)
   - Distill will highlight the selected area
   - Click "Save selections"

3. **Set Check Frequency**
   - Free tier: Every 6 hours
   - Premium ($5/mo): Every 5 minutes
   - Choose interval based on urgency

4. **Configure Alerts**
   - Email notifications (free)
   - SMS notifications (premium)
   - Desktop notifications
   - Webhook/Slack integration (premium)

### Pros
- Very reliable
- Visual selection (no coding)
- Monitors even when computer is off (cloud mode - premium)
- Change history/diff viewer
- Mobile app available

### Cons
- Free tier limited to 6-hour intervals
- Premium needed for frequent checks ($5/mo)

### Best For
- Non-technical users
- "Set it and forget it" monitoring
- Multiple movies/theaters

---

## Option 2: Visualping

### What It Is
Dedicated website change monitoring service with generous free tier.

### Setup
1. **Create Account**
   - Go to https://visualping.io
   - Sign up (free account includes 65 checks/month)

2. **Add Monitor**
   - Click "Add a monitor"
   - Paste AMC movie URL
   - Select monitoring mode:
     - **Visual Mode**: Takes screenshots, compares pixels
     - **Text Mode**: Monitors text changes (better for showtimes)

3. **Select Area**
   - Choose "Monitor specific area"
   - Click and drag to select showtime section
   - Or enter CSS selector (e.g., `.ShowtimeButton`)

4. **Set Schedule**
   - Free: 65 checks/month (check 2x/day for a month)
   - Paid: Unlimited checks, every 5 minutes ($10/mo)
   - Smart suggestion: Check every 12 hours normally, increase to hourly on release day

5. **Notifications**
   - Email (instant)
   - Browser push notifications
   - Telegram bot
   - Slack/Discord webhooks
   - SMS (paid plans)

### Pros
- Great free tier
- Screenshot history (visual proof of changes)
- No browser extension needed
- Works 24/7 (cloud-based)
- API access (paid)

### Cons
- Limited checks on free tier
- Need to budget checks for release week

### Best For
- Casual monitoring
- Visual confirmation needed
- Multiple sites to monitor

---

## Option 3: UptimeRobot

### What It Is
Originally for server monitoring, but excellent for webpage change detection.

### Setup
1. **Create Account**
   - Go to https://uptimerobot.com
   - Free account: 50 monitors, 5-minute intervals

2. **Create HTTP Monitor**
   - Click "Add New Monitor"
   - Monitor Type: "HTTP(s)"
   - Friendly Name: "AMC Showtimes - [Movie Name]"
   - URL: Your AMC movie page URL
   - Monitoring Interval: 5 minutes

3. **Add Keyword Monitoring**
   - Enable "Keyword Exists" or "Keyword Not Exists"
   - For new showtimes: Look for date strings
   - Example keyword: "TICKETS" or specific date like "March 23"
   - This alerts when keywords appear/disappear

4. **Set Alert Contacts**
   - Email (free, unlimited)
   - SMS (limited on free tier)
   - Slack, Discord, Telegram webhooks (free)
   - Voice call (paid)
   - Push notifications via mobile app

### Pros
- Completely free for basic use
- 5-minute check intervals
- Very reliable uptime
- Status page you can share
- Webhook integrations

### Cons
- Keyword monitoring is basic (not visual)
- Can't monitor specific page sections
- May miss subtle changes

### Best For
- Free, reliable monitoring
- Technical users comfortable with keywords
- Integration with other services (Slack, Discord)

---

## Option 4: IFTTT (If This Then That)

### What It Is
Automation platform that connects web services.

### Setup
1. **Create Account**
   - Go to https://ifttt.com
   - Free tier available

2. **Create Applet**
   - Click "Create"
   - Choose "RSS Feed" as trigger (AMC doesn't have RSS, see workaround)
   - OR use "Webhooks" with a separate monitoring service

3. **Workaround for AMC**
   Since AMC doesn't provide RSS:
   - Use IFTTT with "Feed43" (creates RSS from any page)
   - Go to https://feed43.com
   - Create feed from AMC movie page
   - Extract showtime data
   - Use that RSS feed in IFTTT

4. **Set Actions**
   - Send email
   - Send SMS
   - Post to Discord/Slack
   - Add to Google Calendar
   - Create iOS notification

### Pros
- Powerful automation
- Free tier available
- Connects to many services
- Mobile app

### Cons
- Complex setup for AMC
- Free tier limited (2 applets)
- Requires Feed43 or similar workaround

### Best For
- Users already in IFTTT ecosystem
- Want automated actions (add to calendar, etc.)

---

## Option 5: ChangeTower

### What It Is
Professional website monitoring with advanced features.

### Setup
1. **Create Account**
   - Go to https://changetower.com
   - 14-day free trial, then $20/mo

2. **Add Monitor**
   - Enter AMC URL
   - Choose monitoring type: "Visual" or "Source code"
   - Set check frequency (every 5 minutes possible)

3. **Configure Detection**
   - Visual threshold: How much change triggers alert
   - Ignore areas: Ads, banners, etc.
   - Focus areas: Showtime section only

4. **Alerts**
   - Email
   - Slack
   - Webhook
   - API access

### Pros
- Very accurate change detection
- Can ignore irrelevant changes (ads)
- Screenshot history
- Change percentage metrics

### Cons
- No free tier (trial only)
- More expensive
- Overkill for simple monitoring

### Best For
- Professional use
- Monitoring many movies/theaters
- Need detailed change reports

---

## Option 6: Wachete

### What It Is
Simplified monitoring focused on specific page elements.

### Setup
1. **Install Browser Extension**
   - Chrome/Firefox: Search "Wachete"

2. **Create Watch**
   - Visit AMC page
   - Click Wachete icon
   - Select showtime area
   - Name it

3. **Set Schedule**
   - Free: Check every 24 hours (3 pages)
   - Paid: Every 5 minutes ($7/mo, unlimited pages)

4. **Notifications**
   - Email
   - Browser notifications
   - Mobile app notifications

### Pros
- Simple, focused interface
- Visual selection
- Affordable premium ($7/mo)

### Cons
- Free tier very limited (daily checks)
- Fewer integrations than competitors

### Best For
- Users who want simplicity
- Don't need frequent checks

---

## Option 7: Page Monitor (Chrome Extension)

### What It Is
Free, open-source Chrome extension for change detection.

### Setup
1. **Install**
   - Chrome Web Store: "Page Monitor"
   - Completely free, no account needed

2. **Configure**
   - Visit AMC page
   - Right-click Page Monitor icon
   - Choose "Monitor this page"
   - Advanced: Use CSS selector for showtime section

3. **Set Interval**
   - Minimum: Every 1 minute
   - Recommended: Every 5 minutes

4. **Notifications**
   - Browser notifications
   - Sound alerts
   - Badge icon changes

### Pros
- Completely free
- No account required
- Open source
- Very fast checks (1 minute possible)

### Cons
- Only works when browser is open
- Chrome/Edge only
- No mobile notifications
- No cloud backup

### Best For
- Free solution
- Computer is always on
- Chrome users

---

## Recommended Setup Strategy

### For Maximum Reliability (Free)
**Combine multiple services:**

1. **Primary: Visualping (Free)**
   - 65 checks/month
   - Use 2 checks/day normally
   - On release Tuesday: check every 2 hours (12 checks)

2. **Backup: UptimeRobot (Free)**
   - 5-minute intervals
   - Keyword monitoring for safety net

3. **Browser: Page Monitor (Free)**
   - When actively browsing
   - 5-minute intervals
   - Immediate alerts

**Total cost: $0**
**Coverage: 24/7 with redundancy**

### For Serious Monitoring (Paid)
**Best single solution:**

- **Distill Premium ($5/mo)**
  - 5-minute intervals
  - Cloud monitoring (works when computer off)
  - SMS alerts
  - Most reliable

**OR**

- **Visualping Unlimited ($10/mo)**
  - Same benefits
  - Better screenshot history
  - More integrations

---

## Step-by-Step: UptimeRobot (Recommended Free Option)

### Detailed Walkthrough

1. **Sign Up**
   ```
   Go to: https://uptimerobot.com/signUp
   Enter email and create password
   Verify email
   ```

2. **Add Monitor**
   ```
   Click "Add New Monitor"
   
   Fields:
   - Monitor Type: HTTP(s)
   - Friendly Name: AMC - [Your Movie] - [Theater]
   - URL (or IP): [Full AMC movie page URL]
   - Monitoring Interval: 5 minutes
   ```

3. **Enable Keyword Monitoring**
   ```
   Scroll down to "Advanced Settings"
   
   Check: "Enable Keyword Monitoring"
   
   Choose: "Keyword Exists"
   Keywords to check: Enter a date you expect
   Example: "March 25" or "3/25" or "TUE"
   
   OR
   
   Choose: "Keyword Not Exists"  
   Keyword: "No showtimes available"
   ```

4. **Set Up Alert Contacts**
   ```
   Click "Alert Contacts" in left menu
   Click "Add Alert Contact"
   
   For Email:
   - Type: E-mail
   - Email: your@email.com
   - Friendly Name: My Email
   
   For SMS (after email confirmed):
   - Type: SMS
   - Phone: +1-XXX-XXX-XXXX
   - Note: Free tier has SMS limits
   
   For Slack:
   - Type: Slack
   - Webhook URL: [Get from Slack]
   ```

5. **Configure Notification Threshold**
   ```
   In monitor settings:
   
   "Alert When Down For": 0 minutes (instant)
   
   This means: Alert immediately when keyword appears/disappears
   ```

6. **Test It**
   ```
   Save monitor
   Wait 5 minutes
   Check email for first "UP" notification
   
   To test alerts:
   - Temporarily change keyword to something that exists now
   - You should get alert
   - Change it back
   ```

### Example Keyword Strategies

**Strategy 1: Date Detection**
```
Keyword: "March 25"
Alert Type: Keyword Exists
Result: Alerts when that specific date appears
```

**Strategy 2: Availability Detection**
```
Keyword: "sold out" OR "not available"
Alert Type: Keyword Not Exists
Result: Alerts when those words disappear (tickets released)
```

**Strategy 3: Generic Detection**
```
Keyword: "BUY TICKETS" or "SELECT SHOWTIME"
Alert Type: Keyword Exists
Result: Alerts when booking becomes available
```

---

## Pro Tips

### Timing Your Checks
- **AMC releases showtimes:** Usually Tuesdays 9-11 AM ET
- **Optimal schedule:**
  - Monday: Every 6 hours
  - Tuesday 8 AM - 2 PM ET: Every 5 minutes
  - After release: Stop or reduce to daily

### Avoiding False Positives
- Ads and banners change frequently
- Use specific CSS selectors or keywords
- Ignore sections with dynamic content
- Test your monitor before release day

### Multiple Movies/Theaters
- Set up separate monitors for each
- Use clear naming: "AMC - Movie Name - Theater Location"
- Group notifications by priority

### Mobile Access
- Most services have mobile apps
- Set up push notifications
- Have backup email alerts

---

## Quick Comparison Table

| Service | Free Tier | Check Frequency | Best Feature | Cost |
|---------|-----------|----------------|--------------|------|
| Distill | 6 hrs | 5 min (paid) | Visual selection | $5/mo |
| Visualping | 65/month | 5 min (paid) | Screenshots | $10/mo |
| UptimeRobot | 5 min | 5 min | Actually free | Free |
| IFTTT | Limited | Varies | Automation | $3/mo |
| Page Monitor | 1 min | 1 min | Free, fast | Free |
| ChangeTower | Trial | 5 min | Accuracy | $20/mo |
| Wachete | Daily | 5 min (paid) | Simple | $7/mo |

---

## Troubleshooting

### Monitor Not Detecting Changes
- AMC may use JavaScript to load times
- Try "Visual" mode instead of "Text" mode
- Increase sensitivity threshold
- Check if you're monitoring the right section

### Too Many False Alerts
- Tighten keyword matching
- Exclude dynamic sections (ads, promos)
- Increase "down for" threshold to 2-3 checks

### Missed the Release
- Check your spam folder
- Verify alert contact is enabled
- Test with manual trigger
- Use multiple services as backup

---

## My Recommendation

**Start with this free setup:**

1. **UptimeRobot** (primary, free, 5-min checks)
2. **Page Monitor extension** (when browsing)
3. **Visualping** (backup, save checks for release week)

**If you want to pay for reliability:**

**Distill Premium ($5/mo)** - Single best solution, works perfectly, worth it.

---

Need help setting up any of these? Let me know which service you'd like to try and I can walk you through it step by step!
