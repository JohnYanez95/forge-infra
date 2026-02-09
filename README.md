# Forge Infrastructure

Personal data platform for Delta Lake projects. One storage substrate, multiple control planes.

## Services

| Service | Version | Port | Purpose |
|---------|---------|------|---------|
| PostgreSQL | 16.4-alpine | 5432 (internal) | Shared metadata store |
| Unity Catalog | v0.3.1 | 8080 | Catalog governance |
| HashiCorp Vault | 1.15 | 8200 | Secrets management |
| MinIO | RELEASE.2024-01-16 | 9000 / 9001 | S3-compatible object storage |
| Hive Metastore | 3.1.3 | 9083 | Table resolution for Spark |
| MLflow | v2.10.0 | 5002 | Model registry + experiment tracking |
| Marquez | 0.41.0 | 5000 / 5001 | OpenLineage backend (lineage) |
| Marquez Web | 0.41.0 | 3000 | Lineage UI |

All ports bind to `127.0.0.1` by default. Access from a workstation via SSH tunnel.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Lakehouse Infrastructure                  │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │    Vault    │  │   Catalog   │  │       Armory        │  │
│  │   Secrets   │  │ (UC + HMS)  │  │  (MLflow Registry)  │  │
│  │    :8200    │  │    :8080    │  │       :5002         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│         │                │                    │              │
│         └────────────────┼────────────────────┘              │
│                          ▼                                   │
│              ┌───────────────────────┐  ┌────────────────┐  │
│              │   MinIO (S3-compat)   │  │    Marquez     │  │
│              │   s3a://forge/lake/   │  │  (OpenLineage) │  │
│              │  bronze/silver/gold   │  │   :5000/:5001  │  │
│              │   :9000 (API)        │  │   Web UI :3000 │  │
│              │   :9001 (Console)    │  └────────────────┘  │
│              └───────────────────────┘                      │
│                          │                                   │
│              ┌───────────────────────┐                      │
│              │     PostgreSQL        │ ← metadata store     │
│              │ (UC,HMS,MLflow,Marq.) │   (internal)         │
│              └───────────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
    ┌─────────┐      ┌─────────┐      ┌─────────┐
    │ koe-tts │      │ Project │      │ Project │
    │ (Spark) │      │    B    │      │    C    │
    │         │      │(DuckDB) │      │ (both)  │
    └─────────┘      └─────────┘      └─────────┘
```

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/JohnYanez95/forge-infra.git
cd forge-infra
cp .env.example .env
cp etc/conf/hibernate.properties.example etc/conf/hibernate.properties
# Edit both files: set UC_DB_PASSWORD, MINIO_ROOT_PASSWORD, LAKE_PATH

# 2. Download dependencies
mkdir -p hive/lib
curl -fSL -o hive/lib/postgresql-42.7.3.jar \
  "https://jdbc.postgresql.org/download/postgresql-42.7.3.jar"

# 3. Start services
docker compose up -d --build

# 4. Create databases (first time only)
docker exec -it uc-postgres psql -U uc_admin -c "CREATE DATABASE metastore_v3;"
docker exec -it uc-postgres psql -U uc_admin -c "CREATE DATABASE mlflow;"
docker exec -it uc-postgres psql -U uc_admin -c "CREATE DATABASE marquez;"

# 5. Initialize Vault
chmod +x scripts/vault-init.sh
./scripts/vault-init.sh
# IMPORTANT: Back up vault/init-keys.json securely, then delete from disk

# 6. Create MinIO bucket
mc alias set forge http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD
mc mb forge/forge

# 7. Verify
curl http://localhost:8080/api/2.1/unity-catalog/catalogs   # UC
curl http://localhost:9000/minio/health/live                 # MinIO
curl http://localhost:5000/api/v1/namespaces                 # Marquez
curl http://localhost:5002/health                            # MLflow
```

## Client Configuration

Projects connect via environment variables. Use `koe bootstrap` to set them all at once:

```bash
eval "$(koe bootstrap)"
```

