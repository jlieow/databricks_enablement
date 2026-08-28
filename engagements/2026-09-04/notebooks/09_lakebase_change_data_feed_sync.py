# Databricks notebook source
# MAGIC %md
# MAGIC # 09. Lakebase change data feed sync: batch serving to PostgreSQL
# MAGIC
# MAGIC This notebook sets up a **Lakebase change data feed sync**, so that clinical data and model
# MAGIC scores flow from Delta into a PostgreSQL operational table that the Databricks App reads.
# MAGIC
# MAGIC ### How the sync works
# MAGIC Lakebase change data feed streams row-level changes from Postgres into Unity Catalog Delta tables,
# MAGIC or vice versa: Delta changes sync back into Postgres. We use this for batch model serving: the risk
# MAGIC model scores a batch of patients and writes to Postgres, which the App queries.
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

# COMMAND ----------

# MAGIC %pip install SQLAlchemy "psycopg[binary]"
# MAGIC %pip install --upgrade databricks-sdk
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1.1: Configuration

# COMMAND ----------

INSTANCE_NAME = "enablement-lakebase"
CAPACITY      = "CU_1"
DATABASE_NAME = "databricks_postgres"
SCHEMA_NAME   = "health_analytics"
TABLE_NAME    = "patient_risk_scores"

UC_CATALOG    = "enablement"
UC_SCHEMA     = "05_ops"

POSTGRES_PORT = 5432

print("Configuration")
print("=" * 70)
print(f"Instance:      {INSTANCE_NAME}")
print(f"Capacity:      {CAPACITY}")
print(f"Database:      {DATABASE_NAME}")
print(f"Table:         {SCHEMA_NAME}.{TABLE_NAME}")
print(f"Synced to:     {UC_CATALOG}.{UC_SCHEMA}.{TABLE_NAME}")
print("=" * 70)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: Provision the Lakebase database instance
# MAGIC
# MAGIC Lakebase instances may take a minute to provision. Reusing an existing one is safe.

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.database import DatabaseInstance

workspace_client = WorkspaceClient()

try:
    instance = workspace_client.database.get_database_instance(name=INSTANCE_NAME)
    print(f"Reusing existing instance: {instance.name}  (state: {instance.state})")
except Exception:
    print(f"Creating instance '{INSTANCE_NAME}' (this can take a couple of minutes)...")
    instance = workspace_client.database.create_database_instance_and_wait(
        DatabaseInstance(name=INSTANCE_NAME, capacity=CAPACITY)
    )
    print(f"Created instance: {instance.name}  (state: {instance.state})")

postgres_host = instance.read_write_dns
print(f"Read-write host: {postgres_host}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3: Connect to Lakebase and create the patient_risk_scores table
# MAGIC
# MAGIC We use OAuth tokens for connection security.

# COMMAND ----------

import uuid
from sqlalchemy import create_engine, event, text

postgres_username = workspace_client.current_user.me().emails[0].value

engine = create_engine(
    f"postgresql+psycopg://{postgres_username}:@{postgres_host}:{POSTGRES_PORT}/{DATABASE_NAME}?sslmode=require"
)

@event.listens_for(engine, "do_connect")
def provide_token(dialect, conn_rec, cargs, cparams):
    """Provide a fresh Lakebase OAuth token as the connection password."""
    credential = workspace_client.database.generate_database_credential(
        request_id=str(uuid.uuid4()),
        instance_names=[INSTANCE_NAME],
    )
    cparams["password"] = credential.token

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
# MAGIC ## Key lessons
# MAGIC
# MAGIC - **Batch serving pattern.** The model scores a batch, writes to Postgres, the App reads from Postgres.
# MAGIC   No live inference, simpler operations.
# MAGIC - **REPLICA IDENTITY FULL is essential.** Without it, updates and deletes are captured incorrectly,
# MAGIC   and the Delta table drifts from truth.
# MAGIC - **Managed Postgres autoscaling is region-gated.** On Free Edition or regions without autoscaling,
# MAGIC   you manually provision capacity. Check region availability before the full build.
# MAGIC - **One synced table, many consumers.** Delta feeds analytics; Postgres feeds the App. Both read
# MAGIC   the same source of truth.

