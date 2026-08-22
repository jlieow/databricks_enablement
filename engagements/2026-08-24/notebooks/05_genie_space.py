# Databricks notebook source
# MAGIC %md
# MAGIC # 05. Genie space over the client master table
# MAGIC
# MAGIC Agenda item 4, the Genie half. **Optional.** The session builds this space in the UI, following
# MAGIC `docs/genie_space_guide.md`, because the curation *is* the work and doing it by hand makes that
# MAGIC obvious. This notebook does the same thing over the REST API, for catching up or for scripting
# MAGIC a space per client.
# MAGIC
# MAGIC The argument either way is the same: **Genie's accuracy comes from metadata, not from the
# MAGIC model.** Comments, named measures and worked examples are what make it right. This matters for
# MAGIC the customer specifically, because the roadmap points a Genie-style experience at
# MAGIC clients, where a confidently wrong number is far worse than "I don't know".
# MAGIC
# MAGIC Two things to know: set `WAREHOUSE_ID` below, and the space is **not** managed by Terraform, so
# MAGIC delete it by hand before tearing the workspace down.

# COMMAND ----------

CATALOG = "enablement"
GOLD, SILVER = "04_gold", "03_silver"
PRIMARY_CLIENT = "helix_biosciences"

WAREHOUSE_ID = "PASTE_YOUR_WAREHOUSE_ID"   # from SQL Warehouses in your workspace

GOLD_TABLE = f"{CATALOG}.{GOLD}.gold_{PRIMARY_CLIENT}_master"
SILVER_TABLE = f"{CATALOG}.{SILVER}.silver_{PRIMARY_CLIENT}_engagement"

