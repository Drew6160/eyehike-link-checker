#!/usr/bin/env python3
"""
Sitewide Link Checker
Checks all external links across eyehike.com and unscripted6160.com
using their WordPress XML sitemaps. Produces a single HTML report.

Usage:
    python sitewide_link_checker.py
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse
import concurrent.futures
import json
import os
import sys
import xml.etree.ElementTree as ET

# ─────────────────────────────────────────────────────────────
# CONFIGURATION — edit here to add/remove sites
# ─────────────────────────────────────────────────────────────
SITES = [
    {
        "name":         "Eyehike",
        "base_url":     "https://www.eyehike.com",
        "sitemap_url": "https://www.eyehike.com/2016/sitemap_index.xml",
        # Only crawl posts & pages — skip category/tag/author/project sitemaps
        "sitemap_filter": ["post-sitemap.xml", "page-sitemap.xml"],
        "skip_domains": {"www.eyehike.com", "eyehike.com"},
    },
    {
        "name":         "Unscripted6160",
        "base_url":     "https://www.unscripted6160.com",
        "sitemap_url":  "https://www.unscripted6160.com/wp-sitemap.xml",
        "sitemap_filter": ["wp-sitemap-posts-post-1.xml", "wp-sitemap-posts-page-1.xml"],
        "skip_domains": {"www.unscripted6160.com", "unscripted6160.com"},
    },
]

REPORT_DIR  = os.path.dirname(os.path.abspath(__file__))
TIMEOUT     = 15
MAX_WORKERS = 12   # parallel threads for link checking
PAGE_WORKERS = 5  # parallel threads for page crawling

# Domains to always skip (WordPress boilerplate, theme authors, etc.)
GLOBAL_SKIP_DOMAINS = {
    "wordpress.org",
    "www.elegantthemes.com",
    "elegantthemes.com",
    "schema.org",
    "www.w3.org",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SitewideL inkChecker/1.0; "
        "contact: your@email.com)"
    )
}


# ─────────────────────────────────────────────────────────────
# STEP 1: PARSE SITEMAP → list of page URLs
# ─────────────────────────────────────────────────────────────
def parse_sitemap_index(sitemap_url: str, filter_list: list[str]) -> list[str]:
    """Fetch a sitemap index and return URLs from matching sub-sitemaps."""
    print(f"  [sitemap] Fetching index: {sitemap_url}")
    try:
        r = requests.get(sitemap_url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        print(f"  [ERROR] Could not fetch sitemap: {e}")
        return []

    root = ET.fromstring(r.text)
    ns   = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    # Collect sub-sitemap URLs that match our filter
    sub_sitemaps = []
    for sitemap in root.findall("sm:sitemap", ns):
        loc = sitemap.findtext("sm:loc", namespaces=ns) or ""
        if any(f in loc for f in filter_list):
            sub_sitemaps.append(loc)

    print(f"  [sitemap] Found {len(sub_sitemaps)} matching sub-sitemaps")

    # Fetch each sub-sitemap and collect page URLs
    page_urls = []
    for sub_url in sub_sitemaps:
        print(f"  [sitemap] Fetching: {sub_url}")
        try:
            r2 = requests.get(sub_url, headers=HEADERS, timeout=TIMEOUT)
            r2.raise_for_status()
            root2 = ET.fromstring(r2.text)
            for url_el in root2.findall("sm:url", ns):
                loc = url_el.findtext("sm:loc", namespaces=ns)
                if loc:
                    page_urls.append(loc)
        except Exception as e:
            print(f"  [ERROR] Could not fetch sub-sitemap {sub_url}: {e}")

    print(f"  [sitemap] Total pages to crawl: {len(page_urls)}")
    return page_urls


# ─────────────────────────────────────────────────────────────
# STEP 2: CRAWL A SINGLE PAGE → extract external links
# ─────────────────────────────────────────────────────────────
def extract_links_from_page(page_url: str, skip_domains: set) -> list[dict]:
    """Fetch a page and return all external links found on it."""
    all_skip = skip_domains | GLOBAL_SKIP_DOMAINS
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        print(f"  [SKIP] Could not fetch page {page_url[:70]}: {e}")
        return []

    soup  = BeautifulSoup(r.text, "html.parser")
    links = []
    seen  = set()

    # Get the page title for the report
    title_tag = soup.find("title")
    page_title = title_tag.get_text(strip=True)[:80] if title_tag else page_url

    for tag in soup.find_all("a", href=True):
        href  = tag["href"].strip()
        label = tag.get_text(strip=True)[:80] or href[:80]

        if not href.startswith("http"):
            continue

        domain = urlparse(href).netloc.lower()

        if domain in all_skip:
            continue

        if href in seen:
            continue
        seen.add(href)

        links.append({
            "url":        href,
            "label":      label,
            "page_url":   page_url,
            "page_title": page_title,
        })

    return links


# ─────────────────────────────────────────────────────────────
# STEP 3: CRAWL ALL PAGES FOR A SITE
# ─────────────────────────────────────────────────────────────
def crawl_site(site: dict) -> list[dict]:
    """Crawl all pages in a site's sitemap and collect external links."""
    print(f"\n{'═'*60}")
    print(f"  📍 Crawling: {site['name']}")
    print(f"{'═'*60}")

    page_urls = parse_sitemap_index(site["sitemap_url"], site["sitemap_filter"])

    if not page_urls:
        print(f"  [WARN] No pages found for {site['name']}")
        return []

    all_links = []
    seen_urls = set()

    print(f"\n  [crawl] Crawling {len(page_urls)} pages for external links…")
    with concurrent.futures.ThreadPoolExecutor(max_workers=PAGE_WORKERS) as pool:
        futures = {
            pool.submit(extract_links_from_page, url, site["skip_domains"]): url
            for url in page_urls
        }
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            page_links = future.result()
            for link in page_links:
                if link["url"] not in seen_urls:
                    seen_urls.add(link["url"])
                    link["site"] = site["name"]
                    all_links.append(link)
            if i % 10 == 0 or i == len(page_urls):
                print(f"  [crawl] {i}/{len(page_urls)} pages done, {len(all_links)} unique links so far")

    print(f"\n  [crawl] ✅ {site['name']}: {len(all_links)} unique external links to check")
    return all_links


