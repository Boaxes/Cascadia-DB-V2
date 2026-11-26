#!/usr/bin/env bash
#
# The pipeline's tests against the two local copies of DB167, end to end.
#
#     ETL/verify/run_tests.sh setup     # once: import both copies, copy live in
#     ETL/verify/run_tests.sh           # every time
#
# Two test databases, each built from scratch every run:
#
#   test_last   DB167 as it was at the live site's last import (DB167_LastImport,
#               ETL/mirror_sqlserver.py), with the live snapshot beside it in
#               live_dbo and live_app. The pipeline runs here exactly as it
#               will on the live server the first time:
#                 1. inputs from the old dbo, a build with no edits, the audit
#                    log moved onto the hashed ids (ETL/move_to_hashed_keys.py),
#                    which also deletes the entries the old import wrote: the
#                    audit log then holds only changes people made
#                 2. the real build, compared with live: every difference must
#                    be one the plan explains (compare_with_live.py); the
#                    pipeline makes the old import's corrections itself
#                 3. built again, and every table and view must come out the
#                    same (checksums.py)
#                 4. swapped in
#   test_today  DB167 as it is now (DB167_Today), with test_last's audit log,
#               track files and vessel numbers, as the live server will have them
#               at the next run:
#                 5. built, and checked against test_last: every edit on its
#                    record, records matched by their hashed key, links kept,
#                    every changed value changed in DB167 (check_rerun.py)
#                 6. built again, and every table and view must come out the same
#                 7. swapped in; then edits made through the website (a form
#                    edit, a track match, a delete) must survive a rebuild
#                    (website_edits_survive.py)
#
# Reports are written to ETL/verify/reports/. Needs the db service, and for
# setup the mssql one (docker compose --profile mssql up -d mssql).
set -euo pipefail
cd "$(dirname "$0")/../.."

REPORTS=ETL/verify/reports
mkdir -p "$REPORTS"

dbt() { local db=$1; shift; docker compose --profile etl run --rm -T -w /app/dbt -e PGDATABASE="$db" etl dbt "$@" --profiles-dir . ; }
sql() { local db=$1; shift; docker compose exec -T db psql -U cascadia -d "$db" -v ON_ERROR_STOP=1 -q "$@"; }
etl() { local db=$1; shift; docker compose --profile etl run --rm -T -e PIPELINE_DATABASE_URL="postgresql://cascadia:cascadia@db:5432/$db" etl "$@"; }
step() { echo; echo "== $*"; }
# The audit log holds only changes people made on the website: nothing may be
# written under the actors the old import used.
no_old_import_entries() {
    local n
    n=$(sql "$1" -tA -c "select count(*) from app.audit_log where actor_name in ('legacy-cleanup', 'Data pipeline')")
    [ "$n" = "0" ] || { echo "$1: $n audit log entries by the old import's actors"; exit 1; }
    echo "$1: no audit log entries by the old import's actors"
}

if [ "${1:-}" = setup ]; then
    for pair in "test_last DB167_LastImport" "test_today DB167_Today"; do
        set -- $pair
        step "importing $2 into $1"
        sql postgres -c "drop database if exists $1"
        docker compose --profile etl --profile mssql run --rm -T -e PIPELINE_DATABASE_URL="postgresql://cascadia:cascadia@db:5432/$1" etl \
            sh -c "DB167_ODBC=\"DRIVER={ODBC Driver 18 for SQL Server};SERVER=mssql,1433;DATABASE=$2;UID=sa;PWD=\$MSSQL_SA_PASSWORD;Encrypt=yes;TrustServerCertificate=yes\" python import_raw.py"
        step "copying the live snapshot into $1 (live_dbo, live_app)"
        docker compose exec -T db sh -c "pg_dump -U cascadia -d cascadia -Fc -N raw -f /tmp/live_noraw.dump && pg_restore -U cascadia -d $1 --no-owner /tmp/live_noraw.dump" || true
        sql "$1" -c "alter schema dbo rename to live_dbo" -c "alter schema app rename to live_app"
    done
    # DB167 had no SpeciesT at the last import; the pipeline needs one, so the
    # last-import copy borrows today's. Every species difference this causes is
    # listed by compare_with_live.py.
    docker compose exec -T db sh -c 'pg_dump -U cascadia -d test_today -t raw.\"SpeciesT\" | psql -U cascadia -d test_last -q'
    exit 0
