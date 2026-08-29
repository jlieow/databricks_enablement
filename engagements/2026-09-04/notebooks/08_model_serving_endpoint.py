# Databricks notebook source
# MAGIC %md
# MAGIC # 08. Optional: serve the champion model on a real-time endpoint
# MAGIC
# MAGIC **This is an optional capability, not this build's serving pattern.** The build serves scores in
# MAGIC batch: notebook 07 batch-scores with the `@champion` model, notebook 12 writes the results to
# MAGIC PostgreSQL, and the app reads them. Nothing calls the model at request time.
# MAGIC
# MAGIC This notebook is here for the case where you later need low-latency, request-time scoring, for
# MAGIC example a clinician tool that scores a single patient on demand. It deploys the same
# MAGIC `@champion` version that notebook 07 promoted to a Databricks Model Serving endpoint. Deploying the
# MAGIC same aliased version keeps batch and real-time on one model, so there is never a batch model and a
# MAGIC separate serving model to keep in step. **Notebook 09 then queries this endpoint** and shows the
# MAGIC captured requests, the same way notebooks 10 and 11 build and query the agent endpoint.
# MAGIC
# MAGIC ### What this notebook does
# MAGIC 1. Resolves the version the `champion` alias points at
# MAGIC 2. Creates or updates a Model Serving endpoint that serves that version, with scale-to-zero and
# MAGIC    an inference table that captures every request and response
# MAGIC 3. Waits for the endpoint to be ready
# MAGIC
# MAGIC Querying it and reading the inference table is notebook 09.
# MAGIC
# MAGIC ### Inference table: capture in Unity Catalog
# MAGIC The endpoint is created with an **AI Gateway inference table**, which logs every request and
# MAGIC response to a governed Delta table in Unity Catalog. For a clinical, regulated build this is the
# MAGIC audit trail of what the model was asked and what it answered, and it is the source the drift and
# MAGIC calibration monitoring in notebook 07 reads from: those queries have nothing to read until
# MAGIC capture is on. We enable it here so serving and monitoring join up. (For a plain tabular
# MAGIC classifier this request/response capture is the right-sized choice; richer MLflow span tracing is
# MAGIC aimed at agent and large language model endpoints, not a Random Forest. Notebook 10 is the agent
# MAGIC counterpart: it builds and serves a multi-step tool-calling agent with `agents.deploy` (notebook
# MAGIC 11 queries it), which is where that span tracing earns its place.)
# MAGIC
# MAGIC The older `auto_capture_config` inference tables are deprecated: the platform now rejects them
# MAGIC and requires the AI Gateway variant, configured through the `ai_gateway` argument rather than on
# MAGIC the core config. This notebook uses the AI Gateway form.
# MAGIC
# MAGIC ### Availability
# MAGIC Model Serving is **not available on Databricks Free Edition**, and serverless compute for serving
# MAGIC is region-gated. This notebook checks whether serving is reachable and exits cleanly with an
# MAGIC explanation if it is not, so it is safe to run anywhere. Treat it as a reference pattern to run
# MAGIC on the client's own workspace, not in the Free Edition workshop.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 0: Install dependencies
# MAGIC
# MAGIC The AI Gateway inference table classes (`AiGatewayConfig`, `AiGatewayInferenceTableConfig`) are
# MAGIC only in newer `databricks-sdk` releases, so we upgrade it. We also install MLflow: this notebook
# MAGIC imports it to resolve the champion alias, and serverless compute (including Free Edition) does not
# MAGIC always ship it. On the ML runtime the install is a fast no-op. Then we restart Python.

# COMMAND ----------

# MAGIC %pip install --upgrade databricks-sdk mlflow
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1: Configuration
# MAGIC
# MAGIC The model and alias match notebooks 06 and 07. `SCALE_TO_ZERO` keeps the endpoint from costing
# MAGIC anything while idle: it spins down after a period of no traffic and cold-starts on the next
# MAGIC request, which is the right default for an on-demand clinician tool that is not used constantly.

# COMMAND ----------

CATALOG = "enablement"
SCHEMA = "05_ops"
MODEL_NAME = "patient_risk_stratification_model"

# Three-level name without backticks for the SDK/serving APIs.
UC_MODEL_NAME = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}"

ALIAS = "champion"
ENDPOINT_NAME = "patient-risk-stratification"   # lowercase, hyphens; endpoint names allow no dots
WORKLOAD_SIZE = "Small"                          # smallest serving size
SCALE_TO_ZERO = True

# Inference table: where captured requests and responses land in Unity Catalog. The serving layer
# creates the table itself from this catalog/schema/prefix; it appears after the first requests
# (which notebook 09 sends). -> enablement.05_ops.patient_risk_stratification_model_payload
CAPTURE_CATALOG = CATALOG        # enablement
CAPTURE_SCHEMA = SCHEMA          # 05_ops
CAPTURE_PREFIX = MODEL_NAME      # -> enablement.05_ops.patient_risk_stratification_model_payload

print("Configuration")
print("=" * 70)
print(f"Model:     {UC_MODEL_NAME}")
print(f"Alias:     {ALIAS}")
print(f"Endpoint:  {ENDPOINT_NAME}")
print(f"Workload:  {WORKLOAD_SIZE} (scale to zero: {SCALE_TO_ZERO})")
print(f"Capture:   {CAPTURE_CATALOG}.{CAPTURE_SCHEMA}.{CAPTURE_PREFIX}_payload")
print("=" * 70)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: Check that Model Serving is available
# MAGIC
# MAGIC We probe the serving API. On Free Edition or a workspace without serving this raises, and we set
# MAGIC a flag so the rest of the notebook explains rather than fails.

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

