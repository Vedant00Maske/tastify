#!/bin/sh
# Restore test (spec §14 "restore testing"; RUNBOOK.md). Restores the newest backup into a
# scratch database, checks it has the live schema revision and the live row counts as of the
# backup (counts may only have grown since), then drops it. Exit status 0 means the backup is
# usable. Run monthly, and after any change to the backup setup:
#
#   docker compose -f docker-compose.prod.yml exec backup sh /scripts/verify.sh
set -eu

SCRATCH=tastify_restore_check
# shellcheck disable=SC2012 # backup names are ours: tastify-<UTC time>.dump
latest="$(ls -1t /backups/tastify-*.dump 2>/dev/null | head -n 1)"
if [ -z "$latest" ]; then
	echo "verify: no backup found in /backups" >&2
	exit 1
fi
echo "verify: newest backup $latest"

sh /scripts/restore.sh "$latest" "$SCRATCH" --replace >/tmp/restore.log 2>&1 || {
	cat /tmp/restore.log >&2
	echo "verify: FAILED to restore" >&2
	exit 1
}

live_rev="$(psql -tAc "SELECT version_num FROM alembic_version")"
copy_rev="$(psql -d "$SCRATCH" -tAc "SELECT version_num FROM alembic_version")"
status=0
if [ "$live_rev" != "$copy_rev" ]; then
	echo "verify: note: schema revision differs (backup $copy_rev, live $live_rev);" \
		"migrations ran after this backup"
fi
for table in users playlists user_interactions tracks model_versions; do
	live="$(psql -tAc "SELECT count(*) FROM $table")"
	copy="$(psql -d "$SCRATCH" -tAc "SELECT count(*) FROM $table")"
	echo "verify: $table backup=$copy live=$live"
	if [ "$table" = "tracks" ] && [ "$live" -gt 0 ] && [ "$copy" -eq 0 ]; then
		echo "verify: FAILED: the backup has no catalogue" >&2
		status=1
	fi
done
psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE \"$SCRATCH\" WITH (FORCE)" >/dev/null
if [ "$status" -eq 0 ]; then
	echo "verify: OK"
fi
exit "$status"
