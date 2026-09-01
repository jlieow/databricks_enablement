# Sample Flask + Lakebase app: patient risk score service

A single-file Flask app that runs as a Databricks App, backed by a Lakebase
Autoscaling (Postgres) database. It is a **read-only internal service**: it
reads the `health_analytics.patient_risk_scores` serving table that the batch
pipeline populates (see `notebooks/09_lakebase_change_data_feed_sync.py`) and
presents the latest scored patient cohort, with a district filter, to the
clinical teams that call it. The app never runs live inference and never writes
clinical data; the batch pipeline is the only writer.

## Prerequisites: provision a Lakebase Autoscaling project, then attach it as a `postgres` resource

**This app does not create its database.** It is written for **Lakebase
Autoscaling** (the `databricks_postgres_*` project/branch/endpoint model), not
the older Provisioned Lakebase instance: `app.py` mints credentials with
`workspace_client.postgres.generate_database_credential(endpoint=PGENDPOINT)`,
which expects the endpoint as `projects/.../branches/.../endpoints/...`. Before
deploying, you must:

1. **Create a Lakebase Autoscaling project** (Terraform `databricks_postgres_project`,
   or `databricks postgres create-project <project-id> --json '{"spec":{"pg_version":16}}'`).
   Creating the project implicitly creates a `production` branch, a `primary`
   read-write endpoint, and a default `databricks_postgres` database.
2. **Point the bundle at it.** This app is packaged as a Databricks Asset Bundle
   (`databricks.yml`), which attaches the database to the app under the resource
   key `postgres` with `CAN_CONNECT_AND_CREATE`. Set the target's
   `postgres_branch` and `postgres_database` variables (they default to
   `PASTE_YOUR_PROJECT_ID` placeholders).

The resource key **must** be `postgres`, because the bundle's `config.env` maps
the endpoint from it. The bundle declares the resource like this:

```yaml
resources:
  apps:
    sample_flask_lakebase:
      resources:
        - name: postgres
          postgres:
            branch: ${var.postgres_branch}      # projects/<id>/branches/production
            database: ${var.postgres_database}  # projects/<id>/branches/production/databases/databricks-postgres
            permission: CAN_CONNECT_AND_CREATE
      config:
        env:
          - name: PGENDPOINT
            value_from: postgres   # <-- endpoint of the postgres app resource
```

> **Two gotchas that cost real time (both verified during deployment):**
>
> - **`config.env` in `databricks.yml` REPLACES the app's `app.yaml` env block,
>   it does not merge.** So the `PGENDPOINT` mapping has to be repeated in
>   `config.env`. Without it the app starts with `PGENDPOINT=""` and every
>   connection fails with `Field 'endpoint' is required`.
> - The bundle field is **`value_from`** (snake_case), not `valueFrom` as in a
>   source `app.yaml`. The bundle silently ignores `valueFrom` and then rejects
>   the env var for having neither `value` nor `value_from`.
>
> The default database's resource id is **`databricks-postgres` (hyphen)** while
> its Postgres database name is **`databricks_postgres` (underscore)** — use the
> hyphen form in the `database` resource path.

The service principal that the app runs as needs read access to the serving
table. Grant it in Postgres (e.g. `GRANT USAGE ON SCHEMA health_analytics`,
`GRANT SELECT ON health_analytics.patient_risk_scores`) to the SP's role, or to
`PUBLIC`.

## Deploy (Databricks Asset Bundle)

```bash
cd dabs/apps/sample_flask_lakebase
profile=<DATABRICKS_PROFILE>
project=<YOUR_PROJECT_ID>
branch="projects/$project/branches/production"
database="projects/$project/branches/production/databases/databricks-postgres"

databricks bundle validate -p $profile
databricks bundle deploy -t dev -p $profile \
  --var="postgres_branch=$branch" --var="postgres_database=$database"
databricks bundle run sample_flask_lakebase -t dev -p $profile \
  --var="postgres_branch=$branch" --var="postgres_database=$database"
```

