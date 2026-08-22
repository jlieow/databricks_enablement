# Databricks notebook source
# MAGIC %md
# MAGIC # 03. Raw ingestion from an API
# MAGIC
# MAGIC Fetch FX rates from an API and land them in a raw table: fetch, flatten, write.
# MAGIC
# MAGIC Frankfurter serves ECB reference rates and needs no signup, which keeps the session
# MAGIC unblocked. Clients are billed in different currencies, so these rates are what convert spend
# MAGIC to one reporting currency in notebook 04. In production an ad platform API replaces it and
# MAGIC the code shape is identical.

# COMMAND ----------

# FX rates are shared across clients, so there is no client_id widget here.
#
# The dates must cover the ad data, which is why they are explicit rather than "the last N days".
# A window from today would only partly overlap the July sample data, and notebook 04 would then
# report no rate for every ad row outside the overlap. Set these to the range your landing files
# cover.
dbutils.widgets.text("start_date", "2026-06-24", "FX from (YYYY-MM-DD)")
dbutils.widgets.text("end_date", "2026-07-22", "FX to (YYYY-MM-DD)")

CATALOG = "enablement"
RAW_SCHEMA = "01_raw"

TARGET = f"{CATALOG}.{RAW_SCHEMA}.raw_fx_rates"
# The gap-filled version, built at the end of this notebook and read by notebook 04.
FX_DAILY = f"{CATALOG}.{RAW_SCHEMA}.fx_daily_rates"

# COMMAND ----------

import requests
from datetime import date

BASE_CURRENCIES = ["GBP", "EUR"]
QUOTE = "USD"

start_date = date.fromisoformat(dbutils.widgets.get("start_date"))
end_date = date.fromisoformat(dbutils.widgets.get("end_date"))

print(f"Fetching FX for: {start_date} to {end_date}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Call the API
# MAGIC
# MAGIC One request per currency pair. Frankfurter returns a date-keyed object, so the response
# MAGIC needs flattening into rows before it can become a table.

# COMMAND ----------

def fetch_fx(base, quote, start_date, end_date):
    """Fetch a daily FX series from Frankfurter. Returns a list of row dicts."""
    resp = requests.get(
        f"https://api.frankfurter.dev/v1/{start_date.isoformat()}..{end_date.isoformat()}",
        params={"base": base, "symbols": quote},
        timeout=30,
    )
    resp.raise_for_status()

    # Response is {"rates": {"2026-07-01": {"USD": 1.324}, ...}}, so flatten to one row per day.
    return [
        {
            "pair": f"{base}/{quote}",
            "base_currency": base,
            "quote_currency": quote,
            "rate_date": day,
            "rate_close": float(rates[quote]),
        }
        for day, rates in sorted(resp.json()["rates"].items())
        if quote in rates
    ]


rows = []
for base in BASE_CURRENCIES:
    got = fetch_fx(base, QUOTE, start_date, end_date)
    rows.extend(got)
    print(f"  {base}/{QUOTE}  {len(got):>4} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Fail loudly on an empty response
# MAGIC
# MAGIC An empty table looks identical to a day with no activity, so it hides expired credentials
# MAGIC and endpoint changes. Raise instead of writing nothing.

# COMMAND ----------

if not rows:
    raise RuntimeError(
        f"API returned no rows for {start_date} to {end_date}. "
        "Frankfurter needs no key, so this is usually a network issue, "
        "or a window that contains no trading days."
    )

print(f"{len(rows)} rows fetched across {len(BASE_CURRENCIES)} currency pairs.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Write to the raw layer
# MAGIC
# MAGIC Same destination shape as file-based sources (notebook 01). Rates exist only for trading
# MAGIC days, which the next cell deals with.

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, DoubleType

schema = StructType([
    StructField("pair", StringType(), False),
    StructField("base_currency", StringType(), False),
    StructField("quote_currency", StringType(), False),
    StructField("rate_date", StringType(), False),
    StructField("rate_close", DoubleType(), False),
])

df = (
    spark.createDataFrame(rows, schema=schema)
    .withColumn("rate_date", F.to_date("rate_date"))
    .withColumn("_ingested_at", F.current_timestamp())
    # Provenance (mirrors _source_file on file sources).
    .withColumn("_source_api", F.lit("api.frankfurter.dev"))
)

df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET)
print(f"Wrote {df.count():,} rows to {TARGET}")

# COMMAND ----------

display(spark.sql(f"SELECT * FROM {TARGET} ORDER BY rate_date DESC, pair LIMIT 15"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Verify trading days only

# COMMAND ----------

display(spark.sql(f"""
  SELECT date_format(rate_date, 'EEEE') AS day_of_week, COUNT(*) AS rows
  FROM {TARGET}
  GROUP BY 1
  ORDER BY 2 DESC
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ### One rate for every day
# MAGIC
# MAGIC The feed only publishes on trading days, so joining it straight onto ad data leaves every
# MAGIC weekend without a rate. Weekend GBP spend would then convert at 1.0 and report as though it
# MAGIC were USD: understated by about 25%, with nothing failing.
# MAGIC
# MAGIC So fill the gaps once, here, next to the feed that caused them. Notebook 04 then joins this
# MAGIC table and needs no FX logic of its own.

# COMMAND ----------

spark.sql(f"""
  CREATE OR REPLACE TABLE {FX_DAILY} AS
  WITH every_day_and_currency AS (
    -- sequence() builds the full calendar, including the days the feed skipped.
    SELECT d AS rate_date, c.base_currency
    FROM (SELECT explode(sequence(
              (SELECT MIN(rate_date) FROM {TARGET}),
              (SELECT MAX(rate_date) FROM {TARGET}))) AS d)
    CROSS JOIN (SELECT DISTINCT base_currency FROM {TARGET}) c
  )
  SELECT e.rate_date, e.base_currency,
         r.rate_close AS published_rate,
         -- On a day with no published rate, carry the most recent one forward.
         LAST_VALUE(r.rate_close) IGNORE NULLS OVER (
           PARTITION BY e.base_currency ORDER BY e.rate_date
         ) AS rate_to_usd
  FROM every_day_and_currency e
  LEFT JOIN (
    SELECT rate_date, base_currency, rate_close
    FROM {TARGET} WHERE quote_currency = 'USD'
  ) r ON r.rate_date = e.rate_date AND r.base_currency = e.base_currency
""")

print(f"Wrote {FX_DAILY}: {spark.table(FX_DAILY).count():,} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC The weekend rows are the point: no `published_rate`, and Friday's rate carried forward.

# COMMAND ----------

display(spark.sql(f"""
  SELECT rate_date, date_format(rate_date, 'E') AS day, published_rate, rate_to_usd,
         CASE WHEN published_rate IS NULL THEN 'carried forward' ELSE 'published' END AS source
  FROM {FX_DAILY}
  WHERE base_currency = 'GBP'
  ORDER BY rate_date
  LIMIT 10
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next
# MAGIC
# MAGIC - Any API follows this shape: `requests`, flatten the response, write a raw table. Same
# MAGIC   destination as the file sources in notebook 01.
# MAGIC - Fail loudly on an empty response, or a broken feed looks like a quiet day.
# MAGIC - The date range is a widget, so a daily load and a one-off reload run the same code.
# MAGIC
# MAGIC A real ad platform API needs three things Frankfurter does not: a **credential** (notebook 02),
# MAGIC **pagination**, and **retry with backoff** on 429 and 5xx. Each is a topic in its own right,
# MAGIC and none of them changes the shape above.