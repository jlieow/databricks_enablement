# Databricks notebook source
# MAGIC %md
# MAGIC # 09. Lakebase change data feed sync: sync Postgres changes to Delta
# MAGIC
# MAGIC This notebook sets up a **Lakebase change data feed sync**, so that changes to your operational
# MAGIC Postgres data flow automatically into Delta tables in Unity Catalog for analytics. You will
# MAGIC provision a Lakebase (managed Postgres) database, create a table, prepare it for the change data
# MAGIC feed, and populate it — leaving you ready to create a synced Delta table.
# MAGIC
# MAGIC ### How the sync works
# MAGIC Lakebase change data feed streams row-level changes from Postgres into Unity Catalog Delta tables.
# MAGIC Under the hood, the sync engine (`wal2delta`) reads Postgres's write-ahead log — the same
# MAGIC mechanism logical replication uses. Inserts, updates, and deletes are captured there and applied
# MAGIC to the destination Delta table.
# MAGIC
# MAGIC ### One requirement to set up front: REPLICA IDENTITY FULL
# MAGIC For the feed to capture **updates** and **deletes** accurately, Postgres needs to log the full
# MAGIC *before-image* of each changed row — every column's old value, not just the primary key. Postgres
# MAGIC does not do this by default, so you tell it to per table:
# MAGIC
# MAGIC ```sql
# MAGIC ALTER TABLE my_schema.my_table REPLICA IDENTITY FULL;
# MAGIC ```
# MAGIC
# MAGIC This is a required setup step for **every table** you want the change data feed to sync. The cost
# MAGIC is a little extra write-ahead-log volume on updates and deletes, which is negligible for most
# MAGIC operational tables. Set it when you create the table and the sync will pick the table up.
# MAGIC
# MAGIC ### Steps in this notebook
# MAGIC 1. Provision a Lakebase database instance
# MAGIC 2. Connect to it with a short-lived OAuth token, refreshed automatically
# MAGIC 3. Create a schema and a table
# MAGIC 4. Prepare the table for the change data feed with `REPLICA IDENTITY FULL`
# MAGIC 5. Populate the table with rows and a change to stream
# MAGIC 6. Create the synced Delta table in Unity Catalog

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1: Prerequisites & setup
# MAGIC
# MAGIC Lakebase is Databricks-managed Postgres. We talk to it two ways: the Databricks SDK to create
# MAGIC and manage the instance, and a normal Postgres driver (`psycopg`) via SQLAlchemy to run SQL. We
# MAGIC install SQLAlchemy and psycopg, and upgrade the SDK so the `database` API is available.

# COMMAND ----------

# MAGIC %pip install SQLAlchemy "psycopg[binary]"
# MAGIC %pip install --upgrade databricks-sdk
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1.1: Configuration
# MAGIC
# MAGIC Literal names so the notebook runs as-is. Edit the constants below to point at a different
# MAGIC instance, schema, or table. `CAPACITY` is the smallest Lakebase size, which is plenty for this
# MAGIC walkthrough.

# COMMAND ----------

# ===================================================================
# CONFIGURATION
# ===================================================================

INSTANCE_NAME = "enablement-lakebase"   # Lakebase database instance name (lowercase, hyphens)
CAPACITY      = "CU_1"                  # Smallest capacity unit
DATABASE_NAME = "databricks_postgres"   # Default database created with every instance
SCHEMA_NAME   = "enablement"            # Postgres schema to create
TABLE_NAME    = "holiday_requests"      # Table to create and sync

# Where the synced Delta table lands in Unity Catalog (Section 6).
UC_CATALOG    = "enablement"            # Unity Catalog created by notebook 01
UC_SCHEMA     = "05_ops"                # Schema for the synced Delta table

POSTGRES_PORT = 5432

print("Configuration")
print("=" * 70)
print(f"Instance:      {INSTANCE_NAME}")
print(f"Capacity:      {CAPACITY}")
print(f"Database:      {DATABASE_NAME}")
print(f"Source table:  {SCHEMA_NAME}.{TABLE_NAME}")
print(f"Synced table:  {UC_CATALOG}.{UC_SCHEMA}.{TABLE_NAME}")
print("=" * 70)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: Provision the Lakebase database instance
# MAGIC
# MAGIC We create the instance through the Databricks SDK and wait for it to become available. If an
# MAGIC instance with this name already exists we reuse it, so the notebook is safe to re-run. New
# MAGIC instances are provisioned as Lakebase Autoscaling, which supports scale-to-zero and branching.

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
# MAGIC ## Section 3: Connect to Lakebase
# MAGIC
# MAGIC We connect as the current user with a short-lived OAuth token instead of a static password. The
# MAGIC SQLAlchemy engine asks the SDK for a fresh token on every new connection (via the `do_connect`
# MAGIC event), so connections keep working after the initial token expires. The SDK caches tokens, so
# MAGIC this is cheap.

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


def execute(sql, params=None):
  """Run a statement and commit. Use for DDL and writes."""
  with engine.connect() as connection:
    connection.execute(text(sql), params or {})
    connection.commit()


def query(sql):
  """Run a query and return all rows."""
  with engine.connect() as connection:
    return connection.execute(text(sql)).fetchall()


print("Connected. Postgres version:")
for row in query("SELECT version();"):
  print(" ", row[0])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4: Create the source table
# MAGIC
# MAGIC Create the schema and the operational table you want to sync. This is an ordinary Postgres table
# MAGIC with a primary key — the sort of table your application writes to.

# COMMAND ----------

execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME};")

execute(f"""
  CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.{TABLE_NAME} (
    request_id    SERIAL PRIMARY KEY,
    employee_name VARCHAR(255) NOT NULL,
    start_date    DATE NOT NULL,
    end_date      DATE NOT NULL,
    status        VARCHAR(50) NOT NULL,
    manager_note  TEXT
  );
""")