fi

reset() {
    sql "$1" -c "set client_min_messages = warning" -c "drop schema if exists dbo, build, dbo_next, build_next, app_next, app cascade"
    dbt "$1" run-operation create_persistent_tables >/dev/null
}

step "test_last: a fresh start, with live's audit log"
reset test_last
sql test_last -c "insert into app.audit_log overriding system value select * from live_app.audit_log" \
              -c "select setval(pg_get_serial_sequence('app.audit_log', 'id'), (select max(id) from app.audit_log))" >/dev/null
etl test_last python move_to_hashed_keys.py inputs --from-schema live_dbo

step "test_last: a build with no edits, then the audit log moved onto its ids"
dbt test_last build --vars '{replay: false}' --exclude package:elementary > "$REPORTS/build_last_noedits.log"
tail -1 "$REPORTS/build_last_noedits.log"
etl test_last python move_to_hashed_keys.py audit --from-schema live_dbo
no_old_import_entries test_last

step "test_last: the real build"
dbt test_last build --exclude package:elementary > "$REPORTS/build_last.log"
tail -1 "$REPORTS/build_last.log"

step "test_last: every difference from live explained"
etl test_last python verify/compare_with_live.py --report verify/reports/compare_with_live.json \
    > "$REPORTS/compare_with_live.txt" 2>/dev/null || { cat "$REPORTS/compare_with_live.txt"; exit 1; }
grep -E "^(Explained|Unexplained)" "$REPORTS/compare_with_live.txt"

step "test_last: built twice, the same"
etl test_last python verify/checksums.py --db test_last --out verify/reports/last_1.json
dbt test_last build --exclude package:elementary > "$REPORTS/build_last_2.log"
etl test_last python verify/checksums.py --db test_last --out verify/reports/last_2.json
etl test_last python verify/checksums.py --compare verify/reports/last_1.json verify/reports/last_2.json

no_old_import_entries test_last

step "test_last: swapped in"
dbt test_last run-operation swap | tail -1

step "test_today: a fresh start, with test_last's audit log, track files and vessel numbers"
reset test_today
docker compose exec -T db sh -c 'pg_dump -U cascadia -d test_last -t app.audit_log -t app.track_geometry -t app.vessel_number --data-only -Fc -f /tmp/app_state.dump 2>/dev/null && pg_restore -U cascadia -d test_today --data-only --disable-triggers /tmp/app_state.dump'
sql test_today -c "select setval(pg_get_serial_sequence('app.audit_log', 'id'), (select max(id) from app.audit_log))" >/dev/null

step "test_today: the build"
dbt test_today build --exclude package:elementary > "$REPORTS/build_today.log"
tail -1 "$REPORTS/build_today.log"

step "test_today: every edit applied, every record matched"
etl test_today sh -c "cd verify && python check_rerun.py --report reports/check_rerun.json" \
    > "$REPORTS/check_rerun.txt" 2>/dev/null || { cat "$REPORTS/check_rerun.txt"; exit 1; }
sed -n '/^Records matched/,/^$/p' "$REPORTS/check_rerun.txt"
grep -E "^(Explained|Unexplained)" "$REPORTS/check_rerun.txt"

step "test_today: built twice, the same"
etl test_today python verify/checksums.py --db test_today --out verify/reports/today_1.json
dbt test_today build --exclude package:elementary > "$REPORTS/build_today_2.log"
etl test_today python verify/checksums.py --db test_today --out verify/reports/today_2.json
etl test_today python verify/checksums.py --compare verify/reports/today_1.json verify/reports/today_2.json

step "test_today: website edits survive a rebuild"
dbt test_today run-operation swap | tail -1
site() { docker compose run --rm -T -v "$PWD/ETL/verify:/verify" -e PHASE="$1" \
             -e DATABASE_URL=postgresql://cascadia:cascadia@db:5432/test_today web \
             python manage.py shell -c "exec(open('/verify/website_edits_survive.py').read())" 2>/dev/null | tail -2; }
site make
dbt test_today build --exclude package:elementary > "$REPORTS/build_today_3.log"
tail -1 "$REPORTS/build_today_3.log"
dbt test_today run-operation swap | tail -1
site check
no_old_import_entries test_today

step "all passed"
