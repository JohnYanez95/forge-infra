#!/usr/bin/env python3
"""Forge Spark Smoke Test
=========================
Validates Hive Metastore connectivity + MinIO S3A I/O from inside
the Docker Compose network. Eliminates SSH-tunnel feedback loop
during infrastructure debugging.

Usage:
    docker compose --profile test run --rm spark-test

Interactive PySpark shell:
    docker compose --profile test run --rm --entrypoint /opt/spark/bin/pyspark spark-test \
        --packages org.apache.hadoop:hadoop-aws:3.4.1,com.amazonaws:aws-java-sdk-bundle:1.12.720

Exit codes:
    0  all checks passed
    1  one or more checks failed
"""

import os
import socket
import sys
import time
import traceback


# ---------------------------------------------------------------------------
# Configuration — all from environment, never hardcoded (security §9)
# ---------------------------------------------------------------------------

METASTORE_URI = os.environ.get("METASTORE_URI", "thrift://metastore:9083")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://minio:9000")
WAREHOUSE_DIR = os.environ.get("WAREHOUSE_DIR", "s3a://forge/lake/warehouse/")

# Credentials are read by Spark from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
# set in the compose environment block. We never log or print them.

# Test isolation namespace — deterministic names, no user input (security §5)
TEST_DB = "forge_smoke_test"
TEST_TABLE = "smoke_t1"

# Timeouts (security §10 — DoS & Resource Exhaustion)
METASTORE_WAIT_TIMEOUT = int(os.environ.get("METASTORE_WAIT_TIMEOUT", "90"))
SPARK_NETWORK_TIMEOUT = os.environ.get("SPARK_NETWORK_TIMEOUT", "30000")  # ms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validate_schemes():
    """Validate URI schemes at the boundary (security §4)."""
    if not WAREHOUSE_DIR.startswith("s3a://"):
        print(
            f"FAIL: WAREHOUSE_DIR must use s3a:// scheme, got: "
            f"{WAREHOUSE_DIR[:20]}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not METASTORE_URI.startswith("thrift://"):
        print(
            f"FAIL: METASTORE_URI must use thrift:// scheme, got: "
            f"{METASTORE_URI[:20]}",
            file=sys.stderr,
        )
        sys.exit(1)


def wait_for_metastore():
    """Block until the Hive Metastore thrift port accepts connections."""
    parts = METASTORE_URI.replace("thrift://", "").split(":")
    host, port = parts[0], int(parts[1])
    deadline = time.monotonic() + METASTORE_WAIT_TIMEOUT
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=3):
                print(f"  Metastore reachable at {host}:{port}")
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(2)

    print(
        f"FAIL: Metastore unreachable at {host}:{port} "
        f"after {METASTORE_WAIT_TIMEOUT}s",
        file=sys.stderr,
    )
    sys.exit(1)


def _redact_secrets(msg):
    """Redact credential values from error messages (security §11)."""
    text = str(msg)
    for env_key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
    ):
        val = os.environ.get(env_key, "")
        if val and val in text:
            text = text.replace(val, "***REDACTED***")
    # Cap length to prevent log flooding (security §10)
    return text[:500]


def create_spark():
    """Build a SparkSession wired to HMS + MinIO."""
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder
        .appName("forge-smoke-test")
        # Hive Metastore
        .config("spark.sql.catalogImplementation", "hive")
        .config("spark.sql.hive.metastore.uris", METASTORE_URI)
        # S3A / MinIO (security §9 — credentials from env, not hardcoded)
        .config("spark.hadoop.fs.s3a.endpoint", S3_ENDPOINT)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config(
            "spark.hadoop.fs.s3a.aws.credentials.provider",
            "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider",
        )
        .config("spark.sql.warehouse.dir", WAREHOUSE_DIR)
        # Timeouts (security §10)
        .config("spark.network.timeout", SPARK_NETWORK_TIMEOUT)
        .config("spark.sql.broadcastTimeout", "120")
        # Redact secrets in Spark UI / logs (security §11)
        .config(
            "spark.redaction.regex",
            "(?i)secret|password|token|access.key",
        )
    )

    # Optional HMS version override (for testing Spark 4.0.x against HMS 4.0)
    hms_version = os.environ.get("HMS_VERSION")
    if hms_version:
        builder = builder.config(
            "spark.sql.hive.metastore.version", hms_version
        )
    hms_jars = os.environ.get("HMS_JARS")
    if hms_jars:
        builder = builder.config(
            "spark.sql.hive.metastore.jars", hms_jars
        )

    return builder.enableHiveSupport().getOrCreate()


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

class Results:
    """Collects test results with live reporting."""

    def __init__(self):
        self.entries = []

    def record(self, name, passed, detail=""):
        self.entries.append((name, passed, detail))
        status = "PASS" if passed else "FAIL"
        line = f"  [{status}] {name}"
        if detail:
            line += f": {detail}"
        print(line)

    @property
    def failed(self):
        return sum(1 for _, ok, _ in self.entries if not ok)

    @property
    def passed(self):
        return sum(1 for _, ok, _ in self.entries if ok)


