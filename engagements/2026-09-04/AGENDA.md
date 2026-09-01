# Health Analytics Enablement: which file goes with which agenda item

Everything here is a **completed reference copy**. We build these live and from scratch during the
session; use these to catch up if you fall behind, and to refer back to afterwards.

This enablement prepares the team to run the POC by practising the build patterns on safe sample data.
It is a focused all-day hands-on workshop, not a full platform demo. The team is new to Databricks
but strong on data, cloud, and machine learning fundamentals, so the time goes on Databricks specifics
and gotchas, not on data or machine learning basics.

The scenario mirrors the team's real work: patient encounter data and clinical intelligence for two
fictional health districts, across three clinical data **streams** (outpatient visits, inpatient
admissions, lab results), consolidated through Bronze, Silver, Gold into an internal clinical
analytics platform. Batch model serving to a PostgreSQL database feeds a Databricks App, Genie, and
dashboards. All four AI workstreams (classical risk model, clinical-note extraction, academic
literature retrieval, dashboard summaries) run on one platform. No live sources and no production
credentials. Safe synthetic data and clinical-note text only.

---

## Morning Session: Data foundations and generative extraction (about three hours)

| # | Agenda item | Files |
| --- | --- | --- |
| 1 | Workspace, Unity Catalog, and medallion foundations | `notebooks/01_foundations.py` |
| 2 | Ingesting clinical data with Auto Loader | `notebooks/02_ingest_encounters_autoloader.py` |
| 3 | Silver to Gold: dedupe, validate, clinical metrics | `notebooks/03_medallion_transform.py` |
| — | Onboarding a second health district with no code change | `notebooks/04_template_reuse.py` |
| 4 | Extracting structured data from clinical notes with AI functions | `notebooks/05_clinical_note_extraction.py` |
| 5 | Packaging with Databricks Asset Bundles | `docs/asset_bundles_guide.md`, `dabs/jobs/sample_encounters_job/`, `dabs/apps/sample_flask_lakebase/` |

Notes on the mapping:

- **Notebook 02 ingests one district, not both.** It takes `district_id` as a widget, defaulting to
  `northmoor_district`. The second district (`eldervale_district`) is onboarded in notebook 04, which
  calls 02 and 03 unchanged with a different `district_id`. That is the point of 04: onboarding is
  configuration, not new code.
- **Notebook 05 (clinical extraction) is a new notebook**, not the template reuse. It uses built-in
  AI functions (`ai_extract`, `ai_classify`, `ai_parse_document`) on synthetic clinical-note text to
  produce structured fields. The template reuse that onboards the second district (`04_template_reuse`)
  is the separate "onboarding" step between items 3 and 4 listed above.
- **Item 5 has a walkthrough guide plus two runnable Asset Bundles** under `dabs/`. The guide
  (`docs/asset_bundles_guide.md`) teaches the shape; the bundles are working reference deployments the
  team can `databricks bundle deploy` themselves: `dabs/jobs/sample_encounters_job/` (a two-task
  serverless ingest -> transform job that also creates its Unity Catalog catalog and schema) and
  `dabs/apps/sample_flask_lakebase/` (the risk-score Databricks App from item 8, packaged as a bundle
  with its Lakebase `postgres` resource). Each bundle has its own README. The job bundle needs
  `DATABRICKS_BUNDLE_ENGINE=direct` because it declares a catalog resource; the app bundle needs a
  Lakebase Autoscaling project to attach to.

---

## Afternoon Session: Machine learning lifecycle, serving, and governance (about three hours)

The model group runs as a clean lifecycle: **06** train → **07** champion/challenger promotion → **08**
serve → **09** query the served model → **10** build/serve/trace an agent → **11** query the agent and
see its traces.

| # | Agenda item | Files |
| --- | --- | --- |
| 6 | Model training and the MLflow lifecycle | `notebooks/06_mlflow_train_risk_model.py` |
| 7 | Champion/challenger tagging and promotion | `notebooks/07_register_batch_score.py` |
| — | Optional: serve the risk model on a real-time endpoint, then query it | `notebooks/08_model_serving_endpoint.py`, `notebooks/09_query_risk_model_endpoint.py` |
| — | Optional: build/serve/trace a tool-calling agent, then query it | `notebooks/10_build_traced_agent.py`, `notebooks/11_query_traced_agent.py` |
| 8 | Serving path: batch to PostgreSQL to a Databricks App | `notebooks/12_lakebase_change_data_feed_sync.py` |
| 9 | Academic-literature retrieval with a Genie agent | `notebooks/13_academic_rag_genie_agent.py`, `docs/academic_rag_guide.md` |
| 10 | Dashboard situation summaries and Genie over Gold | `data/district_health.lvdash.json`, `notebooks/15_dashboard_and_summaries.py`, `docs/genie_space_guide.md`, `notebooks/14_genie_space_gold.py` |
| 11 | Unity AI gateway: LLM governance and cost | `docs/ai_gateway_guide.md` |

