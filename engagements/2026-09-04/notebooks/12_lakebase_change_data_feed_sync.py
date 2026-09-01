# Databricks notebook source
# MAGIC %md
# MAGIC # 12. Lakebase change data feed sync: batch serving to PostgreSQL
# MAGIC
# MAGIC This notebook sets up a **Lakebase change data feed sync**, so that clinical data and model
# MAGIC scores flow from Delta into a PostgreSQL operational table that the Databricks App reads.
# MAGIC
# MAGIC ### How the sync works
# MAGIC Lakebase change data feed streams row-level changes from Postgres into Unity Catalog Delta tables,
# MAGIC or vice versa: Delta changes sync back into Postgres. We use this for batch model serving: the risk
# MAGIC model scores a batch of patients and writes to Postgres, which the App queries.
# MAGIC
# MAGIC ### This notebook uses Lakebase Autoscaling
# MAGIC Lakebase comes in two shapes: the older **Provisioned** instance and the current **Autoscaling**
# MAGIC project. This notebook uses **Autoscaling** because the Databricks App
# MAGIC (`dabs/apps/sample_flask_lakebase`) connects that way, and the two must match for the app to read
# MAGIC the table this notebook populates. An Autoscaling project is a `projects/<id>` resource with a
# MAGIC `production` branch, a `primary` endpoint, and a default `databricks_postgres` database. Credentials
# MAGIC are minted per endpoint (`projects/<id>/branches/<branch>/endpoints/<endpoint>`), not per instance.
# MAGIC
# MAGIC ### One requirement: REPLICA IDENTITY FULL
# MAGIC For the feed to capture **updates** and **deletes** accurately, Postgres needs to log the full
# MAGIC *before-image* of each changed row. Postgres does not do this by default, so you tell it to
# MAGIC per table:
# MAGIC
# MAGIC ```sql
# MAGIC ALTER TABLE patient_risk_scores REPLICA IDENTITY FULL;
# MAGIC ```
# MAGIC
# MAGIC This is a required setup step for **every table** you want to sync. The cost is a little extra
# MAGIC write-ahead-log volume on updates and deletes, which is negligible for most operational tables.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1: Prerequisites & setup
# MAGIC
# MAGIC Lakebase is Databricks-managed Postgres. We talk to it with the Databricks SDK and SQLAlchemy.
# MAGIC The Lakebase Autoscaling control-plane API is a preview, so we call it over REST through the
# MAGIC SDK's `api_client`; that keeps this notebook working regardless of the exact SDK version.

# COMMAND ----------

# MAGIC %pip install SQLAlchemy "psycopg[binary]"
# MAGIC %pip install --upgrade databricks-sdk
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1.1: Configuration

# COMMAND ----------

# Lakebase Autoscaling identifiers. Creating the project implicitly creates the
# production branch, the primary endpoint, and the default database below.
PROJECT_ID    = "enablement-lakebase"   # Lakebase Autoscaling project id
BRANCH_ID     = "production"
ENDPOINT_ID   = "primary"
PG_VERSION    = 16

DATABASE_NAME = "databricks_postgres"
SCHEMA_NAME   = "health_analytics"
TABLE_NAME    = "patient_risk_scores"

UC_CATALOG    = "enablement"
UC_SCHEMA     = "05_ops"

POSTGRES_PORT = 5432

# Resource paths the Autoscaling API and the app resource use.
BRANCH_PATH   = f"projects/{PROJECT_ID}/branches/{BRANCH_ID}"
ENDPOINT_PATH = f"{BRANCH_PATH}/endpoints/{ENDPOINT_ID}"
# The default database's resource id is `databricks-postgres` (hyphen), while its
# Postgres database name is `databricks_postgres` (underscore). The app's
# postgres resource takes the hyphen form.
DATABASE_PATH = f"{BRANCH_PATH}/databases/databricks-postgres"

