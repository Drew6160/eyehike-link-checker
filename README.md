# 🏔️ Eyehike Webcam Link Checker

Automatically checks links on [eyehike.com/2016/](https://www.eyehike.com/2016/) and [unscripted6160.com] (https://www.unscripted6160.com) then generates a report showing which links are working, broken, or redirected.

Runs automatically on GitHub — no server or local machine needed.

---

## 📋 What it checks

Every external link on the sites, categorized as:

| Status | Meaning |
|--------|---------|
| ✅ OK | Link is working |
| ↪️ Redirect | Link works but points to a new URL — worth updating |
| ❌ Broken | HTTP error (404, 403, 500, etc.) — link is dead |
| ⏱️ Timeout | Server didn't respond — may be temporarily down |
| ⚠️ Error | DNS failure or SSL error |

---

## 📅 Schedule

Runs **quarterly** (January, April, July, and October 1st at 8 AM UTC).

To change the schedule, edit `.github/workflows/link_check.yml` and update the cron line:
- Monthly: `"0 8 1 * *"`
- Quarterly: `"0 8 1 1,4,7,10 *"`

You can also trigger a run **manually** at any time from the Actions tab.

---

## 📥 Getting your report

1. Go to the **Actions** tab on this GitHub repo
2. Click the most recent **sitewide_link_checker** run
3. Scroll down to **Artifacts**
4. Download **sitewide_link_checker report** and open the `.html` file in your browser

The report has a live filter box — type "BROKEN" to instantly see only the dead links.

Reports are kept for **90 days**.

---

## 🛠️ Running locally

```bash
pip install requests beautifulsoup4
python webcam_link_checker.py
```

The HTML report opens in any browser. No account or API key needed.
