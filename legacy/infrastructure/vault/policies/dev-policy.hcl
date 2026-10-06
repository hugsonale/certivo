# Development Environment Policy
# Read/write access to dev secrets only

# Development secrets path
path "secret/data/development/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# Development KV metadata
path "secret/metadata/development/*" {
  capabilities = ["list", "read", "delete"]
}

# Deny access to other environments
path "secret/data/staging/*" {
  capabilities = ["deny"]
}

path "secret/data/production/*" {
  capabilities = ["deny"]
}

# Allow token renewal
path "auth/token/renew-self" {
  capabilities = ["update"]
}

# Allow token lookup
path "auth/token/lookup-self" {
  capabilities = ["read"]
}