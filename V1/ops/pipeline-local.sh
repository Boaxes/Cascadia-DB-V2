#!/usr/bin/env bash
#
# A whole run of the daily pipeline against a local database, with the same
# steps as .github/workflows/pipeline.yml (both call ops/pipeline-steps.sh):
# copy DB167 in, check whether this is the first run, build, test, publish,
# then the documentation, Elementary's report and the report's web site. It
# then serves the web site with Cloudflare Pages' own runtime.
#
#     ops/pipeline-local.sh DATABASE [options]
#
#     --from SOURCE      first make DATABASE as a copy of SOURCE (a database name in the local Postgres)
#     --no-publish       build and test, but leave the website on the current data
#     --db167 NAME       the local SQL Server's copy of DB167 to import (default DB167_Today)
#     --check            serve the web site, check it answers, and stop
#     --no-serve         make the web site and stop
#
# It writes to DATABASE and to the local SQL Server's copy only by reading it. The
# SQL Server password is read from ENV_FILE (default .env) and never shown.
# Names that hold other people's work are refused.
set -euo pipefail
cd "$(dirname "$0")/.."

DB=${1:?usage: ops/pipeline-local.sh DATABASE [--from SOURCE] [--no-publish] [--db167 NAME] [--check|--no-serve]}
shift
SOURCE=""
export PUBLISH=true
DB167=DB167_Today
MODE=serve
while [ $# -gt 0 ]; do
    case "$1" in
        --from) SOURCE=$2; shift 2 ;;
        --no-publish) PUBLISH=false; shift ;;
        --db167) DB167=$2; shift 2 ;;
        --check) MODE=check; shift ;;
        --no-serve) MODE=none; shift ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
done

case "$DB" in
    postgres|template0|template1|cascadia|pipeline|reference|test_today|test_last|test_review)
        echo "$DB holds other work and is not touched." >&2; exit 2 ;;
esac
case "$DB" in test_*|scratch*) ;; *) echo "The database name has to start with test_." >&2; exit 2 ;; esac

step() { echo; echo "== $*"; }
db() { docker exec cascadia-db-1 psql -U cascadia -d postgres -v ON_ERROR_STOP=1 -q "$@"; }

if [ -n "$SOURCE" ]; then
    step "making $DB from $SOURCE"
    db -c "drop database if exists $DB" -c "create database $DB"
    docker exec cascadia-db-1 pg_dump -U cascadia -Fc -f "/tmp/$DB.dump" "$SOURCE"
    docker exec cascadia-db-1 pg_restore -U cascadia -d "$DB" --no-owner "/tmp/$DB.dump"
    docker exec cascadia-db-1 rm -f "/tmp/$DB.dump"
fi

ROOT=$PWD
# The same exact version as ops/pipeline-steps.sh.
WRANGLER=wrangler@4.146.0
ENV_FILE=${ENV_FILE:-.env}
[ -f "$ENV_FILE" ] || { echo "$ENV_FILE is not there; it holds MSSQL_SA_PASSWORD for the local SQL Server." >&2; exit 1; }
MSSQL_SA_PASSWORD=$(sed -n 's/^MSSQL_SA_PASSWORD=//p' "$ENV_FILE")
export DB167_ODBC="DRIVER={ODBC Driver 18 for SQL Server};SERVER=mssql,1433;DATABASE=$DB167;UID=sa;PWD=$MSSQL_SA_PASSWORD;Encrypt=yes;TrustServerCertificate=yes"
export PIPELINE_DATABASE_URL="postgresql://cascadia:cascadia@db:5432/$DB"
PIPELINE_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo local)
export PIPELINE_COMMIT
export JOB_STATUS=success

# The same steps, in the etl image: it has the SQL Server driver, dbt and Elementary.
steps() {
    docker run --rm --network cascadia_default -v "$PWD:/repo" -w /repo -e HOME=/tmp \
        -e PIPELINE_DATABASE_URL -e DB167_ODBC -e PUBLISH -e PIPELINE_COMMIT -e JOB_STATUS -e GITHUB_EVENT_NAME \
        --entrypoint bash cascadia-etl ops/pipeline-steps.sh "$@"
}

OK=true
steps begin
steps deps || OK=false
for name in check elementary-models import detect cutover build publish; do
    if [ "$OK" = true ]; then steps "$name" || OK=false; fi
done
# As in the workflow, these run even after a failure, so the report says what happened.
[ "$OK" = true ] || JOB_STATUS=failure
for name in docs elementary-report record site; do steps "$name" || true; done
rm -rf ETL/dbt/edr_target 2>/dev/null || true

echo
if [ "$OK" = true ]; then echo "The run finished."; else echo "The run FAILED; its report says where."; fi

case "$MODE" in
    none) ;;
    check)
        step "serving ETL/site with wrangler pages dev, and checking it answers"
        (cd ETL/site && exec npx --yes "$WRANGLER" pages dev . --port 8788 > "$ROOT/ETL/run/wrangler.log" 2>&1) &
        echo $! > ETL/run/wrangler.pid
        for _ in $(seq 1 60); do
            curl -s -o /dev/null http://localhost:8788/ && break
            sleep 1
        done
        for path in / /elementary/ /docs/; do
            echo "$path -> $(curl -s -o /dev/null -w '%{http_code}' "http://localhost:8788$path")"
        done
        curl -s http://localhost:8788/ | sed -n 's/.*<div class="banner \([a-z]*\)"><strong>\([^<]*\)<.*/banner: \1, \2/p'
        curl -sI http://localhost:8788/ | grep -i '^x-robots-tag' || true
        kill "$(cat ETL/run/wrangler.pid)" 2>/dev/null || true
        pkill -f "pages dev . --port 8788" 2>/dev/null || true
        ;;
    serve)
        step "serving ETL/site at http://localhost:8788 (Ctrl-C to stop)"
        cd ETL/site && exec npx --yes "$WRANGLER" pages dev . --port 8788
        ;;
esac
[ "$OK" = true ]
