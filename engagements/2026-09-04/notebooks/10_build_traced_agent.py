# Databricks notebook source
# MAGIC %md
# MAGIC # 10. Build and serve a traced tool-calling agent with agents.deploy
# MAGIC
# MAGIC **This is the agent counterpart to notebook 08, and like it, an optional reference pattern rather
# MAGIC than this build's serving path.** The build serves scores in batch (notebook 07 scores, notebook 12
# MAGIC writes to PostgreSQL, the app reads). Both serving notebooks are here for the case where you later
# MAGIC need request-time behaviour.
# MAGIC
# MAGIC Notebook 08 serves the classical `@champion` risk model. That model has no internal steps, so it uses
# MAGIC an **inference table** to capture requests and responses, and there is nothing finer to see. This
# MAGIC notebook is the case where **MLflow tracing** earns its place: a small tool-calling agent that calls a
# MAGIC large language model, lets the model decide to call a tool, then composes an answer. Every served
# MAGIC request is a **tree of spans** (agent, model call, tool calls, final model call) you can inspect,
# MAGIC rather than one opaque call.
# MAGIC
# MAGIC The scenario keeps the health theme: a **clinical triage assistant** that answers questions about a
# MAGIC patient by looking up the batch risk score notebook 07 produced and classifying it into a band. The
# MAGIC tools are deliberately trivial (a tiny synthetic score book and a threshold check) so the demo is
# MAGIC about the tracing, not the tools. On the real build the same shape wraps the actual gold tables.
# MAGIC
# MAGIC ### Why agents.deploy rather than the Model Serving SDK
# MAGIC Notebook 08 builds its endpoint by hand with the serving SDK plus an AI Gateway inference table. That
# MAGIC shows the moving parts, but the endpoint is not wired to an MLflow experiment, so traces only land in
# MAGIC the inference table and that capture is best effort (it can lag up to about an hour).
# MAGIC `databricks.agents.deploy` is the Databricks-recommended way to serve an agent. It does the wiring for
# MAGIC you: turns on MLflow tracing, points the endpoint at an MLflow experiment so traces appear in the
# MAGIC experiment's Traces tab in near real time, and provisions the request/response payload tables.
# MAGIC
# MAGIC ### What this notebook does
# MAGIC 1. Defines two traced tools and a `ResponsesAgent` that runs a traced tool loop over the Foundation
# MAGIC    Model API
# MAGIC 2. Runs the agent once in the notebook to produce a trace you can look at inline
# MAGIC 3. Logs and registers the agent in Unity Catalog
# MAGIC 4. Deploys it with `agents.deploy` (reference pattern, guarded)
# MAGIC
# MAGIC Then **notebook 11 queries the deployed endpoint and reads the traces back.**
# MAGIC
# MAGIC ### Availability
# MAGIC Model Serving is **not available on Databricks Free Edition**, and the pay-per-token Foundation Model
# MAGIC API model this uses is region-gated. The notebook checks what is reachable and skips the deploy step
# MAGIC cleanly where it is not, so it is safe to run anywhere. The local agent run in Section 3 still produces
# MAGIC a trace wherever the Foundation Model API is reachable. Treat the deploy step as a pattern to run on
# MAGIC the client's own workspace.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 0: Install and restart
# MAGIC
# MAGIC `databricks-agents` adds the `agents.deploy` API. `mlflow[databricks]` brings the `ResponsesAgent`
# MAGIC base class and tracing; `openai` is the client the agent uses to call the Foundation Model API.

# COMMAND ----------

# MAGIC %pip install --upgrade "mlflow[databricks]" databricks-agents databricks-sdk openai httpx
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1: Configuration
# MAGIC
# MAGIC The model is registered in the same `enablement.05_ops` location as the classical model in notebook 08.
# MAGIC Notebook 11 reads the same `ENDPOINT_NAME` and `PAYLOAD_TABLE` to query it, so keep them in step.
# MAGIC
# MAGIC One gotcha worth knowing for `agents.deploy`: it derives the served entity name from the model's full
# MAGIC name (catalog, schema, model), and that name must be alphanumeric-and-dashes and under 63 characters. A
# MAGIC catalog whose name **starts with an underscore** makes the derived name invalid; mid-name underscores
# MAGIC are fine, only a leading one is rejected. `enablement` is safe. If you rename the catalog, keep it off a
# MAGIC leading underscore.

# COMMAND ----------

CATALOG = "enablement"
SCHEMA = "05_ops"
MODEL_NAME = "clinical_triage_agent"

# Three-level name without backticks for the registry / serving APIs.
UC_MODEL_NAME = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}"

ENDPOINT_NAME = "clinical-triage-agent"   # lowercase, hyphens; endpoint names allow no dots

