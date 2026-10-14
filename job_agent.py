#!/usr/bin/env python3
"""
Data Analyst Job Agent für Berlin
Durchsucht täglich Job-Plattformen und generiert ein lokales HTML-Dashboard.

Unterstützte Plattformen:
  - StepStone, Indeed, Glassdoor, Xing, LinkedIn
"""

import os, json, hashlib, logging, time, random, webbrowser, subprocess, sys
from datetime import datetime, date
from html import escape
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ── Konfiguration ──────────────────────────────────────────────
CONFIG = {
    "search_query":          "Data Analyst",
    "location":              "Berlin",
    "huntr_token":           os.getenv("HUNTR_API_TOKEN", ""),
    "huntr_board_list_id":   os.getenv("HUNTR_LIST_ID", ""),
    "log_file":              "job_agent.log",
    "seen_file":             "seen_jobs.json",
    "dashboard_file":        "dashboard.html",
    "max_jobs_per_source":   10,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(CONFIG["log_file"], encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# Erst nach logging.basicConfig importieren, damit das Modul dasselbe Log nutzt
from assessor import assess_jobs


# ── Hilfsfunktionen ────────────────────────────────────────────

def load_seen() -> set:
    p = Path(CONFIG["seen_file"])
    return set(json.loads(p.read_text())) if p.exists() else set()


def save_seen(seen: set):
    Path(CONFIG["seen_file"]).write_text(json.dumps(list(seen), indent=2))


def job_id(title, company, url):
    return hashlib.md5(f"{title}|{company}|{url}".lower().encode()).hexdigest()[:12]


def polite_pause(a=1.5, b=4.0):
    time.sleep(random.uniform(a, b))


def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.warning(f"Fehler: {url} -> {e}")
        return None


# ── Scraper ────────────────────────────────────────────────────

def scrape_stepstone():
    log.info("Durchsuche StepStone ...")
    soup = get_soup("https://www.stepstone.de/jobs/data-analyst/in-berlin.html?sort=2")
    if not soup:
        return []
    jobs = []
    for card in soup.select("article[data-at='job-item']")[:CONFIG["max_jobs_per_source"]]:
        try:
            t = card.select_one("[data-at='job-item-title']")
            c = card.select_one("[data-at='job-item-company-name']")
            a = card.select_one("a[data-at='job-item-title']")
            href = a["href"] if a else ""
            if href and not href.startswith("http"):
                href = "https://www.stepstone.de" + href
            jobs.append({"title": t.get_text(strip=True) if t else "-",
                         "company": c.get_text(strip=True) if c else "-",
                         "url": href, "source": "StepStone"})
        except Exception:
            pass
    log.info(f"   -> {len(jobs)} Jobs")
    return jobs


def scrape_indeed():
    log.info("Durchsuche Indeed ...")
    soup = get_soup("https://de.indeed.com/jobs?q=Data+Analyst&l=Berlin&sort=date&fromage=1")
    if not soup:
        return []
    jobs = []
    for card in soup.select("div.job_seen_beacon")[:CONFIG["max_jobs_per_source"]]:
        try:
            t = card.select_one("h2.jobTitle span[title]")
            c = card.select_one("span.companyName")
            a = card.select_one("h2.jobTitle a")
            jobs.append({"title": t["title"] if t else "-",
                         "company": c.get_text(strip=True) if c else "-",
                         "url": "https://de.indeed.com" + (a["href"] if a else ""),
                         "source": "Indeed"})
        except Exception:
            pass
    log.info(f"   -> {len(jobs)} Jobs")
    return jobs


def scrape_glassdoor():
    log.info("Durchsuche Glassdoor ...")
    soup = get_soup(
        "https://www.glassdoor.de/Job/berlin-data-analyst-jobs-SRCH_IL.0,6_IC2622109_KO7,19.htm?sortBy=date_desc"
    )
    if not soup:
        return []
    jobs = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else \
                    [e.get("item", {}) for e in data.get("itemListElement", [])]
            for item in items[:CONFIG["max_jobs_per_source"]]:
                if item.get("@type") == "JobPosting":
                    jobs.append({"title": item.get("title", "-"),
                                 "company": item.get("hiringOrganization", {}).get("name", "-"),
                                 "url": item.get("url", ""), "source": "Glassdoor"})
        except Exception:
            pass
    if not jobs:
        for card in soup.select("li.react-job-listing")[:CONFIG["max_jobs_per_source"]]:
            try:
                t = card.select_one("[data-test='job-title']")
                c = card.select_one("[data-test='employer-name']")
                a = card.select_one("a[data-test='job-link']")
                jobs.append({"title": t.get_text(strip=True) if t else "-",
                             "company": c.get_text(strip=True) if c else "-",
                             "url": "https://www.glassdoor.de" + (a["href"] if a else ""),
                             "source": "Glassdoor"})
            except Exception:
                pass
    log.info(f"   -> {len(jobs)} Jobs")
    return jobs


def scrape_xing():
    log.info("Durchsuche Xing ...")
    soup = get_soup(
        "https://www.xing.com/jobs/search?keywords=Data+Analyst&location=Berlin&sort=date"
    )
    if not soup:
        return []
    jobs = []
    for card in soup.select("article.jobs-search-results-list-item")[:CONFIG["max_jobs_per_source"]]:
        try:
            t = card.select_one("a.jobs-search-results-list-item--title")
            c = card.select_one("span.jobs-search-results-list-item--company-name")
            jobs.append({"title": t.get_text(strip=True) if t else "-",
                         "company": c.get_text(strip=True) if c else "-",
                         "url": "https://www.xing.com" + (t["href"] if t else ""),
                         "source": "Xing"})
        except Exception:
            pass
    log.info(f"   -> {len(jobs)} Jobs")
    return jobs


def scrape_linkedin():
    log.info("Durchsuche LinkedIn ...")
    soup = get_soup(
        "https://www.linkedin.com/jobs/search/?keywords=Data%20Analyst"
        "&location=Berlin&f_TPR=r86400&sortBy=DD"
    )
    if not soup:
        return []
    jobs = []
    for card in soup.select("div.base-card")[:CONFIG["max_jobs_per_source"]]:
        try:
            t = card.select_one("h3.base-search-card__title")
            c = card.select_one("h4.base-search-card__subtitle")
            a = card.select_one("a.base-card__full-link")
            jobs.append({"title": t.get_text(strip=True) if t else "-",
                         "company": c.get_text(strip=True) if c else "-",
                         "url": a["href"] if a else "",
                         "source": "LinkedIn"})
        except Exception:
            pass
    log.info(f"   -> {len(jobs)} Jobs")
    return jobs


# ── Huntr API ──────────────────────────────────────────────────

def post_to_huntr(job):
    token, lid = CONFIG["huntr_token"], CONFIG["huntr_board_list_id"]
    if not (token and lid):
        return False
    try:
        r = requests.post(
            "https://api.huntr.co/org/job-posts",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"title": job["title"], "companyName": job["company"],
                  "jobUrl": job["url"], "listId": lid,
                  "location": "Berlin", "notes": f"Quelle: {job['source']}"},
            timeout=10,
        )
        r.raise_for_status()
        log.info(f"   Huntr: {job['title']} gespeichert")
        return True
    except Exception as e:
        log.warning(f"   Huntr Fehler: {e}")
        return False


# ── HTML-Dashboard ─────────────────────────────────────────────

SOURCE_COLORS = {
    "StepStone": "#e8642c",
    "Indeed":    "#2164f3",
    "Glassdoor": "#0caa41",
    "Xing":      "#026466",
    "LinkedIn":  "#0a66c2",
}


FIT_COLORS = {
    "hoch":   "#2f855a",
    "mittel": "#b7791f",
    "gering": "#9b2c2c",
}


def render_assessment(a):
    """HTML-Block mit der Claude-Einordnung einer Stelle."""
    if not a:
        return ""
    chips = "".join(f'<span class="chip">{escape(m)}</span>' for m in a.get("must_haves", []))
    gaps = ", ".join(escape(g) for g in a.get("gaps", [])) or "keine erkannt"
    low = ' &middot; <span title="Nur anhand des Titels eingeordnet">unsicher</span>' \
        if a.get("confidence") == "niedrig" else ""
    return f"""
            <div class="assess">
              <div class="assess-head">
                <span class="fit" style="background:{FIT_COLORS.get(a['fit'], '#666')}">Passung {escape(a['fit'])}</span>
                <span class="assess-meta">{escape(a.get('seniority', ''))} &middot; {escape(a.get('language', ''))}{low}</span>
              </div>
              <p class="assess-reason">{escape(a.get('reason', ''))}</p>
              <div class="chips">{chips}</div>
              <p class="assess-gaps"><strong>Lücken:</strong> {gaps}</p>
            </div>"""


def make_huntr_url(job):
    from urllib.parse import quote
    return (
        f"https://huntr.co/kanban/jobs/new"
        f"?title={quote(job['title'])}"
        f"&company={quote(job['company'])}"
        f"&url={quote(job['url'])}"
    )


def generate_dashboard(new_jobs, all_today):
    today_str = datetime.now().strftime("%A, %d. %B %Y, %H:%M Uhr")

    source_counts = {}
    for j in all_today:
        source_counts[j["source"]] = source_counts.get(j["source"], 0) + 1

    badges_html = "".join(
        f'<span class="badge" style="background:{SOURCE_COLORS.get(s,"#666")}">'
        f'{s}&nbsp;<strong>{n}</strong></span>'
        for s, n in source_counts.items()
    )

    filters_html = (
        '<button class="filter active" onclick="filterCards(\'all\', this)">Alle</button>' +
        "".join(
            f'<button class="filter" onclick="filterCards(\'{s}\', this)" '
            f'style="--fc:{SOURCE_COLORS[s]}">{s}</button>'
            for s in SOURCE_COLORS
        )
    )
    if any(j.get("assessment") for j in new_jobs):
        filters_html += (
            '<span class="filter-sep"></span>' +
            "".join(
                f'<button class="filter" onclick="filterCards(\'fit:{f}\', this)" '
                f'style="--fc:{FIT_COLORS[f]}">Passung {f}</button>'
                for f in FIT_COLORS
            )
        )

    if not new_jobs:
        cards_html = '<div class="empty">Keine neuen Stellen heute. Genieße deinen Kaffee!</div>'
    else:
        cards_html = ""
        for i, job in enumerate(new_jobs):
            color = SOURCE_COLORS.get(job["source"], "#555")
            huntr = make_huntr_url(job)
            delay = i * 0.05
            a = job.get("assessment")
            fit = a["fit"] if a else ""
            cards_html += f"""
        <div class="card" data-source="{job['source']}" data-fit="{fit}" style="animation-delay:{delay:.2f}s">
          <div class="card-source" style="background:{color}">{job['source']}</div>
          <div class="card-body">
            <h2 class="card-title">{escape(job['title'])}</h2>
            <p class="card-company">&#127970; {escape(job['company'])}</p>
            {render_assessment(a)}
          </div>
          <div class="card-actions">
            <a class="btn btn-primary" href="{job['url']}" target="_blank" rel="noopener">Zur Stelle &rarr;</a>
            <a class="btn btn-huntr" href="{huntr}" target="_blank" rel="noopener">+ Huntr</a>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job-Dashboard &middot; {date.today().isoformat()}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,300;0,700;1,300&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --bg: #f5f2eb; --ink: #1a1209; --muted: #7a6e5f;
  --card-bg: #fffef9; --border: #e2ddd3; --accent: #c4622d;
  --radius: 12px; --shadow: 0 2px 16px rgba(0,0,0,.07);
}}
body {{ font-family: 'DM Mono', monospace; background: var(--bg); color: var(--ink); min-height: 100vh; padding-bottom: 60px; }}
header {{ background: var(--ink); color: var(--bg); padding: 36px 40px 56px; position: relative; overflow: hidden; }}
header::after {{ content: ''; position: absolute; bottom: -30px; left: -10px; right: -10px; height: 60px; background: var(--bg); border-radius: 50%; }}
.header-label {{ font-size: .7rem; letter-spacing: .18em; text-transform: uppercase; opacity: .5; margin-bottom: 8px; }}
header h1 {{ font-family: 'Fraunces', serif; font-size: clamp(2rem, 5vw, 3.2rem); font-weight: 300; line-height: 1.1; }}
header h1 em {{ font-style: italic; color: #f0a06a; }}
.header-meta {{ margin-top: 12px; font-size: .75rem; opacity: .45; }}
.stat-bar {{ display: flex; gap: 10px; flex-wrap: wrap; padding: 36px 40px 0; align-items: center; }}
.stat-count {{ font-family: 'Fraunces', serif; font-size: 3rem; font-weight: 700; color: var(--accent); line-height: 1; margin-right: 6px; }}
.stat-label {{ font-size: .75rem; color: var(--muted); margin-right: 20px; }}
.badge {{ display: inline-flex; align-items: center; gap: 4px; padding: 4px 12px; border-radius: 99px; font-size: .68rem; color: #fff; letter-spacing: .04em; }}
.filter-bar {{ padding: 20px 40px 0; display: flex; gap: 8px; flex-wrap: wrap; }}
.filter {{ border: 1.5px solid var(--border); background: transparent; padding: 6px 16px; border-radius: 99px; font-family: 'DM Mono', monospace; font-size: .72rem; cursor: pointer; transition: all .18s; color: var(--ink); }}
.filter:hover {{ border-color: var(--fc, var(--accent)); color: var(--fc, var(--accent)); }}
.filter.active {{ background: var(--ink); border-color: var(--ink); color: var(--bg); }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; padding: 24px 40px 0; }}
.card {{ background: var(--card-bg); border: 1.5px solid var(--border); border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow); display: flex; flex-direction: column; transition: transform .18s, box-shadow .18s; animation: rise .35s ease both; }}
.card:hover {{ transform: translateY(-3px); box-shadow: 0 6px 28px rgba(0,0,0,.12); }}
@keyframes rise {{ from {{ opacity:0; transform:translateY(12px); }} to {{ opacity:1; transform:translateY(0); }} }}
.card-source {{ padding: 5px 14px; font-size: .65rem; letter-spacing: .12em; text-transform: uppercase; color: #fff; font-weight: 500; }}
.card-body {{ padding: 18px 20px 12px; flex: 1; }}
.card-title {{ font-family: 'Fraunces', serif; font-size: 1.05rem; font-weight: 300; line-height: 1.3; margin-bottom: 8px; }}
.card-company {{ font-size: .75rem; color: var(--muted); }}
.card-actions {{ display: flex; gap: 8px; padding: 12px 20px 16px; border-top: 1px solid var(--border); }}
.btn {{ flex: 1; text-align: center; padding: 8px 10px; border-radius: 8px; font-family: 'DM Mono', monospace; font-size: .72rem; text-decoration: none; transition: opacity .15s; }}
.btn:hover {{ opacity: .8; }}
.btn-primary {{ background: var(--ink); color: var(--bg); }}
.btn-huntr {{ background: #e8f4f8; color: #1a4f6e; border: 1px solid #c5dde8; }}
.empty {{ grid-column: 1/-1; text-align: center; padding: 60px 20px; font-family: 'Fraunces', serif; font-size: 1.2rem; color: var(--muted); font-style: italic; }}
.filter-sep {{ width: 1px; background: var(--border); margin: 0 6px; }}
.assess {{ margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--border); }}
.assess-head {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }}
.fit {{ color: #fff; font-size: .65rem; padding: 3px 10px; border-radius: 99px; letter-spacing: .04em; }}
.assess-meta {{ font-size: .68rem; color: var(--muted); }}
.assess-reason {{ font-size: .72rem; line-height: 1.5; margin-bottom: 8px; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }}
.chip {{ font-size: .62rem; padding: 2px 8px; border-radius: 6px; background: #efe9dd; color: var(--ink); }}
.assess-gaps {{ font-size: .68rem; color: var(--muted); line-height: 1.5; }}
footer {{ margin-top: 48px; text-align: center; font-size: .68rem; color: var(--muted); }}
@media (max-width: 600px) {{ header, .stat-bar, .filter-bar, .grid {{ padding-left: 20px; padding-right: 20px; }} }}
</style>
</head>
<body>
<header>
  <div class="header-label">Daily Briefing &middot; Berlin</div>
  <h1>Neue <em>Data&nbsp;Analyst</em><br>Stellen f&uuml;r dich</h1>
  <div class="header-meta">Zuletzt aktualisiert: {today_str}</div>
</header>
<div class="stat-bar">
  <div>
    <span class="stat-count">{len(new_jobs)}</span>
    <span class="stat-label">neue Stelle{"n" if len(new_jobs) != 1 else ""}<br>heute gefunden</span>
  </div>
  {badges_html}
</div>
<div class="filter-bar">{filters_html}</div>
<div class="grid" id="grid">
  {cards_html}
</div>
<footer><p style="margin-top:16px">Generiert von deinem Job-Agenten &middot; {date.today().isoformat()}</p></footer>
<script>
function filterCards(source, btn) {{
  document.querySelectorAll('.filter').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.card').forEach(card => {{
    const show = source === 'all'
      || card.dataset.source === source
      || (source.startsWith('fit:') && card.dataset.fit === source.slice(4));
    card.style.display = show ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""

    Path(CONFIG["dashboard_file"]).write_text(html, encoding="utf-8")
    log.info(f"Dashboard gespeichert: {Path(CONFIG['dashboard_file']).resolve()}")


# ── Hauptprogramm ──────────────────────────────────────────────

def main():
    log.info("=" * 58)
    log.info(f"Job-Agent gestartet [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
    log.info("=" * 58)

    seen = load_seen()
    all_today = []

    for scraper in [scrape_stepstone, scrape_indeed, scrape_glassdoor,
                    scrape_xing, scrape_linkedin]:
        try:
            all_today.extend(scraper())
        except Exception as e:
            log.error(f"{scraper.__name__}: {e}")
        polite_pause()

    log.info(f"Gesamt gefunden: {len(all_today)} Jobs")

    new_jobs = []
    for job in all_today:
        jid = job_id(job["title"], job["company"], job["url"])
        if jid not in seen:
            job["id"] = jid
            new_jobs.append(job)
            seen.add(jid)

    log.info(f"Davon neu: {len(new_jobs)}")

    # Claude ordnet neue Stellen ein (übersprungen, falls kein API-Key gesetzt)
    assessments = assess_jobs(new_jobs, HEADERS)
    for job in new_jobs:
        job["assessment"] = assessments.get(job["id"])
    fit_rank = {"hoch": 0, "mittel": 1, "gering": 2}
    new_jobs.sort(key=lambda j: fit_rank.get((j["assessment"] or {}).get("fit"), 3))

    # Huntr API (nur für Org-Accounts)
    if CONFIG["huntr_token"] and CONFIG["huntr_board_list_id"]:
        for job in new_jobs:
            post_to_huntr(job)
            polite_pause(0.5, 1.5)

    generate_dashboard(new_jobs, all_today)
    save_seen(seen)

    # Dashboard automatisch im Browser öffnen
    dashboard_path = str(Path(CONFIG["dashboard_file"]).resolve())
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", dashboard_path])
        elif sys.platform == "win32":
            os.startfile(dashboard_path)
        else:
            subprocess.run(["xdg-open", dashboard_path])
        log.info("Dashboard im Browser geoeffnet")
    except Exception:
        log.info(f"Bitte manuell oeffnen: {dashboard_path}")

    log.info(f"Fertig! {len(new_jobs)} neue Stellen gefunden.")


if __name__ == "__main__":
    main()
