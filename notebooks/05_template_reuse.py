# Databricks notebook source
# MAGIC %md
# MAGIC # 05. Onboarding a second client with no new code
# MAGIC
# MAGIC This is the notebook that proves the commercial argument: onboarding a client is
# MAGIC **configuration, not development**.
# MAGIC
# MAGIC The proof is deliberately literal. Rather than a template function that reimplements the
# MAGIC pipeline, this notebook **runs notebooks 01 and 04 unchanged**, passing a different
# MAGIC `client_id`. If a second client needed so much as one edited line, that would show up here
# MAGIC immediately.
# MAGIC
# MAGIC The second client is not a clone of the first: **Contoso Travel** bills in EUR where
# MAGIC Northwind bills in GBP. A template that only worked for identically-shaped clients would not
# MAGIC prove much.

# COMMAND ----------

CATALOG = "enablement"
GOLD = "04_gold"

PRIMARY_CLIENT = "northwind_retail"
SECONDARY_CLIENT = "contoso_travel"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run the existing notebooks for the new client
# MAGIC
# MAGIC `dbutils.notebook.run()` calls a notebook with its widgets set. These are the same two
# MAGIC notebooks already run for Northwind, with one argument different.
# MAGIC
# MAGIC The files for this client must already be in `landing/contoso_travel/`.

# COMMAND ----------

for nb in ["01_raw_ingest_autoloader", "04_medallion_transform"]:
    print(f"Running {nb} for {SECONDARY_CLIENT} ...")
    dbutils.notebook.run(nb, 1800, {"client_id": SECONDARY_CLIENT})
    print("  done")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Both clients, side by side
# MAGIC
# MAGIC Same code produced both. Note the different local currencies converging on one `spend_usd`,
# MAGIC which is the whole point of the FX join in notebook 04.

# COMMAND ----------

display(spark.sql(f"""
  SELECT client_id, local_currency,
         COUNT(*) AS rows,
         COUNT(DISTINCT campaign_id) AS campaigns,
         ROUND(SUM(spend_local), 2) AS spend_local,
         ROUND(SUM(spend_usd), 2)   AS spend_usd
  FROM (
    SELECT * FROM {CATALOG}.{GOLD}.gold_{PRIMARY_CLIENT}_master
    UNION ALL
    SELECT * FROM {CATALOG}.{GOLD}.gold_{SECONDARY_CLIENT}_master
  )
  GROUP BY client_id, local_currency
  ORDER BY client_id
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Onboarding any further client
# MAGIC
# MAGIC 1. Drop the client's files into `landing/<client_id>/`.
# MAGIC 2. Re-run this notebook with `SECONDARY_CLIENT` set to the new `client_id`.
# MAGIC
# MAGIC No new code. In production this becomes a Lakeflow job with `client_id` as a job parameter,
# MAGIC so onboarding is a row in a config table and nothing else. Per-client business rules
# MAGIC (minimum spend, different currencies, source-specific windows) belong in that table too,
# MAGIC read by the notebooks rather than written into them.
