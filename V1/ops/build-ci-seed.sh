#!/usr/bin/env bash
#
# Build the small, scrubbed database that the automatic tests on GitHub run
# against (ETL/ci/seed.sql.gz), and the real track files that go with it
# (ETL/ci/track_files/).
#
#     ops/build-ci-seed.sh [source_database]     # default test_review
#
# Why it exists: the tests need data, and the real data lives only on the
# user's Mac and on the server. GitHub gets a small piece of it instead: a
# coherent cut of the real records, with every name and login removed.
#
# What it does, in order:
#   1. copies the source's raw schema, the three tables the build keeps from
#      one run to the next (app.audit_log, app.track_geometry,
#      app.vessel_number) and Django's login tables into a scratch database
#   2. cuts the records down (ETL/ci/seed_subset.sql): CRC's three most recent
#      years, a little of two other groups, every Effort that has several
#      tracks, and every record the website's edits and the pipeline's
#      corrections refer to, so nothing is left pointing at a record that was
#      cut; the lookups that hold people's names are cut to what is used
#   3. removes every personal detail (ETL/ci/seed_scrub.sql) and puts in three
#      made-up users. In short: the columns that hold a person (photographers,
#      who sampled, crew, observers, photo data entry) become tokens such as
#      "Observer 12"; every word taken from them (names, initials) is replaced
#      wherever else it appears (photo file names, permits, comments); in the
#      free-text columns any word that is not an ordinary dictionary word or one
#      the data's own vocabularies use is replaced (so a name that only a
#      comment mentions goes too); emails, web addresses and phone numbers go;
#      the website's audit log entries are re-attributed to "CI Admin" and
#      "CI Editor"; users, sessions and the admin log are replaced by the three
#      made-up users.
#   4. checks the result (ETL/ci/seed_checks.sql): no orphans, no names, no
#      emails; the script stops if any check fails
#   5. writes the compressed dump and copies the real track files
#   6. drops the scratch database
#
# The source database is only read. dbo, app (the views) and build are not
# copied: the tests build them from raw with dbt, as the live site does.
#
# The made-up users (they exist only in this seed and in CI):
#   ci_admin    superuser   password CI-b7f3Qm9xKd2LpR4v   (a throwaway; it guards nothing)
#   ci_editor   staff       no usable password
#   ci_viewer   plain user  no usable password
# The password is also written in the comments of .github/workflows/tests.yml,
# ops/ci-local.sh and ETL/ci/steps.sh, which checks the seed's hash matches it.
#
# Needs the local database container (docker compose up -d db), python3 on the
# Mac, the system dictionary (/usr/share/dict/words and propernames), and the
# local copy of the GPS bucket (TRACK_FILES_FROM, default the
# track_files_reference folder beside the repository's .git).
#
# Run it again whenever the source data or the cut should change, and commit
# ETL/ci/seed.sql.gz and ETL/ci/track_files/ with the new numbers.
set -euo pipefail
cd "$(dirname "$0")/.."

SOURCE=${1:-test_review}
CONTAINER=${CI_SEED_DB_CONTAINER:-cascadia-db-1}
WORK=ci_seed_work
TRACK_FILES_FROM=${TRACK_FILES_FROM:-$(git rev-parse --path-format=absolute --git-common-dir)/../track_files_reference}
ADMIN_PASSWORD='CI-b7f3Qm9xKd2LpR4v'
STOP_AFTER=${CI_SEED_STOP_AFTER:-}
S_TMP=$(mktemp -u "${TMPDIR:-/tmp}/ci-seed.XXXXXX")      # subset | scrub: leave the scratch database for a look

db()  { docker exec -i "$CONTAINER" psql -U cascadia -d "$1" -v ON_ERROR_STOP=1 -q -X "${@:2}"; }
step() { echo; echo "== $*"; }

[ -d "$TRACK_FILES_FROM/files" ] || { echo "No track files at $TRACK_FILES_FROM/files (set TRACK_FILES_FROM)."; exit 1; }
db postgres -tAc "select 1 from pg_database where datname = '$SOURCE'" | grep -q 1 || { echo "No database $SOURCE."; exit 1; }
case "$SOURCE" in reference|test_today|test_last) echo "Refusing to read $SOURCE: use a copy such as test_review."; exit 1;; esac

step "1. copying $SOURCE's raw schema, persistent tables and login tables into $WORK"
db postgres -c "drop database if exists $WORK" -c "create database $WORK"
db "$WORK" -c "create extension postgis" -c "create schema app" -c "create schema ci"
docker exec "$CONTAINER" sh -c "pg_dump -U cascadia -d '$SOURCE' --no-owner --no-privileges -n raw | psql -U cascadia -d $WORK -q -v ON_ERROR_STOP=1 >/dev/null"
docker exec "$CONTAINER" sh -c "pg_dump -U cascadia -d '$SOURCE' --no-owner --no-privileges \
    -t app.audit_log -t app.track_geometry -t app.vessel_number \
    -t public.auth_group -t public.auth_group_permissions -t public.auth_permission -t public.auth_user \
    -t public.auth_user_groups -t public.auth_user_user_permissions -t public.django_admin_log \
    -t public.django_content_type -t public.django_migrations -t public.django_session \
    | psql -U cascadia -d $WORK -q -v ON_ERROR_STOP=1 >/dev/null"

