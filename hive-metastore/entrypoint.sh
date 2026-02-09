#!/bin/bash
set -e

: ${DB_DRIVER:=derby}

export HIVE_CONF_DIR=$HIVE_HOME/conf

if [ -d "${HIVE_CUSTOM_CONF_DIR:-}" ]; then
  find "${HIVE_CUSTOM_CONF_DIR}" -type f -exec \
    ln -sfn {} "${HIVE_CONF_DIR}"/ \;
  export HADOOP_CONF_DIR=$HIVE_CONF_DIR
  export TEZ_CONF_DIR=$HIVE_CONF_DIR
fi

export HADOOP_CLIENT_OPTS="$HADOOP_CLIENT_OPTS -Xmx1G $SERVICE_OPTS"

# Idempotent schema init: check if schema exists before attempting init.
# schematool -info succeeds if the schema is present, fails otherwise.
if ! "$HIVE_HOME/bin/schematool" -dbType "$DB_DRIVER" -info >/dev/null 2>&1; then
  echo "Initializing metastore schema..."
  "$HIVE_HOME/bin/schematool" -dbType "$DB_DRIVER" -initSchema
  echo "Schema initialized successfully."
else
  echo "Schema already exists, skipping initialization."
fi

if [ "${SERVICE_NAME}" == "hiveserver2" ]; then
  export HADOOP_CLASSPATH=$TEZ_HOME/*:$TEZ_HOME/lib/*:$HADOOP_CLASSPATH
elif [ "${SERVICE_NAME}" == "metastore" ]; then
  export METASTORE_PORT=${METASTORE_PORT:-9083}
fi

exec "$HIVE_HOME/bin/hive" --skiphadoopversion --skiphbasecp --service "$SERVICE_NAME"
