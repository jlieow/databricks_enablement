# Sample Flask Asset Bundle app: the barebones intro DAB app

A minimal Databricks App packaged as a Databricks Asset Bundle. It is the
**dependency-free starting point** for agenda item 5: unlike the sibling
`../sample_flask_lakebase/` app (which needs a Lakebase Autoscaling project and a
populated serving table before it shows anything), this app needs **nothing but
a workspace**. You `databricks bundle deploy`, open the URL, and immediately see
a working Databricks App. Start here to learn the Asset Bundle mechanics, then
move to the Lakebase app for the data-backed pattern.

It proves two things, both of which the full build relies on:

1. **Asset Bundle variables reach the app as environment variables.** The bundle
   declares `${var.env}`, `${var.warehouse_id}`, and so on, and injects them into
   the app's runtime. The page renders each one and flags any that arrived
   unsubstituted, so "did my bundle variable actually land?" becomes visible.
2. **A Unity Catalog secret is read at runtime without ever placing its value in
   the app config.** Only the secret's three-level *name* is passed in; the app
   fetches the *value* at runtime under the `READ SECRET` grant. This is
   optional (see below) and the app degrades gracefully when no secret exists.

The secret piece maps directly to the external-model-key governance story in
agenda item 12: an external large language model API key is exactly the kind of
value you keep in a governed Unity Catalog secret and read at runtime, rather
than baking into config.

## Runs on Free Edition, no dependencies

Everyone can deploy this on their own Free Edition workspace during the session.
The core path (variable passthrough) needs only serverless compute. The Unity
Catalog secret extension needs a catalog and grants, which also work on Free
Edition but are entirely optional.

## Deploy the barebones path (no secret, no Terraform)

```bash
cd dabs/apps/sample_flask_asset_bundle
profile=<DATABRICKS_PROFILE>

databricks bundle validate -p $profile
databricks bundle deploy -t dev -p $profile          # dev is the default target
databricks bundle run sample_flask_asset_bundle -t dev -p $profile
```

Open the app URL. The table shows `APP_ENV = dev`. If bundle substitution had
failed you would instead see `APP_ENV = ${var.env}` with a `NOT SUBSTITUTED`
flag. The Unity Catalog secret section shows a **not configured** message,
because no secret has been wired up yet, and the app renders fine regardless.

Override a variable at deploy time to see the passthrough change:

```bash
databricks bundle deploy -t dev -p $profile --var="env=staging"

# Confirm what the platform actually set (should show the value, not the literal):
databricks apps get sample-flask-asset-bundle-dev -o json | grep -A2 APP_ENV
```

Deploy the prod variant (a separate app name, so both can exist at once):

```bash
databricks bundle deploy -t prod -p $profile
databricks bundle run sample_flask_asset_bundle -t prod -p $profile
```

## How the passthrough works (the three layers)

A variable reaching the app is a three-layer chain. `config.env` never holds the
value directly, it holds a *reference* to a variable, and the target supplies the
variable's *value*:

```
targets.<t>.variables.env   ->   ${var.env}   ->   config.env[APP_ENV].value   ->   app
      (per-target value)         (reference)        (where it lands)
```

1. **Declare** the variable in the top-level `variables:` block (STEP 1 in
   `databricks.yml`). Skip this and `${var.env}` renders as a literal string.
2. **Reference** it in `resources.apps.<name>.config.env` (STEP 2). `${var.x}` is
   substituted here because this block lives in `databricks.yml`.
3. **Value** it per target under `targets.<t>.variables` (STEP 3).

> **Put variable-backed env vars in `databricks.yml`, not in `app.yaml`.**
> Variable substitution runs only on `databricks.yml` (and files it includes).
> The app's own `app.yaml` is uploaded verbatim, so a `value: ${var.env}` written
> there reaches the app as the literal string `${var.env}`. The `app.yaml` here
> carries only the startup command, and an annotated note explaining why.

See `../../../docs/asset_bundles_guide.md` for the conceptual walkthrough.

## Optional: read a Unity Catalog secret at runtime

Sensitive values (an external API key, a model endpoint token) need a different
pattern from `APP_ENV`. This demo uses **Unity Catalog secrets**, a governed
object with a three-level name (`catalog.schema.name`) secured by the
`READ SECRET` privilege. A UC secret cannot be auto-injected as an app env var,
so the pattern is:

1. **Terraform** (in [`./terraform`](./terraform)) creates the UC secret and
   grants `USE CATALOG` + `USE SCHEMA` + `READ SECRET` to the app's principal.
2. **The bundle** passes only the secret's *name* (a non-sensitive pointer) to
   the app as `UC_SECRET_FULL_NAME` via `${var.uc_secret_full_name}`.
3. **The app** reads the *value* at runtime through the Unity Catalog secrets
   API using its own service-principal identity. If the grant is missing, the
   read fails visibly in the UI. That is the governance boundary.

```bash
# --- Phase 1: create the UC secret (from ./terraform) ---
cd terraform
cp terraform.tfvars.example terraform.tfvars    # fill in profile
export TF_VAR_secret_value='sk-live-...'          # keep the value out of source
terraform init
terraform apply
terraform output uc_secret_full_names             # e.g. enablement_sfab_dev.secrets.external_api_key
cd ..

# The bundle's dev/prod targets already point var.uc_secret_full_name at
# enablement_sfab_dev / enablement_sfab_prod, matching these defaults.

# --- Phase 2: (re)deploy the app ---
databricks bundle deploy -t dev -p $profile
```

**The grant chicken-and-egg.** The app's runtime service principal only exists
once the app is created. So the honest sequence is: deploy once, read the app's
SP application id with `databricks apps get sample-flask-asset-bundle-dev -o json`,
add it to `secret_readers` in `terraform.tfvars`, and re-run `terraform apply`.
To keep the strict `terraform` then `bundle` order, instead grant a **group** the
app SP belongs to (put the group name in `secret_readers`).

Once the grant is in place, the secret section shows `READ OK` with a masked
value. Until then, the section is self-describing:

- **not configured** — `UC_SECRET_FULL_NAME` was never set to a real secret name.
- **does not exist** — create a Unity Catalog secret with that `catalog.schema.name`.
- **denied** — grant the app's service principal (the message prints its id)
  `USE CATALOG` on the catalog and `USE SCHEMA` + `READ SECRET` on the schema.

## Teardown

```bash
cd dabs/apps/sample_flask_asset_bundle
databricks bundle destroy -t dev -p $profile
databricks bundle destroy -t prod -p $profile

# Only if you created the optional secret:
cd terraform && terraform destroy
```

## Files

| File                          | Purpose                                                               |
| ----------------------------- | --------------------------------------------------------------------- |
| `databricks.yml`              | Asset Bundle: declares the variables and injects them via `config.env`, dev/prod targets |
| `app.py`                      | Flask app: renders env vars, flags literals, reads the optional UC secret |
| `app.yaml`                    | App startup command; annotated to show why `${var.x}` must NOT live here |
| `requirements.txt`            | `flask`, `databricks-sdk`                                             |
| `terraform/`                  | OPTIONAL. Creates the Unity Catalog secret and its `READ SECRET` grant |
