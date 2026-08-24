# Databricks notebook source
# MAGIC %md
# MAGIC # 08. Train a CPU model and log it to MLflow
# MAGIC
# MAGIC An optional extra. This notebook trains a simple scikit-learn classifier on CPU, logs it to
# MAGIC MLflow, and registers it in Unity Catalog. It stands alone from the medallion pipeline: it
# MAGIC uses a built-in scikit-learn dataset rather than the campaign tables, so it can run on its own
# MAGIC once the `enablement` catalog exists (notebook 01).
# MAGIC
# MAGIC ### What the model predicts
# MAGIC The model is a binary classifier for breast tumor diagnosis. Given 30 numeric measurements
# MAGIC taken from a digitized image of a breast mass (a fine needle aspirate biopsy), it predicts
# MAGIC whether the tumor is **malignant** (cancerous) or **benign** (not cancerous). In this dataset
# MAGIC the label is `0` for malignant and `1` for benign. This is a well known teaching dataset, not
# MAGIC a clinical tool, so the model is for demonstration only.
# MAGIC
# MAGIC ### What this notebook does
# MAGIC 1. Loads a small tabular dataset (scikit-learn breast cancer)
# MAGIC 2. Trains a Random Forest classifier on CPU
# MAGIC 3. Evaluates the model on a held-out test set
# MAGIC 4. Logs parameters, metrics, and the model to MLflow
# MAGIC 5. Registers the model in Unity Catalog
# MAGIC
# MAGIC ### Why scikit-learn on CPU
# MAGIC Classic machine learning on tabular data does not benefit from a graphics processing unit. A
# MAGIC general-purpose CPU cluster, or serverless on Free Edition, is the cheapest, simplest choice
# MAGIC for this kind of workload.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1: Prerequisites & setup
# MAGIC
# MAGIC The Databricks ML runtime ships with scikit-learn and MLflow, so no installs are needed there.
# MAGIC On serverless or a standard runtime, `%pip install scikit-learn mlflow` first if either import
# MAGIC fails. We point MLflow's model registry at Unity Catalog.

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
MODEL_NAME   = "train_cpu_model"

# Full three-level Unity Catalog name: catalog.schema.model
UC_MODEL_NAME = f"{CATALOG_NAME}.`{SCHEMA_NAME}`.{MODEL_NAME}"

# MLflow experiment, placed in the current user's workspace directory so runs are discoverable.
username = dbutils.notebook.entry_point.getDbutils().notebook().getContext().userName().get()
EXPERIMENT_NAME = f"/Users/{username}/enablement/train_cpu_model"
mlflow.set_experiment(EXPERIMENT_NAME)

print("Configuration")
print("=" * 70)
print(f"Catalog:           {CATALOG_NAME}")
print(f"Schema:            {SCHEMA_NAME}")
print(f"Model:             {MODEL_NAME}")
print(f"UC registration:   {CATALOG_NAME}.{SCHEMA_NAME}.{MODEL_NAME}")
print(f"Experiment:        {EXPERIMENT_NAME}")
print("=" * 70)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: Load the dataset
# MAGIC
# MAGIC We use the breast cancer dataset that ships with scikit-learn. Each row is a breast tumor
# MAGIC described by 30 numeric features (mean, standard error, and worst value of measurements such as
# MAGIC radius, texture, perimeter, and area computed from a digitized biopsy image). The target labels
# MAGIC the tumor as malignant (`0`) or benign (`1`), so the model learns to predict a diagnosis from
# MAGIC the measurements. It is a small, self-contained binary classification problem, which is plenty
# MAGIC to demonstrate an end-to-end training and logging workflow.

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
print(f"Classes:       {list(data.target_names)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3: Train and log the model
# MAGIC
# MAGIC We train a Random Forest classifier on CPU inside an MLflow run. We log the hyperparameters and
# MAGIC evaluation metrics ourselves, and log the fitted model with a signature and input example so it
# MAGIC is ready for serving.

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

with mlflow.start_run(run_name="train_cpu_model") as run:
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

  # Log parameters and metrics
  mlflow.log_params(params)
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
# MAGIC to Model Serving or loaded by other workloads.

# COMMAND ----------

model_version = mlflow.register_model(
  model_uri=model_uri,
  name=UC_MODEL_NAME,
)

print("Model registered")
print("=" * 70)
print(f"Name:    {model_version.name}")
print(f"Version: {model_version.version}")
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
print("Done. The CPU model is trained, logged to MLflow, and registered in Unity Catalog.")
