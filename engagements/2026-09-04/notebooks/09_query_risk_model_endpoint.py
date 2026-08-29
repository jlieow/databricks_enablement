# Databricks notebook source
# MAGIC %md
# MAGIC # 09. Query the risk model serving endpoint
# MAGIC
# MAGIC A consumer notebook. It calls the real-time endpoint that **notebook 08** deployed for the
# MAGIC `@champion` patient risk model, the same way an application or downstream job would, then shows the
# MAGIC requests landing in the inference table. This is the classical-model counterpart to notebook 11,
# MAGIC which queries the traced agent endpoint.
# MAGIC
# MAGIC The endpoint serves the `champion` alias, so this notebook never needs to know which model version
# MAGIC is live: whatever notebook 07 last promoted is what answers here.
# MAGIC
# MAGIC ### What this notebook does
# MAGIC 1. Confirms the endpoint is ready
# MAGIC 2. Scores a single record and prints the prediction
# MAGIC 3. Scores a small batch in one request
# MAGIC 4. Shows the traffic it generated landing in the AI Gateway inference table
# MAGIC
# MAGIC ### Availability
# MAGIC This needs the endpoint notebook 08 deployed, which needs Model Serving. Model Serving is **not on
# MAGIC Databricks Free Edition** and is region-gated, so the notebook checks the endpoint exists and exits
# MAGIC cleanly where it does not. Run it on the client's own workspace, after notebook 08. Remember the
# MAGIC build's real serving path is batch (notebook 07 scores, notebook 12 writes to PostgreSQL); this and
# MAGIC notebook 08 are the optional real-time reference.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 0: Install dependencies
# MAGIC
# MAGIC The typed query payload (`DataframeSplitInput`) needs a newer `databricks-sdk` than some runtimes
# MAGIC ship, and we use scikit-learn to build a request with the right feature shape. Serverless (including
# MAGIC Free Edition) does not always include scikit-learn; on the ML runtime the install is a fast no-op.

# COMMAND ----------

# MAGIC %pip install --upgrade databricks-sdk scikit-learn
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1: Configuration
# MAGIC
# MAGIC These match notebook 08: the same endpoint name and inference (payload) table.

# COMMAND ----------

CATALOG = "enablement"
SCHEMA = "05_ops"
MODEL_NAME = "patient_risk_stratification_model"

ENDPOINT_NAME = "patient-risk-stratification"
PAYLOAD_TABLE = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}_payload"

print("Configuration")
print("=" * 70)
print(f"Endpoint:  {ENDPOINT_NAME}")
print(f"Traces:    {PAYLOAD_TABLE}")
print("=" * 70)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: Confirm the endpoint is ready
# MAGIC
# MAGIC Notebook 08 creates the endpoint with `create_and_wait`, so it is already READY once 08 finishes;
# MAGIC we still check here so a query does not fail with a confusing error if the endpoint is missing.
# MAGIC Scale-to-zero endpoints cold-start on the first request after idle, so the first call may take a
# MAGIC little longer. If Model Serving is unavailable (Free Edition), we skip the query cleanly.

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

endpoint_ready = False
try:
    if any(e.name == ENDPOINT_NAME for e in w.serving_endpoints.list()):
        state = w.serving_endpoints.get(ENDPOINT_NAME).state
        endpoint_ready = True
        print(f"Endpoint '{ENDPOINT_NAME}' found; ready={getattr(state, 'ready', None)}")
    else:
        print(f"Endpoint '{ENDPOINT_NAME}' not found.")
        print("Run notebook 08 first to deploy it (needs Model Serving, not on Free Edition).")
except Exception as e:
    print(f"Model Serving is not available here: {type(e).__name__}")
    print("This is expected on Free Edition. Run notebook 08, then this one, on the client's workspace.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3: Score a single record
# MAGIC
# MAGIC We take one row from the dataset the model was trained on so the feature shape matches. In a real
# MAGIC application this record would carry the engineered clinical features for one patient.

# COMMAND ----------

if endpoint_ready:
    from sklearn.datasets import load_breast_cancer
    from sklearn.model_selection import train_test_split
    from databricks.sdk.service.serving import DataframeSplitInput

    data = load_breast_cancer(as_frame=True)
    _, X_test, _, y_test = train_test_split(
        data.data, data.target, test_size=0.2, random_state=42, stratify=data.target
    )
    one = X_test.head(1)

    response = w.serving_endpoints.query(
        name=ENDPOINT_NAME,
        dataframe_split=DataframeSplitInput(
            columns=list(one.columns),
            data=one.values.tolist(),
        ),
    )
    print("Single-record prediction:", response.predictions)
else:
    print("Skipped: endpoint not available (see Section 2).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4: Score a batch in one request
# MAGIC
# MAGIC The same call with several rows. The prediction list comes back in the same order as the rows sent,
# MAGIC so we can line each prediction up against the true label. Recall the risk mapping from notebooks 06
# MAGIC and 07: label `0` (malignant) stands in for higher risk, `1` (benign) for lower risk.

# COMMAND ----------

if endpoint_ready:
    batch = X_test.head(10)

    response = w.serving_endpoints.query(
        name=ENDPOINT_NAME,
        dataframe_split=DataframeSplitInput(
            columns=list(batch.columns),
            data=batch.values.tolist(),
        ),
    )

    predictions = response.predictions
    actuals = list(y_test.head(10))

    print(f"{'row':>3}  {'predicted':>9}  {'actual':>6}  match")
    print("-" * 34)
    for i, (p, a) in enumerate(zip(predictions, actuals)):
        print(f"{i:>3}  {int(p):>9}  {a:>6}  {'y' if int(p) == a else 'n'}")

    matches = sum(1 for p, a in zip(predictions, actuals) if int(p) == a)
    print(f"\n{matches}/{len(predictions)} predictions matched the held-out labels.")
else:
    print("Skipped: endpoint not available (see Section 2).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5: See the calls in the inference table
# MAGIC
# MAGIC Every request above is captured to the AI Gateway inference table that notebook 08 configured. This
# MAGIC is the governed request/response audit trail, and the source the drift and calibration monitoring in
# MAGIC notebook 07 reads from. Capture is asynchronous, so the rows for this run land a few minutes later;
# MAGIC re-run this cell then if it is still empty.

# COMMAND ----------

if endpoint_ready:
    if spark.catalog.tableExists(PAYLOAD_TABLE):
        count = spark.table(PAYLOAD_TABLE).count()
        print(f"Inference table {PAYLOAD_TABLE}: {count} row(s) captured so far.")
        display(spark.table(PAYLOAD_TABLE).limit(10))
    else:
        print(f"Inference table {PAYLOAD_TABLE} not visible yet.")
        print("Capture is asynchronous; give it a few minutes after the requests above, then re-run.")
else:
    print("Skipped: no endpoint, so no inference table.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recap
# MAGIC
# MAGIC - The endpoint is called by its alias-backed name, so this notebook keeps working after a new
# MAGIC   champion is promoted (notebook 07), with no change here.
# MAGIC - Single and batch requests use the same `query` call; a batch is one round trip for many rows.
# MAGIC - The calls are captured in the inference table notebook 08 configured, which is the audit trail
# MAGIC   and the source for the drift monitoring in notebook 07.
# MAGIC - This is the optional real-time path. The build serves in batch (notebook 07 scores, notebook 12
# MAGIC   writes to PostgreSQL, the app reads).
