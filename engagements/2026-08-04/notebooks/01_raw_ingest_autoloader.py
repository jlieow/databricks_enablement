# Databricks notebook source
# MAGIC %md
# MAGIC # 01. Raw ingestion from a volume with Auto Loader
# MAGIC
# MAGIC One raw Delta table per source. Auto Loader tracks which files it has already read, so
# MAGIC re-running does not double-count.
# MAGIC
# MAGIC Serverless supports bounded triggers (`availableNow`), not continuous streaming.
# MAGIC
# MAGIC This ingests **one client**, the one in the `client_id` widget. The second client is
# MAGIC onboarded from config in notebook 05.

# COMMAND ----------

dbutils.widgets.text("client_id", "northwind_retail", "Client ID")
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
# MAGIC One CSV per platform per weekly reporting window.

# COMMAND ----------

files = dbutils.fs.ls(LANDING)
for f in files:
    print(f"{f.name:45s} {f.size:>10,} bytes")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Discover the sources
# MAGIC
# MAGIC Convention: `<platform>.csv` or `<platform>__<variant>.csv`. Splitting on `__` maps every
# MAGIC file for a source back to its platform, so sources are discovered rather than hardcoded.

# COMMAND ----------

from pyspark.sql import functions as F

platforms = sorted({
    f.name.replace(".csv", "").split("__")[0]
    for f in files if f.name.endswith(".csv")
})

print(f"Discovered sources: {platforms}")

for p in platforms:
    matching = [f.name for f in files if f.name.startswith(p) and f.name.endswith(".csv")]
    print(f"  {p:16s} {len(matching)} file(s)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Ingest each source into its own raw table
# MAGIC
# MAGIC `schemaHints` pins the numeric columns. Without it Spark can infer `spend` as a string,
# MAGIC which breaks the arithmetic in silver.

# COMMAND ----------

SCHEMA_HINTS = (
    "impressions LONG, clicks LONG, spend DOUBLE, "
    "conversions LONG, report_date DATE"
)

print(f"Ingesting {len(platforms)} sources, one table each.\n")


def row_count(table):
    return spark.table(table).count() if spark.catalog.tableExists(table) else 0


for n, platform in enumerate(platforms, start=1):
    target = f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{platform}"
    before_rows = row_count(target)
    print(f"[{n}/{len(platforms)}] {platform}")

    # Per-source checkpoint, so sources can be reprocessed independently.
    checkpoint = f"{CHECKPOINT_ROOT}/{platform}"

    stream = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", f"{checkpoint}/schema")
        .option("cloudFiles.schemaHints", SCHEMA_HINTS)
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("header", "true")
        # Only this platform's files.
        .option("pathGlobFilter", f"{platform}*.csv")
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

for platform in platforms:
    target = f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{platform}"
    df = spark.table(target)
    print(f"{platform:16s} {df.count():>6,} rows from {df.select('_source_file').distinct().count()} file(s)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Which file each row came from

# COMMAND ----------

from functools import reduce

per_file = reduce(
    lambda a, b: a.unionByName(b),
    [
        spark.table(f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{p}")
        .withColumn("raw_table", F.lit(f"raw_{client_id}_{p}"))
        .withColumn("source_file", F.regexp_extract(F.col("_source_file"), r"([^/]+)$", 1))
        .groupBy("raw_table", "source_file")
        .agg(
            F.count("*").alias("rows"),
            F.min("report_date").alias("from_date"),
            F.max("report_date").alias("to_date"),
        )
        for p in platforms
    ],
)
display(per_file.orderBy("raw_table", "source_file"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sample one source

# COMMAND ----------

dbutils.widgets.dropdown("preview_source", platforms[0], platforms, "Preview which source")
preview = dbutils.widgets.get("preview_source")

display(spark.sql(f"""
  SELECT * FROM {CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{preview}
  ORDER BY report_date DESC
  LIMIT 10
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Prove idempotency
# MAGIC
# MAGIC Re-run every source. Row counts must not move.

# COMMAND ----------

before = {
    p: spark.table(f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{p}").count()
    for p in platforms
}

for platform in platforms:
    checkpoint = f"{CHECKPOINT_ROOT}/{platform}"
    (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", f"{checkpoint}/schema")
        .option("cloudFiles.schemaHints", SCHEMA_HINTS)
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("header", "true")
        .option("pathGlobFilter", f"{platform}*.csv")
        .load(LANDING)
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.col("_metadata.file_path"))
        .writeStream
        .option("checkpointLocation", f"{checkpoint}/commits")
        .option("mergeSchema", "true")
        .trigger(availableNow=True)
        .toTable(f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{platform}")
        .awaitTermination()
    )

print(f"{'source':16s} {'before':>8s} {'after':>8s}   result")
all_stable = True
for platform in platforms:
    after = spark.table(f"{CATALOG}.{RAW_SCHEMA}.raw_{client_id}_{platform}").count()
    stable = after == before[platform]
    all_stable &= stable
    print(f"{platform:16s} {before[platform]:>8,} {after:>8,}   {'unchanged' if stable else 'CHANGED, investigate'}")

print(f"\n{'PASS: re-running ingested nothing twice' if all_stable else 'FAIL: row counts moved'}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next
# MAGIC
# MAGIC - Land the later weekly files and re-run: Auto Loader reads only the new ones.
# MAGIC - Drop `facebook_ads__late_arrival.csv` in to fire the file-arrival job trigger.
# MAGIC - Notebook 03: the one source that is not a file (an API).
# MAGIC - Notebook 04: raw through bronze and silver into gold.
