# Forge Infrastructure

Personal data platform for Delta Lake projects. One storage substrate, multiple control planes.

## Components

- **MinIO** - S3-compatible object storage for Delta tables
- **Unity Catalog OSS** - Centralized metadata catalog for Delta tables
- **PostgreSQL** - Persistent metadata store
- **HashiCorp Vault** - Secrets management for cross-project env vars
- **Hive Metastore** (planned) - Table resolution for Spark
- **OpenLineage + Marquez** (planned) - Runtime data lineage
- **MLflow** (planned) - Model registry and experiment tracking

## Quick Start

```bash
# 1. Clone
git clone https://github.com/JohnYanez95/forge-infra.git
cd forge-infra

# 2. Configure
cp .env.example .env
cp etc/conf/hibernate.properties.example etc/conf/hibernate.properties
# Edit both files with your password and lake path

# 3. Start services
docker compose up -d

# 4. Verify services
curl http://127.0.0.1:8080/api/2.1/unity-catalog/catalogs  # UC
curl http://127.0.0.1:9000/minio/health/live               # MinIO
# UC should return: {"catalogs": []}

# 5. Set up MinIO bucket
mc alias set forge http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD
mc mb forge/forge  # Create 'forge' bucket
```

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
│              ┌───────────────────────┐                      │
│              │   MinIO (S3-compat)   │ ← canonical writes   │
│              │   s3a://forge/lake/   │   :9000 (API)        │
│              │  bronze/silver/gold   │   :9001 (Console)    │
│              └───────────────────────┘                      │
│                          │                                   │
│              ┌───────────────────────┐                      │
│              │     PostgreSQL        │ ← metadata store     │
│              │   (UC, HMS, MLflow)   │   (internal)         │
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

## Pinned Versions

All components are pinned to stable releases:

| Component | Version | Notes |
|-----------|---------|-------|
| MinIO | RELEASE.2024-01-16 | S3-compatible storage |
| Unity Catalog | v0.3.1 | Pinned in docker-compose.yml |
| PostgreSQL | 16.4-alpine | Metadata store |
| Vault | 1.15 | Secrets management |
| PySpark | 4.0.0 | With Scala 2.13 |
| Delta Spark | 4.0.0 | Match Spark version |
| DuckDB | 1.2.0 | Pin in requirements.txt |
| unitycatalog-client | 0.3.1 | Match UC server |

## Client Configuration

Projects connect to UC using environment variables:

| Variable | Default | Used By |
|----------|---------|---------|
| `UC_SERVER_URL` | `http://localhost:8080` | Spark |
| `UC_API_URL` | `http://localhost:8080/api/2.1/unity-catalog` | Python REST client |
| `UC_TOKEN` | (none) | All clients (when auth enabled) |
| `UC_ENABLED` | `false` | Application toggle |

### Spark (Full UC Integration)

```python
spark = (
    SparkSession.builder
    .config("spark.jars.packages",
            "io.delta:delta-spark_2.13:4.0.0,"
            "io.unitycatalog:unitycatalog-spark_2.13:0.3.1")
    .config("spark.sql.catalog.my_catalog", "io.unitycatalog.spark.UCSingleCatalog")
    .config("spark.sql.catalog.my_catalog.uri", os.getenv("UC_SERVER_URL"))
    .getOrCreate()
)

# Query via catalog
spark.table("my_catalog.schema.table").show()
```

### DuckDB (Direct Delta Access)

DuckDB's UC extension is not yet in stable. Use `delta_scan()` for reliable access:

```python
import duckdb  # Pin to 1.2.0 in requirements.txt

conn = duckdb.connect()
conn.execute("INSTALL delta; LOAD delta;")

# Query Delta tables directly by path
df = conn.execute("SELECT * FROM delta_scan('/lake/silver/mydata/table')").fetchdf()
```

UC provides the catalog (table discovery, schema management) while DuckDB queries the underlying Delta files directly.

## Security

### Default: Localhost Only

By default, UC binds to `127.0.0.1:8080`. This is safe for local development.

### Enabling Network Access

1. **Enable authentication first:**
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

```bash
# Make executable
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

## Vault Secrets Management

HashiCorp Vault provides centralized secrets for all projects.

### First-time Setup

```bash
# Start vault
docker compose up -d vault

