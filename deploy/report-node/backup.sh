#!/bin/sh
# One-shot Postgres backup -> gzip -> OSS. Fails loud (non-zero exit) on ANY error.
# The daily loop lives in the container CMD / compose, not here (keeps this testable).
set -eu

: "${DATABASE_URL:?DATABASE_URL required}"
: "${OSS_BUCKET:?OSS_BUCKET required}"

DATE="$(date +%F)"
REMOTE="oss://${OSS_BUCKET}/backups/pg/marketwind-${DATE}.sql.gz"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

pg_dump "$DATABASE_URL" > "$WORK/dump.sql"
gzip -c "$WORK/dump.sql" > "$WORK/dump.sql.gz"
ossutil cp "$WORK/dump.sql.gz" "$REMOTE" ${OSSUTIL_AUTH_ARGS:-}

echo "backup uploaded: $REMOTE"
