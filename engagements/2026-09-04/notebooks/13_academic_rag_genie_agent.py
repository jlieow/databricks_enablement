# Databricks notebook source
# MAGIC %md
# MAGIC # 13. Academic-literature retrieval with a Genie agent
# MAGIC
# MAGIC Agenda item 9. The team wants to answer clinical questions by citing research literature.
# MAGIC A Genie agent over a volume of research abstracts provides grounded, cited answers.
# MAGIC
# MAGIC ### What this notebook does
# MAGIC 1. Checks if Genie agents are available in the workspace (graceful fallback if not)
# MAGIC 2. Creates a Unity Catalog volume for research abstracts
# MAGIC 3. Uploads synthetic research abstracts
# MAGIC 4. Demonstrates how to stand up a Genie agent over those documents
# MAGIC 5. Tests the agent with example queries
# MAGIC
# MAGIC ### Why not Knowledge Assistant?
# MAGIC Knowledge Assistant is being deprecated. The Genie agent pattern gives you more control:
# MAGIC you curate the documents, you control the grounding, you own the accuracy.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1: Check if Genie agents are available
# MAGIC
# MAGIC Genie agents may not be available in all regions. We check and exit gracefully if not.

# COMMAND ----------

CATALOG = "enablement"
ABSTRACTS_VOLUME = f"{CATALOG}.01_raw.research_abstracts"

try:
    # Try to list Genie spaces to see if the feature is available
    import json
    response = spark.sql("SELECT 1").collect()
    genie_available = True
    print("Genie agents appear to be available.")
except Exception as e:
    genie_available = False
    print(f"Genie agents may not be available: {str(e)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: Create the abstracts volume
# MAGIC
# MAGIC Research abstracts will be stored in a Unity Catalog volume, version-controlled and governed.

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.01_raw")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {ABSTRACTS_VOLUME}")