# Initialize (saves keys to vault/init-keys.json)
chmod +x scripts/vault-init.sh
./scripts/vault-init.sh

# IMPORTANT: Back up init-keys.json securely, then delete from disk
```

### Usage

```bash
# Store a secret
vault kv put secret/koe-tts UC_DB_PASSWORD=mypassword WANDB_API_KEY=xxx

# Retrieve
vault kv get -format=json secret/koe-tts | jq -r '.data.data'

# Inject into shell (future: CLI wrapper)
export $(vault kv get -format=json secret/koe-tts | jq -r '.data.data | to_entries | .[] | "\(.key)=\(.value)"')
```

### Pinned Version

| Component | Version |
|-----------|---------|
| Vault | 1.15 |

## MinIO Object Storage

MinIO provides S3-compatible storage for Delta tables and MLflow artifacts.

### Critical: Storage Location

**MinIO data MUST be on local disks, NOT NFS-mounted storage.**

MinIO-on-NFS has weird locking behavior and failure modes. Configure `MINIO_DATA_PATH` in `.env`:

```bash
# For NAS: local disk path
MINIO_DATA_PATH=/volume1/forge-data

# For development: local directory (default)
MINIO_DATA_PATH=./minio-data
```

### Bucket Structure

```
s3://forge/
├── lake/
│   ├── bronze/
│   │   └── koe/
│   ├── silver/
│   │   └── koe/
│   └── gold/
│       └── koe/
└── mlflow/
    └── artifacts/
```

### Usage with MinIO Client

```bash
# Set up alias
mc alias set forge http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD

# Browse objects
mc ls forge/forge/lake/gold/koe/

# View Delta log
mc cat forge/forge/lake/gold/koe/utterances/_delta_log/00000000000000000000.json
```

### Client Configuration

Projects connect using these environment variables:

| Variable | Value | Used By |
|----------|-------|---------|
| `MINIO_ENDPOINT` | `http://localhost:9000` | Spark, DuckDB |
| `MINIO_ROOT_USER` | (from .env) | All clients |
| `MINIO_ROOT_PASSWORD` | (from .env) | All clients |
| `FORGE_LAKE_ROOT_S3A` | `s3a://forge/lake` | Spark |
| `FORGE_LAKE_ROOT_S3` | `s3://forge/lake` | DuckDB |

## MLflow Integration (Planned)

Will be enabled with MinIO artifact storage:

- Model registry at `http://localhost:5002`
- PostgreSQL backend for metadata
- Artifact storage at `s3://forge/mlflow/`

First, create the MLflow database:
```bash
docker exec -it uc-postgres psql -U uc_admin -c "CREATE DATABASE mlflow;"
```

## Troubleshooting

### UC using embedded H2 instead of Postgres

**Symptom:** Tables disappear after container restart

**Check:**
```bash
docker logs unity-catalog | grep -i "datasource\|h2\|postgres"
```

**Fix:** Ensure `hibernate.properties` is mounted at `/opt/unitycatalog/etc/conf/`

## Roadmap

### Storage Layer
- [x] MinIO S3-compatible storage
- [ ] Bucket lifecycle policies
- [ ] Cross-region replication (if needed)

### Catalog Layer
- [x] Unity Catalog for governance (future use)
- [ ] Hive Metastore for Spark table resolution
- [ ] DuckDB view sync from metastore

### Lineage Layer
- [ ] OpenLineage + Marquez for runtime lineage
- [ ] Dataset/job relationship graphs

### Model Registry (MLflow)
- [ ] Enable MLflow service with PostgreSQL backend
- [ ] Artifact storage on MinIO (`s3://forge/mlflow/`)
- [ ] Model versioning and staging (dev → staging → prod)
- [ ] Integration with training pipelines

### Vault Expansion
- [x] Basic KV secrets engine
- [ ] CLI wrapper for easy secret injection (`koe bootstrap`)
- [ ] AppRole auth for CI/CD pipelines
- [ ] Secret rotation policies

### Infrastructure
- [ ] Reverse proxy (Caddy/Traefik) for TLS termination
- [ ] Unified auth across services
- [ ] Monitoring stack (Prometheus + Grafana)

## Projects Using This Infrastructure

- [koe-tts](https://github.com/JohnYanez95/koe-tts) - Japanese TTS training pipeline

## License

Apache License 2.0
