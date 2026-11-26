"""
Build `dbo` from `raw`.

`dbo` is the live operational schema, and it holds every research group's data,
not just CRC's -- that filter belongs in the app views, not here. This phase
adds structure only: foreign keys DB167 never declared, and a small number of
columns the app needs that have no source in DB167 at all. No value from `raw`
changes.

    python build_dbo.py --schema     write ETL/schema/dbo.sql
    python build_dbo.py              create dbo, copy raw -> dbo, add structure
    python build_dbo.py --verify     run the gate
"""

import argparse
import os
import sys

import psycopg
from dotenv import load_dotenv

SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "schema", "dbo.sql")

VIEWS = ["DailyEffortV", "SightingV", "SightingEffortTrackV", "TrackV",
         "TagSummaryV", "IdentificationsBySightingV", "SpeciesSummaryByEffortV"]

TABLES = [
    "AdditionalCameraT", "CollaboratorT", "CRC_Vessels_ByYear_T",
    "DailyConditionT", "DailyEffortT", "DailyEventT", "DataStatusT",
    "DataStatusTypeT", "DroneDeploymentT", "DroneTargetAnimalT",
    "EffortCrewT", "EffortProblemT", "EventCodeT", "IdentificationT", "IndividualT",
    "OtherSpeciesT", "PermitTakeT", "ResearchGroupT",
    "SampleIdentificationT", "SampleT", "ServerSystemT", "SightingEventT",
    "SightingFollowT", "SightingIdentificationT", "SightingT", "SourceT",
    "TagSummaryT", "TrackCompleteCodeT", "TrackFileList", "TrackFolderT",
    "TrackingT", "TrackT", "UserT", "VesselT",
]

