# Databricks notebook source
# MAGIC %md
# MAGIC # 04. Onboarding a second client with no new code
# MAGIC
# MAGIC The notebook that proves the commercial argument the customer cares about: onboarding a client
# MAGIC is **configuration, not development**. That is what makes a client-facing product
# MAGIC affordable to run across many clients.
# MAGIC
# MAGIC The proof is deliberately literal. Rather than a template function that reimplements the
# MAGIC pipeline, this notebook **runs notebooks 02 and 03 unchanged**, passing a different `client_id`.
# MAGIC If a second client needed so much as one edited line, that would show up here immediately.
# MAGIC
# MAGIC The second client is not a clone of the first: **Orbital Instruments** has fewer campaigns and
# MAGIC a late-arriving webinar file. A template that only worked for identically shaped clients would
# MAGIC not prove much.

# COMMAND ----------

CATALOG = "enablement"
GOLD = "04_gold"

PRIMARY_CLIENT = "helix_biosciences"
SECONDARY_CLIENT = "orbital_instruments"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run the existing notebooks for the new client
# MAGIC
# MAGIC `dbutils.notebook.run()` calls a notebook with its widgets set. These are the same two
# MAGIC notebooks already run for Helix, with one argument different.
# MAGIC
# MAGIC The files for this client must already be in `landing/orbital_instruments/`. All three
# MAGIC notebooks (02, 03, and this one) must sit in the same folder, which is how they are
# MAGIC distributed.

# COMMAND ----------

for nb in ["02_ingest_csv_autoloader", "03_medallion_transform"]:
    print(f"Running {nb} for {SECONDARY_CLIENT} ...")
    dbutils.notebook.run(nb, 1800, {"client_id": SECONDARY_CLIENT})
    print("  done")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Both clients, side by side
# MAGIC
# MAGIC Same code produced both. Different campaign counts and tactics, one consistent report shape,
# MAGIC which is what lets one dashboard and one Genie space serve every client.

# COMMAND ----------

display(spark.sql(f"""
  SELECT client_id,
         COUNT(*) AS rows,
         COUNT(DISTINCT campaign_id) AS campaigns,
         COUNT(DISTINCT tactic) AS tactics,
         SUM(impressions) AS impressions,
         SUM(engagements) AS engagements,
         SUM(leads)       AS leads
  FROM (
    SELECT * FROM {CATALOG}.{GOLD}.gold_{PRIMARY_CLIENT}_master
    UNION ALL
    SELECT * FROM {CATALOG}.{GOLD}.gold_{SECONDARY_CLIENT}_master
  )
  GROUP BY client_id
  ORDER BY client_id
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Consolidate into one all-clients report table
# MAGIC
# MAGIC The dashboard and Genie space read one table, not one per client, so build the consolidated
# MAGIC table here from whatever per-client master tables exist. Discover them rather than list them,
# MAGIC so onboarding a client picks it up automatically on the next run.
# MAGIC
# MAGIC This is a point-in-time copy, not a view: **re-run this notebook after anything that changes a
# MAGIC client's gold table**, or the consolidated table goes stale.

# COMMAND ----------

from functools import reduce

CONSOLIDATED = f"{CATALOG}.{GOLD}.gold_all_clients_master"

masters = [
    r.table_name for r in spark.sql(f"""
      SELECT table_name FROM {CATALOG}.information_schema.tables
      WHERE table_schema = '{GOLD}'
        AND table_name LIKE 'gold_%_master'
        AND table_name <> 'gold_all_clients_master'
      ORDER BY table_name
    """).collect()
]
if not masters:
    raise RuntimeError("No per-client gold master tables. Run notebook 03 first.")

combined = reduce(
    lambda a, b: a.unionByName(b, allowMissingColumns=True),
    [spark.table(f"{CATALOG}.{GOLD}.{t}") for t in masters],
)
combined.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(CONSOLIDATED)

print(f"Built {CONSOLIDATED} from {masters}")
display(spark.sql(f"""
  SELECT client_id, COUNT(*) AS rows FROM {CONSOLIDATED} GROUP BY client_id ORDER BY client_id
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Onboarding any further client
# MAGIC
# MAGIC 1. Drop the client's files into `landing/<client_id>/`.
# MAGIC 2. Re-run this notebook with `SECONDARY_CLIENT` set to the new `client_id`.
# MAGIC
# MAGIC No new code. In production this becomes a Lakeflow job with `client_id` as a job parameter, so
# MAGIC onboarding is a row in a config table and nothing else. Per-client business rules (which
# MAGIC tactics they run, minimum volumes, source-specific windows) belong in that table too, read by
# MAGIC the notebooks rather than written into them.
# MAGIC
# MAGIC This is also why cost attribution in notebook 06 works: **one job run per client** means each
# MAGIC client's compute carries that client's tag.
# MAGIC
# MAGIC The dashboard (agenda item 4) reads `gold_all_clients_master` built above. Notebook 07 shows
# MAGIC how a Unity Catalog row filter would restrict that same table per client, which is the
# MAGIC governance foundation for the client-facing product.