step "2. cutting the records down"
db "$WORK" -c "create table ci.fixes (table_name text, legacy_id text, record_date text, column_name text, old_value text, new_value text, rule text, reason text)" \
           -c "create table ci.removed (removed_effort integer, kept_effort integer, reason text)" \
           -c "create table ci.multi (effort integer, tracks integer)" \
           -c "create table ci.file_size (name text primary key, bytes bigint)" \
           -c "create table ci.pick_efforts (id integer primary key)"
# The source's dbo gives the order the site tests rely on (see seed_subset.sql).
db "$SOURCE" -tA -c "select e.\"DailyEffortID\" from dbo.\"DailyEffortT\" e
    where e.id in (select daily_effort_id from dbo.\"TrackT\" where daily_effort_id is not null group by 1 having count(*) = 1)
    order by e.id limit 3" | db "$WORK" -c "\copy ci.pick_efforts from stdin"
db "$WORK" -c "\copy ci.fixes from stdin csv header" < ETL/dbt/seeds/record_fixes.csv
db "$WORK" -c "\copy ci.removed from stdin csv header" < ETL/dbt/seeds/removed_efforts.csv
db "$WORK" -c "\copy ci.multi from stdin csv header" < ETL/dbt/seeds/multi_track_efforts.csv
python3 -I - "$TRACK_FILES_FROM/files" <<'PY' | db "$WORK" -c "\copy ci.file_size from stdin csv"
import csv, os, sys
w = csv.writer(sys.stdout)
for e in sorted(os.scandir(sys.argv[1]), key=lambda e: e.name):
    if e.is_file():
        w.writerow([e.name, e.stat().st_size])
PY
db "$WORK" < ETL/ci/seed_subset.sql
[ "$STOP_AFTER" = subset ] && { echo "stopped after the cut; look in $WORK"; exit 0; }

step "3. removing every personal detail"
# The words an ordinary comment may use: the system dictionary, less first names.
DICT=/usr/share/dict/words; NAMES=/usr/share/dict/propernames
[ -r "$DICT" ] && [ -r "$NAMES" ] || { echo "Needs $DICT and $NAMES (macOS has them)."; exit 1; }
db "$WORK" -c "create table ci.dict (w text primary key)" -c "create table ci.column_kinds (table_name text, column_name text, kind text, vocabulary text)"
tr 'A-Z' 'a-z' < "$DICT" | sort -u > "$S_TMP.dict"
tr 'A-Z' 'a-z' < "$NAMES" | sort -u > "$S_TMP.names"
comm -23 "$S_TMP.dict" "$S_TMP.names" | db "$WORK" -c "\copy ci.dict from stdin"
rm -f "$S_TMP.dict" "$S_TMP.names"
db "$WORK" -c "\copy ci.column_kinds from stdin csv header" < ETL/dbt/seeds/column_kinds.csv
ADMIN_HASH=$(python3 -I - "$ADMIN_PASSWORD" <<'PY'
# Django's own format, pbkdf2_sha256$iterations$salt$hash, so no Django is needed here.
import base64, hashlib, secrets, sys
iterations = 1_000_000
salt = secrets.token_hex(8)
digest = base64.b64encode(hashlib.pbkdf2_hmac("sha256", sys.argv[1].encode(), salt.encode(), iterations)).decode()
print(f"pbkdf2_sha256${iterations}${salt}${digest}")
PY
)
db "$WORK" -v "admin_hash=$ADMIN_HASH" < ETL/ci/seed_scrub.sql
[ "$STOP_AFTER" = scrub ] && { echo "stopped after the scrub; look in $WORK"; exit 0; }

step "4. checking the result"
db "$WORK" < ETL/ci/seed_checks.sql

step "5. writing ETL/ci/seed.sql.gz and the track files"
db "$WORK" -c "set client_min_messages = warning" -c "drop schema ci cascade" -c "vacuum full analyze" >/dev/null
mkdir -p ETL/ci/track_files
rm -f ETL/ci/track_files/*
# Two dumps in one file: all of raw, then the named tables (pg_dump -n with -t
# would give only the tables that are in both).
{
    docker exec "$CONTAINER" pg_dump -U cascadia -d "$WORK" --no-owner --no-privileges --no-comments -n raw
    docker exec "$CONTAINER" pg_dump -U cascadia -d "$WORK" --no-owner --no-privileges --no-comments \
        -t app.audit_log -t app.track_geometry -t app.vessel_number \
        -t public.auth_group -t public.auth_group_permissions -t public.auth_permission -t public.auth_user \
        -t public.auth_user_groups -t public.auth_user_user_permissions -t public.django_admin_log \
        -t public.django_content_type -t public.django_migrations -t public.django_session
} | sed '/^\\restrict /d;/^\\unrestrict /d' | gzip -9n > ETL/ci/seed.sql.gz
db "$WORK" -tAc "select object_key from app.track_geometry order by 1" | while IFS= read -r name; do
    cp "$TRACK_FILES_FROM/files/$name" "ETL/ci/track_files/$name"; chmod 644 "ETL/ci/track_files/$name"
done
ls -l ETL/ci/seed.sql.gz
echo "$(ls ETL/ci/track_files | wc -l | tr -d ' ') track files, $(du -sk ETL/ci/track_files | cut -f1) KB"

step "6. dropping $WORK"
db postgres -c "drop database $WORK"
echo "done"
