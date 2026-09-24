# Dash app deployed with Asset Bundles

A minimal [Plotly Dash](https://dash.plotly.com/) app (a heading, a scatter
chart, and a button) packaged as a Databricks Asset Bundle. It shows three
things:

- **the app `resources` block** - the app declares a job AND a SQL warehouse as
  its resources (with `CAN_MANAGE_RUN` / `CAN_USE`), which populates the app's
  **Resources** tab and grants the app's service principal those permissions;
- **the chart query offloaded to the SQL warehouse** - the scatter chart's data
  is computed by a `SELECT` that runs on the warehouse (via the Statement
  Execution API), not in the app process;
- **a button in the app that triggers the job** (`jobs.run_now`), passing the
  app's own name in, so the job prints `Triggered by app: <app name>`;
- **a pair of scheduled jobs that start and stop the app** so its compute is off
  out of hours.

It uses a multifile bundle layout: `databricks.yml` stripped to almost nothing,
every logical section in its own file, pulled back together with `include:`.

> Runs on Databricks **Free Edition** - see [Free Edition notes](#free-edition-notes)
> for the two things that differ there (one shared warehouse, 24-hour app auto-stop).

## Quickstart

Needs the [Databricks CLI](https://docs.databricks.com/en/dev-tools/cli/index.html)
(v0.220+) authenticated to a workspace via a profile. All bundle commands run
from the `bundle/` directory.

```bash
# 0. Clone and enter the bundle
git clone <this-repo>
cd databricks_enablement/assets/apps/sample_dash_asset_bundle/bundle

# 1. Point at your workspace profile (from ~/.databrickscfg)
profile=<DATABRICKS_PROFILE>

# 2. Find your workspace's existing SQL warehouse. Free Edition ships exactly one
#    (the "Serverless Starter Warehouse") and caps the account at one, so the
#    bundle USES it rather than creating a second (which would fail).
wid=$(databricks warehouses list -p $profile -o json | \
  python3 -c "import sys,json; ws=json.load(sys.stdin); ws=ws if isinstance(ws,list) else ws.get('warehouses',[]); print(ws[0]['id'])")
echo "using warehouse $wid"

# 3. Check the config resolves (optional but recommended)
databricks bundle validate -t dev -p $profile --var="warehouse_id=$wid"

# 4. Deploy the resources (the app + the jobs)
databricks bundle deploy -t dev -p $profile --var="warehouse_id=$wid"

# 5. Start / (re)deploy the running app
databricks bundle run sample_dash_asset_bundle -t dev -p $profile
```

Step 5 prints the app URL. Open it, and click **Trigger the print job** to run
the job. The `dev` target is per-user safe: several people can clone and deploy
into the same workspace without colliding (see
[Multiple people, one workspace](#multiple-people-one-workspace)).

Other things you can run (pass the same `--var="warehouse_id=$wid"` to any
`deploy`):

```bash
# Trigger the demo job by hand (prints "Triggered by app: <app name>")
databricks bundle run app_name_demo -t dev -p $profile

# Manually stop / start the app (schedules are auto-paused in dev)
databricks bundle run app_stop  -t dev -p $profile
databricks bundle run app_start -t dev -p $profile

# Tear down the app + jobs this bundle created (the shared warehouse is NOT
# touched - the bundle only references it, it does not own it)
databricks bundle destroy -t dev -p $profile
```

## Layout

```
sample_dash_asset_bundle/
└── bundle/
    ├── databricks.yml          # ONLY `bundle:` + the `include:` list
    ├── config/                 # bundle CONFIG, one block per file
    │   ├── variables.yml        # the `variables:` block
    │   ├── targets.yml          # the `targets:` block (dev / prod)
    │   └── sync.yml             # the `sync:` block (keeps local-only files out of deploys)
    ├── resources/              # resource DEFINITIONS, one file per type
    │   ├── app.yml              # a `resources:` block (the Dash app + its resource bindings)
    │   └── job.yml              # a `resources:` block (demo job + scheduled start/stop jobs)
    └── src/                    # all SOURCE CODE, one subdir per resource type
        ├── app/                #   the app  (source_code_path points here)
        │   ├── app.py           #   Dash app (chart + button that triggers the job)
        │   ├── app.yaml         #   app runtime config (synced as-is; no `${var.*}`)
        │   ├── requirements.txt
        │   ├── local.env        #   LOCAL values for laptop runs (excluded from sync)
        │   └── run_local.sh     #   `uv` one-liner to run locally (excluded from sync)
        └── jobs/               #   job code (a sibling of the app, never inside it)
            ├── app_lifecycle.py #   notebook the start/stop jobs run
            └── triggered_by_app.py #   script the app_name_demo job runs (prints the app name)
```

At deploy time the CLI merges all the config files into one configuration - the
split is purely for humans, and the deployed result is identical to one big
`databricks.yml`.

## The variable chain

The same variables drive three run modes (local, dev, prod). `APP_TITLE` and
`APP_ENV` are shown live in the app page so the active source is visible:

```
config/variables.yml     resources/app.yml         config/targets.yml
   (declare)         ->   (reference ${var.x})  <-   (per-target value)
```

Keep variable-backed env vars in `resources/app.yml` (`config.env`), never in
`src/app/app.yaml`: files under `source_code_path` are synced as-is and are
**not** substituted, so `${var.x}` written in `app.yaml` reaches the app as a
literal string.

## Deploy and verify

```bash
profile=<DATABRICKS_PROFILE>

cd bundle
# The bundle references an EXISTING warehouse - grab its id (see Quickstart):
wid=$(databricks warehouses list -p $profile -o json | \
  python3 -c "import sys,json; ws=json.load(sys.stdin); ws=ws if isinstance(ws,list) else ws.get('warehouses',[]); print(ws[0]['id'])")

databricks bundle validate -t dev -p $profile --var="warehouse_id=$wid"
databricks bundle deploy   -t dev -p $profile --var="warehouse_id=$wid"
# Start / (re)deploy the running app so it picks up new code + env vars:
databricks bundle run sample_dash_asset_bundle -t dev -p $profile
```

Open the app URL. The heading is `Dash Asset Bundle (dev - <you>)` (from
`var.app_title`), the app reports it was launched from the `dev` environment, and
the **Trigger the print job** button kicks off the job (see the section below).

Switch environments by changing only the target (`prod` also needs a
`warehouse_id`):

```bash
databricks bundle deploy -t prod -p $profile --var="warehouse_id=$wid"
databricks bundle run    sample_dash_asset_bundle -t prod -p $profile
```

## Multiple people, one workspace

If several people clone this bundle and deploy it into the **same** workspace,
use the **`dev` target** - it runs in `mode: development`, which namespaces
almost everything per user automatically:

| Resource | In development mode |
|---|---|
| Jobs | prefixed `[dev <user>] …` |
| Workspace files + bundle state | under each user's home (`/Workspace/Users/<you>/.bundle/…`) |
| Schedules | auto-paused |
| SQL warehouse | shared - the bundle references the workspace's one warehouse (not created per user) |
| **App name** | **NOT auto-namespaced** - the one thing you must handle |

Apps are the exception: the CLI does not prefix app names. So the `dev` target
derives the app name from the numeric user id:

```yaml
# config/targets.yml (dev)
app_name: sample-dash-${workspace.current_user.id}   # -> e.g. sample-dash-<your numeric user id>
```

That id is always a valid app-name token (apps allow only lowercase
letters/digits/hyphens, ≤30 chars - which rules out `short_name`, it has
underscores) and unique per person, so no two clones collide. The **heading**
still shows `${workspace.current_user.short_name}`, so a shared workspace shows
whose app is whose even though the URL is opaque. Everyone just runs:

```bash
databricks bundle deploy -t dev -p $profile
databricks bundle run    sample_dash_asset_bundle -t dev -p $profile
```

> **`prod` is not for this.** Production mode namespaces *nothing* (it is meant
> for one canonical deploy from a CI/CD identity), so multiple people on `prod`
> would collide on every resource. Use `dev` for the clone-and-run workflow.

## Run locally

Needs [`uv`](https://docs.astral.sh/uv/). Uses the LOCAL values from `local.env`:

```bash
cd bundle/src/app
./run_local.sh                 # -> http://localhost:8000, APP_ENV=local
```

`app.py` just reads `os.environ`, so it stays identical whether it runs locally
or deployed - `uv --env-file` is what puts `local.env`'s values into the
environment for a local run. `local.env` and `run_local.sh` are committed to git
but excluded from the bundle sync (`config/sync.yml`), so neither is ever
uploaded as app code.

## The app `resources` block, and the button that uses it

An app can declare **its own resources** - a SQL warehouse, a secret, a job, a
Lakebase database, etc. Declaring one both **lists it in the app's Resources tab**
in the UI and **grants the app's service principal a permission on it**. That is
a different `resources:` from the top-level bundle block; it is nested under the
app in [`resources/app.yml`](./bundle/resources/app.yml):

```yaml
resources:
  apps:
    sample_dash_asset_bundle:
      name: ${var.app_name}
      resources:
        - name: app-name-demo-job
          job:
            id: ${resources.jobs.app_name_demo.id}
            permission: CAN_MANAGE_RUN     # the app SP may trigger this job
      config:
        env:
          - name: APP_NAME
            value: ${var.app_name}
          - name: JOB_ID
            value: ${resources.jobs.app_name_demo.id}   # so app.py knows which job
```

The bundle also hands the app the job's numeric id and its own name as env vars
(`config.env`), so `app.py` knows which job to run. The **button** on the app
page calls `jobs.run_now` on that job, passing `APP_NAME` in as a run parameter:

```python
w = WorkspaceClient()                       # the app's ambient SP auth
run = w.jobs.run_now(job_id=int(job_id),
                     job_parameters={"app_name": app_name})
```

That call only succeeds because the app SP was granted `CAN_MANAGE_RUN` by the
resource binding above. The job ([`app_name_demo`](./bundle/resources/job.yml))
runs a plain Python script
([`src/jobs/triggered_by_app.py`](./bundle/src/jobs/triggered_by_app.py)) that
prints the name it was handed:

```
Triggered by app: sample-dash-<your numeric user id>
```

Run the job by hand too (it defaults `app_name` to `${var.app_name}`):

```bash
databricks bundle run app_name_demo -t dev -p $profile
```

Confirm the Resources tab is populated after deploy. Your app is named
`sample-dash-<your numeric user id>` (see the deploy output, or run
`databricks bundle summary -t dev -p $profile`); pass that name here:

```bash
databricks apps get <your-app-name> -p $profile -o json | \
  python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['resources'], indent=2))"
```

> **Avoiding a dependency cycle.** The app references the job
> (`${resources.jobs.app_name_demo.id}`), so the job must **not** reference the
> app back (`${resources.apps.*.name}`) - that would be a cycle the CLI rejects
> (`cycle detected`). Instead the app name is single-sourced as `${var.app_name}`
> (declared in `config/variables.yml`, valued per target in `config/targets.yml`),
> and both the app's `name` and the job's `app_name` parameter read that variable.
> The dependency stays one-directional: app -> job.

> **`spark_python_task` on serverless** needs an `environments:` block plus an
> `environment_key` on the task (a `notebook_task` does not). The empty spec
> (`client: "3"`) just requests the default serverless environment.

## Offloading the chart query to a SQL warehouse

The scatter chart's data is **not** computed in the app process - it is produced
by a `SELECT` that runs on a SQL warehouse. This is the recommended shape for a
Databricks App: the app is a thin serving tier, and data-scale work is pushed to
the lakehouse. (For this toy `pow(2, id)` calc the offload is illustrative, not
necessary; the pattern is what matters for real tables.)

Three pieces wire it together, all mirroring the job binding:

1. **You pass an existing warehouse id** as `${var.warehouse_id}` at deploy time
   (the Quickstart's `wid=$(…)` one-liner reads the workspace's Serverless
   Starter Warehouse). The bundle does **not** create a warehouse - Free Edition
   caps the account at one, so it references the one already there.
2. **The app binds to it** ([`resources/app.yml`](./bundle/resources/app.yml)) with
   `CAN_USE`, and receives its id as the `WAREHOUSE_ID` env var:
   ```yaml
   resources:
     - name: app-warehouse
       sql_warehouse:
         id: ${var.warehouse_id}
         permission: CAN_USE
   ```
3. **`app.py` runs the query** through the Statement Execution API - the same
   `WorkspaceClient()` ambient SP auth the button uses, no extra dependency and
   no connection wiring:
   ```python
   resp = w.statement_execution.execute_statement(
       warehouse_id=warehouse_id,
       statement="SELECT id AS x, pow(2, id) AS y FROM range(30) ORDER BY id",
       wait_timeout="50s",
   )
   df = pd.DataFrame(resp.result.data_array, columns=["x", "y"]).astype(float)
   ```

The call only succeeds because the resource binding granted the app SP `CAN_USE`.
A caption under the chart states which path produced the data, so the offload is
visible: `Computed on SQL warehouse <id> via the Statement Execution API`. If
`WAREHOUSE_ID` is unset (a local `run_local.sh` run) or the query fails, the app
falls back to computing in pandas so the page still renders, and the caption says
so.

> **`data_array` is strings.** The Statement Execution API returns rows as arrays
> of strings, so `app.py` casts them with `.astype(float)` before plotting. For
> large results use `disposition=EXTERNAL_LINKS`; for long/cold-start queries the
> synchronous `wait_timeout` caps at 50s, after which you poll `get_statement`.

### Want the bundle to CREATE a new warehouse instead?

The default references an existing warehouse because Free Edition caps the account
at one. On a workspace where you're allowed to create warehouses (i.e. **not** Free
Edition), you can have the bundle create and manage its own. Three edits:

1. Add `bundle/resources/warehouse.yml`:
   ```yaml
   resources:
     sql_warehouses:
       demo_warehouse:
         name: sample-dash-warehouse-${var.env}
         warehouse_type: PRO
         enable_serverless_compute: true
         cluster_size: "2X-Small"
         auto_stop_mins: 10
         max_num_clusters: 1
   ```
2. Add it to the `include:` list in `bundle/databricks.yml`:
   ```yaml
   include:
     - resources/warehouse.yml   # add this line
   ```
3. In `bundle/resources/app.yml`, point BOTH warehouse references at the created
   warehouse instead of the variable — the binding id and the `WAREHOUSE_ID` env:
   ```yaml
   # was: id: ${var.warehouse_id}          (binding, under resources:)
   # was: value: ${var.warehouse_id}       (WAREHOUSE_ID, under config.env)
   #  ->  ${resources.sql_warehouses.demo_warehouse.id}   (in both places)
   ```

Then deploy **without** `--var="warehouse_id=..."` (the bundle now supplies the id;
the `warehouse_id` variable becomes unused and can be deleted from
`config/variables.yml`). Everything else — the `CAN_USE` binding, the app query,
the caption — is unchanged. `databricks bundle destroy` will now also delete the
warehouse, since the bundle owns it.

> This is exactly how the field-engineering source copy of this bundle is wired;
> the workshop copy just swaps the created warehouse for a referenced one.

## Scheduled start/stop jobs

[`resources/job.yml`](./bundle/resources/job.yml) defines two jobs that share one
notebook ([`src/jobs/app_lifecycle.py`](./bundle/src/jobs/app_lifecycle.py)) to
turn the app off out of hours:

| Job         | Schedule (cron)      | Action        |
|-------------|----------------------|---------------|
| `app_start` | `0 0 8 * * ?` (08:00)  | start the app |
| `app_stop`  | `0 0 18 * * ?` (18:00) | stop the app  |

Both run on **serverless** (no cluster block). Run either by hand:

```bash
databricks bundle run app_start -t dev -p $profile   # or app_stop
```

Design notes:

- **Two jobs, not one.** A job has a single schedule, so an 08:00 start cron and
  an 18:00 stop cron must be separate jobs. Each fixes its `action` via a
  parameter *default*, so a scheduled run (which passes no params) does the right
  thing and manual runs need no `--params`.
- **Timezone** is `var.schedule_timezone` (`config/variables.yml`), default
  `America/New_York`. Change it to your business hours' zone.
- **Per-target pause is automatic.** `pause_status` is deliberately *omitted*:
  development mode auto-pauses schedules, so **dev never fires on the clock**
  (test by hand), while **prod runs UNPAUSED** at 08:00 / 18:00.

### Why `start` = redeploy, not just `apps.start`

Databricks Apps apply env vars (`config.env`) at **deploy** time. A bare
`apps.start` resumes compute but **drops the env vars**, and the API **masks env
values on read** so they can't be recovered from the running app. So the notebook
brings the app up *configured* by redeploying with the env values, which the
bundle passes in via `env_json` - wired from the same variables `config.env`
uses, so the values stay single-sourced in `config/targets.yml`. The notebook
also handles the Apps state machine and `%pip install`s a newer `databricks-sdk`
than serverless ships (for `apps.EnvVar`).

## Free Edition notes

This bundle runs on Databricks Free Edition (each attendee in their own free
workspace), with two edition-specific things to know:

- **One shared warehouse, not one per deploy.** Free Edition allows a single SQL
  warehouse per account - the pre-provisioned "Serverless Starter Warehouse". The
  bundle therefore *references* it via `${var.warehouse_id}` (the Quickstart
  one-liner reads its id) instead of creating one. The app SP is granted
  `CAN_USE` on it. First query after idle incurs a ~5s serverless cold start.
- **Apps auto-stop after 24 hours idle.** If you deploy the night before, the app
  may be stopped when you sit down - just run
  `databricks bundle run sample_dash_asset_bundle -t dev -p $profile` (or
  `databricks apps start <your-app-name>`) to bring it back. When an app restarts
  it gets fresh service-principal credentials; nothing you need to manage.
- **Fair-use compute quota.** A runaway job can exhaust the day's quota. The demo
  jobs are tiny, so this only matters if something loops.

Other Free Edition limits (3 apps/account, 5 concurrent job tasks) are well above
what this one bundle uses.

## Teardown

```bash
databricks bundle destroy -t dev  -p $profile
databricks bundle destroy -t prod -p $profile
```

`destroy` removes the app and jobs this bundle created. It does **not** touch the
SQL warehouse - the bundle only references that warehouse, it does not own it.
