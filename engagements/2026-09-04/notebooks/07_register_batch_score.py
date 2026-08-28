# Databricks notebook source
# MAGIC %md
# MAGIC # 07. Register model champion alias and batch score
# MAGIC
# MAGIC This notebook demonstrates the production ML workflow: register a champion alias on a model
# MAGIC in Unity Catalog, then batch-score a snapshot of the clinical gold table to identify high-risk
# MAGIC patients. This is the operational pattern for patient risk stratification at scale.
# MAGIC
# MAGIC ### Champion-challenger pattern
# MAGIC
# MAGIC In production, you maintain multiple model versions and promote them through stages:
# MAGIC - **Challenger** versions are newly trained models in development or validation
# MAGIC - **Staging** versions are ready for review but not yet approved
# MAGIC - **Champion** is the current production model that scores all new patients
# MAGIC
# MAGIC The champion alias ensures one name points to the right version at any time. Your scoring jobs
# MAGIC always reference `champion`, never a version number, so you swap models without changing code.
# MAGIC
# MAGIC ### Monthly retraining and drift monitoring
# MAGIC
# MAGIC In a production environment, you:
# MAGIC - Retrain monthly on recent clinical data to capture new patterns
# MAGIC - Evaluate new models against the champion on a hold-out test set
# MAGIC - If the challenger significantly outperforms, promote it to champion
# MAGIC - Monitor for data drift: changes in patient populations that degrade model accuracy
# MAGIC
# MAGIC This notebook shows the batch scoring half. The training (notebook 06) runs separately and
# MAGIC returns a model version that you can test, validate, and promote.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration and prerequisites

# COMMAND ----------

import mlflow

CATALOG = "enablement"
SCHEMA = "05_ops"
MODEL_NAME = "patient_risk_stratification_model"
UC_MODEL_NAME = f"{CATALOG}.`{SCHEMA}`.{MODEL_NAME}"

# Register models in Unity Catalog
mlflow.set_registry_uri("databricks-uc")

