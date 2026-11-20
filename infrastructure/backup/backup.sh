#!/bin/sh
# Scheduled PostgreSQL backups (docker-compose.prod.yml `backup` service; RUNBOOK.md).
#
# Every BACKUP_INTERVAL_SECONDS (default daily) writes a compressed custom-format dump to
# /backups/tastify-<UTC time>.dump, atomically (written to .partial, then renamed), deletes dumps
# older than BACKUP_KEEP_DAYS, and records the time of the last success in /backups/last_success
# (the worker exposes it as a metric; an alert fires when it is too old).
#
# One-off backup (e.g. before a deploy):
#   docker compose -f docker-compose.prod.yml exec backup sh /scripts/backup.sh --once
#
# Connection settings come from PGHOST, PGUSER, PGPASSWORD and PGDATABASE.
set -eu

DIR=/backups
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"

backup_once() {
	stamp="$(date -u +%Y%m%dT%H%M%SZ)"
	target="$DIR/tastify-$stamp.dump"
	echo "backup: writing $target"
	pg_dump --format=custom --compress=6 --no-owner --no-privileges --file="$target.partial"
	# A dump that cannot be listed is not a backup.
	pg_restore --list "$target.partial" >/dev/null
	mv "$target.partial" "$target"
	date -u +%s >"$DIR/last_success"
	size="$(du -h "$target" | cut -f1)"
	echo "backup: done ($size)"
	find "$DIR" -name 'tastify-*.dump' -type f -mtime +"$KEEP_DAYS" -print -delete
	find "$DIR" -name '*.partial' -type f -mmin +120 -delete
}

if [ "${1:-}" = "--once" ]; then
	backup_once
	exit 0
fi

# Wait until the database accepts connections, then back up on the interval.
until pg_isready --quiet; do sleep 2; done
while true; do
	if ! backup_once; then
		echo "backup: FAILED; retrying in 10 minutes" >&2
		rm -f "$DIR"/*.partial
		sleep 600
		continue
	fi
	sleep "$INTERVAL"
done