print(f"Source table ready: {SCHEMA_NAME}.{TABLE_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5: Prepare the table for the change data feed
# MAGIC
# MAGIC Set `REPLICA IDENTITY FULL` so Postgres logs the complete old row on every update and delete.
# MAGIC This is the setup step that makes the table eligible for the change data feed — do it for every
# MAGIC table you want to sync. We then read it back from `pg_class.relreplident` to confirm.
# MAGIC
# MAGIC | `relreplident` | Replica identity | Change data feed |
# MAGIC |----------------|------------------|------------------|
# MAGIC | `d` | default — primary key columns only | not eligible |
# MAGIC | `f` | full — the complete old row | **eligible** |
# MAGIC | `i` | a specific unique index | — |
# MAGIC | `n` | nothing | — |

# COMMAND ----------

execute(f"ALTER TABLE {SCHEMA_NAME}.{TABLE_NAME} REPLICA IDENTITY FULL;")

replica_identity = query(f"""
  SELECT relreplident
  FROM pg_class
  WHERE oid = '{SCHEMA_NAME}.{TABLE_NAME}'::regclass;
""")[0][0]

print(f"Replica identity: {replica_identity}   (expected 'f' = full)")
assert replica_identity == "f", "Replica identity is not FULL — the change data feed will not pick up this table."
print("Table is ready for the change data feed.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 6: Populate the table
# MAGIC
# MAGIC Insert a few rows and update one, giving the feed some changes to stream. With
# MAGIC `REPLICA IDENTITY FULL` set, the update is captured with its full before-image, so it will sync
# MAGIC cleanly. We `TRUNCATE` first so the notebook is safe to re-run without piling up rows.

# COMMAND ----------

execute(f"TRUNCATE TABLE {SCHEMA_NAME}.{TABLE_NAME} RESTART IDENTITY;")

execute(f"""
  INSERT INTO {SCHEMA_NAME}.{TABLE_NAME} (employee_name, start_date, end_date, status, manager_note)
  VALUES
    ('Joe',     '2026-08-01', '2026-08-20', 'Pending', ''),
    ('Suzy',    '2026-07-22', '2026-07-25', 'Pending', ''),
    ('Charlie', '2026-08-01', '2026-08-05', 'Pending', '');
""")

# An update, to show a change flowing through the feed with its full before-image.
execute(f"""
  UPDATE {SCHEMA_NAME}.{TABLE_NAME}
  SET status = 'Approved', manager_note = 'Enjoy!'
  WHERE employee_name = 'Joe';
""")

rows = query(f"SELECT request_id, employee_name, status, manager_note FROM {SCHEMA_NAME}.{TABLE_NAME} ORDER BY request_id;")
print("Current rows")
print("=" * 70)
for r in rows:
  print(f"  {r[0]}  {r[1]:10s}  {r[2]:10s}  {r[3]}")
print("=" * 70)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 7: Create the synced Delta table
# MAGIC
# MAGIC With the source table prepared and populated, create the synced Delta table so changes land in
# MAGIC Unity Catalog. Two steps:
# MAGIC
# MAGIC 1. **Register the Lakebase database in Unity Catalog** as a database catalog — in Catalog
# MAGIC    Explorer (open the Lakebase instance and create a catalog) or with the SDK, as below.
# MAGIC 2. **Create a synced table** from `enablement.holiday_requests` into a Delta table in Unity
# MAGIC    Catalog. The change data feed then streams inserts, updates, and deletes into Delta.
# MAGIC
# MAGIC You can create the synced table in Catalog Explorer, or with the SDK using
# MAGIC `workspace_client.database.create_synced_database_table`. The UI is the simplest place to start;
# MAGIC the code below registers the catalog to get you there.

# COMMAND ----------

from databricks.sdk.service.database import DatabaseCatalog

catalog_name = f"{INSTANCE_NAME.replace('-', '_')}_catalog"

try:
  workspace_client.database.get_database_catalog(name=catalog_name)
  print(f"Reusing existing database catalog: {catalog_name}")
except Exception:
  workspace_client.database.create_database_catalog(
    catalog=DatabaseCatalog(
      name=catalog_name,
      database_instance_name=INSTANCE_NAME,
      database_name=DATABASE_NAME,
      create_database_if_not_exists=False,
    )
  )
  print(f"Registered database catalog: {catalog_name}")

print()
print("Next: create the synced Delta table")
print("=" * 70)
print(f"Source (Postgres): {SCHEMA_NAME}.{TABLE_NAME}")
print(f"Target (Delta):    {UC_CATALOG}.{UC_SCHEMA}.{TABLE_NAME}")
print("In Catalog Explorer, open the Lakebase instance, select the source table,")
print("and choose 'Create synced table' — or use create_synced_database_table.")
print("=" * 70)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recap
# MAGIC
# MAGIC You provisioned a Lakebase database, created and populated a table, and prepared it for the
# MAGIC change data feed. Changes to the Postgres table now flow into the synced Delta table in Unity
# MAGIC Catalog, ready for analytics.
# MAGIC
# MAGIC The step to carry forward: every table you want to sync needs `REPLICA IDENTITY FULL`. Set it
# MAGIC right after you create the table.
# MAGIC
# MAGIC ```sql
# MAGIC ALTER TABLE my_schema.my_table REPLICA IDENTITY FULL;
# MAGIC ```

# COMMAND ----------

print("Done.")
print(f"  Instance:     {INSTANCE_NAME}")
print(f"  Source table: {SCHEMA_NAME}.{TABLE_NAME}  (REPLICA IDENTITY FULL)")
print(f"  Synced table: {UC_CATALOG}.{UC_SCHEMA}.{TABLE_NAME}")
