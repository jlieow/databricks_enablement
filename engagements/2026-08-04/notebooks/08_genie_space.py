# Databricks notebook source
# MAGIC %md
# MAGIC # 08. Genie space over the client master table
# MAGIC
# MAGIC **Optional.** The session builds this space in the UI, following `docs/genie_space_guide.md`,
# MAGIC because the curation *is* the work and doing it by hand makes that obvious. This notebook does
# MAGIC the same thing over the REST API, for catching up or for scripting a space per client.
# MAGIC
# MAGIC The argument either way is the same: **Genie's accuracy comes from metadata, not from the
# MAGIC model.** Comments, named measures and worked examples are what make it right.
# MAGIC
# MAGIC Two things to know: set `WAREHOUSE_ID` below, and the space is **not** managed by Terraform, so
# MAGIC delete it by hand before tearing the workspace down.

# COMMAND ----------

CATALOG = "enablement"
GOLD, SILVER = "04_gold", "03_silver"
PRIMARY_CLIENT = "northwind_retail"

WAREHOUSE_ID = "PASTE_YOUR_WAREHOUSE_ID"   # from SQL Warehouses in your workspace

GOLD_TABLE = f"{CATALOG}.{GOLD}.gold_{PRIMARY_CLIENT}_master"
SILVER_TABLE = f"{CATALOG}.{SILVER}.silver_{PRIMARY_CLIENT}_performance"