# A pay-per-token Foundation Model API model that supports tool calling. If this one is not available
# in your workspace (likely on Free Edition), set it to another served foundation model that supports
# tool calling. List what you have with:  databricks serving-endpoints list
LLM_ENDPOINT = "databricks-claude-sonnet-4-5"

# agents.deploy provisions request/response payload tables next to the model. Notebook 11 reads this.
PAYLOAD_TABLE = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}_payload"

print("Configuration")
print("=" * 70)
print(f"UC model:      {UC_MODEL_NAME}")
print(f"Endpoint:      {ENDPOINT_NAME}")
print(f"LLM endpoint:  {LLM_ENDPOINT}")
print(f"Payload table: {PAYLOAD_TABLE}")
print("=" * 70)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2: The agent
# MAGIC
# MAGIC Two tools, each decorated with `@mlflow.trace`, and a `ResponsesAgent` that runs a tool loop over the
# MAGIC Foundation Model API with `mlflow.openai.autolog()` on. The tool loop and the tools are traced, so each
# MAGIC request becomes a tree of spans.
# MAGIC
# MAGIC The tools are trivial on purpose. `get_patient_risk_score` reads a tiny synthetic score book (stand-in
# MAGIC for the batch scores notebook 07 writes to the gold table); `classify_risk_band` applies fixed
# MAGIC thresholds. On the real build these read the gold tables and the agreed clinical bands. All patient ids
# MAGIC and scores here are fictional.

# COMMAND ----------

import json
import uuid
from typing import Any, Generator

import mlflow
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
)

# Trace every Foundation Model API call automatically.
mlflow.openai.autolog()

# ---- Tools -------------------------------------------------------------------

# Synthetic stand-in for the batch risk scores notebook 07 writes to the gold table. Fictional ids.
RISK_SCORE_BOOK = {
    "p001": 0.12,
    "p002": 0.44,
    "p003": 0.71,
    "p004": 0.88,
    "p005": 0.29,
}


@mlflow.trace(span_type="TOOL")
def get_patient_risk_score(patient_id: str) -> float:
    """Return the batch risk score (0 to 1) for a patient id, or -1 if the id is unknown."""
    return RISK_SCORE_BOOK.get(patient_id.strip().lower(), -1.0)


@mlflow.trace(span_type="TOOL")
def classify_risk_band(risk_score: float) -> str:
    """Classify a risk score into a band using the agreed thresholds."""
    if risk_score < 0:
        return "unknown"
    if risk_score < 0.30:
        return "low"
    if risk_score < 0.70:
        return "moderate"
    return "high"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_patient_risk_score",
            "description": "Look up the batch risk score (0 to 1) for a patient id (for example p001).",
            "parameters": {
                "type": "object",
                "properties": {"patient_id": {"type": "string"}},
                "required": ["patient_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_risk_band",
            "description": "Classify a risk score (0 to 1) into a band: low, moderate, or high.",
            "parameters": {
                "type": "object",
                "properties": {"risk_score": {"type": "number"}},
                "required": ["risk_score"],
            },
        },
    },
]

TOOL_FNS = {
    "get_patient_risk_score": get_patient_risk_score,
    "classify_risk_band": classify_risk_band,
}


class TracedTriageAgent(ResponsesAgent):
    """A tool-calling clinical triage assistant over a Foundation Model API model. The tool loop and
    the tools are traced, so each served request is a tree of spans."""

    def _client(self):
        # The workspace exposes an OpenAI-compatible client for the Foundation Model API.
        #
        # In the serving container we authenticate with a personal access token that the deploy step
        # stored in a secret and injected as the FMAPI_HOST and FMAPI_TOKEN environment variables. That
        # token belongs to a principal that can reach the pay-per-token Foundation Model API. The serving
        # runtime's own default credential is scoped down to the model's declared resources and cannot
        # reach it, so it fails with the confusing "USE CATALOG on system" permission error.
        #
        # When those variables are absent (the local test in Section 3) we fall back to default
        # authentication, which already reaches the endpoint from the notebook.
        import os

        from databricks.sdk import WorkspaceClient

        host = os.environ.get("FMAPI_HOST")
        token = os.environ.get("FMAPI_TOKEN")
        if host and token:
            client = WorkspaceClient(host=host, token=token)
        else:
            client = WorkspaceClient()
        return client.serving_endpoints.get_open_ai_client()

    @mlflow.trace(span_type="AGENT")
    def _run(self, question: str) -> str:
        client = self._client()
        messages = [
            {"role": "system", "content": "You are a clinical triage assistant. Use the tools to look "
             "up a patient's risk score and classify the band. Do not guess scores or bands. If the "
             "patient id is unknown, say so."},
            {"role": "user", "content": question},
        ]

        # Let the model call tools until it stops asking for them (cap the loop for safety).
        for _ in range(5):
            completion = client.chat.completions.create(
                model=LLM_ENDPOINT, messages=messages, tools=TOOLS,
            )
            choice = completion.choices[0].message
            if not choice.tool_calls:
                return choice.content or ""

            messages.append(choice.to_dict() if hasattr(choice, "to_dict") else dict(choice))
            for call in choice.tool_calls:
                args = json.loads(call.function.arguments)
                result = TOOL_FNS[call.function.name](**args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                })

        return "Stopped after too many tool calls."

    def _question_text(self, request: ResponsesAgentRequest) -> str:
        question = request.input[-1].content
        if isinstance(question, list):  # ResponsesAgent typed content
            return " ".join(part.get("text", "") for part in question if isinstance(part, dict))
        return question

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        answer = self._run(self._question_text(request))
        # create_text_output_item builds a schema-valid output item (including the required id),
        # rather than hand-rolling the dict.
        return ResponsesAgentResponse(
            output=[self.create_text_output_item(text=answer, id=str(uuid.uuid4()))]
        )

    def predict_stream(
        self, request: ResponsesAgentRequest
    ) -> Generator[ResponsesAgentStreamEvent, None, None]:
        # Non-streaming demo: emit the whole answer as one completed item.
        answer = self._run(self._question_text(request))
        yield ResponsesAgentStreamEvent(
            type="response.output_item.done",
            item=self.create_text_output_item(text=answer, id=str(uuid.uuid4())),
        )


