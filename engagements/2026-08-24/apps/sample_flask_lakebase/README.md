# Sample Flask + Lakebase app

A single-file Flask todo app that runs as a Databricks App, backed by a
Lakebase Autoscaling (Postgres) database. The app creates its own schema and
`todos` table on first request, so there is no separate provisioning notebook.

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

The schema it uses is derived as `{PGAPPNAME}_schema_{PGUSER}`, created on the
first request via `init_database()`.

## Files

| File               | Purpose                                        |
| ------------------ | ---------------------------------------------- |
| `app.py`           | The Flask app (routes, DB access, OAuth conn)  |
| `app.yaml`         | App entrypoint and the `postgres` env mapping  |
| `requirements.txt` | Python dependencies                            |
| `templates/`       | The HTML template for the todo UI              |
