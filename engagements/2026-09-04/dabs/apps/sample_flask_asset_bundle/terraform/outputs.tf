# env -> the secret's three-level name. These are non-sensitive pointers; copy
# each into the matching bundle target's var.uc_secret_full_name.
#   dev  -> enablement_sfab_dev.secrets.external_api_key
#   prod -> enablement_sfab_prod.secrets.external_api_key
output "uc_secret_full_names" {
  value       = { for env in var.environments : env => databricks_secret_uc.app_secret[env].full_name }
  description = "Map of environment -> secret catalog.schema.name. Pass to the bundle, NOT the value."
}
