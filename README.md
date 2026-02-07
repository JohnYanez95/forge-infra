# Lakehouse Infrastructure

Shared data catalog infrastructure for Delta Lake projects.

## Components

- **Unity Catalog OSS** - Centralized metadata catalog for Delta tables
- **PostgreSQL** - Persistent metadata store
- **MLflow** (optional) - Model registry and experiment tracking

## Quick Start

```bash
# 1. Clone
git clone https://github.com/JohnYanez95/lakehouse-infra.git
cd lakehouse-infra

# 2. Configure
cp .env.example .env
cp etc/conf/hibernate.properties.example etc/conf/hibernate.properties
# Edit both files with your password and lake path

# 3. Start services
docker compose up -d

# 4. Verify
curl http://127.0.0.1:8080/api/2.1/unity-catalog/catalogs
# Should return: {"catalogs": []}
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Lakehouse Infrastructure               │
│                                                         │
│  ┌──────────────┐  ┌────────────────────────────────┐  │
│  │  PostgreSQL  │◄─│    Unity Catalog Server        │  │
│  │   (metadata) │  │         :8080                  │  │
│  └──────────────┘  └────────────────────────────────┘  │
│                              │                          │
│                    ┌─────────┴─────────┐               │
│                    │      /lake/       │               │
│                    │  bronze/ silver/  │               │
│                    │  gold/ (Delta)    │               │
│                    └───────────────────┘               │
└─────────────────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   ┌─────────┐     ┌─────────┐     ┌─────────┐
   │ Project │     │ Project │     │ Project │
   │    A    │     │    B    │     │    C    │
   │ (Spark) │     │(DuckDB) │     │ (both)  │
   └─────────┘     └─────────┘     └─────────┘
```

## Pinned Versions

All components are pinned to stable releases:

| Component | Version | Notes |
|-----------|---------|-------|
| Unity Catalog | v0.3.1 | Pinned in docker-compose.yml |
| PostgreSQL | 16.4-alpine | Metadata store |
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
0 2 * * * /path/to/lakehouse-infra/scripts/backup.sh
```

### Recovery

```bash
gunzip -c backups/uc_YYYYMMDD_HHMMSS.sql.gz | \
  docker exec -i -e PGPASSWORD="$UC_DB_PASSWORD" uc-postgres \
  psql -U uc_admin unity_catalog
```

## MLflow Integration (Optional)

Uncomment the `mlflow` service in `docker-compose.yml` to enable:

- Model registry at `http://localhost:5000`
- Shared PostgreSQL backend
- Artifact storage in `./mlflow-artifacts/`

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

## Projects Using This Infrastructure

- [koe-tts](https://github.com/JohnYanez95/koe-tts) - Japanese TTS training pipeline

## License

Apache License 2.0
