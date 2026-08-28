# Databricks notebook source
# MAGIC %md
# MAGIC # 12. Dashboard and AI-powered clinical summaries
# MAGIC
# MAGIC Demonstrates how to generate narrative summaries of clinical metrics using AI functions.
# MAGIC Handles gracefully if AI functions are not available (Free Edition compatibility).

# COMMAND ----------

CATALOG = "enablement"
GOLD_SCHEMA = "04_gold"

GOLD_TABLE = f"{CATALOG}.{GOLD_SCHEMA}.gold_all_districts_master"

if not spark.catalog.tableExists(GOLD_TABLE):
    raise RuntimeError(f"{GOLD_TABLE} not found. Run notebook 04 first.")

print(f"Clinical gold table: {GOLD_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Clinical metrics summary

# COMMAND ----------

metrics_query = f"""
SELECT
  district_id,
  COUNT(*) AS total_encounters,
  COUNT(DISTINCT patient_id) AS unique_patients,
  AVG(length_of_stay) AS avg_los,
  ROUND(SUM(readmission_count)*100.0/NULLIF(SUM(total_encounters), 0), 2) AS readmission_rate_pct,
  MIN(visit_date) AS reporting_start,
  MAX(visit_date) AS reporting_end
FROM {GOLD_TABLE}
GROUP BY district_id
ORDER BY district_id
"""

metrics_df = spark.sql(metrics_query)
display(metrics_df)

# Store for reference
metrics_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{GOLD_SCHEMA}.clinical_metrics_summary"
)

print("Metrics summary saved")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Example queries for dashboard widgets

# COMMAND ----------

display(spark.sql(f"""
SELECT
  district_id,
  COUNT(*) AS encounters,
  COUNT(DISTINCT patient_id) AS patients
FROM {GOLD_TABLE}
GROUP BY district_id
ORDER BY district_id
"""))

# COMMAND ----------

display(spark.sql(f"""
SELECT
  DATE_TRUNC('week', visit_date) AS week,
  district_id,
  COUNT(*) AS encounters,
  ROUND(SUM(readmission_count)*100.0/NULLIF(SUM(total_encounters), 0), 2) AS readmission_rate_pct
FROM {GOLD_TABLE}
GROUP BY DATE_TRUNC('week', visit_date), district_id
ORDER BY week DESC, district_id
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## How to use summaries in practice
# MAGIC
# MAGIC ### Option 1: Email digest
# MAGIC ```python
# MAGIC metrics = spark.sql("SELECT * FROM clinical_metrics_summary")
# MAGIC for row in metrics.collect():
# MAGIC     message = f"Daily clinical summary for {row.district_id}: {row.total_encounters} encounters, readmission rate: {row.readmission_rate_pct}%"
# MAGIC     send_email(to=clinical_leads, subject="Daily report", body=message)
# MAGIC ```
# MAGIC
# MAGIC ### Option 2: Databricks App
# MAGIC ```python
# MAGIC summary = spark.sql(f"SELECT * FROM clinical_metrics_summary WHERE district_id = '{selected_district}'")
# MAGIC st.metric("Encounters", summary.total_encounters)
# MAGIC st.metric("Readmission Rate", f"{summary.readmission_rate_pct}%")
# MAGIC ```

print("Clinical summaries ready for dashboard consumption")
