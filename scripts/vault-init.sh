#!/bin/sh
# Initialize Vault (run once after first start)
# Saves root token and unseal keys to vault/init-keys.json
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(dirname "$SCRIPT_DIR")"
KEYS_FILE="${INFRA_DIR}/vault/init-keys.json"

export VAULT_ADDR="http://127.0.0.1:8200"

# Check if already initialized
if vault status 2>/dev/null | grep -q "Initialized.*true"; then
    echo "Vault already initialized"
    exit 0
fi

echo "Initializing Vault..."
vault operator init -key-shares=1 -key-threshold=1 -format=json > "$KEYS_FILE"
chmod 600 "$KEYS_FILE"

echo "Unsealing..."
UNSEAL_KEY=$(jq -r '.unseal_keys_b64[0]' "$KEYS_FILE")
vault operator unseal "$UNSEAL_KEY"

echo "Enabling KV secrets engine..."
ROOT_TOKEN=$(jq -r '.root_token' "$KEYS_FILE")
vault login "$ROOT_TOKEN"
vault secrets enable -path=secret kv-v2

echo ""
echo "=== Vault initialized ==="
echo "Keys saved to: $KEYS_FILE"
echo "Root token: $ROOT_TOKEN"
echo ""
echo "IMPORTANT: Back up $KEYS_FILE securely and delete from disk!"
