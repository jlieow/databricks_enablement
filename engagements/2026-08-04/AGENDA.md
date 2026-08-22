# Which file goes with which agenda item

Everything here is a **completed reference copy**. We build these live and from scratch during
the session; use these to catch up if you fall behind, and to refer back to afterwards.

Agenda item numbers and notebook numbers match. The two Part 2 items with no notebook, Designer
and dashboards, come last.

---

## Part 1: building the pipeline (Python)

| # | Agenda item | Files |
| --- | --- | --- |
| 1 | Auto Loader pulling files from a volume, and a job that fires when a new file lands | `notebooks/01_raw_ingest_autoloader.py` |
| 2 | Where credentials live, and which mechanism to use where | `notebooks/02_credentials_and_secrets.py` |
| 3 | Pulling data from an API into a raw table | `notebooks/03_raw_ingest_api.py` |
| 4 | Raw to bronze to silver to gold: dedupe, quality checks, currency conversion | `notebooks/04_medallion_transform.py` |
| 5 | Turning it into a reusable template, then onboarding a second client with no code changes | `notebooks/05_template_reuse.py` |

Also relevant to Part 1:

- `data/landing/` — the seed CSVs. One file per platform per weekly reporting window.

---

## Part 2: operating it (no Python needed)

| # | Agenda item | Files |
| --- | --- | --- |
| 6 | Row level security, so each team only sees the clients they are entitled to | `notebooks/06_row_level_security.py` |
| 7 | Cost visibility per client | `notebooks/07_cost_visibility.py` |
| 8 | Genie, and how to check whether its answers are actually right | `docs/genie_space_guide.md`, `notebooks/08_genie_space.py` |
| 9 | Lakeflow Designer, building transformations visually instead of in code | `docs/lakeflow_designer_guide.md` |
| 10 | Dashboards | `data/client_performance.lvdash.json` |

Three things to know about Part 2:

- **Items 9 and 10 have no notebook, on purpose.** Both are UI work. The Designer guide walks the
  screens, and it builds the same silver-to-gold transformation that notebook 04 does in code.
- **Item 10 is a file, not a notebook.** Import
  `data/client_performance.lvdash.json` via **Dashboards > Create dashboard > ... > Import
  dashboard from file**. Three pages: Performance, Data Quality, Cost. It needs gold to exist
  first, and the Cost page needs notebook 07 to have run.
- **Item 8 is done in the UI.** We build the Genie space by hand following
  `docs/genie_space_guide.md`, because the curation *is* the work and doing it manually is what
  makes that obvious. That is also what you will do for each new client.
  `notebooks/08_genie_space.py` is a **fallback**: it builds the same space over the REST API if
  you would rather not follow the UI steps, or want to catch up. You do not need to run it. It is
  the one Part 2 notebook containing real Python, and it needs your own SQL warehouse id
  (see below).

---

## Setup

The notebooks assume this structure, which the session walks through creating:

| Object | Name |
| --- | --- |
| Catalog | `enablement` |
| Schemas | `01_raw`, `02_bronze`, `03_silver`, `04_gold`, `05_ops` |
| Volumes | `01_raw.landing`, `01_raw.checkpoints` |
| Secret scope | `enablement_demo`, keys `api_token_via_cli` and `api_token_via_py_sdk` |

Upload the seed CSVs from `data/landing/<client>/` to
`/Volumes/enablement/01_raw/landing/<client>/`.

Catalog and schema names are literals in these notebooks rather than parameters, so they run
as-is. To use different names, edit the constants near the top of each notebook.

**Notebook 08 needs your own SQL warehouse id.** It is set to `PASTE_YOUR_WAREHOUSE_ID`; replace
it with the id from **SQL Warehouses** in your workspace.

---

## Running order

Almost the agenda order, because each notebook reads tables the earlier ones create. Each one
fails with the name of the notebook to run rather than a raw `TABLE_OR_VIEW_NOT_FOUND`, so getting
this wrong is recoverable.

| Order | Notebook | Why here |
| --- | --- | --- |
| 1 | `01_raw_ingest_autoloader` | Raw tables. Everything downstream needs these |
| 2 | `03_raw_ingest_api` | FX rates. Notebook 04 needs these to convert spend |

**Before running 03, check its two date widgets cover your ad data.** They default to 2026-06-24 to
2026-07-22, which matches the seed CSVs with a lead-in. FX only exists for trading days, so the
lead-in gives the first few days of July a rate to carry forward from. Get this wrong and gold still
builds, but the rows outside the FX range get no rate and their USD spend is null.

| 3 | `04_medallion_transform` | Bronze, silver and gold, with FX applied |
| 4 | `05_template_reuse` | The second client. Calls 01 and 04 again |
| 5 | `06_row_level_security` | The consolidated tables the dashboard reads |
| 6 | `07_cost_visibility` | Populates the dashboard's Cost page |
| 7 | `08_genie_space` | **Optional.** Only if you want the space built for you instead of building it in the UI |
| 8 | `02` | Standalone, any time |

Three ordering traps:

- **03 before 04.** Notebook 04 joins the `fx_daily_rates` table that 03 builds, so run 03 first or
  gold has no rates to convert with.
- **Re-run 06 after anything that changes gold.** It takes point-in-time *copies* into
  `gold_all_clients_master_filtered` and `..._unfiltered`. The dashboard reads the filtered one, and
  neither auto-updates.
- **05 calls notebooks 01 and 04.** So all three must sit in the same folder, which is how they are
  distributed.

---

## Things worth knowing

- **Notebook 01 ingests one client, not both.** It takes `client_id` as a widget, defaulting to
  `northwind_retail`. The second client (`contoso_travel`) is onboarded in notebook 05, which calls
  notebooks 01 and 04 unchanged with a different `client_id`. That is the point of 05: onboarding is
  configuration, not new code. Do not shortcut it by re-running 01 with the widget changed.
- **Serverless has no continuous streaming.** Auto Loader uses bounded triggers
  (`availableNow`). A file-arrival job trigger starts a bounded run, which is the right shape for
  daily batch anyway.
- **Notebook 03 calls a live third-party API.** Frankfurter needs no signup, which is why it is
  used, but it does occasionally return a 5xx. The notebook raises rather than writing an empty
  table, so if it fails, re-run the cell.
- **Cost attribution needs tags applied when a job runs.** Notebook 07 reads real billing data,
  but everything built during the session is untagged, so it all lands in one `untagged` bucket.
  That is the lesson rather than a defect: tags cannot be backdated.
- **Unity Catalog secrets need DBR 17.3 LTS+ or serverless environment version 4+** for the
  `catalog=` / `schema=` read. Notebook 02 creates one and reads it back. A workspace secret scope
  has no runtime floor, so prefer a scope when the compute is uncertain.
- **The Genie space is not managed by Terraform**, however you create it. Delete it by hand if
  you tear the rest down, or it is left orphaned.

---

## Before the session

[`../../shared/prework.md`](../../shared/prework.md). About ten minutes, and the Free Edition account signup needs doing ahead of
time because it cannot be rushed on the day.
