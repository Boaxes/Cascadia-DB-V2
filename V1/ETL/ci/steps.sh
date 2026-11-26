#!/usr/bin/env bash
#
# The steps of the automatic tests, one command each, so that the GitHub
# workflow (.github/workflows/tests.yml) and the local replay (ops/ci-local.sh)
# run exactly the same things.
#
#     ETL/ci/steps.sh <step>
#
#     unit        Django's unit tests (no database)
#     prepare     small set-up the other steps need (see below)
#     load        make the database `ci_reference` and put the seed in it
#     build       dbt deps, dbt build (with all its tests), built a second time
#                 and every table compared, then swapped in as dbo and app
#     trackfiles  the real GPS files in ETL/ci/track_files give, through the
#                 site's own cleaning, exactly the lines the seed stores
#     site        the site tests in TESTS/, on a fresh copy of ci_reference
#                 (site <labels> runs only those, e.g. TESTS.test_filters)
#     replay      ETL/verify/applied_entries_replay.sh, on a copy
#     edits       ETL/verify/website_edits_survive.py, on a copy
#
# Needs a PostgreSQL with PostGIS reachable by the usual PG* variables (default
# localhost:5432, user and password cascadia), Python with the three
# requirements files installed, GDAL's libraries, and psql.
#
# The database. The seed (ETL/ci/seed.sql.gz) holds raw, the website's audit
# log, track lines and vessel numbers, and Django's login tables, with made-up
# users (see ops/build-ci-seed.sh). dbo and app are not in it: `build` makes
# them, as the live site does, so the tests always run against what the current
# pipeline produces. The order of the checks therefore differs a little from a
# list that puts the site tests first: the database has to be built before the
# site tests have anything to read.
#
# What `prepare` does: lets the name `db` reach the database (ETL/verify/checksums.py
# connects to host `db`), and makes /verify point at ETL/verify (the script
# website_edits_survive.py writes its notes to /verify/reports).
# WARNING: the seed holds a superuser with a known throwaway password. Never load
# it into a live or shared database; these steps only make and drop their own.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$PWD

: "${PGHOST:=localhost}" "${PGPORT:=5432}" "${PGUSER:=cascadia}" "${PGPASSWORD:=cascadia}"
export PGHOST PGPORT PGUSER PGPASSWORD
BUILD_DB=${CI_BUILD_DB:-ci_reference}
REPORTS=ETL/verify/reports
mkdir -p "$REPORTS"

# Settings Django needs. Nothing here is a secret: the key only signs cookies
# of a database that is thrown away.
export DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY:-ci-only-not-a-secret}
# As in the local .env (.env.example): static files under their plain names, as
# the site tests expect them. The live site hashes them (collectstatic).
export DJANGO_DEBUG=${DJANGO_DEBUG:-True}
export DATABASE_URL="postgresql://$PGUSER:$PGPASSWORD@$PGHOST:$PGPORT/cascadia"
export REFERENCE_DB="$BUILD_DB"
export PYTHONPATH="$ROOT:$ROOT/ETL/ci${PYTHONPATH:+:$PYTHONPATH}"

step() { echo; echo "== $*"; }
sql()  { local db=$1; shift; psql -d "$db" -v ON_ERROR_STOP=1 -q "$@"; }
dbt_() { local db=$1; shift; (cd ETL/dbt && PGDATABASE="$db" dbt "$@" --profiles-dir .); }
copy_of() {   # copy_of <new name>: a fresh copy of the built database
    sql postgres -c "drop database if exists $1 with (force)" -c "create database $1 template $BUILD_DB"
}

prepare() {
    local sudo_=""
    [ "$(id -u)" = 0 ] || sudo_=sudo
    if ! getent hosts db >/dev/null 2>&1; then
        echo "127.0.0.1 db" | $sudo_ tee -a /etc/hosts >/dev/null
    fi
    if [ ! -e /verify ]; then
        $sudo_ ln -s "$ROOT/ETL/verify" /verify
    fi
}

unit() {
    (cd Django && python manage.py test unit_tests --settings=config.unit_settings)
}

