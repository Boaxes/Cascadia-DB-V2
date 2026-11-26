#!/usr/bin/env bash
#
# Delete every track file from a scratch copy of the site, put every one back
# through the website's own Track File Manager pages, rebuild with dbt, and
# list every difference from today. The work is in rebuild_all_track_files.py;
# this runs the whole sequence in order.
#
#   REFERENCE=<folder of the original track files, read only> \
#   OUT=<folder for the reports> BUCKET=<empty folder for the scratch bucket> \
#   ETL/verify/rebuild_all_track_files.sh
#
# It makes the database $DB (default test_c2) from $SOURCE (default
# test_review, today's data fully built; read only), runs a web container
# $NAME (default web-c2) on port $PORT (default 8041), and removes all three at
# the end unless KEEP=1. It never touches any other database or container.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
WT=$(cd "$HERE/../.." && pwd)
: "${REFERENCE:?the folder of the original track files}"
: "${OUT:?a folder for the reports}"
: "${BUCKET:?an empty folder for the scratch bucket}"
DB=${DB:-test_c2}
SOURCE=${SOURCE:-test_review}
NAME=${NAME:-web-c2}
PORT=${PORT:-8041}
KEEP=${KEEP:-0}
case "$DB" in test_today | test_last | test_review | reference) echo "refusing $DB"; exit 1 ;; test_*) ;; *) echo "the database must be named test_*"; exit 1 ;; esac
mkdir -p "$OUT" "$BUCKET"
[ -z "$(ls -A "$BUCKET")" ] || { echo "$BUCKET is not empty"; exit 1; }

psql_db() { docker exec -i cascadia-db-1 psql -U cascadia -d "$1" -At "${@:2}"; }
script() {
  docker run --rm --network cascadia_default -v "$HERE":/verify:ro -v "$REFERENCE":/reference:ro \
    -v "$BUCKET":/bucket -v "$OUT":/out -e C2_PASSWORD="$PASSWORD" \
    cascadia-web python -I /verify/rebuild_all_track_files.py "$@"
}
dbt() {
  docker run --rm --network cascadia_default -v "$WT/ETL":/app -w /app/dbt -e PGHOST=db -e PGDATABASE="$DB" \
    cascadia-etl dbt "$@" --profiles-dir .
}
sums() { docker run --rm --network cascadia_default -v "$WT/ETL":/app -w /app -v "$OUT":/out cascadia-etl python verify/checksums.py "$@"; }
build() {   # build, swap, fingerprint every dbo and app table, and fingerprint the whole Audit Log
  dbt build --exclude package:elementary > "$OUT/build_$1.log" 2>&1 || { echo "build $1 FAILED"; tail -20 "$OUT/build_$1.log"; exit 1; }
  dbt run-operation swap > "$OUT/swap_$1.log" 2>&1
  sums --db "$DB" --schemas dbo,app --out "/out/sums_$1.json" > /dev/null
  psql_db "$DB" -c "select count(*), md5(string_agg(md5(to_jsonb(a)::text), '' order by id)) from app.audit_log a" > "$OUT/auditsum_$1.txt"
  echo "build $1 done: $(grep -o 'PASS=[0-9]* WARN=[0-9]* ERROR=[0-9]*' "$OUT/build_$1.log" | tail -1)"
}
cleanup() {
  [ "$KEEP" = 1 ] && return
  docker rm -f "$NAME" > /dev/null 2>&1 || true
  psql_db postgres -c "drop database if exists $DB" > /dev/null 2>&1 || true
  rm -rf "$BUCKET"/* 2> /dev/null || true
}
trap cleanup EXIT

[ -d "$WT/ETL/dbt/dbt_packages" ] || dbt deps > /dev/null

echo "== 1. the scratch copy of today's data: $DB from $SOURCE"
psql_db postgres -c "create database $DB template template0" > /dev/null
docker exec cascadia-db-1 pg_dump -U cascadia -Fc -f "/tmp/$DB.fc" "$SOURCE"
docker exec cascadia-db-1 pg_restore -U cascadia -d "$DB" --no-owner "/tmp/$DB.fc"
docker exec cascadia-db-1 rm "/tmp/$DB.fc"
docker run -d --name "$NAME" --network cascadia_default -p "$PORT:8000" -v "$WT/Django":/app -v "$WT/TESTS":/TESTS \
  -v "$BUCKET":/bucket -e DATABASE_URL="postgresql://cascadia:cascadia@db:5432/$DB" -e SPACES_LOCAL_DIR=/bucket \
  -e SPACES_KEY= -e SPACES_SECRET= -e SPACES_ENDPOINT= -e SPACES_URL= -e DJANGO_DEBUG=True -e DJANGO_SECRET_KEY=local-test \
  -e DJANGO_ALLOWED_HOSTS='*' -e PYTHONPATH=/ cascadia-web python manage.py runserver 0.0.0.0:8000 > /dev/null
PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(18))")
sleep 8
docker exec -e C2_PASSWORD="$PASSWORD" "$NAME" python manage.py shell -c "
import os
from django.contrib.auth.models import User
u, _ = User.objects.get_or_create(username='c2-test', defaults={'first_name': 'Test', 'last_name': 'C2'})
u.is_superuser = True; u.is_staff = True; u.set_password(os.environ['C2_PASSWORD']); u.save()" > /dev/null

echo "== 2. today's state, and today's data rebuilt once more with nothing changed (the control)"
script capture --db "$DB" --reference /reference --out /out/expected_today.json
build control1
build control2
script capture --db "$DB" --reference /reference --out /out/expected_rebuilt.json

echo "== 3. delete every track file, then rebuild twice"
script teardown --db "$DB"
build empty1
build empty2

echo "== 4. put every file back through the website"
script restore --db "$DB" --base "http://$NAME:8000" --expected /out/expected_today.json --out /out/restore_log.json
docker exec "$NAME" python manage.py create_blank_track_files | tail -1

echo "== 5. rebuild three times"
build after1
build after2
build final

echo "== 6. compare"
script compare --db "$DB" --expected /out/expected_today.json --baseline /out/expected_rebuilt.json --out /out/final_vs_today.json | tee "$OUT/report.txt"
echo "-- the last two builds, every dbo and app table (none may differ):"
sums --compare /out/sums_after2.json /out/sums_final.json || true
echo "-- the Audit Log, after each of the last three builds:"
cat "$OUT/auditsum_after1.txt" "$OUT/auditsum_after2.txt" "$OUT/auditsum_final.txt"
