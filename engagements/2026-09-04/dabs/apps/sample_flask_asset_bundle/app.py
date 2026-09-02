"""Minimal Databricks App that proves two things:

1. Asset Bundle variables reached the runtime as environment variables. It reads
   the vars that databricks.yml set from `${var.*}` and renders them. If bundle
   substitution worked, APP_ENV shows "dev"/"prod"; if it did not, you would see
   the literal string "${var.env}".

2. A Unity Catalog secret can be consumed without ever placing its value in the
   app config. Only the secret's three-level NAME (UC_SECRET_FULL_NAME) is passed
   in as an environment variable; the app fetches the VALUE at runtime via the
   Unity Catalog secrets API, using its own service-principal identity, gated by
   the READ SECRET privilege on the secret's schema.
"""

import os

from flask import Flask
from databricks.sdk import WorkspaceClient

app = Flask(__name__)

# Populated by resources.apps.<name>.config.env in databricks.yml, where
# ${var.*} is substituted at deploy time.
WATCHED_VARS = ["APP_ENV", "SQL_WAREHOUSE_ID", "UC_SECRET_FULL_NAME"]


# A UC_SECRET_FULL_NAME that has not been pointed at a real secret yet: unset,
# an unsubstituted bundle variable, a `<placeholder>`, or the README example.
_UNCONFIGURED_NAMES = {"", "my_catalog.secrets.external_api_key"}


def _app_principal():
    """The app's own service-principal id, injected at runtime, for grant hints."""
    return os.environ.get("DATABRICKS_CLIENT_ID", "this app's service principal")


def read_uc_secret(full_name):
    """Read a Unity Catalog secret value at runtime, failing gracefully.

    We call the Unity Catalog secrets REST endpoint directly. Returns
    (level, message) where level is one of "ok" | "warn" | "error" and the app
    never raises - every failure mode becomes a readable, actionable message so
    the page always renders:

      - not configured : UC_SECRET_FULL_NAME was never set to a real secret name
      - not found       : the secret does not exist yet
      - forbidden       : the secret exists but this principal lacks READ SECRET
      - ok              : a masked preview of the value

    Each message says what to do in Unity Catalog directly, so it stands on its
    own regardless of how the secret was (or will be) created.
    """
    if full_name in _UNCONFIGURED_NAMES or full_name.startswith("${") or "<" in full_name:
        return (
            "warn",
            "UC_SECRET_FULL_NAME is not set to a real secret. Set it to the "
            "secret's three-level name (catalog.schema.name) in the app's "
            "environment variables, then restart the app.",
        )

    try:
        w = WorkspaceClient()  # uses the app service principal's ambient auth
        resp = w.api_client.do(
            "GET",
            f"/api/2.1/unity-catalog/secrets/{full_name}",
            query={"include_value": "true"},
        )
    except Exception as exc:  # noqa: BLE001 - classify, never crash the request
        name = type(exc).__name__
        low = str(exc).lower()
        principal = _app_principal()
        if name == "NotFound" or any(
            s in low for s in ("not found", "does not exist", "no_such", "nosuch", "404")
        ):
            return (
                "error",
                f"Secret '{full_name}' does not exist. Create a Unity Catalog secret "
                "with this catalog.schema.name (in Catalog Explorer, or with a "
                "CREATE query), then reload.",
            )
        if name == "PermissionDenied" or any(
            s in low for s in ("permission", "does not have", "read_secret", "read secret", "403")
        ):
            return (
                "error",
                f"Cannot read '{full_name}': it does not exist yet, or {principal} "
                "cannot access it. In Unity Catalog, make sure the secret exists and "
                "grant this app's service principal USE CATALOG on the catalog and "
                "USE SCHEMA + READ SECRET on the schema, then reload.",
            )
        return ("error", f"Unexpected error reading secret: {name}: {exc}")

    value = resp.get("effective_value")
    if not value:
        return ("warn", f"Secret '{full_name}' exists but returned no value.")
    masked = value[:3] + "*" * max(len(value) - 3, 3)
    return ("ok", masked)


@app.route("/")
def index():
    rows = ""
    for name in WATCHED_VARS:
        value = os.environ.get(name, "(not set)")
        looks_literal = value.startswith("${") and value.endswith("}")
        flag = " ⚠️ NOT SUBSTITUTED" if looks_literal else ""
        rows += f"<tr><td><code>{name}</code></td><td><code>{value}</code>{flag}</td></tr>"

    level, detail = read_uc_secret(os.environ.get("UC_SECRET_FULL_NAME", ""))
    if level == "ok":
        secret_status = f"<span style='color:green'>READ OK</span> (masked: <code>{detail}</code>)"
    elif level == "warn":
        secret_status = f"<span style='color:#b8860b'>not configured</span> — {detail}"
    else:
        secret_status = f"<span style='color:#b00'>could not read</span> — {detail}"

    return (
        "<h1>Asset Bundle variable + Unity Catalog secret passthrough</h1>"
        "<p>The values below came from <code>${var.*}</code> declared in "
        "<code>databricks.yml</code> and injected via "
        "<code>resources.apps.&lt;name&gt;.config.env</code>.</p>"
        "<table border='1' cellpadding='8' cellspacing='0'>"
        "<tr><th>Environment variable</th><th>Value</th></tr>"
        f"{rows}</table>"
        "<h2>Unity Catalog secret read at runtime</h2>"
        "<p>Only the secret's name is passed in as an environment variable. The app "
        "attempts to read the value here at runtime, under the <code>READ SECRET</code> "
        "privilege on the secret's schema. The value never appears in the app config, "
        "and a missing secret or grant is reported below rather than crashing the app.</p>"
        f"<p>{secret_status}</p>"
    )


if __name__ == "__main__":
    # Databricks Apps provides the port to listen on via DATABRICKS_APP_PORT
    # (defaults to 8000). Always bind 0.0.0.0.
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