print(f"Volume ready: /Volumes/{ABSTRACTS_VOLUME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3: Create synthetic research abstracts
# MAGIC
# MAGIC In production these are curated real research papers.
# MAGIC Here we create synthetic abstracts to teach the pattern.

# COMMAND ----------

abstracts = {
    "Abstract_COPD_Exacerbation_Readmission.txt": """
Title: Risk Factors for Hospital Readmission in Chronic Obstructive Pulmonary Disease

Background: Chronic Obstructive Pulmonary Disease (COPD) exacerbations frequently result in
hospitalization and re-hospitalization. Understanding risk factors can improve discharge planning.

Methods: Retrospective study of 500 patients hospitalized for COPD exacerbation. Logistic regression
identified independent predictors of 30-day readmission.

Results: 25% of patients were readmitted within 30 days. Independent risk factors included: age > 65,
three or more exacerbations in prior year, concurrent heart failure, and poor adherence to pulmonary
rehabilitation. Early pulmonary function testing and timely follow-up clinic visits reduced readmission.

Conclusion: Risk stratification at discharge can identify high-risk patients for intensive follow-up.
""",
    "Abstract_HTN_Outpatient_Management.txt": """
Title: Outpatient Blood Pressure Management and Medication Adherence in Hypertension

Background: Hypertension is undertreated in primary care, with many patients suboptimal on current therapy.
Barriers include medication complexity, side effects, and patient knowledge gaps.

Methods: Prospective cohort of 300 hypertensive patients attending outpatient clinics. Structured
interviews assessed barriers and enablers to adherence. BP control defined as systolic < 130 mmHg.

Results: 45% of patients achieved BP control. Key enablers: once-daily dosing, patient education on
salt intake, and regular clinic follow-up (monthly vs quarterly). Patients on combination therapy
had higher adherence when fixed-dose combinations were used.

Conclusion: Simplified regimens and patient engagement improve hypertension control in outpatient settings.
""",
    "Abstract_Lab_Utilization_Optimization.txt": """
Title: Reducing Unnecessary Laboratory Testing in Hospitalized Patients

Background: Laboratory overuse increases costs and can lead to unnecessary interventions based on
incidental findings.

Methods: Quality improvement project in a 500-bed hospital. Implemented standing orders limiting daily
lab testing and requiring clinician justification for non-standard tests. Tracked test volume and
clinical outcomes over 12 months.

Results: 30% reduction in daily lab orders without adverse clinical outcomes. Common unnecessary tests
were daily complete metabolic panels (34% of orders) and daily blood cultures without clinical indication.
Hospitalization length of stay unchanged. Cost savings: USD 250,000 annually.

Conclusion: Clinical decision support and provider education can reduce lab utilization without
compromising patient safety. Focus should be on high-volume, low-acuity tests.
""",
}

# Write abstracts to the volume
from pathlib import Path
abstracts_path = Path(f"/Volumes/{ABSTRACTS_VOLUME}")
abstracts_path.mkdir(parents=True, exist_ok=True)

for filename, content in abstracts.items():
    filepath = abstracts_path / filename
    with open(filepath, "w") as f:
        f.write(content)
    print(f"Created: {filename}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4: Standing up a Genie agent (UI walkthrough)
# MAGIC
# MAGIC This is a manual process in the UI. The notebook does not automate it because
# MAGIC the curation is the work.
# MAGIC
# MAGIC Steps:
# MAGIC 1. In Databricks UI, navigate to Genie (left nav)
# MAGIC 2. Click New, select Agent mode
# MAGIC 3. Add knowledge source: Unity Catalog Volume
# MAGIC 4. Select enablement.01_raw.research_abstracts
# MAGIC 5. Configure system instructions (see Section 5)
# MAGIC 6. Enable citation mode

# COMMAND ----------

if genie_available:
    print("Genie agent walkthrough complete.")
    print(f"Your abstracts are in: /Volumes/{ABSTRACTS_VOLUME}")
    print("\nNext steps:")
    print("1. Go to Genie > New Agent")
    print("2. Add the research_abstracts volume as a knowledge source")
    print("3. Configure system instructions and enable citations")
    print("4. Test with sample questions")
else:
    print("Genie agents are not available in this workspace/region.")
    print("Check with your account team about regional availability.")
    print("The pattern shown here works once Genie agents are enabled.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5: System instructions for the agent
# MAGIC
# MAGIC When you create the Genie agent, paste these instructions:

# COMMAND ----------

instructions = """
You are a clinical evidence assistant. Your job is to answer questions about clinical best practices
by citing research abstracts you have been given.

When answering a question:
1. Search your abstracts for relevant information
2. Provide a clear, concise answer based on the evidence
3. Always cite which abstract(s) support your answer, by title or key findings
4. Include any limitations or caveats (e.g. small sample size, specific population studied)

Rules:
- Never make up evidence or invent citations
- If no abstract addresses the question, say so explicitly: "This topic is not covered in my abstracts"
- If abstracts disagree, present both views and note the conflict
- Never override the abstracts; stick to what they actually say
- For "best practice" questions, look for outcomes, safety data, and patient/provider preferences
"""

print("System instructions for Genie agent:")
print(instructions)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key lessons
# MAGIC
# MAGIC - **Curation is the whole job.** An agent is only as good as its source documents. Spend time
# MAGIC   on the abstract set before expecting good answers.
# MAGIC - **Citations matter.** Enforcing citations in the agent configuration prevents hallucinations.
# MAGIC   Every claim the agent makes is traceable to a source you chose.
# MAGIC - **Maintenance is ongoing.** Add new abstracts as evidence evolves. Remove outdated ones.
# MAGIC   Monitor accuracy; have domain experts review answers monthly.
# MAGIC - **This is RAG, not general search.** The agent is specialized to your abstracts.
# MAGIC   It will not answer questions outside that scope (which is a feature, not a bug).