load() {
    step "making $BUILD_DB and loading the seed"
    sql postgres -c "drop database if exists $BUILD_DB with (force)" -c "create database $BUILD_DB"
    sql "$BUILD_DB" -c "create extension if not exists postgis" -c "create schema if not exists app"
    gzip -dc ETL/ci/seed.sql.gz | sql "$BUILD_DB"
    sql "$BUILD_DB" -tA -c "select 'raw.SightingT ' || count(*) from raw.\"SightingT\"" \
                         -c "select 'app.audit_log ' || count(*) from app.audit_log" \
                         -c "select 'auth_user ' || count(*) from auth_user"
    # The made-up superuser (ci_admin) logs in with a throwaway password that
    # guards nothing: CI-b7f3Qm9xKd2LpR4v. Prove the seed's hash is that password.
    local hash
    hash=$(psql -d "$BUILD_DB" -tAc "select password from auth_user where username = 'ci_admin'")
    python - "$hash" <<'PY'
import sys
from django.conf import settings
settings.configure()
from django.contrib.auth.hashers import check_password
assert check_password("CI-b7f3Qm9xKd2LpR4v", sys.argv[1]), "the seed's ci_admin hash is not the throwaway password"
print("ci_admin's password hash matches the throwaway password")
PY
}

build() {
    step "dbt deps"
    dbt_ "$BUILD_DB" deps
    step "dbt build (models and all their tests), first time"
    dbt_ "$BUILD_DB" build --exclude package:elementary | tee "$REPORTS/build_1.log" | tail -25
    python ETL/verify/checksums.py --db "$BUILD_DB" --out "$REPORTS/checksums_1.json"
    step "dbt build, second time, and every table compared"
    dbt_ "$BUILD_DB" build --exclude package:elementary | tee "$REPORTS/build_2.log" | tail -3
    python ETL/verify/checksums.py --db "$BUILD_DB" --out "$REPORTS/checksums_2.json"
    python ETL/verify/checksums.py --compare "$REPORTS/checksums_1.json" "$REPORTS/checksums_2.json"
    step "swap the build in as dbo and app"
    dbt_ "$BUILD_DB" run-operation swap | tail -3
}

trackfiles() {
    step "the track files in ETL/ci/track_files give the lines stored in the seed"
    (cd Django && DATABASE_URL="postgresql://$PGUSER:$PGPASSWORD@$PGHOST:$PGPORT/$BUILD_DB" \
        SPACES_LOCAL_DIR="$ROOT/ETL/ci/track_files" python manage.py shell -c "
from django.db import connection
from datahealth.gps import tracks
def stored():
    with connection.cursor() as cur:
        cur.execute(\"\"\"SELECT md5(string_agg(concat_ws('|', object_key, point_count, length_nm,
                              encode(ST_AsEWKB(geom), 'hex')), ',' ORDER BY object_key))
                       FROM app.track_geometry\"\"\")
        return cur.fetchone()[0]
before = stored()
# The seed's rows were made before a track's first and last time were kept; this
# fills those, and must change no line.
out = tracks.regenerate(report=lambda *a, **k: None)
print({k: len(v) for k, v in out.items()})
assert not out['not_in_bucket'] and not out['added'], out
assert stored() == before, 'the stored lines differ from what the files give'
again = tracks.regenerate(dry_run=True, report=lambda *a, **k: None)
assert again['unchanged'] and not again['changed'] and not again['added'] and not again['not_in_bucket'], again
print('every stored line is what its file gives')
")
}

site() {   # site [test label ...]: the whole of TESTS/ unless some are named
    step "the site tests in TESTS/ (a fresh copy of $BUILD_DB per run)"
    (cd Django && python manage.py test "${@:-TESTS}" --testrunner=ci_runner.CiRunner --noinput)
}

replay() {
    step "applied entries are not replayed, over three builds"
    copy_of ci_replay
    PATH="$ROOT/ETL/ci/bin:$PATH" ETL/verify/applied_entries_replay.sh ci_replay
}

edits() {
    step "edits made on the website survive a rebuild"
    copy_of ci_edits
    local env_=(DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY" DATABASE_URL="postgresql://$PGUSER:$PGPASSWORD@$PGHOST:$PGPORT/ci_edits")
    (cd Django && env "${env_[@]}" PHASE=make python manage.py shell -c "exec(open('/verify/website_edits_survive.py').read())")
    dbt_ ci_edits build --exclude package:elementary > "$REPORTS/edits_build.log"
    tail -1 "$REPORTS/edits_build.log"
    dbt_ ci_edits run-operation swap | tail -1
    (cd Django && env "${env_[@]}" PHASE=check python manage.py shell -c "exec(open('/verify/website_edits_survive.py').read())")
}

case "${1:-}" in
    unit|prepare|load|build|trackfiles|site|replay|edits) "$@" ;;
    *) sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