# Genie's API rejects the whole request if any referenced table is missing.
for t in (GOLD_TABLE, SILVER_TABLE):
    if not spark.catalog.tableExists(t):
        raise RuntimeError(f"{t} not found. Run notebooks 01, 03 and 04 first.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: comment the table and columns
# MAGIC
# MAGIC **The highest-leverage step, and the one most often skipped.** Genie reads Unity Catalog
# MAGIC comments as its description of the data. A column called `cpa` with no comment is a guess; the
# MAGIC same column documented as cost per acquisition in local currency is not.
# MAGIC
# MAGIC This is worth doing regardless of Genie: the same comments show up in Catalog Explorer for
# MAGIC anyone browsing the table.

# COMMAND ----------

spark.sql(f"""
  COMMENT ON TABLE {GOLD_TABLE} IS
  'Consolidated daily advertising performance for a single client, one row per campaign per
   platform per day. Built from Facebook, Google and Snapchat exports plus an FX rate feed.
   Only rows that passed data quality validation are included. spend_local is in the client
   billing currency; spend_usd is converted for cross-client comparison.'
""")

COLUMN_COMMENTS = {
    "client_id":      "Client identifier. One client per master table.",
    "platform":       "Advertising platform: facebook_ads, google_ads or snapchat_ads.",
    "campaign_id":    "Platform campaign identifier. Unique within a platform, not across platforms.",
    "campaign_name":  "Human readable campaign name, for example NW_BrandSearch_UK.",
    "report_date":    "The date the activity occurred, not the date it was ingested.",
    "impressions":    "Number of times an ad was shown.",
    "clicks":         "Number of clicks. Always less than or equal to impressions.",
    "conversions":    "Conversions attributed to the campaign. May be restated by the platform for up to 30 days.",
    "spend_local":    "Media spend in the client billing currency.",
    "local_currency": "ISO code of the billing currency, for example GBP or EUR.",
    "ctr_pct":        "Click-through rate percentage: clicks / impressions * 100. Null when impressions are zero.",
    "fx_rate_to_usd": "Rate used to convert spend_local to USD, from the FX feed for that date.",
    "spend_usd":      "Media spend converted to USD. Use this to compare across currencies.",
}

existing = {f.name for f in spark.table(GOLD_TABLE).schema.fields}
for col, comment in COLUMN_COMMENTS.items():
    if col in existing:
        spark.sql(f"ALTER TABLE {GOLD_TABLE} ALTER COLUMN {col} COMMENT '{comment}'")

print(f"Commented {len(existing & set(COLUMN_COMMENTS))} columns on {GOLD_TABLE}")
display(spark.sql(f"DESCRIBE TABLE {GOLD_TABLE}").select("col_name", "comment"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: the curation that stops specific mistakes
# MAGIC
# MAGIC Three kinds of curation, each one earning its place:
# MAGIC
# MAGIC - **Instructions** are domain rules. Each one below prevents a specific, predictable error.
# MAGIC - **Measures** are named calculations, so "CTR" is always computed the right way.
# MAGIC - **Worked examples** show the shape of a correct query.
# MAGIC
# MAGIC The averaging rule is the important one. Averaging a per-row ratio weights a campaign with 200
# MAGIC impressions the same as one with 200,000, and it is the most common analytical error in this
# MAGIC domain. It is also the trap benchmarked in step 4.

# COMMAND ----------

TEXT_INSTRUCTIONS = [
    "When comparing or totalling spend across clients or currencies, always use spend_usd. "
    "Only use spend_local when the user explicitly asks about one client's billing currency.",

    "Never average ctr_pct directly across rows. Recalculate from totals: CTR is "
    "SUM(clicks)/SUM(impressions)*100 and CPA is SUM(spend_usd)/SUM(conversions). Averaging "
    "per-row ratios weights a tiny campaign the same as a large one.",

    "report_date is when the advertising activity happened, not when the data was loaded. "
    "Always filter and group on report_date for time based questions.",

    "Conversions and spend for recent dates may still be restated by the platforms for up to "
    "30 days. When asked about the last few days, mention that figures may change.",

    "campaign_id is only unique within a platform. When counting distinct campaigns across "
    "platforms, group by both platform and campaign_id.",

    "This table contains only rows that passed data quality validation. Questions about "
    "rejected or flagged data belong to the silver table, where dq_status = 'flagged'.",
]

# Named measures: asking for "CTR" now uses the correct calculation every time.
MEASURES = [
    ("total_spend_usd", "SUM(spend_usd)", "Total Spend (USD)", ["spend", "cost", "budget"]),
    ("ctr", "SUM(clicks) * 100.0 / NULLIF(SUM(impressions), 0)", "Click-Through Rate %",
     ["ctr", "click through rate"]),
    ("cpa", "SUM(spend_usd) / NULLIF(SUM(conversions), 0)", "Cost Per Acquisition (USD)",
     ["cpa", "cost per acquisition", "cost per conversion"]),
    ("cvr", "SUM(conversions) * 100.0 / NULLIF(SUM(clicks), 0)", "Conversion Rate %",
     ["cvr", "conversion rate"]),
]

EXAMPLE_SQLS = [
    ("What was total spend by platform last week?",
     f"""SELECT platform, ROUND(SUM(spend_usd), 2) AS spend_usd,
       SUM(impressions) AS impressions, SUM(clicks) AS clicks
FROM {GOLD_TABLE}
WHERE report_date >= DATE_SUB((SELECT MAX(report_date) FROM {GOLD_TABLE}), 7)
GROUP BY platform ORDER BY spend_usd DESC"""),

    # Deliberately recomputes CTR from totals rather than averaging ctr_pct.
    ("Which campaign had the best click-through rate?",
     f"""SELECT campaign_name, platform, SUM(impressions) AS impressions, SUM(clicks) AS clicks,
       ROUND(SUM(clicks) * 100.0 / NULLIF(SUM(impressions), 0), 3) AS ctr_pct
FROM {GOLD_TABLE}
GROUP BY campaign_name, platform
HAVING SUM(impressions) > 1000
ORDER BY ctr_pct DESC"""),

    ("Which campaign had the lowest cost per acquisition?",
     f"""SELECT campaign_name, platform, SUM(conversions) AS conversions,
       ROUND(SUM(spend_usd) / NULLIF(SUM(conversions), 0), 2) AS cpa_usd
FROM {GOLD_TABLE}
GROUP BY campaign_name, platform
HAVING SUM(conversions) > 0
ORDER BY cpa_usd ASC"""),
]

SAMPLE_QUESTIONS = [
    "What was total spend by platform last week?",
    "Which campaign had the lowest cost per acquisition?",
    "Show me daily impressions and clicks for the last 14 days",
    "Which platform has the best click-through rate?",
]

SYNONYMS = {
    "spend_usd": ["spend", "cost", "media spend"],
    "ctr_pct": ["ctr", "click through rate"],
    "report_date": ["date", "day"],
    "campaign_name": ["campaign"],
    "platform": ["channel", "network", "source"],
}

print(f"{len(TEXT_INSTRUCTIONS)} instructions, {len(MEASURES)} measures, "
      f"{len(EXAMPLE_SQLS)} worked examples, {len(SAMPLE_QUESTIONS)} starter questions")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: create the space
# MAGIC
# MAGIC Four API requirements, all found the hard way and all silent failures if broken: every `id` is
# MAGIC a 32-character lowercase hex UUID with no hyphens; `tables` sorted by `identifier`;
# MAGIC `column_configs` sorted by `column_name`; and `text_instructions` holds **one** entry whose
# MAGIC `content` is the array of rules.
# MAGIC
# MAGIC Re-running updates the existing space rather than creating a duplicate.

# COMMAND ----------

import json
import uuid

from databricks.sdk import WorkspaceClient


def uid():
    return uuid.uuid4().hex


def by_id(items):
    return sorted(items, key=lambda x: x["id"])


serialized_space = {
    "version": 2,
    "config": {
        "sample_questions": by_id([{"id": uid(), "question": [q]} for q in SAMPLE_QUESTIONS]),
    },
    "data_sources": {
        "tables": sorted([
            {
                "identifier": GOLD_TABLE,
                "description": ["Consolidated daily advertising performance per campaign, "
                                "platform and day. The primary table for performance questions."],
                "column_configs": [
                    {"column_name": c, "description": [COLUMN_COMMENTS[c]], "synonyms": SYNONYMS.get(c, [])}
                    for c in sorted(c for c in COLUMN_COMMENTS if c in existing)
                ],
            },
            {
                "identifier": SILVER_TABLE,
                "description": ["Pre-validation data including rows that failed quality checks. "
                                "Use only for questions about rejected or flagged data, where "
                                "dq_status is 'flagged' and dq_flags lists the reasons."],
            },
        ], key=lambda t: t["identifier"]),
    },
    "instructions": {
        "text_instructions": [{"id": uid(), "content": TEXT_INSTRUCTIONS}],
        "example_question_sqls": by_id(
            [{"id": uid(), "question": [q], "sql": [s]} for q, s in EXAMPLE_SQLS]
        ),
        "sql_snippets": {
            "measures": by_id([
                {"id": uid(), "alias": a, "sql": [s], "display_name": d, "synonyms": syn}
                for a, s, d, syn in MEASURES
            ]),
        },
    },
}

w = WorkspaceClient()
TITLE = f"Client Performance - {PRIMARY_CLIENT}"

payload = {
    "title": TITLE,
    "description": "Ad-hoc questions over the consolidated client master table.",
    "warehouse_id": WAREHOUSE_ID,
    "serialized_space": json.dumps(serialized_space),
}

spaces = w.api_client.do("GET", "/api/2.0/genie/spaces").get("spaces", [])
match = next((s for s in spaces if s.get("title") == TITLE), None)

if match:
    space_id = match["space_id"]
    w.api_client.do("PATCH", f"/api/2.0/genie/spaces/{space_id}", body=payload)
    print(f"Updated existing space {space_id}")
else:
    space_id = w.api_client.do("POST", "/api/2.0/genie/spaces", body=payload)["space_id"]
    print(f"Created space {space_id}")

print(f"\nOpen it: https://{spark.conf.get('spark.databricks.workspaceUrl')}/genie/rooms/{space_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: benchmark the answers
# MAGIC
# MAGIC **"It answered" is not "it is right."** Ask Genie each question below and compare against the
# MAGIC known-correct answer computed here.
# MAGIC
# MAGIC The two marked TRAP are the test that curation actually worked. Both have a plausible wrong
# MAGIC answer: `AVG(ctr_pct)` for the first, and for the second, averaging a per-campaign CPA instead
# MAGIC of dividing total spend by total conversions. Each looks reasonable and is not. If Genie
# MAGIC returns the averaged figure, strengthen the instructions and measures and ask again.
# MAGIC
# MAGIC This benchmark is the deliverable to keep. Re-run it whenever the space or the data changes.

# COMMAND ----------

BENCHMARK = [
    ("What was total spend in USD?",
     f"SELECT ROUND(SUM(spend_usd), 2) AS answer FROM {GOLD_TABLE}"),
    ("How many campaigns are there?",
     f"SELECT COUNT(DISTINCT campaign_id) AS answer FROM {GOLD_TABLE}"),
    ("Which platform had the highest spend?",
     f"SELECT platform AS answer FROM {GOLD_TABLE} GROUP BY platform ORDER BY SUM(spend_usd) DESC LIMIT 1"),
    ("TRAP: What is the overall click-through rate?",
     f"SELECT ROUND(SUM(clicks)*100.0/NULLIF(SUM(impressions),0), 3) AS answer FROM {GOLD_TABLE}"),
    ("TRAP: What is the average CPA?",
     f"SELECT ROUND(SUM(spend_usd)/NULLIF(SUM(conversions),0), 2) AS answer FROM {GOLD_TABLE}"),
]

rows = []
for question, sql in BENCHMARK:
    try:
        rows.append((question, str(spark.sql(sql).collect()[0]["answer"])))
    except Exception as e:
        rows.append((question, f"error: {type(e).__name__}"))

display(spark.createDataFrame(rows, ["ask_genie_this", "correct_answer"]))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next
# MAGIC
# MAGIC - Accuracy comes from metadata, not prompt engineering. Comments first, then measures.
# MAGIC - Benchmark against known-correct SQL, and keep the benchmark.
# MAGIC - This space is not managed by Terraform. Delete it by hand at teardown.
# MAGIC
# MAGIC **On row-level security:** this space points at `gold_<client>_master`, which is one client per
# MAGIC table and carries no row filter, so separation here comes from table grants. Point a space at
# MAGIC the filtered consolidated table from notebook 06 instead and the filter applies to Genie
# MAGIC automatically, because enforcement is in Unity Catalog rather than in the tool. That is the
# MAGIC one-space-for-all-clients option discussed in `docs/genie_space_guide.md`.
