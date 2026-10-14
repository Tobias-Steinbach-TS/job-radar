"""
LLM-Einordnung von Stellenanzeigen über die Claude API.

Ein kleiner Agent mit zwei Werkzeugen:
  - fetch_posting:     lädt den Anzeigentext von der Job-URL (Claude entscheidet selbst, ob nötig)
  - record_assessment: gibt die strukturierte Einordnung zurück (beendet die Schleife)

Ergebnisse werden in assessments.json gecacht, damit jede Anzeige nur einmal
an die API geht.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import anthropic
except ImportError:
    anthropic = None


# ── Konfiguration ──────────────────────────────────────────────

MODEL = "claude-haiku-5-5"
CACHE_FILE = "assessments.json"
MAX_PER_RUN = 25          # Kostenbremse: höchstens so viele neue Einordnungen pro Lauf
MAX_STEPS = 4             # höchstens so viele Runden pro Anzeige
MAX_POSTING_CHARS = 6000  # Anzeigentext wird gekürzt, bevor er ans Modell geht

MY_PROFILE = """\
Junior-Profil, Berlin. Abschluss: Internationale BWL (WU Wien).
Ausbildung: Le Wagon Data Science & AI Bootcamp (2026), WBS Datenanalyse-Bootcamp (2025).
Stack: Python (pandas, NumPy), SQL, BigQuery, scikit-learn, LightGBM, TensorFlow/Keras,
LLMs & RAG (LangChain), Docker, FastAPI, GCP (Cloud Run), Prefect, MLflow, Git/GitHub,
Tableau, Looker Studio, Streamlit.
Nicht vorhanden: Power BI, Azure, AWS, Airflow, dbt, Spark, SAP.
Sprachen: Deutsch C2, Englisch C1, Italienisch C1.
Keine Berufserfahrung in einer Data-Rolle; sucht Junior- und Einstiegsstellen.
Nicht eingeschrieben: Werkstudenten- und Pflichtpraktikumsstellen passen nicht."""

SYSTEM_PROMPT = f"""Du ordnest Stellenanzeigen für eine Person ein, die einen Job im Datenbereich sucht.

Profil der Person:
{MY_PROFILE}

Vorgehen:
- Reichen Titel und Firma nicht für eine belastbare Einordnung, lade die Anzeige mit fetch_posting.
- Schlägt das Laden fehl, ordne nur anhand des Titels ein und setze confidence auf "niedrig".
- Schließe mit genau einem Aufruf von record_assessment ab.
- Nenne nur Anforderungen, die tatsächlich in der Anzeige stehen. Erfinde nichts.
- "fit" bewertet, wie realistisch eine Bewerbung für genau dieses Profil ist, nicht wie attraktiv die Stelle ist."""

TOOLS = [
    {
        "name": "fetch_posting",
        "description": "Lädt den Text der Stellenanzeige von ihrer URL. Nur aufrufen, "
                       "wenn Titel und Firma für die Einordnung nicht reichen.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL der Anzeige"}},
            "required": ["url"],
        },
    },
    {
        "name": "record_assessment",
        "description": "Speichert die strukturierte Einordnung der Anzeige. Beendet die Bearbeitung.",
        "input_schema": {
            "type": "object",
            "properties": {
                "role_type": {
                    "type": "string",
                    "description": "z. B. Data Analyst, Data Engineer, Data Scientist, BI, AI Engineer, Sonstiges",
                },
                "seniority": {
                    "type": "string",
                    "enum": ["Werkstudent/Praktikum", "Junior", "Mid", "Senior", "Unklar"],
                },
                "language": {"type": "string", "enum": ["Deutsch", "Englisch", "Beides", "Unklar"]},
                "must_haves": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Wichtigste Muss-Anforderungen, höchstens 6, kurz",
                },
                "gaps": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Muss-Anforderungen, die im Profil fehlen",
                },
                "fit": {"type": "string", "enum": ["hoch", "mittel", "gering"]},
                "reason": {"type": "string", "description": "Ein Satz Begründung für fit"},
                "confidence": {"type": "string", "enum": ["hoch", "niedrig"]},
            },
            "required": ["role_type", "seniority", "language", "must_haves",
                         "gaps", "fit", "reason", "confidence"],
        },
    },
]


# ── Werkzeuge ──────────────────────────────────────────────────

def fetch_posting(url: str, headers: dict) -> str:
    """Lädt die Seite und gibt bereinigten Text zurück (oder eine Fehlermeldung fürs Modell)."""
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
    except Exception as e:
        return f"FEHLER: Seite nicht ladbar ({e})."
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    if len(text) < 200:
        return "FEHLER: Seite enthält kaum Text (vermutlich Login oder Bot-Schutz)."
    return text[:MAX_POSTING_CHARS]


# ── Cache ──────────────────────────────────────────────────────

def load_cache() -> dict:
    p = Path(CACHE_FILE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("assessments.json beschädigt, starte mit leerem Cache")
        return {}


def save_cache(cache: dict):
    Path(CACHE_FILE).write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Agenten-Schleife ───────────────────────────────────────────

def assess_job(client, job: dict, headers: dict) -> dict | None:
    """Lässt Claude eine Anzeige einordnen. Gibt das Assessment-Dict zurück oder None."""
    messages = [{
        "role": "user",
        "content": f"Titel: {job['title']}\nFirma: {job['company']}\n"
                   f"Quelle: {job['source']}\nURL: {job['url']}",
    }]

    for step in range(MAX_STEPS):
        # In der letzten Runde muss record_assessment kommen
        tool_choice = ({"type": "tool", "name": "record_assessment"}
                       if step == MAX_STEPS - 1 else {"type": "any"})
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            tool_choice=tool_choice,
            messages=messages,
        )

        tool_results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if block.name == "record_assessment":
                result = dict(block.input)
                result["fetched"] = any(
                    m["role"] == "user" and isinstance(m["content"], list)
                    for m in messages
                )
                return result
            if block.name == "fetch_posting":
                url = block.input.get("url") or job["url"]
                log.info(f"      Agent lädt Anzeige: {job['title'][:50]}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": fetch_posting(url, headers),
                })

        if not tool_results:
            break
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": tool_results})

    log.warning(f"   Keine Einordnung erhalten: {job['title']}")
    return None


def assess_jobs(jobs: list, headers: dict) -> dict:
    """Ordnet neue Jobs ein, nutzt den Cache. Gibt {job_id: assessment} für die übergebenen Jobs zurück."""
    cache = load_cache()

    if anthropic is None:
        log.info("Paket 'anthropic' fehlt – Einordnung übersprungen (pip install anthropic)")
        return {j["id"]: cache[j["id"]] for j in jobs if j.get("id") in cache}
    if not os.getenv("ANTHROPIC_API_KEY"):
        log.info("ANTHROPIC_API_KEY nicht gesetzt – Einordnung übersprungen")
        return {j["id"]: cache[j["id"]] for j in jobs if j.get("id") in cache}

    client = anthropic.Anthropic()
    todo = [j for j in jobs if j.get("id") and j["id"] not in cache][:MAX_PER_RUN]
    log.info(f"Ordne {len(todo)} Stellen mit Claude ein ...")

    for job in todo:
        try:
            result = assess_job(client, job, headers)
        except Exception as e:
            log.warning(f"   API-Fehler bei '{job['title']}': {e}")
            continue
        if result:
            cache[job["id"]] = result
            log.info(f"   {result['fit']:>6} | {result['seniority']:<10} | {job['title'][:60]}")

    save_cache(cache)
    return {j["id"]: cache[j["id"]] for j in jobs if j.get("id") in cache}
