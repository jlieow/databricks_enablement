# Databricks enablement materials

Hands-on Databricks enablement sessions, organised one folder per customer engagement. Each
engagement is self-contained and runnable on Databricks Free Edition. Content shared across
engagements lives in [`shared/`](shared/).

## Engagements

Engagements are named by session date.

| Engagement | Scenario | Status |
| --- | --- | --- |
| [`engagements/2026-08-04/`](engagements/2026-08-04/) | Client (ad-spend) data consolidation for a marketing agency: Auto Loader → medallion → RLS → cost → Genie → dashboard | Complete |
| [`engagements/2026-08-24/`](engagements/2026-08-24/) | Scientific publisher: connector-based ingestion (CSV upload + Google Drive connector) → medallion → internal campaign-engagement report on AI/BI dashboard + Genie, with cost readout and a governance foundation | Complete |
| [`engagements/2026-09-04/`](engagements/2026-09-04/) | Health authority: patient encounter medallion platform (outpatient visits, inpatient admissions, lab results) with classical risk-stratification model, clinical-note extraction, academic literature retrieval agent, batch serving to PostgreSQL, Genie, dashboards | Complete |

Start with each engagement's `AGENDA.md`, which maps agenda items to files and covers setup,
running order and the gotchas.

## Shared

| Path | For |
| --- | --- |
| [`shared/prework.md`](shared/prework.md) | Pre-session setup (Free Edition account, test notebook). Same for every engagement |

## Adding a new engagement

1. `cp -R engagements/2026-08-04 engagements/<new-date>` (or copy the closest existing one).
2. Replace the seed data, adapt the notebook narrative and transforms to the new scenario, and
   rewrite `AGENDA.md`.
3. Point the pre-work link at `../../shared/prework.md`.
4. Add a row to the table above.