# This notebook depends on the model that notebook 06 trained and registered.
print(f"Model: {UC_MODEL_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1: Set the champion alias
# MAGIC
# MAGIC Find the latest registered version and point the `champion` alias at it. We use the MLflow
# MAGIC client (`set_registered_model_alias`), which is the supported way to manage Unity Catalog model
# MAGIC aliases. In production you would validate the model against the current champion first and only
# MAGIC promote after it clears your performance thresholds; here we promote the latest version so the
# MAGIC scoring step below has a `@champion` to load.

# COMMAND ----------

from mlflow.tracking import MlflowClient

client = MlflowClient(registry_uri="databricks-uc")

# Latest registered version of the model from notebook 06.
versions = client.search_model_versions(f"name = '{CATALOG}.{SCHEMA}.{MODEL_NAME}'")
if not versions:
    raise RuntimeError(
        f"No versions of {CATALOG}.{SCHEMA}.{MODEL_NAME} found. Run notebook 06 first to train and "
        "register the model."
    )
latest_version = max(versions, key=lambda v: int(v.version))
print(f"Latest model version: {latest_version.version}")

# Create or move the champion alias. set_registered_model_alias is idempotent: it repoints an
# existing alias, so this is safe to re-run.
client.set_registered_model_alias(
    name=f"{CATALOG}.{SCHEMA}.{MODEL_NAME}",
    alias="champion",
    version=int(latest_version.version),
)
print(f"champion -> version {latest_version.version}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: Batch score a cohort with the champion model
# MAGIC
# MAGIC Load the model by its `@champion` alias, not by a version number, so this scoring code never
# MAGIC changes when a new model is promoted. We score the same reference cohort the model was trained
# MAGIC on (the scikit-learn teaching dataset from notebook 06), because the champion expects exactly
# MAGIC those features.
# MAGIC
# MAGIC **In the real build**, this is where you would read engineered clinical features from the gold
# MAGIC table (`gold_<district>_master` and its Silver inputs), one feature row per patient, and score
# MAGIC those instead. The scoring mechanics, load `@champion`, predict, write a results table, are
# MAGIC identical; only the feature source changes. We do not score the gold table here because its
# MAGIC columns are encounter counts and rates, not the trained model's feature space, and scoring a
# MAGIC model on features it was not trained on would produce meaningless risk labels.

# COMMAND ----------

from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split

# Load the champion by alias. Never pin a version here.
champion_model = mlflow.pyfunc.load_model(f"models:/{CATALOG}.{SCHEMA}.{MODEL_NAME}@champion")

# The reference cohort: the same held-out split notebook 06 evaluated on, so the features match the
# model exactly. This is a stand-in for the engineered clinical feature table in the real build.
data = load_breast_cancer(as_frame=True)
_, X_cohort, _, _ = train_test_split(
    data.data, data.target, test_size=0.2, random_state=42, stratify=data.target
)
X_cohort = X_cohort.reset_index(drop=True)
print(f"Scoring a cohort of {len(X_cohort)} records with {X_cohort.shape[1]} features each.")

# Score. The pyfunc flavour returns the class prediction (0 or 1 in this teaching dataset).
predictions = champion_model.predict(X_cohort)

results = X_cohort.copy()
results.insert(0, "cohort_row_id", results.index)
results["risk_prediction"] = predictions
results["risk_category"] = ["higher_risk" if int(p) == 0 else "lower_risk" for p in predictions]

results_df = spark.createDataFrame(results[["cohort_row_id", "risk_prediction", "risk_category"]])

scoring_table = f"{CATALOG}.{SCHEMA}.batch_scoring_results"
results_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(scoring_table)

higher = int((predictions == 0).sum())
lower = int((predictions == 1).sum())
print(f"\nBatch scoring complete. Results saved to {scoring_table}")
print(f"  higher_risk: {higher}")
print(f"  lower_risk:  {lower}")
print("\nNote: labels are from a teaching dataset (malignant=0 mapped to higher_risk), not a clinical")
print("tool. In the real build, features come from the gold clinical tables and labels are clinical.")
display(results_df.limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3: Monitor model and data drift
# MAGIC
# MAGIC In production, you monitor two key things:
# MAGIC
# MAGIC 1. **Model performance drift**: Compare the champion's predictions against actual outcomes
# MAGIC    (did patients we predicted as high-risk actually have adverse events?)
# MAGIC 2. **Data drift**: Watch for changes in the patient population that might degrade predictions
# MAGIC    (different age distribution, comorbidity patterns, etc.)
# MAGIC
# MAGIC **Where the predictions come from.** For this batch build they are in `batch_scoring_results`,
# MAGIC written above. If you also stand up the real-time endpoint (notebook 08), its inference table
# MAGIC `enablement.05_ops.patient_risk_stratification_model_payload` captures every served request and
# MAGIC response, and the same monitoring queries run against it after you unpack its request and
# MAGIC response columns. Either way the monitoring needs a captured prediction to read; batch scoring
# MAGIC and the inference table are the two sources.
# MAGIC
# MAGIC Below are the SQL patterns you would use to track these monthly.

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Pattern 1: Join predictions against actual outcomes (when available)
# MAGIC -- This shows model calibration: are predicted high-risk patients actually high-risk?
# MAGIC --
# MAGIC -- SELECT
# MAGIC --   risk_category,
# MAGIC --   COUNT(*) AS predicted_count,
# MAGIC --   SUM(CASE WHEN actual_adverse_event = 1 THEN 1 ELSE 0 END) AS actual_events,
# MAGIC --   ROUND(SUM(CASE WHEN actual_adverse_event = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS event_rate_pct
# MAGIC -- FROM batch_scoring_results
# MAGIC -- JOIN actual_outcomes ON batch_scoring_results.patient_id = actual_outcomes.patient_id
# MAGIC -- WHERE batch_scoring_results.score_date >= DATE_SUB(CURRENT_DATE(), 30)
# MAGIC -- GROUP BY risk_category
# MAGIC -- ORDER BY risk_category;
# MAGIC --
# MAGIC -- Pattern 2: Monitor patient population shifts
# MAGIC --
# MAGIC -- SELECT
# MAGIC --   DATE_TRUNC('month', visit_date) AS month,
# MAGIC --   COUNT(DISTINCT patient_id) AS unique_patients,
# MAGIC --   AVG(age) AS avg_age,
# MAGIC --   SUM(CASE WHEN comorbidity_count > 3 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS pct_high_comorbidity,
# MAGIC --   AVG(readmission_rate_pct) AS avg_readmission_rate
# MAGIC -- FROM gold_northmoor_district_master
# MAGIC -- GROUP BY DATE_TRUNC('month', visit_date)
# MAGIC -- ORDER BY month DESC;

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next steps
# MAGIC
# MAGIC **Champion-challenger workflow:**
# MAGIC - Retrain monthly using recent clinical data (notebook 06)
# MAGIC - Evaluate the new model against the champion
# MAGIC - If the challenger outperforms significantly, promote it to champion
# MAGIC - Your scoring jobs always reference `@champion`, so no code changes needed
# MAGIC
# MAGIC **Monitoring:**
# MAGIC - Track model calibration: do high-risk predictions match actual outcomes?
# MAGIC - Watch for data drift: population changes that might degrade predictions
# MAGIC - Alert if prediction accuracy drops below threshold
# MAGIC
# MAGIC **Productionizing:**
# MAGIC - Wrap batch scoring in a Databricks job running monthly
# MAGIC - Use the scoring results to flag patients for outreach or intervention
# MAGIC - Log all scoring runs and predictions for audit trail
# MAGIC
# MAGIC **Batch is the serving path for this build.** The scores land in a table, the pipeline writes
# MAGIC them to PostgreSQL (notebook 09), and the app reads them. There is no synchronous call to the
# MAGIC model at request time. If you ever need low-latency, request-time scoring instead, notebook 08
# MAGIC shows how to deploy the same `@champion` model to a real-time Model Serving endpoint. That is an
# MAGIC optional capability, not this build's pattern.