# child table, child column, parent table, parent column, valid.
# DB167 declares no foreign keys at all; every one of these is inferred by
# matching an int column's name to another table's primary key, then checked
# row by row against the live data.
FOREIGN_KEYS = [
    ("AdditionalCameraT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("AdditionalCameraT", "ResearchGroupID", "ResearchGroupT", "ResearchGroupID", True),
    ("AdditionalCameraT", "VesselID", "VesselT", "VesselID", True),
    ("AdditionalCameraT", "SightingID", "SightingT", "SightingID", True),
    ("DailyConditionT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("DailyEventT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("DataStatusT", "DataStatusTypeID", "DataStatusTypeT", "DataStatusTypeID", True),
    ("DroneDeploymentT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("DroneTargetAnimalT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("DroneTargetAnimalT", "DroneEventID", "DroneDeploymentT", "DroneEventID", True),
    ("EffortCrewT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("IdentificationT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("IdentificationT", "SightingID", "SightingT", "SightingID", True),
    ("IdentificationT", "IndividualID", "IndividualT", "IndividualID", True),
    ("OtherSpeciesT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("PermitTakeT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("SampleIdentificationT", "SightingID", "SightingT", "SightingID", True),
    ("SampleIdentificationT", "IdentificationID", "IdentificationT", "IdentificationID", True),
    ("SampleIdentificationT", "IndividualID", "IndividualT", "IndividualID", True),
    ("SampleT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("SampleT", "SightingID", "SightingT", "SightingID", True),
    ("SampleT", "SightingEventID", "SightingEventT", "SightingEventID", True),
    ("SampleT", "IndividualID", "IndividualT", "IndividualID", True),
    ("SightingEventT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("SightingFollowT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("SightingIdentificationT", "IndividualID", "IndividualT", "IndividualID", True),
    ("SightingIdentificationT", "SightingID", "SightingT", "SightingID", True),
    ("SightingIdentificationT", "IdentificationID", "IdentificationT", "IdentificationID", True),
    ("SightingT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("TagSummaryT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("TrackingT", "DailyEffortID", "DailyEffortT", "DailyEffortID", True),
    ("TrackT", "ResearchGroupID", "ResearchGroupT", "ResearchGroupID", True),
    ("TrackT", "TrackCompleteCodeID", "TrackCompleteCodeT", "TrackCompleteCodeID", True),
    ("TrackT", "VesselID", "VesselT", "VesselID", True),
    ("TrackT", "SourceID", "SourceT", "SourceID", True),
    ("TrackT", "EffortID", "DailyEffortT", "DailyEffortID", True),
    ("VesselT", "ResearchGroupID", "ResearchGroupT", "ResearchGroupID", True),
    ("VesselT", "CollaboratorID", "CollaboratorT", "CollaboratorID", True),
]

# sighting_id: SightingEventT and OtherSpeciesT have no SightingID column, only
# DailyEffortID plus the natural key (Research Group, Vessel, Date, Sighting) --
# the same key DB167's own SightingV joins on. Matched on (DailyEffortID,
# Sighting), kept only where exactly one SightingID matches, NULL otherwise.
SIGHTING_LINKS = ["SightingEventT", "OtherSpeciesT"]

# DB167's own indexes, carried across unchanged -- each was a decision made
# against real Access query patterns. IX_SampleT (on SampleID alone) is left
# out: SampleID is already SampleT's primary key.
DB167_INDEXES = [
    ("DailyEffortT", ["Date"]),
    ("DailyEffortT", ["Research Group"]),
    ("DailyEffortT", ["Vessel"]),
    ("DailyEffortT", ["Research Group", "Date", "Vessel"]),
    ("DroneTargetAnimalT", ["DroneEventID"]),
    ("IdentificationT", ["Research Group", "Date", "Vessel", "Sighting"]),
    ("IdentificationT", ["SightingID", "CRC ID"]),
    ("SampleT", ["Date"]),
    ("SampleT", ["Research Group"]),
    ("SampleT", ["Sighting"]),
    ("SampleT", ["Vessel"]),
    ("SightingT", ["Date", "RG_hash", "Vessel_hash", "Sighting_hash"]),
    ("SightingT", ["Research Group", "Date", "Vessel", "Sighting"]),
    ("SightingT", ["Date"]),
    ("SightingT", ["Research Group"]),
    ("SightingT", ["Sighting"]),
    ("SightingT", ["Vessel"]),
]


def ident(name):
    return '"' + name.replace('"', '""') + '"'


def fk_name(table, column):
    return "fk_" + (table + "_" + column).lower().replace(" ", "_").replace("#", "num")


def ix_name(table, columns):
    return "ix_" + "_".join([table] + columns).lower().replace(" ", "_").replace("#", "num")


def build_schema():
    out = [
        "-- Generated by ETL/build_dbo.py --schema. Do not edit by hand.",
        "--",
        "-- Every table is raw's structure (LIKE ... INCLUDING ALL, so the",
        "-- primary key comes with it), plus the foreign keys DB167 never",
        "-- declared and the few columns the app needs that DB167 has no room",
        "-- for. No value from raw changes, and no row is filtered out --",
        "-- CRC-only is a view concern (Phase 4), not a dbo concern.",
        "",
        "CREATE EXTENSION IF NOT EXISTS postgis;",
        "CREATE SCHEMA dbo;",
        "",
    ]
    for table in TABLES:
        out.append(f"CREATE TABLE dbo.{ident(table)} (LIKE raw.{ident(table)} INCLUDING ALL);")
    out.append("")

    out += [
        "-- Columns this phase adds.",
        'ALTER TABLE dbo."SightingT"',
        "    ADD COLUMN identified_individual_count integer NOT NULL DEFAULT 0,",
        "    ADD COLUMN geom geometry(Point, 4326),",
        "    ADD COLUMN end_geom geometry(Point, 4326);",
    ]
    for table in SIGHTING_LINKS:
        out.append(f"ALTER TABLE dbo.{ident(table)} ADD COLUMN sighting_id integer;")
    out.append("")

    out.append("-- Foreign keys DB167 never declared, inferred and checked in Phase 2a.")
    for child_t, child_c, parent_t, parent_c, valid in FOREIGN_KEYS:
        clause = "" if valid else " NOT VALID"
        out.append(
            f"ALTER TABLE dbo.{ident(child_t)} ADD CONSTRAINT {fk_name(child_t, child_c)} "
            f"FOREIGN KEY ({ident(child_c)}) REFERENCES dbo.{ident(parent_t)} ({ident(parent_c)}){clause};"
        )
    for table in SIGHTING_LINKS:
        out.append(
            f"ALTER TABLE dbo.{ident(table)} ADD CONSTRAINT {fk_name(table, 'sighting_id')} "
            f'FOREIGN KEY (sighting_id) REFERENCES dbo."SightingT" ("SightingID");'
        )
    out.append("")

    out.append("-- DB167's own indexes, carried across unchanged.")
    for table, columns in DB167_INDEXES:
        cols = ", ".join(ident(c) for c in columns)
        out.append(f"CREATE INDEX {ix_name(table, columns)} ON dbo.{ident(table)} ({cols});")
    out.append("")

    out += [
        "-- Indexes on the columns this phase adds.",
        'CREATE INDEX ix_sightingeventt_sighting_id ON dbo."SightingEventT" (sighting_id);',
        'CREATE INDEX ix_otherspeciest_sighting_id ON dbo."OtherSpeciesT" (sighting_id);',
        'CREATE INDEX ix_sightingt_geom ON dbo."SightingT" USING GIST (geom);',
        'CREATE INDEX ix_sightingt_end_geom ON dbo."SightingT" USING GIST (end_geom);',
        "",
    ]
    return "\n".join(out)


def load(dst):
    ddl = open(SCHEMA_FILE).read()
    tables_ddl, rest = ddl.split("-- Foreign keys", 1)
    with dst.cursor() as cur:
        cur.execute(tables_ddl)
    dst.commit()
    print(f"created dbo's {len(TABLES)} tables")

    with dst.cursor() as cur:
        for table in TABLES:
            cur.execute(f"INSERT INTO dbo.{ident(table)} SELECT * FROM raw.{ident(table)}")
    dst.commit()
    print("copied raw -> dbo, every research group, no values changed")

    with dst.cursor() as cur:
        cur.execute("""
            UPDATE dbo."SightingT" s SET identified_individual_count = sub.n
            FROM (SELECT "SightingID", count(*) AS n FROM dbo."SightingIdentificationT"
                  GROUP BY "SightingID") sub
            WHERE sub."SightingID" = s."SightingID"
        """)
        for lat, lon, geom_col in [("Start Dec Lat", "Start Dec Long", "geom"),
                                    ("End Dec Lat", "End Dec Long", "end_geom")]:
            cur.execute(f"""
                UPDATE dbo."SightingT" SET {geom_col} =
                    ST_SetSRID(ST_MakePoint({ident(lon)}, {ident(lat)}), 4326)
                WHERE {ident(lat)} IS NOT NULL AND {ident(lon)} IS NOT NULL
                  AND NOT ({ident(lat)} = 0 AND {ident(lon)} = 0)
                  AND {ident(lon)} BETWEEN -180 AND 180 AND {ident(lat)} BETWEEN -90 AND 90
            """)
        for child in SIGHTING_LINKS:
            pk = {"SightingEventT": "SightingEventID", "OtherSpeciesT": "OtherSpeciesID"}[child]
            cur.execute(f"""
                UPDATE dbo.{ident(child)} t SET sighting_id = matched."SightingID"
                FROM (
                    SELECT {ident(pk)}, min("SightingID") AS "SightingID" FROM (
                        SELECT DISTINCT c.{ident(pk)}, s."SightingID"
                        FROM dbo.{ident(child)} c
                        JOIN dbo."SightingT" s
                          ON s."DailyEffortID" = c."DailyEffortID" AND s."Sighting" = c."Sighting"
                        WHERE c."DailyEffortID" IS NOT NULL AND c."Sighting" IS NOT NULL
                    ) matches
                    GROUP BY {ident(pk)}
                    HAVING count(*) = 1
                ) matched
                WHERE matched.{ident(pk)} = t.{ident(pk)}
            """)
            cur.execute(f'SELECT count(*), count(sighting_id) FROM dbo.{ident(child)}')
            total, resolved = cur.fetchone()
            print(f"  {child}: sighting_id resolved {resolved:,}/{total:,}")
    dst.commit()

    delete_orphans(dst)

    with dst.cursor() as cur:
        cur.execute("-- Foreign keys" + rest)
    dst.commit()
    print("added foreign keys and indexes")

    views_file = os.path.join(os.path.dirname(__file__), "schema", "dbo_views.sql")
    with dst.cursor() as cur:
        cur.execute(open(views_file).read())
    dst.commit()
    print("created dbo167's translated views")


def delete_orphans(dst):
    """
    8 rows whose foreign key points nowhere: 2 EffortCrewT rows naming a
    DailyEffortID (28149) that no longer exists, 6 TrackT rows naming a
    VesselID (41) that no longer exists and carrying no Vessel text either.
    Deleted so every foreign key can be a real, validated constraint. `raw`
    still has all 8, unfrozen and complete, so nothing is lost -- Phase 5
    records each as an audit_log correction, actor Unknown, once that table
    exists.
    """
    with dst.cursor() as cur:
        cur.execute("""
            DELETE FROM dbo."EffortCrewT" c WHERE c."DailyEffortID" IS NOT NULL AND NOT EXISTS
                (SELECT 1 FROM dbo."DailyEffortT" d WHERE d."DailyEffortID" = c."DailyEffortID")
        """)
        print(f"  deleted {cur.rowcount} EffortCrewT rows with no matching DailyEffortT")
        cur.execute("""
            DELETE FROM dbo."TrackT" t WHERE t."VesselID" IS NOT NULL AND NOT EXISTS
                (SELECT 1 FROM dbo."VesselT" v WHERE v."VesselID" = t."VesselID")
        """)
        print(f"  deleted {cur.rowcount} TrackT rows with no matching VesselT")
    dst.commit()


# The 8 rows deleted by delete_orphans() -- see its docstring. Both raw-vs-dbo
# checks below expect exactly these two tables to be short by exactly this many.
DELETED_ORPHANS = {"EffortCrewT": 2, "TrackT": 6}


def verify(dst):
    failures = []
    with dst.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='dbo' AND table_type='BASE TABLE'")
        present = {r[0] for r in cur.fetchall()}
        if present != set(TABLES):
            failures.append(f"tables: missing {sorted(set(TABLES)-present)}, unexpected {sorted(present-set(TABLES))}")

        for table in TABLES:
            cur.execute(f'SELECT count(*) FROM raw.{ident(table)}')
            raw_n = cur.fetchone()[0]
            cur.execute(f'SELECT count(*) FROM dbo.{ident(table)}')
            dbo_n = cur.fetchone()[0]
            expected = raw_n - DELETED_ORPHANS.get(table, 0)
            if dbo_n != expected:
                failures.append(f"{table}: {raw_n:,} rows in raw, {dbo_n:,} in dbo, expected {expected:,}")

        cur.execute("""
            SELECT c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='dbo' AND c.relkind='r'
              AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid=c.oid AND k.contype='p')
        """)
        without_pk = [r[0] for r in cur.fetchall()]
        if without_pk:
            failures.append(f"no primary key on: {without_pk}")

        cur.execute("""
            SELECT count(*) FILTER (WHERE convalidated), count(*) FILTER (WHERE NOT convalidated)
            FROM pg_constraint WHERE contype='f' AND connamespace='dbo'::regnamespace
        """)
        validated, not_valid = cur.fetchone()
        expected_valid = len([f for f in FOREIGN_KEYS if f[-1]]) + len(SIGHTING_LINKS)
        expected_not_valid = len([f for f in FOREIGN_KEYS if not f[-1]])
        if (validated, not_valid) != (expected_valid, expected_not_valid):
            failures.append(f"FKs: {validated} validated + {not_valid} not valid, "
                             f"expected {expected_valid} + {expected_not_valid}")

        # raw and dbo agree on every value: compare raw's own columns as
        # multisets (EXCEPT ALL keeps duplicates), ignoring the few columns
        # this phase added.
        for table in TABLES:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='raw' AND table_name=%s ORDER BY ordinal_position
            """, (table,))
            cols = ", ".join(ident(r[0]) for r in cur.fetchall())
            cur.execute(f"""
                SELECT (SELECT count(*) FROM (SELECT {cols} FROM raw.{ident(table)}
                                               EXCEPT ALL SELECT {cols} FROM dbo.{ident(table)}) a),
                       (SELECT count(*) FROM (SELECT {cols} FROM dbo.{ident(table)}
                                               EXCEPT ALL SELECT {cols} FROM raw.{ident(table)}) b)
            """)
            only_raw, only_dbo = cur.fetchone()
            expected_only_raw = DELETED_ORPHANS.get(table, 0)
            if only_raw != expected_only_raw or only_dbo:
                failures.append(f"{table}: raw and dbo disagree on {only_raw} + {only_dbo} rows, "
                                 f"expected {expected_only_raw} + 0")

        for view in VIEWS:
            cur.execute(f'SELECT count(*) FROM dbo.{ident(view)}')
            if cur.fetchone()[0] == 0:
                failures.append(f"{view}: returns no rows")

    print(f"\n{'FAILED' if failures else 'PASSED'}")
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if args.schema:
        os.makedirs(os.path.dirname(SCHEMA_FILE), exist_ok=True)
        with open(SCHEMA_FILE, "w") as f:
            f.write(build_schema())
        print(f"wrote {SCHEMA_FILE}")
        return 0

    with psycopg.connect(os.environ["DATABASE_URL"]) as dst:
        if not args.verify:
            with dst.cursor() as cur:
                cur.execute("DROP SCHEMA IF EXISTS dbo CASCADE")
            dst.commit()
            load(dst)
        return verify(dst)


if __name__ == "__main__":
    sys.exit(main())
