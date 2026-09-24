# Databricks notebook source
# MAGIC %md
# MAGIC # Start / stop the Databricks App
# MAGIC
# MAGIC Driven by the `action` job parameter:
# MAGIC - `stop`  -> stop the app's compute (`apps.stop`).
# MAGIC - `start` -> **(re)deploy** the app so it comes back up WITH its env vars.
# MAGIC
# MAGIC **Why start = deploy, not `apps.start`.** Databricks Apps apply env vars at
# MAGIC DEPLOY time. A bare compute start resumes the app but drops the env vars
# MAGIC (`config.env`) - and the API masks env *values* on read, so they cannot be
# MAGIC recovered from the running app. To bring the app up fully configured we
# MAGIC redeploy with the env values, which the bundle passes in via `env_json`
# MAGIC (wired from the same variables the app's `config.env` uses, so the VALUES
# MAGIC stay single-sourced in `config/targets.yml`).

# COMMAND ----------

# The serverless runtime ships an older databricks-sdk without apps.EnvVar /
# AppDeployment.env_vars. Upgrade so the deploy-with-env path below works.
# MAGIC %pip install --quiet --upgrade "databricks-sdk>=0.68"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("action", "start")
dbutils.widgets.text("app_name", "")
dbutils.widgets.text("env_json", "[]")

action = dbutils.widgets.get("action").strip().lower()
app_name = dbutils.widgets.get("app_name").strip()
env_json = dbutils.widgets.get("env_json")

if not app_name:
    raise ValueError("app_name is required (the bundle passes it in).")
if action not in ("start", "stop"):
    raise ValueError(f"action must be 'start' or 'stop', got {action!r}.")

print(f"action={action}  app_name={app_name}")

# COMMAND ----------

import json
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import AppDeployment, EnvVar

w = WorkspaceClient()  # ambient auth = the job's run identity (needs CAN_MANAGE on the app)


def _name(x):
    # Normalise an enum/str to its bare name ("ACTIVE", "RUNNING", ...), robust
    # across SDK versions.
    return getattr(x, "value", None) or getattr(x, "name", None) or (str(x) if x else "")


def snapshot(name):
    a = w.apps.get(name=name)
    compute = _name(a.compute_status.state if a.compute_status else None)
    app_state = _name(a.app_status.state if a.app_status else None)
    pending = a.pending_deployment is not None
    return a, compute, app_state, pending


def wait_deployable(name, timeout=900):
    """Wait until compute is ACTIVE and no deployment is in progress.

    apps.start kicks off its own deployment; deploying again before that settles
    fails with "active deployment in progress", so we wait for that to clear. We
    deliberately do NOT wait for app=RUNNING - the start's auto-deploy has no env
    and the redeploy below is what makes the app healthy, so gating on RUNNING
    here would deadlock.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        a, compute, app_state, pending = snapshot(name)
        if compute == "ACTIVE" and not pending:
            return a
        time.sleep(5)
    raise TimeoutError(f"app {name} not deployable within {timeout}s")


_, compute, app_state, _ = snapshot(app_name)
print(f"before: compute={compute} app={app_state}")

if action == "stop":
    # Idempotent: only stop if not already stopped.
    if compute != "STOPPED":
        w.apps.stop(name=app_name).result()
else:
    # An app can only be DEPLOYED while RUNNING, and apps.start errors if it is
    # already ACTIVE - so start only when stopped, wait for that deployment to
    # settle, then redeploy to re-apply the env vars a bare start drops. The
    # startup command comes from app.yaml in the source.
    if compute != "ACTIVE":
        w.apps.start(name=app_name).result()
    app = wait_deployable(app_name)
    # The app's configured source path. Prefer default_source_code_path (kept in
    # sync with the bundle's source_code_path); fall back to the last deployment.
    src = app.default_source_code_path \
        or (app.active_deployment.source_code_path if app.active_deployment else None)
    env_vars = [EnvVar(name=e["name"], value=e["value"]) for e in json.loads(env_json)]
    w.apps.deploy(
        app_name=app_name,
        app_deployment=AppDeployment(source_code_path=src, env_vars=env_vars),
    ).result()

_, compute, app_state, _ = snapshot(app_name)
print(f"after:  compute={compute} app={app_state}")