print("Configuration")
print("=" * 70)
print(f"Project:       {PROJECT_ID}")
print(f"Branch path:   {BRANCH_PATH}")
print(f"Endpoint path: {ENDPOINT_PATH}")
print(f"Database:      {DATABASE_NAME}")
print(f"Table:         {SCHEMA_NAME}.{TABLE_NAME}")
print(f"Synced to:     {UC_CATALOG}.{UC_SCHEMA}.{TABLE_NAME}")
print("=" * 70)
print("App binding (set these on dabs/apps/sample_flask_lakebase):")
print(f"  postgres_branch   = {BRANCH_PATH}")
print(f"  postgres_database = {DATABASE_PATH}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: Provision the Lakebase Autoscaling project
# MAGIC
# MAGIC Creating the project can take a minute. Reusing an existing one is safe. We wait until the
# MAGIC primary endpoint is `ACTIVE`, then read its host.

# COMMAND ----------

import time
from databricks.sdk import WorkspaceClient

workspace_client = WorkspaceClient()


def pg_api(method, path, **kwargs):
    """Call the Lakebase (preview) REST API through the SDK's api_client."""
    return workspace_client.api_client.do(method, path, **kwargs)


# Create the project if it does not already exist.
try:
    pg_api("GET", f"/api/2.0/postgres/projects/{PROJECT_ID}")
    print(f"Reusing existing project: {PROJECT_ID}")
except Exception:
    print(f"Creating project '{PROJECT_ID}' (this can take a minute)...")
    pg_api(
        "POST",
        "/api/2.0/postgres/projects",
        query={"project_id": PROJECT_ID},
        body={"spec": {"pg_version": PG_VERSION}},
    )

# Wait for the primary endpoint to come up, then read its host.
postgres_host = None
for attempt in range(60):
    endpoint = pg_api("GET", f"/api/2.0/postgres/{ENDPOINT_PATH}")
    state = endpoint.get("status", {}).get("current_state")
    if state == "ACTIVE":
        postgres_host = endpoint["status"]["hosts"]["host"]
        break
    print(f"  endpoint state: {state} (waiting...)")
    time.sleep(10)

if not postgres_host:
    raise RuntimeError(f"Endpoint {ENDPOINT_PATH} did not become ACTIVE in time")

print(f"Read-write host: {postgres_host}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3: Connect to Lakebase and create the patient_risk_scores table
# MAGIC
# MAGIC We use OAuth tokens for connection security. On Autoscaling, credentials are minted **per
# MAGIC endpoint**. This is the same call the Databricks App makes
# MAGIC (`workspace_client.postgres.generate_database_credential(endpoint=...)`); we make it over REST here
# MAGIC so the notebook does not depend on a specific SDK method name.

# COMMAND ----------

from sqlalchemy import create_engine, event, text

postgres_username = workspace_client.current_user.me().emails[0].value

engine = create_engine(
    f"postgresql+psycopg://{postgres_username}:@{postgres_host}:{POSTGRES_PORT}/{DATABASE_NAME}?sslmode=require"
)

@event.listens_for(engine, "do_connect")
def provide_token(dialect, conn_rec, cargs, cparams):
    """Provide a fresh Lakebase OAuth token as the connection password."""
    credential = pg_api(
        "POST",
        "/api/2.0/postgres/credentials",
        body={"endpoint": ENDPOINT_PATH},
    )
    cparams["password"] = credential["token"]

def execute(sql):
    """Run a statement and commit."""
    with engine.connect() as connection:
        connection.execute(text(sql))
        connection.commit()
        print(f"  OK: {sql[:60]}...")

# Create schema and table
execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")

execute(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.{TABLE_NAME} (
    patient_id INTEGER PRIMARY KEY,
    district_id VARCHAR(100),
    risk_score FLOAT,
    risk_category VARCHAR(20),
    model_version VARCHAR(50),
    scored_at TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW()
)
""")

# Set REPLICA IDENTITY FULL so the change data feed captures updates and deletes
execute(f"ALTER TABLE {SCHEMA_NAME}.{TABLE_NAME} REPLICA IDENTITY FULL")

# The Databricks App runs as its own service principal and only reads this table.
# Granting SELECT (and schema USAGE) to PUBLIC lets the app's role read it without
# having to look up the service principal's role name. Tighten this to the specific
# service principal role in a real deployment.
execute(f"GRANT USAGE ON SCHEMA {SCHEMA_NAME} TO PUBLIC")
execute(f"GRANT SELECT ON {SCHEMA_NAME}.{TABLE_NAME} TO PUBLIC")

print(f"Table {SCHEMA_NAME}.{TABLE_NAME} ready for change data feed sync")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4: Populate with sample risk scores
# MAGIC
# MAGIC In production, the batch scoring notebook writes the model's predictions here daily.
# MAGIC We populate with samples to show the pattern.

# COMMAND ----------

# Sample risk scores from a hypothetical batch run
sample_scores = [
    (1101, "northmoor_district", 0.23, "LOW", "v0.1.0"),
    (1102, "northmoor_district", 0.67, "HIGH", "v0.1.0"),
    (1103, "northmoor_district", 0.45, "MEDIUM", "v0.1.0"),
    (2101, "eldervale_district", 0.34, "MEDIUM", "v0.1.0"),
    (2102, "eldervale_district", 0.81, "HIGH", "v0.1.0"),
]

with engine.connect() as connection:
    for patient_id, district, score, category, version in sample_scores:
        connection.execute(text(f"""
            INSERT INTO {SCHEMA_NAME}.{TABLE_NAME}
            (patient_id, district_id, risk_score, risk_category, model_version)
            VALUES ({patient_id}, '{district}', {score}, '{category}', '{version}')
            ON CONFLICT (patient_id) DO UPDATE SET
                risk_score = EXCLUDED.risk_score,
                risk_category = EXCLUDED.risk_category,
                last_updated = NOW()
        """))
    connection.commit()

print(f"Populated {len(sample_scores)} sample risk scores")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5: What the change data feed does
# MAGIC
# MAGIC When you set up a change data feed sync (in the admin console or via API), the system reads
# MAGIC the Postgres write-ahead log and captures:
# MAGIC - Inserts: new rows added to the table
# MAGIC - Updates: rows modified (old and new values captured because of REPLICA IDENTITY FULL)
# MAGIC - Deletes: rows removed
# MAGIC
# MAGIC These changes flow into a Delta table in Unity Catalog, so they can be aggregated and joined
# MAGIC with clinical data for deeper analytics.
# MAGIC
# MAGIC The Databricks App continues to query Postgres directly (low latency, consistent with operational
# MAGIC state), while analytics queries Delta (historical, can join with other tables).

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 6: Point the app at this project
# MAGIC
# MAGIC The Databricks App in `dabs/apps/sample_flask_lakebase` attaches to this same Autoscaling project
# MAGIC through its `postgres` app resource. Deploy it with the two variables this notebook printed in
# MAGIC Section 1.1:
# MAGIC
# MAGIC ```bash
# MAGIC cd dabs/apps/sample_flask_lakebase
# MAGIC databricks bundle deploy -t dev -p <profile> \
# MAGIC   --var="postgres_branch=projects/enablement-lakebase/branches/production" \
# MAGIC   --var="postgres_database=projects/enablement-lakebase/branches/production/databases/databricks-postgres"
# MAGIC databricks bundle run sample_flask_lakebase -t dev -p <profile> \
# MAGIC   --var="postgres_branch=projects/enablement-lakebase/branches/production" \
# MAGIC   --var="postgres_database=projects/enablement-lakebase/branches/production/databases/databricks-postgres"
# MAGIC ```
# MAGIC
# MAGIC The app reads `health_analytics.patient_risk_scores` and renders the cohort this notebook populated.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key lessons
# MAGIC
# MAGIC - **Batch serving pattern.** The model scores a batch, writes to Postgres, the App reads from Postgres.
# MAGIC   No live inference, simpler operations.
# MAGIC - **REPLICA IDENTITY FULL is essential.** Without it, updates and deletes are captured incorrectly,
# MAGIC   and the Delta table drifts from truth.
# MAGIC - **Autoscaling and Provisioned Lakebase do not interoperate.** This notebook and the app both use
# MAGIC   Autoscaling (a `projects/<id>` project, per-endpoint credentials). A Provisioned instance does not
# MAGIC   expose the `projects/.../endpoints/...` endpoint the app needs, so keep both on one model.
# MAGIC - **Autoscaling is region-gated.** It may not be available on Free Edition or in every region; check
# MAGIC   availability before the full build. Where it is unavailable, this serving-to-Postgres step is the
# MAGIC   one part of the workshop that needs a workspace and region that offer Lakebase.
# MAGIC - **One synced table, many consumers.** Delta feeds analytics; Postgres feeds the App. Both read
# MAGIC   the same source of truth.
