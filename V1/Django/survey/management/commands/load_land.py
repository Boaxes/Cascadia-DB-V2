"""
Load the land outline the Sightings on Land filter uses.

    manage.py load_land

Natural Earth 1:10m land polygons (public domain), kept in
survey/data/land.twkb.gz. They go into two tables in the public schema, which
the nightly data rebuild leaves alone (it replaces only app and dbo):

    land_area   the land, cut along every whole degree of latitude and
                longitude, and the pieces split further where a cell is
                complicated. Each piece carries its cell number, so one
                position meets only the few pieces of its own cell. (A
                spatial index on the pieces was five times slower: the
                coast is ragged and their boxes overlap a great deal.)
    land_coast  the coastline, the same way, as geography so a distance in
                metres can be asked of it

The file's checksum is kept as a comment on land_area. Running this again with
the same file does nothing, so the deploy can run it every time.
"""

import gzip
import hashlib
import struct
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection, transaction

LAND_FILE = Path(__file__).resolve().parents[2] / "data" / "land.twkb.gz"

# Pieces of at most this many vertices. Small pieces keep each test cheap.
PIECE_VERTICES = 128

# A position's cell is floor(lon + 180) * 1000 + floor(lat + 90). The filter in
# survey/filters.py works it out the same way.


def checksum():
    return hashlib.sha256(LAND_FILE.read_bytes()).hexdigest()


def polygons():
    """Each polygon in the file, as TWKB bytes: a 4-byte length, then the bytes."""
    with gzip.open(LAND_FILE, "rb") as f:
        data = f.read()
    at = 0
    while at < len(data):
        (size,) = struct.unpack_from("<I", data, at)
        yield data[at + 4:at + 4 + size]
        at += 4 + size


class Command(BaseCommand):
    help = "Load the land polygons and coastline for the Sightings on Land filter."

    def handle(self, *args, **options):
        version = checksum()
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.land_area (
                    id serial PRIMARY KEY, cell integer NOT NULL, geom geometry(Polygon, 4326) NOT NULL);
                CREATE INDEX IF NOT EXISTS land_area_cell ON public.land_area (cell);
                CREATE TABLE IF NOT EXISTS public.land_coast (
                    id serial PRIMARY KEY, geom geography(LineString, 4326) NOT NULL);
                CREATE INDEX IF NOT EXISTS land_coast_geom ON public.land_coast USING gist (geom)""")
            cur.execute("""SELECT obj_description('public.land_area'::regclass, 'pg_class'),
                                  EXISTS (SELECT 1 FROM public.land_area),
                                  EXISTS (SELECT 1 FROM public.land_coast)""")
            loaded, has_area, has_coast = cur.fetchone()
            if loaded == version and has_area and has_coast:
                self.stdout.write("Land outline already loaded.")
                return

            cur.execute("TRUNCATE public.land_area, public.land_coast RESTART IDENTITY")
            cur.execute("CREATE TEMP TABLE land_source (twkb bytea) ON COMMIT DROP")
            with cur.copy("COPY land_source (twkb) FROM STDIN (FORMAT BINARY)") as copy:
                copy.set_types(["bytea"])
                for twkb in polygons():
                    copy.write_row((twkb,))
            cur.execute("""
                CREATE TEMP TABLE land_whole ON COMMIT DROP AS
                SELECT ST_SetSRID(ST_GeomFromTWKB(twkb), 4326) AS geom FROM land_source""")
            cur.execute("""
                CREATE TEMP TABLE land_pieces ON COMMIT DROP AS
                SELECT ST_Subdivide(geom, %s) AS geom FROM land_whole""", [PIECE_VERTICES])
            cur.execute("""
                INSERT INTO public.land_area (cell, geom)
                SELECT cell, geom FROM (
                    SELECT x * 1000 + y AS cell,
                           (ST_Dump(ST_ClipByBox2D(p.geom,
                                    ST_MakeEnvelope(x - 180, y - 90, x - 179, y - 89, 4326)))).geom AS geom
                    FROM land_pieces p,
                         LATERAL generate_series(floor(ST_XMin(p.geom) + 180)::int, floor(ST_XMax(p.geom) + 180)::int) x,
                         LATERAL generate_series(floor(ST_YMin(p.geom) + 90)::int, floor(ST_YMax(p.geom) + 90)::int) y
                ) clipped
                -- a piece that only touches the cell's edge clips to a line or a point
                WHERE ST_GeometryType(geom) = 'ST_Polygon' AND NOT ST_IsEmpty(geom)""")
            cur.execute("""
                INSERT INTO public.land_coast (geom)
                SELECT (ST_Dump(ST_Subdivide(ST_Boundary(geom), %s))).geom::geography FROM land_whole""",
                        [PIECE_VERTICES])
            cur.execute("COMMENT ON TABLE public.land_area IS %s", [version])
            cur.execute("ANALYZE public.land_area")
            cur.execute("ANALYZE public.land_coast")
            cur.execute("SELECT (SELECT count(*) FROM public.land_area), (SELECT count(*) FROM public.land_coast)")
            areas, coasts = cur.fetchone()
        self.stdout.write(f"Loaded land outline: {areas:,} land pieces, {coasts:,} coast pieces.")
