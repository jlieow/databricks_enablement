# Databricks notebook source
# MAGIC %md
# MAGIC # 05. Extracting structured data from clinical notes with AI functions
# MAGIC
# MAGIC Agenda item 4. Clinical notes are free text: narrative summaries of patient visits, test results,
# MAGIC diagnoses, treatment plans. Structured extraction turns that text into database fields so it can
# MAGIC be aggregated and analyzed.
# MAGIC
# MAGIC This notebook demonstrates **built-in AI functions** (`ai_extract`, `ai_classify`, `ai_parse_document`)
# MAGIC that call a managed large language model to extract structured fields from free text.
# MAGIC
# MAGIC ### What this notebook does
# MAGIC 1. Creates a small table of synthetic clinical notes
# MAGIC 2. Uses `ai_extract` to pull structured fields (follow_up_required, mentioned_conditions)
# MAGIC 3. Teaches the clinical nuance: a condition MENTIONED in a note is not the same as a CONFIRMED diagnosis
# MAGIC 4. Handles the case where AI functions are not available in the workspace (graceful fallback)
# MAGIC
# MAGIC ### Why this matters
# MAGIC Classical text mining (keyword counting, regular expressions) is brittle. LLM-based extraction
# MAGIC understands context. "Possible hypertension" is different from "confirmed hypertension". This
# MAGIC notebook shows how to build that distinction into the extraction logic.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1: Check if AI functions are available
# MAGIC
# MAGIC AI functions like `ai_extract` may not be enabled in all regions or workspaces. The only
# MAGIC reliable check is to actually call one on a tiny input and see whether it resolves: built-in
# MAGIC functions do not appear in `information_schema`, so probing that would give a false positive.
# MAGIC We run one small `ai_extract` and fall back gracefully if it errors.

# COMMAND ----------

CATALOG = "enablement"
GOLD = "04_gold"

# Probe with a one-row call. If AI functions are not enabled here, this raises, and we skip the
# extraction path so the notebook still completes on Free Edition or a region without them.
try:
    spark.sql(
        "SELECT ai_extract('Patient reports a cough.', array('symptom')) AS probe"
    ).collect()
    ai_available = True
    print("AI functions are available.")
except Exception as e:
    ai_available = False
    print(f"AI functions not available: {type(e).__name__}")
    print("\nThis is expected on Free Edition or some regions.")
    print("The reference pattern is shown below, but the extraction step is skipped.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: Create synthetic clinical notes
# MAGIC
# MAGIC In the real build these come from the client's clinical documentation system.
# MAGIC Here we create a small synthetic set to teach the extraction pattern.

# COMMAND ----------

from pyspark.sql import functions as F

notes_data = [
    ("E001", "2026-07-05", "northmoor_district", 
     "Patient presents with persistent cough and fatigue for 2 weeks. History of hypertension controlled on medications. "
     "CXR shows possible pneumonia. Started on antibiotics. Follow-up imaging in 1 week."),
    ("E002", "2026-07-06", "northmoor_district",
     "Routine diabetes checkup. Blood glucose 145 mg/dL, BP 128/82. Patient reports good medication adherence. "
     "No new symptoms. Continue current regimen. Next visit 3 months."),
    ("E003", "2026-07-07", "eldervale_district",
     "Patient reports dyspnea on exertion. History of congestive heart failure. Previous EF 35%. "
     "Echocardiogram ordered to assess current function. May need medication adjustment."),
    ("E004", "2026-07-08", "eldervale_district",
     "Routine checkup. Patient reports occasional headaches, no other complaints. BP normal, exam unremarkable. "
     "Reassured patient, no treatment needed."),
]

notes_df = spark.createDataFrame(
    notes_data,
    ["encounter_id", "visit_date", "district_id", "clinical_note_text"]
)

print("Clinical notes to extract from:")
notes_df.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3: Extract structured fields with AI functions
# MAGIC
# MAGIC `ai_extract(content, array(labels))` returns a struct with one field per label, each holding the
# MAGIC text the model found for that label. It is a SQL function, so we register the notes as a
# MAGIC temporary view and call it from SQL. We ask for the labels separately for **mentioned** versus
# MAGIC **confirmed** conditions, which is the clinical nuance the next section is about, and use
# MAGIC `ai_classify` for the yes/no follow-up decision.

# COMMAND ----------

if not ai_available:
    print("Skipping AI extraction (functions not available).")
    print("In the real build, the team would:")
    print("1. Check region availability with the account team")
    print("2. Extract with ai_extract using labels that separate mention from diagnosis:")
    print("""
      SELECT
        encounter_id,
        ai_extract(clinical_note_text,
          array('mentioned_conditions', 'confirmed_diagnoses', 'recommended_tests')) AS fields,
        ai_classify(clinical_note_text,
          array('follow_up_required', 'no_follow_up')) AS follow_up
      FROM clinical_notes
    """)
else:
    notes_df.createOrReplaceTempView("clinical_notes")

    # ai_extract returns a struct keyed by the labels we pass; ai_classify picks one label.
    extracted_flat = spark.sql("""
      SELECT
        encounter_id,
        visit_date,
        district_id,
        fields.mentioned_conditions  AS mentioned_conditions,
        fields.confirmed_diagnoses   AS confirmed_diagnoses,
        fields.recommended_tests     AS recommended_tests,
        follow_up
      FROM (
        SELECT
          encounter_id, visit_date, district_id,
          ai_extract(
            clinical_note_text,
            array('mentioned_conditions', 'confirmed_diagnoses', 'recommended_tests')
          ) AS fields,
          ai_classify(clinical_note_text, array('follow_up_required', 'no_follow_up')) AS follow_up
        FROM clinical_notes
      )
    """)

    print("Extracted fields:")
    extracted_flat.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4: The clinical nuance lesson
# MAGIC
# MAGIC **Mention is not diagnosis.** This is the hardest pattern to teach an LLM.
# MAGIC
# MAGIC Example: "Patient with history of hypertension" (mention, prior diagnosis)
# MAGIC vs. "Patient diagnosed with hypertension today" (confirmed today).
# MAGIC
# MAGIC The extraction schema above separates `mentioned_conditions` from `confirmed_diagnoses`.
# MAGIC A downstream quality check should flag any row where something is in `mentioned_conditions`
# MAGIC but not in `confirmed_diagnoses`, so a clinician can verify.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5: Storing the extracted data
# MAGIC
# MAGIC In production, extracted fields join back to the encounter table in Silver or Gold,
# MAGIC and become available for aggregation and dashboarding.
# MAGIC
# MAGIC For now, we just show the pattern. In the real pipeline, this would be a step inside
# MAGIC a Lakeflow pipeline or a notebook called by a daily job.

# COMMAND ----------

if ai_available:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.03_silver")
    
    # Store the extracted data (this would normally happen during the medallion transform)
    table_name = f"{CATALOG}.03_silver.silver_extracted_fields"
    extracted_flat.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table_name)
    
    print(f"Extracted fields stored in {table_name}")
else:
    print("Extraction skipped; table not created.")

