variable "profile" {
  type        = string
  description = "Databricks CLI profile Terraform authenticates with."
}

variable "catalog_prefix" {
  type        = string
  description = <<-EOT
    Prefix for the per-environment catalog names. The catalog for each entry in
    var.environments is "<catalog_prefix>_<env>" (e.g. enablement_sfab_dev).
    Fixed, deterministic names (no random suffix) so the bundle can reference the
    secret by a known name in each target.
  EOT
  default     = "enablement_sfab"
}

variable "environments" {
  type        = list(string)
  description = "Environments to create a catalog + secret for. Must match the bundle targets."
  default     = ["dev", "prod"]
}

variable "schema" {
  type        = string
  description = "Schema (created in each catalog) that holds the secret."
  default     = "secrets"
}

variable "secret_name" {
  type        = string
  description = "Name of the Unity Catalog secret to create in each catalog."
  default     = "external_api_key"
}

variable "secret_value" {
  type        = string
  description = "The secret value. Supply via TF_VAR_secret_value or a .tfvars file, not in source."
  sensitive   = true
  default     = "sk-live-demo-do-not-use-in-prod"
}

variable "secret_readers" {
  type        = list(string)
  description = <<-EOT
    Principals granted USE CATALOG + USE SCHEMA + READ SECRET in EVERY environment,
    so they can read the secret value. Put the app's runtime service principal
    application id here (get it after the first `databricks bundle deploy` via
    `databricks apps get <name>`), or a group the app service principal belongs to.
  EOT
  default     = []
}
