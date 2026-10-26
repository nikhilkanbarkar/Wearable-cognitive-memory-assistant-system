#!/usr/bin/env bash
# Safe SQLite backup using the online .backup API.
# Works while recognition or the dashboard is running.
#
# Usage:
#   ./backup_database.sh
#   ./backup_database.sh --with-files

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="${PROJECT_ROOT}/database/recognition.db"
BACKUP_DIR="${PROJECT_ROOT}/backups"
WITH_FILES=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-files) WITH_FILES=1; shift ;;
        --help|-h) echo "Usage: $0 [--with-files]"; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

mkdir -p "$BACKUP_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

if [[ ! -f "$DB_PATH" ]]; then
    echo "Error: database not found at $DB_PATH" >&2
    exit 1
fi

DB_BACKUP="${BACKUP_DIR}/recognition_${TIMESTAMP}.db"

python3 - "$DB_PATH" "$DB_BACKUP" <<'PY'
import sqlite3, sys
src_path, dst_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(src_path)
dst = sqlite3.connect(dst_path)
try:
    with dst:
        src.backup(dst)
finally:
    src.close()
    dst.close()
PY

echo "Database backed up to: $DB_BACKUP"

if [[ "$WITH_FILES" -eq 1 ]]; then
    FILES_BACKUP="${BACKUP_DIR}/unknown_files_${TIMESTAMP}.tar.gz"
    tar -czf "$FILES_BACKUP" \
        -C "$PROJECT_ROOT" \
        logs/unknown_faces unknown_embeddings 2>/dev/null || true
    echo "Files backed up to:    $FILES_BACKUP"
fi