Notes:

- **Item 6 (notebook 06) uses the scikit-learn breast-cancer dataset** (a clinical binary classifier)
  reframed as risk stratification on CPU. Teaching data only, not a clinical tool. Trained with MLflow,
  logged, registered in Unity Catalog, and timestamped so repeated runs build a version history.
- **Item 7 (notebook 07) is champion/challenger tagging and promotion.** It picks the current
  challenger (the latest registered version), sets/moves the `champion` alias with the MLflow client,
  and covers monthly retrain and drift monitoring. It also batch-scores a reference cohort with the
  `@champion` model to show the no-live-inference pattern the build uses.
- **Notebook 08 (serve) is optional and sits between items 7 and 8.** It deploys the `@champion` model
  to a real-time endpoint with an AI Gateway inference table for request/response capture, for the case
  where request-time scoring is later needed. **Notebook 09 (query)** then sends the endpoint a scoring
  request and shows the captured rows in the inference table. Not part of the batch serving path this
  build uses; see the optional-worked-examples note below. Kept next to 06/07 because they are the model
  group.
- **Notebooks 10 and 11 (traced agent) are the agent counterpart to 08/09, also optional.** Notebook 10
  builds a small tool-calling clinical triage agent (two traced tools over a Foundation Model API
  model), registers it in Unity Catalog, and serves it with `databricks.agents.deploy`, which turns on
  MLflow tracing and wires an MLflow experiment for near-real-time traces; notebook 11 queries the
  endpoint and reads the traces back. Where 08/09 use request/response capture because a classical
  classifier has nothing internal to trace, 10 and 11 are the case where tracing earns its place: each
  request is a span tree (agent, model call, tool calls, final model call). Like 08/09 they are a
  reference pattern, not this build's serving path, and they are guarded: Model Serving is not on Free
  Edition, so the deploy and live-query steps skip cleanly, while notebook 10's local agent run still
  produces a trace inline wherever the Foundation Model API is reachable.
- **Item 8 is Lakebase change-data-feed sync** (notebook 12), setting up Postgres to Delta sync with
  `REPLICA IDENTITY FULL`. Teaches the operational table pattern the app reads from. Note: managed
  Postgres autoscaling is region-gated and not available on Free Edition in all regions.
- **Item 9 uses a Genie agent over documents in a volume** (notebook 13), not the deprecated Knowledge
  Assistant. Teaches curation, RAG accuracy, and document quality as foundational. Includes 3-5
  synthetic research abstract files under `data/research_abstracts/`.
- **Item 10 is built in the UI.** The dashboard is `.lvdash.json` imported via **Dashboards > Import**.
  The Genie space is built by hand following the guide. Notebook 14 is a fallback API build over the
  consolidated `gold_all_districts_master` table. Notebook 15 aggregates the same table for the
  dashboard and generates the AI situation summaries (with a graceful fallback if AI functions are off).
- **Item 11 is documentation walkthrough only.** The AI gateway is region-gated; it is taught as a
  reference pattern rather than deployed in this session.

---

## Optional worked examples and buffer (use only if time allows)

| Topic | Files |
| --- | --- |
| Governance foundation: row-level security worked example | `notebooks/16_row_level_security.py` |
| Real-time serving: serve the risk model, then query it (optional capability) | `notebooks/08_model_serving_endpoint.py`, `notebooks/09_query_risk_model_endpoint.py` |
| Traced tool-calling agent: build/serve/trace, then query (optional capability) | `notebooks/10_build_traced_agent.py`, `notebooks/11_query_traced_agent.py` |
| Overflow / second pass on anything that ran short | (whichever notebook or guide) |

Notes:

- **Notebooks 08 and 09 are an optional capability, not part of the batch serving path.** This build
  serves scores in batch (07 promotes and batch-scores, 12 writes to PostgreSQL, the app reads).
  Notebook 08 deploys the `@champion` model to a real-time endpoint with an inference table that
  captures every request and response to a governed Delta table for audit and drift monitoring; notebook
  09 queries it and shows those rows. Model Serving is not on Free Edition and is region-gated, so both
  check availability and exit cleanly where it is not reachable. Run them on the client's own workspace,
  not in the workshop. They are numbered next to the model group (06 train, 07 promote, 08 serve, 09
  query).
