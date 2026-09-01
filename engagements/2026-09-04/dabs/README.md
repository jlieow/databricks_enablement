# Databricks Asset Bundles (DABs) for this engagement

This folder holds the runnable Databricks Asset Bundles for agenda item 5
(Packaging with Databricks Asset Bundles). Each subfolder is a self-contained
bundle you deploy with the Databricks command line interface (CLI):

| Bundle | What it is | Deploys |
| --- | --- | --- |
| `jobs/sample_encounters_job/` | Two-task serverless job (ingest then transform) that also creates its own Unity Catalog catalog and schema | A Unity Catalog catalog + schema and a two-task job |
| `apps/sample_flask_lakebase/` | The risk-score Databricks App (agenda item 8), packaged as a bundle with its Lakebase `postgres` resource | A Databricks App bound to a Lakebase Autoscaling database |

Each bundle has its own README with the full detail; this file is the shared
quick start. See also `../docs/asset_bundles_guide.md` for the concepts.

## Prerequisites

1. **Databricks CLI** v0.240 or newer (`databricks --version`).
2. **An authenticated profile.** Everything below uses `-p <PROFILE>`; set your
   profile once with `export DATABRICKS_CONFIG_PROFILE=<PROFILE>` if you prefer
   not to repeat the flag. Confirm it with `databricks current-user me -p <PROFILE>`.
3. **Serverless compute and Unity Catalog** enabled on the target workspace.
4. For the app only: a **Lakebase Autoscaling project** to attach to (see below).

Every command uses the bundle's `dev` target by default. Add `-t prod` to deploy
the production variant (larger data / real schedule for the job; a separate app
name for the app).

## First-time setup: which command deploys what

`databricks bundle deploy` creates or updates the resources; `databricks bundle
run <resource>` runs the job or starts the app. `databricks bundle validate`
checks the definition without deploying.

---

## Jobs bundle: `jobs/sample_encounters_job`

The job declares a Unity Catalog **catalog** resource, which requires the
`direct` deployment engine (a preview). Set it for every `bundle` command that
touches this bundle:

```bash
cd jobs/sample_encounters_job
export DATABRICKS_BUNDLE_ENGINE=direct
profile=<PROFILE>

databricks bundle validate -p $profile
databricks bundle deploy   -p $profile            # creates catalog + schema + job
databricks bundle run sample_encounters_job -p $profile

# Production variant (daily schedule on, larger row_count, prod schema):
databricks bundle deploy -t prod -p $profile
databricks bundle run sample_encounters_job -t prod -p $profile
```

After a run, the output tables are in Catalog Explorer under the catalog and
schema the bundle created (in dev, `enablement_dabs_demo.dev_<you>_encounters`):
`encounters_raw` (from `ingest`) and `encounters_by_district` (from `transform`).

Tear down (the bundle does not own the tables the job wrote, so drop them first):

```bash
cd jobs/sample_encounters_job
export DATABRICKS_BUNDLE_ENGINE=direct
databricks tables delete enablement_dabs_demo.dev_<you>_encounters.encounters_raw
databricks tables delete enablement_dabs_demo.dev_<you>_encounters.encounters_by_district
databricks bundle destroy -p $profile
```

---

## App bundle: `apps/sample_flask_lakebase`

This app connects to **Lakebase Autoscaling** (the project / branch / endpoint
model). Create a project first, then point the bundle at it with two variables.

```bash
profile=<PROFILE>

# 1. Create a Lakebase Autoscaling project (implicitly creates a production
#    branch, a primary endpoint, and a default databricks_postgres database).
databricks postgres create-project my-enablement-pg \
  --json '{"spec":{"pg_version":16}}' -p $profile

# 2. Build the two resource paths the app resource needs. Note the default
#    database's resource id is databricks-postgres (hyphen), while its Postgres
#    database name is databricks_postgres (underscore).
project=my-enablement-pg
branch="projects/$project/branches/production"
database="projects/$project/branches/production/databases/databricks-postgres"

# 3. Deploy and start the app.
cd apps/sample_flask_lakebase
databricks bundle validate -p $profile \
  --var="postgres_branch=$branch" --var="postgres_database=$database"
databricks bundle deploy -t dev -p $profile \
  --var="postgres_branch=$branch" --var="postgres_database=$database"
databricks bundle run sample_flask_lakebase -t dev -p $profile \
  --var="postgres_branch=$branch" --var="postgres_database=$database"
```

The app is read-only and does **not** create its serving table
`health_analytics.patient_risk_scores`. Populate it first by running
`notebooks/12_lakebase_change_data_feed_sync.py` (agenda item 8), which
provisions a Lakebase **Autoscaling** project, creates and populates the table,
and grants the app read access. That notebook prints the exact `postgres_branch`
and `postgres_database` values to pass to this bundle, so the two attach to the
same project. Until the table has rows the page renders "No risk scores found".
See the app bundle's README section **"Where the serving table comes from"** for
detail and a standalone seed recipe. To watch the app:
`databricks apps logs sample-flask-lakebase-dev -p $profile`.

Tear down:

```bash
cd apps/sample_flask_lakebase
databricks bundle destroy -t dev -p $profile \
  --var="postgres_branch=$branch" --var="postgres_database=$database"
databricks postgres delete-project my-enablement-pg -p $profile
```

> **Two portability gotchas, verified while preparing this material:**
> a bundle's `config.env` **replaces** the app's `app.yaml` env block (it does
> not merge), so the `PGENDPOINT` mapping is repeated in `databricks.yml`; and
> the bundle field is **`value_from`** (snake_case), not `valueFrom`.

---

## Notes for this engagement

- **Free Edition.** Serverless jobs and Unity Catalog run on Free Edition.
  Lakebase is region-gated and may not be available there, so the app bundle
  needs a workspace with a Lakebase Autoscaling project; the rest of the
  material still runs on Free Edition.
- **Fictional data only.** The seed data is synthetic patient-encounter data for
  two fictional health districts. No real or identifying data appears anywhere.
- Both bundles were deployed and run end to end while preparing this material.
