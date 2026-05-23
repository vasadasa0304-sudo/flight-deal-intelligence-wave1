#!/usr/bin/env bash
# Dump the flight_deals database to data/exports/backups/ and retain the last 7 backups.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-data/exports/backups}"
KEEP_LAST="${KEEP_LAST:-7}"
TS=$(date -u +%Y%m%d_%H%M%S)
FILE="${BACKUP_DIR}/flight_deals_${TS}.sql.gz"

# Accept a SQLAlchemy URL (postgresql+psycopg://...) or a plain psql URL.
_RAW_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/flight_deals}"
PSQL_URL="${_RAW_URL//+psycopg/}"

mkdir -p "${BACKUP_DIR}"

echo "Writing backup: ${FILE}"
pg_dump "${PSQL_URL}" | gzip > "${FILE}"
echo "Backup complete: ${FILE}"

# Delete all but the most-recent $KEEP_LAST backups.
find "${BACKUP_DIR}" -maxdepth 1 -name "flight_deals_*.sql.gz" \
  | sort \
  | head -n -"${KEEP_LAST}" \
  | xargs -r rm --
echo "Retained last ${KEEP_LAST} backup(s) in ${BACKUP_DIR}."
