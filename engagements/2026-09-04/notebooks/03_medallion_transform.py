# Databricks notebook source
# MAGIC %md
# MAGIC # 03. Raw to bronze to silver to gold
# MAGIC
# MAGIC Agenda item 3. One table per layer, one job each:
# MAGIC
# MAGIC | Layer | Job |
# MAGIC |---|---|
# MAGIC | Bronze | Combine the clinical streams, drop duplicates |
# MAGIC | Silver | Tidy the values, mark the bad rows |
# MAGIC | Gold | Keep the good rows, add the report's clinical metrics |
# MAGIC
# MAGIC Every layer is a `CREATE OR REPLACE TABLE ... AS SELECT` passed to `spark.sql()`. Four schemas,
# MAGIC one catalog, one engine: no cluster to size, no connector between layers, and every table below
# MAGIC is queryable by anyone with the grant the moment it is written.
# MAGIC
# MAGIC The gold table is the health authority's internal report: one row per patient encounter per stream
# MAGIC per day, with clinical metrics consolidated across the three data streams that raw splits
# MAGIC them into.
# MAGIC
# MAGIC The sample data has planted defects, so the checks have something to find.

# COMMAND ----------

dbutils.widgets.text("district_id", "northmoor_district", "District ID")
district_id = dbutils.widgets.get("district_id")

CATALOG = "enablement"

# Named once here so the queries below stay short and the layer each table belongs to is
# stated in one place.
raw_outpatient_visits = f"{CATALOG}.01_raw.raw_{district_id}_outpatient_visits"
raw_inpatient_admissions = f"{CATALOG}.01_raw.raw_{district_id}_inpatient_admissions"
raw_lab_results = f"{CATALOG}.01_raw.raw_{district_id}_lab_results"

bronze_table = f"{CATALOG}.02_bronze.bronze_{district_id}_encounters"
silver_table = f"{CATALOG}.03_silver.silver_{district_id}_encounters"
gold_table = f"{CATALOG}.04_gold.gold_{district_id}_master"

