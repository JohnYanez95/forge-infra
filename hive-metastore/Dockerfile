FROM apache/hive:3.1.3

# Replace entrypoint with idempotent version that survives container
# restarts (e.g., NAS reboot). The stock entrypoint runs
# `schematool -initSchema` which fails if schema already exists.
COPY --chmod=755 entrypoint.sh /entrypoint.sh
