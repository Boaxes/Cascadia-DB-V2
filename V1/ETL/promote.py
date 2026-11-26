"""
Turn the copy of DB167 in `dbo` into the data the application reads.

Three kinds of change happen here, and they are kept apart on purpose:

  Rules        systematic changes to many records -- ETL/rules/*.py
  Corrections  fixes to a handful of records, written to app.audit_log under
               the actor `legacy-cleanup` with the original reasoning as the
               comment -- also ETL/rules/*.py
  Derived      columns DB167 never had: geometry, species, parsed numbers,
               effort positions, track statistics. Nothing to compare against,
               so nothing to log; provenance lives in the data itself.

    python promote.py            apply everything
    python promote.py --verify   check that every raw/dbo difference is explained
"""

import argparse
import csv
import importlib
import json
import os
import pathlib
import sys

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "Django" / "admintools"))

from rules import NORMALIZE, MAP, SQL

SCHEMA = pathlib.Path(__file__).parent / "schema"
RULE_MODULES = ["daily_effort_t", "sighting_t", "daily_condition_t",
                "daily_event_t", "sample_t", "track_t"]

LEGACY_ACTOR = "legacy-cleanup"

# Tables that record a vessel as free text and so need a resolved vessel_id.
VESSEL_TABLES = ["DailyEffortT", "DailyConditionT", "DailyEventT", "SightingT",
                 "SampleT", "TagSummaryT", "TrackingT", "SightingEventT",
                 "OtherSpeciesT", "IdentificationT", "SightingIdentificationT",
                 "TrackT"]


def ident(name):
    return '"' + name.replace('"', '""') + '"'


def load_rules():
    return [importlib.import_module(f"rules.{name}") for name in RULE_MODULES]


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def apply_rule(cur, rule):
    if rule.kind == NORMALIZE:
        changed = 0
        for column in rule.columns:
            # The winning spelling is the one used most often; ties go to the
            # alphabetically first so the result does not depend on row order.
            cur.execute(f"""
                WITH counts AS (
                    SELECT {ident(column)} AS value, count(*) AS n
                    FROM dbo.{ident(rule.table)}
                    WHERE {ident(column)} IS NOT NULL GROUP BY 1
                ), canon AS (
                    SELECT lower(btrim(value)) AS key, value,
                           row_number() OVER (PARTITION BY lower(btrim(value))
                                              ORDER BY n DESC, value) AS rank
                    FROM counts
                )
                UPDATE dbo.{ident(rule.table)} t SET {ident(column)} = c.value
                FROM canon c
                WHERE lower(btrim(t.{ident(column)})) = c.key AND c.rank = 1
                  AND t.{ident(column)} IS DISTINCT FROM c.value
            """)
            changed += cur.rowcount
        return changed

    if rule.kind == MAP:
        column = rule.columns[0]
        changed = 0
        for old, new in rule.mapping.items():
            cur.execute(
                f"UPDATE dbo.{ident(rule.table)} SET {ident(column)} = %s "
                f"WHERE btrim({ident(column)}) = %s", (new, old))
            changed += cur.rowcount
        return changed

    if rule.kind == SQL:
        cur.execute(rule.sql)
        return cur.rowcount

    raise ValueError(f"unknown rule kind {rule.kind!r}")


def apply_correction(cur, correction):
    """Apply it, and write one audit_log row per affected record."""
    where = correction.where
    if correction.crc_only:
        where = f'({where}) AND "Research Group" = \'CRC\''
    # Read the rows first so the log can say what each value actually was.
    cur.execute(
        f"SELECT {ident(correction.pk)}::text, to_jsonb(t) FROM dbo.{ident(correction.table)} t "
        f"WHERE {where}")
    before = {pk: row for pk, row in cur.fetchall()}
    if not before:
        return 0

    cur.execute(f"UPDATE dbo.{ident(correction.table)} SET {correction.set} "
                f"WHERE {ident(correction.pk)}::text = ANY(%s)", (list(before),))

    cur.execute(
        f"SELECT {ident(correction.pk)}::text, to_jsonb(t) FROM dbo.{ident(correction.table)} t "
        f"WHERE {ident(correction.pk)}::text = ANY(%s)", (list(before),))
    after = {pk: row for pk, row in cur.fetchall()}

    for pk, old_row in before.items():
        new_row = after.get(pk, {})
        changes = {
            key: {"old": old_row[key], "new": new_row.get(key)}
            for key in old_row
            if old_row[key] != new_row.get(key)
        }
        if not changes:
            continue
        cur.execute("""
            INSERT INTO app.audit_log
                (actor_name, action, target_table, target_pk, changes, comment)
            VALUES (%s, 'update', %s, %s, %s, %s)
        """, (LEGACY_ACTOR, correction.table, pk, json.dumps(changes),
              f"{correction.id}. {correction.description}"))
    return len(before)


