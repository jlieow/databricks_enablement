# Databricks notebook source
# MAGIC %md
# MAGIC # 06. Per-client cost visibility
# MAGIC
# MAGIC Agenda item 5. How to answer "what does this client cost us", and how it compares against the
# MAGIC customer's current cloud spend today.
# MAGIC
# MAGIC **The one thing that matters here is the first section.** Cost attribution depends entirely on
# MAGIC tags applied when a job runs, and tags cannot be applied retrospectively. Untagged compute from
# MAGIC month one is permanently unattributable.
# MAGIC
# MAGIC Usage data lives in `system.billing`, which Unity Catalog exposes as ordinary tables. So this
# MAGIC is the same SQL you have been writing all session, pointed at the platform's own telemetry.

# COMMAND ----------

CATALOG = "enablement"
OPS = "05_ops"

# The system tables are governed, so a workspace may simply not have granted them. Check rather
# than fail three cells later. On Free Edition billing may not be exposed at all, which the
# fallback below handles so the dashboard's cost page still renders.
billing_available = False
try:
    spark.sql("SELECT 1 FROM system.billing.usage LIMIT 1").collect()
    billing_available = True
    print("system.billing.usage is readable.")
except Exception as e:
    print(f"system.billing.usage not readable ({type(e).__name__}).")
    print("On Free Edition this is expected. On the customer's cloud workspace, ask an account")
    print("admin to grant the system.billing schema, then re-run.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: tag everything, before you need the data
# MAGIC
# MAGIC This is the whole game. Tag the job, and every usage record it generates carries the tag.
# MAGIC
# MAGIC ```hcl
# MAGIC tags = {
# MAGIC   client      = "helix_biosciences"
# MAGIC   cost_center = "client_delivery"
# MAGIC }
# MAGIC ```
# MAGIC
# MAGIC **One job run per client.** A single job processing every client cannot be split by client
# MAGIC afterwards, at any price. That is why notebook 04 onboards each client as its own run, and it
# MAGIC is a pipeline design decision driven by a finance requirement, so it is worth settling early.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: cost per client
# MAGIC
# MAGIC The headline number: what each client costs to run, per category.
# MAGIC
# MAGIC Note `list_prices` gives the **list** rate, so apply your organisation's own pricing before
# MAGIC treating any of these as a real figure to compare against the current cloud spend.

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
# MAGIC tagging needs fixing before anyone quotes them to leadership.
# MAGIC
# MAGIC `billing_origin_product` splits pipeline compute from dashboard and Genie usage, which matters
# MAGIC because they scale with different things: pipelines with data volume, dashboards and Genie with
# MAGIC how many people are asking questions. That split is exactly the extrapolation basis for the
# MAGIC January products.

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
    # Empty but correctly shaped, so the dashboard page still renders on Free Edition.
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
# MAGIC - Apply your organisation's own pricing to `list_prices`, then compare against the current
# MAGIC   cloud warehouse-plus-integration spend to make the readout like for like.
# MAGIC - Cost levers worth setting now: SQL warehouse auto-stop and right-sizing, budget policies by
# MAGIC   tag, and Genie rate limits. All three are cheaper to configure than to retrofit after a
# MAGIC   surprise bill.