> **Lakebase is region-gated and not available on Databricks Free Edition in all
> regions.** Deploy this app against a workspace that has a Lakebase Autoscaling
> project; on Free Edition without Lakebase the app deploys but has nothing to
> connect to.

## How the connection works

Attaching the `postgres` resource makes the Apps runtime inject the standard
Postgres connection variables the app reads:

| Variable     | Purpose                                              |
| ------------ | ---------------------------------------------------- |
| `PGENDPOINT` | Lakebase endpoint, used to mint OAuth credentials    |
| `PGHOST`     | Database host                                        |
| `PGPORT`     | Database port                                        |
| `PGDATABASE` | Database name                                        |
| `PGUSER`     | Database user (the app's service principal)          |
| `PGSSLMODE`  | SSL mode (defaults to `require`)                     |
| `PGAPPNAME`  | Application name, used to derive the schema name     |

The app never stores a static password. On each connection it calls
`workspace_client.postgres.generate_database_credential(endpoint=PGENDPOINT)`
to request a short-lived OAuth token, so credentials rotate automatically.

The serving table it reads is `health_analytics.patient_risk_scores` by
default; override with the `SERVING_SCHEMA` and `SERVING_TABLE` environment
variables.

## Where the serving table comes from (populating Lakebase)

The app is a **read-only consumer**. It never creates or writes the serving
table; something else must create `health_analytics.patient_risk_scores` and
populate it *before* the app has anything to show (until then the page renders
"No risk scores found"). There are two ways to get data in:

**1. The real build path: notebook 12.**
`notebooks/12_lakebase_change_data_feed_sync.py` is the source of truth. It
provisions a Lakebase **Autoscaling** project (default id `enablement-lakebase`),
creates the `health_analytics` schema and the `patient_risk_scores` table,
populates it with the batch model's scores, and grants the app read access. In
production this table is kept current by the Lakebase change data feed sync from
the Delta gold layer; the app just reads whatever the batch pipeline last wrote.

Notebook 12 and this app both use the **Autoscaling** model on purpose, so they
interoperate: the notebook creates the `projects/<id>` project and this bundle
attaches to the same project. Notebook 12's Section 1.1 prints the exact
`postgres_branch` and `postgres_database` values to pass to this bundle. (A
Provisioned Lakebase instance would not work here: it does not expose the
`projects/.../branches/.../endpoints/...` endpoint the app mints credentials
against.)

**2. Standalone seed for a demo or test.**
To exercise the app on its own, create the table on the Autoscaling project's
`production` branch and insert a few rows directly. Get the host from
`databricks postgres get-endpoint projects/<id>/branches/production/endpoints/primary`
and a token from `databricks postgres generate-database-credential
projects/<id>/branches/production/endpoints/primary`, then with `psql`:

```sql
CREATE SCHEMA IF NOT EXISTS health_analytics;
CREATE TABLE IF NOT EXISTS health_analytics.patient_risk_scores (
  patient_id text, district_id text, risk_score double precision,
  risk_category text, model_version text, scored_at timestamptz, last_updated timestamptz);
INSERT INTO health_analytics.patient_risk_scores VALUES
  ('P-1001','northmoor_district',0.92,'high','risk_v3', now(), now()),
  ('P-2001','eldervale_district',0.88,'high','risk_v3', now(), now());
-- The app's service principal must be able to read it:
GRANT USAGE ON SCHEMA health_analytics TO PUBLIC;
GRANT SELECT ON health_analytics.patient_risk_scores TO PUBLIC;
```

Connect as `dbname=databricks_postgres user=<your-email> sslmode=require` with the
token as the password. This is exactly how the bundle was verified end to end.

## Files

| File               | Purpose                                            |
| ------------------ | -------------------------------------------------- |
| `databricks.yml`   | Asset Bundle: declares the app + `postgres` resource, dev/prod targets |
| `app.py`           | The Flask app (routes, read-only DB access, OAuth) |
| `app.yaml`         | App entrypoint and the `postgres` env mapping      |
| `requirements.txt` | Python dependencies                                |
| `templates/`       | The HTML template for the risk score UI            |