# ---------------------------------------------------------------------------
# Derived columns
# ---------------------------------------------------------------------------


def add_derived_columns(cur):
    cur.execute("""
        ALTER TABLE dbo."DailyEffortT"
            ADD COLUMN IF NOT EXISTS total_distance_nm numeric(10,3),
            ADD COLUMN IF NOT EXISTS start_point geometry(Point, 4326),
            ADD COLUMN IF NOT EXISTS end_point geometry(Point, 4326),
            ADD COLUMN IF NOT EXISTS start_coord_source text,
            ADD COLUMN IF NOT EXISTS end_coord_source text;
        ALTER TABLE dbo."SightingT"
            ADD COLUMN IF NOT EXISTS num_calves integer,
            ADD COLUMN IF NOT EXISTS depth_m numeric(10,2),
            ADD COLUMN IF NOT EXISTS species_id integer,
            ADD COLUMN IF NOT EXISTS species_uncertain boolean NOT NULL DEFAULT false;
        ALTER TABLE dbo."TrackT"
            ADD COLUMN IF NOT EXISTS geom geometry(MultiLineString, 4326),
            ADD COLUMN IF NOT EXISTS length_nm numeric(12,3),
            ADD COLUMN IF NOT EXISTS point_count integer,
            ADD COLUMN IF NOT EXISTS track_status text,
            ADD COLUMN IF NOT EXISTS file_name text;
        ALTER TABLE dbo."DailyConditionT"
            ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326),
            ADD COLUMN IF NOT EXISTS visibility_nm numeric(8,2);
        ALTER TABLE dbo."DailyEventT"
            ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);
        ALTER TABLE dbo."SampleT"
            ADD COLUMN IF NOT EXISTS species_id integer;
    """)
    # vessel_id on the tables that record a vessel as free text.
    for table in VESSEL_TABLES:
        cur.execute(f'ALTER TABLE dbo.{ident(table)} '
                    f'ADD COLUMN IF NOT EXISTS vessel_id integer')


