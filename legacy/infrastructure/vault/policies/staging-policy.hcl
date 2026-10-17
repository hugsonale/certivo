# Staging Environment Policy
# Read-only access to staging secrets

# Staging secrets path (read-only)
path "secret/data/staging/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/staging/*" {
  capabilities = ["list", "read"]
}

# Deny write access to staging
path "secret/data/staging/*" {
  capabilities = ["create", "update", "delete"]
  denied_capabilities = ["create", "update", "delete"]
}

# Deny access to other environments
path "secret/data/development/*" {
  capabilities = ["deny"]
}

path "secret/data/production/*" {
  capabilities = ["deny"]
}