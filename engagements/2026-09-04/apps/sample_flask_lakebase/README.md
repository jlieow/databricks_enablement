# Sample Flask + Lakebase app: patient risk score service

A single-file Flask app that runs as a Databricks App, backed by a Lakebase
Autoscaling (Postgres) database. It is a **read-only internal service**: it
reads the `health_analytics.patient_risk_scores` serving table that the batch
pipeline populates (see `notebooks/09_lakebase_change_data_feed_sync.py`) and
presents the latest scored patient cohort, with a district filter, to the
clinical teams that call it. The app never runs live inference and never writes
clinical data; the batch pipeline is the only writer.

## Prerequisites: provision Lakebase first, then attach it as a `postgres` resource

**This app does not create its database.** Before deploying, you must:

1. **Provision a Lakebase (Postgres) database instance** in your workspace (UI,
   Terraform, or the API — whichever you use).
2. **Declare it as an app resource with the key `postgres`** during app
   deployment, granting `CAN_CONNECT_AND_CREATE` on the branch/database.

The resource key **must** be `postgres`, because `app.yaml` maps the endpoint
from it:

```yaml
command: ["python", "app.py"]
env:
  - name: PGENDPOINT
    valueFrom: postgres   # <-- name of the postgres app resource
```

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
variables. Provision and populate it first with notebook 08.

## Files

| File               | Purpose                                            |
| ------------------ | -------------------------------------------------- |
| `app.py`           | The Flask app (routes, read-only DB access, OAuth) |
| `app.yaml`         | App entrypoint and the `postgres` env mapping      |
| `requirements.txt` | Python dependencies                                |
| `templates/`       | The HTML template for the risk score UI            |
