#!/usr/bin/env bash
# Nightly Mintly backup: a verified pg_dump of the app database plus a copy of the
# price-history cold storage (Backend/.archive/price-history/), kept locally with
# rotation and optionally rsynced off the server.
#
# Run from anywhere (it finds Backend/ from its own location):
#   Backend/scripts/backup.sh
#
# Cron on the VPS (03:10 nightly — after the day's snapshot job has archived):
#   10 3 * * * /path/to/Mintly/Backend/scripts/backup.sh >> /var/log/mintly-backup.log 2>&1
#
# Config — environment variables win, then plain KEY=value lines in Backend/.env:
#   DATABASE_URL      required; the database to dump (same value the app uses)
#   BACKUP_DIR        where backups land        (default: ~/backups/mintly)
#   BACKUP_KEEP_DAYS  days of local dumps kept  (default: 14)
#   BACKUP_REMOTE     optional rsync destination for the whole backup dir,
#                     e.g. user@host:/backups/mintly (an off-server copy; without
#                     it the script warns — a backup on the same disk as the DB
#                     does not survive the disk)
#   PG_BIN            optional dir holding pg_dump/pg_restore, for hosts where
#                     they aren't on PATH (this dev Mac: /opt/homebrew/opt/postgresql@15/bin)
#
# Layout under BACKUP_DIR:
#   db/mintly-YYYY-MM-DD.dump   one custom-format dump per UTC day (same-day rerun overwrites)
#   price-history/              mirror of Backend/.archive/price-history/ (monthly CSVs)
#
# Restore:
#   pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL" db/mintly-YYYY-MM-DD.dump
#   cp price-history/*.csv.gz /path/to/Mintly/Backend/.archive/price-history/
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"

log() { echo "$(date -u '+%Y-%m-%d %H:%M:%S') $*"; }

# KEY=value lookup in Backend/.env (the documented format; quotes stripped).
# Never echo the values themselves — DATABASE_URL is a secret.
env_get() {
    [ -f "$BACKEND_DIR/.env" ] || return 0
    sed -n "s/^$1=//p" "$BACKEND_DIR/.env" | tail -1 \
        | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

DATABASE_URL="${DATABASE_URL:-$(env_get DATABASE_URL)}"
BACKUP_DIR="${BACKUP_DIR:-$(env_get BACKUP_DIR)}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/mintly}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-$(env_get BACKUP_KEEP_DAYS)}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
BACKUP_REMOTE="${BACKUP_REMOTE:-$(env_get BACKUP_REMOTE)}"
PG_BIN="${PG_BIN:-$(env_get PG_BIN)}"

if [ -z "$DATABASE_URL" ]; then
    log "ERROR: DATABASE_URL is not set (environment or Backend/.env)" >&2
    exit 1
fi
if [ -n "$PG_BIN" ]; then
    PATH="$PG_BIN:$PATH"
fi
command -v pg_dump >/dev/null || { log "ERROR: pg_dump not found on PATH (set PG_BIN)" >&2; exit 1; }

DUMP_DIR="$BACKUP_DIR/db"
mkdir -p "$DUMP_DIR"

# --- 1. Database dump: write to a temp file, verify it, then rename into place
# (never leave a half-written file under the final name; a same-day rerun
# overwrites, so each UTC day has exactly one dump).
STAMP="$(date -u +%Y-%m-%d)"
DUMP_FILE="$DUMP_DIR/mintly-$STAMP.dump"
TMP_FILE="$DUMP_FILE.tmp"
trap 'rm -f "$TMP_FILE"' EXIT

log "dumping database -> $DUMP_FILE"
pg_dump --format=custom --no-owner --file "$TMP_FILE" "$DATABASE_URL"
pg_restore --list "$TMP_FILE" >/dev/null   # verify the dump is readable before keeping it
mv "$TMP_FILE" "$DUMP_FILE"
log "dump ok ($(du -h "$DUMP_FILE" | cut -f1 | tr -d ' '))"

# --- 2. Price-history cold storage: the DB now keeps every daily row (already
# captured by the pg_dump above), so the archive CSVs are a redundant, extra
# backup of price history. Append-only source, so no --delete: a bad/empty
# source can never erase already-backed-up months.
ARCHIVE_DIR="$BACKEND_DIR/.archive/price-history"
if [ -d "$ARCHIVE_DIR" ]; then
    rsync -a "$ARCHIVE_DIR/" "$BACKUP_DIR/price-history/"
    log "price-history archive synced ($(ls "$ARCHIVE_DIR" | wc -l | tr -d ' ') files)"
else
    log "no price-history archive at $ARCHIVE_DIR yet — skipped"
fi

# --- 3. Rotate local dumps (the off-server copy below is not pruned from here)
find "$DUMP_DIR" -name 'mintly-*.dump' -mtime +"$BACKUP_KEEP_DAYS" -delete

# --- 4. Off-server copy
if [ -n "$BACKUP_REMOTE" ]; then
    log "rsyncing to $BACKUP_REMOTE"
    rsync -a "$BACKUP_DIR/" "$BACKUP_REMOTE/"
    log "off-server copy ok"
else
    log "WARNING: BACKUP_REMOTE not set — backup is on this machine only"
fi

log "backup complete"
