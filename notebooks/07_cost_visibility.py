# Databricks notebook source
# MAGIC %md
# MAGIC # 07. Per-client cost visibility
# MAGIC
# MAGIC How to answer "what does this client cost us".
# MAGIC
# MAGIC **The one thing that matters here is the first section.** Cost attribution depends entirely on
# MAGIC tags applied when a job runs, and tags cannot be applied retrospectively. Untagged compute
# MAGIC from month one is permanently unattributable.
# MAGIC
# MAGIC Usage data lives in `system.billing`, which Unity Catalog exposes as ordinary tables. So this
# MAGIC is the same SQL you have been writing all session, pointed at the platform's own telemetry.

# COMMAND ----------

CATALOG = "enablement"
OPS = "05_ops"

# The system tables are governed, so a workspace may simply not have granted them. Check rather
# than fail three cells later.
billing_available = False
try:
    spark.sql("SELECT 1 FROM system.billing.usage LIMIT 1").collect()
    billing_available = True
    print("system.billing.usage is readable.")
except Exception as e:
    print(f"system.billing.usage not readable ({type(e).__name__}).")
    print("Ask an account admin to grant the system.billing schema, then re-run.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: tag everything, before you need the data
# MAGIC
# MAGIC This is the whole game. Tag the job, and every usage record it generates carries the tag.
# MAGIC
# MAGIC ```hcl
# MAGIC tags = {
# MAGIC   client      = "northwind_retail"
# MAGIC   cost_center = "client_delivery"
# MAGIC }
# MAGIC ```
# MAGIC
# MAGIC **One job run per client.** A single job processing every client cannot be split by client
# MAGIC afterwards, at any price. That is a pipeline design decision driven by a finance requirement,
# MAGIC so it is worth settling early rather than deferring.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: cost per client
# MAGIC
# MAGIC The headline number: what each client costs to run, per category.
# MAGIC
# MAGIC Note `list_prices` gives the **list** rate, so apply your organisation's own pricing before
# MAGIC treating any of these as a real figure.

# COMMAND ----------

cost_per_client_sql = """
SELECT
  COALESCE(u.custom_tags['client'], 'untagged')  AS client,
  u.billing_origin_product                       AS category,
  ROUND(SUM(u.usage_quantity), 2)                AS dbus,
  ROUND(SUM(u.usage_quantity * lp.pricing.default), 2) AS estimated_usd,
  COUNT(DISTINCT u.usage_date)                   AS days_active,
  ROUND(SUM(u.usage_quantity * lp.pricing.default)
        / NULLIF(COUNT(DISTINCT u.usage_date), 0) * 30, 2) AS projected_monthly_usd
FROM system.billing.usage u
LEFT JOIN system.billing.list_prices lp
  ON u.sku_name = lp.sku_name
 AND u.usage_end_time >= lp.price_start_time
 AND (lp.price_end_time IS NULL OR u.usage_end_time < lp.price_end_time)
WHERE u.usage_date >= DATE_SUB(CURRENT_DATE(), 30)
GROUP BY 1, 2
ORDER BY estimated_usd DESC
"""

print(cost_per_client_sql)
if billing_available:
    display(spark.sql(cost_per_client_sql))

# COMMAND ----------

# MAGIC %md
# MAGIC **Read the `untagged` row first.** In this workspace it is almost certainly *everything*,
# MAGIC because nothing we built today was tagged. That is the lesson landing in the most convincing
# MAGIC way available: the query is right, the data is there, and the attribution is still useless.
# MAGIC
# MAGIC If a large share of spend is untagged, the per-client figures are not trustworthy and the
# MAGIC tagging needs fixing before anyone quotes them.
# MAGIC
# MAGIC `billing_origin_product` splits pipeline compute from dashboard and Genie usage, which matters
# MAGIC because they scale with different things: pipelines with data volume, dashboards and Genie with
# MAGIC how many people are asking questions.

# COMMAND ----------

# MAGIC %md
# MAGIC ## The dashboard table
# MAGIC
# MAGIC The dashboard's cost page reads a table, not `system.billing` directly, so the query above runs
# MAGIC once on a schedule rather than on every dashboard load.

# COMMAND ----------

COST_TABLE = f"{CATALOG}.{OPS}.cost_per_client"

if billing_available:
    spark.sql(f"CREATE OR REPLACE TABLE {COST_TABLE} AS {cost_per_client_sql}")
else:
    # Empty but correctly shaped, so the dashboard page still renders.
    spark.sql(f"""
      CREATE TABLE IF NOT EXISTS {COST_TABLE} (
        client                STRING COMMENT 'From the client tag on the job run',
        category              STRING COMMENT 'pipeline, dashboard or Genie',
        dbus                  DOUBLE,
        estimated_usd         DOUBLE,
        days_active           INT,
        projected_monthly_usd DOUBLE
      )
    """)

print(f"{COST_TABLE}: {spark.table(COST_TABLE).count()} rows")
display(spark.table(COST_TABLE))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next
# MAGIC
# MAGIC - Tag on day one. Attribution cannot be backdated, and one job run per client is a
# MAGIC   prerequisite rather than an optimisation.
# MAGIC - Check untagged spend before trusting any figure.
# MAGIC - Apply your organisation's own pricing to `list_prices` before treating a number as real.
# MAGIC - Guardrails worth setting now: warehouse auto-stop, budget policies by tag, and Genie rate
# MAGIC   limits. All three are cheaper to configure than to retrofit after a surprise bill.