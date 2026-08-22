# Databricks notebook source
# MAGIC %md
# MAGIC # 07. Governance foundation: row-level security on the consolidated table
# MAGIC
# MAGIC Agenda item 6. In the session this is introduced conceptually; this notebook is the optional
# MAGIC worked example (a POC nice-to-have) that makes it concrete.
# MAGIC
# MAGIC It is the governance foundation the whole roadmap rests on: the client-facing product
# MAGIC must guarantee one client can **never** see another client's data. This shows how Unity Catalog
# MAGIC enforces that once, on the table, so it holds everywhere the table is read.
# MAGIC
# MAGIC To make the effect obvious we build the **same table twice**, from the same source rows:
# MAGIC
# MAGIC | Table | Row filter |
# MAGIC |---|---|
# MAGIC | `gold_all_clients_master_unfiltered` | none, every client visible |
# MAGIC | `gold_all_clients_master_filtered` | Unity Catalog row filter |
# MAGIC
# MAGIC Running the identical query against both is the demonstration: same data, same SQL, different
# MAGIC result. In production you keep only the filtered one.
# MAGIC
# MAGIC The filter goes **on the table, in Unity Catalog**, not in the dashboard. That matters: a
# MAGIC filter in a dashboard is only as good as the dashboard, and is bypassed by anyone who queries
# MAGIC the table directly. Enforced in Unity Catalog it applies everywhere at once: SQL editor,
# MAGIC notebooks, dashboards, Genie, Databricks Apps, and any external tool connecting over
# MAGIC JDBC or ODBC (including Power BI).

# COMMAND ----------

CATALOG = "enablement"
GOLD, OPS = "04_gold", "05_ops"
PRIMARY_CLIENT = "helix_biosciences"
SECONDARY_CLIENT = "orbital_instruments"

SOURCE = f"{CATALOG}.{GOLD}.gold_all_clients_master"   # built in notebook 04
ENTITLEMENTS = f"{CATALOG}.{OPS}.client_entitlements"

ALL_CLIENTS_UNFILTERED = f"{CATALOG}.{GOLD}.gold_all_clients_master_unfiltered"
ALL_CLIENTS_FILTERED = f"{CATALOG}.{GOLD}.gold_all_clients_master_filtered"

if not spark.catalog.tableExists(SOURCE):
    raise RuntimeError(f"{SOURCE} not found. Run notebook 04 first to build the consolidated table.")

current_user = spark.sql("SELECT current_user()").collect()[0][0]
print(f"Running as: {current_user}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: who is allowed to see what
# MAGIC
# MAGIC A plain table mapping users to clients. Access control as data, so entitlements can be granted
# MAGIC without a deployment.
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
# MAGIC Copy the consolidated table twice. Both start out identical.
# MAGIC
# MAGIC Note these are point-in-time copies, not views: **re-run this notebook after anything that
# MAGIC changes gold**, or the filtered table shows stale numbers.

# COMMAND ----------

combined = spark.table(SOURCE)

for target in (ALL_CLIENTS_UNFILTERED, ALL_CLIENTS_FILTERED):
    # Drop first: an existing row filter would otherwise apply to the rows being written,
    # so a re-run would persist only the rows this user can currently see.
    spark.sql(f"DROP TABLE IF EXISTS {target}")
    combined.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(target)

print(f"Built both tables from {SOURCE}")

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
         COUNT(*) AS rows, SUM(leads) AS leads
  FROM {ALL_CLIENTS_UNFILTERED} GROUP BY client_id
  UNION ALL
  SELECT 'filtered', client_id,
         COUNT(*), SUM(leads)
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

print(f"unfiltered, all clients:              {total:,} rows")
print(f"filtered, {PRIMARY_CLIENT}:   {visible:,} rows")
print(f"filtered, {SECONDARY_CLIENT}: {blocked:,} rows")
print("\nPASS: only entitled rows are returned" if blocked == 0 and visible > 0
      else "CHECK: entitlements may not be set as expected")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Where the filter shows up
# MAGIC
# MAGIC It is a property of the table, so it is visible to anyone inspecting it and cannot be
# MAGIC sidestepped by querying differently. This is the first thing to check when someone reports that
# MAGIC their data has disappeared.

# COMMAND ----------

display(spark.sql(f"DESCRIBE EXTENDED {ALL_CLIENTS_FILTERED}").filter("col_name LIKE '%Filter%'"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Two things to carry forward
# MAGIC
# MAGIC **Column masking is the same idea per column.** Where a row filter hides whole rows, a mask
# MAGIC nulls or redacts one column, which suits a case like showing a client their engagement but not
# MAGIC an internal margin field:
# MAGIC
# MAGIC ```sql
# MAGIC CREATE OR REPLACE FUNCTION enablement.05_ops.mask_leads(leads_param BIGINT)
# MAGIC RETURN CASE WHEN is_account_group_member('internal') THEN leads_param ELSE NULL END;
# MAGIC
# MAGIC ALTER TABLE <table> ALTER COLUMN leads SET MASK enablement.05_ops.mask_leads;
# MAGIC ```
# MAGIC
# MAGIC **Dashboards and apps must not embed credentials.** Publish with `embed_credentials = false`,
# MAGIC otherwise every viewer sees the data through the publisher's entitlements and the filter is
# MAGIC silently bypassed. This is the single most common way row-level security is undone in practice,
# MAGIC and it is the exact failure the client-facing product cannot afford.
