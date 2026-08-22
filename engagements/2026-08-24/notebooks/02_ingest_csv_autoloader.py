# Databricks notebook source
# MAGIC %md
# MAGIC # 02. Landing a CSV upload into raw with Auto Loader
# MAGIC
# MAGIC Agenda item 2, the file-upload half. One raw Delta table per tactic. Auto Loader tracks which
# MAGIC files it has already read, so re-running never double-counts, and dropping the next weekly file
# MAGIC in ingests only that file.
# MAGIC
# MAGIC This is the pattern behind a CSV upload, and it is also the shape a connector lands data in: a
# MAGIC ready-built connector (Lakeflow Connect, or Fivetran) writes to a raw table, and everything
# MAGIC downstream is identical regardless of how the bytes arrived. The **Google Drive connector
# MAGIC guide** (`docs/google_drive_connector_guide.md`) covers that second, no-code path over the same
# MAGIC landing volume.
# MAGIC
# MAGIC This ingests **one client**, the one in the `client_id` widget. The second client is onboarded
# MAGIC from config in notebook 03, with no code change.
# MAGIC
# MAGIC Serverless supports bounded triggers (`availableNow`), not continuous streaming, which is the
# MAGIC right shape for daily batch reporting anyway.

# COMMAND ----------

dbutils.widgets.text("client_id", "helix_biosciences", "Client ID")
client_id = dbutils.widgets.get("client_id")

CATALOG = "enablement"
RAW_SCHEMA = "01_raw"

LANDING = f"/Volumes/{CATALOG}/{RAW_SCHEMA}/landing/{client_id}"
# Must sit outside LANDING, or Auto Loader ingests its own checkpoint files.
CHECKPOINT_ROOT = f"/Volumes/{CATALOG}/{RAW_SCHEMA}/checkpoints/{client_id}"

