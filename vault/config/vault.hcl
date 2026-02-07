# HashiCorp Vault Configuration
# Single-node file storage for NAS deployment

# Disable memory locking (container handles this via IPC_LOCK cap)
disable_mlock = true

# Storage backend - file for single-node simplicity
storage "file" {
  path = "/vault/data"
}

# Listener configuration
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true  # TLS disabled - localhost only or reverse proxy
}

# API address for client redirects
api_addr = "http://127.0.0.1:8200"

# UI enabled for convenience
ui = true

# Logging
log_level = "info"
log_file  = "/vault/logs/vault.log"
