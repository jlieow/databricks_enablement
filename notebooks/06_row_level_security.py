# Databricks notebook source
# MAGIC %md
# MAGIC # 06. Row-level security on the gold table
# MAGIC
# MAGIC Every client in one consolidated table, where each team sees only their own rows.
# MAGIC
# MAGIC To make the effect obvious we build the **same table twice**, from the same source rows:
# MAGIC
# MAGIC | Table | Row filter |
# MAGIC |---|---|
# MAGIC | `gold_all_clients_master_unfiltered` | none, every client visible |
# MAGIC | `gold_all_clients_master_filtered` | Unity Catalog row filter |
# MAGIC
# MAGIC Running the identical query against both is the demonstration: same data, same SQL, different
# MAGIC result. In production you would keep only the filtered one.
# MAGIC
# MAGIC The filter goes **on the table, in Unity Catalog**, not in the dashboard. That matters: a
# MAGIC filter in a dashboard is only as good as the dashboard, and is bypassed by anyone who queries
# MAGIC the table directly. Enforced in Unity Catalog it applies everywhere at once: SQL editor,
# MAGIC notebooks, dashboards, Genie, and any external tool connecting over JDBC or ODBC.

# COMMAND ----------

CATALOG = "enablement"
GOLD, OPS = "04_gold", "05_ops"
PRIMARY_CLIENT = "northwind_retail"
SECONDARY_CLIENT = "contoso_travel"

ENTITLEMENTS = f"{CATALOG}.{OPS}.client_entitlements"

ALL_CLIENTS_NAME = "gold_all_clients_master"
ALL_CLIENTS_UNFILTERED = f"{CATALOG}.{GOLD}.{ALL_CLIENTS_NAME}_unfiltered"
ALL_CLIENTS_FILTERED = f"{CATALOG}.{GOLD}.{ALL_CLIENTS_NAME}_filtered"