# ─────────────────────────────────────────────────────────────
# STEP 4: CHECK A SINGLE LINK
# ─────────────────────────────────────────────────────────────
def check_link(entry: dict) -> dict:
    url    = entry["url"]
    result = entry.copy()
    result["checked_at"] = datetime.utcnow().isoformat() + "Z"

    try:
        r = requests.head(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)

        # Some servers reject HEAD — fall back to GET
        if r.status_code in (405, 403, 501):
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                             allow_redirects=True, stream=True)
            r.close()

        final_url   = r.url
        status_code = r.status_code
        redirected  = (final_url.rstrip("/") != url.rstrip("/"))

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
    print(f"  {icon.get(result['status'], '?')} [{result['status_code']}] {url[:75]}")
    return result


# ─────────────────────────────────────────────────────────────
# STEP 5: CHECK ALL LINKS IN PARALLEL
# ─────────────────────────────────────────────────────────────
def check_all_links(links: list[dict]) -> list[dict]:
    print(f"\n{'═'*60}")
    print(f"  🔍 Checking {len(links)} unique external links…")
    print(f"{'═'*60}\n")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(check_link, lnk): lnk for lnk in links}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    order = {"BROKEN": 0, "TIMEOUT": 1, "ERROR": 2, "REDIRECT": 3, "OK": 4}
    results.sort(key=lambda r: (r.get("site", ""), order.get(r["status"], 5)))
    return results


