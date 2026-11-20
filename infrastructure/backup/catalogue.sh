#!/bin/sh
# Catalogue snapshots: move the music catalogue and trained models (not user data) from the
# machine that runs the ML pipelines to a deployment (DEPLOYMENT.md "Loading the catalogue").
#
#   catalogue.sh export <file|->    data-only dump of every non-user table
#   catalogue.sh import <file>      replace those tables' contents in the target database
#
# Import is for a new deployment (no users yet). Both sides must be at the same schema revision
# (alembic upgrade head). User data (accounts,
# events, playlists, connections, logs) is never exported: USER_TABLES below are excluded by
# name, and every other table is catalogue, provenance or model data.
#
# From the development database to a file on the host:
#   docker exec -i soniqueo-postgres-1 sh -s export - < infrastructure/backup/catalogue.sh > catalogue.dump
# Into a deployment:
#   docker compose -f docker-compose.prod.yml cp catalogue.dump backup:/backups/catalogue.dump
#   docker compose -f docker-compose.prod.yml exec backup sh /scripts/catalogue.sh import /backups/catalogue.dump
#
# Connection settings: PGHOST, PGUSER, PGPASSWORD, PGDATABASE (inside the postgres container
# the defaults come from POSTGRES_USER / POSTGRES_DB).
set -eu

export PGUSER="${PGUSER:-${POSTGRES_USER:-soniqueo}}"
export PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-soniqueo}}"

USER_TABLES="users user_sessions account_tokens user_preferences user_artist_preferences \
user_genre_preferences user_interactions user_taste_profiles playlists playlist_tracks \
playlist_exports provider_connections provider_imports provider_track_ids \
recommendation_requests recommendation_logs experiments alembic_version"

catalogue_tables() {
	# shellcheck disable=SC2086 # split the list into one argument per table
	excluded="$(printf "'%s'," $USER_TABLES)"
	psql -tA -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public'
		AND tablename NOT IN (${excluded%,}) ORDER BY tablename"
}

case "${1:-}" in
export)
	target="${2:?usage: catalogue.sh export <file|->}"
	args=""
	for table in $(catalogue_tables); do args="$args --table=public.$table"; done
	revision="$(psql -tAc "SELECT version_num FROM alembic_version")"
	echo "catalogue: exporting at schema revision $revision" >&2
	# shellcheck disable=SC2086
	if [ "$target" = "-" ]; then
		pg_dump --format=custom --data-only --no-owner --no-privileges $args
	else
		pg_dump --format=custom --data-only --no-owner --no-privileges $args --file="$target"
	fi
	echo "catalogue: done" >&2
	;;
import)
	source="${2:?usage: catalogue.sh import <file>}"
	# Only into a deployment without users: user tables reference the catalogue (events,
	# playlists), and replacing tracks under them would break or delete their data. A live
	# deployment updates its catalogue with the pipelines instead (ML_PIPELINE.md).
	users="$(psql -tAc "SELECT (SELECT count(*) FROM users) + (SELECT count(*) FROM playlists)")"
	if [ "$users" != "0" ]; then
		echo "catalogue: refusing to import: this database already has users or playlists" >&2
		exit 1
	fi
	tables="$(catalogue_tables | paste -sd, -)"
	echo "catalogue: replacing $(echo "$tables" | tr ',' '\n' | wc -l) tables"
	# One transaction: the catalogue is never half-loaded. Triggers (foreign keys) are deferred
	# for the load, which needs a superuser (the compose database user is one).
	{
		echo "BEGIN;"
		# CASCADE reaches only user tables, which the check above proved empty.
		echo "TRUNCATE $tables CASCADE;"
		echo "SET session_replication_role = replica;"
		pg_restore --data-only --no-owner --no-privileges --file=- "$source"
		echo "SET session_replication_role = DEFAULT;"
		echo "COMMIT;"
		echo "ANALYZE;"
	} | psql -v ON_ERROR_STOP=1 --quiet
	psql -tA -c "SELECT 'tracks', count(*) FROM tracks UNION ALL
		SELECT 'active models', count(*) FROM model_versions WHERE status = 'active'"
	echo "catalogue: imported; restart the api and recommender services to drop process caches"
	;;
*)
	echo "usage: catalogue.sh export <file|-> | import <file>" >&2
	exit 2
	;;
esac
