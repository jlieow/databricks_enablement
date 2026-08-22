# Databricks notebook source
# MAGIC %md
# MAGIC # 01. Workspace, Unity Catalog, and medallion foundations
# MAGIC
# MAGIC Agenda item 1. Before any data lands, lay out where it will live and why. Nothing here is
# MAGIC customer-specific yet: it is the structure every later notebook assumes.
# MAGIC
# MAGIC Three ideas, in order:
# MAGIC
# MAGIC 1. **Unity Catalog** is the governance layer. One `catalog.schema.table` namespace for the
# MAGIC    whole workspace, with permissions and lineage attached to the objects rather than bolted on.
# MAGIC 2. **Delta** is the table format. Every table below is Delta by default: ACID writes, time
# MAGIC    travel, and schema tracking, with nothing to configure.
# MAGIC 3. **Medallion** is a naming and grants convention over those tables, not four systems. Raw,
# MAGIC    bronze, silver, gold are four schemas in one catalog, queried by one engine.
# MAGIC
# MAGIC This mirrors the landing / staging / reporting layers the customer runs on a SQL warehouse
# MAGIC today, but as governed Delta tables rather than one monolithic warehouse.

# COMMAND ----------

# MAGIC %md
# MAGIC ## The structure this build uses
# MAGIC
# MAGIC | Object | Name | Holds |
# MAGIC |---|---|---|
# MAGIC | Catalog | `enablement` | Everything in this session |
# MAGIC | Schema | `01_raw` | Landed source data, as-is |
# MAGIC | Schema | `02_bronze` | Combined sources, deduplicated |
# MAGIC | Schema | `03_silver` | Cleaned, validated, quality-flagged |
# MAGIC | Schema | `04_gold` | The consolidated report tables |
# MAGIC | Schema | `05_ops` | Entitlements, cost, operational tables |
# MAGIC | Volume | `01_raw.landing` | Uploaded CSVs, one folder per client |
# MAGIC | Volume | `01_raw.checkpoints` | Auto Loader's bookkeeping |
# MAGIC
# MAGIC Catalog and schema names are literals in these notebooks, so they run as-is. To use different
# MAGIC names, edit the constants near the top of each notebook.

# COMMAND ----------

CATALOG = "enablement"
SCHEMAS = ["01_raw", "02_bronze", "03_silver", "04_gold", "05_ops"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create the catalog and schemas
# MAGIC
# MAGIC `CREATE ... IF NOT EXISTS` is idempotent, so this cell is safe to re-run. On Free Edition the
# MAGIC catalog lands in the workspace's own metastore with you as owner.

# COMMAND ----------

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"USE CATALOG {CATALOG}")

for schema in SCHEMAS:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.`{schema}`")
    print(f"  {CATALOG}.{schema}")

print(f"\n{len(SCHEMAS)} schemas ready in {CATALOG}.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create the volumes
# MAGIC
# MAGIC A **volume** is UC-governed file storage, addressed as `/Volumes/<catalog>/<schema>/<name>`.
# MAGIC It is where files live before they become tables: the CSV uploads in notebook 02 land in
# MAGIC `landing`, and Auto Loader keeps its state in `checkpoints`.
# MAGIC
# MAGIC Checkpoints sit in their **own** volume, not inside `landing`, or Auto Loader would try to
# MAGIC ingest its own bookkeeping files.

# COMMAND ----------

spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.`01_raw`.landing")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.`01_raw`.checkpoints")

print("Volumes ready:")
print(f"  /Volumes/{CATALOG}/01_raw/landing")
print(f"  /Volumes/{CATALOG}/01_raw/checkpoints")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Where the CSVs go
# MAGIC
# MAGIC Upload the seed files from `data/landing/<client>/` to
# MAGIC `/Volumes/enablement/01_raw/landing/<client>/`, one folder per client:
# MAGIC
# MAGIC - `helix_biosciences/`
# MAGIC - `orbital_instruments/`
# MAGIC
# MAGIC In the UI: **Catalog > enablement > 01_raw > Volumes > landing**, then **Upload**, creating a
# MAGIC folder per client. The next cell creates the folders so the upload target exists.

# COMMAND ----------

for client in ["helix_biosciences", "orbital_instruments"]:
    path = f"/Volumes/{CATALOG}/01_raw/landing/{client}"
    dbutils.fs.mkdirs(path)
    print(f"  {path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Confirm what landed
# MAGIC
# MAGIC After uploading, re-run this. Empty is expected until then.

# COMMAND ----------

for client in ["helix_biosciences", "orbital_instruments"]:
    path = f"/Volumes/{CATALOG}/01_raw/landing/{client}"
    try:
        files = dbutils.fs.ls(path)
        print(f"{client}: {len(files)} file(s)")
        for f in files:
            print(f"    {f.name:55s} {f.size:>10,} bytes")
    except Exception:
        print(f"{client}: folder empty or not found yet")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Why Delta, in one query
# MAGIC
# MAGIC Write a throwaway table, change it, and read an old version back. That capability, time
# MAGIC travel, is what "Delta is the table foundation" buys, and it needed no configuration.

# COMMAND ----------

DEMO = f"{CATALOG}.05_ops.delta_demo"

spark.sql(f"CREATE OR REPLACE TABLE {DEMO} AS SELECT 1 AS id, 'first write' AS note")
spark.sql(f"INSERT INTO {DEMO} VALUES (2, 'second write')")

print("History (every version is queryable):")
display(spark.sql(f"DESCRIBE HISTORY {DEMO}").select("version", "timestamp", "operation"))

# COMMAND ----------

# Version 0 is the table as first written, before the INSERT.
print("Version 0, before the second write:")
display(spark.sql(f"SELECT * FROM {DEMO} VERSION AS OF 0"))

spark.sql(f"DROP TABLE {DEMO}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next
# MAGIC
# MAGIC The structure exists and is empty. From here:
# MAGIC
# MAGIC - **Notebook 02** lands the first client's CSVs into raw with Auto Loader, and the Google Drive
# MAGIC   connector guide covers the second ingestion path with no code.
# MAGIC - **Notebook 03** runs raw through bronze and silver into a gold report table.
# MAGIC - Everything downstream reads the catalog and schemas created here, so run this first.