current_user = spark.sql("SELECT current_user()").collect()[0][0]
print(f"Running as: {current_user}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: who is allowed to see what
# MAGIC
# MAGIC A plain table mapping users to clients. Access control as data, so entitlements can be
# MAGIC granted without a deployment.
# MAGIC
# MAGIC The current user is entitled to **the primary client only**, so the filter has something to
# MAGIC actually hide. Free Edition is single-user, so this is the only way to see the effect.

# COMMAND ----------

spark.sql(f"""
  CREATE OR REPLACE TABLE {ENTITLEMENTS} (
    user_email STRING COMMENT 'Account-level user email',
    client_id  STRING COMMENT 'Client the user may see'
  )
  COMMENT 'Drives the row filter on the consolidated gold table.'
""")

spark.sql(f"INSERT INTO {ENTITLEMENTS} VALUES ('{current_user}', '{PRIMARY_CLIENT}')")

display(spark.table(ENTITLEMENTS))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: build the two consolidated tables
# MAGIC
# MAGIC Union the per-client master tables, then write the result twice. Both start out identical.
# MAGIC
# MAGIC Note these are point-in-time copies, not views: **re-run this notebook after anything that
# MAGIC changes gold**, or the dashboard shows stale numbers.

# COMMAND ----------

from functools import reduce

# Exclude the consolidated tables from their own source list, or the row count grows every run.
masters = [
    r.table_name for r in spark.sql(f"""
      SELECT table_name FROM {CATALOG}.information_schema.tables
      WHERE table_schema = '{GOLD}'
        AND table_name LIKE 'gold_%_master'
        AND table_name NOT LIKE '{ALL_CLIENTS_NAME}%'
      ORDER BY table_name
    """).collect()
]
if not masters:
    raise RuntimeError("No gold master tables. Run notebook 04 first.")

combined = reduce(
    lambda a, b: a.unionByName(b, allowMissingColumns=True),
    [spark.table(f"{CATALOG}.{GOLD}.{t}") for t in masters],
)

for target in (ALL_CLIENTS_UNFILTERED, ALL_CLIENTS_FILTERED):
    # Drop first: an existing row filter would otherwise apply to the rows being written,
    # so a re-run would persist only the rows this user can currently see.
    spark.sql(f"DROP TABLE IF EXISTS {target}")
    combined.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(target)

print(f"Built both tables from {masters}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: the row filter
# MAGIC
# MAGIC A function returning true for rows the caller may see. Unity Catalog calls it per row and
# MAGIC passes the column named in `ON (...)`.
# MAGIC
# MAGIC The `is_account_group_member('admins')` clause is the escape hatch: without something like it,
# MAGIC the pipeline's own service principal cannot read the table it just wrote.
# MAGIC
# MAGIC It is applied to **one** of the two tables.

# COMMAND ----------

spark.sql(f"""
  CREATE OR REPLACE FUNCTION {CATALOG}.{OPS}.client_row_filter(client_id_param STRING)
  RETURN
    is_account_group_member('admins')
    OR EXISTS (
      SELECT 1 FROM {ENTITLEMENTS} e
      WHERE e.user_email = current_user()
        AND e.client_id  = client_id_param
    )
""")

spark.sql(f"""
  ALTER TABLE {ALL_CLIENTS_FILTERED}
  SET ROW FILTER {CATALOG}.{OPS}.client_row_filter ON (client_id)
""")

print(f"Row filter applied to {ALL_CLIENTS_FILTERED}")
print(f"No filter on           {ALL_CLIENTS_UNFILTERED}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Side by side
# MAGIC
# MAGIC The same aggregate against both tables. The filter runs **before** aggregation, so the totals
# MAGIC are correct for what the caller may see rather than being blanked out afterwards.

# COMMAND ----------

display(spark.sql(f"""
  SELECT 'unfiltered' AS table_variant, client_id,
         COUNT(*) AS rows, ROUND(SUM(spend_usd), 2) AS spend_usd
  FROM {ALL_CLIENTS_UNFILTERED} GROUP BY client_id
  UNION ALL
  SELECT 'filtered', client_id,
         COUNT(*), ROUND(SUM(spend_usd), 2)
  FROM {ALL_CLIENTS_FILTERED} GROUP BY client_id
  ORDER BY table_variant, client_id
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC The unfiltered table lists both clients. The filtered one lists only the entitled client, and
# MAGIC an unentitled client returns **no rows rather than an error**, which is the right behaviour: an
# MAGIC error would confirm the data exists.

# COMMAND ----------

visible = spark.sql(
    f"SELECT COUNT(*) AS c FROM {ALL_CLIENTS_FILTERED} WHERE client_id = '{PRIMARY_CLIENT}'"
).collect()[0]["c"]
blocked = spark.sql(
    f"SELECT COUNT(*) AS c FROM {ALL_CLIENTS_FILTERED} WHERE client_id = '{SECONDARY_CLIENT}'"
).collect()[0]["c"]
total = spark.sql(f"SELECT COUNT(*) AS c FROM {ALL_CLIENTS_UNFILTERED}").collect()[0]["c"]

print(f"unfiltered, all clients:            {total:,} rows")
print(f"filtered, {PRIMARY_CLIENT}:   {visible:,} rows")
print(f"filtered, {SECONDARY_CLIENT}:     {blocked:,} rows")
print("\nPASS: only entitled rows are returned" if blocked == 0 and visible > 0
      else "CHECK: entitlements may not be set as expected")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Where the filter shows up
# MAGIC
# MAGIC It is a property of the table, so it is visible to anyone inspecting it and cannot be
# MAGIC sidestepped by querying differently. This is the first thing to check when someone reports
# MAGIC that their data has disappeared.

# COMMAND ----------

display(spark.sql(f"DESCRIBE EXTENDED {ALL_CLIENTS_FILTERED}").filter("col_name LIKE '%Filter%'"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Two things to carry forward
# MAGIC
# MAGIC **Column masking is the same idea per column.** Where a row filter hides whole rows, a mask
# MAGIC nulls or redacts one column, which suits a case like showing campaign performance but not
# MAGIC spend:
# MAGIC
# MAGIC ```sql
# MAGIC CREATE OR REPLACE FUNCTION enablement.05_ops.mask_spend(spend_param DOUBLE)
# MAGIC RETURN CASE WHEN is_account_group_member('finance') THEN spend_param ELSE NULL END;
# MAGIC
# MAGIC ALTER TABLE <table> ALTER COLUMN spend_usd SET MASK enablement.05_ops.mask_spend;
# MAGIC ```
# MAGIC
# MAGIC **Dashboards must not embed credentials.** Publish with `embed_credentials = false`, otherwise
# MAGIC every viewer sees the data through the publisher's entitlements and the filter is silently
# MAGIC bypassed. This is the single most common way row-level security is undone in practice.
