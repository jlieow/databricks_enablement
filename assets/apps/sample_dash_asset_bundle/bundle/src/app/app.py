"""Minimal Dash app for the "deployable with Asset Bundles" demo.

The app is a small Plotly Dash page: a heading, a scatter chart, and a button
that triggers a Databricks job. The demo-relevant additions over a bare Dash
starter are:

  1. It reads its title / environment / name and the demo job's id from
     environment variables the Asset Bundle passes in (resources/app.yml ->
     config.env), so per-target values are visible in the UI.
  2. A button calls jobs.run_now on that job. The app is ALLOWED to because the
     bundle declares the job as one of the app's resources with CAN_MANAGE_RUN
     (resources/app.yml -> resources), which grants the app's service principal
     that permission and is what populates the app's "Resources" tab.
  3. It binds to the port Databricks Apps provides.
"""

import os

import pandas as pd
import plotly.express as px
import dash_bootstrap_components as dbc
from dash import Dash, dcc, html, Input, Output
from databricks.sdk import WorkspaceClient

# Set by resources/app.yml -> config.env, where ${var.*} / ${resources.*} are
# substituted at deploy time. For a local run, run_local.sh loads them from
# local.env instead.
app_title = os.environ.get("APP_TITLE", "Dash Asset Bundle")
app_env = os.environ.get("APP_ENV", "(unknown)")
app_name = os.environ.get("APP_NAME", "(unknown)")
job_id = os.environ.get("JOB_ID", "")
warehouse_id = os.environ.get("WAREHOUSE_ID", "")

# The chart query. The whole point of the demo: this computation runs ON THE SQL
# WAREHOUSE, not in the app process. The app just plots the small result.
CHART_QUERY = "SELECT id AS x, pow(2, id) AS y FROM range(30) ORDER BY id"


def load_chart_data():
    """Return (dataframe, caption).

    Offloads the calculation to the SQL warehouse via the Statement Execution
    API (databricks-sdk, same ambient SP auth the button uses - allowed because
    the bundle granted the app CAN_USE on the warehouse). If no WAREHOUSE_ID is
    set (a local `run_local.sh` run has no warehouse or SP auth), or the query
    fails, fall back to computing in pandas so the page still renders - the
    caption says which path produced the data.
    """
    if not warehouse_id:
        df = pd.DataFrame({"x": range(30), "y": [2 ** x for x in range(30)]})
        return df, "Computed locally in pandas (no WAREHOUSE_ID set)."
    try:
        w = WorkspaceClient()
        resp = w.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=CHART_QUERY,
            wait_timeout="50s",  # synchronous; 50s is the max before it goes async
        )
        rows = resp.result.data_array if resp.result else None
        if not rows:
            raise RuntimeError(f"query returned no rows (state={resp.status.state if resp.status else '?'})")
        df = pd.DataFrame(rows, columns=["x", "y"]).astype(float)
        return df, f"Computed on SQL warehouse {warehouse_id} via the Statement Execution API."
    except Exception as exc:
        df = pd.DataFrame({"x": range(30), "y": [2 ** x for x in range(30)]})
        return df, f"Warehouse query failed ({exc}); fell back to local pandas."


# Initialise the Dash app with Bootstrap styling.
dash_app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

chart_data, chart_source = load_chart_data()

# Databricks Apps looks for a WSGI callable named `app` (or the object the
# startup command runs). Exposing the underlying Flask server also lets a WSGI
# server host it if the command is ever changed to use one.
app = dash_app.server

dash_app.layout = dbc.Container([
    dbc.Row([dbc.Col(html.H1(app_title), width=12)]),
    dbc.Row([dbc.Col(html.P(f"Launched from the '{app_env}' environment."), width=12)]),
    dbc.Row([dbc.Col([
        dbc.Button("Trigger the print job", id="trigger-job-btn",
                   color="primary", n_clicks=0),
        html.Div(id="run-status", style={"marginTop": "12px"}),
    ], width=12)], className="mb-3"),
    dcc.Graph(
        id="fare-scatter",
        figure=px.scatter(chart_data, x="x", y="y",
            labels={"x": "Apps", "y": "Fun with data"},
            template="simple_white"),
        style={"height": "500px", "width": f"{min(100 + 50 * 30, 1000)}px"},
    ),
    dbc.Row([dbc.Col(html.Small(chart_source, className="text-muted"), width=12)]),
], fluid=True)


@dash_app.callback(
    Output("run-status", "children"),
    Input("trigger-job-btn", "n_clicks"),
    prevent_initial_call=True,
)
def trigger_job(n_clicks):
    """Kick off the app_name_demo job, passing this app's name as a run param.

    WorkspaceClient() uses the app's ambient service-principal auth. The call
    only succeeds because the bundle granted that SP CAN_MANAGE_RUN on the job
    (the app resource binding). run_now returns immediately with a run id - we do
    NOT block on completion, so the button stays responsive.
    """
    if not job_id:
        return "JOB_ID is not set - is the app_name_demo job attached as a resource?"
    try:
        w = WorkspaceClient()
        run = w.jobs.run_now(job_id=int(job_id),
                             job_parameters={"app_name": app_name})
        run_url = f"{w.config.host}/jobs/{job_id}/runs/{run.run_id}"
        return html.Div([
            html.Span(
                f"Triggered run {run.run_id}. The job prints "
                f"\"Triggered by app: {app_name}\". "
            ),
            html.A("Open the run", href=run_url, target="_blank"),
        ])
    except Exception as exc:  # surface the error in the UI rather than 500ing
        return f"Failed to trigger job {job_id}: {exc}"


if __name__ == "__main__":
    # Databricks Apps provides the port to listen on via DATABRICKS_APP_PORT
    # (defaults to 8000). Always bind 0.0.0.0.
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    dash_app.run(host="0.0.0.0", port=port)
