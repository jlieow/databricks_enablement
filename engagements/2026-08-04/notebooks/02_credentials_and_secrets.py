# Databricks notebook source
# MAGIC %md
# MAGIC # 02. Storing credentials: secret scopes and UC secrets
# MAGIC
# MAGIC Three places a credential can live, and they are not interchangeable. This notebook covers
# MAGIC the two that Python code uses. The third, the UC connection, is what SQL and Lakeflow
# MAGIC Designer use instead, since neither can reach `dbutils`.
# MAGIC
# MAGIC | | Secret scope | Unity Catalog secret | UC connection |
# MAGIC |---|---|---|---|
# MAGIC | Lives in | Workspace | `catalog.schema` | Metastore |
# MAGIC | Created with | CLI or Python SDK | REST API | `CREATE CONNECTION` in SQL |
# MAGIC | Read with | `dbutils.secrets.get(scope, key)` | `dbutils.secrets.get(catalog=, schema=, key=)` | `http_request(conn => ...)` |
# MAGIC | For | Python code | Python code, better governed | SQL, and Lakeflow Designer |
# MAGIC
# MAGIC This build uses a **secret scope**, which works everywhere. A scope is a workspace object
# MAGIC with its own ACLs, not something inside a catalog: `dbutils.secrets.get()` takes a scope
# MAGIC name, never a three-part `catalog.schema.name`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Part 1: Secret scopes
# MAGIC
# MAGIC A scope is a named container of key/value secrets. Nothing exists yet, so we create the
# MAGIC scope and the secrets before reading them back.
# MAGIC
# MAGIC `dbutils.secrets` is the **read** side only: it cannot create anything. Writing goes
# MAGIC through one of two clients, both calling the same API:
# MAGIC
# MAGIC | | Use it for |
# MAGIC |---|---|
# MAGIC | **CLI**, from a terminal | The normal case. The credential holder puts it in place out of band, and it never appears in notebook code |
# MAGIC | **Python SDK**, in a cell | Scripted setup, seeding a workspace, or a rotation job |
# MAGIC
# MAGIC We do both, writing one key each so you can see them land side by side in the same scope.

# COMMAND ----------

SCOPE = "enablement_demo"

CLI_KEY = "api_token_via_cli"        # written by the CLI, below
SDK_KEY = "api_token_via_py_sdk"     # written by the SDK cell, below

# COMMAND ----------

# MAGIC %md
# MAGIC ### Path 1: the CLI
# MAGIC
# MAGIC Run this in a terminal, not in a cell. `create-scope` makes the container, `put-secret`
# MAGIC writes a key into it.
# MAGIC
# MAGIC ```bash
# MAGIC # One-off, if this machine has not been authenticated before. Opens a browser;
# MAGIC # the profile name is yours to choose.
# MAGIC databricks auth login --host https://your-workspace.cloud.databricks.com --profile enablement
# MAGIC
# MAGIC # The scope. A workspace container, not a catalog object, so no catalog name here.
# MAGIC databricks secrets create-scope enablement_demo --profile enablement
# MAGIC
# MAGIC # A key, written by the CLI. The value can be any non-empty string: nothing in this
# MAGIC # build authenticates against a real endpoint, so the mechanism is the point.
# MAGIC databricks secrets put-secret enablement_demo api_token_via_cli \
# MAGIC   --string-value "cli-token" --profile enablement
# MAGIC
# MAGIC # Confirm. Prints key names, never values.
# MAGIC databricks secrets list-scopes --profile enablement
# MAGIC databricks secrets list-secrets enablement_demo --profile enablement
# MAGIC
# MAGIC # Delete Secret
# MAGIC databricks secrets delete-secret enablement_demo api_token
# MAGIC ```
# MAGIC
# MAGIC `put-secret` is the same command for create and update: run it again with a different
# MAGIC `--string-value` and the existing value is overwritten. That is how rotation works, and
# MAGIC it means the command is safe to re-run.
# MAGIC
# MAGIC In production this is exactly where a Facebook or Google Ads token goes, and none of
# MAGIC the code that reads it changes. In the UI the same objects appear under
# MAGIC **Catalog > Secrets**.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Path 2: the Python SDK
# MAGIC
# MAGIC The same two API calls, from a cell. `WorkspaceClient()` needs no credentials in a
# MAGIC notebook: it authenticates as you.
# MAGIC
# MAGIC The drawback is visible in the code: the value is hardcoded, and a notebook cell is
# MAGIC saved, versioned and readable by anyone with access to the notebook. Fine for a throwaway
# MAGIC demo value, wrong for a real credential. That asymmetry is the reason the CLI is the
# MAGIC default advice, not the SDK.

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import ResourceAlreadyExists

w = WorkspaceClient()

# create_scope raises if the scope exists, which it will if you ran the CLI above, so this is
# wrapped to stay re-runnable. put_secret needs no such guard: it overwrites by design.
try:
    w.secrets.create_scope(SCOPE)
    print(f"Created scope {SCOPE}.")
except ResourceAlreadyExists:
    print(f"Scope {SCOPE} already exists, continuing.")

