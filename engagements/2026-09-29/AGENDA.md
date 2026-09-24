# Databricks Apps with Asset Bundles: which file goes with which agenda item

Everything here is a **completed reference copy**. We build and deploy it live during the session;
use it to catch up if you fall behind, and to refer back to afterwards.

This is a focused hands-on workshop on **packaging and deploying a Databricks App with Databricks
Asset Bundles (DABs)**, and on wiring an app to the other resources it needs. The team is new to
Databricks Apps but comfortable with Python and the CLI, so the time goes on the bundle mechanics
and the platform gotchas, not on the app framework itself.

The app is deliberately trivial - a Plotly Dash page with a chart and a button. The interesting
parts are everything around it: the multifile bundle layout, the app `resources` block (a job and a
SQL warehouse the app is granted), offloading the chart's calculation to the warehouse, triggering
a job from a button in the app, scheduled start/stop jobs, and a per-user deploy that works whether
attendees are each in their own workspace (as on Free Edition) or ever share one.

> **Pre-work:** complete [`../../shared/prework.md`](../../shared/prework.md) first (Free Edition
> account + Databricks CLI authenticated to a profile).

---

## The asset: one reusable bundle

The entire workshop is driven by one reusable asset, kept outside this engagement so other sessions
can reuse it:

**[`../../assets/apps/sample_dash_asset_bundle/`](../../assets/apps/sample_dash_asset_bundle/)**

Start with its [`README.md`](../../assets/apps/sample_dash_asset_bundle/README.md) - it has the
Quickstart, the file map, and a section per concept below. All `databricks bundle` commands run from
that bundle's `bundle/` directory.

## Agenda

| # | Agenda item | Where in the asset |
| --- | --- | --- |
| 1 | Deploy an app with a bundle: validate → deploy → run | `README.md` (Quickstart), `bundle/databricks.yml`, `bundle/config/` |
| 2 | The multifile layout: one block per file, merged by `include:` | `bundle/databricks.yml`, `bundle/config/`, `bundle/resources/` |
| 3 | The variable chain: `variables.yml` → `resources/app.yml` → `targets.yml` | `bundle/config/variables.yml`, `bundle/resources/app.yml`, `bundle/config/targets.yml` |
| 4 | The app `resources` block: grant the app a job and a SQL warehouse | `bundle/resources/app.yml`, `bundle/resources/job.yml` |
| 5 | Offload the chart query to the SQL warehouse (Statement Execution API) | `bundle/src/app/app.py`, `bundle/resources/app.yml` (warehouse binding) |
| 6 | Trigger a job from a button in the app (`jobs.run_now` + `CAN_MANAGE_RUN`) | `bundle/src/app/app.py`, `bundle/resources/job.yml` |
| 7 | Scheduled start/stop jobs (turn the app off out of hours) | `bundle/resources/job.yml`, `bundle/src/jobs/app_lifecycle.py` |
| 8 | Deploying per-user so it works whether workspaces are individual or shared | `bundle/config/targets.yml`, `README.md` (Multiple people, one workspace) |

Notes on the mapping:

- **Attendees run this in their own Databricks Free Edition workspace.** Two edition specifics,
  both covered in the asset README's *Free Edition notes*: (1) the bundle references the workspace's
  one pre-provisioned SQL warehouse rather than creating one (Free Edition caps the account at one),
  passed in as `--var="warehouse_id=$wid"` - the Quickstart has the copy-paste one-liner to look up
  `$wid`; (2) apps auto-stop after 24h idle, so have attendees deploy and start within the session.
- **Item 4 is the heart of the session.** The app declares a job (`CAN_MANAGE_RUN`) and the existing
  warehouse (`CAN_USE`) as its own resources; deploying the bundle both lists them in the app's
  **Resources** tab and grants the app's service principal those permissions. Items 5 and 6 then
  *use* those grants (query the warehouse; trigger the job from a button).
- **Item 8 covers both setups.** The `dev` target runs in development mode (per-user `[dev <user>]`
  jobs, per-user workspace path, paused schedules) and derives the app name from the numeric user id.
  That is unnecessary when everyone has their own Free Edition workspace, but harmless - and it means
  the same asset also works if a group ever shares one workspace, without anyone changing config.
- **Teardown:** `databricks bundle destroy -t dev` removes the app and jobs. It does NOT touch the
  shared SQL warehouse - the bundle only references it.
