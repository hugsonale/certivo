# Production Environment Policy
# Strict read-only access, write via automation only

# Production secrets path (read-only for services)
path "secret/data/production/*" {
  capabilities = ["read"]
}

path "secret/metadata/production/*" {
  capabilities = ["read"]
}

# Explicitly deny write operations
path "secret/data/production/*" {
  capabilities = ["create", "update", "delete"]
  denied_capabilities = ["create", "update", "delete"]
}

# Deny access to other environments
path "secret/data/development/*" {
  capabilities = ["deny"]
}

path "secret/data/staging/*" {
  capabilities = ["deny"]
}

# Allow token operations
path "auth/token/renew-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}