#!/bin/sh
# Restore a backup into a database (RUNBOOK.md "Restore").
#
#   restore.sh <dump file> <target database> [--replace]
#
# The target is created; with --replace an existing target is dropped first (stop the apps
# before replacing the live database). Restores with pg_restore (parallel, exit on first error)
# and prints the schema revision and row counts of the main tables to compare with expectations.
#
# Run inside the backup container, which has the PostgreSQL client and the backups volume:
#   docker compose -f docker-compose.prod.yml exec backup \
#     sh /scripts/restore.sh /backups/tastify-20261119T033000Z.dump tastify_restored
set -eu

DUMP="${1:?usage: restore.sh <dump file> <target database> [--replace]}"
TARGET="${2:?usage: restore.sh <dump file> <target database> [--replace]}"
REPLACE="${3:-}"

case "$TARGET" in
*[!a-z0-9_]*) echo "restore: database name must be lowercase letters, digits and _" >&2; exit 2 ;;
esac

exists="$(psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$TARGET'")"
if [ "$exists" = "1" ]; then
	if [ "$REPLACE" != "--replace" ]; then
		echo "restore: database $TARGET exists; pass --replace to drop it first" >&2
		exit 2
	fi
	echo "restore: dropping $TARGET"
	psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE \"$TARGET\" WITH (FORCE)"
fi

echo "restore: creating $TARGET"
psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$TARGET\""
echo "restore: restoring $DUMP"
pg_restore --dbname="$TARGET" --no-owner --no-privileges --exit-on-error --jobs=4 "$DUMP"

echo "restore: schema revision"
psql -d "$TARGET" -tAc "SELECT version_num FROM alembic_version"
echo "restore: rows"
psql -d "$TARGET" -tA -F ' ' -c "
SELECT 'users', count(*) FROM users UNION ALL
SELECT 'playlists', count(*) FROM playlists UNION ALL
SELECT 'user_interactions', count(*) FROM user_interactions UNION ALL
SELECT 'tracks', count(*) FROM tracks UNION ALL
SELECT 'model_versions', count(*) FROM model_versions"
echo "restore: done"