def run_tests(spark, results):
    """Execute DDL/DML smoke tests against HMS + S3A."""

    # 1. CREATE DATABASE
    try:
        spark.sql(f"DROP DATABASE IF EXISTS {TEST_DB} CASCADE")
        spark.sql(f"CREATE DATABASE {TEST_DB}")
        spark.sql(f"USE {TEST_DB}")
        results.record("CREATE DATABASE", True, TEST_DB)
    except Exception as exc:
        results.record("CREATE DATABASE", False, _redact_secrets(exc))
        return  # Cannot continue without the database

    # 2. CREATE TABLE (managed Parquet — forces warehouse path resolution)
    try:
        spark.sql(
            f"CREATE TABLE {TEST_TABLE} (id INT, name STRING) "
            f"STORED AS PARQUET"
        )
        results.record("CREATE TABLE", True, TEST_TABLE)
    except Exception as exc:
        results.record("CREATE TABLE", False, _redact_secrets(exc))
        return  # Cannot continue without the table

    # 3. DESCRIBE TABLE (metastore schema lookup)
    try:
        desc = spark.sql(f"DESCRIBE TABLE {TEST_TABLE}").collect()
        col_names = [row.col_name for row in desc]
        if "id" in col_names and "name" in col_names:
            results.record("DESCRIBE TABLE", True, f"columns: {col_names}")
        else:
            results.record(
                "DESCRIBE TABLE", False, f"unexpected columns: {col_names}"
            )
    except Exception as exc:
        results.record("DESCRIBE TABLE", False, _redact_secrets(exc))

    # 4. INSERT INTO (forces S3A write — the critical path)
    try:
        spark.sql(
            f"INSERT INTO {TEST_TABLE} VALUES (1, 'alice'), (2, 'bob')"
        )
        results.record("INSERT INTO (S3A write)", True, "2 rows written")
    except Exception as exc:
        results.record("INSERT INTO (S3A write)", False, _redact_secrets(exc))

    # 5. SELECT (forces S3A read)
    try:
        rows = spark.sql(f"SELECT * FROM {TEST_TABLE}").collect()
        if len(rows) == 2:
            results.record("SELECT (S3A read)", True, f"{len(rows)} rows")
        else:
            results.record(
                "SELECT (S3A read)", False, f"expected 2, got {len(rows)}"
            )
    except Exception as exc:
        results.record("SELECT (S3A read)", False, _redact_secrets(exc))

    # 6. SHOW TABLES (catalog listing)
    try:
        tables = [
            row.tableName
            for row in spark.sql("SHOW TABLES").collect()
        ]
        if TEST_TABLE in tables:
            results.record("SHOW TABLES", True, f"found {TEST_TABLE}")
        else:
            results.record(
                "SHOW TABLES", False,
                f"missing {TEST_TABLE}: {tables}",
            )
    except Exception as exc:
        results.record("SHOW TABLES", False, _redact_secrets(exc))


def cleanup(spark, results):
    """Remove test artifacts. Always runs regardless of test outcome."""
    try:
        spark.sql(f"DROP TABLE IF EXISTS {TEST_DB}.{TEST_TABLE}")
        spark.sql(f"DROP DATABASE IF EXISTS {TEST_DB} CASCADE")
        results.record("CLEANUP", True, "test artifacts removed")
    except Exception as exc:
        results.record("CLEANUP", False, _redact_secrets(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Forge Spark Smoke Test")
    print("=" * 60)

    # Validate config
    print("\n[1/4] Validating configuration...")
    validate_schemes()
    print(f"  METASTORE_URI: {METASTORE_URI}")
    print(f"  S3_ENDPOINT:   {S3_ENDPOINT}")
    print(f"  WAREHOUSE_DIR: {WAREHOUSE_DIR}")

    # Verify credentials are present (fail fast, never print them)
    for required_var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(required_var):
            print(
                f"FAIL: Required env var {required_var} is not set",
                file=sys.stderr,
            )
            return 1

    # Wait for metastore
    print("\n[2/4] Waiting for Hive Metastore...")
    wait_for_metastore()

    # Create Spark session
    print("\n[3/4] Creating SparkSession...")
    spark = create_spark()
    spark.sparkContext.setLogLevel("WARN")
    print("  SparkSession ready")

    # Run tests
    print("\n[4/4] Running tests...\n")
    results = Results()
    try:
        run_tests(spark, results)
    except Exception:
        traceback.print_exc()
    finally:
        cleanup(spark, results)
        spark.stop()

    # Summary
    print("\n" + "=" * 60)
    print(f"  {results.passed} passed, {results.failed} failed")
    print("=" * 60)

    return 0 if results.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
