# Asset Bundle variables to job parameters (encounters pipeline)

A minimal Databricks **Job** deployed as an Asset Bundle, and the jobs
counterpart to [`../../apps/sample_flask_lakebase`](../../apps/sample_flask_lakebase).
It is the runnable version of agenda item 5 (Packaging with Databricks Asset
Bundles) and shows how to:

- pass **Asset Bundle variables** (`${var.row_count}`, ...) through to a job's
  **task parameters**, and therefore into the Python code;
- create the **Unity Catalog catalog and schema from the bundle itself**
  (`resources.catalogs` / `resources.schemas`) - no separate Terraform;
- hand the job the **resource's** catalog/schema name so `mode: development`
  name-prefixing flows through consistently;
- switch values per environment with bundle **targets** (`dev` / `prod`);
- chain two tasks with a **dependency** (`transform` runs after `ingest`);
- run on **serverless** compute, so there is no cluster to size or start.

The data is synthetic patient-encounter events for two fictional health
districts, mirroring the enablement scenario without any real or identifying
data.

## Layout

```
sample_encounters_job/
├── databricks.yml     # variables, the catalog + schema, the job, dev/prod targets
├── README.md
└── src/
    ├── ingest.py      # task 1: writes a synthetic encounters Delta table
    └── transform.py   # task 2: aggregates it per district (runs after ingest)
```

## The bundle creates the catalog and schema

DABs supports `catalogs` and `schemas` as first-class resources, so a single
deploy provisions the Unity Catalog objects **and** the job - no Terraform.

> **Catalog resources need the `direct` deployment engine** (a preview). The
> default Terraform-based bundle engine rejects `resources.catalogs` with
> *"Catalog resources are only supported with direct deployment mode"*. Set the
> engine for every `bundle` command that touches the catalog:
>
> ```bash
> export DATABRICKS_BUNDLE_ENGINE=direct
> ```
>
> Schemas, jobs, and the rest work on either engine; only the catalog forces
> `direct`. See <https://docs.databricks.com/dev-tools/bundles/direct>.

## Two kinds of reference in the job

```yaml
parameters:
  - "--catalog=${resources.catalogs.demo_catalog.name}"   # RESOURCE reference
  - "--schema=${resources.schemas.demo_schema.name}"      # RESOURCE reference
  - "--row-count=${var.row_count}"                         # VARIABLE passthrough
```

- **`${var.row_count}`** - a plain variable, exactly what the active target set
  (`500` in dev, `50000` in prod).
- **`${resources.schemas.demo_schema.name}`** - the name of the schema the
  bundle *actually created*, which in `dev` mode is prefixed (e.g.
  `dev_you_encounters`). Handing the job the resource's name (not `${var.schema}`)
  makes the job write to the same prefixed schema the bundle made.

Every variable you reference must be **declared** in the top-level `variables:`
block. A variable only given a value under a target, without that declaration,
is treated as "not defined" and `${var.x}` stays a literal string.

## dev vs prod targets

| | `dev` (default) | `prod` |
|---|---|---|
| `mode` | `development` | `production` |
| Job name | prefixed `[dev <you>] ...` | `sample-encounters-job` |
| Schema name | prefixed `dev_<you>_encounters` | `encounters_prod` |
| Schedule | paused automatically | daily at 06:00 UTC |
| `row_count` | `500` | `50000` |

Catalog names are *not* prefixed, so both targets share the one
`enablement_dabs_demo` catalog but land in different schemas.

## Deploy and run

```bash
cd dabs/jobs/sample_encounters_job
export DATABRICKS_BUNDLE_ENGINE=direct        # required for the catalog resource
profile=<DATABRICKS_PROFILE>

databricks bundle validate -p $profile
databricks bundle deploy -p $profile                       # creates catalog + schema + job
databricks bundle run sample_encounters_job -p $profile

# Production version (daily schedule on, larger row_count, prod schema):
databricks bundle deploy -t prod -p $profile
databricks bundle run sample_encounters_job -t prod -p $profile
```

After a run, check the output tables in Catalog Explorer under the catalog and
schema the bundle created (in dev, `enablement_dabs_demo.dev_<you>_encounters`):

- `encounters_raw` - written by `ingest`
- `encounters_by_district` - written by `transform`

### Tearing it down

The bundle does not own the tables the job wrote, so drop them first, then
destroy:

```bash
cd dabs/jobs/sample_encounters_job
export DATABRICKS_BUNDLE_ENGINE=direct
databricks tables delete enablement_dabs_demo.dev_<you>_encounters.encounters_raw
databricks tables delete enablement_dabs_demo.dev_<you>_encounters.encounters_by_district
databricks bundle destroy -p $profile
```

## Files

| File                    | Purpose                                                                     |
|-------------------------|-----------------------------------------------------------------------------|
| `databricks.yml`        | Variables, the catalog + schema, the two-task job, and the dev/prod targets.|
| `src/ingest.py`         | Task 1: generates `row_count` synthetic encounter rows into a raw Delta table.|
| `src/transform.py`      | Task 2: aggregates the raw table into a per-district summary table.         |