print(f"Client:     {client_id}")
print(f"Landing:    {LANDING}")
print(f"Checkpoint: {CHECKPOINT_ROOT}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## What has landed
# MAGIC
# MAGIC One CSV per tactic per weekly reporting window. Upload the seed files first (notebook 01
# MAGIC creates the folder), or this cell is empty.

# COMMAND ----------

files = dbutils.fs.ls(LANDING)
for f in files:
    print(f"{f.name:55s} {f.size:>10,} bytes")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Discover the tactics
# MAGIC
# MAGIC Convention: `<tactic>__<window>.csv`. Splitting on `__` maps every file back to its tactic, so
# MAGIC tactics are discovered from what landed rather than hardcoded. A new tactic is a new file, not
# MAGIC a code change.

# COMMAND ----------

from pyspark.sql import functions as F

tactics = sorted({
    f.name.replace(".csv", "").split("__")[0]
    for f in files if f.name.endswith(".csv")
})

print(f"Discovered tactics: {tactics}")

for t in tactics:
    matching = [f.name for f in files if f.name.startswith(t) and f.name.endswith(".csv")]
    print(f"  {t:18s} {len(matching)} file(s)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Ingest each tactic into its own raw table
# MAGIC
# MAGIC `schemaHints` pins the numeric columns. Without it Spark can infer `leads` as a string, which
# MAGIC breaks the arithmetic in silver.

# COMMAND ----------

SCHEMA_HINTS = (
    "impressions LONG, engagements LONG, leads LONG, report_date DATE"
)

print(f"Ingesting {len(tactics)} tactics, one table each.\n")


def row_count(table):
    return spark.table(table).count() if spark.catalog.tableExists(table) else 0


for n, tactic in enumerate(tactics, start=1):
    target = f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{tactic}"
    before_rows = row_count(target)
    print(f"[{n}/{len(tactics)}] {tactic}")

    # Per-tactic checkpoint, so tactics can be reprocessed independently.
    checkpoint = f"{CHECKPOINT_ROOT}/{tactic}"

    stream = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", f"{checkpoint}/schema")
        .option("cloudFiles.schemaHints", SCHEMA_HINTS)
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("header", "true")
        # Only this tactic's files.
        .option("pathGlobFilter", f"{tactic}*.csv")
        .load(LANDING)
        # Provenance: lets you trace a wrong number back to a specific file.
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.col("_metadata.file_path"))
    )

    (
        stream.writeStream
        .option("checkpointLocation", f"{checkpoint}/commits")
        .option("mergeSchema", "true")
        .trigger(availableNow=True)
        .toTable(target)
        .awaitTermination()
    )
    rows = spark.table(target).count()
    print(f"        -> {target}  ({rows:,} rows, +{rows - before_rows:,} this run)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify

# COMMAND ----------

for tactic in tactics:
    target = f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{tactic}"
    df = spark.table(target)
    print(f"{tactic:18s} {df.count():>6,} rows from {df.select('_source_file').distinct().count()} file(s)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Which file each row came from

# COMMAND ----------

from functools import reduce

per_file = reduce(
    lambda a, b: a.unionByName(b),
    [
        spark.table(f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{t}")
        .withColumn("raw_table", F.lit(f"raw_{client_id}_{t}"))
        .withColumn("source_file", F.regexp_extract(F.col("_source_file"), r"([^/]+)$", 1))
        .groupBy("raw_table", "source_file")
        .agg(
            F.count("*").alias("rows"),
            F.min("report_date").alias("from_date"),
            F.max("report_date").alias("to_date"),
        )
        for t in tactics
    ],
)
display(per_file.orderBy("raw_table", "source_file"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sample one tactic

# COMMAND ----------

dbutils.widgets.dropdown("preview_tactic", tactics[0], tactics, "Preview which tactic")
preview = dbutils.widgets.get("preview_tactic")

display(spark.sql(f"""
  SELECT * FROM {CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{preview}
  ORDER BY report_date DESC
  LIMIT 10
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Prove idempotency
# MAGIC
# MAGIC Re-run every tactic. Row counts must not move: Auto Loader has already committed these files,
# MAGIC so a second pass reads nothing.

# COMMAND ----------

before = {
    t: spark.table(f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{t}").count()
    for t in tactics
}

for tactic in tactics:
    checkpoint = f"{CHECKPOINT_ROOT}/{tactic}"
    (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", f"{checkpoint}/schema")
        .option("cloudFiles.schemaHints", SCHEMA_HINTS)
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("header", "true")
        .option("pathGlobFilter", f"{tactic}*.csv")
        .load(LANDING)
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.col("_metadata.file_path"))
        .writeStream
        .option("checkpointLocation", f"{checkpoint}/commits")
        .option("mergeSchema", "true")
        .trigger(availableNow=True)
        .toTable(f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{tactic}")
        .awaitTermination()
    )

print(f"{'tactic':18s} {'before':>8s} {'after':>8s}   result")
all_stable = True
for tactic in tactics:
    after = spark.table(f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{tactic}").count()
    stable = after == before[tactic]
    all_stable &= stable
    print(f"{tactic:18s} {before[tactic]:>8,} {after:>8,}   {'unchanged' if stable else 'CHANGED, investigate'}")

print(f"\n{'PASS: re-running ingested nothing twice' if all_stable else 'FAIL: row counts moved'}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next
# MAGIC
# MAGIC - Land the later weekly files and re-run: Auto Loader reads only the new ones.
# MAGIC - Drop `webinar__late_arrival.csv` into `orbital_instruments/` to see one new file picked up on
# MAGIC   its own. In production a file-arrival job trigger fires the run automatically.
# MAGIC - **Google Drive connector guide**: the second ingestion path, no code, landing to the same
# MAGIC   volume. Ready-built connectors (Lakeflow Connect, Fivetran) land raw the same way.
# MAGIC - Notebook 03: raw through bronze and silver into the gold report table.