serving_available = False
try:
    # Listing endpoints is a cheap call that fails fast where serving is not enabled.
    list(w.serving_endpoints.list())
    serving_available = True
    print("Model Serving is available in this workspace.")
except Exception as e:
    print(f"Model Serving is not available here: {type(e).__name__}")
    print("\nThis is expected on Free Edition and in regions without serverless serving.")
    print("Run this notebook on the client's own workspace. The pattern below is unchanged there.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3: Resolve the champion version
# MAGIC
# MAGIC The endpoint serves a specific version, so we look up which version the `champion` alias points
# MAGIC at right now. Serving that resolved version, rather than hardcoding a number, keeps this in step
# MAGIC with whatever notebook 07 last promoted.

# COMMAND ----------

from mlflow.tracking import MlflowClient

champion_version = None
if serving_available:
    client = MlflowClient(registry_uri="databricks-uc")
    try:
        mv = client.get_model_version_by_alias(UC_MODEL_NAME, ALIAS)
        champion_version = mv.version
        trained_at = (mv.tags or {}).get("trained_at", "unknown")
        print(f"champion -> version {champion_version} (trained_at: {trained_at})")
    except Exception as e:
        print(f"Could not resolve the '{ALIAS}' alias on {UC_MODEL_NAME}: {type(e).__name__}")
        print("Run notebook 07 first to train, register, and set the champion alias.")
        serving_available = False
else:
    print("Skipped: Model Serving is not available (see Section 2).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4: Create or update the endpoint
# MAGIC
# MAGIC One endpoint, one served model, pointed at the resolved champion version. `create_and_wait`
# MAGIC blocks until the endpoint is ready. If the endpoint already exists we update its config instead,
# MAGIC so this notebook is safe to re-run and re-runs it to serve a newly promoted champion.

# COMMAND ----------

if serving_available and champion_version is not None:
    from databricks.sdk.service.serving import (
        AiGatewayConfig,
        AiGatewayInferenceTableConfig,
        EndpointCoreConfigInput,
        ServedEntityInput,
    )

    served_entity = ServedEntityInput(
        entity_name=UC_MODEL_NAME,
        entity_version=champion_version,
        workload_size=WORKLOAD_SIZE,
        scale_to_zero_enabled=SCALE_TO_ZERO,
    )

    # Turn on the AI Gateway inference table. The serving layer writes requests and responses to
    # <catalog>.<schema>.<prefix>_payload, creating the table on first traffic. This is the current,
    # non-deprecated request/response capture; the older auto_capture_config form is rejected now.
    inference_table = AiGatewayInferenceTableConfig(
        enabled=True,
        catalog_name=CAPTURE_CATALOG,
        schema_name=CAPTURE_SCHEMA,
        table_name_prefix=CAPTURE_PREFIX,
    )
    ai_gateway = AiGatewayConfig(inference_table_config=inference_table)

    existing = next(
        (e for e in w.serving_endpoints.list() if e.name == ENDPOINT_NAME), None
    )

    if existing:
        print(f"Endpoint '{ENDPOINT_NAME}' exists; updating it to serve version {champion_version} ...")
        w.serving_endpoints.update_config_and_wait(
            name=ENDPOINT_NAME,
            served_entities=[served_entity],
        )
        # The AI Gateway config is set separately from the served-entity config.
        w.serving_endpoints.put_ai_gateway(
            name=ENDPOINT_NAME, inference_table_config=inference_table
        )
        print("Updated.")
    else:
        print(f"Creating endpoint '{ENDPOINT_NAME}' (this can take several minutes) ...")
        w.serving_endpoints.create_and_wait(
            name=ENDPOINT_NAME,
            config=EndpointCoreConfigInput(
                name=ENDPOINT_NAME, served_entities=[served_entity]
            ),
            ai_gateway=ai_gateway,
        )
        print("Created and ready.")
else:
    print("Skipped endpoint creation. See the messages above for why.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recap and cleanup
# MAGIC
# MAGIC You deployed the `@champion` model to a real-time endpoint with request/response capture turned on.
# MAGIC **Run notebook 09 next** to send it a scoring request and see the captured rows in the inference
# MAGIC table. Points to carry forward:
# MAGIC
# MAGIC - **This build serves in batch.** Use this only where request-time scoring is genuinely needed;
# MAGIC   the batch path in notebooks 07 and 12 is the default and the one the app relies on.
# MAGIC - **Serve the alias, not a version number.** Re-run this after notebook 07 promotes a new
# MAGIC   champion and the endpoint moves with it, with no change to callers.
# MAGIC - **Scale to zero.** An on-demand endpoint costs nothing while idle; the trade-off is a cold
# MAGIC   start on the first request after a quiet period.
# MAGIC - **Capture is on.** The inference table gives you a governed request/response audit trail and
# MAGIC   feeds the drift monitoring in notebook 07. Keep it; it is the monitoring source.
# MAGIC - **A serving endpoint is not managed by these notebooks after creation.** Delete it by hand when
# MAGIC   you tear the workspace down, or it lingers. The inference table it wrote stays too.
# MAGIC
# MAGIC ```python
# MAGIC # Delete the endpoint when finished:
# MAGIC # w.serving_endpoints.delete(name=ENDPOINT_NAME)
# MAGIC ```

# COMMAND ----------

if serving_available and champion_version is not None:
    print(f"Endpoint '{ENDPOINT_NAME}' is serving {UC_MODEL_NAME} version {champion_version}.")
    print("Run notebook 09 to query it; delete it by hand when you are done (see the cell above).")
else:
    print("Nothing to clean up: no endpoint was created in this run.")
