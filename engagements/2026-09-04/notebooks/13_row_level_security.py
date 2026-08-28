# Databricks notebook source
# MAGIC %md
# MAGIC # 13. Governance foundation: row-level security on the consolidated table
# MAGIC
# MAGIC This notebook demonstrates how Unity Catalog enforces district-level access control.
# MAGIC One district must never see another district's patient data.

# COMMAND ----------

CATALOG = "enablement"
GOLD, OPS = "04_gold", "05_ops"
PRIMARY_DISTRICT = "northmoor_district"
SECONDARY_DISTRICT = "eldervale_district"

SOURCE = f"{CATALOG}.{GOLD}.gold_all_districts_master"
ENTITLEMENTS = f"{CATALOG}.{OPS}.district_entitlements"

ALL_DISTRICTS_UNFILTERED = f"{CATALOG}.{GOLD}.gold_all_districts_master_unfiltered"
ALL_DISTRICTS_FILTERED = f"{CATALOG}.{GOLD}.gold_all_districts_master_filtered"

if not spark.catalog.tableExists(SOURCE):
    raise RuntimeError(f"{SOURCE} not found. Run notebook 04 first.")

current_user = spark.sql("SELECT current_user()").collect()[0][0]
print(f"Running as: {current_user}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Define entitlements

# COMMAND ----------

spark.sql(f"""
  CREATE OR REPLACE TABLE {ENTITLEMENTS} (
    user_email STRING,
    district_id STRING
  )
""")

spark.sql(f"INSERT INTO {ENTITLEMENTS} VALUES ('{current_user}', '{PRIMARY_DISTRICT}')")
display(spark.table(ENTITLEMENTS))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Build unfiltered and filtered copies

# COMMAND ----------

combined = spark.table(SOURCE)

for target in (ALL_DISTRICTS_UNFILTERED, ALL_DISTRICTS_FILTERED):
    spark.sql(f"DROP TABLE IF EXISTS {target}")
    combined.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(target)

print(f"Built both tables from {SOURCE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Apply the row filter

# COMMAND ----------

spark.sql(f"""
  CREATE OR REPLACE FUNCTION {CATALOG}.{OPS}.district_row_filter(district_id_param STRING)
  RETURN
    is_account_group_member('admins')
    OR EXISTS (
      SELECT 1 FROM {ENTITLEMENTS} e
      WHERE e.user_email = current_user()
        AND e.district_id = district_id_param
    )
""")

spark.sql(f"""
  ALTER TABLE {ALL_DISTRICTS_FILTERED}
  SET ROW FILTER {CATALOG}.{OPS}.district_row_filter ON (district_id)
""")

print(f"Row filter applied to {ALL_DISTRICTS_FILTERED}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Compare filtered vs unfiltered

# COMMAND ----------

display(spark.sql(f"""
  SELECT 'unfiltered' AS table_variant, district_id, COUNT(*) AS rows
  FROM {ALL_DISTRICTS_UNFILTERED} GROUP BY district_id
  UNION ALL
  SELECT 'filtered', district_id, COUNT(*)
  FROM {ALL_DISTRICTS_FILTERED} GROUP BY district_id
  ORDER BY table_variant, district_id
"""))

# COMMAND ----------

visible = spark.sql(f"SELECT COUNT(*) AS c FROM {ALL_DISTRICTS_FILTERED} WHERE district_id = '{PRIMARY_DISTRICT}'").collect()[0]["c"]
blocked = spark.sql(f"SELECT COUNT(*) AS c FROM {ALL_DISTRICTS_FILTERED} WHERE district_id = '{SECONDARY_DISTRICT}'").collect()[0]["c"]

print(f"\nFiltered - {PRIMARY_DISTRICT}: {visible:,} rows (visible)")
print(f"Filtered - {SECONDARY_DISTRICT}: {blocked:,} rows (blocked)")
print("✓ PASS: Row filter working correctly" if blocked == 0 and visible > 0 else "✗ CHECK ENTITLEMENTS")
