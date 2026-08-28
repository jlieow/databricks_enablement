# Databricks notebook source
# MAGIC %md
# MAGIC # 04. Onboarding a second district with no new code
# MAGIC
# MAGIC The notebook that proves the operational argument the health authority cares about: onboarding a district
# MAGIC is **configuration, not development**. That is what makes a multi-district reporting system
# MAGIC affordable to run across many health districts.
# MAGIC
# MAGIC The proof is deliberately literal. Rather than a template function that reimplements the
# MAGIC pipeline, this notebook **runs notebooks 02 and 03 unchanged**, passing a different `district_id`.
# MAGIC If a second district needed so much as one edited line, that would show up here immediately.
# MAGIC
# MAGIC The second district is not a clone of the first: **Eldervale District** has different patient volumes and
# MAGIC stream characteristics. A template that only worked for identically shaped districts would
# MAGIC not prove much.

# COMMAND ----------

CATALOG = "enablement"
GOLD = "04_gold"

PRIMARY_DISTRICT = "northmoor_district"
SECONDARY_DISTRICT = "eldervale_district"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run the existing notebooks for the new district
# MAGIC
# MAGIC `dbutils.notebook.run()` calls a notebook with its widgets set. These are the same two
# MAGIC notebooks already run for Northmoor, with one argument different.
# MAGIC
# MAGIC The files for this district must already be in `landing/eldervale_district/`. All three
# MAGIC notebooks (02, 03, and this one) must sit in the same folder, which is how they are
# MAGIC distributed.

# COMMAND ----------

for nb in ["02_ingest_encounters_autoloader", "03_medallion_transform"]:
    print(f"Running {nb} for {SECONDARY_DISTRICT} ...")
    dbutils.notebook.run(nb, 1800, {"district_id": SECONDARY_DISTRICT})
    print("  done")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Both districts, side by side
# MAGIC
# MAGIC Same code produced both. Different patient volumes and stream characteristics, one consistent report shape,
# MAGIC which is what lets one dashboard and one Genie space serve every district.

# COMMAND ----------

display(spark.sql(f"""
  SELECT district_id,
         COUNT(*) AS rows,
         COUNT(DISTINCT patient_id) AS patients,
         COUNT(DISTINCT stream) AS streams,
         SUM(encounter_count) AS encounters,
         SUM(readmission_count) AS readmissions,
         SUM(total_encounters) AS total_encounters
  FROM (
    SELECT * FROM {CATALOG}.{GOLD}.gold_{PRIMARY_DISTRICT}_master
    UNION ALL
    SELECT * FROM {CATALOG}.{GOLD}.gold_{SECONDARY_DISTRICT}_master
  )
  GROUP BY district_id
  ORDER BY district_id
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Consolidate into one all-districts report table
# MAGIC
# MAGIC The dashboard and Genie space read one table, not one per district, so build the consolidated
# MAGIC table here from whatever per-district master tables exist. Discover them rather than list them,
# MAGIC so onboarding a district picks it up automatically on the next run.
# MAGIC
# MAGIC This is a point-in-time copy, not a view: **re-run this notebook after anything that changes a
# MAGIC district's gold table**, or the consolidated table goes stale.

# COMMAND ----------

from functools import reduce

CONSOLIDATED = f"{CATALOG}.{GOLD}.gold_all_districts_master"

masters = [
    r.table_name for r in spark.sql(f"""
      SELECT table_name FROM {CATALOG}.information_schema.tables
      WHERE table_schema = '{GOLD}'
        AND table_name LIKE 'gold_%_master'
        AND table_name <> 'gold_all_districts_master'
      ORDER BY table_name
    """).collect()
]
if not masters:
    raise RuntimeError("No per-district gold master tables. Run notebook 03 first.")

combined = reduce(
    lambda a, b: a.unionByName(b, allowMissingColumns=True),
    [spark.table(f"{CATALOG}.{GOLD}.{t}") for t in masters],
)
combined.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(CONSOLIDATED)

print(f"Built {CONSOLIDATED} from {masters}")
display(spark.sql(f"""
  SELECT district_id, COUNT(*) AS rows FROM {CONSOLIDATED} GROUP BY district_id ORDER BY district_id
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Onboarding any further district
# MAGIC
# MAGIC 1. Drop the district's files into `landing/<district_id>/`.
# MAGIC 2. Re-run this notebook with `SECONDARY_DISTRICT` set to the new `district_id`.
# MAGIC
# MAGIC No new code. In production this becomes a Lakeflow job with `district_id` as a job parameter, so
# MAGIC onboarding is a row in a config table and nothing else. Per-district business rules (which
# MAGIC streams they report, minimum volumes, source-specific windows) belong in that table too, read by
# MAGIC the notebooks rather than written into them.
# MAGIC
# MAGIC This is also why cost attribution in notebook 06 works: **one job run per district** means each
# MAGIC district's compute carries that district's tag.
# MAGIC
# MAGIC The dashboard (agenda item 4) reads `gold_all_districts_master` built above. Notebook 07 shows
# MAGIC how a Unity Catalog row filter would restrict that same table per district, which is the
# MAGIC governance foundation for the multi-district product.
