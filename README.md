# Job Radar

A small pipeline I built for my own job search. Every weekday morning it collects
new data job listings in Berlin from several platforms (StepStone, Indeed,
Glassdoor, Xing, LinkedIn), removes duplicates and listings it has already seen,
and generates a single HTML overview.

New listings are then assessed by Claude: role type, seniority, language,
key requirements, which of them I don't meet yet, and an overall fit rating.
The dashboard sorts by fit and can be filtered by it.

## How the assessment works

`assessor.py` runs a small agent loop with two tools:

- **`fetch_posting`** – loads the full listing text. The model decides whether
  title and company are enough or whether it needs the full text.
- **`record_assessment`** – returns the result as structured fields
  (JSON schema), which ends the loop.

If a page can't be loaded (login walls, bot protection), the model assesses the
listing from its title alone and marks the result as low confidence.

Results are cached in `assessments.json`, so every listing is sent to the API
only once. A per-run limit keeps costs predictable.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project folder:

```
ANTHROPIC_API_KEY=your-key
```

Without a key the pipeline still runs; it simply skips the assessment step.

## Run

```bash
python job_agent.py
```

## Scheduling

Runs on weekdays via cron:

```
0 9 * * 1-5 cd ~/job-agent && python3 job_agent.py
```

## Notes

- Scraping depends on each site's current HTML structure; selectors break when
  sites change their layout.
- Built for personal use; it keeps request volume low and pauses between requests.
