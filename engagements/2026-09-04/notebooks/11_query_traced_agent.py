# Databricks notebook source
# MAGIC %md
# MAGIC # 11. Query the traced agent endpoint and read the traces back
# MAGIC
# MAGIC A consumer notebook. It calls the clinical triage agent endpoint that **notebook 10** built and
# MAGIC deployed with `agents.deploy`, then shows the traces those calls produced.
# MAGIC
# MAGIC Because that endpoint was deployed with `agents.deploy`, it is wired to an MLflow experiment and traces
# MAGIC show up there in near real time, not only in the best-effort inference table.
# MAGIC
# MAGIC ### What this notebook does
# MAGIC 1. Confirms the endpoint is ready
# MAGIC 2. Sends a few triage questions to the endpoint
# MAGIC 3. Reads the traces back with the MLflow search API, so you can see the span tree (agent, model call,
# MAGIC    tool calls, final model call) for each request
# MAGIC 4. Points at the payload table where production traces are also captured
# MAGIC
# MAGIC ### Availability
# MAGIC This notebook needs the endpoint notebook 10 deploys, which needs Model Serving. Model Serving is not
# MAGIC on Free Edition, so the notebook checks the endpoint exists and exits cleanly where it does not. Run it
# MAGIC on the client's own workspace, after notebook 10.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 0: Install and restart

# COMMAND ----------

# MAGIC %pip install --upgrade "mlflow[databricks]" databricks-sdk
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1: Configuration
# MAGIC
# MAGIC These must match notebook 10: the same endpoint name and payload table.

# COMMAND ----------

CATALOG = "enablement"
SCHEMA = "05_ops"
MODEL_NAME = "clinical_triage_agent"

ENDPOINT_NAME = "clinical-triage-agent"
PAYLOAD_TABLE = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}_payload"