Or set manually:

| Variable | Value | Used By |
|----------|-------|---------|
| `VAULT_ADDR` | `http://localhost:8200` | Vault client |
| `METASTORE_URI` | `thrift://localhost:9083` | Spark |
| `MINIO_ENDPOINT` | `http://localhost:9000` | Spark, DuckDB |
| `MINIO_ROOT_USER` | (from Vault) | All clients |
| `MINIO_ROOT_PASSWORD` | (from Vault) | All clients |
| `FORGE_LAKE_ROOT_S3A` | `s3a://forge/lake` | Spark (hadoop-aws) |
| `FORGE_LAKE_ROOT_S3` | `s3://forge/lake` | DuckDB (httpfs) |
| `MLFLOW_TRACKING_URI` | `http://localhost:5002` | MLflow client |
| `OPENLINEAGE_URL` | `http://localhost:5000` | Spark lineage listener |

## MinIO

S3-compatible object storage for Delta tables and MLflow artifacts.

**MinIO data MUST be on local disks, NOT NFS-mounted storage.** MinIO-on-NFS has locking issues.

### Bucket Structure

```
s3://forge/
├── lake/
│   ├── bronze/
│   ├── silver/
│   └── gold/
└── mlflow/
    └── artifacts/
```

### Usage

```bash
mc alias set forge http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD
mc ls forge/forge/lake/gold/koe/
```

## Hive Metastore

Table name to S3 location resolution for Spark.

### Schema Naming

Medallion prefix: `{layer}_{dataset}` (e.g. `gold_koe`, `silver_koe`).

### Registering Tables

```python
spark.sql("CREATE DATABASE IF NOT EXISTS gold_koe")
spark.sql("""
    CREATE TABLE IF NOT EXISTS gold_koe.utterances
    USING DELTA
    LOCATION 's3a://forge/lake/gold/koe/utterances'
""")
spark.table("gold_koe.utterances").show()
```

## Vault

Centralized secrets for all projects.

### Storing Secrets

```bash
vault kv put secret/koe-tts/minio user=minio password=<secure-password>
```

### Retrieving Secrets

```bash
# CLI
vault kv get -field=password secret/koe-tts/minio

# Python (via forge module — no subprocess needed)
from modules.forge.secrets.vault import VaultClient
vault = VaultClient.from_env()
pw = vault.get_field("secret/koe-tts/minio", "password")
```

## MLflow

Model registry and experiment tracking at `http://localhost:5002`.

- PostgreSQL backend for metadata
- Artifact storage at `s3://forge/mlflow/` via MinIO

## Marquez (OpenLineage)

Runtime data lineage. Spark jobs emit lineage events via the OpenLineage listener.

- API: `http://localhost:5000`
- Web UI: `http://localhost:3000`
- Admin: `http://localhost:5001`

Config at `marquez/marquez.yml`. Shares the Postgres instance (database: `marquez`).

## SSH Tunnel Access

For workstation access to services running on a NAS:

```ssh-config
# ~/.ssh/config
Host forge-nas
    HostName <YOUR_NAS_IP>
    User <YOUR_NAS_USER>
    LocalForward 8080 127.0.0.1:8080   # Unity Catalog
    LocalForward 8200 127.0.0.1:8200   # Vault
    LocalForward 9000 127.0.0.1:9000   # MinIO API
    LocalForward 9001 127.0.0.1:9001   # MinIO Console
    LocalForward 9083 127.0.0.1:9083   # Hive Metastore
    LocalForward 5000 127.0.0.1:5000   # Marquez API
    LocalForward 5001 127.0.0.1:5001   # Marquez Admin
    LocalForward 5002 127.0.0.1:5002   # MLflow
    LocalForward 3000 127.0.0.1:3000   # Marquez Web UI
```

## Security

### Default: Localhost Only

All services bind to `127.0.0.1`. No service is exposed to the network by default.

### Enabling Network Access

1. **Enable Unity Catalog authentication first:**
   ```properties
   # etc/conf/server.properties
   server.authorization=enable
   ```

