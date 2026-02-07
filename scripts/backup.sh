#!/bin/sh
# Unity Catalog PostgreSQL Backup Script
# Run daily via cron: 0 2 * * * /path/to/backup.sh

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${INFRA_DIR}/backups"
RETENTION_DAYS=14

# Source password from .env
if [ -f "${INFRA_DIR}/.env" ]; then
    . "${INFRA_DIR}/.env"
fi

if [ -z "${UC_DB_PASSWORD:-}" ]; then
    echo "Error: UC_DB_PASSWORD not set"
    exit 1
fi

# Ensure backup dir exists
mkdir -p "$BACKUP_DIR"

# Dump and compress
echo "Backing up Unity Catalog database..."
docker exec -e PGPASSWORD="$UC_DB_PASSWORD" uc-postgres \
    pg_dump -U uc_admin unity_catalog \
    | gzip > "${BACKUP_DIR}/uc_$(date +%Y%m%d_%H%M%S).sql.gz"

# Prune old backups
echo "Pruning backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -name "uc_*.sql.gz" -mtime +$RETENTION_DAYS -delete

echo "Backup complete: ${BACKUP_DIR}"
ls -lh "${BACKUP_DIR}" | tail -5
