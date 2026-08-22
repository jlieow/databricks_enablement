# Databricks notebook source
# MAGIC %md
# MAGIC # 04. Raw to bronze to silver to gold
# MAGIC
# MAGIC One table per layer, one job each:
# MAGIC
# MAGIC | Layer | Job |
# MAGIC |---|---|
# MAGIC | Bronze | Combine the three platforms, drop duplicates |
# MAGIC | Silver | Tidy the values, mark the bad rows |
# MAGIC | Gold | Keep the good rows, convert spend to USD |
# MAGIC
# MAGIC Every layer is a `CREATE OR REPLACE TABLE ... AS SELECT` passed to `spark.sql()`. Four
# MAGIC schemas, one catalog, one engine: no cluster to size, no connector between layers, and every
# MAGIC table below is queryable by anyone with the grant the moment it is written.
# MAGIC
# MAGIC The sample data has planted defects, so the checks have something to find.

# COMMAND ----------

dbutils.widgets.text("client_id", "northwind_retail", "Client ID")
client_id = dbutils.widgets.get("client_id")

CATALOG = "enablement"

# Named once here so the queries below stay short and the layer each table belongs to is
# stated in one place.
raw_facebook = f"{CATALOG}.01_raw.raw_{client_id}_facebook_ads"
raw_google = f"{CATALOG}.01_raw.raw_{client_id}_google_ads"
raw_snapchat = f"{CATALOG}.01_raw.raw_{client_id}_snapchat_ads"
fx_table = f"{CATALOG}.01_raw.fx_daily_rates"

bronze_table = f"{CATALOG}.02_bronze.bronze_{client_id}_performance"
silver_table = f"{CATALOG}.03_silver.silver_{client_id}_performance"
gold_table = f"{CATALOG}.04_gold.gold_{client_id}_master"

