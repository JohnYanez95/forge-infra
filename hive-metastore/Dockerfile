FROM apache/hive:3.1.3

# Copy S3A jars from Hadoop tools to the Hive classpath.
# The image bundles hadoop-aws:3.1.0 + aws-java-sdk:1.11.271 in
# /opt/hadoop/share/hadoop/tools/lib/ but they're not on Hive's
# classpath by default. These versions match the image's Hadoop 3.1.0 —
# do NOT mount hadoop-aws:3.3.4+ here (ClassNotFoundException on
# IOStatisticsSource which only exists in Hadoop 3.3+).
USER root
RUN cp /opt/hadoop/share/hadoop/tools/lib/hadoop-aws-3.1.0.jar \
       /opt/hadoop/share/hadoop/tools/lib/aws-java-sdk-bundle-1.11.271.jar \
       /opt/hive/lib/
USER hive

# Replace entrypoint with idempotent version that survives container
# restarts (e.g., NAS reboot). The stock entrypoint runs
# `schematool -initSchema` which fails if schema already exists.
COPY --chmod=755 entrypoint.sh /entrypoint.sh
