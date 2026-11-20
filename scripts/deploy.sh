#!/bin/sh
# Deploy (or roll back to) a released version on the server (RUNBOOK.md "Deploy", "Roll back").
#
#   scripts/deploy.sh v0.7.0
#
# Run from the server's checkout of the repository, next to .env.production. Steps:
#   1. check out the release's compose and proxy files (git tag),
#   2. back up the database (a restore point for this deploy),
#   3. pull the release images (IMAGE_PREFIX in .env.production, e.g. ghcr.io/owner),
#   4. apply database migrations,
#   5. recreate the application services on the new images and wait until healthy,
#   6. reload the edge proxy and check readiness through it,
#   7. record the version (previous one kept for rollback).
# Rolling back is deploying the previous version; see RUNBOOK.md about migrations.
set -eu

TAG="${1:?usage: scripts/deploy.sh <version tag, e.g. v0.7.0>}"
ENV_FILE="${ENV_FILE:-.env.production}"
[ -f "$ENV_FILE" ] || { echo "deploy: $ENV_FILE not found" >&2; exit 2; }

# Only the variables this script needs, read without executing the file.
setting() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; }
PREFIX="$(setting IMAGE_PREFIX)"
SITE="$(setting APP_PUBLIC_URL)"
[ -n "$PREFIX" ] || { echo "deploy: set IMAGE_PREFIX in $ENV_FILE (e.g. ghcr.io/owner)" >&2; exit 2; }

export BACKEND_IMAGE="$PREFIX/tastify-backend:$TAG"
export FRONTEND_IMAGE="$PREFIX/tastify-frontend:$TAG"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file $ENV_FILE"

echo "deploy: $TAG ($BACKEND_IMAGE, $FRONTEND_IMAGE)"
git fetch --quiet --tags origin
git checkout --quiet --detach "$TAG"

if $COMPOSE ps --status running --services 2>/dev/null | grep -qx backup; then
	echo "deploy: backing up the database first"
	$COMPOSE exec -T backup sh /scripts/backup.sh --once
fi

$COMPOSE pull --quiet migrate api recommender worker beat frontend
$COMPOSE up -d --wait postgres redis
$COMPOSE run --rm migrate
$COMPOSE up -d --no-deps --force-recreate --wait --wait-timeout 300 \
	api recommender worker beat frontend
$COMPOSE up -d --wait caddy backup
$COMPOSE exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile

if [ -n "$SITE" ]; then
	echo "deploy: checking $SITE"
	curl --fail --silent --show-error --retry 10 --retry-delay 3 --retry-all-errors \
		"$SITE/api/v1/health/ready" >/dev/null
fi

[ -f .deployed ] && cp .deployed .deployed.previous
echo "$TAG" >.deployed
echo "deploy: $TAG is live (previous: $(cat .deployed.previous 2>/dev/null || echo none))"