print(f"Endpoint: {ENDPOINT_NAME}")
print(f"Traces:   {PAYLOAD_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: Wait for the endpoint to be ready
# MAGIC
# MAGIC `agents.deploy` (notebook 10) provisions the endpoint asynchronously, so right after a deploy the
# MAGIC endpoint exists but is not yet servable, and a query returns "endpoint does not exist" until it comes
# MAGIC up. We poll until it reports READY before querying. If Model Serving is unavailable (Free Edition)
# MAGIC or the endpoint never appears, we skip the query cleanly rather than fail.

# COMMAND ----------

import time

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# First a cheap probe: if listing endpoints fails, Model Serving is not enabled here (Free Edition),
# so skip immediately rather than waiting out the readiness loop.
serving_available = False
try:
    list(w.serving_endpoints.list())
    serving_available = True
except Exception as e:
    print(f"Model Serving is not available here: {type(e).__name__}")
    print("This is expected on Free Edition. Run notebook 10, then this one, on the client's workspace.")

endpoint_ready = False
if serving_available:
    deadline = time.time() + 20 * 60  # a fresh agents.deploy can take several minutes to become servable
    while time.time() < deadline:
        try:
            state = w.serving_endpoints.get(ENDPOINT_NAME).state
        except Exception:
            state = None  # not registered yet
        if state is None:
            print(f"Endpoint '{ENDPOINT_NAME}' not visible yet (run notebook 10 first if you have not); waiting...")
        else:
            # state.ready is an enum; take the last dotted segment so 'NOT_READY' is not mistaken for READY.
            ready = str(getattr(state, "ready", None)).rsplit(".", 1)[-1]
            print(f"Endpoint '{ENDPOINT_NAME}': ready={ready} config_update={getattr(state, 'config_update', None)}")
            if ready == "READY":
                endpoint_ready = True
                break
        time.sleep(30)
    if not endpoint_ready:
        print(f"Endpoint '{ENDPOINT_NAME}' did not reach READY within the wait window; skipping the query.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3: Ask the agent a few questions
# MAGIC
# MAGIC Each question needs a score lookup and a band classification, so each drives the full tool loop and
# MAGIC produces a multi-span trace. A `ResponsesAgent` endpoint takes the Responses schema, `{"input": [...]}`,
# MAGIC so we POST that body straight to the invocations route.

# COMMAND ----------

import json
import time

if endpoint_ready:
    def ask(question: str) -> dict:
        return w.api_client.do(
            "POST",
            f"/serving-endpoints/{ENDPOINT_NAME}/invocations",
            body={"input": [{"role": "user", "content": question}]},
        )

    def answer_text(response: dict) -> str:
        # The Responses payload is {"output": [{"content": [{"text": ...}], ...}], ...}.
        for item in response.get("output", []):
            for part in item.get("content", []):
                if part.get("text"):
                    return part["text"]
        return json.dumps(response)[:500]

    questions = [
        "What risk band is patient p004 in?",
        "Is patient p001 low, moderate, or high risk?",
        "What about patient p999?",
    ]

    for q in questions:
        try:
            resp = ask(q)
        except Exception as e:
            # A scale-to-zero endpoint cold-starts on the first request; a brief retry covers that.
            print(f"(first call may cold-start: {type(e).__name__}) retrying in 30s ...")
            time.sleep(30)
            resp = ask(q)
        print(f"Q: {q}")
        print(f"A: {answer_text(resp)}\n")
else:
    print("Skipped: endpoint not available (see Section 2).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4: Read the traces back
# MAGIC
# MAGIC Because the endpoint was deployed with `agents.deploy`, its traces are wired to an MLflow experiment
# MAGIC and show up in that experiment's **Traces** tab in near real time, not only in the best-effort payload
# MAGIC table. `mlflow.search_traces` gives a quick in-notebook view. Each trace is a tree of spans: the agent,
# MAGIC the Foundation Model API calls, and the tool calls. That tree is the payoff of turning tracing on. This
# MAGIC cell is best-effort: capture is not instant, so an empty result just means "not yet", and we never fail
# MAGIC the notebook on it.

# COMMAND ----------

import mlflow

if endpoint_ready:
    try:
        traces = mlflow.search_traces(max_results=10)
        n = len(traces)
    except Exception as e:
        traces, n = None, 0
        print(f"search_traces not available here ({type(e).__name__}); use the payload table below.")

    print(f"Traces found: {n}")
    if n:
        display(traces)
    else:
        print("No traces surfaced yet. Open the endpoint's experiment in the UI and use the Traces tab,")
        print("or check the payload table below in a few minutes.")
else:
    print("Skipped: no endpoint, so no traces to read.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5: Where the production traces land
# MAGIC
# MAGIC `agents.deploy` also provisions a payload table for governed, production capture. Capture is
# MAGIC asynchronous, so rows land a few minutes after the calls.

# COMMAND ----------

if endpoint_ready:
    if spark.catalog.tableExists(PAYLOAD_TABLE):
        count = spark.table(PAYLOAD_TABLE).count()
        print(f"Payload table {PAYLOAD_TABLE}: {count} row(s) captured so far.")
        display(spark.table(PAYLOAD_TABLE).limit(10))
    else:
        print(f"Payload table {PAYLOAD_TABLE} not visible yet.")
        print("Capture is asynchronous; give it a few minutes after the requests above, then re-run.")
else:
    print("Skipped: no endpoint, so no payload table.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recap
# MAGIC
# MAGIC - The endpoint answered triage questions by calling tools, and each call produced a multi-span trace.
# MAGIC - The traces are the reason to instrument the agent: they show the model's tool choices and where
# MAGIC   latency and token cost go, per request.
# MAGIC - Because the endpoint was deployed with `agents.deploy` (notebook 10), traces appear in the MLflow
# MAGIC   experiment's Traces tab in near real time, and production traffic is also captured in the payload
# MAGIC   table.
# MAGIC - **The endpoint is not torn down for you.** Delete it by hand when you are done, or it lingers:
# MAGIC   `w.serving_endpoints.delete(name=ENDPOINT_NAME)`. The payload table it wrote stays too.
