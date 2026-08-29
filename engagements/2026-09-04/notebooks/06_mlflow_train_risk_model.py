# Databricks notebook source
# MAGIC %md
# MAGIC # 06. Train a patient risk stratification model and log it to MLflow
# MAGIC
# MAGIC An optional extra. This notebook trains a simple scikit-learn classifier on CPU, logs it to
# MAGIC MLflow, and registers it in Unity Catalog. It stands alone from the medallion pipeline: it
# MAGIC uses a built-in scikit-learn dataset rather than the clinical tables, so it can run on its own
# MAGIC once the `enablement` catalog exists (notebook 01).
# MAGIC
# MAGIC ### What the model predicts
# MAGIC The model is a binary classifier for patient risk stratification. Given 30 numeric measurements
# MAGIC from a patient profile, it predicts a risk class for an adverse outcome. This demonstration uses the
# MAGIC scikit-learn breast cancer dataset, reframed as a teaching example for binary risk classification:
# MAGIC the malignant label (`0`) stands in for **higher risk** and the benign label (`1`) for **lower
# MAGIC risk**, matching the mapping notebook 07 applies when it batch-scores. This is not a clinical tool —
# MAGIC it is for demonstration purposes only.
# MAGIC
# MAGIC ### What this notebook does
# MAGIC 1. Loads a tabular dataset (scikit-learn breast cancer, reframed as risk data)
# MAGIC 2. Trains a Random Forest classifier on CPU
# MAGIC 3. Evaluates the model on a held-out test set
# MAGIC 4. Logs parameters, metrics, and the model to MLflow under a timestamped run
# MAGIC 5. Registers the model in Unity Catalog, tagged with that timestamp
# MAGIC
# MAGIC ### Run it more than once
# MAGIC Every run is stamped with the time it started (`trained_at`), so re-running this notebook builds
# MAGIC a legible version history rather than a pile of anonymous versions. That history is what makes
# MAGIC the promotion step in notebook 07 (promote the newest version to `champion`) mean something: run
# MAGIC 06 twice in the workshop, then run 07, and watch `champion` move to the newer of the two.
# MAGIC
# MAGIC ### Why scikit-learn on CPU
# MAGIC Classic machine learning on tabular patient data does not benefit from a graphics processing unit. A
# MAGIC general-purpose CPU cluster, or serverless on Free Edition, is the cheapest, simplest choice
# MAGIC for this kind of workload.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1: Prerequisites & setup
# MAGIC
# MAGIC This engagement runs on serverless compute (including Databricks Free Edition), whose base
# MAGIC environment does not always include MLflow and scikit-learn. We install them and restart Python
# MAGIC first, so the notebook runs the same everywhere. On the ML runtime they are already present and
# MAGIC the install is a fast no-op. After installing, we point MLflow's model registry at Unity Catalog.

# COMMAND ----------

# MAGIC %pip install --quiet mlflow scikit-learn
# MAGIC %restart_python

# COMMAND ----------

import mlflow
import sklearn

print("MLflow version:      ", mlflow.__version__)
print("scikit-learn version:", sklearn.__version__)

# Register models in Unity Catalog rather than the workspace registry.
mlflow.set_registry_uri("databricks-uc")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1.1: Configuration
# MAGIC
# MAGIC Literal names so the notebook runs as-is, matching the rest of this engagement. The model is
# MAGIC registered in the `enablement` catalog, in the `05_ops` schema that notebook 01 created. To use
# MAGIC different names, edit the constants below.

# COMMAND ----------

# ===================================================================
# CONFIGURATION
# ===================================================================

CATALOG_NAME = "enablement"   # Unity Catalog created by notebook 01
SCHEMA_NAME  = "05_ops"       # Schema for model registration
MODEL_NAME   = "patient_risk_stratification_model"

# Full three-level Unity Catalog name: catalog.schema.model. No backticks: the MLflow registry and
# the models:/ URI take the raw dotted name, and a digit-leading schema like 05_ops is a valid UC
# identifier at the API level (backticks are only for SQL parsing). This matches notebooks 07 and 08.
UC_MODEL_NAME = f"{CATALOG_NAME}.{SCHEMA_NAME}.{MODEL_NAME}"

# MLflow experiment, placed directly under the current user's home so runs are grouped and
# discoverable. We use a single path segment under /Users/<you>/ (which always exists) rather than a
# nested folder: mlflow.set_experiment does not create intermediate workspace directories, so a
# nested path like /Users/<you>/enablement/... fails with "Parent directory does not exist" unless
# something created that folder first.
username = dbutils.notebook.entry_point.getDbutils().notebook().getContext().userName().get()
EXPERIMENT_NAME = f"/Users/{username}/enablement_train_risk_model"
mlflow.set_experiment(EXPERIMENT_NAME)

# Stamp this run with the time it started. This names the run, is logged as a param and tag on the
# run, and is copied onto the registered model version below, so every retrain is traceable and the
# version history reads in time order. Notebook 07 promotes the newest version to champion.
from datetime import datetime, timezone