print("Agent defined with 2 traced tools.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3: Try it locally and look at the trace
# MAGIC
# MAGIC One call before logging, to confirm the tool loop works and to generate a trace we can inspect inline.
# MAGIC This runs wherever the Foundation Model API is reachable, including where Model Serving is not
# MAGIC available, so the workshop can see a real span tree even on Free Edition. If the model is not reachable
# MAGIC or does not support tool calling, we explain and carry on rather than fail.

# COMMAND ----------

local_run_ok = False
try:
    agent = TracedTriageAgent()
    req = ResponsesAgentRequest(
        input=[{"role": "user", "content": "What risk band is patient p004 in?"}]
    )
    result = agent.predict(req)
    print(result.output[0].model_dump()["content"][0]["text"])
    local_run_ok = True
except Exception as e:
    print(f"Local agent run did not complete here: {type(e).__name__}: {e}")
    print(f"\nThe '{LLM_ENDPOINT}' Foundation Model API model may not be available in this workspace,")
    print("or it may not support tool calling. Set LLM_ENDPOINT in Section 1 to an available tool-calling")
    print("model (databricks serving-endpoints list). The registration step below still works.")

# COMMAND ----------

# MAGIC %md
# MAGIC The call above should have produced a multi-span trace: the agent, a Foundation Model API call where
# MAGIC the model decides to call `get_patient_risk_score`, the tool, another model call that decides to call
# MAGIC `classify_risk_band`, that tool, and a final model call that writes the answer. Open the trace from the
# MAGIC cell output or the notebook's MLflow run to see the tree. That tree is the payoff of instrumenting the
# MAGIC agent: you can see which tool ran with what arguments and where the time and tokens went, per request.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4: Log and register the agent in Unity Catalog
# MAGIC
# MAGIC We log the agent as a pyfunc model and register it in Unity Catalog. The Foundation Model API model is
# MAGIC recorded as a resource, so serving knows the agent depends on it. Registration works on Free Edition
# MAGIC even though the deploy step below does not.

# COMMAND ----------

from mlflow.models.resources import DatabricksServingEndpoint

mlflow.set_registry_uri("databricks-uc")

with mlflow.start_run(run_name="clinical_triage_agent") as run:
    logged = mlflow.pyfunc.log_model(
        artifact_path=MODEL_NAME,
        python_model=TracedTriageAgent(),
        # httpx is what the OpenAI-compatible client (get_open_ai_client) uses to make calls; it must be
        # in the served environment or inference fails with "No module named 'httpx'".
        pip_requirements=["mlflow", "databricks-sdk", "openai", "httpx"],
        resources=[DatabricksServingEndpoint(endpoint_name=LLM_ENDPOINT)],
        input_example={"input": [{"role": "user", "content": "What band is patient p001 in?"}]},
    )

print(f"Logged: {logged.model_uri}")

model_version = mlflow.register_model(model_uri=logged.model_uri, name=UC_MODEL_NAME)
print(f"Registered {UC_MODEL_NAME} version {model_version.version}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5: Check that Model Serving is available
# MAGIC
# MAGIC The deploy step needs Model Serving, which is not on Free Edition and is region-gated. We probe once;
# MAGIC if it is unreachable the rest of the notebook explains rather than fails.

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
    print("Run the deploy step on the client's own workspace. The pattern below is unchanged there.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 6: A credential the served agent can call the model with
# MAGIC
# MAGIC The serving runtime's own credential cannot reach the pay-per-token Foundation Model API (it fails with
# MAGIC `USE CATALOG on system`), so we mint a personal access token, store it in a secret, and inject it into
# MAGIC the deployment's environment. `agents.deploy` passes `environment_vars` straight through to the served
# MAGIC entity, so the `FMAPI_HOST` / `FMAPI_TOKEN` the agent reads in Section 2 are resolved at serve time.
# MAGIC
# MAGIC Skipped where serving is unavailable, since there is nothing to deploy.

# COMMAND ----------

SECRET_SCOPE = f"{MODEL_NAME}_serving"
HOST_KEY = "fmapi_host"
TOKEN_KEY = "fmapi_token"

if serving_available:
    if SECRET_SCOPE not in {s.name for s in w.secrets.list_scopes()}:
        w.secrets.create_scope(scope=SECRET_SCOPE)
        print(f"Created secret scope '{SECRET_SCOPE}'.")

    # put_secret overwrites, so re-running rotates the stored token.
    minted = w.tokens.create(
        comment=f"{MODEL_NAME} serving Foundation Model API access",
        lifetime_seconds=90 * 24 * 3600,
    )
    w.secrets.put_secret(scope=SECRET_SCOPE, key=HOST_KEY, string_value=w.config.host)
    w.secrets.put_secret(scope=SECRET_SCOPE, key=TOKEN_KEY, string_value=minted.token_value)
    print(f"Stored Foundation Model API host and token in secret scope '{SECRET_SCOPE}'.")
else:
    print("Skipped: Model Serving is not available (see Section 5).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 7: Deploy with agents.deploy
# MAGIC
# MAGIC This is the step that differs from notebook 08's hand-built endpoint. `agents.deploy` creates (or
# MAGIC updates) the serving endpoint, turns on MLflow tracing, wires the endpoint to an MLflow experiment for
# MAGIC near-real-time traces, and provisions the payload tables. We pass the Foundation Model API credential
# MAGIC through `environment_vars`. `scale_to_zero` keeps an idle endpoint free at the cost of a cold start on
# MAGIC the first request. Re-running updates the endpoint in place.

# COMMAND ----------

if serving_available:
    from databricks import agents

    deployment = agents.deploy(
        model_name=UC_MODEL_NAME,
        model_version=int(model_version.version),
        scale_to_zero=True,
        endpoint_name=ENDPOINT_NAME,
        environment_vars={
            # The agent reads these to build a client that can reach the Foundation Model API.
            # {{secrets/scope/key}} is resolved by Model Serving at serve time, not stored in clear.
            "FMAPI_HOST": f"{{{{secrets/{SECRET_SCOPE}/{HOST_KEY}}}}}",
            "FMAPI_TOKEN": f"{{{{secrets/{SECRET_SCOPE}/{TOKEN_KEY}}}}}",
        },
        tags={"demo": "clinical_triage_agent", "deploy_path": "agents_api"},
    )
    print(f"Deployed {UC_MODEL_NAME} v{model_version.version} to endpoint '{ENDPOINT_NAME}'.")
    print(f"Query endpoint: {getattr(deployment, 'query_endpoint', '(see serving UI)')}")
    print("\nNext: run notebook 11 to query the endpoint and read the traces back.")
else:
    print("Skipped deploy. See Section 5 for why. Run this on the client's workspace to deploy.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recap
# MAGIC
# MAGIC - **This build serves in batch.** Like notebook 08, this is an optional reference pattern. Use it
# MAGIC   where request-time agent behaviour is genuinely needed.
# MAGIC - **Tracing earns its place on a multi-step agent.** A classical classifier (notebook 08) has nothing
# MAGIC   internal to trace, so it uses request/response capture; a tool-calling agent produces a span tree, so
# MAGIC   tracing shows the model's tool choices and where latency and token cost go, per request.
# MAGIC - **agents.deploy is the recommended path for agents.** It turns on tracing, wires an MLflow experiment
# MAGIC   for near-real-time traces, and provisions the payload tables, rather than leaving traces only in the
# MAGIC   best-effort inference table.
# MAGIC - **The served agent needs a credential that can reach the Foundation Model API.** The serving
# MAGIC   runtime's own credential cannot; a secret-backed personal access token supplies it.
# MAGIC
# MAGIC **Run notebook 11 next** to query the deployed endpoint and read the traces back. Remember the endpoint
# MAGIC is not torn down for you: delete it by hand (`w.serving_endpoints.delete(name=ENDPOINT_NAME)`) when you
# MAGIC are done, or it lingers (it scales to zero, so an idle one is cheap).