def build_vessels(cur):
    """
    The vessel list the application shows.

    DB167's VesselT has 80 rows, but the survey tables do not point at it --
    they store whatever text somebody typed, and most of that text has no
    VesselT row (there are far more vessels across all the research groups than
    the lookup covers). So the list is derived: one row per distinct vessel
    text, carrying VesselT's name and code where the text matches either of
    them, and just the text where it does not.

    That makes vessel_id an exact one-to-one join afterwards, with nothing to
    disambiguate: every vessel text that exists gets exactly one row.
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dbo."VesselListT" (
            vessel_id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            vessel_text      text NOT NULL UNIQUE,
            code             text,
            name             text,
            legacy_vessel_id integer
        );
        TRUNCATE dbo."VesselListT" RESTART IDENTITY CASCADE;

        WITH texts AS (
            SELECT DISTINCT btrim("Vessel") AS vessel_text FROM dbo."DailyEffortT"
                WHERE "Vessel" IS NOT NULL AND btrim("Vessel") <> ''
            UNION SELECT DISTINCT btrim("Vessel") FROM dbo."SightingT"
                WHERE "Vessel" IS NOT NULL AND btrim("Vessel") <> ''
            UNION SELECT DISTINCT btrim("Vessel") FROM dbo."DailyConditionT"
                WHERE "Vessel" IS NOT NULL AND btrim("Vessel") <> ''
            UNION SELECT DISTINCT btrim("Vessel") FROM dbo."DailyEventT"
                WHERE "Vessel" IS NOT NULL AND btrim("Vessel") <> ''
            UNION SELECT DISTINCT btrim("Vessel") FROM dbo."SampleT"
                WHERE "Vessel" IS NOT NULL AND btrim("Vessel") <> ''
        )
        INSERT INTO dbo."VesselListT" (vessel_text, code, name, legacy_vessel_id)
        SELECT t.vessel_text, v."VesselCode", v."VesselName", v."VesselID"
        FROM   texts t
        LEFT JOIN LATERAL (
            -- Lowest identifier wins: VesselT itself has three rows for MIG and
            -- two for MOK, so a code is not always unique on its own.
            SELECT "VesselCode", "VesselName", "VesselID" FROM dbo."VesselT"
            WHERE lower(btrim("VesselCode")) = lower(t.vessel_text)
               OR lower(btrim("VesselName")) = lower(t.vessel_text)
            ORDER BY "VesselID" LIMIT 1
        ) v ON true
        ORDER BY t.vessel_text;
    """)
    for table in VESSEL_TABLES:
        cur.execute(f"""
            UPDATE dbo.{ident(table)} t SET vessel_id = v.vessel_id
            FROM dbo."VesselListT" v WHERE v.vessel_text = btrim(t."Vessel")
        """)
    # TrackT is the one table that points at VesselT directly, so where its text
    # is missing the identifier still resolves.
    cur.execute("""
        UPDATE dbo."TrackT" t SET vessel_id = v.vessel_id
        FROM dbo."VesselListT" v
        WHERE t.vessel_id IS NULL AND v.legacy_vessel_id = t."VesselID"
    """)


def build_child_geometry(cur):
    """
    Points for the sightings, weather readings and log entries.

    Installed as triggers rather than run once, so a point can never drift from
    the coordinates it is drawn from -- including when the change comes from
    somewhere other than the application. Touching each row makes the trigger
    fill in what is already there.
    """
    cur.execute(open(SCHEMA / "dbo_geometry.sql").read())
    for table in ["SightingT", "DailyConditionT", "DailyEventT"]:
        cur.execute(f'UPDATE dbo.{ident(table)} SET "Dec Lat" = "Dec Lat"'
                    if table != "SightingT" else
                    'UPDATE dbo."SightingT" SET "Start Dec Lat" = "Start Dec Lat"')
    # Visibility: DB167 has two overlapping columns. The later one wins where it
    # reads as a number, the older one where it does not.
    cur.execute("""
        UPDATE dbo."DailyConditionT" SET visibility_nm = COALESCE(
            CASE WHEN btrim("Visibility (nm)") ~ '^[0-9]+(\.[0-9]+)?$'
                 THEN btrim("Visibility (nm)")::numeric END,
            CASE WHEN btrim("Visibility") ~ '^[0-9]+(\.[0-9]+)?$'
                 THEN btrim("Visibility")::numeric END)
    """)
    # Samples carry their own species code.
    cur.execute("""
        UPDATE dbo."SampleT" s SET species_id = sp.species_id
        FROM dbo."SpeciesT" sp
        WHERE sp.code = btrim(rtrim(btrim(s."Species"), '?'))
    """)