w.secrets.put_secret(SCOPE, SDK_KEY, string_value="py-sdk-token")
print(f"Wrote {SCOPE}/{SDK_KEY}.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Read it back
# MAGIC
# MAGIC Now `dbutils.secrets`, which is the read side, available in any notebook with no client
# MAGIC to construct. Both writes land in the same scope: the API does not record which client
# MAGIC made them, so `api_token_via_cli` and `api_token_via_py_sdk` are indistinguishable here
# MAGIC apart from the names we chose.

# COMMAND ----------

# Scopes visible to you. The SecretScope object exposes only .name, so use the CLI
# (databricks secrets list-scopes) if you need the backend type.
for s in dbutils.secrets.listScopes():
    print(s.name)

# COMMAND ----------

# Keys in our scope. Note this lists key NAMES only, never values.
for k in dbutils.secrets.list(SCOPE):
    print(k.key)

# COMMAND ----------

# Confirm each key is readable, without printing any value. Lengths only here; the next
# section covers why that is the right habit and what else to check.
for k in (CLI_KEY, SDK_KEY):
    try:
        print(f"{k:24s} {len(dbutils.secrets.get(scope=SCOPE, key=k)):>3} chars")
    except Exception as e:
        # Expected for CLI_KEY if you only ran the SDK cell, and vice versa.
        print(f"{k:24s} not found ({type(e).__name__})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Part 2: Unity Catalog secrets
# MAGIC
# MAGIC The newer mechanism: secrets as real UC objects in a `catalog.schema`, governed by UC
# MAGIC grants rather than a separate set of workspace ACLs. There is no `CREATE SECRET` DDL to
# MAGIC rely on: create via the REST API, read via `dbutils.secrets` with the `catalog=` /
# MAGIC `schema=` keywords (needs DBR 17.3 LTS+ or serverless env v4+), grant via SQL.
# MAGIC
# MAGIC ### Create, read, and grant UC secrets
# MAGIC
# MAGIC **Create** via UI
# MAGIC
# MAGIC In your Databricks workspace, click Catalog to open Catalog Explorer.
# MAGIC Go to the schema where you want to create the secret.
# MAGIC Click Create > Secret.
# MAGIC Enter a name and value. Optionally, add a comment and an expiration date. If a secret expires, Catalog Explorer shows a warning.
# MAGIC Click Create.
# MAGIC
# MAGIC **Create** from the same terminal. `databricks api post` handles auth from your profile,
# MAGIC so this is the REST call without the `curl` ceremony:
# MAGIC ```bash
# MAGIC databricks api post /api/2.1/unity-catalog/secrets --profile enablement --json '{
# MAGIC   "catalog_name": "enablement", "schema_name": "01_raw",
# MAGIC   "name": "example_secret", "value": "your_secret_value" }'
# MAGIC ```
# MAGIC
# MAGIC **Read** (requires DBR 17.3 LTS+ or serverless env v4+):
# MAGIC ```python
# MAGIC my_secret = dbutils.secrets.get(catalog="enablement", schema="01_raw", key="example_secret")
# MAGIC ```
# MAGIC
# MAGIC **Grant** using UC SQL (inherits from schema grants):
# MAGIC ```sql
# MAGIC GRANT READ SECRET ON SECRET enablement.01_raw.example_secret TO `user@example.com`;
# MAGIC ```

# COMMAND ----------

UC_CATALOG = "enablement"
UC_SCHEMA = "01_raw"
UC_SECRET_NAME = "example_secret"
UC_FULL_NAME = f"{UC_CATALOG}.{UC_SCHEMA}.{UC_SECRET_NAME}"

# Confirm the object exists over the REST API first, so the read failure below is clearly
# about the read path and not a missing or misnamed object.
# The API is the only surface that works here: DESCRIBE SECRET fails with UC_SECRETS_NOT_ENABLED.
from databricks.sdk import WorkspaceClient

print(f"Does {UC_FULL_NAME} exist?")
try:
    meta = WorkspaceClient().api_client.do(
        "GET", f"/api/2.1/unity-catalog/secrets/{UC_FULL_NAME}"
    )
    # Metadata only. The API never returns the value, by design.
    print(f"  yes, created {meta.get('create_time')} by {meta.get('created_by')}")
    print(f"  securable_kind={meta.get('securable_kind')}, no value field in the response")
except Exception as e:
    print(f"  {type(e).__name__}: {str(e)[:200]}")

# The only documented read path. Wrapped because the keyword arguments do not exist on older
# runtimes, which is exactly the failure worth showing.
print("\ndbutils.secrets.get(catalog=, schema=, key=)")
try:
    v = dbutils.secrets.get(catalog=UC_CATALOG, schema=UC_SCHEMA, key=UC_SECRET_NAME)
    print(f"  SUCCESS: read {len(v)} characters.")
    print("  UC secrets work here, so prefer them over workspace secret scopes.")
except TypeError as e:
    print(f"  TypeError: {e}")
    print("  Needs Databricks Runtime 17.3 LTS+ or serverless environment version 4+.")
except Exception as e:
    print(f"  {type(e).__name__}: {str(e)[:200]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Prefer UC secrets when enabled
# MAGIC
# MAGIC UC secret governance integrates with UC grants, and per-client schemas naturally scope
# MAGIC credentials without naming conventions.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next
# MAGIC
# MAGIC Two mechanisms covered, both for Python:
# MAGIC
# MAGIC - **Secret scope**, created by CLI or SDK, read with `dbutils.secrets.get(scope, key)`. No
# MAGIC   runtime floor, so it works on any compute.
# MAGIC - **UC secret**, created by REST API, read with `dbutils.secrets.get(catalog=, schema=, key=)`
# MAGIC   on DBR 17.3 LTS+ or serverless env v4+. Governed by UC grants, so the schema you put it in
# MAGIC   is the access control. Prefer this where the runtime supports it.
# MAGIC
# MAGIC The third mechanism, the **UC connection**, is what SQL and Lakeflow Designer use, because a
# MAGIC SQL UDF cannot reach `dbutils`. It is covered in the Lakeflow Designer guide.
# MAGIC
# MAGIC Notebook 03 calls an API that needs no credential, so it reads none of these. The mechanism
# MAGIC is what matters here: a real ad platform API is the same `requests` call with one of the above
# MAGIC supplying the token.
# MAGIC
# MAGIC Next: notebook 03 ingests from an API into a raw table.