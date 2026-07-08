# Backup sidecar for the report node: pg_dump (from the postgres image) + ossutil.
# The build context is deploy/report-node/ (see docker-compose.prod.yml), so
# `COPY backup.sh` resolves to deploy/report-node/backup.sh.
FROM postgres:16-alpine

# ossutil: static Linux amd64 binary. CONFIRM URL/version + musl compatibility at build time;
# if the static binary fails on alpine/musl, change the base image to `postgres:16` (debian).
ARG OSSUTIL_VERSION=1.7.19
RUN apk add --no-cache curl \
 && curl -fsSL -o /usr/local/bin/ossutil \
      "https://gosspublic.alicdn.com/ossutil/${OSSUTIL_VERSION}/ossutil-v${OSSUTIL_VERSION}-linux-amd64" \
 && chmod +x /usr/local/bin/ossutil

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

# Daily loop. A single backup failure logs loud to stderr but does NOT kill the loop
# (backups are best-effort; report delivery is the safety-critical path the FC watcher covers).
CMD ["sh", "-c", "while true; do /usr/local/bin/backup.sh || echo 'BACKUP FAILED (see logs above)' >&2; sleep \"${BACKUP_INTERVAL_SECONDS:-86400}\"; done"]