# Genie's API rejects the whole request if any referenced table is missing.
for t in (GOLD_TABLE, SILVER_TABLE):
    if not spark.catalog.tableExists(t):
        raise RuntimeError(f"{t} not found. Run notebooks 02 and 03 first.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: comment the table and columns
# MAGIC
# MAGIC **The highest-leverage step, and the one most often skipped.** Genie reads Unity Catalog
# MAGIC comments as its description of the data. A column called `lead_rate_pct` with no comment is a
# MAGIC guess; the same column documented as leads per engagement is not.
# MAGIC
# MAGIC This is worth doing regardless of Genie: the same comments show up in Catalog Explorer for
# MAGIC anyone browsing the table, and they are the semantic layer the customer says it lacks today.

# COMMAND ----------

spark.sql(f"""
  COMMENT ON TABLE {GOLD_TABLE} IS
  'Consolidated daily campaign engagement for a single client, one row per campaign per tactic
   per day. Built from product listing, email blast and webinar exports. Only rows that passed
   data quality validation are included. This is the internal report delivered back about a
   client campaign.'
""")

COLUMN_COMMENTS = {
    "client_id":           "Client identifier. One client per master table.",
    "tactic":              "Marketing tactic: product_listing, email_blast or webinar.",
    "campaign_id":         "Campaign identifier. Unique within a tactic, not across tactics.",
    "campaign_name":       "Human readable campaign name, for example HX_ProteinAssay_Listing.",
    "report_date":         "The date the activity occurred, not the date it was ingested.",
    "impressions":         "Number of times the tactic was shown or delivered (page views, emails delivered, webinar registrations).",
    "engagements":         "Number of engagements: clicks, opens, or webinar attendance. Always less than or equal to impressions.",
    "leads":               "Qualified leads attributed to the campaign. May be restated for up to 30 days.",
    "engagement_rate_pct": "Engagement rate percentage: engagements / impressions * 100. Null when impressions are zero.",
    "lead_rate_pct":       "Lead rate percentage: leads / engagements * 100. Null when engagements are zero.",
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
# MAGIC - **Measures** are named calculations, so "engagement rate" is always computed the right way.
# MAGIC - **Worked examples** show the shape of a correct query.
# MAGIC
# MAGIC The averaging rule is the important one. Averaging a per-row rate weights a campaign with 200
# MAGIC impressions the same as one with 200,000, and it is the most common analytical error in this
# MAGIC domain. It is also the trap benchmarked in step 4.

# COMMAND ----------

TEXT_INSTRUCTIONS = [
    "Never average engagement_rate_pct or lead_rate_pct directly across rows. Recalculate from "
    "totals: engagement rate is SUM(engagements)/SUM(impressions)*100 and lead rate is "
    "SUM(leads)/SUM(engagements)*100. Averaging per-row ratios weights a tiny campaign the same "
    "as a large one.",

    "report_date is when the campaign activity happened, not when the data was loaded. Always "
    "filter and group on report_date for time based questions.",

    "Leads for recent dates may still be restated for up to 30 days. When asked about the last "
    "few days, mention that figures may change.",

    "campaign_id is only unique within a tactic. When counting distinct campaigns across tactics, "
    "group by both tactic and campaign_id.",

    "This table contains only rows that passed data quality validation. Questions about rejected "
    "or flagged data belong to the silver table, where dq_status = 'flagged'.",

    "'Performance' here means efficiency: engagement rate and lead rate. It does not mean volume "
    "(impressions or leads). If a user asks which campaign performed best, ask whether they mean "
    "the most efficient or the largest, unless it is clear from context.",
]

# Named measures: asking for "engagement rate" now uses the correct calculation every time.
MEASURES = [
    ("total_impressions", "SUM(impressions)", "Total Impressions", ["impressions", "reach", "views"]),
    ("total_leads", "SUM(leads)", "Total Leads", ["leads", "conversions"]),
    ("engagement_rate", "SUM(engagements) * 100.0 / NULLIF(SUM(impressions), 0)",
     "Engagement Rate %", ["engagement rate", "engagement"]),
    ("lead_rate", "SUM(leads) * 100.0 / NULLIF(SUM(engagements), 0)",
     "Lead Rate %", ["lead rate", "conversion rate"]),
]

EXAMPLE_SQLS = [
    ("What were total leads by tactic last week?",
     f"""SELECT tactic, SUM(leads) AS leads,
       SUM(impressions) AS impressions, SUM(engagements) AS engagements
FROM {GOLD_TABLE}
WHERE report_date >= DATE_SUB((SELECT MAX(report_date) FROM {GOLD_TABLE}), 7)
GROUP BY tactic ORDER BY leads DESC"""),

    # Deliberately recomputes engagement rate from totals rather than averaging the row column.
    ("Which campaign had the best engagement rate?",
     f"""SELECT campaign_name, tactic, SUM(impressions) AS impressions, SUM(engagements) AS engagements,
       ROUND(SUM(engagements) * 100.0 / NULLIF(SUM(impressions), 0), 3) AS engagement_rate_pct
FROM {GOLD_TABLE}
GROUP BY campaign_name, tactic
HAVING SUM(impressions) > 1000
ORDER BY engagement_rate_pct DESC"""),

    ("Which campaign generated the most leads per engagement?",
     f"""SELECT campaign_name, tactic, SUM(engagements) AS engagements, SUM(leads) AS leads,
       ROUND(SUM(leads) * 100.0 / NULLIF(SUM(engagements), 0), 3) AS lead_rate_pct
FROM {GOLD_TABLE}
GROUP BY campaign_name, tactic
HAVING SUM(engagements) > 100
ORDER BY lead_rate_pct DESC"""),
]

SAMPLE_QUESTIONS = [
    "What were total leads by tactic last week?",
    "Which campaign had the best engagement rate?",
    "Show me daily impressions and engagements for the last 14 days",
    "Which tactic generates the most leads?",
]

SYNONYMS = {
    "impressions": ["reach", "views", "delivered"],
    "engagements": ["clicks", "opens", "attendance"],
    "leads": ["conversions", "signups"],
    "engagement_rate_pct": ["engagement rate", "engagement"],
    "report_date": ["date", "day"],
    "campaign_name": ["campaign"],
    "tactic": ["channel", "activity", "source"],
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
                "description": ["Consolidated daily campaign engagement per campaign, tactic and "
                                "day. The primary table for performance questions."],
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
TITLE = f"Campaign Engagement - {PRIMARY_CLIENT}"

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
# MAGIC answer: `AVG(engagement_rate_pct)` for the first, and for the second, averaging a per-campaign
# MAGIC lead rate instead of dividing total leads by total engagements. Each looks reasonable and is
# MAGIC not. If Genie returns the averaged figure, strengthen the instructions and measures and ask
# MAGIC again.
# MAGIC
# MAGIC This benchmark is the deliverable to keep. Re-run it whenever the space or the data changes.

# COMMAND ----------

BENCHMARK = [
    ("What were total leads?",
     f"SELECT SUM(leads) AS answer FROM {GOLD_TABLE}"),
    ("How many campaigns are there?",
     f"SELECT COUNT(DISTINCT campaign_id) AS answer FROM {GOLD_TABLE}"),
    ("Which tactic had the most leads?",
     f"SELECT tactic AS answer FROM {GOLD_TABLE} GROUP BY tactic ORDER BY SUM(leads) DESC LIMIT 1"),
    ("TRAP: What is the overall engagement rate?",
     f"SELECT ROUND(SUM(engagements)*100.0/NULLIF(SUM(impressions),0), 3) AS answer FROM {GOLD_TABLE}"),
    ("TRAP: What is the overall lead rate?",
     f"SELECT ROUND(SUM(leads)*100.0/NULLIF(SUM(engagements),0), 3) AS answer FROM {GOLD_TABLE}"),
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
# MAGIC **On governance:** this space points at `gold_<client>_master`, one client per table, so
# MAGIC separation here comes from table grants. Point a space at a row-filtered consolidated table
# MAGIC (notebook 07) instead and the filter applies to Genie automatically, because enforcement is in
# MAGIC Unity Catalog rather than in the tool. That is the one-space-for-all-clients option, and the
# MAGIC pattern behind the planned client-facing experience.
