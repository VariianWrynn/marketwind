# Backup sidecar for the report node: pg_dump (from the postgres image) + ossutil.
# The build context is deploy/report-node/ (see docker-compose.prod.yml), so
# `COPY backup.sh` resolves to deploy/report-node/backup.sh.
FROM postgres:16-alpine

# ossutil 2.x: distributed as a zip (verified 2026-07-08 against the Aliyun docs;
# URL pattern is https://gosspublic.alicdn.com/ossutil/v2/<ver>/ossutil-<ver>-linux-amd64.zip).
# CONFIRM the current version + musl compatibility at build time; if the binary fails on
# alpine/musl, change the base image to `postgres:16` (debian).
ARG OSSUTIL_VERSION=2.2.1
RUN apk add --no-cache curl unzip \
 && curl -fsSL -o /tmp/ossutil.zip \
      "https://gosspublic.alicdn.com/ossutil/v2/${OSSUTIL_VERSION}/ossutil-${OSSUTIL_VERSION}-linux-amd64.zip" \
 && unzip -j /tmp/ossutil.zip -d /usr/local/bin \
 && rm /tmp/ossutil.zip \
 && chmod +x /usr/local/bin/ossutil

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

# Daily loop. A single backup failure logs loud to stderr but does NOT kill the loop
# (backups are best-effort; report delivery is the safety-critical path the FC watcher covers).
CMD ["sh", "-c", "while true; do /usr/local/bin/backup.sh || echo 'BACKUP FAILED (see logs above)' >&2; sleep \"${BACKUP_INTERVAL_SECONDS:-86400}\"; done"]
