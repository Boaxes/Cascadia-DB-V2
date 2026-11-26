"""
Move a database from the old dbo onto the new pipeline (ETL/dbt). Run once.

    dbt run-operation create_persistent_tables
    python move_to_hashed_keys.py inputs     # 1. before the first build
    dbt build --vars '{replay: false}'       # 2. a build that applies no edits
    python move_to_hashed_keys.py backup     # 3a. keep a copy of the audit log first
    python move_to_hashed_keys.py audit      # 3. move the audit log onto its ids
    dbt build && dbt run-operation swap      # 4. the real build

1. inputs: the two tables the new pipeline keeps from build to build, filled
   from the old dbo while it is still there:
     app.track_geometry  each GPS file in the bucket and its line, from the old
                         dbo."TrackT" (a stored file whose line could not be
                         read has no line)
     app.vessel_number   each vessel's vessel_id, from the old dbo."VesselListT":
                         a vessel keeps the lowest id any of its spellings had

2. A build of the same copy of DB167 the website's edits were made against,
   with no edits applied, so build_next holds every record's hashed id next to
   the DB167 ID the audit log names it by.

3. audit: first a check that every vessel keeps its vessel_id (step 1 read
   the vessels as the build does). Then the entries the old import wrote under
   the actors below are deleted. The audit log holds only changes people made
   on the website; the pipeline makes those corrections itself (the rules on
   the Data Pipeline page, seeds/record_fixes.csv and seeds/removed_efforts.csv).
   Then every audit log entry on one of the 8 tables with a hashed Primary Key
   is moved from DB167's ID to the hashed id, so it finds its record however
   DB167 renumbers it, and keeps DB167's ID in legacy_pk, so it still finds it
   if DB167 changes the record's key columns. Every link of a track to an
   effort also records the effort's hashed id, as daily_effort_id. Last, one
   fix: entries 109, 112 and 113 were someone trying the edit form on sighting
   114893, and are deleted.
   An entry whose record is not in the build keeps its DB167 ID and is listed.

backup: step 3 deletes and rewrites audit log entries (the only table the move
changes in place; inputs only fills two empty ones), so a copy of the whole log
is kept first, in app.audit_log_before_cutover_YYYYMMDD. If a copy already
exists the move has been tried before, and it is left as the first one made.

--from-schema names the old dbo (default dbo); the tests use live_dbo.
"""

import argparse
import datetime
import json
import os
import sys

import psycopg
from dotenv import load_dotenv

# The 8 tables with a hashed Primary Key, and the DB167 ID column it replaces.
HASHED = {
    "DailyEffortT": "DailyEffortID", "DailyEventT": "DailyEventID", "DailyConditionT": "DailyConditionID",
    "SightingT": "SightingID", "SightingEventT": "SightingEventID", "OtherSpeciesT": "OtherSpeciesID",
    "SampleT": "SampleID", "IdentificationT": "IdentificationID",
}
# The actors the old import wrote entries under.
OLD_IMPORT_ACTORS = ("legacy-cleanup", "Data pipeline")
TRIAL_ENTRIES = (109, 112, 113)


# build.key_text (macros/functions.sql), for before the build has made it.
KEY_TEXT = """
    create function pg_temp.key_text(value text) returns text language sql immutable as $$
        SELECT nullif(lower(regexp_replace(btrim(value, E' \\t\\r\\n\\f\\v\u00a0'), '\\s+', ' ', 'g')), '')
    $$
"""


