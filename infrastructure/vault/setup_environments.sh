#!/bin/bash
# Setup Vault with environment isolation

set -e

echo "🔐 Setting up HashiCorp Vault with environment isolation"

# Enable KV v2 secrets engine
vault secrets enable -path=secret kv-v2

# Create environment-specific paths
echo "📁 Creating environment paths..."

vault kv put secret/development/database username=certivo_dev password=dev_password
vault kv put secret/staging/database username=certivo_staging password=staging_password
vault kv put secret/production/database username=certivo_prod password=prod_password

# Create policies
echo "📋 Creating environment policies..."

vault policy write development-policy infrastructure/vault/policies/dev-policy.hcl
vault policy write staging-policy infrastructure/vault/policies/staging-policy.hcl
vault policy write production-policy infrastructure/vault/policies/production-policy.hcl

# Create AppRole for each environment
echo "🔑 Creating AppRoles..."

# Development AppRole
vault auth enable approle
vault write auth/approle/role/development \
    secret_id_ttl=24h \
    token_ttl=1h \
    token_max_ttl=4h \
    policies="development-policy"

# Staging AppRole
vault write auth/approle/role/staging \
    secret_id_ttl=24h \
    token_ttl=1h \
    token_max_ttl=4h \
    policies="staging-policy"

# Production AppRole
vault write auth/approle/role/production \
    secret_id_ttl=24h \
    token_ttl=1h \
    token_max_ttl=4h \
    policies="production-policy"

# Get Role IDs
echo ""
echo "✅ Vault setup complete!"
echo ""
echo "Development Role ID:"
vault read auth/approle/role/development/role-id

echo ""
echo "Staging Role ID:"
vault read auth/approle/role/staging/role-id

echo ""
echo "Production Role ID:"
vault read auth/approle/role/production/role-id

echo ""
echo "⚠️  Store these Role IDs securely!"