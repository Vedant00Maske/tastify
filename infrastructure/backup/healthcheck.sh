#!/bin/sh
# Backup container health: a backup exists and the newest is less than 26 hours old.
set -eu
last="$(cat /backups/last_success)"
age=$(( $(date +%s) - last ))
[ "$age" -lt 93600 ]
