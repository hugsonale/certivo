# HashiCorp Vault Configuration
# Separate paths for each environment

# Storage backend
storage "consul" {
  address = "127.0.0.1:8500"
  path    = "vault/"
}

# Listener
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 0
  tls_cert_file = "/etc/vault/tls/vault.crt"
  tls_key_file  = "/etc/vault/tls/vault.key"
}

# API address
api_addr = "https://vault.certivo.com:8200"
cluster_addr = "https://vault.certivo.com:8201"

# UI
ui = true

# Telemetry
telemetry {
  prometheus_retention_time = "30s"
  disable_hostname = true
}