# ─────────────────────────────────────────────────────────────
# STEP 6: GENERATE HTML REPORT
# ─────────────────────────────────────────────────────────────
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

    # Build per-site summary cards
    site_names = list(dict.fromkeys(r.get("site", "Unknown") for r in results))
    site_summaries = ""
    for sname in site_names:
        site_results = [r for r in results if r.get("site") == sname]
        s_ok    = sum(1 for r in site_results if r["status"] == "OK")
        s_redir = sum(1 for r in site_results if r["status"] == "REDIRECT")
        s_broke = sum(1 for r in site_results if r["status"] in ("BROKEN","TIMEOUT","ERROR"))
        site_summaries += f"""
        <div class="site-card">
          <h3>🌐 {sname}</h3>
          <div class="mini-stats">
            <span class="stat ok">✅ {s_ok} Working</span>
            <span class="stat redir">↪️ {s_redir} Redirected</span>
            <span class="stat broke">❌ {s_broke} Broken</span>
            <span class="stat total">📊 {len(site_results)} Total</span>
          </div>
        </div>"""

    # Build table rows
    rows = ""
    current_site = None
    for r in results:
        site = r.get("site", "")
        if site != current_site:
            current_site = site
            rows += f"""
            <tr class="site-header">
              <td colspan="5" style="background:#1a4a7a; color:#fff; padding:10px 16px;
                  font-size:1rem; font-weight:700; letter-spacing:.5px">
                🌐 {site}
              </td>
            </tr>"""

        bg, fg  = status_colors.get(r["status"], ("#fff", "#000"))
        final   = f'<br><small>→ <a href="{r["final_url"]}" target="_blank" style="color:inherit">{r["final_url"][:70]}</a></small>' \
                  if r.get("final_url") else ""
        pg_link = f'<a href="{r["page_url"]}" target="_blank" style="color:inherit; font-size:.8rem">{r.get("page_title","")[:55]}</a>'

        rows += f"""
        <tr style="background:{bg}; color:{fg}">
          <td style="padding:7px 12px; font-weight:700; white-space:nowrap">{r['status']}</td>
          <td style="padding:7px 12px; white-space:nowrap">{r['status_code']}</td>
          <td style="padding:7px 12px">{pg_link}</td>
          <td style="padding:7px 12px; font-size:.85rem">{r.get('label','')[:50]}</td>
          <td style="padding:7px 12px; word-break:break-all; font-size:.85rem">
            <a href="{r['url']}" target="_blank" style="color:inherit">{r['url']}</a>{final}
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sitewide Link Report – {now}</title>
<style>
  * {{ box-sizing: border-box; }}
  body  {{ font-family: system-ui, -apple-system, sans-serif; margin:0; padding:2rem; color:#222; background:#f5f7fa; }}
  .wrap {{ max-width:1400px; margin:0 auto; }}
  h1    {{ color:#1a4a7a; margin-bottom:.25rem; }}
  .sub  {{ color:#666; margin-bottom:1.5rem; font-size:.95rem; }}
  .top-summary {{ display:flex; gap:1rem; margin:1.5rem 0; flex-wrap:wrap; }}
  .big-card {{ background:#fff; border-radius:10px; padding:1.2rem 1.8rem;
               box-shadow:0 1px 4px rgba(0,0,0,.1); text-align:center; min-width:130px; }}
  .big-card .num {{ font-size:2.4rem; font-weight:800; }}
  .big-card .lbl {{ font-size:.8rem; color:#666; margin-top:.2rem; text-transform:uppercase; letter-spacing:.5px; }}
  .sites {{ display:flex; gap:1rem; margin:1.5rem 0; flex-wrap:wrap; }}
  .site-card {{ background:#fff; border-radius:10px; padding:1.2rem 1.5rem;
                box-shadow:0 1px 4px rgba(0,0,0,.1); flex:1; min-width:280px; }}
  .site-card h3 {{ margin:0 0 .75rem; color:#1a4a7a; }}
  .mini-stats {{ display:flex; flex-wrap:wrap; gap:.5rem; }}
  .stat {{ padding:.3rem .7rem; border-radius:20px; font-size:.85rem; font-weight:600; }}
  .stat.ok    {{ background:#d4edda; color:#155724; }}
  .stat.redir {{ background:#fff3cd; color:#856404; }}
  .stat.broke {{ background:#f8d7da; color:#721c24; }}
  .stat.total {{ background:#e9ecef; color:#333; }}
  .filter-bar {{ background:#fff; padding:1rem; border-radius:8px;
                 box-shadow:0 1px 4px rgba(0,0,0,.08); margin-bottom:1rem;
                 display:flex; gap:.75rem; flex-wrap:wrap; align-items:center; }}
  .filter-bar label {{ font-size:.85rem; font-weight:600; color:#555; }}
  .filter-bar input, .filter-bar select {{
    padding:.4rem .8rem; border:1px solid #ccc; border-radius:6px; font-size:.9rem; }}
  .filter-bar input {{ width:280px; }}
  table  {{ border-collapse:collapse; width:100%; background:#fff;
            border-radius:10px; overflow:hidden;
            box-shadow:0 1px 4px rgba(0,0,0,.08); font-size:.875rem; }}
  th     {{ background:#2c5f9e; color:#fff; padding:10px 12px; text-align:left;
            font-size:.8rem; text-transform:uppercase; letter-spacing:.5px; }}
  tr:not(.site-header):hover td {{ filter:brightness(.96); }}
  .ts    {{ color:#999; font-size:.75rem; margin-top:2rem; }}
</style>
</head>
<body>
<div class="wrap">

<h1>🔗 Sitewide Link Report</h1>
<p class="sub">Generated: <strong>{now}</strong></p>

<div class="top-summary">
  <div class="big-card">
    <div class="num" style="color:#155724">{ok}</div>
    <div class="lbl">Working</div>
  </div>
  <div class="big-card">
    <div class="num" style="color:#856404">{redir}</div>
    <div class="lbl">Redirected</div>
  </div>
  <div class="big-card">
    <div class="num" style="color:#721c24">{broke}</div>
    <div class="lbl">Broken</div>
  </div>
  <div class="big-card">
    <div class="num">{total}</div>
    <div class="lbl">Total Links</div>
  </div>
</div>

<div class="sites">
  {site_summaries}
</div>

<div class="filter-bar">
  <label>Filter:</label>
  <input type="text" id="filterInput" onkeyup="applyFilters()" placeholder="Search URL, page title, label…">
  <label>Status:</label>
  <select id="statusFilter" onchange="applyFilters()">
    <option value="">All</option>
    <option value="BROKEN">❌ Broken</option>
    <option value="TIMEOUT">⏱️ Timeout</option>
    <option value="ERROR">⚠️ Error</option>
    <option value="REDIRECT">↪️ Redirect</option>
    <option value="OK">✅ OK</option>
  </select>
  <label>Site:</label>
  <select id="siteFilter" onchange="applyFilters()">
    <option value="">All Sites</option>
    {''.join(f'<option value="{s}">{s}</option>' for s in site_names)}
  </select>
</div>

<table id="linkTable">
  <thead>
    <tr>
      <th>Status</th>
      <th>HTTP</th>
      <th>Found On Page</th>
      <th>Link Label</th>
      <th>URL</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>

<p class="ts">Report generated by sitewide_link_checker.py</p>

</div>
<script>
function applyFilters() {{
  var text   = document.getElementById("filterInput").value.toLowerCase();
  var status = document.getElementById("statusFilter").value.toLowerCase();
  var site   = document.getElementById("siteFilter").value.toLowerCase();
  var rows   = document.querySelectorAll("#linkTable tbody tr:not(.site-header)");
  rows.forEach(function(row) {{
    var rowText = row.textContent.toLowerCase();
    var matchText   = !text   || rowText.includes(text);
    var matchStatus = !status || rowText.includes(status);
    var matchSite   = !site   || rowText.includes(site);
    row.style.display = (matchText && matchStatus && matchSite) ? "" : "none";
  }});
}}
</script>
</body>
</html>"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[+] HTML report saved → {report_path}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    timestamp   = datetime.now().strftime("%Y-%m-%d")
    report_path = os.path.join(REPORT_DIR, f"sitewide_report_{timestamp}.html")
    json_path   = os.path.join(REPORT_DIR, f"sitewide_report_{timestamp}.json")

    print(f"\n{'═'*60}")
    print(f"  🔗 Sitewide Link Checker")
    print(f"  {datetime.now().strftime('%B %d, %Y at %I:%M %p')}")
    print(f"{'═'*60}")

    all_links = []
    for site in SITES:
        links = crawl_site(site)
        all_links.extend(links)

    results = check_all_links(all_links)

    generate_html_report(results, report_path)

    # Save JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"[+] JSON data saved  → {json_path}")

    # Final summary
    ok    = sum(1 for r in results if r["status"] == "OK")
    redir = sum(1 for r in results if r["status"] == "REDIRECT")
    broke = sum(1 for r in results if r["status"] in ("BROKEN", "TIMEOUT", "ERROR"))
    print(f"\n{'═'*60}")
    print(f"  FINAL SUMMARY")
    print(f"{'─'*60}")
    for site in SITES:
        s = [r for r in results if r.get("site") == site["name"]]
        s_broke = sum(1 for r in s if r["status"] in ("BROKEN","TIMEOUT","ERROR"))
        print(f"  {site['name']}: {len(s)} links, {s_broke} broken")
    print(f"{'─'*60}")
    print(f"  Total : {len(results)}  ✅ {ok}  ↪️ {redir}  ❌ {broke}")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    main()
