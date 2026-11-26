#!/usr/bin/env bash
#
# Run the automatic tests (.github/workflows/tests.yml) on this Mac, in a clean
# throwaway environment, so a change can be proven without pushing it.
#
#     ops/ci-local.sh                 all steps, in the workflow's order
#     ops/ci-local.sh unit site       only these steps (they still need `load` and `build` before them
#                                     in a fresh environment: unit is the only one that does not)
#
# What it makes, and removes again at the end:
#   - a Docker network and a PostGIS database container (the same image the
#     workflow uses). Nothing from this Mac's other databases is in it: it
#     starts empty and gets only ETL/ci/seed.sql.gz.
#   - a Python container with Python 3.13, GDAL, psql and the three
#     requirements files installed, holding a copy of this working folder
#     (so uncommitted changes are tested too; .git is left out).
# It never touches the other containers or databases.
#
# The steps themselves are ETL/ci/steps.sh, which the workflow calls too. What
# differs from GitHub is only the machinery around them (a container instead
# of a runner, apt and pip here and in the workflow's install steps).
#
# The seed's made-up superuser is ci_admin, with the throwaway password
# CI-b7f3Qm9xKd2LpR4v (it guards nothing; the database is thrown away).
#
# CI_LOCAL_KEEP=1   leave the containers running afterwards (to look around:
#                   docker exec -it cascadia-ci-local-py bash)
# CI_LOCAL_REUSE=1  use the containers a CI_LOCAL_KEEP=1 run left, instead of
#                   making new ones (the installs are not repeated)
#
# Prints a line per step and a summary; exits 1 if any step failed. A failed
# step does not stop the later ones that can still run, so one run shows
# everything that is wrong.
set -uo pipefail
cd "$(dirname "$0")/.."

NET=cascadia-ci-local-net
DB=cascadia-ci-local-db
PY=cascadia-ci-local-py
POSTGIS_IMAGE=imresamu/postgis:18-3.6
PYTHON_IMAGE=python:3.13-slim
LOGS=${CI_LOCAL_LOGS:-$PWD/ETL/verify/reports/ci-local}
mkdir -p "$LOGS"

cleanup() {
    [ "${CI_LOCAL_KEEP:-}" = 1 ] && { echo "Leaving $DB and $PY running (CI_LOCAL_KEEP=1)."; return; }
    docker rm -f "$PY" "$DB" >/dev/null 2>&1
    docker network rm "$NET" >/dev/null 2>&1
}
trap cleanup EXIT

copy_in() {
    echo "== copying the working folder into the Python container (uncommitted changes included)"
    # The packages dbt downloaded stay; everything else is replaced.
    docker exec "$PY" sh -c 'rm -rf /work/.keep; mkdir -p /work/.keep
        [ -d /work/ETL/dbt/dbt_packages ] && mv /work/ETL/dbt/dbt_packages /work/.keep/
        rm -rf /work/ETL /work/Django /work/TESTS /work/ops'
    COPYFILE_DISABLE=1 tar -c --exclude=.git --exclude=.claude --exclude=__pycache__ --exclude=ETL/dbt/target \
        --exclude=ETL/dbt/dbt_packages --exclude=ETL/dbt/logs --exclude=ETL/verify/reports --exclude=ETL/site \
        --exclude=staticfiles . \
        | docker exec -i "$PY" sh -c 'mkdir -p /work && tar -x --warning=no-unknown-keyword -C /work' || exit 1
    docker exec "$PY" sh -c '[ -d /work/.keep/dbt_packages ] && mv /work/.keep/dbt_packages /work/ETL/dbt/; rm -rf /work/.keep; true'
}

if [ "${CI_LOCAL_REUSE:-}" != 1 ]; then
    docker rm -f "$PY" "$DB" >/dev/null 2>&1
    docker network rm "$NET" >/dev/null 2>&1
    docker network create "$NET" >/dev/null || exit 1
    echo "== starting a throwaway PostGIS database ($POSTGIS_IMAGE)"
    docker run -d --name "$DB" --network "$NET" --network-alias db \
        -e POSTGRES_USER=cascadia -e POSTGRES_PASSWORD=cascadia -e POSTGRES_DB=cascadia \
        "$POSTGIS_IMAGE" >/dev/null || exit 1
    for i in $(seq 1 60); do
        docker exec "$DB" pg_isready -U cascadia -d cascadia >/dev/null 2>&1 && break
        sleep 2
    done
    echo "== starting the Python container"
    docker run -d --name "$PY" --network "$NET" -e PGHOST=db "$PYTHON_IMAGE" sleep infinity >/dev/null || exit 1
    copy_in
    echo "== installing the system packages and the Python requirements (the workflow's install steps)"
    docker exec "$PY" sh -c '
        set -e
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq --no-install-recommends gdal-bin libgdal-dev postgresql-client >/dev/null
        cd /work
        pip install -q --no-cache-dir -r Django/requirements.txt -r Django/requirements-dev.txt -r ETL/requirements.txt
    ' || { echo "install failed"; exit 1; }
else
    copy_in
fi


# Steps that were asked for, in the workflow's order.
ALL="unit prepare load build trackfiles site replay edits"
WANT=${*:-$ALL}
failed=()
summary=()
for s in $ALL; do
    case " $WANT " in *" $s "*) ;; *) continue ;; esac
    echo; echo "######## $s"
    start=$(date +%s)
    docker exec -e PGHOST=db -w /work "$PY" ETL/ci/steps.sh "$s" > "$LOGS/$s.log" 2>&1
    code=$?
    took=$(( $(date +%s) - start ))
    tail -15 "$LOGS/$s.log"
    if [ $code -eq 0 ]; then summary+=("PASS  $s (${took}s)"); else summary+=("FAIL  $s (${took}s, exit $code)"); failed+=("$s"); fi
done

echo; echo "######## summary (full logs in $LOGS)"
printf '%s\n' "${summary[@]}"
[ ${#failed[@]} -eq 0 ]
