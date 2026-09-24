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
| [`engagements/2026-09-29/`](engagements/2026-09-29/) | Databricks Apps with Asset Bundles: deploy a Plotly Dash app via DABs, wire the app `resources` block (job + SQL warehouse), offload the chart query to the warehouse, trigger a job from a button, schedule start/stop, and deploy per-user so a class shares one workspace. Driven by [`assets/apps/sample_dash_asset_bundle/`](assets/apps/sample_dash_asset_bundle/) | Complete |

Start with each engagement's `AGENDA.md`, which maps agenda items to files and covers setup,
running order and the gotchas.

## Shared

| Path | For |
| --- | --- |
| [`shared/prework.md`](shared/prework.md) | Pre-session setup (Free Edition account, test notebook). Same for every engagement |

## Assets

Reusable, runnable assets referenced by one or more engagements. Kept separate so a single
maintained copy serves every session that uses it.

| Path | What |
| --- | --- |
| [`assets/apps/sample_dash_asset_bundle/`](assets/apps/sample_dash_asset_bundle/) | Databricks App (Plotly Dash) packaged as an Asset Bundle: app `resources` block (job + SQL warehouse), warehouse-offloaded chart query, button-triggered job, scheduled start/stop, per-user deploy. Used by [`engagements/2026-09-29/`](engagements/2026-09-29/) |
| [`assets/jobs_pipelines/sample_jobs_pipelines_asset_bundle/`](assets/jobs_pipelines/sample_jobs_pipelines_asset_bundle/) | Jobs and Lakeflow Declarative Pipelines in one Asset Bundle: a standalone two-task job, standalone SQL + Python pipelines, and a job that orchestrates a pipeline via a `pipeline_task` (ingest → pipeline → summarize). Bundle creates the catalog + schemas (`direct` engine); serverless; per-user deploy. Needs a workspace where catalogs can be created (not Free Edition — the README covers the Free Edition variant) |

## Adding a new engagement

1. `cp -R engagements/2026-08-04 engagements/<new-date>` (or copy the closest existing one).
2. Replace the seed data, adapt the notebook narrative and transforms to the new scenario, and
   rewrite `AGENDA.md`.
3. Point the pre-work link at `../../shared/prework.md`.
4. Add a row to the table above.