2. **Change config mount to writable** (for token.txt):
   ```yaml
   - ./etc/conf:/opt/unitycatalog/etc/conf:rw
   ```

3. **Restart and get token:**
   ```bash
   docker compose restart unity-catalog
   cat etc/conf/token.txt
   ```

4. **Now safe to bind to network:**
   ```yaml
   ports:
     - "<YOUR_LAN_IP>:8080:8080"
   ```

## Backup & Recovery

### Automated Backups

`scripts/backup.sh` dumps all four databases (unity_catalog, metastore_v3, mlflow, marquez).

```bash
chmod +x scripts/backup.sh

# Add to crontab (daily at 2am)
0 2 * * * /path/to/forge-infra/scripts/backup.sh
```

### Recovery

```bash
gunzip -c backups/uc_YYYYMMDD_HHMMSS.sql.gz | \
  docker exec -i -e PGPASSWORD="$UC_DB_PASSWORD" uc-postgres \
  psql -U uc_admin unity_catalog
```

Same pattern for `metastore_v3_*.sql.gz`, `mlflow_*.sql.gz`, and `marquez_*.sql.gz`.

## Troubleshooting

### Common Pitfalls (NAS Deployment)

- **Docker socket permission denied:** Add your user to the `docker` group (`sudo usermod -aG docker $USER`) and re-login.
- **Vault restart loop:** The Vault config mount must not be `:ro` — the container needs to chown the directory before reading it.
- **MinIO healthcheck fails:** The MinIO container doesn't ship `curl`. Use `mc ready local` instead.
- **MLflow `No module named 'psycopg2'`:** The base MLflow image lacks a Postgres driver. Use the custom `mlflow/Dockerfile` which adds `psycopg2-binary`.
- **Hive Metastore `ClassNotFoundException: org.postgresql.Driver`:** The Hive image doesn't include the PostgreSQL JDBC driver. Download it into `hive/lib/` (see Quick Start step 2).
- **Hive Metastore `ClassNotFoundException: IOStatisticsSource`:** You mounted `hadoop-aws:3.3.4+` into HMS 3.1.3 which bundles Hadoop 3.1.0. The `IOStatisticsSource` interface only exists in Hadoop 3.3+. Use the image's built-in jars (baked in via `hive-metastore/Dockerfile`).
- **`CREATE DATABASE` fails with `database "uc_admin" does not exist`:** Specify the target database explicitly: `psql -U uc_admin -d unity_catalog -c "CREATE DATABASE ..."`.

### UC using embedded H2 instead of Postgres

**Symptom:** Tables disappear after container restart.

**Fix:** Ensure `hibernate.properties` is mounted at `/opt/unitycatalog/etc/conf/`.

```bash
docker logs unity-catalog | grep -i "datasource\|h2\|postgres"
```

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Service definitions (8 containers) |
| `.env.example` | Environment variables template |
| `marquez/marquez.yml` | Marquez server configuration |
| `vault/config/vault.hcl` | Vault server configuration |
| `mlflow/Dockerfile` | Custom MLflow image (adds psycopg2, boto3) |
| `hive-metastore/Dockerfile` | Custom HMS 3.1.3 image (idempotent schema init, S3A jars) |
| `hive-metastore/entrypoint.sh` | Idempotent entrypoint (survives NAS reboots) |
| `hive/lib/postgresql-42.7.3.jar` | PostgreSQL JDBC driver for Hive (gitignored, download at setup) |
| `etc/conf/` | Unity Catalog configuration |
| `scripts/backup.sh` | Database backup script (UC + HMS + MLflow + Marquez) |
| `scripts/vault-init.sh` | Vault initialization script |
| `tests/spark_smoke_test.py` | PySpark smoke test (DDL, DML, S3A I/O) |

## Projects Using This Infrastructure

- [koe-tts](https://github.com/JohnYanez95/koe-tts) - Japanese TTS training pipeline

## License

Apache License 2.0
