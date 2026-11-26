#!/usr/bin/env bash
#
# Freeze the local copy of the live database as `reference`.
#
#     ops/pull-db.sh          # first: a fresh copy of live, into cascadia
#     ops/make-reference.sh
#
# The tests run against copies of `reference`. Nothing ever writes to it. Run
# this again after every pull, so the tests see the copy you just took.
#
# It closes any connection to the local cascadia database first -- a running
# `docker compose up` holds some, and Postgres cannot copy a database that is
# in use. The web server reconnects on its next request.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

docker compose exec -T db psql -U cascadia -d postgres -v ON_ERROR_STOP=1 -q <<'SQL'
SELECT count(pg_terminate_backend(pid)) AS closed_connections
FROM   pg_stat_activity
WHERE  datname = 'cascadia' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS reference WITH (FORCE);
CREATE DATABASE reference TEMPLATE cascadia;
SQL

docker compose exec -T db psql -U cascadia -d reference -tAc \
    "SELECT 'reference: ' || count(*) || ' sightings, audit log to ' || max(occurred_at)::date
     FROM app.sighting, (SELECT max(occurred_at) AS occurred_at FROM app.audit_log) a"
