#!/usr/bin/env bash
#
# Build Django/survey/data/land.twkb.gz, the land outline that
# `manage.py load_land` loads into the database.
#
#     ops/build-land.sh path/to/ne_10m_land.zip
#
# Natural Earth 1:10m land polygons, public domain (naturalearthdata.com).
# Download ne_10m_land.zip from
# https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip into an empty
# folder outside the repository. This script needs a local Postgres with
# PostGIS (shp2pgsql, psql) and Python; the server needs neither, because the
# file holds plain TWKB (PostGIS's compact binary form) that psycopg hands
# straight to PostGIS.
#
# Nothing is simplified. The only change is that coordinates are kept to 7
# decimal places of a degree (about 1 cm), the most TWKB allows, which makes
# the file about half the size. Each polygon is written as a 4-byte length and
# its TWKB, and the whole stream is gzipped.
set -euo pipefail
export MSYS_NO_PATHCONV=1
ZIP=${1:?usage: ops/build-land.sh ne_10m_land.zip}
PG_BIN=${PG_BIN:-}                 # folder holding psql and shp2pgsql, if not on PATH
PYTHON=${PYTHON:-python}        # a Python with psycopg installed
export PGHOST=${PGHOST:-localhost} PGPORT=${PGPORT:-5433} PGUSER=${PGUSER:-cascadia}
export PGPASSWORD=${PGPASSWORD:-cascadia}
DB=slot_land_build
cd "$(dirname "$0")/.."
OUT=Django/survey/data/land.twkb.gz   # relative, so Windows Pythons find it too
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

"$PYTHON" -I -m zipfile -e "$ZIP" "$WORK"
"${PG_BIN:+$PG_BIN/}psql" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1 \
    || "${PG_BIN:+$PG_BIN/}createdb" "$DB"
"${PG_BIN:+$PG_BIN/}psql" -q -d "$DB" -c "CREATE EXTENSION IF NOT EXISTS postgis" -c "DROP TABLE IF EXISTS ne_land"
"${PG_BIN:+$PG_BIN/}shp2pgsql" -s 4326 -g geom "$WORK"/ne_10m_land.shp public.ne_land | "${PG_BIN:+$PG_BIN/}psql" -q -d "$DB"

"$PYTHON" -I - "$OUT" <<'PY'
import gzip, os, struct, sys
import psycopg
with psycopg.connect(dbname="slot_land_build", host=os.environ["PGHOST"], port=os.environ["PGPORT"],
                     user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"]) as conn:
    rows = conn.execute("SELECT ST_AsTWKB((ST_Dump(geom)).geom, 7) FROM ne_land").fetchall()
with gzip.GzipFile(sys.argv[1], "wb", 9, mtime=0) as f:
    for (twkb,) in rows:
        twkb = bytes(twkb)
        f.write(struct.pack("<I", len(twkb)) + twkb)
print(f"{len(rows)} polygons, {os.path.getsize(sys.argv[1]):,} bytes")
PY
