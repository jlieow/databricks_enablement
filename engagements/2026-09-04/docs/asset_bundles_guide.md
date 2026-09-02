# Packaging with Databricks Asset Bundles

**Audience:** the team building and deploying the solution

Agenda item 5. Databricks Asset Bundles (DABs) are a way to define, package, and deploy Databricks
resources (notebooks, jobs, models, dashboards, Genie spaces, Databricks Apps) as code in a Git
repository, so the entire solution is version-controlled and reproducible.

This is a **walkthrough and reference pattern**, not a required hands-on build. The actual packaging
into DABs happens during the full build, not during this enablement session.

---

## Why Asset Bundles

**The develop-here, deploy-into-client path.** The team develops notebooks and models in their own
Databricks workspace or a staging environment. When ready, they commit to Git. A continuous integration
and continuous delivery (CI/CD) pipeline detects the commit, packages everything into a DAB, and
deploys it into the client's environment with one command.

This means:
- Everything is version-controlled. Rollback is a Git revert.
- The solution runs the same way in dev, staging, and production.
- New districts are onboarded by adding a row to a config table and re-deploying. No code changes.
- The client owns and operates the deployed solution after handover, using the same Git and DAB pattern.

---

## What goes into a DAB

For this health analytics solution, the DAB includes:

1. **Notebooks** — the medallion pipelines (02, 03, 04) that ingest and transform encounters.
2. **Jobs** — scheduled or event-triggered jobs that run the notebooks daily, weekly, or on-demand.
3. **Models** — the trained risk-stratification model registered in Unity Catalog.
4. **Pipelines** — optional Lakeflow pipelines instead of or alongside notebooks.
5. **Dashboards** — the health analytics dashboard.
6. **Genie spaces** — the curated spaces over gold tables.
7. **Databricks Apps** — the internal service that serves risk scores and encounter data.
8. **Configuration** — district list, schedule, owner contact, cost tags, and other metadata.

---

## The databricks.yml file

A DAB is defined in a file called `databricks.yml` (or `databricks.dev.yml` for development).
Here is what the structure looks like:

```yaml
bundle:
  name: health-analytics-poc
  version: 0.1.0

environments:
  dev:
    workspace:
      host: https://your-dev-workspace.cloud.databricks.com
      token: ${var.dev_token}
    variables:
      district_list: ["northmoor_district", "eldervale_district"]
  
  prod:
    workspace:
      host: https://customer-workspace.cloud.databricks.com
      token: ${var.prod_token}
    variables:
      district_list: ["northmoor_district", "eldervale_district", "additional_district"]

resources:
  notebooks:
    ingest_pipeline:
      path: ./notebooks/02_ingest_encounters_autoloader.py
      directory: /Workspace/health_analytics/notebooks

  jobs:
    daily_ingest_and_transform:
      tasks:
        - task_key: ingest
          notebook_task:
            notebook_path: ${resources.notebooks.ingest_pipeline.path}
            base_parameters:
              district_id: northmoor_district
        - task_key: transform
          notebook_task:
            notebook_path: ./notebooks/03_medallion_transform.py
            base_parameters:
              district_id: northmoor_district
          depends_on:
            - task_key: ingest
      schedule:
        quartz_cron_expression: "0 8 * * * ?"  # Daily at 8 AM
        timezone_id: UTC
      tags:
        cost_center: health_analytics
        client: health_authority

  models:
    risk_stratification:
      model_path: "enablement.05_ops.risk_stratification_model"
      model_type: "sklearn"

  dashboards:
    health_analytics:
      path: ./data/district_health.lvdash.json
      directory: /Dashboards/health_analytics

  apps:
    encounter_service:
      path: ./apps/encounter_service/
      config: ./apps/encounter_service/app.yaml
```

---

## Deploying a DAB

Once the `databricks.yml` is in Git:

```bash
# Validate the bundle
databricks bundle validate

# Deploy to dev
databricks bundle deploy --target dev

# Deploy to prod (after review and approval)
databricks bundle deploy --target prod
```

---

## Key takeaways

- **Single source of truth.** Everything is in Git. The bundle definition is code.
- **Reproducible.** Deploy the same bundle into dev, staging, and prod, and it runs the same way.
- **Portable.** Onboarding a new district is a config change, not a code change.
- **Client-friendly.** After handover, the client uses the same Git + DAB + CI/CD workflow to
  operate and extend the solution.

This is the shape the full build will use. Enablement teaches the underlying Databricks capabilities
(medallion, models, dashboards, Genie, serving); the full build wraps them all in a DAB.

---

## Runnable examples in this engagement

Three working Asset Bundles live under `dabs/`, each with its own README, so the team can deploy a real
DAB rather than only read about one. Start with the first: it is the only one with no external dependency.

- `dabs/apps/sample_flask_asset_bundle/` — the barebones intro app. An Asset Bundle whose variables pass
  through to the app's environment variables (with a page that flags any that arrived unsubstituted), plus
  an optional Unity Catalog secret read at runtime without the value touching the app config. No data
  dependency: deploy it against any workspace and it works, which makes it the right first thing to run.
  The optional secret piece maps to the external-model-key governance story in agenda item 12.
- `dabs/jobs/sample_encounters_job/` — a two-task serverless job (ingest then transform) that also
  creates its own Unity Catalog catalog and schema from the bundle. Shows variable passthrough into
  task parameters and dev/prod targets. Needs `export DATABRICKS_BUNDLE_ENGINE=direct` because it
  declares a catalog resource.
- `dabs/apps/sample_flask_lakebase/` — the risk-score Databricks App (agenda item 8) packaged as a
  bundle, attaching a Lakebase Autoscaling database under the app's `postgres` resource. Needs a
  Lakebase Autoscaling project to point at.

Both were deployed and run end to end while preparing this material. Two portability notes from that
run, worth knowing before the full build: a bundle's `config.env` **replaces** an app's `app.yaml`
env block (it does not merge), and the bundle field is `value_from` (snake_case), not `valueFrom`.

