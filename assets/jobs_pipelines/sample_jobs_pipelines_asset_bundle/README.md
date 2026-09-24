# Jobs + Pipelines in one Asset Bundle

A single Databricks Asset Bundle that deploys **both jobs and Lakeflow
Declarative Pipelines**, and shows the three ways they relate:

1. **A standalone job** — two `spark_python` tasks (`ingest` → `transform`) on
   serverless compute. No pipeline involved.
2. **Standalone pipelines** — one SQL, one Python, each self-contained (it
   generates its own sample rows and aggregates them).
3. **An orchestrated job** — a job whose middle task is a **`pipeline_task`**
   that triggers a pipeline, with a `spark_python` ingest before it and a
   summarize after it. This is the canonical Lakeflow pattern: a job produces
   the input, hands off to a pipeline, then consumes the pipeline's output.

One `databricks bundle deploy` provisions the **Unity Catalog catalog**, every
schema, both jobs, and all three pipelines.

> **Not a Free Edition asset.** This copy has the bundle *create* the catalog,
> which needs the `direct` engine and does **not** work on Free Edition (Default
> Storage blocks catalog creation via the API). It is meant for a workspace where
> you can create catalogs — e.g. an Azure/AWS field-eng or terraform-provisioned
> workspace. To run it on Free Edition, see
> [Run on Free Edition](#run-on-free-edition-reference-an-existing-catalog).

## What gets deployed (5 objects, 3 concepts)

The three concepts above surface as **five** objects in the workspace, because
the orchestration concept needs two: a job *plus* the pipeline it drives.

| Name in the workspace | Type | Concept |
|---|---|---|
| `sample-standalone-job` | **Job** (2 tasks: `ingest` → `transform`) | ① Standalone job |
| `sql-customer-pipeline-dev` | **Pipeline** | ② Standalone pipelines (SQL) |
| `python-customer-pipeline-dev` | **Pipeline** | ② Standalone pipelines (Python) |
| `sample-orchestrated-job` | **Job** (3 tasks: `ingest_orders` → **`run_pipeline`** → `summarize`) | ③ Job orchestrating a pipeline |
| `orchestrated-customer-pipeline-dev` | **Pipeline** | ③ — the pipeline that `sample-orchestrated-job` drives |

(In `dev` mode each name is prefixed `[dev <you>]`.)

**Why ③ is two objects, not one.** A job's `pipeline_task` does not *contain* a
pipeline — it *references* an existing pipeline by id and triggers a run of it.
So the pipeline has to exist as its own object (`orchestrated-customer-pipeline-dev`);
the job (`sample-orchestrated-job`) is the orchestrator that launches it as its
middle task. That is why running the orchestrated job shows only the two Python
tasks' output — the `run_pipeline` task launches the pipeline update rather than
printing anything itself.

**How `orchestrated-customer-pipeline-dev` differs from the two standalone
pipelines.** The standalone SQL/Python pipelines are **self-contained** — each
generates its own `raw_orders` sample data, so you can run them directly. The
orchestrated pipeline is **not** — it reads an `orders_raw` table that the job's
`ingest_orders` task writes first. Run it on its own before the job's ingest task
and it would have no input; it is designed to be driven by the job.

## Quickstart

Needs the [Databricks CLI](https://docs.databricks.com/en/dev-tools/cli/index.html)
authenticated to a workspace via a profile. All bundle commands run from the
`bundle/` directory.

```bash
# 0. Enter the bundle
cd databricks_enablement/assets/jobs_pipelines/sample_jobs_pipelines_asset_bundle/bundle

# 1. Point at your workspace profile (from ~/.databrickscfg)
profile=<DATABRICKS_PROFILE>

# 2. The catalog resource needs the direct deployment engine (see note below)
export DATABRICKS_BUNDLE_ENGINE=direct

# 3. Check the config resolves, then deploy the catalog + schemas + jobs + pipelines
databricks bundle validate -t dev -p $profile
databricks bundle deploy   -t dev -p $profile

# 4. Run each resource
databricks bundle run standalone_job           -t dev -p $profile
databricks bundle run sql_customer_pipeline    -t dev -p $profile
databricks bundle run python_customer_pipeline -t dev -p $profile
databricks bundle run orchestrated_job         -t dev -p $profile   # ingest -> pipeline -> summarize
```

The `dev` target is per-user safe: several people can deploy into the same
workspace without colliding (development mode prefixes names and schemas with
`[dev <you>]` / `dev_<you>_`; catalog names are shared and not prefixed).

## Layout

```
sample_jobs_pipelines_asset_bundle/
└── bundle/                                # everything - one `databricks bundle deploy`
    ├── databricks.yml                     # variables, the catalog + 4 schemas, dev/prod targets
    ├── resources/
    │   ├── standalone_job.yml             # (1) ingest -> transform job
    │   ├── sql_pipeline.yml               # (2) standalone SQL pipeline
    │   ├── python_pipeline.yml            # (2) standalone Python pipeline
    │   ├── orchestrated_pipeline.yml      # (3) the pipeline the orchestrated job drives
    │   └── orchestrated_job.yml           # (3) ingest -> pipeline_task -> summarize
    └── src/
        ├── job/
        │   ├── ingest.py                  # standalone job task 1
        │   └── transform.py               # standalone job task 2
        ├── pipelines/
        │   ├── sql/transformations.sql
        │   └── python/transformations.py
        └── orchestrated/
            ├── ingest_orders.py           # writes orders_raw (the pipeline's input)
            ├── pipeline.py                # reads orders_raw -> customer_summary
            └── summarize.py               # reads customer_summary -> customer_final
```

## The bundle creates the catalog and every schema

DABs supports `catalogs` and `schemas` as first-class resources, so one deploy
provisions the Unity Catalog objects **and** the jobs/pipelines — no Terraform.
Each pipeline publishes into its **own schema**, because a Delta table can only
be owned by one pipeline; separate schemas keep the pipelines' tables from
colliding.

```yaml
resources:
  catalogs:
    demo_catalog:
      name: ${var.catalog}                                     # e.g. sample_jobs_pipelines_demo
  schemas:
    job_schema:          { catalog_name: ${resources.catalogs.demo_catalog.name}, name: ${var.schema}_job }
    sql_schema:          { catalog_name: ${resources.catalogs.demo_catalog.name}, name: ${var.schema}_sql }
    python_schema:       { catalog_name: ${resources.catalogs.demo_catalog.name}, name: ${var.schema}_python }
    orchestrated_schema: { catalog_name: ${resources.catalogs.demo_catalog.name}, name: ${var.schema}_orchestrated }
```

> **Catalog resources need the `direct` deployment engine** (a preview). The
> default Terraform-based bundle engine rejects `resources.catalogs` with
> *"Catalog resources are only supported with direct deployment mode"*. Set the
> engine for every `bundle` command:
>
> ```bash
> export DATABRICKS_BUNDLE_ENGINE=direct
> ```
>
> Schemas, jobs, and pipelines all work on the direct engine too. See
> <https://docs.databricks.com/dev-tools/bundles/direct>.

## (3) How a job orchestrates a pipeline

The interesting resource is the orchestrated job. Its middle task is a
`pipeline_task` that points at the pipeline defined in the same bundle, by its
resource id — the bundle wires the two together:

```yaml
tasks:
  - task_key: ingest_orders          # spark_python: writes orders_raw
    spark_python_task: { python_file: ../src/orchestrated/ingest_orders.py, ... }
  - task_key: run_pipeline           # pipeline_task: refreshes the pipeline
    depends_on: [{ task_key: ingest_orders }]
    pipeline_task:
      pipeline_id: ${resources.pipelines.orchestrated_pipeline.id}
  - task_key: summarize              # spark_python: reads customer_summary
    depends_on: [{ task_key: run_pipeline }]
    spark_python_task: { python_file: ../src/orchestrated/summarize.py, ... }
```

Unlike the standalone pipelines, `orchestrated_pipeline` is **not**
self-contained — it reads the `orders_raw` table the job's `ingest_orders` task
wrote. It learns which catalog/schema to read from through the pipeline's
`configuration`, read in the source with `spark.conf.get(...)` — the pipeline
equivalent of a job task's `parameters`:

```yaml
orchestrated_pipeline:
  configuration:
    source_catalog: ${resources.catalogs.demo_catalog.name}
    source_schema:  ${resources.schemas.orchestrated_schema.name}
```

## Variable and resource references

Task parameters and pipeline fields mix two kinds of reference:

- **`${var.row_count}`** — a plain **variable** passthrough; the value is exactly
  what the active target set (`100` in dev, `100000` in prod).
- **`${resources.schemas.job_schema.name}`** — a **resource** reference, so the
  job/pipeline uses the exact schema the bundle created. In `mode: development`
  the bundle prefixes schema names (`dev_<you>_demo_job`); referencing the
  resource — not `${var.schema}` — makes everything land in that same prefixed
  schema, so dev and prod stay consistent end to end. (Catalog names are not
  prefixed, so both targets share the one catalog but land in different schemas.)

Every referenced variable must be **declared** in the top-level `variables:`
block; a variable given a value only under a target is treated as "not defined"
and its `${var.x}` stays a literal string.

## Output tables (dev)

In `mode: development` every schema is prefixed `dev_<you>_`:

| Resource | Table | Rows |
|---|---|---|
| standalone_job | `..._job.sample_events_raw` | `row_count` (100 in dev) |
| standalone_job | `..._job.sample_events_by_user` | one per user_id (5) |
| sql / python pipeline | `..._sql` / `..._python`.`customer_summary` | one per customer (3) |
| orchestrated_job | `..._orchestrated.orders_raw` | 6 (written by ingest task) |
| orchestrated_job | `..._orchestrated.customer_summary` | 3 (written by pipeline) |
| orchestrated_job | `..._orchestrated.customer_final` | 3 (ranked by spend) |

Both pipelines' `customer_summary` return the same six-order rollup:

| customer_id | total_amount | order_count |
|---|---|---|
| 101 | 375.50 | 2 |
| 102 | 560.00 | 2 |
| 103 | 386.00 | 2 |

## dev vs prod targets

| | `dev` (default) | `prod` |
|---|---|---|
| `mode` | `development` | `production` |
| Names | prefixed `[dev <you>] …` | as-is |
| Schemas | prefixed `dev_<you>_demo_*` | `prod_*` |
| Catalog | shared `sample_jobs_pipelines_demo` | shared `sample_jobs_pipelines_demo` |
| Deployed under | your user (`~/.dabs/…`) | the deploying principal |
| `row_count` | `100` | `100000` |

The `prod` target pins `host` and a `/.dabs` `root_path` — set the host before
deploying prod. `prod` runs in production mode (namespaces nothing), so use `dev`
for the clone-and-run workflow.

## Run on Free Edition (reference an existing catalog)

Free Edition accounts use UC **Default Storage**, and Default Storage catalogs
can only be created through the workspace **UI** — the create API (which
`databricks bundle deploy` and `databricks catalogs create` both use) rejects
them with *"Metastore storage root URL does not exist"*. So on Free Edition the
bundle cannot create the catalog. To run there, reference an existing catalog
(`workspace`, which every Free Edition workspace ships) and create only the
schemas. Two edits, and you can drop the `direct` engine entirely:

1. In `databricks.yml`, remove the `catalogs:` block and point the schemas'
   `catalog_name` at the variable instead of the resource:
   ```yaml
   variables:
     catalog: { default: workspace }        # an EXISTING catalog
   resources:
     schemas:
       job_schema: { catalog_name: ${var.catalog}, name: ${var.schema}_job }
       # ... same for sql_schema / python_schema / orchestrated_schema
   ```
2. Switch the pipeline `catalog:` fields, the `source_catalog` config, and the
   job task `--catalog=` parameters from `${resources.catalogs.demo_catalog.name}`
   to `${var.catalog}`.

Then deploy with the default engine (no `DATABRICKS_BUNDLE_ENGINE=direct`).
Everything else — schemas, jobs, pipelines, the orchestration — is unchanged.
(This is the exact reverse of the catalog-creating setup, and it was verified on
Free Edition on 2026-09-24.)

## Teardown

```bash
cd bundle
export DATABRICKS_BUNDLE_ENGINE=direct
databricks bundle destroy -t dev -p $profile
```

`destroy` removes the catalog, all four schemas, both jobs, and all three
pipelines. The standalone job's output tables are not bundle-owned, so if
`destroy` reports a schema is not empty, drop them first with
`databricks tables delete <fqn>`.

## Verified

Deployed and run end to end on the **Azure terraform workspace**
(`terraform_azure_workspace_classic_custom_vnet`) on 2026-09-24 with
`DATABRICKS_BUNDLE_ENGINE=direct` (serverless): the bundle created the catalog
`sample_jobs_pipelines_demo` and all four schemas (dev-prefixed to
`dev_jerome_lieow_demo_*`); the standalone job wrote 100 raw / 5 summary rows;
both standalone pipelines produced the 375.50 / 560.00 / 386.00 rollup; and the
orchestrated job ran `ingest_orders` (6 rows) → `run_pipeline` (`customer_summary`,
3 rows) → `summarize` (`customer_final`, ranked by spend: 102, 103, 101). The
Free-Edition (referenced-catalog) variant above was also verified on Free Edition
the same day.
