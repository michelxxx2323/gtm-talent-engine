# GTM Talent Engine

I'm job hunting the way GTM teams prospect. This engine finds, researches and
scores small and mid-size GTM agencies (Clay, GTM engineering, RevOps,
outbound, AI automation) in the US, Canada, the UK and Europe as remote
employers. It also finds the decision makers, drafts personalized outreach
and runs the follow-up cadence in Attio, using the stack those agencies sell.

Case page: [michelsoares.vercel.app/talent.html](https://michelsoares.vercel.app/talent.html?lang=en)

## Results (November 2026)

- 285 listings (196 Clay Solutions Partners and 89 from the GTM Daily
  directory) merged into 225 companies; cheap filters leave 202 candidates.
- Every candidate researched, put through gates and caps, and scored 0-100
  by Jev; Claude blind-scored a sample of 25 and the pilot of 20, which I
  labeled by hand to calibrate the rubric.
- Team geography from Clay for the top ~100. 97 companies in the Attio
  pipeline, decision makers for band A, 10 wave-1 drafts.

## Pipeline

```
Clay partner directory ──┐
GTM Daily directory ─────┼─► merge + dedupe ─► cheap filters ─► research ─► gates, caps, score ─► rank
GTM Daily + ATS jobs ────┘   (domain, name)    (region,          (site +      (Jev on all,
   = hiring signal                              language)         Clay)        Claude on a sample)
                                                                                      │
        Attio follow-up tasks ◄── drafts (sent by hand) ◄── Attio pipeline ◄── decision makers (Clay Search)
```

| Step | Code |
|---|---|
| Sources | [`engine/sources/`](engine/sources): Clay directory (PartnerPage public JSON), GTM Daily (within robots.txt), public ATS APIs (Ashby, Greenhouse, Lever, Workable) |
| Merge and filters | [`engine/consolidate.py`](engine/consolidate.py) |
| Research | [`engine/research.py`](engine/research.py): home page plus up to 6 site pages, company record |
| Clay enrichment | [`clay_enrich.py`](engine/sources/clay_enrich.py) and [`clay_geography.py`](engine/sources/clay_geography.py) read finished Clay workflow runs (no credits) |
| Scoring | [`engine/score.py`](engine/score.py): one dossier per company, Jev, comparison with Claude's blind scores |
| Calibration | [`engine/pilot.py`](engine/pilot.py), [`engine/labels.py`](engine/labels.py), [`engine/sample.py`](engine/sample.py) |
| Decision makers | [`engine/decision_makers.py`](engine/decision_makers.py) from Clay Search results |
| CRM | [`engine/attio_sync.py`](engine/attio_sync.py), [`attio_outreach.py`](engine/attio_outreach.py), [`attio_followups.py`](engine/attio_followups.py) |

## Rubric

[`config/rubric.yaml`](config/rubric.yaml) holds the exact texts both
evaluators receive; [`config/rubric.md`](config/rubric.md) explains them and
keeps the calibration log.

- **Gates → Out:** still operating; sells client service work.
- **Caps → at most C:** has a team; recent activity; remote work possible.
- **Score:** Clay depth 20, structure 20, team geography 20, hiring 20, fronts
  10, reachability 10. A ≥ 70 (wave 1), B ≥ 50 (wave 2).

Every score cites an evidence URL; no evidence means 0. Rejected companies go
to `rejected.csv` with the reason, never dropped silently.

## Clay workflows

Built in Clay with the CLI, on the free plan:

1. **Company enrichment waterfall:** CSV upload (name, domain, LinkedIn URL) →
   Enrich company (Clay, 0.5 credit) → "Clay found nothing?" → Enrich company
   (Datagma fallback, 0.4, only when Clay finds nothing).
2. **Team geography:** CSV upload (name, domain, company identifier) →
   Employee headcount by country (1 credit).

```bash
clay workflows triggers csv upload <trigger id> --file clay/<batch>.csv
clay workflows triggers csv run <trigger id>   # once: running it again spends twice
python engine/sources/clay_enrich.py           # or clay_geography.py
```

`csv run --limit N` restarts from the top of the file, so after a 1-row
smoke test upload a file without that row.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env    # add your keys and IDs

python engine/sources/clay_directory.py
python engine/sources/gtm_daily.py
python engine/sources/ats_jobs.py
python engine/consolidate.py               # -> data/out/candidates.csv, rejected.csv
python engine/research.py candidates
python engine/score.py dossier candidates
python engine/score.py jev candidates
python engine/sample.py                    # blind sample for Claude
python engine/score.py compare candidates
python engine/rank.py                      # -> data/out/ranked.csv
python engine/decision_makers.py
python engine/attio_sync.py A --dry-run    # then A, AB or ABD
python engine/attio_followups.py --dry-run
```

`config/profile.yaml` describes the candidate (me): fronts, proof points and
hard constraints. Change it to point the engine at someone else.

## Constraints, on purpose

- **Clay first:** every step Clay can do runs in Clay; each fallback is
  logged in [`docs/decisions.md`](docs/decisions.md).
- **Clay on the free plan:** credits and search quota are budgeted, not assumed.
- **The engine never sends a message.** It drafts; I send by hand.
- **No emails or phone numbers** are collected. Contacts live in Attio, not in
  files or anything public (GDPR/LGPD).
- **No automated LinkedIn scraping.** LinkedIn data only through Clay.
- **robots.txt is respected**, and sites that block bots are not worked
  around: they count as thin evidence.

## Not in this repository

Research data, dossiers, scores, rankings, contacts and drafts name real
agencies and people, so they stay in a private repository. Only the code,
configuration and the decisions log are public.
