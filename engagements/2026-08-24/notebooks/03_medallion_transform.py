# Databricks notebook source
# MAGIC %md
# MAGIC # 03. Raw to bronze to silver to gold
# MAGIC
# MAGIC Agenda item 3. One table per layer, one job each:
# MAGIC
# MAGIC | Layer | Job |
# MAGIC |---|---|
# MAGIC | Bronze | Combine the tactics, drop duplicates |
# MAGIC | Silver | Tidy the values, mark the bad rows |
# MAGIC | Gold | Keep the good rows, add the report's engagement metrics |
# MAGIC
# MAGIC Every layer is a `CREATE OR REPLACE TABLE ... AS SELECT` passed to `spark.sql()`. Four schemas,
# MAGIC one catalog, one engine: no cluster to size, no connector between layers, and every table below
# MAGIC is queryable by anyone with the grant the moment it is written.
# MAGIC
# MAGIC The gold table is the internal report the customer delivers: one row per campaign per tactic
# MAGIC per day, with engagement and lead metrics, consolidated across the three tactics that raw split
# MAGIC them into.
# MAGIC
# MAGIC The sample data has planted defects, so the checks have something to find.

# COMMAND ----------

dbutils.widgets.text("client_id", "helix_biosciences", "Client ID")
client_id = dbutils.widgets.get("client_id")

CATALOG = "enablement"

# Named once here so the queries below stay short and the layer each table belongs to is
# stated in one place.
raw_product_listing = f"{CATALOG}.01_raw.raw_{client_id}_product_listing"
raw_email_blast = f"{CATALOG}.01_raw.raw_{client_id}_email_blast"
raw_webinar = f"{CATALOG}.01_raw.raw_{client_id}_webinar"

bronze_table = f"{CATALOG}.02_bronze.bronze_{client_id}_engagement"
silver_table = f"{CATALOG}.03_silver.silver_{client_id}_engagement"
gold_table = f"{CATALOG}.04_gold.gold_{client_id}_master"

print(f"Client: {client_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze: combine the tactics and drop duplicates
# MAGIC
# MAGIC Three raw tables become one. `QUALIFY` keeps the newest row per campaign per day, so a tactic
# MAGIC resending a corrected day replaces it rather than doubling it. The sample data resends one
# MAGIC product-listing day for exactly this reason.

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.02_bronze")

spark.sql(f"""
  CREATE OR REPLACE TABLE {bronze_table} AS
  WITH all_tactics AS (
    SELECT * FROM {raw_product_listing}
    UNION ALL
    SELECT * FROM {raw_email_blast}
    UNION ALL
    SELECT * FROM {raw_webinar}
  )
  SELECT * FROM all_tactics
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY client_id, tactic, campaign_id, report_date
    ORDER BY _ingested_at DESC, row_id DESC
  ) = 1
""")

# COMMAND ----------

# MAGIC %md
# MAGIC How many duplicates that removed, as a number you can show rather than assert.

# COMMAND ----------

display(spark.sql(f"""
  SELECT
    (SELECT COUNT(*) FROM {raw_product_listing})
    + (SELECT COUNT(*) FROM {raw_email_blast})
    + (SELECT COUNT(*) FROM {raw_webinar}) AS raw_rows,
    (SELECT COUNT(*) FROM {bronze_table})  AS bronze_rows,
    raw_rows - bronze_rows                 AS duplicates_removed
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Silver: tidy the values, mark the bad rows
# MAGIC
# MAGIC Two things happen here, and the order matters. **Tidy first**, so no check fails on formatting:
# MAGIC `" Product_Listing "` and `"product_listing"` must be the same tactic or the totals split in
# MAGIC two with nothing failing.
# MAGIC
# MAGIC Then **mark, do not delete**. A dropped row is invisible; a marked row is a worklist.
# MAGIC The customer reports these numbers back to a client, so a row cannot be quietly lost, and a
# MAGIC flagged one has to be reviewable.

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.03_silver")

spark.sql(f"""
  CREATE OR REPLACE TABLE {silver_table} AS
  SELECT
    row_id, client_id, report_date, campaign_id,
    impressions, engagements, leads,

    -- Tidy
    LOWER(TRIM(tactic))        AS tactic,        -- " Product_Listing " -> "product_listing"
    TRIM(campaign_name)        AS campaign_name,

    -- Mark. First failing check wins; NULL means the row is clean.
    CASE
      WHEN campaign_id IS NULL OR report_date IS NULL THEN 'missing_key'
      WHEN leads < 0                                  THEN 'negative_leads'
      WHEN engagements > impressions                  THEN 'engagements_exceed_impressions'
    END AS dq_flags,
    CASE WHEN dq_flags IS NULL THEN 'valid' ELSE 'flagged' END AS dq_status,

    -- NULLIF guards the divide: one row with zero impressions would otherwise poison
    -- every downstream average.
    ROUND(engagements * 100.0 / NULLIF(impressions, 0), 3) AS engagement_rate_pct,
    current_timestamp() AS _processed_at
  FROM {bronze_table}
""")

# COMMAND ----------

# MAGIC %md
# MAGIC Adding a client-specific check is one more `WHEN` line above. Here is what it caught:

# COMMAND ----------

display(spark.sql(f"""
  SELECT dq_status, dq_flags, COUNT(*) AS rows
  FROM {silver_table}
  GROUP BY dq_status, dq_flags
  ORDER BY dq_status, dq_flags
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold: one master report table per client
# MAGIC
# MAGIC Valid rows only, with the report's engagement metrics derived once here so every consumer,
# MAGIC dashboard, Genie, Power BI, uses the same definition.
# MAGIC
# MAGIC The two rates are the metrics the customer reports to the client: what share of people who saw
# MAGIC a tactic engaged with it, and what share of those engagements became leads. Computing them here
# MAGIC rather than in each dashboard is what stops three tools disagreeing on "conversion rate".

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.04_gold")

spark.sql(f"""
  CREATE OR REPLACE TABLE {gold_table} AS
  SELECT
    client_id, tactic, campaign_id, campaign_name, report_date,
    impressions, engagements, leads,
    engagement_rate_pct,
    -- Lead rate: leads per engagement. NULLIF guards the divide.
    ROUND(leads * 100.0 / NULLIF(engagements, 0), 3) AS lead_rate_pct
  FROM {silver_table}
  WHERE dq_status = 'valid'
""")

# COMMAND ----------

# MAGIC %md
# MAGIC What reached gold, by tactic. The flagged rows stayed behind in silver, which is the point:
# MAGIC the report is built from validated rows only, and the rejected ones are still there to review.

# COMMAND ----------

display(spark.sql(f"""
  SELECT tactic,
         COUNT(*) AS rows,
         COUNT(DISTINCT campaign_id) AS campaigns,
         SUM(impressions) AS impressions,
         SUM(engagements) AS engagements,
         SUM(leads)       AS leads
  FROM {gold_table}
  GROUP BY tactic
  ORDER BY tactic
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
# MAGIC Notebook 04 onboards the second client, `orbital_instruments`, by running notebooks 02 and 03
# MAGIC unchanged with a different `client_id`. No new code.