TRAINED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
RUN_NAME = f"train_risk_model_{TRAINED_AT}"

print("Configuration")
print("=" * 70)
print(f"Catalog:           {CATALOG_NAME}")
print(f"Schema:            {SCHEMA_NAME}")
print(f"Model:             {MODEL_NAME}")
print(f"UC registration:   {CATALOG_NAME}.{SCHEMA_NAME}.{MODEL_NAME}")
print(f"Experiment:        {EXPERIMENT_NAME}")
print(f"Trained at (UTC):  {TRAINED_AT}")
print(f"Run name:          {RUN_NAME}")
print("=" * 70)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: Load the dataset
# MAGIC
# MAGIC We use a tabular dataset that ships with scikit-learn. Each row represents a patient
# MAGIC described by 30 numeric features (clinical measurements and laboratory values). The target labels
# MAGIC a patient as higher risk (`0`, malignant) or lower risk (`1`, benign) for an adverse outcome, so
# MAGIC the model learns to predict patient risk from the measurements. It is a small, self-contained
# MAGIC binary classification problem, which is plenty to demonstrate an end-to-end training and logging
# MAGIC workflow for patient risk stratification.

# COMMAND ----------

from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split

data = load_breast_cancer(as_frame=True)
X = data.data
y = data.target

X_train, X_test, y_train, y_test = train_test_split(
  X, y, test_size=0.2, random_state=42, stratify=y
)

print(f"Training rows: {len(X_train)}")
print(f"Test rows:     {len(X_test)}")
print(f"Features:      {X.shape[1]}")
print(f"Risk classes:  {list(data.target_names)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3: Train and log the model
# MAGIC
# MAGIC We train a Random Forest classifier on CPU inside an MLflow run. We log the hyperparameters and
# MAGIC evaluation metrics ourselves, and log the fitted model with a signature and input example so it
# MAGIC is ready for batch scoring and serving.

# COMMAND ----------

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from mlflow.models import infer_signature

# Hyperparameters for the Random Forest
params = {
  "n_estimators": 200,
  "max_depth": 5,
  "random_state": 42,
}

with mlflow.start_run(run_name=RUN_NAME) as run:
  run_id = run.info.run_id
  print(f"MLflow run ID: {run_id}")

  # Train on CPU
  model = RandomForestClassifier(**params)
  model.fit(X_train, y_train)

  # Evaluate on the held-out test set
  preds = model.predict(X_test)
  proba = model.predict_proba(X_test)[:, 1]

  metrics = {
    "accuracy": accuracy_score(y_test, preds),
    "f1":       f1_score(y_test, preds),
    "roc_auc":  roc_auc_score(y_test, proba),
  }

  # Log parameters and metrics. trained_at is logged as both a param and a tag so the run is
  # searchable by it and it shows in the runs table.
  mlflow.log_params(params)
  mlflow.log_param("trained_at", TRAINED_AT)
  mlflow.set_tag("trained_at", TRAINED_AT)
  mlflow.log_metrics(metrics)

  # Log the model with a signature and input example
  signature = infer_signature(X_train, model.predict(X_train))
  mlflow.sklearn.log_model(
    sk_model=model,
    artifact_path=MODEL_NAME,
    signature=signature,
    input_example=X_train.head(5),
  )

  print("Metrics")
  print("=" * 70)
  for name, value in metrics.items():
    print(f"  {name:10s}: {value:.4f}")
  print("=" * 70)

model_uri = f"runs:/{run_id}/{MODEL_NAME}"
print(f"Model URI: {model_uri}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4: Register the model in Unity Catalog
# MAGIC
# MAGIC Registering the model creates a governed, versioned entry in Unity Catalog that can be deployed
# MAGIC to Model Serving or loaded by other workloads for batch scoring.

# COMMAND ----------

model_version = mlflow.register_model(
  model_uri=model_uri,
  name=UC_MODEL_NAME,
)

# Copy the timestamp onto the registered version too, so the version history is legible in Catalog
# Explorer and notebook 07 can report when the version it promotes was trained.
from mlflow.tracking import MlflowClient

MlflowClient(registry_uri="databricks-uc").set_model_version_tag(
  name=f"{CATALOG_NAME}.{SCHEMA_NAME}.{MODEL_NAME}",
  version=model_version.version,
  key="trained_at",
  value=TRAINED_AT,
)

print("Model registered")
print("=" * 70)
print(f"Name:       {model_version.name}")
print(f"Version:    {model_version.version}")
print(f"Trained at: {TRAINED_AT}")
print("=" * 70)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5: Load the model back and predict
# MAGIC
# MAGIC A quick sanity check that the registered model loads and produces predictions on the test data.

# COMMAND ----------

loaded_model = mlflow.pyfunc.load_model(f"models:/{UC_MODEL_NAME}/{model_version.version}")

sample = X_test.head(5)
predictions = loaded_model.predict(sample)

print("Sample predictions:", list(predictions))
print("Actual labels:     ", list(y_test.head(5)))
print()
print("Done. The patient risk stratification model is trained, logged to MLflow, and registered in Unity Catalog.")
