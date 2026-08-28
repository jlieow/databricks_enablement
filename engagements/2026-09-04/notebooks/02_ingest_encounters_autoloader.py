# Databricks notebook source
# MAGIC %md
# MAGIC # 02. Landing a CSV upload into raw with Auto Loader
# MAGIC
# MAGIC Agenda item 2, the file-upload half. One raw Delta table per clinical data stream. Auto Loader tracks which
# MAGIC files it has already read, so re-running never double-counts, and dropping the next weekly file
# MAGIC in ingests only that file.
# MAGIC
# MAGIC This is the pattern behind a CSV upload, and it is also the shape a connector lands data in: a
# MAGIC ready-built connector (Lakeflow Connect, or Fivetran) writes to a raw table, and everything
# MAGIC downstream is identical regardless of how the bytes arrived. In the real build, the client's
# MAGIC clinical source systems land into this same volume; here we use a safe CSV upload as the stand-in.
# MAGIC
# MAGIC This ingests **one district**, the one in the `district_id` widget. The second district is onboarded
# MAGIC from config in notebook 04, with no code change.
# MAGIC
# MAGIC Serverless supports bounded triggers (`availableNow`), not continuous streaming, which is the
# MAGIC right shape for daily batch reporting anyway.

# COMMAND ----------

dbutils.widgets.text("district_id", "northmoor_district", "District ID")
district_id = dbutils.widgets.get("district_id")

CATALOG = "enablement"
RAW_SCHEMA = "01_raw"

LANDING = f"/Volumes/{CATALOG}/{RAW_SCHEMA}/landing/{district_id}"
# Must sit outside LANDING, or Auto Loader ingests its own checkpoint files.
CHECKPOINT_ROOT = f"/Volumes/{CATALOG}/{RAW_SCHEMA}/checkpoints/{district_id}"

print(f"District:   {district_id}")
print(f"Landing:    {LANDING}")
print(f"Checkpoint: {CHECKPOINT_ROOT}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## What has landed
# MAGIC
# MAGIC One CSV per clinical data stream per weekly reporting window. Upload the seed files first (notebook 01
# MAGIC creates the folder), or this cell is empty.

# COMMAND ----------

files = dbutils.fs.ls(LANDING)
for f in files:
    print(f"{f.name:55s} {f.size:>10,} bytes")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Discover the streams
# MAGIC
# MAGIC Convention: `<stream>__<window>.csv`. Splitting on `__` maps every file back to its stream, so
# MAGIC streams are discovered from what landed rather than hardcoded. A new stream is a new file, not
# MAGIC a code change.

# COMMAND ----------

from pyspark.sql import functions as F

streams = sorted({
    f.name.replace(".csv", "").split("__")[0]
    for f in files if f.name.endswith(".csv")
})

print(f"Discovered streams: {streams}")

for s in streams:
    matching = [f.name for f in files if f.name.startswith(s) and f.name.endswith(".csv")]
    print(f"  {s:18s} {len(matching)} file(s)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Ingest each stream into its own raw table
# MAGIC
# MAGIC `schemaHints` pins the numeric columns. Without it Spark can infer metrics as strings, which
# MAGIC breaks the arithmetic in silver.

# COMMAND ----------

SCHEMA_HINTS = (
    "encounter_count LONG, test_count LONG, patient_count LONG, readmission_count LONG, total_encounters LONG, adverse_event_count LONG, visit_date DATE, test_date DATE, admission_date DATE"
)

print(f"Ingesting {len(streams)} streams, one table each.\n")


def row_count(table):
    return spark.table(table).count() if spark.catalog.tableExists(table) else 0


for n, stream_name in enumerate(streams, start=1):
    target = f"{CATALOG}.{RAW_SCHEMA}.raw_{district_id}_{stream_name}"
    before_rows = row_count(target)
    print(f"[{n}/{len(streams)}] {stream_name}")

    # Per-stream checkpoint, so streams can be reprocessed independently.
    checkpoint = f"{CHECKPOINT_ROOT}/{stream_name}"

    stream = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", f"{checkpoint}/schema")
        .option("cloudFiles.schemaHints", SCHEMA_HINTS)
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("header", "true")
        # Only this stream's files.
        .option("pathGlobFilter", f"{stream_name}*.csv")
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

for stream_name in streams:
    target = f"{CATALOG}.{RAW_SCHEMA}.raw_{district_id}_{stream_name}"
    df = spark.table(target)
    print(f"{stream_name:18s} {df.count():>6,} rows from {df.select('_source_file').distinct().count()} file(s)")

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
        for t in streams
    ],
)
display(per_file.orderBy("raw_table", "source_file"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sample one stream

# COMMAND ----------

dbutils.widgets.dropdown("preview_stream", streams[0], streams, "Preview which stream")
preview = dbutils.widgets.get("preview_stream")

display(spark.sql(f"""
  SELECT * FROM {CATALOG}.{RAW_SCHEMA}.raw_{district_id}_{preview}
  LIMIT 10
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Prove idempotency
# MAGIC
# MAGIC Re-run every stream. Row counts must not move: Auto Loader has already committed these files,
# MAGIC so a second pass reads nothing.

# COMMAND ----------

before = {
    s: spark.table(f"{CATALOG}.{RAW_SCHEMA}.raw_{district_id}_{s}").count()
    for s in streams
}

for stream_name in streams:
    checkpoint = f"{CHECKPOINT_ROOT}/{stream_name}"
    (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", f"{checkpoint}/schema")
        .option("cloudFiles.schemaHints", SCHEMA_HINTS)
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("header", "true")
        .option("pathGlobFilter", f"{stream_name}*.csv")
        .load(LANDING)
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.col("_metadata.file_path"))
        .writeStream
        .option("checkpointLocation", f"{checkpoint}/commits")
        .option("mergeSchema", "true")
        .trigger(availableNow=True)
        .toTable(f"{CATALOG}.{RAW_SCHEMA}.raw_{district_id}_{stream_name}")
        .awaitTermination()
    )

print(f"{'stream':18s} {'before':>8s} {'after':>8s}   result")
all_stable = True
for stream_name in streams:
    after = spark.table(f"{CATALOG}.{RAW_SCHEMA}.raw_{district_id}_{stream_name}").count()
    stable = after == before[stream_name]
    all_stable &= stable
    print(f"{stream_name:18s} {before[stream_name]:>8,} {after:>8,}   {'unchanged' if stable else 'CHANGED, investigate'}")

print(f"\n{'PASS: re-running ingested nothing twice' if all_stable else 'FAIL: row counts moved'}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next
# MAGIC
# MAGIC - Land the later weekly files and re-run: Auto Loader reads only the new ones.
# MAGIC - Drop new stream files into `eldervale_district/` to see them picked up on their own.
# MAGIC   In production a file-arrival job trigger fires the run automatically.
# MAGIC - Ready-built connectors (Lakeflow Connect, Fivetran) land raw the same way, so nothing
# MAGIC   downstream changes when the real clinical source replaces the CSV upload at the build.
# MAGIC - Notebook 03: raw through bronze and silver into the gold encounter table.