def inputs(conn, old):
    with conn.cursor() as cur:
        cur.execute("select count(*) from app.track_geometry")
        if cur.fetchone()[0]:
            print("app.track_geometry already has rows; left as it is")
        else:
            cur.execute(f"""
                insert into app.track_geometry (object_key, geom, point_count, length_nm)
                select distinct on (lower(file_name)) file_name, geom, point_count, length_nm
                from {old}."TrackT"
                where file_name is not null
                  and (geom is not null or track_status in ('available', 'unassociated'))
                order by lower(file_name), geom is null, "TrackID"
            """)
            print(f"app.track_geometry: {cur.rowcount:,} files")
            # The tracks the old process gave to files no track named keep
            # their TrackID. Where it gave one file two, the lowest TrackID.
            cur.execute(f"""
                update app.track_geometry g set track_id = t.track_id
                from (select lower(o.file_name) as name, min(o."TrackID") as track_id
                      from {old}."TrackT" o
                      where o.file_name is not null
                        and not exists (select 1 from raw."TrackT" r where r."TrackID" = o."TrackID")
                        and not exists (select 1 from app.audit_log a
                                        where a.target_table = 'TrackT' and a.action = 'create'
                                          and a.target_pk = o."TrackID"::text)
                      group by 1) t
                where t.name = lower(g.object_key)
            """)
            print(f"  {cur.rowcount} of them keep the TrackID of the record the old process gave them")

        cur.execute("select count(*) from app.vessel_number")
        if cur.fetchone()[0]:
            print("app.vessel_number already has rows; left as it is")
            return
        # Which vessel each old row stood for, read from its text exactly as
        # the build reads typed vessel text (models/build/vessels.sql and
        # vessel_keys.sql): a VesselT code (the lowest VesselID where VesselT
        # repeats one), else a VesselT name, else the text as its own vessel.
        # The build's functions are not there yet, so key_text is made here,
        # the same as build.key_text (macros/functions.sql); the audit step
        # checks the result against the build.
        cur.execute(KEY_TEXT)
        cur.execute(f"""
            insert into app.vessel_number (vessel_key, vessel_id)
            with old as (
                select vessel_id, pg_temp.key_text(vessel_text) as text from {old}."VesselListT"
            ),
            fleet as (
                select distinct pg_temp.key_text("VesselCode") as code from raw."VesselT"
                where pg_temp.key_text("VesselCode") is not null
            ),
            names as (
                select distinct on (pg_temp.key_text("VesselName"))
                       pg_temp.key_text("VesselName") as name, pg_temp.key_text("VesselCode") as code
                from raw."VesselT"
                where pg_temp.key_text("VesselName") is not null and pg_temp.key_text("VesselCode") is not null
                order by pg_temp.key_text("VesselName"), "VesselID"
            )
            select coalesce('code:' || f.code, 'code:' || n.code, 'text:' || o.text) as vessel_key,
                   min(o.vessel_id)
            from old o
            left join fleet f on f.code = o.text
            left join names n on n.name = o.text
            where o.text is not null
            group by 1
            order by 1
        """)
        print(f"app.vessel_number: {cur.rowcount:,} vessels")


def backup(conn):
    """A dated copy of app.audit_log, unless an earlier copy is there."""
    with conn.cursor() as cur:
        cur.execute("select relname from pg_class where relnamespace = 'app'::regnamespace "
                    "and relname like 'audit_log\\_before\\_cutover\\_%' order by relname")
        existing = [r[0] for r in cur.fetchall()]
        if existing:
            print(f"app.{existing[0]} already holds a copy of the audit log from before the move; "
                  "no new copy is made")
            return
        name = f"audit_log_before_cutover_{datetime.date.today():%Y%m%d}"
        cur.execute(f"create table app.{name} as table app.audit_log")
        print(f"app.audit_log copied to app.{name}: {cur.rowcount:,} entries")
    conn.commit()


def check_vessels(cur, old, build):
    """Every vessel the old dbo had, that the build still has, keeps its number."""
    cur.execute(f"""
        select o.vessel_id, o.vessel_text, v.vessel_key, v.vessel_id
        from {old}."VesselListT" o
        join {build}.vessel_keys k on k.key = {build}.key_text(o.vessel_text)
        join {build}.vessels v on v.vessel_id = k.vessel_id
        where v.is_new
        order by o.vessel_id
    """)
    lost = cur.fetchall()
    for old_id, text, key, new_id in lost:
        print(f"  vessel {text!r} (vessel_id {old_id}) is {key} in the build, which app.vessel_number lacks: "
              f"it would get the new number {new_id}")
    if lost:
        raise SystemExit(f"{len(lost)} vessels would lose their vessel_id: app.vessel_number does not match "
                         "models/build/vessels.sql")
    print("every vessel keeps its vessel_id")


