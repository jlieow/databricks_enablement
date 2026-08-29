# Databricks notebook source
# MAGIC %md
# MAGIC # 14. Genie space over the consolidated clinical gold table
# MAGIC
# MAGIC Builds a single Genie space over the **consolidated** `gold_all_districts_master` table.
# MAGIC Row-level security applied via Unity Catalog ensures each district user sees only their data.

# COMMAND ----------

CATALOG = "enablement"
GOLD = "04_gold"

CONSOLIDATED_TABLE = f"{CATALOG}.{GOLD}.gold_all_districts_master"
SILVER_TABLE = f"{CATALOG}.03_silver.silver_northmoor_district_encounters"

WAREHOUSE_ID = "PASTE_YOUR_WAREHOUSE_ID"

# Check that tables exist
for t in (CONSOLIDATED_TABLE, SILVER_TABLE):
    try:
        if spark.catalog.tableExists(t):
            print(f"Found: {t}")
    except Exception as e:
        print(f"Warning: {t} may not exist")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Comment the consolidated table

# COMMAND ----------

spark.sql(f"""
  COMMENT ON TABLE {CONSOLIDATED_TABLE} IS
  'Consolidated clinical encounters across all districts. Row filter restricts each user to their entitled district.'
""")

COLUMN_COMMENTS = {
    "district_id":              "Health district (row filter applied).",
    "stream":                   "Clinical stream: outpatient_visits, inpatient_admissions, or lab_results.",
    "patient_id":               "De-identified patient identifier.",
    "encounter_id":             "Unique encounter identifier.",
    "visit_date":               "Date encounter occurred.",
    "readmission_rate_pct":     "Readmission rate: readmissions / encounters * 100.",
}

existing = {f.name for f in spark.table(CONSOLIDATED_TABLE).schema.fields}
for col, comment in COLUMN_COMMENTS.items():
    if col in existing:
        spark.sql(f"ALTER TABLE {CONSOLIDATED_TABLE} ALTER COLUMN {col} COMMENT '{comment}'")

print(f"Commented {len(existing & set(COLUMN_COMMENTS))} columns")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Create the Genie space

# COMMAND ----------

import json
import uuid
from databricks.sdk import WorkspaceClient

def uid():
    return uuid.uuid4().hex

def by_id(items):
    return sorted(items, key=lambda x: x["id"])

TEXT_INSTRUCTIONS = [
    "Never average readmission_rate_pct. Recalculate from totals.",
    "This table includes all districts. Filter by district_id to focus on one.",
    "visit_date is when the encounter occurred.",
]

MEASURES = [
    ("total_encounters", "SUM(total_encounters)", "Total Encounters", ["encounters"]),
    ("readmission_rate", "SUM(readmission_count) * 100.0 / NULLIF(SUM(total_encounters), 0)", "Readmission Rate %", ["readmission rate"]),
]

SAMPLE_QUESTIONS = [
    "Which district had the highest readmission rate?",
    "Show me encounters by stream",
]

serialized_space = {
    "version": 2,
    "config": {
        "sample_questions": by_id([{"id": uid(), "question": [q]} for q in SAMPLE_QUESTIONS]),
    },
    "data_sources": {
        "tables": sorted([
            {
                "identifier": CONSOLIDATED_TABLE,
                "description": ["All clinical encounters across all districts."],
                "column_configs": [
                    {"column_name": c, "description": [COLUMN_COMMENTS.get(c, "")], "synonyms": []}
                    for c in sorted(c for c in COLUMN_COMMENTS if c in existing)
                ],
            },
        ], key=lambda t: t["identifier"]),
    },
    "instructions": {
        "text_instructions": [{"id": uid(), "content": TEXT_INSTRUCTIONS}],
        "sql_snippets": {
            "measures": by_id([
                {"id": uid(), "alias": a, "sql": [s], "display_name": d, "synonyms": syn}
                for a, s, d, syn in MEASURES
            ]),
        },
    },
}

w = WorkspaceClient()
TITLE = "Clinical Encounters - All Districts"

payload = {
    "title": TITLE,
    "description": "Consolidated clinical encounters. Row filters apply per district.",
    "warehouse_id": WAREHOUSE_ID,
    "serialized_space": json.dumps(serialized_space),
}

try:
    spaces = w.api_client.do("GET", "/api/2.0/genie/spaces").get("spaces", [])
    match = next((s for s in spaces if s.get("title") == TITLE), None)

    if match:
        space_id = match["space_id"]
        w.api_client.do("PATCH", f"/api/2.0/genie/spaces/{space_id}", body=payload)
        print(f"Updated space {space_id}")
    else:
        space_id = w.api_client.do("POST", "/api/2.0/genie/spaces", body=payload)["space_id"]
        print(f"Created space {space_id}")

    print(f"\nOpen: https://{spark.conf.get('spark.databricks.workspaceUrl')}/genie/rooms/{space_id}")
except Exception as e:
    print(f"Could not create Genie space: {e}")
    if "warehouse" in str(e).lower():
        print("Set WAREHOUSE_ID to a valid SQL Warehouse ID")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key advantages
# MAGIC
# MAGIC - One space to maintain instead of per-district
# MAGIC - Row filter is source of truth
# MAGIC - Scales to any number of districts
# MAGIC - Same UI, different data per user
