#!/bin/sh
# One-shot Postgres backup -> gzip -> OSS. Fails LOUD on ANY error:
#  - exits non-zero, AND
#  - sends a Bark push (if BARK_BASE_URL + BARK_KEY are set) so a failed backup is
#    never silent (project value: "silent fail strongly unwelcomed").
# The daily loop lives in the container CMD / compose, not here (keeps this testable).
set -eu

: "${DATABASE_URL:?DATABASE_URL required}"
: "${OSS_BUCKET:?OSS_BUCKET required}"

DATE="$(date +%F)"
REMOTE="oss://${OSS_BUCKET}/backups/pg/marketwind-${DATE}.sql.gz"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

notify_failure() {
  # Best-effort Bark alert; never mask the original failure. No-op if unconfigured.
  [ -n "${BARK_BASE_URL:-}" ] && [ -n "${BARK_KEY:-}" ] || return 0
  curl -fsS -m 10 \
    "${BARK_BASE_URL%/}/${BARK_KEY}/MarketWind%20backup%20failed/Postgres%20backup%20to%20OSS%20failed%20on%20${DATE}" \
    >/dev/null 2>&1 || true
}

# Explicit per-step failure handling: `|| return 1` guarantees a failed step aborts the
# run (set -e is disabled when a function is used as an `if` condition), so a broken
# pg_dump can never fall through to uploading a partial/empty dump.
run_backup() {
  pg_dump "$DATABASE_URL" > "$WORK/dump.sql" || return 1
  gzip -c "$WORK/dump.sql" > "$WORK/dump.sql.gz" || return 1
  ossutil cp "$WORK/dump.sql.gz" "$REMOTE" ${OSSUTIL_AUTH_ARGS:-} || return 1
}

if run_backup; then
  echo "backup uploaded: $REMOTE"
else
  echo "backup FAILED -- sending Bark alert (if configured)" >&2
  notify_failure
  exit 1
fi