- **Notebooks 10 and 11 are the agent counterpart to 08/09, also optional and standalone.** They build,
  serve, and query a traced tool-calling agent with `agents.deploy` rather than a classical model, to
  show where MLflow tracing earns its place (a multi-step agent produces a span tree; a classifier does
  not). Notebook 10 registers its own agent model (`enablement.05_ops.clinical_triage_agent`) and
  deploys it; notebook 11 queries it and reads the traces back. Neither depends on 06/07. Same
  availability guard as 08/09: the deploy and live-query steps need Model Serving and skip cleanly on
  Free Edition, but notebook 10's local agent run still produces a trace wherever the Foundation Model
  API is reachable. Two gotchas they carry: the served agent needs a secret-backed personal access token
  to reach the pay-per-token Foundation Model API (the runtime credential fails with `USE CATALOG on
  system`), and `agents.deploy` rejects a catalog name that starts with an underscore.

---

## Setup

The notebooks assume this structure, which notebook 01 walks through creating:

| Object | Name |
| --- | --- |
| Catalog | `enablement` |
| Schemas | `01_raw`, `02_bronze`, `03_silver`, `04_gold`, `05_ops` |
| Volumes | `01_raw.landing`, `01_raw.checkpoints`, `01_raw.research_abstracts` |

Upload the seed CSVs from `data/landing/<district>/` to
`/Volumes/enablement/01_raw/landing/<district>/`, one folder per district:

- `northmoor_district/`
- `eldervale_district/`

Upload the research abstracts from `data/research_abstracts/` to
`/Volumes/enablement/01_raw/research_abstracts/`.

Catalog and schema names are literals in these notebooks rather than parameters, so they run as-is.
To use different names, edit the constants near the top of each notebook.

**Notebook 14 needs your own SQL warehouse id.** It is set to `PASTE_YOUR_WAREHOUSE_ID`; replace it
with the id from **SQL Warehouses** in your workspace.

---

## Running order

Almost the agenda order, because each notebook reads tables the earlier ones create.

| Order | Notebook | Why here |
| --- | --- | --- |
| 1 | `01_foundations` | Creates the catalog, schemas and volumes everything else needs |
| 2 | `02_ingest_encounters_autoloader` | Raw tables for the first district (`northmoor_district`) |
| 3 | `03_medallion_transform` | Bronze, silver and gold for the first district |
| 4 | `04_template_reuse` | Onboards `eldervale_district`, builds `gold_all_districts_master` |
| 5 | `05_clinical_note_extraction` | AI functions on synthetic clinical notes; standalone, no dependency on 01-03 |
| 6 | `06_mlflow_train_risk_model` | Classical risk model training; standalone, uses built-in dataset |
| 7 | `07_register_batch_score` | Promotes the champion from 06, batch-scores the reference cohort (depends on 06) |
| 8 | `12_lakebase_change_data_feed_sync` | Postgres sync; standalone, no dependency on the medallion tables |
| 9 | `13_academic_rag_genie_agent` | Genie agent over research abstracts; standalone |
| 10 | `14_genie_space_gold` | **Optional.** Only if you want the space built for you instead of in the UI. Reads `gold_all_districts_master` from 04 |
| 11 | `15_dashboard_and_summaries` | Aggregates `gold_all_districts_master` for the dashboard; generates AI situation summaries (graceful fallback). Reads the consolidated table from 04 |
| 12 | `16_row_level_security` | **Optional worked example.** Reads the consolidated table from 04 |
| — | `08_model_serving_endpoint` | **Optional capability, standalone.** Serves the `@champion` model from 07 on a real-time endpoint with an inference table. Not on Free Edition; run on the client's workspace |
| — | `09_query_risk_model_endpoint` | **Optional capability.** Queries the endpoint 08 deploys and shows the inference table. Run after 08; needs Model Serving |
| — | `10_build_traced_agent` | **Optional capability, standalone.** Builds, registers, and (where serving is available) deploys a traced tool-calling agent with `agents.deploy`. The local traced run works anywhere; deploy needs Model Serving (not on Free Edition) and skips cleanly |
| — | `11_query_traced_agent` | **Optional capability.** Queries the endpoint 10 deploys and reads the traces back. Run after 10; needs Model Serving |

Ordering traps:

- **Upload the CSVs before running 02.** Notebook 01 creates the landing folders, but the files
  have to be uploaded before Auto Loader has anything to read. Same for research abstracts in 01.
- **04 calls notebooks 02 and 03.** So all three must sit in the same folder. Do not shortcut
  onboarding by re-running 02 with the widget changed; running 04 is the point.
- **The dashboard reads `gold_all_districts_master`**, which notebook 04 builds. Import the dashboard
  after 04 has run.
- **Re-run 04 after anything that changes a district's gold table**, and re-run 16 after 04. Both
  take point-in-time copies that do not auto-update.
- **Notebook 07 depends on 06.** If you skip 06, skip 07 or set up the model manually first.
- **Notebook 06 stamps each run with `trained_at`.** Run it more than once to build a real version
  history; notebook 07 then promotes the newest version to `champion`. Running 06 twice, then 07, is
  the clean way to show promotion moving the alias.
