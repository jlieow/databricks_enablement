terraform {
  required_providers {
    databricks = {
      source = "databricks/databricks"
    }
  }
}

provider "databricks" {
  profile = var.profile
}

# ---------------------------------------------------------------------------
# One Unity Catalog catalog per environment, with a FIXED, deterministic name
# (e.g. enablement_sfab_dev, enablement_sfab_prod) - no random suffix.
# Deterministic names let the bundle reference the secret by a known
# catalog.schema.name in each target (see ../databricks.yml).
#
# A UC secret is a governed object with a three-level name (catalog.schema.name),
# secured by Unity Catalog privileges. databricks_secret_uc is a Private Preview
# resource.
# ---------------------------------------------------------------------------
locals {
  # env -> catalog name, e.g. "dev" => "enablement_sfab_dev"
  catalogs = { for env in var.environments : env => "${var.catalog_prefix}_${env}" }

  # Flatten (env x reader) into one map so grants can be created per pair.
  grant_pairs = merge([
    for env in var.environments : {
      for reader in var.secret_readers :
      "${env}:${reader}" => { env = env, principal = reader }
    }
  ]...)
}

resource "databricks_catalog" "this" {
  for_each      = local.catalogs
  name          = each.value
  comment       = "sample_flask_asset_bundle ${each.key} secrets catalog"
  force_destroy = true # let `terraform destroy` remove it even if non-empty
}

resource "databricks_schema" "secrets" {
  for_each      = local.catalogs
  catalog_name  = databricks_catalog.this[each.key].name
  name          = var.schema
  comment       = "Holds the ${each.key} Unity Catalog secret"
  force_destroy = true
}

resource "databricks_secret_uc" "app_secret" {
  for_each     = local.catalogs
  catalog_name = databricks_schema.secrets[each.key].catalog_name
  schema_name  = databricks_schema.secrets[each.key].name
  name         = var.secret_name
  value        = var.secret_value
  comment      = "Secret read at runtime by the ${each.key} app"
}

# ---------------------------------------------------------------------------
# Grant each reader access in every environment. Reading a secret value needs
# USE CATALOG on the catalog, plus USE SCHEMA and READ SECRET on the schema.
# READ SECRET is the privilege that gates the value itself; listing returns
# metadata only. databricks_grant (singular) adds only these principals'
# privileges and never clobbers other grants.
# ---------------------------------------------------------------------------
resource "databricks_grant" "catalog_use" {
  for_each   = local.grant_pairs
  catalog    = databricks_catalog.this[each.value.env].name
  principal  = each.value.principal
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "schema_read_secret" {
  for_each = local.grant_pairs
  # Reference the schema resource's id (catalog.schema) so Terraform waits for
  # the schema to exist before creating the grant.
  schema     = databricks_schema.secrets[each.value.env].id
  principal  = each.value.principal
  privileges = ["USE_SCHEMA", "READ_SECRET"]
}