def audit(conn, build, old):
    with conn.cursor() as cur:
        check_vessels(cur, old, build)

        cur.execute("update app.audit_log set restored_by = null where restored_by in "
                    "(select id from app.audit_log where actor_name = any(%s))", [list(OLD_IMPORT_ACTORS)])
        cur.execute("delete from app.audit_log where actor_name = any(%s)", [list(OLD_IMPORT_ACTORS)])
        print(f"{cur.rowcount} audit log entries by the old import deleted ({', '.join(OLD_IMPORT_ACTORS)})")

        ids = {}
        for table, legacy in HASHED.items():
            cur.execute(f'select "{legacy}"::text, id::text from {build}."keyed_{table}"')
            ids[table] = dict(cur.fetchall())

        moved, left = 0, []
        cur.execute("select id, target_table, target_pk, legacy_pk, changes, snapshot from app.audit_log order by id")
        for entry_id, table, pk, legacy_pk, changes, snapshot in cur.fetchall():
            if entry_id in TRIAL_ENTRIES:
                continue
            new_pk, new_legacy, new_changes, new_snapshot = pk, legacy_pk, changes, snapshot
            if table in HASHED and pk is not None and legacy_pk is None:
                # The entry keeps the Legacy ID it was written with, so the
                # build can still find its record if the id ever changes.
                new_legacy = pk
                new_pk = ids[table].get(pk)
                if new_pk is None:
                    left.append((entry_id, table, pk))
                    new_pk = pk
            if table == "TrackT" and changes and "EffortID" in changes:
                effort = changes["EffortID"]
                new_changes = dict(changes)
                new_changes["daily_effort_id"] = {
                    "new": int(ids["DailyEffortT"][str(effort["new"])]) if effort.get("new") is not None
                    and str(effort["new"]) in ids["DailyEffortT"] else None,
                    "old": int(ids["DailyEffortT"][str(effort["old"])]) if effort.get("old") is not None
                    and str(effort["old"]) in ids["DailyEffortT"] else None,
                }
            if snapshot:
                new_snapshot = dict(snapshot)
                for name, rows in snapshot.items():
                    if name in HASHED and isinstance(rows, list):
                        new_snapshot[name] = [
                            {"id": int(ids[name][str(r[HASHED[name]])]), **r}
                            if str(r.get(HASHED[name])) in ids[name] else r
                            for r in rows]
            if (new_pk, new_legacy, new_changes, new_snapshot) != (pk, legacy_pk, changes, snapshot):
                cur.execute("update app.audit_log set target_pk = %s, legacy_pk = %s, changes = %s, snapshot = %s "
                            "where id = %s",
                            [new_pk, new_legacy, json.dumps(new_changes) if new_changes is not None else None,
                             json.dumps(new_snapshot) if new_snapshot is not None else None, entry_id])
                moved += 1
        print(f"{moved} audit log entries moved onto the hashed ids")
        for entry_id, table, pk in left:
            print(f"  left as it is: entry {entry_id}, {table} {pk}, which is not in this copy of DB167")

        # The edit-form trial on sighting 114893.
        cur.execute("update app.audit_log set restored_by = null where restored_by = any(%s)", [list(TRIAL_ENTRIES)])
        cur.execute("delete from app.audit_log where id = any(%s)", [list(TRIAL_ENTRIES)])
        print(f"{cur.rowcount} trial entries deleted ({', '.join(map(str, TRIAL_ENTRIES))})")
    conn.commit()


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["inputs", "backup", "audit"])
    parser.add_argument("--from-schema", default="dbo", help="the old dbo")
    parser.add_argument("--build-schema", default="build_next", help="the build with no edits applied, for audit")
    args = parser.parse_args()
    url = os.environ.get("PIPELINE_DATABASE_URL") or os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn:
        if args.step == "inputs":
            inputs(conn, args.from_schema)
            conn.commit()
        elif args.step == "backup":
            backup(conn)
        else:
            audit(conn, args.build_schema, args.from_schema)
    return 0


if __name__ == "__main__":
    sys.exit(main())