- **Notebook 08 depends on 07 having set the champion alias**, and notebook 09 depends on 08 having
  deployed the endpoint. All need Model Serving, which is not on Free Edition; they check availability
  and exit cleanly where serving is unreachable.
- **Notebook 11 depends on notebook 10** having deployed the endpoint, and both need Model Serving.
  Notebook 10's local agent run (its Section 3) is the part that works on Free Edition; the deploy and
  the query in 11 are for the client's workspace.

---

## Things worth knowing

**Data and clinical context:**

- The sample data has **planted defects**, all designed to be caught by quality checks:
  - One blank patient_id in outpatient_visits week 1 (northmoor_district) -> caught by missing_key check
  - One negative length_of_stay_days (-1) in inpatient_admissions week 1 -> caught by negative_values check
  - One duplicate lab_result on 2026-07-03 (northmoor_district) -> caught by QUALIFY dedupe
  - One row where readmission_count > total_encounters in inpatient_admissions -> caught by logical_conflict check
  - Untidy admission_status values (Active, active, ACTIVE) -> caught by LOWER/TRIM in Silver
- **Three clinical streams.** Each district's CSV files are prefixed `outpatient_visits__`, `inpatient_admissions__`,
  `lab_results__`, one per week. Auto Loader discovers them and ingests each into its own raw table.
- **Clinical gold metrics** computed once in the gold layer: encounter_count, avg_length_of_stay,
  readmission_rate_pct (readmission_count / total_encounters * 100), abnormal_lab_rate_pct.

**Databricks specifics:**

- **Notebook 02 ingests one district, not both.** It takes `district_id` as a widget, defaulting to
  `northmoor_district`. The second district is onboarded in notebook 04, which calls 02 and 03
  unchanged with a different `district_id`. That is the point: onboarding is configuration, not code.
- **No FX, no currency, no live API.** Clinical data has no cross-currency conversion, so no FX
  notebook. Enablement uses only safe sample data and needs no production credentials.
- **Serverless has no continuous streaming.** Auto Loader uses bounded triggers (`availableNow`). A
  file-arrival job trigger starts a bounded run, which is the right shape for daily batch anyway.
- **Cost attribution needs tags applied when a job runs.** If cost visibility is enabled on the
  customer's workspace (not on Free Edition), anything built untagged lands in one `untagged` bucket.
  That is the lesson rather than a defect: tags cannot be backdated.
- **The Genie space is not managed by Terraform**, however you create it. Delete it by hand if you
  tear the rest down, or it is left orphaned.
- **A Model Serving endpoint (notebook 08) is also not torn down for you.** If you create one, delete
  it by hand, or it lingers. It scales to zero so an idle one is cheap, but it is still there. Its
  inference table (`enablement.05_ops.patient_risk_stratification_model_payload`) stays too, and is
  worth keeping: it is the request/response audit trail and the source the drift-monitoring queries
  read.
- **Tracing versus request/response capture: match it to what you serve.** Notebooks 08/09 serve a
  classical classifier and use an inference table, because a classifier has no internal steps to
  trace. Notebooks 10 and 11 serve a multi-step tool-calling agent and use MLflow tracing via
  `agents.deploy`, because each request is a span tree (agent, model call, tool calls, final answer)
  worth seeing. `agents.deploy` also wires an MLflow experiment for near-real-time traces rather than
  the best-effort inference table. That agent endpoint (`clinical-triage-agent`) and its payload table
  are not torn down for you either; delete the endpoint by hand. This mirrors the `serving_traced_agent`
  terraform demo the two notebooks are based on.
- **AI functions may not be available in all regions.** `ai_extract`, `ai_classify`, `ai_parse_document`
  may not be enabled depending on region and workspace settings. Notebooks handle absence gracefully
  with a clear message and deterministic fallback.
- **Notebook 12 uses Lakebase Autoscaling, to match the app.** It provisions a Lakebase Autoscaling
  project (`projects/<id>` with a `production` branch and `primary` endpoint), creates and populates
  `health_analytics.patient_risk_scores`, and the Databricks App attaches to that same project. Both
  use the Autoscaling model deliberately: a Provisioned instance does not expose the
  `projects/.../endpoints/...` endpoint the app mints credentials against. **Autoscaling is
  region-gated and may not be available on Free Edition in all regions**, so this serving-to-Postgres
  step is the one part of the workshop that needs a workspace and region offering Lakebase; the rest
  runs on Free Edition. Verified end to end: notebook 12 populated the table and the app rendered it.
- **Genie agent availability in some regions is unconfirmed.** Notebook 13 teaches the pattern; if
  the workspace region does not support it, the notebook exits with a clear message.

---

## Before the session

[`../../shared/prework.md`](../../shared/prework.md). About ten minutes. Free Edition account signup
cannot be rushed on the day, so do it ahead of time.