print(f"District: {district_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze: combine the streams and drop duplicates
# MAGIC
# MAGIC Three raw tables become one. `QUALIFY` keeps the newest row per patient per day, so a stream
# MAGIC resending a corrected day replaces it rather than doubling it. The sample data resends one
# MAGIC lab_results day for exactly this reason.

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.02_bronze")

spark.sql(f"""
  CREATE OR REPLACE TABLE {bronze_table} AS
  WITH all_streams AS (
    SELECT * FROM {raw_outpatient_visits}
    UNION ALL
    SELECT * FROM {raw_inpatient_admissions}
    UNION ALL
    SELECT * FROM {raw_lab_results}
  )
  SELECT * FROM all_streams
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY district_id, stream, patient_id, COALESCE(visit_date, admission_date, test_date)
    ORDER BY _ingested_at DESC, row_id DESC
  ) = 1
""")

# COMMAND ----------

# MAGIC %md
# MAGIC How many duplicates that removed, as a number you can show rather than assert.

# COMMAND ----------

display(spark.sql(f"""
  SELECT
    (SELECT COUNT(*) FROM {raw_outpatient_visits})
    + (SELECT COUNT(*) FROM {raw_inpatient_admissions})
    + (SELECT COUNT(*) FROM {raw_lab_results}) AS raw_rows,
    (SELECT COUNT(*) FROM {bronze_table})  AS bronze_rows,
    raw_rows - bronze_rows                 AS duplicates_removed
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Silver: tidy the values, mark the bad rows
# MAGIC
# MAGIC Two things happen here, and the order matters. **Tidy first**, so no check fails on formatting:
# MAGIC `" Outpatient_Visits "` and `"outpatient_visits"` must be the same stream or the totals split in
# MAGIC two with nothing failing.
# MAGIC
# MAGIC Then **mark, do not delete**. A dropped row is invisible; a marked row is a worklist.
# MAGIC The health authority reports these numbers back to its stakeholders, so a row cannot be quietly lost, and a
# MAGIC flagged one has to be reviewable.

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.03_silver")

spark.sql(f"""
  CREATE OR REPLACE TABLE {silver_table} AS
  SELECT
    row_id, district_id, encounter_id, patient_id,
    encounter_count, readmission_count, total_encounters, adverse_event_count,

    -- Tidy
    LOWER(TRIM(stream))            AS stream,        -- " Outpatient_Visits " -> "outpatient_visits"
    LOWER(TRIM(admission_status))  AS admission_status,

    -- Mark. First failing check wins; NULL means the row is clean.
    CASE
      WHEN patient_id IS NULL THEN 'missing_patient'
      WHEN avg_length_of_stay < 0                    THEN 'negative_los'
      WHEN readmission_count > total_encounters      THEN 'readmissions_exceed_total'
      WHEN adverse_event_count > encounter_count     THEN 'adverse_events_exceed_encounters'
    END AS dq_flags,
    CASE WHEN dq_flags IS NULL THEN 'valid' ELSE 'flagged' END AS dq_status,

    -- Clinical metrics: adverse event rate as percentage. NULLIF guards the divide.
    ROUND(COALESCE(adverse_event_rate_pct, adverse_event_count * 100.0 / NULLIF(encounter_count, 0)), 3) AS adverse_event_rate_pct,
    ROUND(COALESCE(avg_length_of_stay, 0), 2) AS avg_length_of_stay,
    current_timestamp() AS _processed_at
  FROM {bronze_table}
""")

# COMMAND ----------

# MAGIC %md
# MAGIC Adding a district-specific check is one more `WHEN` line above. Here is what it caught:

# COMMAND ----------

display(spark.sql(f"""
  SELECT dq_status, dq_flags, COUNT(*) AS rows
  FROM {silver_table}
  GROUP BY dq_status, dq_flags
  ORDER BY dq_status, dq_flags
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold: one master report table per district
# MAGIC
# MAGIC Valid rows only, with the report's clinical metrics derived once here so every consumer,
# MAGIC dashboard, Genie, Power BI, uses the same definition.
# MAGIC
# MAGIC The readmission rate and adverse event rate are the metrics the health authority reports:
# MAGIC what share of patients have readmissions, and what share of encounters involve adverse events.
# MAGIC Computing them here rather than in each dashboard is what stops three tools disagreeing on "readmission rate".

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.04_gold")

spark.sql(f"""
  CREATE OR REPLACE TABLE {gold_table} AS
  SELECT
    district_id, stream, patient_id, encounter_id,
    encounter_count, readmission_count, total_encounters,
    avg_length_of_stay, adverse_event_rate_pct,
    -- Readmission rate: readmissions per total encounters. NULLIF guards the divide.
    ROUND(readmission_count * 100.0 / NULLIF(total_encounters, 0), 3) AS readmission_rate_pct
  FROM {silver_table}
  WHERE dq_status = 'valid'
""")

# COMMAND ----------

# MAGIC %md
# MAGIC What reached gold, by stream. The flagged rows stayed behind in silver, which is the point:
# MAGIC the report is built from validated rows only, and the rejected ones are still there to review.

# COMMAND ----------

display(spark.sql(f"""
  SELECT stream,
         COUNT(*) AS rows,
         COUNT(DISTINCT patient_id) AS patients,
         SUM(encounter_count) AS encounters,
         SUM(readmission_count) AS readmissions,
         SUM(total_encounters) AS total_encounters,
         ROUND(SUM(readmission_count) * 100.0 / NULLIF(SUM(total_encounters), 0), 2) AS readmission_rate_pct
  FROM {gold_table}
  GROUP BY stream
  ORDER BY stream
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## What the platform did for you here
# MAGIC
# MAGIC Nothing above was configured. It came with the workspace:
# MAGIC
# MAGIC - **Lineage.** Open the gold table in Catalog Explorer, then the Lineage tab. The graph back to
# MAGIC   the three CSV files was built from the queries you just ran. This is the lineage the customer
# MAGIC   wants as a first-class concern.
# MAGIC - **Time travel.** `DESCRIBE HISTORY` on any table above shows every version, and
# MAGIC   `VERSION AS OF` reads an old one. A bad load is reversible without a backup.
# MAGIC - **One engine.** Bronze, silver and gold are the same SQL against the same tables. No extract
# MAGIC   step, no separate warehouse to load into, unlike the cloud data-integration hops today.
# MAGIC - **Four schemas, one catalog.** The layers are a naming and grants convention, not four
# MAGIC   systems to keep in step.

# COMMAND ----------

display(spark.sql(f"DESCRIBE HISTORY {gold_table}"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next
# MAGIC
# MAGIC This rebuilds each table from scratch every run, which is the right default and fine at this
# MAGIC size. Two things change at production scale, both covered later:
# MAGIC
# MAGIC - **Incremental loads**, so a daily run touches only the days that changed.
# MAGIC - **Declarative pipelines** (Lakeflow), where you write the same `SELECT`s and Databricks works
# MAGIC   out the dependency order, the refresh and the data quality expectations.
# MAGIC
# MAGIC Notebook 04 onboards the second district, `eldervale_district`, by running notebooks 02 and 03
# MAGIC unchanged with a different `district_id`. No new code.