print(f"Client: {client_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze: combine the platforms and drop duplicates
# MAGIC
# MAGIC Three raw tables become one. `QUALIFY` keeps the newest row per campaign per day, so a
# MAGIC platform resending a corrected day replaces it rather than doubling it.

# COMMAND ----------

spark.sql(f"""
  CREATE SCHEMA IF NOT EXISTS {CATALOG}.02_bronze
""")

spark.sql(f"""
  CREATE OR REPLACE TABLE {bronze_table} AS
  WITH all_platforms AS (
    SELECT * FROM {raw_facebook}
    UNION ALL
    SELECT * FROM {raw_google}
    UNION ALL
    SELECT * FROM {raw_snapchat}
  )
  SELECT * FROM all_platforms
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY client_id, platform, campaign_id, report_date
    ORDER BY _ingested_at DESC, row_id DESC
  ) = 1
""")

# COMMAND ----------

# MAGIC %md
# MAGIC How many duplicates that removed, as a number you can show rather than assert.

# COMMAND ----------

display(spark.sql(f"""
  SELECT
    (SELECT COUNT(*) FROM {raw_facebook})
    + (SELECT COUNT(*) FROM {raw_google})
    + (SELECT COUNT(*) FROM {raw_snapchat}) AS raw_rows,
    (SELECT COUNT(*) FROM {bronze_table})   AS bronze_rows,
    raw_rows - bronze_rows                  AS duplicates_removed
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Silver: tidy the values, mark the bad rows
# MAGIC
# MAGIC Two things happen here, and the order matters. **Tidy first**, so no check fails on
# MAGIC formatting: `" Facebook_Ads "` and `"facebook_ads"` must be the same platform or the totals
# MAGIC split in two with nothing failing.
# MAGIC
# MAGIC Then **mark, do not delete**. A dropped row is invisible; a marked row is a worklist. An
# MAGIC agency cannot quietly lose client spend.

# COMMAND ----------

spark.sql(f"""
  CREATE SCHEMA IF NOT EXISTS {CATALOG}.03_silver
""")

spark.sql(f"""
  CREATE OR REPLACE TABLE {silver_table} AS
  SELECT
    row_id, client_id, report_date, campaign_id,
    impressions, clicks, conversions,

    -- Tidy
    LOWER(TRIM(platform))           AS platform,       -- " Facebook_Ads " -> "facebook_ads"
    UPPER(TRIM(currency))           AS currency,       -- "gbp"            -> "GBP"
    TRIM(campaign_name)             AS campaign_name,
    ROUND(CAST(spend AS DOUBLE), 2) AS spend,          -- "1950.061"       -> 1950.06

    -- Mark. First failing check wins; NULL means the row is clean.
    CASE
      WHEN campaign_id IS NULL OR report_date IS NULL THEN 'missing_key'
      WHEN spend < 0                                  THEN 'negative_spend'
      WHEN clicks > impressions                       THEN 'clicks_exceed_impressions'
    END AS dq_flags,
    CASE WHEN dq_flags IS NULL THEN 'valid' ELSE 'flagged' END AS dq_status,

    -- NULLIF guards the divide: one row with zero impressions would otherwise poison
    -- every downstream average.
    ROUND(clicks * 100.0 / NULLIF(impressions, 0), 3) AS ctr_pct,
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
# MAGIC ## Gold: one master table per client
# MAGIC
# MAGIC Valid rows only, with spend converted to USD so clients billed in different currencies can be
# MAGIC compared.
# MAGIC
# MAGIC The conversion is an ordinary join because notebook 03 already did the hard part: its
# MAGIC `fx_daily_rates` table has a rate for **every** calendar day, weekends included. Joining the
# MAGIC raw feed here instead would leave every weekend without a rate.

# COMMAND ----------

spark.sql(f"""
  CREATE SCHEMA IF NOT EXISTS {CATALOG}.04_gold
""")

spark.sql(f"""
  CREATE OR REPLACE TABLE {gold_table} AS
  SELECT
    s.client_id, s.platform, s.campaign_id, s.campaign_name, s.report_date,
    s.impressions, s.clicks, s.conversions, s.ctr_pct,
    s.spend    AS spend_local,
    s.currency AS local_currency,
    fx.rate_to_usd                     AS fx_rate_to_usd,
    ROUND(s.spend * fx.rate_to_usd, 2) AS spend_usd
  FROM {silver_table} s
  -- LEFT JOIN, so a currency missing from the feed shows up as a null rate rather than
  -- silently dropping a row of client spend.
  LEFT JOIN {fx_table} fx
    ON fx.rate_date = s.report_date AND fx.base_currency = s.currency
  WHERE s.dq_status = 'valid'
""")

# COMMAND ----------

# MAGIC %md
# MAGIC **`missing_rate` must be zero.** Anything else means the FX dates in notebook 03 do not cover
# MAGIC the ad data, so that spend is missing from `spend_usd` entirely. Widen the dates and re-run 03.

# COMMAND ----------

display(spark.sql(f"""
  SELECT local_currency,
         COUNT(*) AS rows,
         SUM(CASE WHEN fx_rate_to_usd IS NULL THEN 1 ELSE 0 END) AS missing_rate,
         ROUND(SUM(spend_local), 2) AS spend_local,
         ROUND(SUM(spend_usd), 2)   AS spend_usd
  FROM {gold_table}
  GROUP BY local_currency
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## What the platform did for you here
# MAGIC
# MAGIC Nothing above was configured. It came with the workspace:
# MAGIC
# MAGIC - **Lineage.** Open the gold table in Catalog Explorer, then the Lineage tab. The graph back
# MAGIC   to the three CSV files was built from the queries you just ran.
# MAGIC - **Time travel.** `DESCRIBE HISTORY` on any table above shows every version, and
# MAGIC   `VERSION AS OF` reads an old one. A bad load is reversible without a backup.
# MAGIC - **One engine.** Bronze, silver and gold are the same SQL against the same tables. No
# MAGIC   extract step, no separate warehouse to load into.
# MAGIC - **Four schemas, one catalog.** The layers are a naming and grants convention, not four
# MAGIC   systems to keep in step.

# COMMAND ----------

display(spark.sql(f"DESCRIBE HISTORY {gold_table}"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next
# MAGIC
# MAGIC This rebuilds each table from scratch every run, which is the right default and fine at this
# MAGIC size. Two things change at production scale, both covered in a later session:
# MAGIC
# MAGIC - **Incremental loads**, so a daily run touches only the days that changed.
# MAGIC - **Declarative pipelines**, where you write the same `SELECT`s and Databricks works out the
# MAGIC   dependency order, the refresh and the data quality expectations.
