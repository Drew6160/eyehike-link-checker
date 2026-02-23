#!/usr/bin/env python3
"""
Webcam Link Checker for eyehike.com/2016/webcams/
Crawls the page, checks every link, and produces an HTML report.

Usage:
    python webcam_link_checker.py

Schedule (cron, monthly on the 1st at 8am):
    0 8 1 * * /usr/bin/python3 /path/to/webcam_link_checker.py

Schedule (cron, quarterly – Jan/Apr/Jul/Oct 1st at 8am):
    0 8 1 1,4,7,10 * /usr/bin/python3 /path/to/webcam_link_checker.py
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse
import concurrent.futures
import json
import os
import sys

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
TARGET_URL   = "https://www.eyehike.com/2016/webcams/"
REPORT_DIR   = os.path.dirname(os.path.abspath(__file__))   # same folder as script
TIMEOUT      = 15        # seconds per request
MAX_WORKERS  = 10        # parallel threads for checking
SKIP_DOMAINS = {         # ignore internal nav / WordPress links
    "www.eyehike.com",
    "eyehike.com",
    "wordpress.org",
    "www.elegantthemes.com",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EyehikeLinkChecker/1.0; "
        "+https://www.eyehike.com/)"
    )
}


# ─────────────────────────────────────────────
# STEP 1: SCRAPE LINKS FROM PAGE
# ─────────────────────────────────────────────
def scrape_links(url: str) -> list[dict]:
    """Fetch the webcam page and extract every external link with its label."""
    print(f"[+] Fetching page: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Focus on the main content area (everything before the sidebar)
    # The webcam links are all inside <h3> tags
    links = []
    seen  = set()

    for tag in soup.find_all("a", href=True):
        href  = tag["href"].strip()
        label = tag.get_text(strip=True) or href

        # Skip anchors, mailto, javascript
        if not href.startswith("http"):
            continue

        domain = urlparse(href).netloc.lower()

        # Skip internal/nav domains
        if domain in SKIP_DOMAINS:
            continue

        # Deduplicate
        if href in seen:
            continue
        seen.add(href)

        # Try to find the nearest h3 ancestor for section context
        parent_h3 = tag.find_parent("h3")
        section   = parent_h3.get_text(strip=True)[:80] if parent_h3 else label[:80]

        links.append({"url": href, "label": label, "section": section})

    print(f"[+] Found {len(links)} unique external links to check.")
    return links


# ─────────────────────────────────────────────
# STEP 2: CHECK A SINGLE LINK
# ─────────────────────────────────────────────
def check_link(entry: dict) -> dict:
    url = entry["url"]
    result = entry.copy()
    result["checked_at"] = datetime.utcnow().isoformat() + "Z"

    try:
        # Try HEAD first (faster, less bandwidth)
        r = requests.head(
            url, headers=HEADERS, timeout=TIMEOUT,
            allow_redirects=True
        )

        # Some servers reject HEAD; fall back to GET
        if r.status_code in (405, 403, 501):
            r = requests.get(
                url, headers=HEADERS, timeout=TIMEOUT,
                allow_redirects=True, stream=True
            )
            r.close()

        final_url    = r.url
        status_code  = r.status_code
        redirected   = (final_url.rstrip("/") != url.rstrip("/"))

        if 200 <= status_code < 400:
            result["status"]      = "OK" if not redirected else "REDIRECT"
            result["status_code"] = status_code
            result["final_url"]   = final_url if redirected else ""
        else:
            result["status"]      = "BROKEN"
            result["status_code"] = status_code
            result["final_url"]   = ""

    except requests.exceptions.ConnectionError:
        result["status"]      = "BROKEN"
        result["status_code"] = "Connection Error"
        result["final_url"]   = ""
    except requests.exceptions.Timeout:
        result["status"]      = "TIMEOUT"
        result["status_code"] = "Timeout"
        result["final_url"]   = ""
    except Exception as e:
        result["status"]      = "ERROR"
        result["status_code"] = str(e)[:60]
        result["final_url"]   = ""

    icon = {"OK": "✅", "REDIRECT": "↪️", "BROKEN": "❌", "TIMEOUT": "⏱️", "ERROR": "⚠️"}
    print(f"  {icon.get(result['status'], '?')}  [{result['status_code']}]  {url[:80]}")
    return result


# ─────────────────────────────────────────────
# STEP 3: CHECK ALL LINKS IN PARALLEL
# ─────────────────────────────────────────────
def check_all_links(links: list[dict]) -> list[dict]:
    print(f"\n[+] Checking {len(links)} links with {MAX_WORKERS} threads …\n")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(check_link, lnk): lnk for lnk in links}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    # Sort: broken first, then redirects, then ok
    order = {"BROKEN": 0, "TIMEOUT": 1, "ERROR": 2, "REDIRECT": 3, "OK": 4}
    results.sort(key=lambda r: order.get(r["status"], 5))
    return results


# ─────────────────────────────────────────────
# STEP 4: GENERATE HTML REPORT
# ─────────────────────────────────────────────
def generate_html_report(results: list[dict], report_path: str):
    now   = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    total = len(results)
    ok    = sum(1 for r in results if r["status"] == "OK")
    redir = sum(1 for r in results if r["status"] == "REDIRECT")
    broke = sum(1 for r in results if r["status"] in ("BROKEN", "TIMEOUT", "ERROR"))

    status_colors = {
        "OK":       ("#d4edda", "#155724"),
        "REDIRECT": ("#fff3cd", "#856404"),
        "BROKEN":   ("#f8d7da", "#721c24"),
        "TIMEOUT":  ("#fde8cc", "#7d4e00"),
        "ERROR":    ("#e2e3e5", "#383d41"),
    }

    rows = ""
    for r in results:
        bg, fg = status_colors.get(r["status"], ("#fff", "#000"))
        final  = f'<br><small>→ <a href="{r["final_url"]}" target="_blank">{r["final_url"][:80]}</a></small>' if r.get("final_url") else ""
        rows += f"""
        <tr style="background:{bg}; color:{fg}">
          <td style="padding:8px 12px; font-weight:600">{r['status']}</td>
          <td style="padding:8px 12px">{r['status_code']}</td>
          <td style="padding:8px 12px">{r['section'][:70]}</td>
          <td style="padding:8px 12px; word-break:break-all">
            <a href="{r['url']}" target="_blank" style="color:inherit">{r['url']}</a>{final}
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Webcam Link Report – {now}</title>
<style>
  body  {{ font-family: system-ui, sans-serif; margin:2rem; color:#222; }}
  h1    {{ color:#1a4a7a; }}
  .summary {{ display:flex; gap:1.5rem; margin:1.5rem 0; flex-wrap:wrap; }}
  .card {{ padding:1rem 1.5rem; border-radius:8px; min-width:120px; text-align:center; }}
  .card .num  {{ font-size:2.2rem; font-weight:700; }}
  .card .lbl  {{ font-size:.85rem; margin-top:.25rem; opacity:.8; }}
  table {{ border-collapse:collapse; width:100%; margin-top:1rem; font-size:.9rem; }}
  th    {{ background:#1a4a7a; color:#fff; padding:10px 12px; text-align:left; }}
  tr:hover td {{ filter:brightness(.97); }}
  .filter-bar {{ margin:1rem 0; }}
  input {{ padding:.4rem .8rem; border:1px solid #ccc; border-radius:4px; width:300px; }}
</style>
</head>
<body>
<h1>🏔️ Eyehike Webcam Link Report</h1>
<p>Generated: <strong>{now}</strong> &nbsp;|&nbsp; Source: <a href="{TARGET_URL}">{TARGET_URL}</a></p>

<div class="summary">
  <div class="card" style="background:#d4edda">
    <div class="num" style="color:#155724">{ok}</div>
    <div class="lbl">Working</div>
  </div>
  <div class="card" style="background:#fff3cd">
    <div class="num" style="color:#856404">{redir}</div>
    <div class="lbl">Redirected</div>
  </div>
  <div class="card" style="background:#f8d7da">
    <div class="num" style="color:#721c24">{broke}</div>
    <div class="lbl">Broken / Timeout</div>
  </div>
  <div class="card" style="background:#e9ecef">
    <div class="num">{total}</div>
    <div class="lbl">Total Links</div>
  </div>
</div>

<div class="filter-bar">
  <input type="text" id="filterInput" onkeyup="filterTable()" placeholder="Filter by status, URL, or section…">
</div>

<table id="linkTable">
  <thead>
    <tr>
      <th>Status</th>
      <th>HTTP Code</th>
      <th>Section / Label</th>
      <th>URL</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>

<script>
function filterTable() {{
  var input = document.getElementById("filterInput").value.toLowerCase();
  var rows  = document.querySelectorAll("#linkTable tbody tr");
  rows.forEach(function(row) {{
    row.style.display = row.textContent.toLowerCase().includes(input) ? "" : "none";
  }});
}}
</script>
</body>
</html>"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[+] HTML report saved → {report_path}")


# ─────────────────────────────────────────────
# STEP 5: SAVE JSON (optional – for diffing over time)
# ─────────────────────────────────────────────
def save_json(results: list[dict], json_path: str):
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"[+] JSON data saved  → {json_path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    timestamp    = datetime.now().strftime("%Y-%m-%d")
    report_path  = os.path.join(REPORT_DIR, f"webcam_report_{timestamp}.html")
    json_path    = os.path.join(REPORT_DIR, f"webcam_report_{timestamp}.json")

    try:
        links   = scrape_links(TARGET_URL)
        results = check_all_links(links)
        generate_html_report(results, report_path)
        save_json(results, json_path)

        # Print a quick text summary
        ok    = sum(1 for r in results if r["status"] == "OK")
        redir = sum(1 for r in results if r["status"] == "REDIRECT")
        broke = sum(1 for r in results if r["status"] in ("BROKEN", "TIMEOUT", "ERROR"))
        print(f"\n{'─'*50}")
        print(f"  Total links checked : {len(results)}")
        print(f"  ✅  Working          : {ok}")
        print(f"  ↪️  Redirected       : {redir}")
        print(f"  ❌  Broken / Timeout : {broke}")
        print(f"{'─'*50}\n")

    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