def build_species(cur):
    """
    The species lookup DB167 has no equivalent of.

    A code is normalised by trimming a trailing question mark, which is an
    observer saying they were not confident. The code stays usable and the
    doubt is kept on the sighting as species_uncertain, because uncertainty is
    a property of the observation, not of the species.
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dbo."SpeciesT" (
            species_id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            code            text NOT NULL UNIQUE,
            common_name     text,
            scientific_name text,
            category        text NOT NULL DEFAULT 'unidentified'
        );
        TRUNCATE dbo."SpeciesT" RESTART IDENTITY CASCADE;
        INSERT INTO dbo."SpeciesT" (code)
        SELECT DISTINCT btrim(rtrim(btrim("Species"), '?'))
        FROM   dbo."SightingT"
        WHERE  "Species" IS NOT NULL AND btrim("Species") <> ''
          AND  btrim(rtrim(btrim("Species"), '?')) <> ''
          -- A value naming more than one species is not a species. The text
          -- alone cannot say which was meant, so it gets no species row and
          -- the sighting keeps its original text.
          AND  btrim("Species") !~ '[/,]'
        ORDER  BY 1;

        UPDATE dbo."SightingT" s SET species_id = sp.species_id
        FROM   dbo."SpeciesT" sp
        WHERE  sp.code = btrim(rtrim(btrim(s."Species"), '?'));

        UPDATE dbo."SightingT"
        SET    species_uncertain = true
        WHERE  btrim("Species") LIKE '%?';
    """)

    # Names and categories, from ETL/seed/species.csv. DB167 stores only the
    # code and says nowhere what one means, so a code with no row in the seed
    # keeps its code as its name and is shown as unidentified. Correcting a
    # name is an edit to that file and a re-run, not a code change.
    seed = SCHEMA.parent / "seed" / "species.csv"
    if seed.exists():
        with open(seed, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                cur.execute("""
                    UPDATE dbo."SpeciesT"
                    SET common_name = NULLIF(%s, ''), scientific_name = NULLIF(%s, ''),
                        category = %s
                    WHERE code = %s
                """, (row["common_name"], row["scientific_name"],
                      row["category"], row["code"]))


def build_event_codes(cur):
    """
    What each daily event code means, from DB167's EventCodeT, linked to every
    event by event_code_id. Deliberately not a foreign key constraint: some
    events carry codes EventCodeT does not define, and they keep an empty
    link rather than being constrained or removed.

    EventCodeT's descriptions are instructions to the crew ("BEGIN survey day,
    describe location"), so each code also gets a short name for display,
    from ETL/seed/event_codes.csv. Codes are matched ignoring case and
    surrounding space, which is how DB167 compared them. The few codes in the
    data EventCodeT does not list keep no link and show as written.
    """
    cur.execute("""
        ALTER TABLE dbo."EventCodeT" ADD COLUMN IF NOT EXISTS name text;
        ALTER TABLE dbo."DailyEventT" ADD COLUMN IF NOT EXISTS event_code_id integer;
        CREATE INDEX IF NOT EXISTS ix_dailyeventt_event_code_id ON dbo."DailyEventT" (event_code_id);
    """)
    seed = SCHEMA.parent / "seed" / "event_codes.csv"
    with open(seed, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            cur.execute('UPDATE dbo."EventCodeT" SET name = %s WHERE "EventCode" = %s',
                        (row["name"], row["code"]))
    cur.execute("""
        UPDATE dbo."DailyEventT" e SET event_code_id = c."EventCodeID"
        FROM   dbo."EventCodeT" c
        WHERE  upper(btrim(e."Code")) = upper(c."EventCode")
    """)


def build_effort_positions(cur):
    """
    No effort in DB167 has a usable recorded position -- the four coordinate
    columns are populated on 18 of 25,066 rows and every one of those is zero.
    So a position is derived, and start_coord_source records per row where it
    came from, which means one from a B event is never confused with one
    inferred from something else.

    The crew logs a B event when an effort begins and a T event when it ends,
    and those entries carry a position. Where there is none, the track's first
    or last point is used.
    """
    for kind, code, column, source_column, endpoint in [
        ("start", "B", "start_point", "start_coord_source", "ST_StartPoint"),
        ("end", "T", "end_point", "end_coord_source", "ST_EndPoint"),
    ]:
        # 1. the B or T event, where it carries a position
        cur.execute(f"""
            UPDATE dbo."DailyEffortT" e
            SET    {column} = ST_SetSRID(ST_MakePoint(ev."Dec Long", ev."Dec Lat"), 4326),
                   {source_column} = 'event_{code}'
            FROM (
                SELECT DISTINCT ON ("DailyEffortID") "DailyEffortID", "Dec Lat", "Dec Long"
                FROM   dbo."DailyEventT"
                WHERE  btrim(upper("Code")) = '{code}'
                  AND  "Dec Lat" IS NOT NULL AND "Dec Long" IS NOT NULL
                ORDER  BY "DailyEffortID", "Time" {'ASC' if kind == 'start' else 'DESC'}
            ) ev
            WHERE ev."DailyEffortID" = e."DailyEffortID" AND e.{column} IS NULL
        """)
        # 2. the first or last point of that effort's GPS track
        cur.execute(f"""
            UPDATE dbo."DailyEffortT" e
            SET    {column} = {endpoint}(ST_GeometryN(t.geom, {'1' if kind == 'start' else 'ST_NumGeometries(t.geom)'})),
                   {source_column} = 'gps_track'
            FROM   dbo."TrackT" t
            WHERE  t."EffortID" = e."DailyEffortID" AND t.geom IS NOT NULL
              AND  e.{column} IS NULL
        """)
    # 3. start only: the earliest positioned record of the day, as a last resort
    cur.execute("""
        UPDATE dbo."DailyEffortT" e
        SET    start_point = ST_SetSRID(ST_MakePoint(ev."Dec Long", ev."Dec Lat"), 4326),
               start_coord_source = 'first_positioned_record'
        FROM (
            SELECT DISTINCT ON ("DailyEffortID") "DailyEffortID", "Dec Lat", "Dec Long"
            FROM   dbo."DailyEventT"
            WHERE  "Dec Lat" IS NOT NULL AND "Dec Long" IS NOT NULL
            ORDER  BY "DailyEffortID", "Time"
        ) ev
        WHERE ev."DailyEffortID" = e."DailyEffortID" AND e.start_point IS NULL
    """)


def build_track_status(cur):
    """
    Two facts decide a track's status: whether it is linked to an effort, and
    whether its file is in object storage. `file_name` is the ntext TrackFileName
    as plain text, which is what the bucket is keyed by.
    """
    cur.execute("""
        UPDATE dbo."TrackT" SET file_name = btrim(CAST("TrackFileName" AS text));
    """)
    cur.execute("""
        UPDATE dbo."TrackT" t SET track_status = CASE
            WHEN t."EffortID" IS NOT NULL AND EXISTS (
                     SELECT 1 FROM dbo."TrackFileList" f
                     WHERE lower(btrim(f."FileName")) = lower(t.file_name)) THEN 'available'
            WHEN t."EffortID" IS NOT NULL THEN 'missing_file'
            WHEN EXISTS (SELECT 1 FROM dbo."TrackFileList" f
                         WHERE lower(btrim(f."FileName")) = lower(t.file_name)) THEN 'unassociated'
            ELSE 'unresolved' END
    """)


def import_tracks(cur, archive):
    """
    Clean the GPS files and build each track's line.

    The archive is the authority for what a track looked like. Every file gets a
    track row: without one, the bucket and the database would disagree about
    which files exist.
    """
    _here = pathlib.Path(__file__).parent
    for candidate in [_here / "gps", _here.parent / "Django" / "admintools" / "gps"]:
        if candidate.is_dir():
            sys.path.insert(0, str(candidate))
            break
    import tracks as gps_tracks

    files = {}
    for root, _, names in os.walk(archive):
        for name in names:
            if name.lower().endswith(".csv"):
                files[name] = os.path.join(root, name)

    cur.execute("""
        INSERT INTO dbo."TrackT" ("TrackID", file_name, "TrackFileName",
                                  "SurveyDate", "Vessel", "TrackFileType", "Useable")
        SELECT (SELECT max("TrackID") FROM dbo."TrackT")
                   + row_number() OVER (ORDER BY f."FileName"),
               btrim(f."FileName"), btrim(f."FileName"),
               CASE WHEN btrim(f."FileName") ~ '^[0-9]{8}'
                    THEN to_date(left(btrim(f."FileName"), 8), 'YYYYMMDD') END,
               CASE WHEN btrim(f."FileName") ~ '^[0-9]{8}-'
                    THEN upper(split_part(split_part(btrim(f."FileName"), '-', 2), '_', 1)) END,
               'csv', true
        FROM   dbo."TrackFileList" f
        WHERE  NOT EXISTS (SELECT 1 FROM dbo."TrackT" t
                           WHERE lower(t.file_name) = lower(btrim(f."FileName")))
    """)
    added = cur.rowcount
    cur.execute("""UPDATE dbo."TrackT" SET track_status = 'unassociated'
                   WHERE track_status IS NULL""")

    cur.execute('SELECT "TrackID", file_name FROM dbo."TrackT" WHERE file_name IS NOT NULL')
    tracks = {}
    for track_id, name in cur.fetchall():
        tracks.setdefault(name.lower(), []).append(track_id)

    for name, path in sorted(files.items()):
        text, _ = gps_tracks.clean_file(path)
        wkt, points = gps_tracks.to_wkt(text)
        for track_id in tracks.get(name.lower(), []):
            cur.execute("""UPDATE dbo."TrackT" SET geom = %s::geometry, point_count = %s
                           WHERE "TrackID" = %s""", (wkt, points, track_id))

    cur.execute("""
        UPDATE dbo."TrackT"
        SET length_nm = round((ST_Length(geom::geography) / 1852)::numeric, 3)
        WHERE geom IS NOT NULL
    """)
    cur.execute("""SELECT count(*), count(geom), sum(length_nm), sum(point_count)
                   FROM dbo."TrackT" """)
    total, geoms, length, count = cur.fetchone()
    print(f"  tracks       {geoms:,} of {total:,} with a line, {added} added from files")
    print(f"               {float(length or 0):,.1f} nm, {count:,} points")


def seed_deletions(cur):
    """
    The 8 rows Phase 2a deleted so every foreign key could be a real one.
    Recorded here now that app.audit_log exists, with the whole row kept so
    the deletion is reversible like any other.
    """
    for table, pk, parent, parent_pk, reason in [
        ("EffortCrewT", "EffortCrewID", "DailyEffortT", "DailyEffortID",
         "Named an effort that no longer exists in DailyEffortT, so the crew "
         "record could not be attached to anything."),
        ("TrackT", "TrackID", "VesselT", "VesselID",
         "Named a vessel that no longer exists in VesselT, and carried no "
         "vessel text either."),
    ]:
        cur.execute(f"""
            SELECT r.{ident(pk)}::text, to_jsonb(r)
            FROM   raw.{ident(table)} r
            WHERE  NOT EXISTS (SELECT 1 FROM dbo.{ident(table)} d
                               WHERE d.{ident(pk)} = r.{ident(pk)})
        """)
        for target_pk, row in cur.fetchall():
            cur.execute("""
                INSERT INTO app.audit_log
                    (actor_name, action, target_table, target_pk, snapshot, comment)
                VALUES (%s, 'delete', %s, %s, %s, %s)
            """, (LEGACY_ACTOR, table, target_pk,
                  json.dumps({table: [row]}, default=str), reason))


def seed_track_associations(cur):
    """
    Twelve track-to-effort links Doug made through V1's admin tool. They never
    reached DB167 -- V1 wrote them to Postgres and its writeback to SQL Server
    was never finished -- so without this they would be lost on rebuild.
    """
    path = SCHEMA.parent / "seed" / "doug_track_links.json"
    if not path.exists():
        return 0
    links = json.loads(path.read_text())
    for link in links:
        cur.execute("""
            UPDATE dbo."TrackT" SET "EffortID" = %s
            WHERE lower(file_name) = lower(%s) AND "EffortID" IS NULL
        """, (link["daily_effort_id"], link["file_name"]))
        if cur.rowcount:
            cur.execute("""
                INSERT INTO app.audit_log
                    (actor_name, action, target_table, target_pk, changes, comment)
                SELECT %s, 'associate', 'TrackT', "TrackID"::text,
                       %s, 'Recovered from the V1 database. Associated through the '
                           'track tool; the writeback to SQL Server was never finished, '
                           'so the link existed only in V1.'
                FROM dbo."TrackT" WHERE lower(file_name) = lower(%s)
            """, ("Doug Sandilands",
                  json.dumps({"EffortID": {"old": None, "new": link["daily_effort_id"]}}),
                  link["file_name"]))
    return len(links)


# ---------------------------------------------------------------------------


def run(conn, archive=None):
    with conn.cursor() as cur:
        cur.execute(open(SCHEMA / "app.sql").read())
        conn.commit()
        print("created app schema, audit_log and record_diff")

        add_derived_columns(cur)
        conn.commit()

        print("\nrules")
        for module in load_rules():
            for rule in module.RULES:
                changed = apply_rule(cur, rule)
                print(f"  {rule.id:<4} {module.TABLE:<18} {changed:>7,} records")
            for name in ["DISTANCE_SQL", "DEPTH_SQL", "CALVES_SQL"]:
                if hasattr(module, name):
                    cur.execute(getattr(module, name))
                    print(f"  {name.split('_')[0].lower():<4} {module.TABLE:<18} {cur.rowcount:>7,} records")
            for statement in getattr(module, "ZERO_PAIR_SQL", []):
                cur.execute(statement)
                print(f"  R7   {module.TABLE:<18} {cur.rowcount:>7,} records")
        conn.commit()

        # Record which rule owns which column, for the chain the detail pages show.
        for module in load_rules():
            for rule in module.RULES:
                for column in rule.columns:
                    cur.execute("""
                        INSERT INTO app.rule_column
                            (rule_id, description, target_table, column_name)
                        VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
                    """, (rule.id, rule.description, module.TABLE, column))
            for name, columns, rule_id, description in [
                ("DISTANCE_SQL", ["total_distance_nm"], "R4",
                 "Distance travelled, converted to nautical miles from the unit "
                 "recorded beside it."),
                ("DEPTH_SQL", ["depth_m"], "R5",
                 "Depth, converted to metres from the unit recorded beside it."),
                ("CALVES_SQL", ["num_calves"], "R6",
                 "Calf count parsed out of a free-text column. A value like 1? "
                 "is an observer who thinks they saw one, so it is left empty "
                 "rather than counted as confirmed."),
            ]:
                if hasattr(module, name):
                    for column in columns:
                        cur.execute("""
                            INSERT INTO app.rule_column
                                (rule_id, description, target_table, column_name)
                            VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
                        """, (rule_id, description, module.TABLE, column))
            if hasattr(module, "ZERO_PAIR_SQL"):
                for column in ["Start Dec Lat", "Start Dec Long", "End Dec Lat",
                               "End Dec Long", "Dec Lat", "Dec Long"]:
                    cur.execute("""
                        INSERT INTO app.rule_column
                            (rule_id, description, target_table, column_name)
                        VALUES ('R7', %s, %s, %s) ON CONFLICT DO NOTHING
                    """, ("A coordinate pair of exactly (0,0) is a real point in "
                          "the Gulf of Guinea and never anywhere Cascadia works, "
                          "so it means the position was not recorded.",
                          module.TABLE, column))
        conn.commit()

        print("\ncorrections -> app.audit_log")
        for module in load_rules():
            for correction in module.CORRECTIONS:
                n = apply_correction(cur, correction)
                flag = ""
                if correction.expected is not None and n != correction.expected:
                    flag = f"  (expected {correction.expected})"
                print(f"  {correction.id:<8} {module.TABLE:<18} {n:>4} records{flag}")
        conn.commit()

        print("\nderived")
        build_species(cur)
        cur.execute('SELECT count(*), count(common_name) FROM dbo."SpeciesT"')
        codes, named = cur.fetchone()
        print(f"  SpeciesT                     {codes:>7,} codes, {named} named")
        cur.execute('SELECT count(species_id), count(*) FILTER (WHERE species_uncertain) FROM dbo."SightingT"')
        matched, uncertain = cur.fetchone()
        print(f"  species_id                   {matched:>7,} sightings, {uncertain} uncertain")
        build_event_codes(cur)
        cur.execute('SELECT count(event_code_id), count(*) FROM dbo."DailyEventT"')
        linked, events = cur.fetchone()
        print(f"  event_code_id                {linked:>7,} of {events:,} events")
        build_vessels(cur)
        cur.execute('SELECT count(*), count(legacy_vessel_id) FROM dbo."VesselListT"')
        vessels, matched_v = cur.fetchone()
        print(f"  VesselListT                  {vessels:>7,} vessels, {matched_v} matched to VesselT")
        build_child_geometry(cur)
        build_track_status(cur)
        conn.commit()

        # The GPS files, before the effort positions: an effort with no B or T
        # event falls back to the first or last point of its track, so the
        # track lines have to exist first.
        if archive:
            import_tracks(cur, archive)
            conn.commit()

        build_effort_positions(cur)
        cur.execute("""SELECT count(start_point), count(end_point), count(*) FROM dbo."DailyEffortT" """)
        start, end, total = cur.fetchone()
        print(f"  effort positions             {start:>7,} start, {end:,} end, of {total:,}")
        conn.commit()

        seed_deletions(cur)
        n = seed_track_associations(cur)
        cur.execute(open(SCHEMA / "app_views.sql").read())
        conn.commit()
        print("\napp views")
        for view in ["species", "vessel", "daily_effort", "sighting", "track",
                     "daily_condition", "daily_event", "sample", "effort_timeline"]:
            cur.execute(f"SELECT count(*) FROM app.{view}")
            print(f"  app.{view:<18} {cur.fetchone()[0]:>8,} rows")

        print("\nseeded history")
        cur.execute("SELECT actor_name, count(*) FROM app.audit_log GROUP BY 1 ORDER BY 2 DESC")
        for actor, count in cur.fetchall():
            print(f"  {actor:<20} {count:>5} rows")
        conn.commit()


def verify(conn):
    """
    Every raw/dbo difference is explained -- by a rule that claims the column,
    or by an audit_log row for that record. Nothing unaccounted for.
    """
    claimed = {}
    for module in load_rules():
        for rule in module.RULES:
            for column in rule.columns:
                claimed.setdefault(module.TABLE, set()).add(column)
        # The rules expressed as SQL name their own columns.
        for name, columns in [("DISTANCE_SQL", ["total_distance_nm"]),
                              ("DEPTH_SQL", ["depth_m"]),
                              ("CALVES_SQL", ["num_calves"])]:
            if hasattr(module, name):
                claimed.setdefault(module.TABLE, set()).update(columns)
        if hasattr(module, "ZERO_PAIR_SQL"):
            claimed.setdefault(module.TABLE, set()).update(
                ["Start Dec Lat", "Start Dec Long", "End Dec Lat", "End Dec Long",
                 "Dec Lat", "Dec Long"])

    failures = []
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='dbo' AND table_type='BASE TABLE'")
        tables = [r[0] for r in cur.fetchall() if r[0] != "SpeciesT"]

        for table in tables:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='raw' AND table_name=%s""", (table,))
            columns = [r[0] for r in cur.fetchall()]
            cur.execute(f"""
                SELECT a.attname FROM pg_index i
                JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
                WHERE i.indrelid = 'dbo.{ident(table)}'::regclass AND i.indisprimary""")
            pk = cur.fetchone()[0]

            for column in columns:
                cur.execute(f"""
                    SELECT count(*), min(r.{ident(pk)}::text)
                    FROM raw.{ident(table)} r JOIN dbo.{ident(table)} d USING ({ident(pk)})
                    WHERE r.{ident(column)}::text IS DISTINCT FROM d.{ident(column)}::text
                """)
                differing, example = cur.fetchone()
                if not differing:
                    continue
                if column in claimed.get(table, set()):
                    continue
                # Not claimed by a rule, so every differing row must have an
                # audit entry naming it.
                cur.execute("""
                    SELECT count(*) FROM app.audit_log
                    WHERE target_table = %s AND changes ? %s""", (table, column))
                logged = cur.fetchone()[0]
                if logged < differing:
                    failures.append(
                        f"{table}.{column}: {differing} rows differ, {logged} explained "
                        f"(e.g. pk {example})")

    print(f"\n{'FAILED' if failures else 'PASSED'} — every raw/dbo difference explained")
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--archive", help="the original GPS files")
    args = parser.parse_args()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        if not args.verify:
            run(conn, args.archive)
        return verify(conn)


if __name__ == "__main__":
    sys.exit(main())
