#!/bin/sh
# Forge Infrastructure PostgreSQL Backup Script
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

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# Dump and compress each database
echo "Backing up Unity Catalog database..."
docker exec -e PGPASSWORD="$UC_DB_PASSWORD" uc-postgres \
    pg_dump -U uc_admin unity_catalog \
    | gzip > "${BACKUP_DIR}/uc_${TIMESTAMP}.sql.gz"

echo "Backing up MLflow database..."
docker exec -e PGPASSWORD="$UC_DB_PASSWORD" uc-postgres \
    pg_dump -U uc_admin mlflow \
    | gzip > "${BACKUP_DIR}/mlflow_${TIMESTAMP}.sql.gz"

echo "Backing up Marquez database..."
docker exec -e PGPASSWORD="$UC_DB_PASSWORD" uc-postgres \
    pg_dump -U uc_admin marquez \
    | gzip > "${BACKUP_DIR}/marquez_${TIMESTAMP}.sql.gz"

echo "Backing up Hive Metastore database (v3)..."
docker exec -e PGPASSWORD="$UC_DB_PASSWORD" uc-postgres \
    pg_dump -U uc_admin metastore_v3 \
    | gzip > "${BACKUP_DIR}/metastore_v3_${TIMESTAMP}.sql.gz"

# Prune old backups
echo "Pruning backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -name "uc_*.sql.gz" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "mlflow_*.sql.gz" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "marquez_*.sql.gz" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "metastore_v3_*.sql.gz" -mtime +$RETENTION_DAYS -delete

echo "Backup complete: ${BACKUP_DIR}"
ls -lh "${BACKUP_DIR}" | tail -10
