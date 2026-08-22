# Enablement: which file goes with which agenda item

Everything here is a **completed reference copy**. We build these live and from scratch during the
session; use these to catch up if you fall behind, and to refer back to afterwards.

This enablement prepares the customer team to run the POC by practising the build patterns on safe
sample data. It is a focused two-hour session with a one-hour buffer, not a full platform
demo. The team already has strong data, architecture and cloud fundamentals, so the time goes on
Databricks specifics and gotchas, not on data or cloud basics.

The scenario mirrors the customer's real work: campaign engagement for two fictional manufacturer
clients, across three marketing **tactics** (product listings, email blasts, webinars),
consolidated through Bronze → Silver → Gold into one internal report per client. No live sources
and no production credentials: the connector story is carried by a personal Google Drive.

---

## Session 1 — the two-hour build (agenda items 1 to 6)

| # | Agenda item | Files |
| --- | --- | --- |
| 1 | Workspace, Unity Catalog, and medallion foundations | `notebooks/01_foundations.py` |
| 2 | Ingestion: CSV upload with Auto Loader, plus a connector | `notebooks/02_ingest_csv_autoloader.py`, `docs/google_drive_connector_guide.md` |
| 3 | Silver to Gold: dedupe, validate, standardise, consolidate | `notebooks/03_medallion_transform.py` |
| — | Onboarding a second client with no code change | `notebooks/04_template_reuse.py` |
| 4 | Analytics: dashboard and Genie over the gold report | `data/client_engagement.lvdash.json`, `docs/genie_space_guide.md`, `notebooks/05_genie_space.py` |
| 5 | Cost awareness and the levers | `notebooks/06_cost_visibility.py` |
| 6 | Governance foundation (introduced; optional worked example) | `notebooks/07_row_level_security.py` |

Notes on the mapping:

- **Item 2 has two halves.** The CSV-upload half is notebook 02 (real, runnable). The connector
  half is `google_drive_connector_guide.md`, a UI walkthrough using a personal Google Drive as a
  safe stand-in for a real connector. Both land data the same way, which is the point.
- **Notebook 04 is not its own agenda item.** It sits between items 3 and 4 because onboarding the
  second client is what makes the dashboard and Genie show two clients. It runs notebooks 02 and 03
  unchanged, and it also builds the consolidated `gold_all_clients_master` table the dashboard reads.
- **Item 4 is built in the UI.** The dashboard is a `.lvdash.json` file you import; the Genie space
  is built by hand following `genie_space_guide.md`, because the curation *is* the work. Notebook 05
  is a fallback that builds the same space over the REST API.
- **Item 6 is introduced conceptually in the session.** Notebook 07 is the optional worked example
  (a POC nice-to-have) that makes row-level security concrete. Governance build-out beyond the
  foundation is roadmap, per the POC doc.

---

## Buffer — one hour, only if needed

| Topic | Files |
| --- | --- |
| Overflow / second pass on anything that ran short | (whichever notebook or guide) |
| Power BI connection (optional) | `docs/power_bi_connection_guide.md` |

The customer already uses Power BI, so the connection guide is the natural buffer topic. It is a
nice-to-have, not a core deliverable.

---

## Setup

The notebooks assume this structure, which notebook 01 walks through creating:

| Object | Name |
| --- | --- |
| Catalog | `enablement` |
| Schemas | `01_raw`, `02_bronze`, `03_silver`, `04_gold`, `05_ops` |
| Volumes | `01_raw.landing`, `01_raw.checkpoints` |

Upload the seed CSVs from `data/landing/<client>/` to
`/Volumes/enablement/01_raw/landing/<client>/`, one folder per client:

- `helix_biosciences/`
- `orbital_instruments/`

Catalog and schema names are literals in these notebooks rather than parameters, so they run as-is.
To use different names, edit the constants near the top of each notebook.

**Notebook 05 needs your own SQL warehouse id.** It is set to `PASTE_YOUR_WAREHOUSE_ID`; replace it
with the id from **SQL Warehouses** in your workspace.

---

## Running order

Almost the agenda order, because each notebook reads tables the earlier ones create.

| Order | Notebook | Why here |
| --- | --- | --- |
| 1 | `01_foundations` | Creates the catalog, schemas and volumes everything else needs |
| 2 | `02_ingest_csv_autoloader` | Raw tables for the first client (`helix_biosciences`) |
| 3 | `03_medallion_transform` | Bronze, silver and gold for the first client |
| 4 | `04_template_reuse` | Onboards `orbital_instruments`, then builds `gold_all_clients_master` |
| 5 | `05_genie_space` | **Optional.** Only if you want the space built for you instead of in the UI |
| 6 | `06_cost_visibility` | Populates the dashboard's Cost page |
| 7 | `07_row_level_security` | **Optional worked example.** Reads the consolidated table from 04 |

Ordering traps:

- **Upload the CSVs before running 02.** Notebook 01 creates the landing folders, but the files
  have to be uploaded (or landed via the Google Drive connector) before Auto Loader has anything to
  read.
- **04 calls notebooks 02 and 03.** So all three must sit in the same folder, which is how they are
  distributed. Do not shortcut onboarding by re-running 02 with the widget changed; running 04 is
  the point, because it proves onboarding is configuration, not code.
- **The dashboard reads `gold_all_clients_master`**, which notebook 04 builds. Import the dashboard
  after 04 has run, and its Cost page after 06.
- **Re-run 04 after anything that changes a client's gold table**, and re-run 07 after 04. Both take
  point-in-time copies that do not auto-update.

---

## Things worth knowing

- **Notebook 02 ingests one client, not both.** It takes `client_id` as a widget, defaulting to
  `helix_biosciences`. The second client (`orbital_instruments`) is onboarded in notebook 04, which
  calls 02 and 03 unchanged with a different `client_id`. That is the point of 04: onboarding is
  configuration, not new code.
- **No FX, no currency, no live API.** Unlike an ad-spend scenario, campaign engagement has no
  cross-currency conversion, so there is no FX notebook. Enablement uses only safe sample data and
  needs no production credentials; the real native-connector-versus-managed-connector decision is
  confirmed at the build.
- **Serverless has no continuous streaming.** Auto Loader uses bounded triggers (`availableNow`). A
  file-arrival job trigger starts a bounded run, which is the right shape for daily batch reporting.
- **The sample data has planted defects**, all in Helix's first product-listing week: a resent
  (duplicate) day, untidy tactic labels, a blank campaign_id, a negative lead count, and one row
  where engagements exceed impressions. Bronze dedupe and the silver checks are built to catch
  exactly these.
- **Cost attribution needs tags applied when a job runs.** Notebook 06 reads real billing data, but
  everything built during the session is untagged, so it all lands in one `untagged` bucket. That is
  the lesson rather than a defect: tags cannot be backdated. On Free Edition `system.billing` may
  not be exposed at all, which the notebook handles.
- **The Genie space is not managed by Terraform**, however you create it. Delete it by hand if you
  tear the rest down, or it is left orphaned.

---

## Before the session

[`../../shared/prework.md`](../../shared/prework.md). About ten minutes, and the Free Edition account
signup needs doing ahead of time because it cannot be rushed on the day.
